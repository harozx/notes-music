// Danh sách theme. Thêm theme mới: thêm 1 dòng ở đây và 1 dòng trong web/themes/index.css
// id: tên file trong web/themes/, label: câu báo khi đổi, color: màu thanh trình duyệt, icon: nút đổi theme
const THEMES = [
  { id: 'milk', label: 'Gấu sữa ban ngày 🥛', color: '#fbf1e6', icon: 'moon' },
  { id: 'cocoa', label: 'Gấu cacao buổi tối 🍫', color: '#241a15', icon: 'sun' },
];

const Theme = {
  saved() {
    try { return THEMES.find(t => t.id === JSON.parse(localStorage.getItem('theme'))) || THEMES[0]; }
    catch { return THEMES[0]; }
  },
  current: () => THEMES.find(t => t.id === document.documentElement.dataset.theme) || THEMES[0],
  next() { return THEMES[(THEMES.indexOf(Theme.current()) + 1) % THEMES.length]; },
  apply(theme) {
    document.documentElement.dataset.theme = theme.id;
    document.querySelector('meta[name=theme-color]').content = theme.color;
  },
};

// Chạy ngay trong <head> để trang không bị nháy theme mặc định khi tải
Theme.apply(Theme.saved());
