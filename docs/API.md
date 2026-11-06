# API

| Method | Path | Mô tả |
|---|---|---|
| GET | `/auth/config` | Phương thức đăng nhập nào đang bật |
| GET | `/auth/login` → `/auth/callback` | Đăng nhập Google |
| POST | `/auth/password` | Đăng nhập bằng mật khẩu (form `password`) |
| GET | `/auth/logout` | Đăng xuất |
| GET | `/api/me` | Email đang đăng nhập |
| GET | `/api/playlists[?refresh=1]` | Danh sách playlist (đầu tiên là `LIKED`) |
| GET | `/api/playlists/{id}[?refresh=1]` | Các bài trong playlist |
| GET | `/api/search?q=&limit=` | Tìm kiếm, hoặc dán link / ID video |
| GET | `/api/radio/{videoId}[?exclude=id1,id2&personal=0]` | Bài tiếp theo: Radio YouTube Music đã sắp xếp lại theo gu (`why`: `yt`/`liked`/`fav`) |
| GET | `/api/foryou[?refresh=1]` | "Mix của Gấu": trộn radio của vài bài bạn thích / nghe nhiều |
| GET | `/api/taste` | Tóm tắt gu nghe: bài đã ♥, bài bị chặn, kênh hay nghe |
| POST | `/api/feedback` | Body `{"track":{...},"event":"finish\|skip\|like\|unlike\|dislike"}` |
| GET | `/api/thumb/{videoId}` | Ảnh bìa |
| GET | `/api/audio/{videoId}` | File audio (hỗ trợ Range/tua) |
| POST | `/api/prefetch` | Body `["id1","id2"]`: tải trước, tối đa 5 bài |
| GET | `/api/cache/stats` | Tình trạng cache 2 lớp |

Mọi đường dẫn đều bắt buộc đăng nhập, trừ `/auth/*`, `/login.html` và file tĩnh `/img/`, `/css/`, `/js/`, `/themes/`.
