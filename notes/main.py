"""Dựng ứng dụng FastAPI: lifespan, middleware, gắn các router và trang web tĩnh."""

import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import auth, core, media, playlists, radio, search
from .auth import GoogleReauth
from .config import BASE_URL, SESSION_COOKIE, SESSION_DAYS, SESSION_SECRET, WEB_DIR
from .core import cache


@asynccontextmanager
async def lifespan(_app):
    # giữ kết nối keep-alive tới Google để không phải bắt tay TLS lại mỗi request
    core.http = httpx.AsyncClient(timeout=15, follow_redirects=True,
                                  limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
    await cache.start()
    yield
    await cache.close()
    await core.http.aclose()


app = FastAPI(title="music-proxy", docs_url=None, redoc_url=None, lifespan=lifespan)

PUBLIC_PATHS = ("/auth/", "/login.html", "/favicon.ico", "/img/", "/css/", "/js/", "/themes/")


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


@app.exception_handler(GoogleReauth)
async def google_reauth_handler(_request: Request, exc: GoogleReauth):
    return JSONResponse({"detail": exc.detail, "code": "google_reauth"}, status_code=403)


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


for module in (auth, playlists, search, radio, media):
    app.include_router(module.router)

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")
