/* Кабинет организатора (этап 5): итоги Игры — формат (путь, финал, веса, очки FPL), черновик итогов,
   решение о равных на местах 1–3, публикация (места, очки, дипломы). */
(function () {
  'use strict';
  var K = window.K, O = K.org, esc = K.esc, pill = K.pill;
  var LEAGUES = [['gold', 'Gold'], ['silver', 'Silver'], ['bronze', 'Bronze']];
  var LNAME = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };
  var TEXT = {
    already_published: 'Итоги уже опубликованы.', game_not_finished: 'Игра ещё не завершена — сначала «Завершить Игру» на странице Игры.',
    rounds_not_published: 'Не у всех туров опубликованы итоги судейства.', place_tie: 'На местах 1–3 есть равные итоги — решите порядок (кнопка «Решить порядок»).',
    no_rounds: 'В итог не входит ни один тур.', no_season_number: 'У сезона не указан номер — он нужен для номеров дипломов (раздел «Сезоны»).',
    no_game_number: 'Не указан номер Игры в сезоне — он нужен для номеров дипломов.', diploma_without_league: 'У кого-то из получающих диплом не указана лига — откройте участницу и укажите лигу (до публикации итогов это можно и после завершения Игры).',
    empty_rounds: 'В каком-то туре никто не сдал работу в срок — судить его нечего, в итог он войдёт без баллов.',
    final_unjudged: 'У кого-то из дошедших до финала нет оценки финала — в места и общий список они не войдут.',
    locked_after_start: 'Игра началась — формат итогов больше не меняется (по Правилам он объявляется до Игры).',
    unknown_round: 'Такого тура нет.', imported_game: 'Игра перенесена из бота — её итоги переносятся готовыми, кабинет их не пересчитывает.',
    diploma_number_taken: 'Номер диплома уже занят (номер сезона или Игры повторяется?). Проверьте номера сезона и Игры.', tie_targets: 'Порядок можно задать только для равных на местах 1–3.', results_published: 'Итоги опубликованы — Игру уже не вернуть в работу.'
  };
  O.addText(TEXT);   // коды ошибок этой страницы понятны и окнам подтверждения
  var t = function (c) { return TEXT[c] || O.text(c); };
  var err = function (r) { return TEXT[r.detail] || O.err(r); };
  var list = function (items, kind, head) {
    return items.length ? '<div class="note ' + kind + ' small">' + (head ? '<b>' + head + '</b>' : '') + '<ul>' + items.map(function (c) { return '<li>' + esc(t(c)) + '</li>'; }).join('') + '</ul></div>' : '';
  };
  var EXCL = { late: 'опоздала', withdrawn: 'вышла', disqualified: 'дисквалифицирована', admin: 'переведена вне конкурса', not_qualified_round1: 'выбыла в 1 туре' };
  var BEST = { place_1: '1 место', place_2: '2 место', place_3: '3 место', top10: 'TOP-10', top25: 'TOP-25', completion: 'завершение' };

  O.on(/^\/org\/games\/([0-9a-f-]{36})\/results$/, function (id) {
    K.load(['/api/org/events/' + id + '/results'], function (d) { draw(id, d); }, [['Игры и туры', '/org/games'], ['Итоги Игры']]);
  });

  function draw(id, d) {
    O.rd = d; O.rid = id;
    var pub = !!d.published_at;
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(d.event.title) + '</span><div class="between"><h1>Итоги Игры</h1>' +
      (pub ? pill('Опубликованы', 'ok') : d.event.status === 'finished' ? pill('Черновик', 'acc') : pill('После завершения Игры', 'plain')) + '</div></div>';
    h += formatCard(d);
    h += resultsCard(d, pub);
    K.page(h, [['Игры и туры', '/org/games'], [d.event.title, '/org/games/' + id], ['Итоги Игры']]);
    bindFormat(id, d);
  }

  /* ---------- формат ---------- */
  function formatCard(d) {
    var c = d.config, edit = d.config_editable, dis = edit ? '' : ' disabled';
    var rounds = d.rounds;
    var h = '<form class="card" id="f-rfmt" novalidate><h2>Формат итогов</h2>' +
      '<p class="small muted">Итог Игры = путь × ' + c.path_weight + '% + финал × ' + (100 - c.path_weight) + '%. Путь — средний балл выбранных туров, финал — балл последнего тура. ' +
      'Места 1–3 — в своей лиге, среди дошедших до финала; при равном итоге выше тот, у кого выше финал, дальше решаете вы. ' +
      'Порядок в лиге: сначала дошедшие до финала — по итогу, потом выбывшие позже — по баллу тура, где выбыли. Выбывшие в 1 туре, опоздавшие, вышедшие и дисквалифицированные не входят. ' +
      'TOP-10 и TOP-25 — тоже в своей лиге: места до 10 (25), но не больше 20% лиги; TOP-10 — если в лиге не меньше ' + c.points.top10_min + ' человек, TOP-25 — не меньше ' + c.points.top25_min + '.</p>' +
      (edit ? '' : '<div class="note small">' + esc(t('locked_after_start')) + '</div>');
    if (!rounds.length) return h + '<p class="muted">Туров пока нет — формат можно задать после того, как они появятся.</p></form>';
    h += '<div class="grid2">' + O.sel('rf-final', 'Финал', [['', 'Без финала (итог — средний балл туров)']].concat(rounds.map(function (r) { return [r.round_no, 'Тур ' + r.round_no + ' · ' + r.title]; })),
      c.final_round == null ? '' : c.final_round, dis) +
      O.txt('rf-w', 'Вес пути, %', c.path_weight, ' type="number" min="0" max="100" step="1"' + dis, 'Финал — остальное (по умолчанию 40 / 60).') + '</div>' +
      '<fieldset class="stack" data-s="g6"><legend class="small">Туры пути</legend>' + rounds.map(function (r) {
        return O.chk('rf-p' + r.round_no, 'Тур ' + r.round_no + ' · ' + esc(r.title), c.path_rounds.indexOf(r.round_no) >= 0, ' data-no="' + r.round_no + '"' + dis);
      }).join('') + '<p class="small muted">Финал в путь не входит, даже если отмечен.</p></fieldset>';
    var p = c.points;
    h += '<h3>Очки FPL</h3><p class="small muted">За итог Игры — одно, самое высокое достижение; TOP WORK — за каждую работу дополнительно. Значения можно поменять до старта Игры.</p>' +
      '<div class="table-wrap"><table class="otable ptable"><thead><tr><th scope="col">Лига</th><th scope="col" class="c">1 место</th><th scope="col" class="c">2 место</th><th scope="col" class="c">3 место</th></tr></thead><tbody>' +
      LEAGUES.map(function (l) {
        return '<tr><th scope="row" data-label="Лига">' + l[1] + '</th>' + [0, 1, 2].map(function (i) {
          return '<td class="c" data-label="' + (i + 1) + ' место"><input class="input num-in" type="number" min="0" max="1000" id="pt-' + l[0] + '-' + i + '" value="' + esc(p.places[l[0]][i]) + '" aria-label="' + l[1] + ', ' + (i + 1) + ' место"' + dis + '></td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div><div class="grid4">' +
      O.txt('pt-top10', 'TOP-10 лиги', p.top10, ' type="number" min="0" max="1000"' + dis) + O.txt('pt-top25', 'TOP-25 лиги', p.top25, ' type="number" min="0" max="1000"' + dis) +
      O.txt('pt-top10min', 'TOP-10 — от скольки человек в лиге', p.top10_min, ' type="number" min="0" max="100000"' + dis, 'Меньше — в этой лиге TOP-10 нет.') +
      O.txt('pt-top25min', 'TOP-25 — от скольки человек в лиге', p.top25_min, ' type="number" min="0" max="100000"' + dis, 'Меньше — в этой лиге TOP-25 нет.') +
      O.txt('pt-completion', 'Завершение (зачёт)', p.completion, ' type="number" min="0" max="1000"' + dis) + O.txt('pt-tw', 'TOP WORK, за работу', p.top_work, ' type="number" min="0" max="1000"' + dis) + '</div>' +
      (d.event.awards_points ? '' : '<p class="small muted">У этой Игры выключено «Даёт очки FPL» — очки не начисляются.</p>') +
      O.errBox + (edit ? '<button class="btn" type="submit">Сохранить формат</button>' : '') + '</form>';
    return h;
  }

  function bindFormat(id, d) {
    var f = document.getElementById('f-rfmt');
    if (!f || !d.config_editable || !d.rounds.length) return;
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var num = function (sel) { var v = f.querySelector(sel).value.trim(); return v === '' ? NaN : +v; };
      var final = f.querySelector('#rf-final').value, w = num('#rf-w');
      if (!(w >= 0 && w <= 100) || Math.round(w) !== w) { K.formError(f, 'Вес пути — целое число от 0 до 100.'); return; }
      var path = Array.prototype.filter.call(f.querySelectorAll('input[data-no]'), function (x) { return x.checked; }).map(function (x) { return +x.getAttribute('data-no'); });
      var places = {}, bad = false;
      LEAGUES.forEach(function (l) { places[l[0]] = [0, 1, 2].map(function (i) { var v = num('#pt-' + l[0] + '-' + i); if (!(v >= 0 && v <= 1000)) bad = true; return v; }); });
      var pts = { places: places, top10: num('#pt-top10'), top25: num('#pt-top25'), top25_min: num('#pt-top25min'), top10_min: num('#pt-top10min'), completion: num('#pt-completion'), top_work: num('#pt-tw') };
      ['top10', 'top25', 'completion', 'top_work'].forEach(function (k) { if (!(pts[k] >= 0 && pts[k] <= 1000) || Math.round(pts[k]) !== pts[k]) bad = true; });
      ['top10_min', 'top25_min'].forEach(function (k) { if (!(pts[k] >= 0 && pts[k] <= 100000) || Math.round(pts[k]) !== pts[k]) bad = true; });
      if (bad) { K.formError(f, 'Очки — целые числа от 0 до 1000.'); return; }
      var body = { no_final: final === '', final_round: final === '' ? null : +final, path_rounds: path, path_weight: w, points: pts };
      O.send('PUT', '/api/org/events/' + id + '/results/format', body, f, function (nd) { K.toast('Формат сохранён'); draw(id, nd); });
    });
  }

  /* ---------- итоги ---------- */
  function resultsCard(d, pub) {
    var h = '<section class="card"><div class="between"><h2>' + (pub ? 'Опубликованные итоги' : 'Итоги (черновик)') + '</h2>' +
      (pub ? '<span class="small muted">' + esc(O.when(d.published_at)) + '</span>' : '') + '</div>';
    if (!pub) h += list(d.checks.problems.filter(function (c) { return c !== 'already_published'; }), 'bad', 'Чтобы опубликовать:') + list(d.checks.warnings, 'warn', 'Обратите внимание:');
    var rows = d.rows || [];
    var noLeague = pub ? [] : rows.filter(function (r) { return r.diploma && !r.league; });
    if (noLeague.length) h += '<div class="note bad small"><b>Без лиги (диплом без лиги не выдать):</b> ' + noLeague.map(function (r) {
      return '<button class="lnk" type="button" data-href="/org/participants/' + r.id + '">' + esc(r.name) + '</button>';
    }).join(', ') + '</div>';
    var ties = {};
    rows.forEach(function (r) { if (r.tie && r.tie.length) ties[r.league + ':' + r.tie.slice().sort().join(',')] = { league: r.league, ids: r.tie }; });
    Object.keys(ties).forEach(function (k) {
      var x = ties[k];
      h += '<div class="note bad small"><b>Равные на месте ' + rowOf(rows, x.ids[0]).league_rank + ', лига ' + esc(LNAME[x.league]) + ':</b> ' + esc(x.ids.map(function (i) { return rowOf(rows, i).name; }).join(', ')) +
        '<div class="row"><button class="btn sec small" type="button" data-act="rTie" data-l="' + x.league + '" data-ids="' + x.ids.join(',') + '">Решить порядок</button></div></div>';
    });
    if (!rows.length) return h + '<p class="muted">В Игре пока нет участниц.</p></section>';
    var final = d.config.final_round;
    h += '<div class="table-wrap"><table class="otable rtable"><thead><tr><th scope="col">Общее место</th><th scope="col">Участница</th><th scope="col">Лига, место</th>' +
      '<th scope="col" class="c">Путь</th><th scope="col" class="c">Финал</th><th scope="col" class="c">Итог</th><th scope="col">Зачёт, диплом</th><th scope="col" class="c">Очки FPL</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var place = (r.award_place ? pill(r.award_place + ' место', r.award_place === 1 ? 'ok' : 'acc') : r.league_rank ? r.league_rank + ' в лиге' : '—') +
          (r.top10 ? ' ' + pill('TOP-10', 'info') : r.top25 ? ' ' + pill('TOP-25', 'info') : '');
        var who = r.excluded ? pill(EXCL[r.excluded] || r.excluded, 'plain') : !r.finalist && r.stage ? '<span class="small muted">выбыла после тура ' + r.stage + '</span>' : !r.stage ? '<span class="small muted">не судилась</span>' : '';
        var dip = (r.counted ? pill('Зачёт', 'ok') : '') + ' ' + (r.certificate ? '<span class="small nowrap">' + esc(r.certificate) + '</span>' : r.diploma ? pill('Диплом', 'acc') : '');
        var pts = r.points && r.points.total != null ? '<b class="num">' + r.points.total + '</b>' + (r.points.best ? '<span class="small muted"> ' + esc(BEST[r.points.best] || '') + (r.points.top_work ? ' + TOP WORK ' + r.points.top_work : '') + '</span>' : '') : '—';
        return '<tr class="' + (r.tie && r.tie.length ? 'tied' : '') + '"><td data-label="Общее место">' + (r.overall_rank || '—') + '</td>' +
          '<td data-label="Участница"><button class="lnk" type="button" data-href="/org/participants/' + r.id + '">' + esc(r.name) + '</button> ' + who + '</td>' +
          '<td data-label="Лига, место">' + esc(r.league ? LNAME[r.league] : '—') + ' · ' + place + '</td>' +
          '<td class="c" data-label="Путь">' + fmt(r.path) + '</td><td class="c" data-label="Финал">' + (final == null ? '—' : fmt(r.final)) + '</td>' +
          '<td class="c" data-label="Итог"><b class="num">' + fmt(r.total) + '</b></td><td data-label="Зачёт, диплом">' + dip + '</td>' +
          '<td class="c" data-label="Очки FPL">' + pts + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    if (!pub) {
      var can = !d.checks.problems.length;
      h += '<p class="small muted">Участницы увидят своё место в лиге, TOP-10/25, итог, очки FPL и номер диплома. После публикации итоги не пересчитываются, а Игру нельзя вернуть в работу.</p>' +
        '<button class="btn wide" type="button" data-act="rPublish"' + (can ? '' : ' disabled') + '>Опубликовать итоги Игры</button>';
    }
    return h + '</section>';
  }
  function fmt(v) { return v == null ? '—' : String(Math.round(v * 100) / 100).replace('.', ','); }
  function rowOf(rows, id) { return rows.filter(function (r) { return r.id === id; })[0] || {}; }

  K.actions.rPublish = function () {
    O.confirm({ title: 'Опубликовать итоги Игры?', text: 'Места, очки FPL и дипломы будут выданы, участницы получат уведомления. Отменить нельзя.',
      ok: 'Опубликовать', path: '/api/org/events/' + O.rid + '/results/publish',
      done: function (nd) { K.toast('Итоги опубликованы: дипломов — ' + nd.summary.diplomas); draw(O.rid, nd); } });
  };
  K.actions.rTie = function (b) {
    var ids = b.getAttribute('data-ids').split(','), league = b.getAttribute('data-l'), rows = O.rd.rows;
    O.confirm({ title: 'Порядок равных', html: '<p>Укажите место каждой (1 — выше). Решение и причина сохранятся в журнале.</p><div class="stack" data-s="g6">' +
      ids.map(function (i) {
        return O.sel('tie-' + i, esc(rowOf(rows, i).name), ids.map(function (_, k) { return [k + 1, String(k + 1)]; }), ids.indexOf(i) + 1, ' data-id="' + i + '"');
      }).join('') + '</div>', ok: 'Сохранить порядок', reason: true, path: '/api/org/events/' + O.rid + '/results/tie',
      validate: function () {
        var v = Array.prototype.map.call(document.querySelectorAll('.modal select[data-id]'), function (s) { return s.value; });
        return v.filter(function (x, i) { return v.indexOf(x) !== i; }).length ? 'У каждой должно быть своё место.' : null;
      },
      body: function (reason) {
        var pairs = Array.prototype.map.call(document.querySelectorAll('.modal select[data-id]'), function (s) { return [+s.value, s.getAttribute('data-id')]; });
        pairs.sort(function (a, c) { return a[0] - c[0]; });
        return { league: league, order: pairs.map(function (p) { return p[1]; }), reason: reason };
      }, done: function (nd) { K.toast('Порядок сохранён'); draw(O.rid, nd); } });
  };
})();
