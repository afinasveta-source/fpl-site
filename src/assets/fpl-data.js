/* FPL: живые данные на сайте из базы (файлы /data/*.json, их собирает сервер раз в 10 минут).
   В файлах только люди с действующим согласием на публикацию. Нет данных — блок показывает «скоро». */
(function () {
  var EN = (document.documentElement.lang || 'ru').slice(0, 2) === 'en';
  var T = EN ? {
    empty: 'The rating will appear here once round results are transferred from the bot.',
    calib: 'Provisional rating: every artist has played {n} of 3 calibration rounds so far. Places can still change a lot.',
    updated: 'Updated {d}', none: 'No one found. Try another name.',
    rounds: 'rounds', masters: 'artists', leagueN: '{n} artists', range: '{a}–{b}',
    tw: 'TOP WORK', prov: 'provisional', calibShort: 'calibration {n}/3', place: 'Place'
  } : {
    empty: 'Рейтинг появится здесь, как только перенесём результаты туров из бота.',
    calib: 'Рейтинг предварительный: у всех пока {n} из 3 калибровочных туров. Места ещё могут заметно меняться.',
    updated: 'Обновлено {d}', none: 'Никого не нашли. Попробуйте другое имя.',
    rounds: 'туров', masters: 'мастеров', leagueN: '{n} мастеров', range: '{a}–{b}',
    tw: 'TOP WORK', prov: 'предварительный', calibShort: 'калибровка {n}/3', place: 'Место'
  };
  var LG = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };
  function f(s, o) { return s.replace(/\{(\w+)\}/g, function (m, k) { return o[k]; }); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function lg(l) { return l ? '<span class="lgb lgb--' + LG[l] + '">' + LG[l] + '</span>' : '<span class="lgb">—</span>'; }
  function date(iso) {
    try { return new Date(iso).toLocaleString(EN ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }) + (EN ? ' MSK' : ' МСК'); }
    catch (e) { return iso; }
  }
  function load(name) {
    return fetch('/data/' + name + '.json', { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw r.status; return r.json(); });
  }
  function season(data) { return (data && data.seasons && data.seasons[0]) || null; }

  // Главная: превью рейтинга
  var prev = document.querySelector('[data-fpl="rating-preview"]');
  // Страница рейтинга
  var rbody = document.getElementById('rbody');
  if (!prev && !rbody) return;

  load('rating').then(function (data) {
    var s = season(data), players = (s && s.players) || [];
    if (prev) renderPreview(players, data);
    if (rbody) renderPage(s, players, data);
  }).catch(function () {
    if (prev) renderPreview([], null);
    if (rbody) renderPage(null, [], null);
  });

  function renderPreview(players, data) {
    var empty = document.querySelector('[data-fpl="rating-empty"]');
    var body = prev.querySelector('tbody');
    if (!players.length) { prev.hidden = true; if (empty) { empty.textContent = T.empty; empty.hidden = false; } return; }
    body.innerHTML = players.slice(0, 5).map(function (p) {
      return '<tr><td>' + p.place + '</td><td>' + esc(p.name) + '</td><td>' + lg(p.league) + '</td><td>' + p.rating +
        (p.status === 'calibrating' ? ' <small class="prov">' + T.prov + '</small>' : '') + '</td><td>' + (p.top_work ? T.tw + (p.top_work > 1 ? ' ×' + p.top_work : '') : '—') + '</td></tr>';
    }).join('');
    var note = document.querySelector('[data-fpl="rating-note"]');
    var cal = players.filter(function (p) { return p.status === 'calibrating'; });
    if (note && cal.length) { note.textContent = f(T.calib, { n: Math.max.apply(null, cal.map(function (p) { return p.calibration || 1; })) }); note.hidden = false; }
  }

  function renderPage(s, players, data) {
    var empty = document.getElementById('rempty');
    var note = document.getElementById('rnote');
    var calNote = document.getElementById('calNote');
    var set = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    var hide = function (sel) { document.querySelectorAll(sel).forEach(function (el) { el.hidden = true; el.style.display = 'none'; }); };
    if (note) note.textContent = data && data.generated_at ? f(T.updated, { d: date(data.generated_at) }) : '';
    hide('[data-league="cal"]'); hide('.rfilters select, label[for="rcountry"]');
    set('rsCount', s ? s.rated : '—');
    hide('[data-stat="countries"]');
    // лиги: сколько мастеров и какой разброс рейтинга
    ['gold', 'silver', 'bronze'].forEach(function (l) {
      var box = document.querySelector('.rl--' + l), xs = players.filter(function (p) { return p.league === l; });
      if (!box) return;
      if (!xs.length) { box.hidden = true; box.style.display = 'none'; var t = document.querySelector('[data-league="' + LG[l] + '"]'); if (t) { t.hidden = true; t.style.display = 'none'; } return; }
      var r = xs.map(function (p) { return p.rating; });
      box.querySelector('b').textContent = f(T.range, { a: Math.min.apply(null, r), b: Math.max.apply(null, r) });
      box.querySelector('span:last-child').textContent = f(T.leagueN, { n: xs.length });
    });
    var cal = players.filter(function (p) { return p.status === 'calibrating'; });
    if (calNote && cal.length) { calNote.textContent = f(T.calib, { n: Math.max.apply(null, cal.map(function (p) { return p.calibration || 1; })) }); calNote.hidden = false; }

    // подиум
    var pod = document.getElementById('podium');
    if (pod) {
      if (players.length >= 3) {
        var order = [players[1], players[0], players[2]], cls = ['pod--2', 'pod--1', 'pod--3'];
        pod.innerHTML = order.map(function (p, i) {
          return '<article class="pod ' + cls[i] + '"><div class="pod-ph"><span class="pod-ini">' + esc((p.name || '?').trim().charAt(0)) + '</span><span class="pod-place">' + p.place + '</span></div>' +
            '<div class="pod-body"><h3>' + esc(p.name) + '</h3><span class="meta">' + lg(p.league) + '</span><div class="pod-row"><span class="rt">' + p.rating + '</span></div></div></article>';
        }).join('');
      } else { var sec = pod.closest('section'); if (sec) { sec.hidden = true; sec.style.display = 'none'; } }
    }

    var state = { league: 'all', q: '' };
    function render() {
      var q = state.q.trim().toLowerCase();
      var rows = players.filter(function (p) { return (state.league === 'all' || p.league === state.league) && (!q || String(p.name).toLowerCase().indexOf(q) > -1); });
      rbody.innerHTML = rows.map(function (p) {
        var aw = p.top_work ? '<span class="aw aw--tw">' + T.tw + (p.top_work > 1 ? ' ×' + p.top_work : '') + '</span>' : '<span class="none" style="color:#B9AEA2">—</span>';
        var rt = '<span class="rt-val">' + p.rating + '</span>' + (p.status === 'calibrating' ? '<span class="prov">' + T.prov + '</span>' : '');
        var games = p.status === 'calibrating' ? f(T.calibShort, { n: p.calibration || 1 }) : '';
        return '<tr><td class="c-pl"><span class="place">' + p.place + '</span></td>' +
          '<td class="c-who"><div class="who"><span class="ava">' + esc((p.name || '?').trim().charAt(0)) + '</span><div><b>' + esc(p.name) + '</b><span>' + games + '</span></div></div></td>' +
          '<td class="c-lg">' + lg(p.league) + '</td><td class="c-rt num">' + rt + '</td><td class="c-dl num"><span class="dl">—</span></td>' +
          '<td class="c-g num">1</td><td class="c-aw"><div class="awards">' + aw + '</div></td><td class="c-go"></td></tr>';
      }).join('');
      if (empty) { empty.textContent = players.length ? T.none : T.empty; empty.hidden = rows.length > 0; }
    }
    document.querySelectorAll('.tabs button[data-league]').forEach(function (b) {
      b.addEventListener('click', function () {
        document.querySelectorAll('.tabs button[data-league]').forEach(function (x) { x.setAttribute('aria-selected', x === b); });
        var v = b.getAttribute('data-league'); state.league = v === 'all' ? 'all' : v.toLowerCase(); render();
      });
    });
    var search = document.getElementById('rsearch');
    if (search) search.addEventListener('input', function (e) { state.q = e.target.value; render(); });
    render();
  }
})();
