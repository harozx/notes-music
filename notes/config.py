"""Cấu hình đọc từ biến môi trường / file .env. Không import module nào khác trong package."""

import os
import re
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent     # gốc dự án (chứa .env, data/, cache/, web/)
WEB_DIR = BASE_DIR / "web"

try:  # đọc cấu hình từ file .env ở gốc dự án nếu có
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

# Ngưỡng: số lần phân tích yt-dlp và số kết nối googlevideo chạy cùng lúc
EXTRACT_LIMIT = int(os.getenv("EXTRACT_LIMIT", "3"))
CONN_LIMIT = int(os.getenv("CONN_LIMIT", "8"))
SEGMENTS = int(os.getenv("SEGMENTS", "4"))           # số đoạn tải song song cho mỗi bài
MIN_SEGMENT = 512 * 1024                            # đoạn nhỏ hơn thế thì không chia nữa

# Thời gian sống của từng loại cache (giây). L1 = RAM, L2 = Redis/SQLite (xem notes/cache.py)
SEARCH_TTL = int(os.getenv("SEARCH_TTL", "21600"))      # kết quả tìm kiếm: 6 giờ
RADIO_TTL = int(os.getenv("RADIO_TTL", "7200"))         # danh sách gợi ý: 2 giờ
PLAYLIST_TTL = int(os.getenv("PLAYLIST_TTL", "300"))    # playlist YouTube: 5 phút (bạn có thể vừa sửa)
FORYOU_TTL = 1200                                       # Mix của Gấu: 20 phút
ERROR_TTL = 600                                         # nhớ video lỗi 10 phút để khỏi hỏi lại YouTube
