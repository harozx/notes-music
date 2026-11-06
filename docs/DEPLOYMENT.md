# Triển khai và vận hành

## Yêu cầu

- Python **3.11+**
- **deno** hoặc **node**: yt-dlp cần một trong hai để giải JS challenge của YouTube
- **ffmpeg** (khuyến nghị, cho đường tải dự phòng)
- Một domain đã đưa về **Cloudflare** (gói Free là đủ)
- Một tài khoản Google để tạo OAuth client

Server phải chạy **ngoài mạng công ty**: máy ở nhà hoặc VPS, ở nơi vào được YouTube.

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

### Bước 3A: Linux + Cloudflare Tunnel (cách đang dùng)

```bash
python3 -m venv .venv-linux
.venv-linux/bin/pip install -r requirements.txt
# điền TUNNEL_TOKEN trong .env (lấy bằng: cloudflared tunnel token notes)
scripts/start          # lần đầu tự cài systemd: chạy khi bật máy, crash tự bật lại
```

### Bước 3B: Windows + Cloudflare Tunnel

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

### Bước 3C: Docker / VPS

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

### Bước 3D: Chạy tay (dev)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m notes                     # Linux/macOS: .venv/bin/python -m notes
```

Mở http://localhost:8000. Muốn thử đăng nhập Google ở local thì đặt `BASE_URL=http://localhost:8000` và thêm
redirect URI tương ứng vào OAuth client.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Địa chỉ public, dùng làm redirect URI của Google. Bắt đầu bằng `https` thì cookie được đặt cờ Secure |
| `SESSION_SECRET` | tự sinh, lưu ở `data/session_secret` | Khoá ký cookie |
| `SESSION_DAYS` | `180` | Số ngày giữ đăng nhập, dùng web là tự gia hạn |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | | OAuth client loại Web application |
| `ALLOWED_EMAILS` | (trống = mọi tài khoản) | Email được phép đăng nhập, phân cách bằng dấu phẩy |
| `LOGIN_PASSWORD` | (trống = tắt) | Mật khẩu đăng nhập dự phòng, không cần Google |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Nên để `127.0.0.1` khi đi qua tunnel |
| `CACHE_DIR` | `./cache` | Thư mục audio và ảnh bìa |
| `DATA_DIR` | `./data` | Token Google, gu nghe, cache SQLite |
| `REDIS_URL` | (trống = SQLite) | Redis cho cache L2 |
| `L1_CACHE_ITEMS` | `2000` | Số mục giữ trong RAM |
| `SEARCH_TTL` / `RADIO_TTL` / `PLAYLIST_TTL` | `21600` / `7200` / `300` | Thời gian cache, tính bằng giây |
| `CACHE_MAX_MB` | `2000` | Dung lượng cache tối đa, vượt quá thì xoá bài cũ nhất |
| `MAX_DURATION` | `10800` | Bỏ qua video dài hơn số giây này |
| `EXTRACT_LIMIT` | `3` | Số lần phân tích yt-dlp chạy cùng lúc |
| `CONN_LIMIT` | `8` | Tổng số kết nối tới googlevideo cùng lúc |
| `SEGMENTS` | `4` | Số đoạn tải song song cho mỗi bài |
| `TUNNEL_TOKEN` | | Token Cloudflare Tunnel, dùng cho `scripts/run-tunnel.sh` và Docker |
| `COOKIES_FILE` | | `cookies.txt` YouTube, dùng khi IP server bị chặn. Cũng dùng để radio gợi ý theo tài khoản YouTube |
| `YT_WRITE` | (tắt) | `1` = nút ♥ bấm "Thích" luôn trên YouTube (cần đăng nhập Google lại để cấp quyền ghi) |

## Vận hành

**Linux** (systemd, chạy từ gốc dự án):

```bash
scripts/start          # bật / khởi động lại server + tunnel
scripts/stop           # tắt
scripts/status         # xem tình trạng
scripts/logs           # xem log trực tiếp

# cập nhật yt-dlp (làm ĐẦU TIÊN khi không phát được nhạc)
.venv-linux/bin/pip install -U "yt-dlp[default]" && scripts/start
```

**Windows** (Scheduled Task):

```powershell
Stop-ScheduledTask MusicServer; Start-ScheduledTask MusicServer
Get-Content server.log -Tail 50 -Wait
.venv\Scripts\pip install -U "yt-dlp[default]"
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
| Domain trả **502** | Server không chạy: xem `server.log`, chạy lại `scripts/start` (Linux) hoặc task `MusicServer` (Windows) |
| Domain không vào được ở công ty | Proxy chặn domain mới hoặc chưa phân loại: thử subdomain hoặc domain khác |

## Bảo mật

- `.env`, `data/` (token Google, OAuth secret) và `cookies.txt` là **bí mật**, đã có trong `.gitignore`.
- Luôn đặt `ALLOWED_EMAILS`. Để trống thì bất kỳ ai có tài khoản Google cũng dùng được server của bạn.
- Mặc định server chỉ xin quyền **`youtube.readonly`**. Bật `YT_WRITE=1` mới có quyền ghi (để nút ♥ thích bài trên YouTube).
- Dùng server này có thể vi phạm quy định IT của công ty, hãy tự cân nhắc.
