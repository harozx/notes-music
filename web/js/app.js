const $ = id => document.getElementById(id);
const audio = $('audio');
const ico = name => `<svg class="i"><use href="#i-${name}"/></svg>`;

// ---------------------------------------------------------------- state
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let queue = store.get('queue', []);
let index = store.get('index', -1);
let original = store.get('original', null);   // thứ tự gốc khi đang trộn bài
let shuffle = store.get('shuffle', false);
let repeat = store.get('repeat', 'off');        // off | all | one
let history = store.get('history', []);         // nghe gần đây
let lists = null;
let mixes = null;                              // bài gốc cho mục "Mix cho bạn"
let view = { type: 'home' };
let viewTracks = [];                            // danh sách bài đang hiển thị (để xử lý click)
let resumeAt = store.get('pos', 0);
let seeking = false;
let liked = new Set(store.get('liked', []));     // bài đã ♥ (đồng bộ với server)
let autoplay = store.get('autoplay', true);     // tự nối bài gợi ý theo gu khi hết hàng đợi
let foryou = null;                              // { tracks, seeds } cho mục "Dành riêng cho bạn"
let meInfo = {};
let lastGood = store.get('lastGood', null);     // bài gần nhất bạn nghe hết / bấm thích -> làm "hạt giống" gợi ý
let skipStreak = 0;                             // số bài gợi ý bị bỏ qua liên tiếp
let listen = null;                              // { t, max } theo dõi bài đang nghe để biết nghe hết hay bỏ qua

function save() {
  store.set('queue', queue); store.set('index', index); store.set('original', original);
  store.set('shuffle', shuffle); store.set('repeat', repeat);
}

// ---------------------------------------------------------------- helpers
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = '/login.html'; throw new Error('Chưa đăng nhập'); }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    // token Google hết hạn: KHÔNG đá ra trang đăng nhập, chỉ hiện nút "Kết nối lại" (nhạc vẫn nghe bình thường)
    if (j.code === 'google_reauth') showReauth();
    throw new Error(j.detail || ('HTTP ' + r.status));
  }
  return r.json();
}
function showReauth() {
  if ($('reauth')) return;
  const d = document.createElement('div');
  d.id = 'reauth'; d.className = 'reauth';
  d.innerHTML = `<img src="/img/bear_sad.webp" alt=""><div><b>Kết nối Google hết hạn rồi</b>Nhạc vẫn nghe bình thường, chỉ cần kết nối lại để xem playlist nha.</div>
    <a class="pill" href="/auth/login">Kết nối lại</a><button class="icon-btn" title="Ẩn">${ico('x')}</button>`;
  d.querySelector('button').onclick = () => d.remove();
  document.querySelector('.main').prepend(d);
}
// emoji 3D Fluent (Microsoft, MIT) tự host trong /img/fluent
const emo = (name, size = 22, cls = '') => `<img class="emo ${cls}" src="/img/fluent/${name}_3d.png" width="${size}" height="${size}" alt="" loading="lazy" decoding="async">`;
const bearImg = (name, cls = 'bear-img') => `<img class="${cls}" src="/img/bear_${name}.webp" alt="" decoding="async">`;
const fmt = s => {
  if (!s || !isFinite(s)) return '0:00';
  s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${x}` : `${m}:${x}`;
};
const fmtLong = s => { const h = Math.floor(s / 3600), m = Math.round(s % 3600 / 60); return h ? `${h} giờ ${m} phút` : `${m} phút`; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const thumb = id => id ? `background-image:url(/api/thumb/${id})` : '';
let toastTimer;
function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}
function prefetch(tracks) {
  const ids = tracks.filter(Boolean).map(t => t.id);
  if (ids.length) fetch('/api/prefetch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ids) }).catch(() => {});
}
const current = () => queue[index];

// ---------------------------------------------------------------- sidebar
function coverHtml(p, cls = '') {
  if (p.id === 'LIKED') return `<div class="cov liked ${cls}">${emo('sparkling_heart', 64, 'cov-emo')}</div>`;
  if (p.thumb) return `<div class="cov ${cls}" style="${thumb(p.thumb)}"></div>`;
  const pick = ['honey_pot', 'cookie', 'strawberry', 'cupcake', 'bubble_tea', 'candy', 'balloon', 'tulip'];
  const h = [...String(p.id)].reduce((a, c) => a + c.charCodeAt(0), 0);
  return `<div class="cov empty ${cls}">${emo(pick[h % pick.length], 64, 'cov-emo')}</div>`;
}
function renderSidebar() {
  document.querySelectorAll('[data-nav]').forEach(b =>
    b.classList.toggle('active', b.dataset.nav === view.type || (b.dataset.nav === 'queue' && !$('queuePanel').hidden)));
  $('qcount').textContent = queue.length ? Math.max(queue.length - index - 1, 0) || '' : '';
  if (!lists) { $('plList').innerHTML = Array(5).fill(`<div class="pl-item"><div class="cov skel"></div><div class="tx" style="flex:1"><div class="skel" style="height:12px;width:70%"></div></div></div>`).join(''); return; }
  if (lists.error) { $('plList').innerHTML = `<div style="padding:10px 12px;color:var(--muted);font-size:13px">${esc(lists.error)}</div>`; return; }
  $('plList').innerHTML = lists.map((p, i) => `
    <button class="pl-item ${view.type === 'playlist' && view.pl.id === p.id ? 'active' : ''} ${view.playingFrom === p.id ? 'playing' : ''}" data-pl="${i}">
      ${coverHtml(p)}
      <div class="tx"><div class="t">${esc(p.title)}</div><div class="s">Playlist${p.count != null ? ' · ' + p.count + ' bài' : ''}</div></div>
    </button>`).join('');
}

// ---------------------------------------------------------------- views
function trackRow(t, i, opts = {}) {
  const cur = current()?.id === t.id;
  const why = opts.remove && t.why ? `<span class="why ${t.why}">${t.why === 'yt' ? '✨ gợi ý' : '💗 bạn thích'}</span>` : '';
  const isLiked = liked.has(t.id);
  return `
  <div class="row ${cur ? 'current' : ''}" data-i="${i}" tabindex="0">
    ${opts.noNum ? '' : `<div class="num"><span class="n">${i + 1}</span><span class="pi">${ico('play')}</span><span class="eq"><i></i><i></i><i></i></span></div>`}
    <div class="main-c">
      <div class="cov" style="${thumb(t.id)}"></div>
      <div style="min-width:0"><div class="t">${esc(t.title)}</div><div class="a">${why}${esc(t.channel)}</div></div>
    </div>
    ${opts.noNum ? '' : `<div class="dur">${t.duration ? fmt(t.duration) : ''}</div>`}
    <div class="acts">
      ${opts.remove
        ? `<button class="icon-btn" data-act="remove" title="Xoá khỏi hàng đợi">${ico('x')}</button>`
        : `<button class="icon-btn ${isLiked ? 'liked' : ''}" data-act="like" title="${isLiked ? 'Bỏ thích' : 'Thích'}">${ico(isLiked ? 'heart' : 'heart-o')}</button>
           <button class="icon-btn" data-act="next" title="Phát tiếp theo">${ico('playnext')}</button>
           <button class="icon-btn" data-act="add" title="Thêm vào hàng đợi">${ico('plus')}</button>`}
    </div>
  </div>`;
}
const thead = `<div class="thead"><div style="text-align:center">#</div><div>Tiêu đề</div><div style="text-align:right">⏱</div><div></div></div>`;
const skeletonRows = n => `<div class="tracks skeleton">${Array(n).fill(`<div class="row"><div class="num"></div><div class="main-c"><div class="cov skel"></div><div style="flex:1"><div class="skel" style="height:12px;width:60%;margin-bottom:6px"></div><div class="skel" style="height:10px;width:30%"></div></div></div><div></div><div></div></div>`).join('')}</div>`;

function greeting() {
  const h = new Date().getHours();
  return h < 11 ? `Chào buổi sáng ${emo('sun_with_face', 30)}` : h < 14 ? `Chào buổi trưa ${emo('honey_pot', 30)}`
       : h < 18 ? `Chào buổi chiều ${emo('teddy_bear', 30)}` : `Chào buổi tối ${emo('crescent_moon', 30)}`;
}

function foryouHtml() {
  if (!foryou) return `<div class="foryou-hero">${bearImg('search', 'bearbig')}<div style="flex:1"><h3>Gấu đang chọn nhạc cho bạn…</h3><div class="skel" style="height:12px;width:60%"></div></div></div>`;
  const tr = foryou.tracks || [];
  const personal = meInfo.yt_personal
    ? `<span class="chip ok">${ico('sparkle').replace('class="i"', 'class="i" style="width:14px;height:14px"')}Theo tài khoản YouTube</span>`
    : `<span class="chip" title="Thêm cookie YouTube (data/cookies.txt) để gợi ý theo lịch sử YouTube của bạn">Theo gu nghe trong app</span>`;
  if (!tr.length) return `<div class="foryou-hero">${bearImg('love', 'bearbig')}<div><h3>Dành riêng cho bạn</h3>
    <p>Hãy thả tim ♥ vài bài hoặc nghe thêm một chút, gấu sẽ học gu của bạn nha!</p></div></div>`;
  return `<div class="foryou-hero">
    ${bearImg('dance', 'bearbig')}
    <div style="min-width:0"><h3>Mix của Gấu dành cho bạn ${emo('sparkles', 24)}</h3>
      <p>${tr.length} bài chọn theo những bài bạn thích & nghe nhiều</p>
      <div class="acts2">
        <button class="big-play" id="playForYou" title="Phát">${ico('play')}</button>
        <button class="pill" id="refreshForYou">${ico('refresh')}Đổi mix</button>
        ${personal}
      </div>
    </div>
    <div class="covs">${tr.slice(0, 4).map(t => `<div class="cov" style="${thumb(t.id)}"></div>`).join('')}</div>
  </div>`;
}

function renderView() {
  const v = $('view');
  viewTracks = [];
  if (view.type === 'home') {
    let html = `<h2 class="sec">${greeting()}</h2>` + foryouHtml();
    if (lists && !lists.error) html += `<h2 class="sec">${emo('honey_pot', 28)}Playlist của bạn</h2>`;
    if (!lists) html += `<div class="grid">${Array(6).fill('<div class="card"><div class="cov skel"></div><div class="skel" style="height:12px;width:70%"></div></div>').join('')}</div>`;
    else if (lists.error) html += `<div class="empty-state">${bearImg('sad')}<br>${esc(lists.error)}<br><br><a class="pill" href="/auth/login">${meInfo.email && meInfo.email !== 'local' ? 'Kết nối lại Google' : 'Đăng nhập Google'}</a></div>`;
    else html += `<div class="grid">${lists.map((p, i) => `
      <button class="card" data-pl="${i}">
        ${coverHtml(p)}
        <div class="t">${esc(p.title)}</div><div class="s">${p.count != null ? p.count + ' bài' : 'Playlist'}</div>
        <span class="fab" data-playpl="${i}">${ico('play')}</span>
      </button>`).join('')}</div>`;
    if (mixes?.length) html += `<h2 class="sec">${emo('headphone', 28)}Mix cho bạn</h2><div class="grid">${mixes.map((t, i) => `
      <button class="card" data-mix="${i}">
        <div class="cov" style="${thumb(t.id)}"></div>
        <div class="t">Mix ${esc(t.channel)}</div><div class="s">${esc(t.title)} và các bài tương tự</div>
        <span class="fab">${ico('play')}</span>
      </button>`).join('')}</div>`;
    if (history.length) {
      viewTracks = history;
      html += `<h2 class="sec">${emo('musical_notes', 28)}Nghe gần đây</h2><div class="tracks">${thead}${history.map((t, i) => trackRow(t, i)).join('')}</div>`;
    }
    v.innerHTML = html;
    if ($('playForYou')) $('playForYou').onclick = () => { if (foryou?.tracks?.length) { playList(foryou.tracks, 0, 'FORYOU'); toast('Gấu bật mix cho bạn nè 🧸'); } };
    if ($('refreshForYou')) $('refreshForYou').onclick = () => { foryou = null; renderView(); loadForYou(true); };
  } else if (view.type === 'playlist') {
    const p = view.pl, tr = view.tracks;
    const total = (tr || []).reduce((s, t) => s + (t.duration || 0), 0);
    v.innerHTML = `
      <div class="hero">${coverHtml(p)}
        <div><div class="kind">Playlist</div><h1>${esc(p.title)}</h1>
        <div class="meta">${tr ? `${tr.length} bài · ${fmtLong(total)}` : 'Đang tải…'}</div></div>
      </div>
      <div class="actions">
        <button class="big-play" id="playAll" title="Phát">${ico('play')}</button>
        <button class="pill" id="shuffleAll">${ico('shuffle')}Trộn bài</button>
        <button class="pill" id="addAll">${ico('plus')}Thêm vào hàng đợi</button>
      </div>
      ${view.error ? `<div class="empty-state">${bearImg('sad')}<div>${esc(view.error)}</div></div>`
        : tr ? (tr.length ? `<div class="tracks">${thead}${tr.map((t, i) => trackRow(t, i)).join('')}</div>` : `<div class="empty-state">${bearImg('sleep')}<div>Playlist trống trơn</div></div>`)
        : skeletonRows(8)}`;
    viewTracks = tr || [];
    $('playAll').onclick = () => tr?.length && playList(tr, shuffle ? Math.floor(Math.random() * tr.length) : 0, p.id);
    $('shuffleAll').onclick = () => { if (!tr?.length) return; shuffle = true; updateModes(); playList(tr, Math.floor(Math.random() * tr.length), p.id); };
    $('addAll').onclick = () => { if (!tr?.length) return; queue.push(...tr); if (original) original.push(...tr); save(); renderAll(); toast(`Đã thêm ${tr.length} bài vào hàng đợi`); };
  } else if (view.type === 'search') {
    if (!view.q) {
      v.innerHTML = `<div class="empty-state">${bearImg('search')}<div>Gấu tìm giúp bạn: tên bài, nghệ sĩ, hoặc dán link YouTube</div></div>`;
    } else if (view.loading) {
      v.innerHTML = `<h2 class="sec">Kết quả cho “${esc(view.q)}”</h2>${skeletonRows(8)}`;
    } else if (view.error) {
      v.innerHTML = `<div class="empty-state">${bearImg('sad')}<div>Ui, lỗi rồi: ${esc(view.error)}</div></div>`;
    } else {
      viewTracks = view.results;
      v.innerHTML = `<h2 class="sec">Kết quả cho “${esc(view.q)}”</h2>` + (view.results.length
        ? `<div class="tracks">${thead}${view.results.map((t, i) => trackRow(t, i)).join('')}</div>`
        : `<div class="empty-state">${bearImg('sad')}<div>Gấu tìm mãi không thấy bài nào 🥺</div></div>`);
    }
  }
}

function renderQueue() {
  if ($('queuePanel').hidden) return;
  const cur = current();
  const next = queue.slice(index + 1);
  const autoBox = `<div class="auto-box">${emo('teddy_bear', 34)}
    <div><b>Tự phát theo gu</b>${meInfo.yt_personal ? 'Gợi ý từ tài khoản YouTube + bài bạn thích' : 'Gợi ý theo bài đang nghe + bài bạn thích'}</div>
    <button class="switch ${autoplay ? 'on' : ''}" id="autoSwitch" title="Bật/tắt tự nối bài gợi ý"></button></div>`;
  $('queueList').innerHTML =
    (cur ? `<h5>Đang phát</h5><div class="tracks">${trackRow(cur, index, { noNum: true, remove: false }).replace('class="acts"', 'class="acts" hidden')}</div>` : '') +
    autoBox +
    `<h5>Tiếp theo${next.length ? ` · ${next.length} bài` : ''}</h5>` +
    (next.length ? `<div class="tracks">${next.map((t, k) => trackRow(t, index + 1 + k, { noNum: true, remove: true })).join('')}</div>`
                 : `<div class="empty-state" style="padding:20px">${bearImg('sleep', 'bear-img sm')}<div>Hàng đợi trống${autoplay ? ' – gấu sẽ tự chọn bài tiếp' : ''}</div></div>`);
  $('autoSwitch').onclick = () => {
    autoplay = !autoplay; store.set('autoplay', autoplay); renderQueue();
    toast(autoplay ? 'Gấu sẽ tự chọn bài tiếp theo gu bạn 🧸' : 'Đã tắt tự phát gợi ý');
    if (autoplay) extendRadio();
  };
}

function renderAll() { renderSidebar(); renderView(); renderQueue(); }

// ---------------------------------------------------------------- navigation
function go(v) {
  view = { ...v, playingFrom: view.playingFrom };
  closeDrawer();
  renderAll();
  $('view').scrollTop = 0;
}
async function openPlaylist(p, autoplay = false) {
  go({ type: 'playlist', pl: p, tracks: null });
  try {
    const tracks = await api('/api/playlists/' + encodeURIComponent(p.id));
    if (view.type !== 'playlist' || view.pl.id !== p.id) return;
    view.tracks = tracks;
    prefetch(tracks.slice(0, 2));
    if (autoplay && tracks.length) playList(tracks, shuffle ? Math.floor(Math.random() * tracks.length) : 0, p.id);
  } catch (e) { view.error = e.message; }
  renderView();
}
let searchSeq = 0;
async function doSearch(q) {
  q = q.trim();
  go({ type: 'search', q, loading: !!q, results: [] });
  if (!q) return;
  const seq = ++searchSeq;
  try {
    const results = await api('/api/search?q=' + encodeURIComponent(q));
    if (seq !== searchSeq) return;
    Object.assign(view, { loading: false, results });
    prefetch(results.slice(0, 1));
  } catch (e) { if (seq === searchSeq) Object.assign(view, { loading: false, error: e.message }); }
  renderView();
}
async function loadLists(refresh = false) {
  try { lists = await api('/api/playlists' + (refresh ? '?refresh=1' : '')); }
  catch (e) { lists = { error: e.message }; }
  renderSidebar(); if (view.type === 'home') renderView();
  loadMixes();
  loadForYou();
}
async function loadForYou(refresh = false) {
  try { foryou = await api('/api/foryou' + (refresh ? '?refresh=1' : '')); }
  catch { foryou = { tracks: [] }; }
  if (view.type === 'home') renderView();
  if (foryou.tracks?.length) prefetch(foryou.tracks.slice(0, 1));
}
async function loadMixes() {
  // chọn bài gốc từ "Video đã thích" + nghe gần đây: ưu tiên độ dài giống bài hát, mỗi kênh 1 bài
  let liked = [];
  if (lists && !lists.error) liked = await api('/api/playlists/LIKED').catch(() => []);
  const pool = shuffled([...history, ...liked].filter(t => !t.duration || (t.duration >= 90 && t.duration <= 900)));
  const seen = new Set();
  mixes = pool.filter(t => !seen.has(t.channel) && seen.add(t.channel)).slice(0, 8);
  if (view.type === 'home') renderView();
}

// ---------------------------------------------------------------- gu nghe nhạc: ghi nhận nghe hết / bỏ qua / thích
function feedback(t, event) {
  if (!t) return Promise.resolve({});
  return api('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ track: { id: t.id, title: t.title, channel: t.channel, duration: t.duration }, event }) }).catch(() => ({}));
}
// gọi khi rời 1 bài: nghe >= 60% (hoặc > 4 phút) = thích nghe, < 30 giây = bỏ qua
function reportListen(ended = false) {
  if (!listen) return;
  const { t, max } = listen; listen = null;
  const d = audio.duration || t.duration || 0;
  if (ended || (d && max >= d * 0.6) || max >= 240) {
    feedback(t, 'finish'); skipStreak = 0;
    lastGood = t; store.set('lastGood', t);
  } else if (max < Math.min(30, d * 0.4 || 30)) {
    feedback(t, 'skip');
    if (t.why) skipStreak++;      // bỏ qua bài do gấu gợi ý
  }
}
function toggleLike(t, ev) {
  if (!t) return;
  const on = !liked.has(t.id);
  on ? liked.add(t.id) : liked.delete(t.id);
  store.set('liked', [...liked]);
  if (on) { lastGood = t; store.set('lastGood', t); hearts(ev); }
  feedback(t, on ? 'like' : 'unlike').then(r => {
    if (on && r.youtube) toast('Đã thích trên YouTube luôn 💗');
  });
  toast(on ? 'Gấu nhớ rồi, sẽ gợi ý bài giống vầy 💗' : 'Đã bỏ thích');
  updateLikeBtn(); renderView(); renderQueue();
}
function dislikeCurrent() {
  const t = current();
  if (!t) return;
  liked.delete(t.id); store.set('liked', [...liked]);
  listen = null;                      // đã báo "không thích" thì khỏi tính là skip nữa
  feedback(t, 'dislike');
  // bỏ luôn các bài cùng nghệ sĩ đang chờ trong phần gợi ý tự động
  const ch = t.channel;
  const before = queue.length;
  queue = queue.filter((q, k) => k <= index || !(q.why && q.channel === ch));
  if (original) original = original.filter(q => queue.includes(q) || !q.why);
  const removed = before - queue.length;
  toast(`Gấu sẽ không gợi ý bài này nữa${removed ? ` (bỏ ${removed} bài tương tự)` : ''} 🙈`);
  next();
}
function hearts(ev) {
  const r = (ev?.target?.closest('button') || $('likeBtn')).getBoundingClientRect();
  for (let k = 0; k < 6; k++) {
    const h = document.createElement('span');
    h.className = 'float-heart'; h.innerHTML = emo(['pink_heart', 'sparkling_heart', 'two_hearts'][k % 3], 22);
    h.style.left = (r.left + r.width / 2 - 8 + (Math.random() * 16 - 8)) + 'px';
    h.style.top = (r.top - 4) + 'px';
    h.style.setProperty('--dx', (Math.random() * 60 - 30) + 'px');
    h.style.animationDelay = (k * 70) + 'ms';
    document.body.appendChild(h);
    setTimeout(() => h.remove(), 1400);
  }
}
function updateLikeBtn() {
  const t = current(), on = !!t && liked.has(t.id);
  const b = $('likeBtn');
  b.classList.toggle('liked', on);
  b.innerHTML = ico(on ? 'heart' : 'heart-o');
  b.title = on ? 'Bỏ thích (L)' : 'Thích (L) – gấu sẽ gợi ý bài giống vầy nhiều hơn';
}
function updateMascot() {
  const t = current();
  if (!t) return;
  $('mascotTitle').textContent = audio.paused ? 'Gấu đang ngủ… 💤' : 'Gấu đang quẩy 🎧';
  $('mascotSub').textContent = audio.paused ? 'Bấm phát để đánh thức gấu nha' : t.channel || t.title;
}

// ---------------------------------------------------------------- playback
function shuffled(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function playList(tracks, start, fromId = null) {
  if (shuffle) {
    original = tracks.slice();
    const first = tracks[start];
    queue = [first, ...shuffled(tracks.filter((_, k) => k !== start))];
    index = 0;
  } else { original = null; queue = tracks.slice(); index = start; }
  view.playingFrom = fromId;
  play(index);
}
// tự nối thêm bài gợi ý (radio đã sắp theo gu) khi hàng đợi sắp hết
let radioP = null;
function radioSeed() {
  const t = current();
  // nếu vừa bỏ qua liên tục các bài gợi ý -> lấy bài gần nhất bạn nghe hết / thích làm hạt giống
  if (skipStreak >= 2 && lastGood) return lastGood;
  return t;
}
function extendRadio(force = false) {
  if (radioP) return radioP;
  const seed = radioSeed();
  if (!seed || (!force && (!autoplay || repeat !== 'off' || index < queue.length - 2))) return Promise.resolve();
  const exclude = [...new Set([...queue.slice(Math.max(0, index - 30)).map(q => q.id), ...history.map(h => h.id)])].slice(0, 60);
  radioP = api(`/api/radio/${seed.id}?exclude=${exclude.join(',')}`).then(list => {
    const have = new Set(queue.map(q => q.id));
    const add = list.filter(x => !have.has(x.id)).map(x => ({ ...x, why: x.why || 'yt' }));
    if (!add.length) return;
    queue.push(...add); if (original) original.push(...add);
    save(); renderQueue(); renderSidebar();
  }).catch(() => {}).finally(() => { radioP = null; });
  return radioP;
}
// bỏ qua >= 3 bài gợi ý liên tiếp: gấu hiểu là chưa đúng gu -> thay phần gợi ý còn lại
function maybeRetune() {
  if (skipStreak < 3 || !autoplay || !lastGood) return;
  const before = queue.length;
  queue = queue.filter((q, k) => k <= index || !q.why);
  if (original) original = original.filter(q => queue.includes(q));
  skipStreak = 0;
  if (before !== queue.length || index >= queue.length - 2) {
    toast('Gấu đổi gu nhạc theo bài bạn thích gần nhất 🧸');
    skipStreak = 2;                         // để radioSeed() chọn lastGood
    extendRadio(true).then(() => { skipStreak = 0; });
  }
}
function playRadio(t) {
  playList([t], 0);
  toast('Đang phát Mix từ bài này 🎶');
}
function play(i, at = 0) {
  if (i < 0 || i >= queue.length) return;
  reportListen();
  index = i; save();
  const t = current();
  resumeAt = at;
  listen = { t, max: at };
  audio.src = '/api/audio/' + t.id;
  audio.play().catch(() => {});
  setLoading(true);
  history = [t, ...history.filter(h => h.id !== t.id)].slice(0, 20); store.set('history', history);
  updateNowPlaying(); renderAll();
  audio.addEventListener('playing', () => prefetch(queue.slice(i + 1, i + 4)), { once: true });
  extendRadio();
}
function next(auto = false) {
  reportListen(auto);
  if (auto && repeat === 'one') { listen = { t: current(), max: 0 }; audio.currentTime = 0; audio.play(); return; }
  maybeRetune();
  if (index + 1 < queue.length) play(index + 1);
  else if (repeat === 'all' && queue.length) play(0);
  else if (current()) extendRadio().then(() => {
    if (index + 1 < queue.length) play(index + 1);
    else if (auto) { audio.pause(); audio.currentTime = 0; }
  });
}
function prev() {
  if (audio.currentTime > 3) { audio.currentTime = 0; return; }
  if (index > 0) play(index - 1);
  else if (repeat === 'all' && queue.length) play(queue.length - 1);
  else audio.currentTime = 0;
}
function togglePlay() {
  if (!current()) {
    if (index + 1 < queue.length) play(index + 1);          // hàng đợi có bài nhưng chưa phát
    else if (viewTracks.length) playList(viewTracks, 0, view.pl?.id);
    return;
  }
  if (!audio.src) { play(index, resumeAt); return; }   // tiếp tục bài đang dở từ lần trước
  audio.paused ? audio.play() : audio.pause();
}
function toggleShuffle() {
  shuffle = !shuffle;
  const cur = current();
  if (shuffle && cur) {
    original = queue.slice();
    queue = [cur, ...shuffled(queue.filter((_, k) => k !== index))]; index = 0;
  } else if (!shuffle && original && cur) {
    queue = original; original = null; index = Math.max(0, queue.findIndex(t => t.id === cur.id));
  }
  save(); updateModes(); renderQueue(); renderSidebar();
  toast(shuffle ? 'Đã bật trộn bài' : 'Đã tắt trộn bài');
}
function cycleRepeat() {
  repeat = { off: 'all', all: 'one', one: 'off' }[repeat];
  save(); updateModes();
  toast({ off: 'Tắt lặp lại', all: 'Lặp lại hàng đợi', one: 'Lặp lại 1 bài' }[repeat]);
}
function updateModes() {
  $('shuffleBtn').classList.toggle('on', shuffle);
  const r = $('repeatBtn');
  r.classList.toggle('on', repeat !== 'off');
  r.innerHTML = ico('repeat') + (repeat === 'one' ? '<span class="badge1">1</span>' : '');
}
function setLoading(on) { $('playBtn').classList.toggle('loading', on); }
function updatePlayState() {
  const paused = audio.paused;
  $('playBtn').innerHTML = ico(paused ? 'play' : 'pause');
  $('player').classList.toggle('paused', paused);
  document.body.classList.toggle('paused', paused);
  updateMascot();
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = paused ? 'paused' : 'playing';
}
function updateNowPlaying() {
  const t = current();
  if (!t) return;
  $('npTitle').textContent = t.title;
  $('npArtist').textContent = t.channel;
  const c = $('npCover'); c.className = 'cov spin'; c.innerHTML = ''; c.style.cssText = thumb(t.id);
  updateLikeBtn(); updateMascot();
  document.title = `${t.title} · Notes`;
  if (t.duration) $('tDur').textContent = fmt(t.duration);
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title, artist: t.channel, album: 'Notes',
      artwork: [{ src: '/api/thumb/' + t.id, sizes: '320x180', type: 'image/jpeg' }] });
  }
}
function updateProgress() {
  const d = audio.duration || current()?.duration || 0;
  const c = audio.currentTime || 0;
  if (!seeking) {
    $('seek').value = d ? (c / d) * 1000 : 0;
    $('tCur').textContent = fmt(c);
  }
  $('tDur').textContent = fmt(d);
  let b = 0;
  if (audio.buffered.length && d) b = audio.buffered.end(audio.buffered.length - 1) / d * 100;
  $('seek').style.setProperty('--p', ($('seek').value / 10) + '%');
  $('seek').style.setProperty('--b', b + '%');
  $('miniProg').style.width = d ? (c / d * 100) + '%' : 0;
}

// ---------------------------------------------------------------- audio events
audio.addEventListener('loadedmetadata', () => {
  if (resumeAt) { audio.currentTime = resumeAt; resumeAt = 0; }
  updateProgress();
});
audio.addEventListener('play', updatePlayState);
audio.addEventListener('pause', updatePlayState);
audio.addEventListener('playing', () => { setLoading(false); updatePlayState(); });
audio.addEventListener('waiting', () => setLoading(true));
audio.addEventListener('canplay', () => setLoading(false));
audio.addEventListener('timeupdate', () => {
  if (listen && !seeking && listen.t.id === current()?.id) listen.max = Math.max(listen.max, audio.currentTime);
  updateProgress();
});
audio.addEventListener('progress', updateProgress);
audio.addEventListener('ended', () => next(true));
audio.addEventListener('error', () => {
  if (!audio.getAttribute('src')) return;
  setLoading(false);
  listen = null;   // lỗi tải không phải do bạn bỏ qua
  toast('Bài này không phát được, gấu chuyển bài tiếp nha…');
  setTimeout(() => next(), 1200);
});
setInterval(() => { if (!audio.paused) store.set('pos', audio.currentTime); }, 5000);

// ---------------------------------------------------------------- controls
$('playBtn').onclick = togglePlay;
$('nextBtn').onclick = () => next();
$('prevBtn').onclick = prev;
$('shuffleBtn').onclick = toggleShuffle;
$('repeatBtn').onclick = cycleRepeat;
$('likeBtn').onclick = e => { e.stopPropagation(); toggleLike(current(), e); };
$('dislikeBtn').onclick = e => { e.stopPropagation(); dislikeCurrent(); };
function applyTheme(theme) {
  Theme.apply(theme);
  $('themeBtn').innerHTML = ico(theme.icon);
}
$('themeBtn').onclick = () => {
  const theme = Theme.next();
  store.set('theme', theme.id); applyTheme(theme);
  toast(theme.label);
};
$('seek').addEventListener('input', () => {
  seeking = true;
  const d = audio.duration || current()?.duration || 0;
  $('tCur').textContent = fmt($('seek').value / 1000 * d);
  $('seek').style.setProperty('--p', ($('seek').value / 10) + '%');
});
$('seek').addEventListener('change', () => {
  const d = audio.duration || 0;
  if (d) audio.currentTime = $('seek').value / 1000 * d;
  seeking = false;
});
const vol = $('vol');
function setVolume(v, persist = true) {
  audio.volume = v; vol.value = v * 100;
  vol.style.setProperty('--p', v * 100 + '%');
  $('muteBtn').innerHTML = ico(v === 0 || audio.muted ? 'mute' : 'vol');
  if (persist && v > 0) store.set('vol', v);
}
vol.addEventListener('input', () => { audio.muted = false; setVolume(vol.value / 100); });
$('muteBtn').onclick = () => {
  if (audio.volume === 0 || audio.muted) { audio.muted = false; setVolume(store.get('vol', 0.8)); }
  else { audio.muted = true; setVolume(0, false); }
};
function toggleQueue(force) {
  const p = $('queuePanel');
  p.hidden = force === undefined ? !p.hidden : !force;
  $('queueBtn').classList.toggle('on', !p.hidden);
  renderQueue(); renderSidebar();
}
$('queueBtn').onclick = () => toggleQueue();
$('closeQueue').onclick = () => toggleQueue(false);
$('clearQueue').onclick = () => {
  queue = queue.slice(0, index + 1); if (original) original = queue.slice(); save(); renderAll(); toast('Đã xoá các bài tiếp theo');
};

// ---------------------------------------------------------------- clicks
document.addEventListener('click', e => {
  const nav = e.target.closest('[data-nav]');
  if (nav) {
    const n = nav.dataset.nav;
    if (n === 'home') go({ type: 'home' });
    if (n === 'search') { go({ type: 'search', q: $('q').value.trim(), results: view.results || [] }); $('q').focus(); if ($('q').value.trim()) doSearch($('q').value); }
    if (n === 'queue') { closeDrawer(); toggleQueue(); }
    return;
  }
  const playPl = e.target.closest('[data-playpl]');
  if (playPl) { e.stopPropagation(); openPlaylist(lists[+playPl.dataset.playpl], true); return; }
  const mix = e.target.closest('[data-mix]');
  if (mix) { playRadio(mixes[+mix.dataset.mix]); return; }
  const pl = e.target.closest('[data-pl]');
  if (pl) { openPlaylist(lists[+pl.dataset.pl]); return; }

  const row = e.target.closest('.row[data-i]');
  if (!row) return;
  const i = +row.dataset.i;
  const inQueue = !!row.closest('#queueList');
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (inQueue) {
    if (act === 'remove') {
      const [t] = queue.splice(i, 1);
      if (original) original = original.filter(o => o !== t);
      save(); renderAll();
    } else play(i);
    return;
  }
  const t = viewTracks[i];
  if (!t) return;
  if (act === 'like') {
    toggleLike(t, e);
  } else if (act === 'add') {
    queue.push(t); if (original) original.push(t); save(); renderAll(); toast('Đã thêm vào hàng đợi');
  } else if (act === 'next') {
    queue.splice(index + 1, 0, t); if (original) original.push(t); save(); renderAll(); toast('Sẽ phát tiếp theo');
    prefetch([t]);
  } else if (view.type === 'search' || (view.type === 'home')) {
    // bài lẻ: phát bài này rồi tự nối các bài gợi ý tương tự
    playRadio(t);
  } else {
    playList(viewTracks, i, view.pl?.id);
  }
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !e.target.matches('.row[data-i]')) return;
  e.target.click();
});

// ---------------------------------------------------------------- search box
let debounce;
$('q').addEventListener('input', () => {
  $('clearQ').hidden = !$('q').value;
  clearTimeout(debounce);
  const q = $('q').value.trim();
  if (q.length >= 2) debounce = setTimeout(() => doSearch(q), 800);
});
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') { clearTimeout(debounce); doSearch($('q').value); $('q').blur(); } });
$('clearQ').onclick = () => { $('q').value = ''; $('clearQ').hidden = true; $('q').focus(); go({ type: 'search', q: '' }); };

// ---------------------------------------------------------------- mở rộng thanh phát nhạc (mobile)
const isMobile = () => matchMedia('(max-width: 760px)').matches;
$('np').addEventListener('click', () => { if (isMobile() && current()) $('player').classList.add('expanded'); });
$('collapseBtn').onclick = e => { e.stopPropagation(); $('player').classList.remove('expanded'); };

// ---------------------------------------------------------------- drawer (mobile)
function closeDrawer() { $('side').classList.remove('open'); $('scrim').classList.remove('show'); }
$('menuBtn').onclick = () => { $('side').classList.add('open'); $('scrim').classList.add('show'); };
$('scrim').onclick = closeDrawer;
$('refreshLists').onclick = () => { lists = null; renderSidebar(); loadLists(true); };

// ---------------------------------------------------------------- keyboard shortcuts
document.addEventListener('keydown', e => {
  if (e.target.matches('input, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === ' ') { e.preventDefault(); togglePlay(); }
  else if (k === 'arrowright') audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5);
  else if (k === 'arrowleft') audio.currentTime = Math.max(0, audio.currentTime - 5);
  else if (k === 'arrowup') { e.preventDefault(); setVolume(Math.min(1, audio.volume + 0.05)); }
  else if (k === 'arrowdown') { e.preventDefault(); setVolume(Math.max(0, audio.volume - 0.05)); }
  else if (k === 'n') next();
  else if (k === 'p') prev();
  else if (k === 's') toggleShuffle();
  else if (k === 'r') cycleRepeat();
  else if (k === 'm') $('muteBtn').click();
  else if (k === 'q') toggleQueue();
  else if (k === 'l') toggleLike(current());
  else if (k === '/') { e.preventDefault(); $('q').focus(); }
});

// ---------------------------------------------------------------- media session
if ('mediaSession' in navigator) {
  const ms = navigator.mediaSession;
  ms.setActionHandler('play', () => audio.play());
  ms.setActionHandler('pause', () => audio.pause());
  ms.setActionHandler('previoustrack', prev);
  ms.setActionHandler('nexttrack', () => next());
  try { ms.setActionHandler('seekto', d => { audio.currentTime = d.seekTime; }); } catch {}
}

// ---------------------------------------------------------------- init
setVolume(store.get('vol', 0.8));
applyTheme(Theme.current());
updateModes(); updatePlayState(); updateLikeBtn();
if (current()) {
  updateNowPlaying();
  $('tCur').textContent = fmt(resumeAt);
  const d = current().duration;
  if (d) { $('seek').value = resumeAt / d * 1000; $('seek').style.setProperty('--p', resumeAt / d * 100 + '%'); }
}
renderAll();
api('/api/me').then(m => {
  meInfo = m;
  $('me').textContent = m.email === 'local' ? 'Đăng nhập bằng mật khẩu' : m.email;
  $('avatar').textContent = (m.email === 'local' ? 'N' : m.email[0]).toUpperCase();
  renderQueue(); if (view.type === 'home') renderView();
}).catch(() => {});
// đồng bộ danh sách ♥ từ server (dùng chung giữa các máy)
api('/api/taste').then(t => { liked = new Set(t.liked); store.set('liked', t.liked); updateLikeBtn(); renderView(); }).catch(() => {});
loadLists();
