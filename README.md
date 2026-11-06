# Notes: server nghe nhạc YouTube qua trung gian

Dùng để nghe nhạc YouTube trong mạng đã chặn YouTube, Facebook, SoundCloud (ví dụ mạng công ty).
Bạn mở web của mình và **đăng nhập bằng Gmail** để thấy và phát **playlist YouTube của chính bạn**,
hoặc tìm bất kỳ bài nào.

```
 Máy công ty (trình duyệt)                    Máy nhà / VPS
┌────────────────────────┐   HTTPS   ┌───────────────┐       ┌───────────────────┐
│ notes.<domain-của-bạn> │ ────────▶ │ Cloudflare    │ ────▶ │ app.py (FastAPI)  │ ──▶ YouTube
└────────────────────────┘           │ Tunnel        │       │ + yt-dlp + cache  │     (API, googlevideo,
          │ lúc đăng nhập            └───────────────┘       └───────────────────┘      ytimg)
          └──────────────▶ accounts.google.com
```

Trình duyệt chỉ cần vào được **domain của bạn** và **accounts.google.com** (chỉ lúc đăng nhập).
Audio, ảnh bìa, dữ liệu playlist và kết quả tìm kiếm đều do server lấy rồi trả lại.

## Tính năng

- Đăng nhập Google (OAuth). Chỉ email trong `ALLOWED_EMAILS` mới vào được.
- Tab **Playlist của tôi** gồm *Video đã thích* và mọi playlist của tài khoản (kể cả playlist tạo trên YouTube Music).
- Tìm kiếm theo từ khoá, hoặc dán link YouTube. Bấm một bài là phát luôn **Mix** (các bài tương tự, như Radio của YouTube Music).
- Trang chủ có mục **Mix cho bạn**: tạo từ *Video đã thích* và các bài nghe gần đây.
- Hàng đợi sắp hết thì tự nối thêm bài gợi ý, nhạc phát liên tục (trừ khi đang bật lặp lại).
- Danh sách phát lưu trong trình duyệt: phát tất cả, trộn bài, chuyển bài, điều khiển trên màn hình khoá (Media Session).
- Đăng nhập dự phòng bằng mật khẩu (`LOGIN_PASSWORD`), không có playlist.

### Bài tiếp theo theo gu của bạn 🧸

Khi hàng đợi sắp hết, app tự nối bài gợi ý. Gợi ý được cá nhân hoá theo 3 tầng:

1. **Tài khoản YouTube (mạnh nhất, tuỳ chọn)**: đặt `cookies.txt` của tài khoản YouTube vào `data/cookies.txt`
   (hoặc `COOKIES_FILE`). Server gọi Radio YouTube Music *dưới danh nghĩa tài khoản đó* nên gợi ý giống hệt
   trong app YouTube Music của bạn (theo lịch sử nghe, lượt thích). Cookie hết hạn thì tự quay về radio ẩn danh.
   Xuất cookie bằng tiện ích kiểu "Get cookies.txt LOCALLY" khi đang đăng nhập music.youtube.com.
   *Lưu ý: OAuth của Google (YouTube Data API) không có API gợi ý bài, nên phải dùng cookie cho tầng này.*
2. **Video đã thích trên YouTube** (đăng nhập Google): được cộng điểm và thỉnh thoảng chèn vào giữa các gợi ý.
3. **Gu nghe trong app** (`data/taste.json`, lưu theo từng tài khoản, dùng chung giữa các máy):
   nghe hết bài (+), bỏ qua trong 30 giây đầu (−), ♥ thích (++), 👎 không thích (chặn bài, bỏ các bài cùng nghệ sĩ
   đang chờ). Bỏ qua 3 bài gợi ý liên tiếp thì gấu tự "đổi gu": thay phần gợi ý còn lại bằng radio từ bài bạn
   nghe hết / thích gần nhất.

Có thể tắt "Tự phát theo gu" trong khung Hàng đợi. Phím tắt `L` = thích bài đang phát.

### Giao diện

Theme **gấu bông**: màu kem / trà sữa / hồng phấn, gấu linh vật đeo tai nghe nhún nhảy khi phát nhạc và ngủ khi
dừng, ảnh bìa tròn quay như đĩa có tai gấu, tim bay khi thả ♥. Nút 🌙 ở góc dưới thanh bên đổi sang theme
**cacao** (tối). Tôn trọng `prefers-reduced-motion`.

### Đăng nhập 1 lần, dùng lâu dài

- Cookie phiên tên riêng `notes_session` (không đụng cookie `session` của web khác cùng domain), giữ `SESSION_DAYS`
  ngày (mặc định 180) và **tự gia hạn** mỗi ngày bạn dùng.
- Không đặt `SESSION_SECRET` thì server tự sinh 1 lần và lưu vào `data/session_secret` (restart không bị đăng xuất).
- Token Google hết hạn **không đá ra trang đăng nhập** nữa: nhạc vẫn nghe được, chỉ hiện nút "Kết nối lại Google".
  Lần sau đăng nhập lại chỉ cần 1 chạm ("Tiếp tục với email@…"), chỉ hỏi cấp quyền khi thật sự cần.
- ⚠️ App OAuth ở chế độ **Testing** thì Google thu hồi quyền sau 7 ngày. Muốn hết hẳn: Google Auth Platform → Audience →
  **Publish app** (In production). Không cần xác minh khi dùng cá nhân, chỉ hiện cảnh báo "chưa xác minh" lúc đăng nhập.

### Cache 2 lớp (hybrid)

| Lớp | Lưu ở | Đặc điểm |
|---|---|---|
| L1 | RAM tiến trình (LRU, `L1_CACHE_ITEMS`) | Nhanh nhất (~µs), mất khi restart |
| L2 | Redis (`REDIS_URL`) hoặc SQLite `data/cache.db` | Sống qua restart; Redis chết thì tự chuyển SQLite, 30 giây sau thử lại |
| Đĩa | `cache/` | File audio + ảnh bìa (LRU theo `CACHE_MAX_MB`) |

Được cache: tìm kiếm (`SEARCH_TTL`, 6h), radio (`RADIO_TTL`, 2h), playlist (`PLAYLIST_TTL`, 5 phút), link audio
(tới trước lúc hết hạn), lỗi video (10 phút), Mix của Gấu (20 phút). Xem tình trạng: `GET /api/cache/stats`.
Linux chạy tay: `sudo apt install redis-server` rồi `REDIS_URL=redis://127.0.0.1:6379/0` (và `pip install redis`); Docker đã có sẵn service `redis`.

### Hình trang trí

- Gấu chibi `static/img/bear_*.webp`: vẽ riêng cho app (nhảy, ngủ, vẫy tay, tìm kiếm, buồn, ôm tim).
- Emoji 3D `static/img/fluent/`: [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji), giấy phép MIT
  (xem `static/img/fluent/LICENSE`). Muốn thêm: tải `assets/<Tên>/3D/<ten>_3d.png` từ repo đó vào thư mục này.
- Tất cả tự host, trình duyệt không cần gọi ra ngoài.

### Tối ưu tốc độ

| Kỹ thuật | Tác dụng |
|---|---|
| Chia mỗi bài thành `SEGMENTS` đoạn, tải song song rồi ghép | Tải nhanh hơn, không cần chạy ffmpeg |
| Giới hạn ngưỡng: `EXTRACT_LIMIT` lượt phân tích yt-dlp, `CONN_LIMIT` kết nối googlevideo | Tránh bị YouTube coi là bot |
| Mỗi thread dùng lại một instance yt-dlp | Phân tích video nhanh hơn ~40% (1,35 giây → 0,8 giây) |
| Gộp request trùng (cùng bài, cùng từ khoá) | Không tải hoặc tìm hai lần |
| Tải trước 3 bài kế tiếp, kết quả tìm kiếm đầu tiên và 2 bài đầu playlist | Bấm là phát ngay |
| Cache tìm kiếm 10 phút, playlist 5 phút, link audio tới khi hết hạn, lỗi 10 phút | Giảm số lần gọi YouTube |
| Audio và ảnh bìa lưu đĩa (tự xoá bài cũ khi vượt `CACHE_MAX_MB`) | Nghe lại thì không cần mạng tới YouTube |
| Nếu tải song song lỗi thì tự chuyển sang yt-dlp tải như thường | Ổn định |

Số đo thực tế qua tunnel: bài đã có trong cache tới byte đầu tiên mất khoảng 0,3 giây; bài mới 3–5 phút mất 1–3 giây.

---

## Yêu cầu

- Python **3.11+**
- **deno** hoặc **node**: yt-dlp cần một trong hai để giải JS challenge của YouTube
- **ffmpeg** (khuyến nghị, cho đường tải dự phòng)
- Một domain đã đưa về **Cloudflare** (gói Free là đủ)
- Một tài khoản Google để tạo OAuth client

Server phải chạy **ngoài mạng công ty**: máy ở nhà hoặc VPS, ở nơi vào được YouTube.

---

## Triển khai

### Bước 1: Google OAuth client

1. Vào https://console.cloud.google.com, tạo hoặc chọn project.
2. **APIs & Services → Library**: bật **YouTube Data API v3**.
3. **Google Auth Platform / OAuth consent screen**:
   - Audience: **External**
   - **Test users**: thêm mọi email sẽ dùng (phải trùng với `ALLOWED_EMAILS`)
4. **Clients → Create client**:
   - Type: **Web application**
   - Authorized redirect URI: `https://<domain>/auth/callback` (phải trùng `BASE_URL` + `/auth/callback`)
5. Tải file JSON về, hoặc chép **Client ID** và **Client secret** vào `.env`.

> App ở chế độ **Testing** nên mỗi lần đăng nhập Google sẽ báo *"Google chưa xác minh ứng dụng này"*: bấm **Tiếp tục**
> và **tích ô "Xem tài khoản YouTube"**. Google thu hồi quyền sau **7 ngày**, nên mỗi tuần phải đăng nhập lại một lần.

### Bước 2: Cấu hình `.env`

```bash
cp .env.example .env
```

Tối thiểu cần điền `BASE_URL`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` và `ALLOWED_EMAILS`.
Danh sách đầy đủ ở mục [Biến môi trường](#biến-môi-trường).

### Bước 3A: Windows (máy nhà) + Cloudflare Tunnel (cách đang dùng)

```powershell
# cloudflared
winget install Cloudflare.cloudflared

# đăng nhập Cloudflare, CHỌN ĐÚNG DOMAIN trong trình duyệt
cloudflared tunnel login

# tạo tunnel và trỏ subdomain về tunnel
cloudflared tunnel create notes
cloudflared tunnel route dns notes notes.<domain>
```

Tạo `%USERPROFILE%\.cloudflared\config.yml`:

```yaml
tunnel: <TUNNEL-ID>
credentials-file: C:\Users\<user>\.cloudflared\<TUNNEL-ID>.json
ingress:
  - hostname: notes.<domain>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Cài venv, thư viện và hai Scheduled Task (`MusicServer`, `MusicTunnel`), tự chạy khi đăng nhập Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows-install.ps1 -TunnelName notes
```

> Máy phải **bật và đã đăng nhập Windows**. Hãy tắt chế độ Sleep.

### Bước 3B: Docker / VPS

```bash
# Tạo tunnel trên dashboard: Cloudflare Zero Trust → Networks → Tunnels → Create
#   Public hostname: notes.<domain>  →  http://app:8000
# Chép token vào TUNNEL_TOKEN trong .env, rồi:
docker compose up -d --build
```

Cache audio và token Google nằm trong volume `music-data`, nên không mất khi build lại.

> Trên VPS, YouTube hay chặn IP datacenter (*"Sign in to confirm you're not a bot"*). Khi đó cần export
> `cookies.txt` từ trình duyệt đã đăng nhập YouTube, mount vào container và đặt `COOKIES_FILE`.
> Hướng dẫn: https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies

### Bước 3C: Chạy tay (dev)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
.venv/Scripts/python app.py
```

Mở http://localhost:8000. Muốn thử đăng nhập Google ở local thì đặt `BASE_URL=http://localhost:8000` và thêm
redirect URI tương ứng vào OAuth client.

---

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Địa chỉ public, dùng làm redirect URI của Google. Bắt đầu bằng `https` thì cookie được đặt cờ Secure |
| `SESSION_SECRET` | ngẫu nhiên mỗi lần chạy | Khoá ký cookie. **Nên đặt cố định**, nếu không mỗi lần restart sẽ bị đăng xuất |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | | OAuth client loại Web application |
| `ALLOWED_EMAILS` | (trống = mọi tài khoản) | Email được phép đăng nhập, phân cách bằng dấu phẩy |
| `LOGIN_PASSWORD` | (trống = tắt) | Mật khẩu đăng nhập dự phòng, không cần Google |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Nên để `127.0.0.1` khi đi qua tunnel |
| `CACHE_DIR` | `./cache` | Thư mục audio và ảnh bìa |
| `DATA_DIR` | `./data` | Thư mục token Google (`tokens.json`) |
| `CACHE_MAX_MB` | `2000` | Dung lượng cache tối đa, vượt quá thì xoá bài cũ nhất |
| `MAX_DURATION` | `10800` | Bỏ qua video dài hơn số giây này |
| `EXTRACT_LIMIT` | `3` | Số lần phân tích yt-dlp chạy cùng lúc |
| `CONN_LIMIT` | `8` | Tổng số kết nối tới googlevideo cùng lúc |
| `SEGMENTS` | `4` | Số đoạn tải song song cho mỗi bài |
| `COOKIES_FILE` | | `cookies.txt` YouTube, dùng khi IP server bị chặn. Cũng dùng để radio gợi ý theo tài khoản YouTube |
| `YT_WRITE` | (tắt) | `1` = nút ♥ bấm "Thích" luôn trên YouTube (cần đăng nhập Google lại để cấp quyền ghi) |

---

## Cấu trúc dự án

```
app.py                  server FastAPI: auth Google/mật khẩu, YouTube API, tìm kiếm, tải audio, cache
static/index.html       giao diện nghe nhạc
static/login.html       trang đăng nhập
requirements.txt
.env.example            mẫu cấu hình
Dockerfile, docker-compose.yml
scripts/windows-install.ps1
cache/                  (tự tạo) audio + thumbs/
data/                   (tự tạo) tokens.json, taste.json (gu nghe), cookies.txt (tuỳ chọn). BÍ MẬT, không commit
```

## API

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

Mọi đường dẫn trừ `/auth/*` và `/login.html` đều bắt buộc đăng nhập.

---

## Vận hành

```powershell
# khởi động lại server (sau khi sửa code hoặc .env)
Stop-ScheduledTask MusicServer; Start-ScheduledTask MusicServer

# xem log
Get-Content D:\music\server.log -Tail 50 -Wait

# cập nhật yt-dlp (làm ĐẦU TIÊN khi không phát được nhạc)
.venv\Scripts\pip install -U "yt-dlp[default]"

# xoá cache
Remove-Item cache\* -Recurse
```

## Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Không phát được bài nào, log có `Signature solving failed` / `n challenge` | yt-dlp hoặc `yt-dlp-ejs` cũ: cập nhật yt-dlp. Kiểm tra máy có deno hoặc node |
| `Sign in to confirm you're not a bot` | IP bị YouTube nghi ngờ: giảm `EXTRACT_LIMIT`, hoặc dùng `COOKIES_FILE` |
| Google báo *Access blocked / not a test user* | Thêm email vào **Test users** trong consent screen |
| `redirect_uri_mismatch` | Redirect URI trong OAuth client phải đúng `BASE_URL/auth/callback` |
| Đăng nhập xong bị đưa về `login.html?error=forbidden` | Email không nằm trong `ALLOWED_EMAILS` |
| `error=state` | Cookie phiên mất giữa chừng (đổi `SESSION_SECRET`, chặn cookie): đăng nhập lại |
| Tab playlist báo lỗi API / 403 | Chưa bật **YouTube Data API v3**, hoặc lúc cấp quyền bỏ tích ô YouTube |
| Playlist báo "Phiên Google hết hạn" | Hết 7 ngày ở chế độ Testing: đăng nhập Google lại |
| Domain trả **502** | `MusicServer` không chạy: xem `server.log`, chạy lại task |
| Domain không vào được ở công ty | Proxy chặn domain mới hoặc chưa phân loại: thử subdomain hoặc domain khác |

## Bảo mật

- `.env`, `data/` (token Google, OAuth secret) và `cookies.txt` là **bí mật**, đã có trong `.gitignore`.
- Luôn đặt `ALLOWED_EMAILS`. Để trống thì bất kỳ ai có tài khoản Google cũng dùng được server của bạn.
- Server chỉ xin quyền **`youtube.readonly`**: không sửa, không xoá gì trên YouTube.
- Dùng server này có thể vi phạm quy định IT của công ty, hãy tự cân nhắc.
