/* FPL: плашка cookie и Яндекс Метрика (включается только после «Разрешить») */
(function () {
  var YM_ID = 113449555, KEY = 'fpl-consent';
  var en = (document.documentElement.lang || '').indexOf('en') === 0;
  var T = en ? {
    text: 'We use analytics cookies (Yandex Metrica) to see how the site is used. They are enabled only if you allow them.',
    more: 'Privacy policy', yes: 'Allow', no: 'Decline', settings: 'Cookie settings', href: (location.pathname.indexOf('/ru/') === 0 ? '../' : '') + 'privacy.html#p6'
  } : {
    text: 'Мы используем аналитические cookie (Яндекс Метрика), чтобы понимать, как пользуются сайтом. Они включаются, только если вы разрешите.',
    more: 'Политика конфиденциальности', yes: 'Разрешить', no: 'Отказаться', settings: 'Настройки cookie', href: 'privacy.html#p6'
  };
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }

  function loadMetrika() {
    if (window.ym) return;
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0];
      k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    window.ym(YM_ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: false });
  }
  function dropMetrikaCookies() {
    document.cookie.split(';').forEach(function (c) {
      var n = c.split('=')[0].trim();
      if (/^_ym|^yandexuid|^yabs/.test(n)) {
        document.cookie = n + '=; Max-Age=0; path=/';
        document.cookie = n + '=; Max-Age=0; path=/; domain=.' + location.hostname.replace(/^www\./, '');
      }
    });
  }

  var css = '.ckbar{position:fixed; z-index:1000; left:16px; bottom:16px; max-width:440px; background:#1E1B18; color:#F3EEE8; border:1px solid rgba(255,255,255,.12); border-radius:14px; padding:18px 18px 16px; box-shadow:0 12px 40px rgba(0,0,0,.35); font:500 14px/1.5 var(--f-body,system-ui,sans-serif)}' +
    '.ckbar p{margin:0}.ckbar a{color:#FF9A66}' +
    '.ckbar-b{display:flex; gap:8px; margin-top:14px; flex-wrap:wrap}' +
    '.ckbar button{flex:1; min-width:120px; cursor:pointer; border-radius:10px; padding:11px 14px; font:600 14px/1 var(--f-body,system-ui,sans-serif); border:1.5px solid rgba(255,255,255,.3); background:transparent; color:#F3EEE8}' +
    '.ckbar button.ck-yes{background:#F2601F; border-color:#F2601F; color:#fff}' +
    '.ckbar button:focus-visible{outline:2px solid #FF9A66; outline-offset:2px}' +
    '@media (max-width:640px){.ckbar{left:12px; right:12px; bottom:84px; max-width:none}}';

  function show() {
    if (document.querySelector('.ckbar')) return;
    if (!document.getElementById('ckcss')) { var s = document.createElement('style'); s.id = 'ckcss'; s.textContent = css; document.head.appendChild(s); }
    var d = document.createElement('div');
    d.className = 'ckbar'; d.setAttribute('role', 'dialog'); d.setAttribute('aria-label', T.settings);
    d.innerHTML = '<p>' + T.text + ' <a href="' + T.href + '">' + T.more + '</a></p>' +
      '<div class="ckbar-b"><button type="button" class="ck-no">' + T.no + '</button><button type="button" class="ck-yes">' + T.yes + '</button></div>';
    document.body.appendChild(d);
    d.querySelector('.ck-yes').addEventListener('click', function () { set('yes'); d.remove(); loadMetrika(); });
    d.querySelector('.ck-no').addEventListener('click', function () {
      var was = get() === 'yes'; set('no'); d.remove(); dropMetrikaCookies(); if (was) location.reload();
    });
  }

  function footerLink() {
    var col = null;
    document.querySelectorAll('.site-footer div').forEach(function (div) {
      if (div.querySelector('a[href*="privacy.html"]')) col = div;
    });
    if (!col || col.querySelector('[data-ck]')) return;
    var a = document.createElement('a'); a.href = '#'; a.setAttribute('data-ck', ''); a.textContent = T.settings;
    a.addEventListener('click', function (e) { e.preventDefault(); show(); });
    col.appendChild(a);
  }

  function start() {
    footerLink();
    var v = get();
    if (v === 'yes') loadMetrika(); else if (v !== 'no') show();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
