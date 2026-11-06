"""Server trung gian nghe nhạc YouTube.

Đăng nhập bằng tài khoản Google để xem playlist YouTube của mình.
Trình duyệt chỉ nói chuyện với server này (và accounts.google.com lúc đăng nhập);
server tự tìm kiếm, gọi YouTube API, tải audio (yt-dlp) và thumbnail rồi trả lại.
"""

import asyncio
import hashlib
import http.cookiejar
import json
import random
import os
import re
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from cache import HybridCache

BASE_DIR = Path(__file__).parent

try:  # đọc cấu hình từ D:\music\.env nếu có
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass
CACHE_DIR = Path(os.getenv("CACHE_DIR", BASE_DIR / "cache"))
CACHE_MAX_MB = int(os.getenv("CACHE_MAX_MB", "2000"))
MAX_DURATION = int(os.getenv("MAX_DURATION", str(3 * 3600)))  # giây
COOKIES_FILE = os.getenv("COOKIES_FILE", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAILS = {e.strip().lower() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()}
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "")
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
TOKENS_FILE = DATA_DIR / "tokens.json"
TASTE_FILE = DATA_DIR / "taste.json"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "180"))      # phiên đăng nhập trượt: dùng web là tự gia hạn
SESSION_COOKIE = os.getenv("SESSION_COOKIE", "notes_session")
REDIS_URL = os.getenv("REDIS_URL", "").strip()
# YT_WRITE=1: xin thêm quyền ghi để nút ♥ trong app bấm "Thích" luôn trên YouTube
# (giúp chính YouTube gợi ý đúng gu hơn). Đổi xong phải đăng nhập Google lại.
YT_WRITE = os.getenv("YT_WRITE", "").lower() in ("1", "true", "yes")
GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/youtube" + ("" if YT_WRITE else ".readonly")
YT_API = "https://www.googleapis.com/youtube/v3"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _session_secret() -> str:
    """Khoá ký cookie phải CỐ ĐỊNH, nếu không mỗi lần restart server mọi người bị đăng xuất.
    Không đặt SESSION_SECRET thì tự sinh 1 lần rồi lưu vào data/session_secret."""
    env = (os.getenv("SESSION_SECRET") or "").strip()
    if env:
        return env
    f = DATA_DIR / "session_secret"
    try:
        saved = f.read_text("utf-8").strip()
    except OSError:
        saved = ""
    if not saved:
        saved = secrets.token_hex(32)
        f.write_text(saved, "utf-8")
    return saved


SESSION_SECRET = _session_secret()

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
URL_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")
MEDIA_TYPES = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm",
               ".opus": "audio/ogg", ".mp3": "audio/mpeg"}

log = logging.getLogger("uvicorn.error")
_http: httpx.AsyncClient | None = None
# cache 2 lớp: L1 RAM + L2 Redis (không có Redis thì SQLite data/cache.db)
cache = HybridCache(REDIS_URL, DATA_DIR / "cache.db", l1_size=int(os.getenv("L1_CACHE_ITEMS", "2000")))


@asynccontextmanager
async def lifespan(_app):
    global _http
    # giữ kết nối keep-alive tới Google để không phải bắt tay TLS lại mỗi request
    _http = httpx.AsyncClient(timeout=15, follow_redirects=True,
                              limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
    await cache.start()
    yield
    await cache.close()
    await _http.aclose()


app = FastAPI(title="music-proxy", docs_url=None, redoc_url=None, lifespan=lifespan)


def _ydl_opts(**extra) -> dict:
    # deno hoặc node để giải JS challenge (mặc định yt-dlp chỉ bật deno)
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "js_runtimes": {"deno": {}, "node": {}}}
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE
    opts.update(extra)
    return opts


# ---------------------------------------------------------------- auth

PUBLIC_PATHS = ("/auth/", "/login.html", "/favicon.ico", "/img/")


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if not path.startswith(PUBLIC_PATHS) and not request.session.get("email"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Chưa đăng nhập", "code": "login"}, status_code=401)
        return RedirectResponse("/login.html")
    if request.session.get("email") and time.time() - request.session.get("t", 0) > 86400:
        # Starlette chỉ gửi lại cookie khi session thay đổi -> mỗi ngày "chạm" 1 lần để gia hạn
        # thêm SESSION_DAYS ngày (phiên trượt: còn dùng web thì không bao giờ bị đăng xuất)
        request.session["t"] = int(time.time())
    return await call_next(request)


# SessionMiddleware thêm sau nên chạy bọc ngoài require_login.
# - Tên cookie riêng (notes_session): tránh đụng cookie "session" của web khác cùng domain (*.youv.dev)
#   -> trình duyệt gửi 2 cookie trùng tên, server đọc nhầm cái kia và coi như chưa đăng nhập.
# - Phiên trượt: mỗi response đều gia hạn cookie thêm SESSION_DAYS ngày.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, session_cookie=SESSION_COOKIE,
                   max_age=SESSION_DAYS * 86400, same_site="lax", https_only=BASE_URL.startswith("https"))


def _load_tokens() -> dict:
    try:
        return json.loads(TOKENS_FILE.read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _write_json(path: Path, data):
    """Ghi file kiểu atomic: ghi ra file tạm rồi đổi tên, tránh hỏng file khi đang ghi thì tắt máy."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def _save_tokens(data: dict):
    _write_json(TOKENS_FILE, data)


HINT_COOKIE = "notes_hint"   # nhớ email Google lần trước (1 năm) để lần sau đăng nhập chỉ 1 chạm


class GoogleReauth(HTTPException):
    """Token Google hết hạn/bị thu hồi. KHÁC với "chưa đăng nhập": phiên web vẫn còn,
    nghe nhạc/tìm kiếm vẫn chạy, chỉ phần playlist cần bấm "Kết nối lại Google"."""

    def __init__(self, msg: str = "Kết nối Google đã hết hạn, bấm \"Kết nối lại\" để xem playlist"):
        super().__init__(403, msg)


@app.exception_handler(GoogleReauth)
async def _google_reauth_handler(_request: Request, exc: GoogleReauth):
    return JSONResponse({"detail": exc.detail, "code": "google_reauth"}, status_code=403)


@app.get("/auth/config")
async def auth_config(request: Request):
    return {"google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET), "password": bool(LOGIN_PASSWORD),
            "hint": request.cookies.get(HINT_COOKIE, ""),            # email lần trước của chính trình duyệt này
            "logged_in": bool(request.session.get("email"))}


@app.get("/auth/login")
async def auth_login(request: Request, consent: bool = False, other: bool = False):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Chưa cấu hình GOOGLE_CLIENT_ID")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    hint = "" if other else request.cookies.get(HINT_COOKIE, "")   # other=1: chọn tài khoản khác
    entry = _load_tokens().get(hint, {})
    # Chỉ bắt màn hình "cấp quyền" khi thật sự cần refresh_token mới; còn lại chỉ chọn tài khoản (1 chạm)
    need_consent = consent or not entry.get("refresh_token") or entry.get("refresh_dead")
    request.session["oauth_consent"] = bool(need_consent)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BASE_URL}/auth/callback",
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "select_account consent" if need_consent else "select_account",
        "state": state,
    }
    if hint:
        params["login_hint"] = hint
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


async def _refresh_ok(refresh_token: str) -> dict | None:
    r = await _http.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token, "grant_type": "refresh_token"})
    return r.json() if r.status_code == 200 else None


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/login.html?error={quote(error)}")
    if not state or state != request.session.pop("oauth_state", None):
        return RedirectResponse("/login.html?error=state")
    asked_consent = request.session.pop("oauth_consent", True)
    r = await _http.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{BASE_URL}/auth/callback",
        "grant_type": "authorization_code",
    })
    if r.status_code != 200:
        return RedirectResponse("/login.html?error=token")
    tok = r.json()
    info = (await _http.get("https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": f"Bearer {tok['access_token']}"})).json()
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or (ALLOWED_EMAILS and email not in ALLOWED_EMAILS):
        return RedirectResponse("/login.html?error=forbidden")
    tokens = _load_tokens()
    entry = tokens.get(email, {})
    if tok.get("refresh_token"):
        entry["refresh_token"] = tok["refresh_token"]
        entry.pop("refresh_dead", None)
    elif not asked_consent and (not entry.get("refresh_token") or not await _refresh_ok(entry["refresh_token"])):
        # refresh_token cũ đã chết mà Google không cấp cái mới -> xin lại quyền đúng 1 lần
        resp = RedirectResponse("/auth/login?consent=1")
        resp.set_cookie(HINT_COOKIE, email, max_age=365 * 86400, httponly=True, samesite="lax",
                        secure=BASE_URL.startswith("https"))
        return resp
    else:
        entry.pop("refresh_dead", None)
    entry.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
    tokens[email] = entry
    _save_tokens(tokens)
    request.session.clear()
    request.session["email"] = email
    request.session["since"] = int(time.time())
    resp = RedirectResponse("/")
    resp.set_cookie(HINT_COOKIE, email, max_age=365 * 86400, httponly=True, samesite="lax",
                    secure=BASE_URL.startswith("https"))
    return resp


@app.post("/auth/password")
async def auth_password(request: Request):
    """Đăng nhập dự phòng bằng mật khẩu (không có playlist Google)."""
    form = await request.form()
    pwd = str(form.get("password", ""))
    if not LOGIN_PASSWORD or not secrets.compare_digest(pwd, LOGIN_PASSWORD):
        await asyncio.sleep(1)  # làm chậm dò mật khẩu
        return RedirectResponse("/login.html?error=password", status_code=303)
    request.session.clear()
    request.session["email"] = "local"
    request.session["since"] = int(time.time())
    return RedirectResponse("/", status_code=303)


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login.html")   # giữ cookie gợi ý email để lần sau đăng nhập 1 chạm


async def _access_token(email: str) -> str:
    tokens = _load_tokens()
    entry = tokens.get(email)
    if not entry:
        raise HTTPException(403, "Chưa liên kết tài khoản Google, hãy đăng nhập bằng Google để xem playlist")
    if entry.get("expires_at", 0) > time.time():
        return entry["access_token"]
    if entry.get("refresh_dead") or not entry.get("refresh_token"):
        raise GoogleReauth()   # đã biết là chết -> khỏi gọi Google mỗi request

    async def refresh():
        return await _refresh_ok(entry["refresh_token"])
    tok = await _once("refresh:" + email, refresh)   # nhiều request cùng lúc chỉ refresh 1 lần
    tokens = _load_tokens()
    entry = tokens.get(email, entry)
    if not tok:
        # Google thu hồi refresh_token (app ở chế độ Testing: 7 ngày/lần, hoặc bạn gỡ quyền)
        entry["refresh_dead"] = True
        tokens[email] = entry
        _save_tokens(tokens)
        log.warning("refresh token Google của %s đã hết hạn", email)
        raise GoogleReauth()
    entry.update(access_token=tok["access_token"], expires_at=time.time() + tok.get("expires_in", 3600) - 60)
    tokens[email] = entry
    _save_tokens(tokens)
    return entry["access_token"]


async def _yt(request: Request, endpoint: str, **params) -> dict:
    token = await _access_token(request.session["email"])
    r = await _http.get(f"{YT_API}/{endpoint}", params=params, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 401:     # token bị Google từ chối -> cần kết nối lại, KHÔNG đá ra trang đăng nhập
        raise GoogleReauth()
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code in (403, 404) else 502,
                            r.json().get("error", {}).get("message", "Lỗi YouTube API"))
    return r.json()


# ---------------------------------------------------------------- tài khoản / playlist

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


@app.get("/api/me")
async def me(request: Request):
    return {"email": request.session["email"],
            "yt_personal": bool(_yt_cookie_headers()),   # radio cá nhân hoá bằng cookie YouTube
            "yt_write": YT_WRITE}


async def _cached(request: Request, key: str, factory, refresh: bool):
    key = f"{request.session['email']}|{key}"
    if not refresh and (hit := await cache.get("pl", key)) is not None:
        return hit
    value = await _once("yt:" + key, factory)
    await cache.set("pl", key, value, ttl=PLAYLIST_TTL)
    return value


@app.get("/api/playlists")
async def playlists(request: Request, refresh: bool = False):
    async def load():
        out = [{"id": "LIKED", "title": "Video đã thích", "count": None, "thumb": None}]
        page = None
        while True:
            data = await _yt(request, "playlists", part="snippet,contentDetails", mine="true",
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


@app.get("/api/playlists/{pid}")
async def playlist_items(request: Request, pid: str, limit: int = 500, refresh: bool = False):
    async def load():
        tracks, page = [], None
        if pid == "LIKED":
            while len(tracks) < limit:
                data = await _yt(request, "videos", part="snippet,contentDetails", myRating="like",
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
            data = await _yt(request, "playlistItems", part="snippet,contentDetails",
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
                vd = await _yt(request, "videos", part="contentDetails", id=",".join(chunk), maxResults=50)
                return {v["id"]: v["contentDetails"].get("duration") for v in vd.get("items", [])}
        durations = {}
        for d in await asyncio.gather(*(batch(ids[k:k + 50]) for k in range(0, len(ids), 50))):
            durations.update(d)
        # video không trả về trong videos.list = đã xóa/riêng tư -> bỏ
        return [_track(i["contentDetails"]["videoId"], i["snippet"], durations[i["contentDetails"]["videoId"]])
                for i in items if i["contentDetails"]["videoId"] in durations]
    return await _cached(request, f"pl:{pid}:{limit}", load, refresh)



# ---------------------------------------------------------------- yt-dlp dùng chung

# Ngưỡng: số lần phân tích yt-dlp và số kết nối googlevideo chạy cùng lúc
EXTRACT_LIMIT = int(os.getenv("EXTRACT_LIMIT", "3"))
CONN_LIMIT = int(os.getenv("CONN_LIMIT", "8"))
SEGMENTS = int(os.getenv("SEGMENTS", "4"))           # số đoạn tải song song cho mỗi bài
MIN_SEGMENT = 512 * 1024                            # đoạn nhỏ hơn thế thì không chia nữa
_extract_sem = asyncio.Semaphore(EXTRACT_LIMIT)
_conn_sem = asyncio.Semaphore(CONN_LIMIT)
_tls = threading.local()


def _ydl(kind: str) -> yt_dlp.YoutubeDL:
    """Mỗi thread giữ sẵn 1 instance cho mỗi loại (search/audio): dùng lại player JS,
    cookie, visitor data -> nhanh hơn ~40% so với tạo mới mỗi lần."""
    cache = _tls.__dict__.setdefault("ydl", {})
    if kind not in cache:
        if kind == "search":
            cache[kind] = yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist", skip_download=True))
        else:
            cache[kind] = yt_dlp.YoutubeDL(_ydl_opts(format="bestaudio[ext=m4a]/bestaudio"))
    return cache[kind]


# Thời gian sống của từng loại cache (giây). L1 = RAM, L2 = Redis/SQLite (xem cache.py)
SEARCH_TTL = int(os.getenv("SEARCH_TTL", "21600"))      # kết quả tìm kiếm: 6 giờ
RADIO_TTL = int(os.getenv("RADIO_TTL", "7200"))         # danh sách gợi ý: 2 giờ
PLAYLIST_TTL = int(os.getenv("PLAYLIST_TTL", "300"))    # playlist YouTube: 5 phút (bạn có thể vừa sửa)
FORYOU_TTL = 1200                                       # Mix của Gấu: 20 phút
ERROR_TTL = 600                                         # nhớ video lỗi 10 phút để khỏi hỏi lại YouTube


class _SegmentError(RuntimeError):
    """Lỗi khi tải các đoạn từ googlevideo (khác lỗi phân tích video)."""
_inflight: dict[str, asyncio.Future] = {}


async def _once(key: str, factory):
    """Gộp các request trùng nhau đang chạy thành 1 lần (dedupe)."""
    fut = _inflight.get(key)
    if fut:
        return await asyncio.shield(fut)
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        result = await factory()
        fut.set_result(result)
        return result
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()  # tránh cảnh báo "exception never retrieved"
        raise
    finally:
        _inflight.pop(key, None)


# ---------------------------------------------------------------- search

def _search(query: str, limit: int) -> list[dict]:
    m = URL_ID_RE.search(query)
    target = f"https://www.youtube.com/watch?v={m.group(1)}" if m else (
        f"https://www.youtube.com/watch?v={query}" if VIDEO_ID_RE.match(query) else f"ytsearch{limit}:{query}")
    info = _ydl("search").extract_info(target, download=False)
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


@app.get("/api/search")
async def search(q: str, limit: int = 20):
    q = " ".join(q.split())
    if not q:
        return []
    limit = max(1, min(limit, 50))
    key = f"{q.lower()}|{limit}"
    if (hit := await cache.get("search", key)) is not None:
        return hit

    async def run():
        async with _extract_sem:
            return await run_in_threadpool(_search, q, limit)
    try:
        results = await _once("search:" + key, run)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(502, f"Lỗi tìm kiếm: {e}")
    await cache.set("search", key, results, ttl=SEARCH_TTL, l1_ttl=600)
    return results


# ---------------------------------------------------------------- radio (Mix tự động theo 1 bài)



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


def _yt_cookie_headers() -> dict:
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


async def _raw_radio(vid: str) -> list[dict]:
    """Danh sách bài gợi ý giống "Radio" của YouTube Music (~25-50 bài) bắt đầu từ bài vid.
    Có cookie YouTube thì gọi dưới danh nghĩa tài khoản đó (gợi ý theo gu thật của người dùng)."""
    auth = _yt_cookie_headers()
    key = ("me:" if auth else "anon:") + vid
    if (hit := await cache.get("radio", key)) is not None:
        return hit

    async def run():
        body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20251001.01.00",
                                       "hl": "vi", "gl": "VN"}},
                "videoId": vid, "playlistId": "RDAMVM" + vid, "isAudioOnly": True}
        url = f"{YTM_ORIGIN}/youtubei/v1/next?prettyPrint=false"
        r = await _http.post(url, json=body, headers={"Origin": YTM_ORIGIN, **auth})
        if auth and r.status_code in (400, 401, 403):  # cookie hết hạn -> vẫn phát được bằng radio ẩn danh
            log.warning("cookie YouTube bị từ chối (%s), dùng radio ẩn danh", r.status_code)
            r = await _http.post(url, json=body, headers={"Origin": YTM_ORIGIN})
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
    tracks = await _once("radio:" + key, run)
    if tracks:
        await cache.set("radio", key, tracks, ttl=RADIO_TTL, l1_ttl=1800)
    return tracks


# ---------------------------------------------------------------- gu nghe nhạc (taste profile)
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
        _write_json(TASTE_FILE, data)
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


@app.get("/api/radio/{vid}")
async def radio(request: Request, vid: str, personal: bool = True, exclude: str = ""):
    """Bài tiếp theo: radio YouTube Music từ bài vid, đã sắp xếp lại theo gu của người dùng."""
    if not VIDEO_ID_RE.match(vid):
        raise HTTPException(400, "video id không hợp lệ")
    try:
        cands = await _raw_radio(vid)
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




@app.get("/api/foryou")
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
    radios = await asyncio.gather(*(_raw_radio(s) for s in seeds), return_exceptions=True)
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


@app.get("/api/taste")
async def taste_get(request: Request):
    t = _taste(request.session["email"])
    return {"liked": list(t["liked"]), "blocked": list(t["blocked"]),
            "plays": sum(t["plays"].values()), "skips": sum(t["skips"].values()),
            "top_channels": sorted(t["channels"], key=lambda c: -t["channels"][c])[:8]}


@app.post("/api/feedback")
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
            token = await _access_token(email)
            r = await _http.post(f"{YT_API}/videos/rate", headers={"Authorization": f"Bearer {token}"},
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


# ---------------------------------------------------------------- thumbnails

THUMB_DIR = CACHE_DIR / "thumbs"
THUMB_DIR.mkdir(exist_ok=True)


@app.get("/api/thumb/{vid}")
async def thumb(vid: str):
    if not VIDEO_ID_RE.match(vid):
        raise HTTPException(400)
    headers = {"Cache-Control": "public, max-age=2592000, immutable"}
    path = THUMB_DIR / f"{vid}.jpg"
    if path.exists():
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    async def fetch():
        for name in ("mqdefault.jpg", "hqdefault.jpg", "default.jpg"):
            r = await _http.get(f"https://i.ytimg.com/vi/{vid}/{name}")
            if r.status_code == 200:
                path.write_bytes(r.content)
                return r.content
        return None
    data = await _once("thumb:" + vid, fetch)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/jpeg", headers=headers)


# ---------------------------------------------------------------- audio

def _cached_file(vid: str) -> Path | None:
    for p in CACHE_DIR.glob(f"{vid}.*"):
        if p.is_file() and not p.name.endswith(TEMP_SUFFIXES):
            return p
    return None


def _extract_stream(vid: str) -> dict:
    info = _ydl("audio").extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
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
        async with _extract_sem:
            return await run_in_threadpool(_extract_stream, vid)
    info = await _once("extract:" + vid, run)
    # link googlevideo có hạn (expire) -> chỉ cache tới trước lúc hết hạn 5 phút
    await cache.set("stream", vid, info, ttl=max(60, info["expire"] - time.time() - 300))
    return info


async def _fetch_range(info: dict, start: int, end: int, f, retries: int = 3):
    """Tải 1 đoạn [start, end] và ghi đúng vị trí trong file."""
    for attempt in range(retries):
        try:
            async with _conn_sem:
                async with _http.stream("GET", info["url"], timeout=30,
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
        r = await _http.head(info["url"], headers=info["headers"])
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
    opts = _ydl_opts(format="bestaudio[ext=m4a]/bestaudio", outtmpl=str(CACHE_DIR / "%(id)s.%(ext)s"),
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
                async with _extract_sem:
                    p = await run_in_threadpool(_ytdlp_download, vid)
                how = "yt-dlp"
            except (yt_dlp.utils.DownloadError, RuntimeError) as e:
                # lỗi ở bước phân tích (video không tồn tại, riêng tư, quá dài...): thử lại cũng vô ích
                await cache.set("err", vid, str(e).replace("ERROR: ", ""), ttl=ERROR_TTL)
                raise
            except Exception as e:
                log.warning("tải song song %s lỗi (%s), dùng yt-dlp", vid, e)
                await cache.delete("stream", vid)
                async with _extract_sem:
                    p = await run_in_threadpool(_ytdlp_download, vid)
                how = "yt-dlp"
            log.info("tải %s (%s) %.2fs %.1fMB", vid, how, time.perf_counter() - t, p.stat().st_size / 1e6)
            await run_in_threadpool(_evict)
            return p
        try:
            path = await _once("audio:" + vid, fill)
        except Exception as e:
            raise HTTPException(502, str(e))
    os.utime(path)  # đánh dấu mới dùng cho LRU
    return path


@app.get("/api/audio/{vid}")
async def audio(vid: str):
    path = await _ensure(vid)
    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/prefetch")
async def prefetch(ids: list[str]):
    """Tải trước các bài kế tiếp; chạy nền, vẫn bị giới hạn bởi các semaphore."""
    for vid in ids[:5]:
        if VIDEO_ID_RE.match(vid) and not _cached_file(vid) and "audio:" + vid not in _inflight:
            asyncio.create_task(_safe_ensure(vid))
    return {"ok": True}


async def _safe_ensure(vid: str):
    try:
        await _ensure(vid)
    except Exception:
        pass


@app.get("/api/cache/stats")
async def cache_stats():
    """Tình trạng cache 2 lớp: backend L2 đang dùng, tỉ lệ trúng cache..."""
    return await cache.info()


@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/img/"):   # ảnh trang trí không đổi -> trình duyệt giữ 30 ngày
        resp.headers["Cache-Control"] = "public, max-age=2592000, immutable"
    return resp


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")

if __name__ == "__main__":
    import sys
    import uvicorn
    if sys.stdout is None or sys.stderr is None:  # chạy bằng pythonw: không có console
        sys.stdout = sys.stderr = open(BASE_DIR / "server.log", "a", buffering=1, encoding="utf-8")
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
