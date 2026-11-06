"""Gọi API nội bộ của YouTube Music: radio theo bài và đăng nhập bằng cookie YouTube."""

import hashlib
import http.cookiejar
import time
from pathlib import Path

from . import core
from .core import cache, log, once
from .config import (
    COOKIES_FILE, DATA_DIR, RADIO_TTL, VIDEO_ID_RE,
)


def _runs(o: dict | None) -> str:
    return "".join(r.get("text", "") for r in (o or {}).get("runs", []))


def _secs(s: str) -> int | None:
    try:
        n = 0
        for part in s.split(":"):
            n = n * 60 + int(part)
        return n
    except ValueError:
        return None


def _walk(o, key):
    if isinstance(o, dict):
        if key in o:
            yield o[key]
        for v in o.values():
            yield from _walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key)


YTM_ORIGIN = "https://music.youtube.com"
_cookie_state: dict = {"mtime": None, "cookies": {}}


def _cookies_path() -> Path | None:
    """File cookies.txt (định dạng Netscape) của tài khoản YouTube: COOKIES_FILE hoặc data/cookies.txt."""
    for p in (COOKIES_FILE, DATA_DIR / "cookies.txt"):
        if p and Path(p).is_file():
            return Path(p)
    return None


def yt_cookie_headers() -> dict:
    """Header đăng nhập YouTube Music từ cookie (SAPISIDHASH) -> radio được cá nhân hoá theo đúng
    lịch sử nghe / lượt thích của tài khoản YouTube đó. Không có cookie thì trả {} (radio ẩn danh)."""
    path = _cookies_path()
    if not path:
        return {}
    mtime = path.stat().st_mtime
    if _cookie_state["mtime"] != mtime:  # chỉ đọc lại khi file đổi
        jar = http.cookiejar.MozillaCookieJar()
        try:
            jar.load(str(path), ignore_discard=True, ignore_expires=True)
            _cookie_state["cookies"] = {c.name: c.value for c in jar if c.domain.endswith("youtube.com")}
        except (OSError, http.cookiejar.LoadError) as e:
            log.warning("không đọc được cookies %s: %s", path, e)
            _cookie_state["cookies"] = {}
        _cookie_state["mtime"] = mtime
    ck = _cookie_state["cookies"]
    sapisid = ck.get("SAPISID") or ck.get("__Secure-3PAPISID")
    if not sapisid:
        return {}
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid} {YTM_ORIGIN}".encode()).hexdigest()
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in ck.items()),
            "Authorization": f"SAPISIDHASH {ts}_{digest}",
            "X-Goog-AuthUser": "0", "X-Origin": YTM_ORIGIN}


async def raw_radio(vid: str) -> list[dict]:
    """Danh sách bài gợi ý giống "Radio" của YouTube Music (~25-50 bài) bắt đầu từ bài vid.
    Có cookie YouTube thì gọi dưới danh nghĩa tài khoản đó (gợi ý theo gu thật của người dùng)."""
    auth = yt_cookie_headers()
    key = ("me:" if auth else "anon:") + vid
    if (hit := await cache.get("radio", key)) is not None:
        return hit

    async def run():
        body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20251001.01.00",
                                       "hl": "vi", "gl": "VN"}},
                "videoId": vid, "playlistId": "RDAMVM" + vid, "isAudioOnly": True}
        url = f"{YTM_ORIGIN}/youtubei/v1/next?prettyPrint=false"
        r = await core.http.post(url, json=body, headers={"Origin": YTM_ORIGIN, **auth})
        if auth and r.status_code in (400, 401, 403):  # cookie hết hạn -> vẫn phát được bằng radio ẩn danh
            log.warning("cookie YouTube bị từ chối (%s), dùng radio ẩn danh", r.status_code)
            r = await core.http.post(url, json=body, headers={"Origin": YTM_ORIGIN})
        r.raise_for_status()
        out, seen = [], {vid}
        for it in _walk(r.json(), "playlistPanelVideoRenderer"):
            v = it.get("videoId")
            if not v or v in seen or not VIDEO_ID_RE.match(v):
                continue
            seen.add(v)
            out.append({"id": v, "title": _runs(it.get("title")) or v,
                        "channel": _runs(it.get("longBylineText") or it.get("shortBylineText")).split(" • ")[0],
                        "duration": _secs(_runs(it.get("lengthText")))})
        return out
    tracks = await once("radio:" + key, run)
    if tracks:
        await cache.set("radio", key, tracks, ttl=RADIO_TTL, l1_ttl=1800)
    return tracks
