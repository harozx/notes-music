# Notes

Server trung gian tự host để nghe nhạc YouTube trong mạng đã chặn YouTube, Facebook, SoundCloud.
Mở web của bạn, **đăng nhập bằng Gmail** và phát **playlist YouTube của chính bạn**, hoặc tìm bất kỳ bài nào.

```
 Máy công ty (trình duyệt)                     Máy nhà / VPS
┌────────────────────────┐   HTTPS   ┌───────────────┐       ┌───────────────────┐
│ notes.<domain-của-bạn> │ ────────▶ │ Cloudflare    │ ────▶ │ notes/ (FastAPI)  │ ──▶ YouTube
└────────────────────────┘           │ Tunnel        │       │ + yt-dlp + cache  │
          │ lúc đăng nhập            └───────────────┘       └───────────────────┘
          └──────────────▶ accounts.google.com
```

Trình duyệt chỉ cần vào được **domain của bạn** và **accounts.google.com** (chỉ lúc đăng nhập).
Audio, ảnh bìa, playlist và kết quả tìm kiếm đều do server lấy rồi trả lại.

## Chạy nhanh

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # điền BASE_URL, GOOGLE_*, ALLOWED_EMAILS
.venv/bin/python -m notes                     # http://localhost:8000
```

Cần Python 3.11+ và deno hoặc node. Trên Linux dùng `scripts/start` để chạy kèm tunnel và tự bật khi khởi động máy.

## Tài liệu

| Tài liệu | Nội dung |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | Tính năng, gợi ý nhạc, cache, tối ưu tốc độ |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Cài đặt, biến môi trường, vận hành, xử lý sự cố, bảo mật |
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | Cấu trúc thư mục và quy ước khi phát triển |
| [docs/THEMES.md](docs/THEMES.md) | Thêm và sửa theme giao diện |
| [docs/API.md](docs/API.md) | Danh sách API |
