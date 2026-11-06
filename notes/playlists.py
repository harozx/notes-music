"""Thông tin tài khoản và playlist YouTube của người đang đăng nhập."""

import asyncio
import re

from fastapi import APIRouter, Request

from .auth import yt_api
from .core import cache, once
from .ytmusic import yt_cookie_headers
from .config import (
    PLAYLIST_TTL, YT_WRITE,
)


router = APIRouter()


def _iso_duration(s: str | None) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _track(vid: str, snippet: dict, duration: str | None = None) -> dict:
    return {
        "id": vid,
        "title": snippet.get("title", vid),
        "channel": snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle", ""),
        "duration": _iso_duration(duration),
    }


@router.get("/api/me")
async def me(request: Request):
    return {"email": request.session["email"],
            "yt_personal": bool(yt_cookie_headers()),   # radio cá nhân hoá bằng cookie YouTube
            "yt_write": YT_WRITE}


async def _cached(request: Request, key: str, factory, refresh: bool):
    key = f"{request.session['email']}|{key}"
    if not refresh and (hit := await cache.get("pl", key)) is not None:
        return hit
    value = await once("yt:" + key, factory)
    await cache.set("pl", key, value, ttl=PLAYLIST_TTL)
    return value


@router.get("/api/playlists")
async def playlists(request: Request, refresh: bool = False):
    async def load():
        out = [{"id": "LIKED", "title": "Video đã thích", "count": None, "thumb": None}]
        page = None
        while True:
            data = await yt_api(request, "playlists", part="snippet,contentDetails", mine="true",
                             maxResults=50, **({"pageToken": page} if page else {}))
            for p in data.get("items", []):
                # ảnh bìa playlist là thumbnail của 1 video -> lấy video id để đi qua /api/thumb
                thumb_url = (p["snippet"].get("thumbnails") or {}).get("medium", {}).get("url", "")
                m = re.search(r"/vi/([A-Za-z0-9_-]{11})/", thumb_url)
                out.append({"id": p["id"], "title": p["snippet"]["title"],
                            "count": p["contentDetails"].get("itemCount"),
                            "thumb": m.group(1) if m else None})
            page = data.get("nextPageToken")
            if not page:
                return out
    return await _cached(request, "lists", load, refresh)


@router.get("/api/playlists/{pid}")
async def playlist_items(request: Request, pid: str, limit: int = 500, refresh: bool = False):
    async def load():
        tracks, page = [], None
        if pid == "LIKED":
            while len(tracks) < limit:
                data = await yt_api(request, "videos", part="snippet,contentDetails", myRating="like",
                                 maxResults=50, **({"pageToken": page} if page else {}))
                tracks += [_track(v["id"], v["snippet"], v["contentDetails"].get("duration"))
                           for v in data.get("items", [])]
                page = data.get("nextPageToken")
                if not page:
                    break
            return tracks[:limit]

        # 1) lấy danh sách item theo trang (bắt buộc tuần tự vì cần pageToken)
        items = []
        while len(items) < limit:
            data = await yt_api(request, "playlistItems", part="snippet,contentDetails",
                             playlistId=pid, maxResults=50, **({"pageToken": page} if page else {}))
            items += [i for i in data.get("items", [])
                      if i["snippet"].get("title") not in ("Deleted video", "Private video")]
            page = data.get("nextPageToken")
            if not page:
                break
        items = items[:limit]
        # 2) lấy thời lượng: chia thành lô 50 id, gọi song song (tối đa 4 lô cùng lúc)
        ids = [i["contentDetails"]["videoId"] for i in items]
        sem = asyncio.Semaphore(4)

        async def batch(chunk):
            async with sem:
                vd = await yt_api(request, "videos", part="contentDetails", id=",".join(chunk), maxResults=50)
                return {v["id"]: v["contentDetails"].get("duration") for v in vd.get("items", [])}
        durations = {}
        for d in await asyncio.gather(*(batch(ids[k:k + 50]) for k in range(0, len(ids), 50))):
            durations.update(d)
        # video không trả về trong videos.list = đã xóa/riêng tư -> bỏ
        return [_track(i["contentDetails"]["videoId"], i["snippet"], durations[i["contentDetails"]["videoId"]])
                for i in items if i["contentDetails"]["videoId"] in durations]
    return await _cached(request, f"pl:{pid}:{limit}", load, refresh)
