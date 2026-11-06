"""Ảnh bìa và audio: tải song song theo đoạn, dự phòng yt-dlp, lưu cache đĩa."""

import asyncio
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from . import core
from .core import cache, conn_sem, extract_sem, get_ydl, inflight, log, once, ydl_opts
from .config import (
    CACHE_DIR, CACHE_MAX_MB, ERROR_TTL, MAX_DURATION,
    MEDIA_TYPES, MIN_SEGMENT, SEGMENTS, TEMP_SUFFIXES, VIDEO_ID_RE,
)


router = APIRouter()


THUMB_DIR = CACHE_DIR / "thumbs"
THUMB_DIR.mkdir(exist_ok=True)


class _SegmentError(RuntimeError):
    """Lỗi khi tải các đoạn từ googlevideo (khác lỗi phân tích video)."""


@router.get("/api/thumb/{vid}")
async def thumb(vid: str):
    if not VIDEO_ID_RE.match(vid):
        raise HTTPException(400)
    headers = {"Cache-Control": "public, max-age=2592000, immutable"}
    path = THUMB_DIR / f"{vid}.jpg"
    if path.exists():
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    async def fetch():
        for name in ("mqdefault.jpg", "hqdefault.jpg", "default.jpg"):
            r = await core.http.get(f"https://i.ytimg.com/vi/{vid}/{name}")
            if r.status_code == 200:
                path.write_bytes(r.content)
                return r.content
        return None
    data = await once("thumb:" + vid, fetch)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/jpeg", headers=headers)


def _cached_file(vid: str) -> Path | None:
    for p in CACHE_DIR.glob(f"{vid}.*"):
        if p.is_file() and not p.name.endswith(TEMP_SUFFIXES):
            return p
    return None


def _extract_stream(vid: str) -> dict:
    info = get_ydl("audio").extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    if (info.get("duration") or 0) > MAX_DURATION:
        raise RuntimeError("Video quá dài")
    q = parse_qs(urlparse(info["url"]).query)
    expire = int(q.get("expire", [time.time() + 3600])[0])
    return {"url": info["url"], "headers": info.get("http_headers", {}), "ext": info.get("ext", "m4a"),
            "size": info.get("filesize") or info.get("filesize_approx"), "expire": expire}


async def _stream_info(vid: str) -> dict:
    if (hit := await cache.get("stream", vid)) is not None:
        return hit

    async def run():
        async with extract_sem:
            return await run_in_threadpool(_extract_stream, vid)
    info = await once("extract:" + vid, run)
    # link googlevideo có hạn (expire) -> chỉ cache tới trước lúc hết hạn 5 phút
    await cache.set("stream", vid, info, ttl=max(60, info["expire"] - time.time() - 300))
    return info


async def _fetch_range(info: dict, start: int, end: int, f, retries: int = 3):
    """Tải 1 đoạn [start, end] và ghi đúng vị trí trong file."""
    for attempt in range(retries):
        try:
            async with conn_sem:
                async with core.http.stream("GET", info["url"], timeout=30,
                                        headers={**info["headers"], "Range": f"bytes={start}-{end}"}) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"googlevideo HTTP {r.status_code}")
                    pos = start
                    async for chunk in r.aiter_bytes(256 * 1024):
                        f.seek(pos)
                        f.write(chunk)
                        pos += len(chunk)
                    if pos != end + 1:
                        raise RuntimeError("thiếu dữ liệu")
                    return
        except Exception:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


async def _parallel_download(vid: str) -> Path:
    """Chia để trị: chia file thành SEGMENTS đoạn, tải đồng thời (trong ngưỡng CONN_LIMIT)."""
    info = await _stream_info(vid)
    size = info["size"]
    if not size:
        r = await core.http.head(info["url"], headers=info["headers"])
        size = int(r.headers.get("content-length", 0))
    if not size:
        raise _SegmentError("không biết kích thước file")
    parts = max(1, min(SEGMENTS, size // MIN_SEGMENT))
    step = -(-size // parts)
    tmp = CACHE_DIR / f"{vid}.{info['ext']}.part"
    try:
        with open(tmp, "wb") as f:
            f.truncate(size)
            await asyncio.gather(*(_fetch_range(info, s, min(s + step, size) - 1, f)
                                   for s in range(0, size, step)))
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise _SegmentError(str(e)) from e
    final = CACHE_DIR / f"{vid}.{info['ext']}"
    os.replace(tmp, final)
    return final


def _ytdlp_download(vid: str) -> Path:
    """Dự phòng: để yt-dlp tự tải nếu cách song song lỗi (403, URL hết hạn...)."""
    opts = ydl_opts(format="bestaudio[ext=m4a]/bestaudio", outtmpl=str(CACHE_DIR / "%(id)s.%(ext)s"),
                     match_filter=yt_dlp.utils.match_filter_func(f"duration < {MAX_DURATION}"))
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={vid}"])
    path = _cached_file(vid)
    if not path:
        raise RuntimeError("Không tải được (video quá dài, bị chặn vùng hoặc yêu cầu đăng nhập)")
    return path


def _evict():
    files = [p for p in CACHE_DIR.iterdir() if p.is_file() and not p.name.endswith(TEMP_SUFFIXES)]
    total = sum(p.stat().st_size for p in files)
    limit = CACHE_MAX_MB * 1024 * 1024
    for p in sorted(files, key=lambda p: p.stat().st_mtime):  # cũ nhất trước
        if total <= limit:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)


async def _ensure(vid: str) -> Path:
    if not VIDEO_ID_RE.match(vid):
        raise HTTPException(400, "ID không hợp lệ")
    if (err := await cache.get("err", vid)) is not None:
        raise HTTPException(502, err)
    path = _cached_file(vid)
    if path is None:
        async def fill():
            t = time.perf_counter()
            try:
                p = await _parallel_download(vid)
                how = "song song"
            except _SegmentError as e:
                log.warning("tải song song %s lỗi (%s), dùng yt-dlp", vid, e)
                await cache.delete("stream", vid)
                async with extract_sem:
                    p = await run_in_threadpool(_ytdlp_download, vid)
                how = "yt-dlp"
            except (yt_dlp.utils.DownloadError, RuntimeError) as e:
                # lỗi ở bước phân tích (video không tồn tại, riêng tư, quá dài...): thử lại cũng vô ích
                await cache.set("err", vid, str(e).replace("ERROR: ", ""), ttl=ERROR_TTL)
                raise
            except Exception as e:
                log.warning("tải song song %s lỗi (%s), dùng yt-dlp", vid, e)
                await cache.delete("stream", vid)
                async with extract_sem:
                    p = await run_in_threadpool(_ytdlp_download, vid)
                how = "yt-dlp"
            log.info("tải %s (%s) %.2fs %.1fMB", vid, how, time.perf_counter() - t, p.stat().st_size / 1e6)
            await run_in_threadpool(_evict)
            return p
        try:
            path = await once("audio:" + vid, fill)
        except Exception as e:
            raise HTTPException(502, str(e))
    os.utime(path)  # đánh dấu mới dùng cho LRU
    return path


@router.get("/api/audio/{vid}")
async def audio(vid: str):
    path = await _ensure(vid)
    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/api/prefetch")
async def prefetch(ids: list[str]):
    """Tải trước các bài kế tiếp; chạy nền, vẫn bị giới hạn bởi các semaphore."""
    for vid in ids[:5]:
        if VIDEO_ID_RE.match(vid) and not _cached_file(vid) and "audio:" + vid not in inflight:
            asyncio.create_task(_safe_ensure(vid))
    return {"ok": True}


async def _safe_ensure(vid: str):
    try:
        await _ensure(vid)
    except Exception:
        pass
