"""Đăng nhập Google OAuth / mật khẩu, lưu token và gọi YouTube Data API."""

import asyncio
import json
import secrets
import time
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import core
from .core import log, once, write_json
from .config import (
    ALLOWED_EMAILS, BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_SCOPES,
    LOGIN_PASSWORD, TOKENS_FILE, YT_API,
)


router = APIRouter()


def _load_tokens() -> dict:
    try:
        return json.loads(TOKENS_FILE.read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_tokens(data: dict):
    write_json(TOKENS_FILE, data)


HINT_COOKIE = "notes_hint"   # nhớ email Google lần trước (1 năm) để lần sau đăng nhập chỉ 1 chạm


class GoogleReauth(HTTPException):
    """Token Google hết hạn/bị thu hồi. KHÁC với "chưa đăng nhập": phiên web vẫn còn,
    nghe nhạc/tìm kiếm vẫn chạy, chỉ phần playlist cần bấm "Kết nối lại Google"."""

    def __init__(self, msg: str = "Kết nối Google đã hết hạn, bấm \"Kết nối lại\" để xem playlist"):
        super().__init__(403, msg)


@router.get("/auth/config")
async def auth_config(request: Request):
    return {"google": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET), "password": bool(LOGIN_PASSWORD),
            "hint": request.cookies.get(HINT_COOKIE, ""),            # email lần trước của chính trình duyệt này
            "logged_in": bool(request.session.get("email"))}


@router.get("/auth/login")
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
    r = await core.http.post("https://oauth2.googleapis.com/token", data={
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token, "grant_type": "refresh_token"})
    return r.json() if r.status_code == 200 else None


@router.get("/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/login.html?error={quote(error)}")
    if not state or state != request.session.pop("oauth_state", None):
        return RedirectResponse("/login.html?error=state")
    asked_consent = request.session.pop("oauth_consent", True)
    r = await core.http.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{BASE_URL}/auth/callback",
        "grant_type": "authorization_code",
    })
    if r.status_code != 200:
        return RedirectResponse("/login.html?error=token")
    tok = r.json()
    info = (await core.http.get("https://openidconnect.googleapis.com/v1/userinfo",
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


@router.post("/auth/password")
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


@router.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login.html")   # giữ cookie gợi ý email để lần sau đăng nhập 1 chạm


async def access_token(email: str) -> str:
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
    tok = await once("refresh:" + email, refresh)   # nhiều request cùng lúc chỉ refresh 1 lần
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


async def yt_api(request: Request, endpoint: str, **params) -> dict:
    token = await access_token(request.session["email"])
    r = await core.http.get(f"{YT_API}/{endpoint}", params=params, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 401:     # token bị Google từ chối -> cần kết nối lại, KHÔNG đá ra trang đăng nhập
        raise GoogleReauth()
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code in (403, 404) else 502,
                            r.json().get("error", {}).get("message", "Lỗi YouTube API"))
    return r.json()
