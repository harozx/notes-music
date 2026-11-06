"""Tìm kiếm YouTube bằng yt-dlp, kết quả được cache."""

import yt_dlp
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from .core import cache, extract_sem, get_ydl, once
from .config import (
    SEARCH_TTL, URL_ID_RE, VIDEO_ID_RE,
)


router = APIRouter()


def _search(query: str, limit: int) -> list[dict]:
    m = URL_ID_RE.search(query)
    target = f"https://www.youtube.com/watch?v={m.group(1)}" if m else (
        f"https://www.youtube.com/watch?v={query}" if VIDEO_ID_RE.match(query) else f"ytsearch{limit}:{query}")
    info = get_ydl("search").extract_info(target, download=False)
    entries = info.get("entries") if "entries" in info else [info]
    results = []
    for e in entries or []:
        vid = e.get("id")
        if not vid or not VIDEO_ID_RE.match(vid):
            continue  # bỏ kênh / playlist
        results.append({
            "id": vid,
            "title": e.get("title") or vid,
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
        })
    return results


@router.get("/api/search")
async def search(q: str, limit: int = 20):
    q = " ".join(q.split())
    if not q:
        return []
    limit = max(1, min(limit, 50))
    key = f"{q.lower()}|{limit}"
    if (hit := await cache.get("search", key)) is not None:
        return hit

    async def run():
        async with extract_sem:
            return await run_in_threadpool(_search, q, limit)
    try:
        results = await once("search:" + key, run)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(502, f"Lỗi tìm kiếm: {e}")
    await cache.set("search", key, results, ttl=SEARCH_TTL, l1_ttl=600)
    return results
