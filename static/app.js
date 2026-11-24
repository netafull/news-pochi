/* ニュースポチ。前半は DOM に触らない純粋な関数（呪文・購読モデル・絞り込み・日時）。
   tests/test_app.py が osascript(JXA) で検証する。後半が画面の組み立て。
   購読モデル: 全部モード {mode:'all'}（後から増えたブログも自動で入る）／
   カスタムモード {mode:'custom', ids:[...]}（保存した id だけが対象）。 */
var NewsPochi = (function () {
  'use strict';
  var PREFIX = 'np1-';
  var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

  function isHttp(u) { return typeof u === 'string' && /^https?:\/\//i.test(u); }

  // 文字列 → UTF-8 のバイト列 → base64url（パディングなし）
  function utf8Bytes(s) {
    var out = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
        var d = s.charCodeAt(i + 1);
        if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }
  function b64urlEncode(s) {
    var b = utf8Bytes(s), out = '';
    for (var i = 0; i < b.length; i += 3) {
      var n = (b[i] << 16) | ((b[i + 1] || 0) << 8) | (b[i + 2] || 0);
      out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63];
      if (i + 1 < b.length) out += B64[(n >> 6) & 63];
      if (i + 2 < b.length) out += B64[n & 63];
    }
    return out;
  }
  // 失敗したら null（文字種・長さが不正、UTF-8 として読めない）
  function b64urlDecode(t) {
    if (!/^[A-Za-z0-9_-]*$/.test(t) || t.length % 4 === 1) return null;
    var bytes = [], buf = 0, bits = 0;
    for (var i = 0; i < t.length; i++) {
      buf = (buf << 6) | B64.indexOf(t.charAt(i));
      bits += 6;
      if (bits >= 8) { bits -= 8; bytes.push((buf >> bits) & 255); buf &= (1 << bits) - 1; }
    }
    var s = '', i2 = 0;
    while (i2 < bytes.length) {
      var c = bytes[i2], n = c < 0x80 ? 0 : c >= 0xf0 ? 3 : c >= 0xe0 ? 2 : c >= 0xc0 ? 1 : -1;
      if (n < 0) return null;
      var cp = n === 0 ? c : n === 1 ? c & 0x1f : n === 2 ? c & 0x0f : c & 0x07;
      for (var k = 1; k <= n; k++) {
        var cc = bytes[i2 + k];
        if (cc === undefined || (cc & 0xc0) !== 0x80) return null;
        cp = (cp << 6) | (cc & 63);
      }
      i2 += n + 1;
      s += cp > 0xffff ? String.fromCharCode(0xd800 + ((cp - 0x10000) >> 10), 0xdc00 + ((cp - 0x10000) & 0x3ff)) : String.fromCharCode(cp);
    }
    return s;
  }

  // 呪文を作る。全部モードは np1-all、カスタムは np1- + base64url(カンマ区切りの id)
  function encodeSpell(sub) {
    if (!sub || sub.mode !== 'custom') return PREFIX + 'all';
    return PREFIX + b64urlEncode((sub.ids || []).join(','));
  }
  // 呪文を読む。形式が違えば null。known（有効な id の配列）に無い id は黙って捨てる
  function decodeSpell(text, known) {
    var t = String(text == null ? '' : text).trim();
    if (t.indexOf(PREFIX) !== 0) return null;
    var body = t.slice(PREFIX.length);
    if (body === 'all') return { mode: 'all' };
    var raw = b64urlDecode(body);
    if (raw === null) return null;
    var k = {};
    (known || []).forEach(function (id) { k[id] = true; });
    var seen = {}, ids = [];
    raw.split(',').forEach(function (id) {
      if (id && k[id] && !seen[id]) { seen[id] = true; ids.push(id); }
    });
    return { mode: 'custom', ids: ids };
  }

  // いま対象のブログ id の配列（allIds の並びで）
  function activeIds(sub, allIds) {
    if (!sub || sub.mode !== 'custom') return allIds.slice();
    var s = {};
    (sub.ids || []).forEach(function (id) { s[id] = true; });
    return allIds.filter(function (id) { return s[id]; });
  }
  // トグル。どれか1つでも触ったらカスタムモードに移り、その時点のオン一覧を保存する
  function toggle(sub, id, allIds) {
    var on = activeIds(sub, allIds), i = on.indexOf(id);
    if (i >= 0) on.splice(i, 1); else on.push(id);
    return { mode: 'custom', ids: allIds.filter(function (x) { return on.indexOf(x) >= 0; }) };
  }

  // 記事を絞る。articles は新しい順のまま返す。category が空なら系統は問わない
  function filterArticles(articles, active, category, blogCategory) {
    var a = {};
    (active || []).forEach(function (id) { a[id] = true; });
    return (articles || []).filter(function (x) {
      return x && a[x.blog] && isHttp(x.url) && x.title && (!category || blogCategory[x.blog] === category);
    });
  }

  // ISO 8601 → JST の「11/24 14:05」
  function fmtJst(s) {
    var t = Date.parse(s);
    if (isNaN(t)) return '';
    var d = new Date(t + 9 * 3600 * 1000);
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return (d.getUTCMonth() + 1) + '/' + d.getUTCDate() + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
  }

  // document.cookie の文字列から name の値を取る
  function readCookie(str, name) {
    var parts = String(str || '').split(';');
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i].replace(/^\s+/, ''), eq = p.indexOf('=');
      if (eq > 0 && p.slice(0, eq) === name) return p.slice(eq + 1);
    }
    return null;
  }

  return {
    isHttp: isHttp, b64urlEncode: b64urlEncode, b64urlDecode: b64urlDecode, encodeSpell: encodeSpell, decodeSpell: decodeSpell,
    activeIds: activeIds, toggle: toggle, filterArticles: filterArticles, fmtJst: fmtJst, readCookie: readCookie
  };
})();

/* ---------------- 画面 ---------------- */
if (typeof document !== 'undefined') (function () {
  'use strict';
  var N = NewsPochi;
  var VIEW_KEY = 'newspochi.view', COOKIE = 'np_sub';
  function load(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 使えなくても動く */ } }

  var tabs = [].slice.call(document.querySelectorAll('.np-tab'));
  var panels = { home: document.getElementById('view-home'), subs: document.getElementById('view-subs') };
  var status = document.getElementById('home-status');
  var list = document.getElementById('home-list');
  var chipBox = document.getElementById('np-chips');
  var updated = document.getElementById('home-updated');
  var subsBox = document.getElementById('subs-groups');
  var spellOut = document.getElementById('spell-current');
  var spellIn = document.getElementById('spell-input');
  var spellMsg = document.getElementById('spell-msg');
  if (!tabs.length || !panels.home || !panels.subs) return;

  var data = null;        // { categories, blogs }
  var articles = null;    // 新しい順
  var generated = '';
  var allIds = [], blogById = {}, blogCategory = {};
  var sub = { mode: 'all' };
  var category = '';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // ---- 購読の保存（cookie） ----
  function readSub() {
    var v = N.readCookie(document.cookie, COOKIE);
    var s = v ? N.decodeSpell(v, allIds) : null;
    return s || { mode: 'all' };
  }
  function writeSub() {
    var secure = location.protocol === 'https:' || location.hostname === 'localhost' ? '; Secure' : '';
    try {
      document.cookie = COOKIE + '=' + N.encodeSpell(sub) + '; Max-Age=31536000; Path=/; SameSite=Lax' + secure;
    } catch (e) { /* cookie が使えなくても動く */ }
  }

  // ---- ホーム ----
  function renderChips() {
    chipBox.textContent = '';
    var defs = [{ id: '', name: 'すべて' }].concat(data.categories);
    defs.forEach(function (c) {
      var b = el('button', 'np-chip', c.name);
      b.type = 'button';
      b.setAttribute('aria-pressed', category === c.id ? 'true' : 'false');
      b.addEventListener('click', function () { category = c.id; renderChips(); renderHome(); });
      chipBox.appendChild(b);
    });
  }

  function card(a) {
    var li = el('li', 'np-card');
    if (N.isHttp(a.image)) {
      var link = el('a', 'np-imglink');
      link.href = a.url; link.target = '_blank'; link.rel = 'noopener';
      link.tabIndex = -1; link.setAttribute('aria-hidden', 'true');
      var box = el('span', 'np-thumb');
      var img = document.createElement('img');
      img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', function () { link.remove(); }); // 読めなければ画像枠ごと消す
      img.src = a.image;
      box.appendChild(img); link.appendChild(box); li.appendChild(link);
    }
    var body = el('div', 'np-body');
    var h = el('h3', 'np-title');
    var t = el('a', null, a.title);
    t.href = a.url; t.target = '_blank'; t.rel = 'noopener';
    h.appendChild(t);
    body.appendChild(h);
    var meta = el('p', 'np-meta');
    var b = blogById[a.blog];
    meta.appendChild(el('span', 'np-blog', b ? b.name : a.blog));
    var time = el('time', 'np-date', N.fmtJst(a.published));
    time.setAttribute('datetime', a.published);
    meta.appendChild(time);
    body.appendChild(meta);
    if (a.summary) body.appendChild(el('p', 'np-summary', a.summary));
    li.appendChild(body);
    return li;
  }

  function renderHome() {
    list.textContent = '';
    if (!data || !articles) return;
    var active = N.activeIds(sub, allIds);
    if (!active.length) {
      status.hidden = false;
      status.textContent = '購読中のブログがありません。「購読リスト」でブログをオンにしてください。';
      return;
    }
    var items = N.filterArticles(articles, active, category, blogCategory);
    if (!items.length) {
      status.hidden = false;
      status.textContent = category ? 'この系統の新着記事はまだありません。' : '新着記事はまだありません。';
      return;
    }
    status.hidden = true;
    var frag = document.createDocumentFragment();
    items.forEach(function (a) { frag.appendChild(card(a)); });
    list.appendChild(frag);
  }

  // ---- 購読リスト ----
  function renderSubs() {
    subsBox.textContent = '';
    var on = {};
    N.activeIds(sub, allIds).forEach(function (id) { on[id] = true; });
    data.categories.forEach(function (c) {
      var blogs = data.blogs.filter(function (b) { return b.category === c.id; });
      if (!blogs.length) return;
      var sec = el('section', 'np-group');
      sec.appendChild(el('h3', 'np-group-h', c.name));
      var ul = el('ul', 'np-switches');
      blogs.forEach(function (b) {
        var li = el('li');
        var label = el('label', 'np-switch');
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.setAttribute('role', 'switch');
        cb.checked = !!on[b.id];
        cb.addEventListener('change', function () {
          sub = N.toggle(sub, b.id, allIds);
          writeSub();
          refresh(false);
        });
        label.appendChild(cb);
        label.appendChild(el('span', 'np-switch-name', b.name));
        li.appendChild(label);
        ul.appendChild(li);
      });
      sec.appendChild(ul);
      subsBox.appendChild(sec);
    });
    spellOut.value = N.encodeSpell(sub);
  }

  function refresh(rebuildSubs) {
    if (rebuildSubs !== false) renderSubs(); else spellOut.value = N.encodeSpell(sub);
    renderHome();
  }

  function setMsg(text, ok) {
    spellMsg.textContent = text;
    spellMsg.className = 'np-msg ' + (ok ? 'is-ok' : 'is-ng');
  }

  document.getElementById('subs-reset').addEventListener('click', function () {
    sub = { mode: 'all' };
    writeSub();
    refresh();
  });
  document.getElementById('spell-copy').addEventListener('click', function () {
    var v = spellOut.value;
    function done(ok) { setMsg(ok ? 'コピーしました。' : 'コピーできませんでした。枠の文字を選んでコピーしてください。', ok); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(v).then(function () { done(true); }, function () { done(false); });
    } else {
      try { spellOut.select(); done(document.execCommand('copy')); } catch (e) { done(false); }
    }
  });
  document.getElementById('spell-load').addEventListener('click', function () {
    var s = N.decodeSpell(spellIn.value, allIds);
    if (!s) { setMsg('読み込めませんでした。呪文の形式が違います。', false); return; }
    sub = s;
    writeSub();
    spellIn.value = '';
    refresh();
    setMsg('読み込みました。', true);
  });

  // ---- タブ ----
  function show(name, persist) {
    tabs.forEach(function (t) {
      var on = t.getAttribute('data-view') === name;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    panels.home.hidden = name !== 'home';
    panels.subs.hidden = name !== 'subs';
    if (persist) save(VIEW_KEY, name);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { show(t.getAttribute('data-view'), true); });
    t.addEventListener('keydown', function (e) {
      var n = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1;
      if (n < 0) return;
      e.preventDefault();
      n = (n + tabs.length) % tabs.length;
      tabs[n].focus();
      show(tabs[n].getAttribute('data-view'), true);
    });
  });
  show(load(VIEW_KEY) === 'subs' ? 'subs' : 'home', false);

  // ---- データ読み込み ----
  function getJson(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }
  status.hidden = false;
  status.textContent = '読み込み中…';
  Promise.all([getJson('/data/blogs.json'), getJson('/data/articles.json').catch(function () { return null; })]).then(function (res) {
    data = res[0];
    allIds = data.blogs.map(function (b) { return b.id; });
    data.blogs.forEach(function (b) { blogById[b.id] = b; blogCategory[b.id] = b.category; });
    articles = res[1] && Array.isArray(res[1].articles) ? res[1].articles : [];
    generated = res[1] && res[1].generated ? res[1].generated : '';
    if (generated) updated.textContent = 'データの最終更新: ' + N.fmtJst(generated);
    sub = readSub();
    renderChips();
    refresh();
  }, function () {
    status.hidden = false;
    status.textContent = '記事を読み込めませんでした。時間をおいてもう一度開いてください。';
  });
})();
