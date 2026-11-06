# Tính năng

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
**cacao** (tối). Thêm theme mới: xem [THEMES.md](THEMES.md). Tôn trọng `prefers-reduced-motion`.

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

- Gấu chibi `web/img/bear_*.webp`: vẽ riêng cho app (nhảy, ngủ, vẫy tay, tìm kiếm, buồn, ôm tim).
- Emoji 3D `web/img/fluent/`: [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji), giấy phép MIT
  (xem `web/img/fluent/LICENSE`). Muốn thêm: tải `assets/<Tên>/3D/<ten>_3d.png` từ repo đó vào thư mục này.
- Tất cả tự host, trình duyệt không cần gọi ra ngoài.

### Tối ưu tốc độ

| Kỹ thuật | Tác dụng |
|---|---|
| Chia mỗi bài thành `SEGMENTS` đoạn, tải song song rồi ghép | Tải nhanh hơn, không cần chạy ffmpeg |
| Giới hạn ngưỡng: `EXTRACT_LIMIT` lượt phân tích yt-dlp, `CONN_LIMIT` kết nối googlevideo | Tránh bị YouTube coi là bot |
| Mỗi thread dùng lại một instance yt-dlp | Phân tích video nhanh hơn ~40% (1,35 giây → 0,8 giây) |
| Gộp request trùng (cùng bài, cùng từ khoá) | Không tải hoặc tìm hai lần |
| Tải trước 3 bài kế tiếp, kết quả tìm kiếm đầu tiên và 2 bài đầu playlist | Bấm là phát ngay |
| Cache tìm kiếm 6 giờ, radio 2 giờ, playlist 5 phút, link audio tới khi hết hạn, lỗi 10 phút | Giảm số lần gọi YouTube |
| Audio và ảnh bìa lưu đĩa (tự xoá bài cũ khi vượt `CACHE_MAX_MB`) | Nghe lại thì không cần mạng tới YouTube |
| Nếu tải song song lỗi thì tự chuyển sang yt-dlp tải như thường | Ổn định |

Số đo thực tế qua tunnel: bài đã có trong cache tới byte đầu tiên mất khoảng 0,3 giây; bài mới 3–5 phút mất 1–3 giây.
