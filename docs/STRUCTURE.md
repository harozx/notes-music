# Cấu trúc dự án

```
.
├── notes/                 Backend (Python, FastAPI)
│   ├── __main__.py        Điểm chạy: python -m notes
│   ├── main.py            Dựng app: lifespan, middleware, gắn router, phục vụ web/
│   ├── config.py          Toàn bộ cấu hình và hằng số
│   ├── core.py            Dùng chung: HTTP client, cache, yt-dlp, gộp request trùng
│   ├── cache.py           Cache 2 lớp (RAM + Redis/SQLite)
│   ├── auth.py            /auth/*: đăng nhập, token Google, gọi YouTube Data API
│   ├── playlists.py       /api/me, /api/playlists
│   ├── search.py          /api/search
│   ├── radio.py           /api/radio, /api/foryou, /api/taste, /api/feedback
│   ├── ytmusic.py         Gọi YouTube Music, đọc cookie YouTube
│   └── media.py           /api/thumb, /api/audio, /api/prefetch
├── web/                   Frontend tĩnh, không cần build
│   ├── index.html         Khung trang nghe nhạc
│   ├── login.html         Khung trang đăng nhập
│   ├── css/               app.css, login.css: bố cục và thành phần
│   ├── js/                app.js, login.js, theme.js
│   ├── themes/            Mỗi theme một file, xem THEMES.md
│   └── img/               Gấu chibi, emoji 3D
├── scripts/               start, stop, status, logs, cài tự khởi động
├── docs/                  Tài liệu
├── Dockerfile, docker-compose.yml
├── requirements.txt
└── .env.example           Mẫu cấu hình

Tạo ra khi chạy, không commit:
.env        cấu hình và bí mật
data/       token Google, gu nghe, cache SQLite, session_secret
cache/      file audio và ảnh bìa
bin/        cloudflared tải riêng
*.log       log server và tunnel
```

## Luồng phụ thuộc trong `notes/`

Chỉ import theo chiều mũi tên, không import ngược lại:

```
main → auth, playlists, search, radio, media
radio → playlists → auth
radio, playlists → ytmusic
tất cả → core → cache, config
```

`config.py` không import module nào trong package.

## Quy ước

**Nên đặt code ở đâu**

| Muốn thêm | Làm ở |
|---|---|
| API mới | Router sẵn có đúng nhóm. Nhóm mới: tạo file trong `notes/` có `router = APIRouter()` rồi thêm vào vòng `for module in (...)` trong `main.py` |
| Biến cấu hình | `notes/config.py`, đồng thời ghi vào `.env.example` và bảng biến trong `DEPLOYMENT.md` |
| Thứ nhiều module cùng dùng | `notes/core.py` |
| Màu sắc | Biến trong `web/themes/`, không viết mã màu vào `web/css/` |
| Bố cục, thành phần giao diện | `web/css/app.css` |
| Logic giao diện | `web/js/app.js` |

**Python**
- Hàm dùng ngoài file thì không có `_` đầu tên, hàm chỉ dùng nội bộ file thì có `_`.
- Dùng HTTP client qua `core.http`, không tạo client mới. Client được tạo trong lifespan nên phải gọi `core.http`, không `from .core import http`.
- Mọi lần gọi YouTube bằng yt-dlp đi qua `extract_sem`, tải googlevideo đi qua `conn_sem`, để giữ trong ngưỡng không bị chặn.
- Ghi file JSON bằng `core.write_json` để không hỏng file khi mất điện.
- Dài tối đa 120 ký tự mỗi dòng.

**Frontend**
- Không dùng bước build. File sửa xong tải lại trang là thấy.
- `theme.js` nạp trong `<head>` để không bị nháy màu; `app.js` nạp cuối `<body>`.
- File tĩnh cần cho trang đăng nhập phải nằm trong `PUBLIC_PATHS` (`notes/main.py`).

**Script Linux**
- Giữ nguyên đường dẫn `scripts/run-server.sh` và `scripts/run-tunnel.sh`: dịch vụ systemd trên máy host trỏ thẳng vào hai file này. Đổi đường dẫn thì phải chạy lại `scripts/install-autostart.sh`.
- `.gitattributes` buộc script dùng LF, nên commit từ Windows vẫn chạy được trên Linux.

**Không commit:** `.env`, `data/`, `cookies.txt`. Trước khi push nên xem lại bằng `git status`.

## Chạy khi phát triển

```bash
.venv/bin/python -m notes
```

Sửa file trong `web/` thì tải lại trang. Sửa file trong `notes/` thì chạy lại lệnh trên.
Để không đụng dữ liệu thật, đặt thêm `DATA_DIR` và `CACHE_DIR` trỏ tới thư mục tạm.
