// FPL: проверка живого сайта. Запуск: node site-check.js [базовый_URL] > report.json
// Проверка сборки до выкладки: FPL_LOCAL=1 node site-check.js http://127.0.0.1:8099 (или tests/check-build.sh)
// — без проверок сервера (API, HTTPS); заглушки и пример-данные уходят в content, в problems — только поломки; код выхода 1, если они есть.
// Нужен playwright (npm i -g playwright или NODE_PATH на глобальные модули).
const { chromium } = require('playwright');
const tls = require('tls');
const BASE = (process.argv[2] || 'https://facepaintingleague.com').replace(/\/$/, '');
const LOCAL = !!process.env.FPL_LOCAL;
const PAGES = ['index','games','rating','master','gallery','find','diploma','rules','about','privacy','feedback'];
const PATHS = [].concat(...PAGES.map(p => [p === 'index' ? '/' : '/' + p + '.html', p === 'index' ? '/ru/' : '/ru/' + p + '.html']));
const PLACEHOLDER = /\[(?:N|X|Y|ник|почта|реквизиты[^\]]*|Имя[^\]]*|имя[^\]]*|фото[^\]]*|работа[^\]]*|город[^\]]*|страна|Страна|СТРАНА|текст[^\]]*|срок[^\]]*|Специализация|стаж|логотип|медиа-партнёр|Победитель|email|organizer[^\]]*|name[^\]]*|photo[^\]]*|work[^\]]*|city[^\]]*|country[^\]]*)\]/g;
const DEMO_NAMES = ['Анна Петрова','Мария Иванова','Lucía Martín','Nino Beridze','Anna Petrova'];

function certDays(host) {
  return new Promise(res => {
    const s = tls.connect(443, host, { servername: host, timeout: 15000 }, () => {
      const c = s.getPeerCertificate(); s.end();
      res(c && c.valid_to ? Math.round((new Date(c.valid_to) - Date.now()) / 864e5) : null);
    });
    s.on('error', e => res('error: ' + e.message)); s.on('timeout', () => { s.destroy(); res('timeout'); });
  });
}

(async () => {
  const host = new URL(BASE).host;
  const R = { base: BASE, at: new Date().toISOString(), cert_days_left: LOCAL ? 'local' : await certDays(host), pages: {}, links_broken: [], problems: [], content: [] };
  const b = await chromium.launch();
  const ctx = await b.newContext();
  // служебные адреса
  for (const pth of [...(LOCAL ? [] : ['/api/health']), '/sitemap.xml', '/robots.txt', '/assets/site.css', '/assets/consent.js']) {
    try { const r = await ctx.request.get(BASE + pth, { timeout: 20000 }); R.pages[pth] = { status: r.status() };
      if (r.status() !== 200) R.problems.push(`${pth}: ответ ${r.status()}`);
      if (pth === '/api/health' && !(await r.text()).includes('"ok"')) R.problems.push('/api/health: нет {"ok": true}');
    } catch (e) { R.problems.push(`${pth}: не открывается (${e.message.split('\n')[0]})`); }
  }
  const allLinks = new Set();
  for (const pth of PATHS) {
    for (const [w, h, tag] of [[390, 844, 'телефон'], [1280, 860, 'компьютер']]) {
      const p = await b.newPage({ viewport: { width: w, height: h } });
      const errs = [], ym = [];
      p.on('pageerror', e => errs.push(e.message));
      p.on('console', m => { if (m.type() === 'error' && !/favicon/.test(m.text())) errs.push(m.text()); });
      p.on('request', r => { if (/mc\.yandex\.ru/.test(r.url())) ym.push(r.url()); });
      let status = 0;
      try { const resp = await p.goto(BASE + pth, { waitUntil: 'networkidle', timeout: 45000 }); status = resp ? resp.status() : 0; }
      catch (e) { R.problems.push(`${pth} (${tag}): не загрузилась — ${e.message.split('\n')[0]}`); await p.close(); continue; }
      await p.waitForTimeout(600);
      const info = await p.evaluate(({ PH, DEMO }) => {
        const vis = e => { const s = getComputedStyle(e), r = e.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
        const text = document.body.innerText;
        const ph = [...new Set(text.match(new RegExp(PH, 'g')) || [])];
        const demo = DEMO.filter(n => text.includes(n));
        const ctaDead = [...document.querySelectorAll('button')].filter(vis).filter(b => /^(Участвовать|Следить|Join|Follow)/i.test(b.textContent.trim()) && !b.closest('form') && !b.onclick && !b.dataset.href).map(b => b.textContent.trim());
        const hashLinks = [...document.querySelectorAll('a[href="#"]')].filter(vis).map(a => a.textContent.trim().slice(0, 40)).filter(t => !/Настройки cookie|Cookie settings/.test(t));
        const links = [...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.startsWith(location.origin));
        return { h1: (document.querySelector('h1') || {}).textContent || '', overflow: document.documentElement.scrollWidth - innerWidth, ph, demo, ctaDead: [...new Set(ctaDead)], hashLinks: [...new Set(hashLinks)], links, banner: !!document.querySelector('.ckbar') };
      }, { PH: PLACEHOLDER.source, DEMO: DEMO_NAMES });
      info.links.forEach(l => allLinks.add(l.split('#')[0]));
      const key = `${pth} (${tag})`;
      R.pages[key] = { status, h1: info.h1.trim().slice(0, 60), overflow: info.overflow, errors: errs.slice(0, 5) };
      if (status !== 200) R.problems.push(`${key}: ответ ${status}`);
      if (info.overflow > 2) R.problems.push(`${key}: страница шире экрана на ${info.overflow}px`);
      if (errs.length) R.problems.push(`${key}: ошибки в коде — ${errs.slice(0, 2).join(' | ')}`);
      if (tag === 'телефон') {
        if (info.ph.length) (LOCAL ? R.content : R.problems).push(`${pth}: заглушки на странице — ${info.ph.slice(0, 8).join(', ')}`);
        if (info.demo.length) (LOCAL ? R.content : R.problems).push(`${pth}: пример-данные вместо настоящих — ${info.demo.join(', ')}`);
        if (info.ctaDead.length) R.problems.push(`${pth}: кнопки никуда не ведут — ${info.ctaDead.join(', ')}`);
        if (info.hashLinks.length) (LOCAL && /master\.html$/.test(pth) ? R.content : R.problems).push(`${pth}: пустые ссылки «#» — ${info.hashLinks.slice(0, 6).join(', ')}`);
        if (!info.banner) R.problems.push(`${pth}: нет плашки cookie при первом визите`);
        if (ym.length) R.problems.push(`${pth}: Яндекс Метрика загрузилась ДО согласия`);
      }
      await p.close();
    }
  }
  // согласие → Метрика
  try { const p = await b.newPage(); const ym = []; p.on('request', r => { if (/mc\.yandex\.ru/.test(r.url())) ym.push(1); });
    await p.goto(BASE + '/ru/', { waitUntil: 'networkidle' }); await p.click('.ck-yes', { timeout: 5000 }); await p.waitForTimeout(2500);
    if (!ym.length) R.problems.push('После «Разрешить» Яндекс Метрика не загрузилась'); await p.close();
  } catch (e) { R.problems.push('Плашка cookie: не удалось нажать «Разрешить» — ' + e.message.split('\n')[0]); }
  // проверка диплома — образец номера
  try { const p = await b.newPage(); await p.goto(BASE + '/ru/diploma.html?n=FPL-S1-01-0247', { waitUntil: 'networkidle' }); await p.waitForTimeout(800);
    const t = await p.evaluate(() => document.body.innerText); R.diploma_sample = /подтвержд/i.test(t) ? 'подтверждается' : 'не подтверждается'; await p.close();
  } catch (e) { R.problems.push('Проверка диплома: страница не отвечает'); }
  // битые внутренние ссылки
  // /kabinet/ — отдельное приложение на том же домене: в локальной сборке его нет, на живом сайте проверяется как обычная ссылка
  for (const l of allLinks) { if (LOCAL && new URL(l).pathname.startsWith('/kabinet/')) continue; try { const r = await ctx.request.get(l, { timeout: 20000 }); if (r.status() >= 400) R.links_broken.push(`${l} → ${r.status()}`); } catch (e) { R.links_broken.push(`${l} → не открывается`); } }
  if (R.links_broken.length) R.problems.push(`Битые ссылки: ${R.links_broken.slice(0, 10).join('; ')}`);
  if (typeof R.cert_days_left === 'number' && R.cert_days_left < 21) R.problems.push(`Сертификат HTTPS истекает через ${R.cert_days_left} дн.`);
  if (!LOCAL && typeof R.cert_days_left !== 'number') R.problems.push(`Сертификат HTTPS: не удалось проверить (${R.cert_days_left})`);
  await b.close();
  console.log(JSON.stringify(R, null, 1));
  if (LOCAL && R.problems.length) process.exitCode = 1;
})();
