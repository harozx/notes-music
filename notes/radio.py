"""Gu nghe nhạc theo tài khoản, radio cá nhân hoá, Mix dành riêng và ghi nhận hành vi nghe."""

import asyncio
import json
import random
import threading

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from . import core
from .auth import access_token
from .core import cache, log, write_json
from .playlists import playlist_items
from .ytmusic import raw_radio
from .config import (
    FORYOU_TTL, TASTE_FILE, VIDEO_ID_RE, YT_API, YT_WRITE,
)


router = APIRouter()


#
# Mỗi tài khoản có 1 hồ sơ nhỏ lưu ở data/taste.json, học từ hành vi trong app:
#   nghe hết bài (+), bỏ qua sớm (-), bấm ♥ (++), "không thích" (chặn bài).
# Hồ sơ này + "Video đã thích" trên YouTube được dùng để sắp xếp lại danh sách radio.

_taste_lock = threading.Lock()
RECENT_MAX = 300


def _load_taste_all() -> dict:
    try:
        return json.loads(TASTE_FILE.read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _taste(email: str) -> dict:
    t = _load_taste_all().get(email) or {}
    for k in ("liked", "plays", "skips", "channels", "blocked"):
        t.setdefault(k, {})
    t.setdefault("recent", [])
    return t


def _update_taste(email: str, fn):
    with _taste_lock:
        data = _load_taste_all()
        t = data.get(email) or {}
        for k in ("liked", "plays", "skips", "channels", "blocked"):
            t.setdefault(k, {})
        t.setdefault("recent", [])
        fn(t)
        data[email] = t
        write_json(TASTE_FILE, data)
        return t


def _ch_key(name: str) -> str:
    return " ".join((name or "").lower().replace(" - topic", "").split())


async def _yt_liked(request: Request) -> list[dict]:
    """'Video đã thích' trên YouTube (nếu đăng nhập Google), dùng cache playlist sẵn có."""
    if request.session.get("email") == "local":
        return []
    try:
        return await playlist_items(request, "LIKED", limit=500, refresh=False)  # cùng cache với giao diện
    except HTTPException:
        return []


def _is_song(t: dict) -> bool:
    d = t.get("duration")
    return not d or 60 <= d <= 900


def _personalize(cands: list[dict], taste: dict, liked_pool: list[dict], exclude: set[str],
                 seed_channels: set[str], inject: bool = True, limit: int = 40) -> list[dict]:
    """Sắp xếp lại gợi ý theo gu: giữ phần lớn thứ tự của YouTube, cộng điểm kênh/bài hay nghe,
    trừ điểm bài hay bỏ qua, chèn vài bài 'đã thích' hợp gu, và tránh 2 bài cùng kênh liền nhau."""
    recent = taste["recent"][-60:]
    recent_set = set(recent)
    liked_ids = set(taste["liked"]) | {t["id"] for t in liked_pool}
    chan = taste["channels"]
    n = max(len(cands), 1)
    scored, seen = [], set(exclude)

    for pos, t in enumerate(cands):
        vid = t["id"]
        if vid in seen or vid in taste["blocked"] or taste["skips"].get(vid, 0) >= 3:
            continue
        seen.add(vid)
        s = 1.0 - 0.6 * pos / n                                   # thứ tự gốc của YouTube
        s += 0.06 * max(-5.0, min(5.0, chan.get(_ch_key(t["channel"]), 0)))  # kênh bạn hay nghe
        s -= 0.25 * taste["skips"].get(vid, 0)                    # bài bạn hay bỏ qua
        if vid in liked_ids:
            s += 0.25
        if vid in recent_set:                                     # vừa nghe xong -> để sau
            s -= 0.5
        scored.append((s + random.uniform(0, 0.05), {**t, "why": "liked" if vid in liked_ids else "yt"}))

    if inject and liked_pool:
        # chèn bài bạn đã thích có cùng nghệ sĩ với seed / các gợi ý, không vừa nghe gần đây
        cand_ch = seed_channels | {_ch_key(t["channel"]) for _, t in scored}
        fav = [t for t in liked_pool if t["id"] not in seen and t["id"] not in recent_set
               and t["id"] not in taste["blocked"] and _is_song(t)]
        same = [t for t in fav if _ch_key(t["channel"]) in cand_ch]
        others = [t for t in fav if _ch_key(t["channel"]) not in cand_ch]
        random.shuffle(same)
        random.shuffle(others)
        k = max(2, len(scored) // 6)
        for t in (same + others[:2])[:k]:
            seen.add(t["id"])
            scored.append((0.55 + random.uniform(0, 0.35), {**t, "why": "fav"}))

    out = [t for _, t in sorted(scored, key=lambda x: -x[0])]
    # đa dạng: tránh 2 bài cùng kênh liền nhau
    for i in range(1, len(out)):
        if _ch_key(out[i]["channel"]) == _ch_key(out[i - 1]["channel"]):
            for j in range(i + 1, len(out)):
                if _ch_key(out[j]["channel"]) != _ch_key(out[i - 1]["channel"]):
                    out[i], out[j] = out[j], out[i]
                    break
    return out[:limit]


def _ids(s: str) -> set[str]:
    return {x for x in s.split(",") if VIDEO_ID_RE.match(x)}


@router.get("/api/radio/{vid}")
async def radio(request: Request, vid: str, personal: bool = True, exclude: str = ""):
    """Bài tiếp theo: radio YouTube Music từ bài vid, đã sắp xếp lại theo gu của người dùng."""
    if not VIDEO_ID_RE.match(vid):
        raise HTTPException(400, "video id không hợp lệ")
    try:
        cands = await raw_radio(vid)
    except httpx.HTTPError as e:
        cands = []
        log.warning("lỗi lấy radio %s: %s", vid, e)
    if not personal:
        if not cands:
            raise HTTPException(502, "Lỗi lấy gợi ý")
        return cands
    email = request.session["email"]
    taste = _taste(email)
    liked = [t for t in await _yt_liked(request) if _is_song(t)] + list(taste["liked"].values())
    seed = next((t for t in liked if t["id"] == vid), None)
    seed_ch = {_ch_key(seed["channel"])} if seed else set()
    out = _personalize(cands, taste, liked, _ids(exclude) | {vid}, seed_ch)
    if not out:
        raise HTTPException(502, "Lỗi lấy gợi ý")
    return out


@router.get("/api/foryou")
async def foryou(request: Request, refresh: bool = False):
    """'Dành riêng cho bạn': trộn radio của vài bài bạn thích/nghe nhiều nhất, sắp theo gu."""
    email = request.session["email"]
    if not refresh and (hit := await cache.get("foryou", email)) is not None:
        return hit
    taste = _taste(email)
    yt_liked = [t for t in await _yt_liked(request) if _is_song(t)]
    local_liked = list(taste["liked"].values())
    top_played = sorted(taste["plays"], key=lambda v: -taste["plays"][v])[:10]
    # bài gốc: ưu tiên bài ♥ trong app và bài nghe nhiều, sau đó tới video đã thích trên YouTube
    mine = local_liked[-10:] + [{"id": v} for v in top_played]
    random.shuffle(mine)
    yt_pool = yt_liked[:40]
    random.shuffle(yt_pool)
    seeds, seen = [], set()
    for t in mine[:2] + yt_pool + mine[2:]:
        if t["id"] not in seen and t["id"] not in taste["blocked"]:
            seen.add(t["id"])
            seeds.append(t["id"])
        if len(seeds) == 3:
            break
    if not seeds:
        return {"seeds": [], "tracks": []}
    radios = await asyncio.gather(*(raw_radio(s) for s in seeds), return_exceptions=True)
    radios = [r for r in radios if isinstance(r, list)]
    # trộn xen kẽ (round-robin) để mix không bị nghiêng về 1 bài gốc
    merged, k = [], 0
    while any(k < len(r) for r in radios):
        merged += [r[k] for r in radios if k < len(r)]
        k += 1
    tracks = _personalize(merged, taste, yt_liked + local_liked, set(), set(), limit=50)
    res = {"seeds": seeds, "tracks": tracks}
    if tracks:
        await cache.set("foryou", email, res, ttl=FORYOU_TTL)
    return res


@router.get("/api/taste")
async def taste_get(request: Request):
    t = _taste(request.session["email"])
    return {"liked": list(t["liked"]), "blocked": list(t["blocked"]),
            "plays": sum(t["plays"].values()), "skips": sum(t["skips"].values()),
            "top_channels": sorted(t["channels"], key=lambda c: -t["channels"][c])[:8]}


@router.post("/api/feedback")
async def feedback(request: Request):
    """Ghi nhận hành vi nghe: finish | skip | like | unlike | dislike."""
    body = await request.json()
    tr, ev = body.get("track") or {}, body.get("event")
    vid = tr.get("id", "")
    if not VIDEO_ID_RE.match(vid) or ev not in ("finish", "skip", "like", "unlike", "dislike"):
        raise HTTPException(400, "dữ liệu không hợp lệ")
    track = {"id": vid, "title": str(tr.get("title", ""))[:200], "channel": str(tr.get("channel", ""))[:120],
             "duration": tr.get("duration") if isinstance(tr.get("duration"), (int, float)) else None}
    ch = _ch_key(track["channel"])

    def apply(t):
        bump = {"finish": 1.0, "skip": -0.5, "like": 3.0, "unlike": -3.0, "dislike": -2.0}[ev]
        if ch:
            t["channels"][ch] = round(t["channels"].get(ch, 0) + bump, 2)
        if ev == "finish":
            t["plays"][vid] = t["plays"].get(vid, 0) + 1
        elif ev == "skip":
            t["skips"][vid] = t["skips"].get(vid, 0) + 1
        elif ev == "like":
            t["liked"][vid] = track
            t["blocked"].pop(vid, None)
            t["skips"].pop(vid, None)
        elif ev == "unlike":
            t["liked"].pop(vid, None)
        elif ev == "dislike":
            t["blocked"][vid] = track
            t["liked"].pop(vid, None)
        if ev in ("finish", "skip"):
            t["recent"] = [x for x in t["recent"] if x != vid][-RECENT_MAX + 1:] + [vid]
        # gọn file: giữ tối đa 2000 mục mỗi loại
        for k in ("plays", "skips", "channels"):
            if len(t[k]) > 2000:
                t[k] = dict(sorted(t[k].items(), key=lambda kv: -abs(kv[1]))[:1500])
    email = request.session["email"]
    await run_in_threadpool(_update_taste, email, apply)
    if ev in ("like", "dislike"):
        await cache.delete("foryou", email)

    synced = None
    if ev in ("like", "unlike", "dislike") and YT_WRITE and email != "local":
        # đồng bộ lên YouTube để chính YouTube cũng học gu của bạn
        try:
            token = await access_token(email)
            r = await core.http.post(f"{YT_API}/videos/rate", headers={"Authorization": f"Bearer {token}"},
                                 params={"id": vid, "rating": {"like": "like", "unlike": "none",
                                                               "dislike": "dislike"}[ev]})
            synced = r.status_code == 204
            if synced:
                await cache.delete_prefix("pl", f"{email}|pl:LIKED")
            else:
                log.warning("rate %s lỗi: %s", vid, r.text[:200])
        except HTTPException:
            synced = False
    return {"ok": True, "youtube": synced}
