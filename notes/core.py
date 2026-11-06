"""Tài nguyên dùng chung: HTTP client, cache 2 lớp, yt-dlp, gộp request trùng."""

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

import httpx
import yt_dlp

from .cache import HybridCache
from .config import COOKIES_FILE, CONN_LIMIT, DATA_DIR, EXTRACT_LIMIT, REDIS_URL

log = logging.getLogger("uvicorn.error")
http: httpx.AsyncClient | None = None    # tạo trong lifespan của notes.main, dùng qua core.http
# cache 2 lớp: L1 RAM + L2 Redis (không có Redis thì SQLite data/cache.db)
cache = HybridCache(REDIS_URL, DATA_DIR / "cache.db", l1_size=int(os.getenv("L1_CACHE_ITEMS", "2000")))

# Ngưỡng chạy đồng thời, xem EXTRACT_LIMIT / CONN_LIMIT trong config.py
extract_sem = asyncio.Semaphore(EXTRACT_LIMIT)
conn_sem = asyncio.Semaphore(CONN_LIMIT)
_tls = threading.local()
inflight: dict[str, asyncio.Future] = {}


def write_json(path: Path, data):
    """Ghi file kiểu atomic: ghi ra file tạm rồi đổi tên, tránh hỏng file khi đang ghi thì tắt máy."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def ydl_opts(**extra) -> dict:
    # deno hoặc node để giải JS challenge (mặc định yt-dlp chỉ bật deno)
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "js_runtimes": {"deno": {}, "node": {}}}
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE
    opts.update(extra)
    return opts


def get_ydl(kind: str) -> yt_dlp.YoutubeDL:
    """Mỗi thread giữ sẵn 1 instance cho mỗi loại (search/audio): dùng lại player JS,
    cookie, visitor data -> nhanh hơn ~40% so với tạo mới mỗi lần."""
    cache = _tls.__dict__.setdefault("ydl", {})
    if kind not in cache:
        if kind == "search":
            cache[kind] = yt_dlp.YoutubeDL(ydl_opts(extract_flat="in_playlist", skip_download=True))
        else:
            cache[kind] = yt_dlp.YoutubeDL(ydl_opts(format="bestaudio[ext=m4a]/bestaudio"))
    return cache[kind]


async def once(key: str, factory):
    """Gộp các request trùng nhau đang chạy thành 1 lần (dedupe)."""
    fut = inflight.get(key)
    if fut:
        return await asyncio.shield(fut)
    fut = asyncio.get_running_loop().create_future()
    inflight[key] = fut
    try:
        result = await factory()
        fut.set_result(result)
        return result
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()  # tránh cảnh báo "exception never retrieved"
        raise
    finally:
        inflight.pop(key, None)
