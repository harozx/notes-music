const e = new URLSearchParams(location.search).get('error');
const msg = { forbidden: 'Tài khoản này không được phép vào nhà gấu.', state: 'Phiên đăng nhập hết hạn, thử lại nha.',
              token: 'Không lấy được token từ Google.', password: 'Sai mật khẩu rồi 🥺', access_denied: 'Bạn đã từ chối cấp quyền.' };
if (e) document.getElementById('err').textContent = msg[e] || ('Lỗi: ' + e);
const pw = document.querySelector('.pw input'), bear = document.getElementById('bear');
pw.addEventListener('focus', () => bear.classList.add('peek'));
pw.addEventListener('blur', () => bear.classList.remove('peek'));
fetch('/auth/config').then(r => r.json()).then(c => {
  if (c.logged_in) { location.replace('/'); return; }   // còn phiên đăng nhập -> vào thẳng
  if (c.google && c.hint) {                               // nhớ tài khoản lần trước -> 1 chạm
    document.querySelector('a.btn').lastChild.textContent = ' Tiếp tục với ' + c.hint;
    const h = document.getElementById('hint'); h.style.display = 'block';
    h.innerHTML = 'Không phải bạn? <a href="#" id="other">Dùng tài khoản khác</a>';
    document.getElementById('other').onclick = ev => { ev.preventDefault(); location.href = '/auth/login?other=1'; };
  }
  if (!c.google) { document.querySelector('a.btn').hidden = true; document.querySelector('.sep').hidden = true; }
  if (!c.password) document.querySelector('form.pw').hidden = true;
}).catch(() => {});
