/* FPL: живые данные на сайте из базы (файлы /data/*.json, их собирает сервер раз в 10 минут).
   В файлах только люди с действующим согласием на публикацию. Нет данных — блок показывает «скоро». */
(function () {
  var EN = (document.documentElement.lang || 'ru').slice(0, 2) === 'en';
  var T = EN ? {
    empty: 'The rating will appear here once round results are transferred from the bot.',
    frozenEmpty: 'The overall rating is not published while a Game is running (Rules, 7.3). It will appear here after {g} ends.',
    frozenNote: 'Rating as of the start of {g}: it does not change during the Game and will be updated after it ends.',
    frozenLink: 'League rating', frozenDd: 'at the start of the Game',
    liveNote: 'Rating after round {n} of {g}: during the Game it is updated after every round.',
    calib: 'Provisional rating: every artist has played {n} of 3 calibration rounds so far. Places can still change a lot.',
    updated: 'Updated {d}', none: 'No one found. Try another name.',
    rounds: 'rounds', masters: 'artists', leagueN: '{n} artists', range: '{a}–{b}',
    tw: 'TOP WORK', prov: 'provisional', calibShort: 'calibration {n}/3', place: 'Place',
    afterRound: 'Rating after round {n}', roundShort: 'Round {n}', twCount: 'TOP WORK: {n}',
    twHidden: '{n} more without a published name', twOf: 'TOP WORK, {r}:', twAll: 'all rounds'
  } : {
    empty: 'Рейтинг появится здесь, как только перенесём результаты туров из бота.',
    frozenEmpty: 'Во время Игры общий рейтинг не публикуется (Правила, п. 7.3). Он появится здесь после окончания {g}.',
    frozenNote: 'Рейтинг на начало {g}: во время Игры он не меняется и обновится после её окончания.',
    frozenLink: 'Рейтинг лиги', frozenDd: 'на начало Игры',
    liveNote: 'Рейтинг после {n} тура {g}: во время Игры обновляется после каждого тура.',
    calib: 'Рейтинг предварительный: у всех пока {n} из 3 калибровочных туров. Места ещё могут заметно меняться.',
    updated: 'Обновлено {d}', none: 'Никого не нашли. Попробуйте другое имя.',
    rounds: 'туров', masters: 'мастеров', leagueN: '{n} мастеров', range: '{a}–{b}',
    tw: 'TOP WORK', prov: 'предварительный', calibShort: 'калибровка {n}/3', place: 'Место',
    afterRound: 'Рейтинг после {n} тура', roundShort: '{n} тур', twCount: 'TOP WORK: {n}',
    twHidden: 'ещё {n} — без публикации имени', twOf: 'TOP WORK, {r}:', twAll: 'все туры'
  };
  var LG = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };
  function masters(n) {
    if (EN) return n + (n === 1 ? ' artist' : ' artists');
    var m10 = n % 10, m100 = n % 100;
    return n + (m10 === 1 && m100 !== 11 ? ' мастер' : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? ' мастера' : ' мастеров');
  }
  function f(s, o) { return s.replace(/\{(\w+)\}/g, function (m, k) { return o[k]; }); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var LG_ORDER = ['gold', 'silver', 'bronze'];
  // TOP WORK всегда с лигой работы в туре: «TOP WORK Gold» (17.10). Просто «TOP WORK» — только если лига неизвестна.
  function twName(l) { return T.tw + (l && LG[l] ? ' ' + LG[l] : ''); }
  // {gold: 2, silver: 1} → «TOP WORK Gold ×2 · TOP WORK Silver»
  function twBadges(byLeague, total) {
    var keys = LG_ORDER.filter(function (k) { return byLeague && byLeague[k]; });
    if (!keys.length) return total ? ['<span class="aw aw--tw">' + T.tw + (total > 1 ? ' ×' + total : '') + '</span>'] : [];
    return keys.map(function (k) { return '<span class="aw aw--tw">' + esc(twName(k)) + (byLeague[k] > 1 ? ' ×' + byLeague[k] : '') + '</span>'; });
  }
  function lg(l) { return l ? '<span class="lgb lgb--' + LG[l] + '">' + LG[l] + '</span>' : '<span class="lgb">—</span>'; }
  function date(iso) {
    try { return new Date(iso).toLocaleString(EN ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }) + (EN ? ' MSK' : ' МСК'); }
    catch (e) { return iso; }
  }
  function load(name) {
    return fetch('/data/' + name + '.json', { cache: 'no-cache' }).then(function (r) { if (!r.ok) throw r.status; return r.json(); });
  }
  // «Игры 01» / «Game 01» — для подписей замороженного рейтинга
  function gameName(fr) {
    if (!fr) return '';
    var no = fr.game_no != null ? (fr.game_no < 10 ? '0' : '') + fr.game_no : '';
    return EN ? 'Game ' + no : 'Игры ' + no;
  }
  function season(data) { return (data && data.seasons && data.seasons[0]) || null; }

  // Итоги туров (games.json): TOP WORK на главной и в «Играх», «Рейтинг после N тура»
  var twRounds = document.querySelector('[data-fpl="tw-rounds"]');
  var twHome = document.querySelector('[data-fpl="tw-home"]');
  var afters = document.querySelectorAll('[data-fpl-after]');
  if (twRounds || twHome || afters.length) {
    load('games').then(renderGames).catch(function () {});
  }

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

  function renderGames(data) {
    var game = ((data && data.games) || []).filter(function (g) { return g.season_no === 1 && g.game_no === 1; })[0];
    if (!game) return;
    var pub = (game.rounds || []).filter(function (r) { return r.published; });
    if (!pub.length) return;
    var last = Math.max.apply(null, pub.map(function (r) { return r.no; }));
    // идёт Игра — рейтинг на сайте на её начало (Правила, п. 7.3), если организатор не разрешил текущий (rating_live, 17.10)
    var running = game.status === 'active' && !game.rating_live;
    afters.forEach(function (el) {
      var arrow = /→\s*$/.test(el.textContent) ? ' →' : '';
      var dd = el.getAttribute('data-fpl-after') === 'dd';
      el.textContent = running ? (dd ? T.frozenDd : T.frozenLink + arrow) : dd ? f(T.roundShort, { n: last }) : f(T.afterRound, { n: last }) + arrow;
    });
    function title(r) { return (r.title_i18n && r.title_i18n[EN ? 'en' : 'ru']) || r.title; }
    // TOP WORK тура — по лигам: «TOP WORK Gold · 5» и имена; без лиги (старые данные) — общим списком
    function byLeague(r) {
      var per = r.top_work_leagues || {}, known = LG_ORDER.some(function (k) { return per[k]; });
      var named = function (k) { return (r.top_work || []).filter(function (w) { return (w.league || '') === k; }); };
      var out = LG_ORDER.map(function (k) { var sh = named(k); return { league: k, shown: sh, count: Math.max(known ? (per[k] || 0) : sh.length, sh.length) }; });
      var rest = named(''), restCount = known ? rest.length : r.top_work_count - out.reduce(function (a, g) { return a + g.count; }, 0);
      out.push({ league: '', shown: rest, count: Math.max(restCount, rest.length) });
      return out.filter(function (g) { return g.count > 0; });
    }
    if (twRounds) {
      var html = pub.filter(function (r) { return r.top_work_count > 0; }).map(function (r) {
        return '<article class="tw-round"><h3>' + esc(title(r)) + '</h3>' + byLeague(r).map(function (g) {
          var hidden = g.count - g.shown.length;
          return '<p class="meta"><b>' + esc(twName(g.league)) + '</b> · ' + g.count + '</p>' +
            (g.shown.length ? '<ul class="tw-names">' + g.shown.map(function (w) { return '<li>' + esc(w.name) + '</li>'; }).join('') + '</ul>' : '') +
            (hidden > 0 ? '<p class="meta">' + f(T.twHidden, { n: hidden }) + '</p>' : '');
        }).join('') + '</article>';
      }).join('');
      if (html) { twRounds.innerHTML = html; var sec = twRounds.closest('[data-fpl="tw-section"]'); if (sec) sec.hidden = false; }
    }
    if (twHome) {
      var lr = pub.filter(function (r) { return r.no === last; })[0];
      if (lr && lr.top_work && lr.top_work.length) {
        twHome.innerHTML = byLeague(lr).filter(function (g) { return g.shown.length; }).map(function (g) {
          return '<b>' + esc(twName(g.league)) + ', ' + esc(title(lr)) + ':</b> ' + g.shown.map(function (w) { return esc(w.name); }).join(', ');
        }).join(' · ') + ' · <a class="text-link" href="games.html#g01">' + T.twAll + '</a>';
        twHome.hidden = false;
      }
    }
  }

  function renderPreview(players, data) {
    var empty = document.querySelector('[data-fpl="rating-empty"]');
    var body = prev.querySelector('tbody');
    var fr = data && data.frozen;
    if (!players.length) { prev.hidden = true; if (empty) { empty.textContent = fr ? f(T.frozenEmpty, { g: gameName(fr) }) : T.empty; empty.hidden = false; } return; }
    body.innerHTML = players.slice(0, 5).map(function (p) {
      return '<tr><td>' + p.place + '</td><td>' + esc(p.name) + '</td><td>' + lg(p.league) + '</td><td>' + p.rating +
        (p.status === 'calibrating' ? ' <small class="prov">' + T.prov + '</small>' : '') + '</td><td>' + (p.top_work ? twBadges(p.top_work_leagues, p.top_work).join(' ') : '—') + '</td></tr>';
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
    var show = function (el) { if (el) { el.hidden = false; el.style.display = ''; } };
    var fr = data && data.frozen;
    var live = data && data.live;
    if (note) note.textContent = (fr && players.length ? f(T.frozenNote, { g: gameName(fr) }) + ' ' : '') +
      (live && live.after_round && players.length ? f(T.liveNote, { n: live.after_round, g: gameName(live) }) + ' ' : '') +
      (data && data.generated_at ? f(T.updated, { d: date(data.generated_at) }) : '');
    set('rsCount', s ? s.rated : '—');
    if (players.length) { show(document.querySelector('.rleagues')); show(document.querySelector('.rcontrols')); }
    // лиги: сколько мастеров и какой разброс рейтинга
    ['gold', 'silver', 'bronze'].forEach(function (l) {
      var box = document.querySelector('.rl--' + l), xs = players.filter(function (p) { return p.league === l; });
      if (!box) return;
      if (!xs.length) { box.hidden = true; var t = document.querySelector('[data-league="' + LG[l] + '"]'); if (t) { t.hidden = true; t.style.display = 'none'; } return; }
      var r = xs.map(function (p) { return p.rating; });
      box.querySelector('b').textContent = f(T.range, { a: Math.min.apply(null, r), b: Math.max.apply(null, r) });
      box.querySelector('span:last-child').textContent = masters(xs.length);
      show(box);
    });
    var cal = players.filter(function (p) { return p.status === 'calibrating'; });
    if (calNote && cal.length) { calNote.textContent = f(T.calib, { n: Math.max.apply(null, cal.map(function (p) { return p.calibration || 1; })) }); calNote.hidden = false; }

    // подиум
    var pod = document.getElementById('podium');
    if (pod) {
      if (players.length >= 3) {
        show(document.getElementById('podiumSec'));
        var order = [players[1], players[0], players[2]], cls = ['pod--2', 'pod--1', 'pod--3'];
        pod.innerHTML = order.map(function (p, i) {
          return '<article class="pod ' + cls[i] + '"><div class="pod-ph"><span class="pod-ini">' + esc((p.name || '?').trim().charAt(0)) + '</span><span class="pod-place">' + p.place + '</span></div>' +
            '<div class="pod-body"><h3>' + esc(p.name) + '</h3><span class="meta">' + lg(p.league) + '</span><div class="pod-row"><span class="rt">' + p.rating + '</span></div></div></article>';
        }).join('');
      }
    }

    var state = { league: 'all', q: '' };
    function render() {
      var q = state.q.trim().toLowerCase();
      var rows = players.filter(function (p) { return (state.league === 'all' || p.league === state.league) && (!q || String(p.name).toLowerCase().indexOf(q) > -1); });
      rbody.innerHTML = rows.map(function (p) {
        var aw = p.top_work ? twBadges(p.top_work_leagues, p.top_work).join('') : '<span class="none" style="color:#B9AEA2">—</span>';
        var rt = '<span class="rt-val">' + p.rating + '</span>' + (p.status === 'calibrating' ? '<span class="prov">' + T.prov + '</span>' : '');
        var games = p.status === 'calibrating' ? f(T.calibShort, { n: p.calibration || 1 }) : '';
        return '<tr><td class="c-pl"><span class="place">' + p.place + '</span></td>' +
          '<td class="c-who"><div class="who"><span class="ava">' + esc((p.name || '?').trim().charAt(0)) + '</span><div><b>' + esc(p.name) + '</b><span>' + games + '</span></div></div></td>' +
          '<td class="c-lg">' + lg(p.league) + '</td><td class="c-rt num">' + rt + '</td>' +
          '<td class="c-aw"><div class="awards">' + aw + '</div></td></tr>';
      }).join('');
      if (empty) { empty.textContent = players.length ? T.none : (fr ? f(T.frozenEmpty, { g: gameName(fr) }) : T.empty); empty.hidden = rows.length > 0; }
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
