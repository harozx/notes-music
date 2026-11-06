# Theme giao diện

Mỗi theme là một file biến màu CSS trong `web/themes/`. Giao diện chỉ đọc các biến này, nên thêm theme không phải sửa bố cục hay logic.
Hai trang nghe nhạc và đăng nhập dùng chung theme. Nút đổi theme ở thanh bên sẽ tự xoay vòng qua mọi theme đã đăng ký.

## Thêm theme mới

Ví dụ thêm theme `sakura`, làm 3 bước:

**1. Tạo `web/themes/sakura.css`**, chỉ cần khai báo biến khác với `milk.css`:

```css
[data-theme="sakura"] {
  --bg: #2a1020;
  --panel: #3a1a2c;
  --text: #fde8f0;
  --accent: #ff8fab;
}
```

**2. Thêm vào cuối `web/themes/index.css`:**

```css
@import "sakura.css";
```

**3. Thêm vào danh sách `THEMES` trong `web/js/theme.js`:**

```js
{ id: 'sakura', label: 'Sakura 🌸', color: '#2a1020', icon: 'sun' },
```

Tải lại trang rồi bấm nút đổi theme là thấy.

| Trường | Ý nghĩa |
|---|---|
| `id` | Trùng với `data-theme` trong file CSS |
| `label` | Câu báo khi chuyển sang theme này |
| `color` | Màu thanh trình duyệt trên điện thoại, nên trùng `--bg` |
| `icon` | Biểu tượng trên nút đổi theme, là `id` của icon trong `index.html` (`i-sun`, `i-moon`...) |

## Biến màu

`milk.css` là theme gốc nên khai báo đủ mọi biến. Theme khác thiếu biến nào sẽ lấy giá trị của `milk`.
Làm theme tối thì nên chép từ `cocoa.css` và khai báo đủ, vì `milk` là màu sáng.

| Biến | Dùng cho |
|---|---|
| `--bg`, `--bg-2` | Nền trang |
| `--panel`, `--panel-2` | Nền khung, thẻ |
| `--hover` | Nền khi rê chuột |
| `--line` | Đường viền |
| `--text`, `--muted` | Chữ chính, chữ phụ |
| `--accent`, `--accent-2` | Màu nhấn, nút chính |
| `--accent-ink` | Chữ nằm trên màu nhấn |
| `--pink`, `--pink-soft` | Màu phụ: tim, thanh tua |
| `--danger`, `--ok` | Báo lỗi, báo thành công |
| `--shadow`, `--shadow-sm` | Đổ bóng khung |
| `--tint` | Màu bóng dưới ảnh, viết dạng `R, G, B`, ví dụ `150, 95, 55` |
| `--scrim` | Lớp phủ tối phía sau menu trên điện thoại |
| `--range-track`, `--range-buf` | Thanh tua: nền và phần đã tải |
| `--cover-foryou` | Nền ảnh bìa Mix cho bạn, có thể là gradient |
| `--field` | Nền ô nhập ở trang đăng nhập |
| `--glow-1`, `--glow-2` | Hai vệt sáng nền trang đăng nhập |

## Đổi riêng một thành phần

Được phép thêm rule trong file theme nếu biến không đủ:

```css
[data-theme="sakura"] .card { border-style: dashed; }
```

## Lưu ý

- Luôn viết màu qua biến, không ghi mã màu vào `web/css/`. Nút tròn trên thanh tua và nút Google cố ý giữ màu trắng ở mọi theme.
- Dòng `@import` của theme mới phải đứng sau `milk.css`.
- Muốn đổi theme mặc định: đưa theme đó lên đầu danh sách `THEMES`.
- Lựa chọn theme lưu trong `localStorage` của từng trình duyệt.
