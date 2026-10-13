/* Кабинет организатора (этап 4): судейство тура — настройка, запуск, ход оценки, граница прохода, переголосование,
   решение организатора, публикация итогов с FPL Rating. */
(function () {
  'use strict';
  var K = window.K, O = K.org, esc = K.esc, pill = K.pill;
  var LEAGUES = [['bronze', 'Bronze'], ['silver', 'Silver'], ['gold', 'Gold']];
  var TEXT = {
    game_not_active: 'Игра ещё не началась (или уже завершена).', round_not_published: 'Тур ещё черновик.',
    judging_started: 'Судейство уже начато — настройка не меняется.', early_started: 'Первую лигу уже судят.',
    early_needs_leagues: 'Чтобы судить первую лигу раньше, пулы должны быть по лигам.', not_relay_top: 'Это не тур-эстафета с лучшими работами.', acceptance_not_over: 'Приём работ в конкурсе ещё идёт (общий срок или срок лиги не прошёл).',
    personal_deadlines_pending: 'У кого-то из участниц личный срок ещё не прошёл, а работы нет. Дождитесь срока или уберите продление.',
    participants_without_league: 'Пулы по лигам, но у некоторых участниц лига не указана. Укажите лигу или выберите общий пул.',
    no_works: 'Нет работ в конкурсе, сданных в срок.', no_criteria: 'Добавьте хотя бы один критерий.', no_judges: 'В каком-то пуле нет судей.',
    judge_not_eligible: 'Судья должен иметь роль «Судья» или «Администратор» и не участвовать в этой Игре.',
    even_judges: 'Чётное число судей в пуле: при переголосовании возможна ничья. Лучше нечётное.', lonely_work: 'В каком-то пуле одна работа: в парах её не с чем сравнить — балла за тур не будет, а без балла нет итога Игры и диплома. Выберите общий пул или критерии.',
    small_pool: 'В пуле меньше 3 работ — рейтинг за тур не изменится.',
    quota_covers_all: 'Число прохода не меньше числа работ — пройдут все.', no_judging_deadline: 'Не задан срок оценки — укажите его в сроках тура.',
    votes_pending: 'Не все судьи закончили оценку.', tie_break_running: 'Идёт переголосование — дождитесь голосов.', border_tie: 'На границе прохода равные баллы — нужно переголосование или ваше решение.',
    already_published: 'Итоги уже опубликованы.', judging_not_started: 'Судейство ещё не начато.', judge_not_found: 'Этот судья не назначен в пул.',
    judge_already_in_pool: 'Этот человек уже судит этот пул.', tie_break_targets: 'Выберите хотя бы две работы.', tie_break_not_tied: 'Переголосование — только среди работ, идущих подряд в таблице, без пропусков. Иначе работа перескочила бы через тех, кто в переголосовании не участвует.', decision_targets: 'Решить самой можно только про равные на границе прохода и работы без оценки.',
    reason_required: 'Укажите причину.', judging_closed: 'Оценка закрыта.',
    unjudged_works: 'У некоторых работ нет ни одной оценки — решите их проход сами (кнопка «Решить самой»).',
    no_tie_break: 'Переголосование не идёт.', regular_locked: 'Основное голосование закрыто.'
  };
  var t = function (code) { return TEXT[code] || O.text(code); };
  var err = function (r) { return TEXT[r.detail] || O.err(r); };
  var issues = function (list, kind) {
    return list.length ? '<div class="note ' + kind + ' small"><ul>' + list.map(function (c) { return '<li>' + esc(t(c)) + '</li>'; }).join('') + '</ul></div>' : '';
  };
  var poolName = function (league) { return league ? 'Лига ' + { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' }[league] : 'Общий пул'; };

  O.on(/^\/org\/rounds\/([0-9a-f-]{36})\/judging$/, function (id) {
    K.load(['/api/org/rounds/' + id + '/judging'], function (d) { draw(id, d); }, [['Игры и туры', '/org/games'], ['Судейство']]);
  });

  function crumbsOf(d) {
    return [['Игры и туры', '/org/games'], [d.event.title, '/org/games/' + d.event.id], ['Тур ' + d.round.round_no, '/org/rounds/' + d.round.id], ['Судейство']];
  }
  function draw(id, d) {
    O.jd = d; O.jid = id;
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(d.event.title + ' · Тур ' + d.round.round_no + ' · ' + d.round.title) + '</span>' +
      '<div class="between"><h1>Судейство тура</h1>' + (d.published ? pill('Итоги опубликованы', 'ok') : d.started ? pill('Идёт оценка', 'acc') : pill('Не начато', 'plain')) + '</div></div>';
    var early = !d.started && d.streams && d.streams.length;     // эстафета: первую лигу уже судят, остальных — ещё нет
    h += d.started ? started(d) : early ? earlyStage(d) : setup(d) + earlyCard(d);
    K.page(h, crumbsOf(d));
    if (!d.started && !early) bindSetup(d);
  }

  /* ---------- до запуска ---------- */
  function judgeBox(d, key, label) {
    var chosen = (d.config.judges || {})[key] || [], q = (d.config.quota || {})[key];
    return '<fieldset class="league-box jpool" data-key="' + key + '"><legend>' + esc(label) + '</legend>' +
      (d.judges.length ? '<div class="stack" data-s="g6">' + d.judges.map(function (j) {
        return O.chk('jj-' + key + '-' + j.id, esc(j.name) + (j.is_judge ? '' : ' <span class="small muted">(администратор)</span>'), chosen.indexOf(j.id) >= 0, ' data-j="' + j.id + '"');
      }).join('') + '</div>' : '<p class="small muted">Нет людей с ролью «Судья». Назначьте роль в разделе «Люди».</p>') +
      O.txt('jq-' + key, 'Проходят дальше (число)', q == null ? '' : q, ' type="number" min="1" max="10000" inputmode="numeric"', 'Пусто — проходят все.') + '</fieldset>';
  }
  function setup(d) {
    var c = d.config, ch = d.checks;
    var h = '<form class="card" id="f-jcfg" novalidate><h2>Настройка</h2>' +
      '<fieldset class="stack" data-s="g6"><legend>Способ оценки</legend>' +
      '<label class="chk"><input type="radio" name="method" value="pairwise"' + (c.method === 'pairwise' ? ' checked' : '') + '> <span>Сравнение пар: судья выбирает сильнейшую из двух работ. Балл 1–100 — по модели Брэдли–Терри: шанс работы обыграть среднюю работу тура с учётом того, кого она обыграла.</span></label>' +
      '<label class="chk"><input type="radio" name="method" value="criteria"' + (c.method === 'criteria' ? ' checked' : '') + '> <span>Оценки по критериям 1–100: среднее с весами критериев, затем среднее по судьям — это и есть балл.</span></label></fieldset>' +
      '<div class="jm-pair"' + (c.method === 'pairwise' ? '' : ' hidden') + '>' + O.sel('j-per', 'Сравнений на работу у каждого судьи', [[2, '2'], [4, '4'], [6, '6']], c.per_target) + '</div>' +
      '<div class="jm-crit"' + (c.method === 'criteria' ? '' : ' hidden') + '><h3>Критерии</h3><div class="stack" id="crit-rows">' +
      (c.criteria.length ? c.criteria : [{ label: '', weight: 1 }]).map(critRow).join('') + '</div>' +
      '<button class="btn sec small" type="button" data-act="jAddCrit">Добавить критерий</button><p class="small muted">До 6 критериев. Вес — во сколько раз критерий важнее (1 — обычный).</p></div>' +
      '<fieldset class="stack" data-s="g6"><legend>Пулы</legend>' +
      '<label class="chk"><input type="radio" name="pools" value="leagues"' + (c.pools === 'leagues' ? ' checked' : '') + '> <span>По лигам: каждая лига судится и проходит отдельно</span></label>' +
      '<label class="chk"><input type="radio" name="pools" value="common"' + (c.pools === 'common' ? ' checked' : '') + '> <span>Общий пул: все работы вместе</span></label></fieldset>' +
      '<h3>Судьи и проход</h3><p class="small muted">Каждый судья пула оценивает все работы своего пула. Участница этой Игры судить её не может.</p>' +
      '<div class="jp-common"' + (c.pools === 'common' ? '' : ' hidden') + '>' + judgeBox(d, 'all', 'Общий пул') + '</div>' +
      '<div class="jp-leagues stack"' + (c.pools === 'leagues' ? '' : ' hidden') + '>' + LEAGUES.map(function (l) { return judgeBox(d, l[0], 'Лига ' + l[1]); }).join('') + '</div>' +
      O.errBox + '<button class="btn" type="submit">Сохранить настройку</button></form>';
    h += '<section class="card"><h2>Запуск</h2>' + (d.acceptance_end ? '<p class="small muted">Приём работ в конкурсе — до ' + esc(O.when(d.acceptance_end)) + '. Срок оценки — ' +
      esc(d.round.judging_deadline ? O.when(d.round.judging_deadline) : 'не задан') + ' (меняется в сроках тура).</p>' : '') +
      (ch.pools.length ? '<div class="stats">' + ch.pools.map(function (p) {
        return '<div class="stat"><span>' + esc(poolName(p.league)) + '</span><b class="num">' + p.works + '</b><span>работ · судей ' + p.judges + (p.quota ? ' · проходят ' + p.quota : '') + '</span></div>';
      }).join('') + '</div>' : '') + issues(ch.problems, 'bad') + issues(ch.warnings, 'warn') +
      '<p class="small">После запуска работы «замораживаются»: судьи видят версию, сданную к этому моменту. Опоздавшие уходят вне конкурса.' +
      (d.event.affects_rating ? ' Рейтинги участниц фиксируются на начало судейства.' : '') + '</p>' +
      '<button class="btn" type="button" data-act="jStart"' + (ch.problems.length ? ' disabled' : '') + '>Начать судейство</button></section>';
    return h;
  }
  var critNo = 0;
  function critRow(c) {
    var i = ++critNo;
    return '<div class="crit-row grid3"><div class="field"><label for="cl' + i + '">Критерий</label><input class="input" name="label" id="cl' + i + '" maxlength="60" value="' + esc(c.label) + '"></div>' +
      '<div class="field"><label for="cw' + i + '">Вес</label><input class="input" name="weight" id="cw' + i + '" type="number" min="0.1" max="100" step="0.1" value="' + esc(c.weight) + '"></div>' +
      '<button class="btn ghost" type="button" data-act="jDropCrit">Убрать</button></div>';
  }
  K.actions.jAddCrit = function () {
    var rows = document.getElementById('crit-rows');
    if (rows.querySelectorAll('.crit-row').length >= 6) { K.toast('Не больше 6 критериев'); return; }
    rows.insertAdjacentHTML('beforeend', critRow({ label: '', weight: 1 }));
  };
  K.actions.jDropCrit = function (b) { b.closest('.crit-row').remove(); };
  function bindSetup(d) {
    var f = document.getElementById('f-jcfg');
    var sync = function () {
      var m = f.querySelector('input[name=method]:checked').value, p = f.querySelector('input[name=pools]:checked').value;
      f.querySelector('.jm-pair').hidden = m !== 'pairwise'; f.querySelector('.jm-crit').hidden = m !== 'criteria';
      f.querySelector('.jp-common').hidden = p !== 'common'; f.querySelector('.jp-leagues').hidden = p !== 'leagues';
    };
    Array.prototype.forEach.call(f.querySelectorAll('input[type=radio]'), function (r) { r.addEventListener('change', sync); });
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var method = f.querySelector('input[name=method]:checked').value, pools = f.querySelector('input[name=pools]:checked').value;
      var body = { method: method, pools: pools, per_target: +f.querySelector('#j-per').value, criteria: [], judges: {}, quota: {} };
      if (method === 'criteria') {
        var bad = false;
        Array.prototype.forEach.call(f.querySelectorAll('.crit-row'), function (r) {
          var l = r.querySelector('[name=label]').value.trim(), w = parseFloat(r.querySelector('[name=weight]').value);
          if (!l && !r.querySelector('[name=weight]').value) return;
          if (!l || !(w > 0)) bad = true; else body.criteria.push({ label: l, weight: w });
        });
        if (bad || !body.criteria.length) { K.formError(f, 'У каждого критерия нужны название и вес больше 0.'); return; }
      }
      var keys = pools === 'common' ? ['all'] : ['bronze', 'silver', 'gold'], qbad = false;
      keys.forEach(function (k) {
        var box = f.querySelector('.jpool[data-key="' + k + '"]');
        body.judges[k] = Array.prototype.map.call(box.querySelectorAll('input[data-j]:checked'), function (x) { return x.getAttribute('data-j'); });
        var q = box.querySelector('#jq-' + k).value.trim();
        if (q && !(/^\d+$/.test(q) && +q >= 1)) qbad = true;
        body.quota[k] = q ? +q : null;
      });
      if (qbad) { K.formError(f, 'Число прохода — целое больше 0 (или пусто).'); return; }
      O.send('PUT', '/api/org/rounds/' + O.jid + '/judging', body, f, function (nd) { K.toast('Настройка сохранена'); draw(O.jid, nd); });
    });
  }
  /* ---------- тур-эстафета: первую лигу судят раньше, чтобы раздать её лучшие работы ---------- */
  var LNAME = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
  function earlyCard(d) {
    var e = d.early;
    if (!e) return '';
    return '<section class="card"><h2>Сначала — ' + esc(LNAME[e.league]) + '</h2><p class="small">Это тур-эстафета: исходники для второй лиги — лучшие работы ' + esc(LNAME[e.league]) +
      ' по судейству. Поэтому ' + esc(LNAME[e.league]) + ' судят сразу после её срока' + (e.deadline ? ' (' + esc(O.when(e.deadline)) + ')' : '') +
      ', а вторую лигу — после её срока. Итоги тура публикуются одной кнопкой, всем сразу. Сначала сохраните настройку — для обеих лиг.</p>' +
      issues(e.problems.filter(function (p) { return p !== 'early_started'; }), 'bad') +
      '<button class="btn" type="button" data-act="jStartEarly"' + (e.available ? '' : ' disabled') + '>Начать судейство ' + esc(LNAME[e.league]) + '</button></section>';
  }
  function earlyStage(d) {
    var ch = d.checks;
    return '<div class="note info">Тур-эстафета: ' + esc(LNAME[(d.early || {}).league] || '') + ' уже судят. Когда голоса соберутся, раздача её лучших работ появится на странице тура — ' +
      'проверьте и отправьте исходники. Вторую лигу судят после её срока; итоги тура — одной кнопкой, всем сразу.</div>' +
      d.streams.map(streamCard).join('') +
      '<section class="card"><h2>Остальные лиги</h2>' + (d.acceptance_end ? '<p class="small muted">Приём работ — до ' + esc(O.when(d.acceptance_end)) + '.</p>' : '') +
      issues(ch.problems, 'bad') + issues(ch.warnings, 'warn') +
      '<button class="btn" type="button" data-act="jStart"' + (ch.problems.length ? ' disabled' : '') + '>Начать судейство остальных лиг</button></section>';
  }
  K.actions.jStartEarly = function () {
    var e = O.jd.early;
    O.confirm({ title: 'Начать судейство ' + LNAME[e.league] + '?', text: 'Судьи ' + LNAME[e.league] + ' получат работы. Вторая лига в это время продолжает тур. Итоги участницы увидят только после публикации всего тура.',
      ok: 'Начать', path: '/api/org/rounds/' + O.jid + '/judging/start-early', done: function (nd) { K.toast('Судейство начато'); draw(O.jid, nd); } });
  };
  K.actions.jStart = function () {
    O.confirm({ title: 'Начать судейство?', text: 'Судьи получат работы и уведомление. Настройка после этого не меняется; судью можно будет заменить.',
      ok: 'Начать', path: '/api/org/rounds/' + O.jid + '/judging/start', done: function (nd) { K.toast('Судейство начато'); draw(O.jid, nd); } });
  };

  /* ---------- после запуска ---------- */
  function started(d) {
    var h = d.streams.map(streamCard).join('');
    if (!d.published) {
      h += '<section class="card"><h2>Публикация итогов</h2>' + issues(d.publish_problems, 'bad') +
        '<p class="small">Участницы увидят балл тура, TOP WORK, проход' + (d.event.affects_rating ? ' и изменение FPL Rating' : '') + '. Мест в туре не видно. ' +
        'Не прошедшие получат предложение продолжить вне конкурса. После публикации итоги не пересчитываются.</p>' +
        '<button class="btn" type="button" data-act="jPublish"' + (d.publish_problems.length ? ' disabled' : '') + '>Опубликовать итоги</button></section>';
    } else {
      h += '<div class="note ok">Итоги опубликованы: участницы получили уведомления. Выбывшие по судейству выбирают, продолжать ли вне конкурса.</div>';
    }
    return h;
  }
  function streamCard(s) {
    var d = O.jd, open = !d.published, tied = s.border.tied || [], close = s.border.close || [];
    var h = '<section class="card jstream" data-stream="' + s.id + '"><div class="between"><h2>' + esc(poolName(s.league)) + ' · ' + s.works + ' работ</h2>' +
      (s.border.status === 'tie' && open ? pill('Граница не решена', 'bad') : s.pending ? pill('Оценка идёт', 'acc') : pill('Оценено', 'ok')) + '</div>' +
      '<p class="small muted">' + (s.method === 'pairwise' ? 'Сравнение пар · ' + s.per_target + ' на работу у судьи' : 'Критерии: ' + esc(s.criteria.map(function (c) { return c.label + (c.weight !== 1 ? ' ×' + c.weight : ''); }).join(', '))) +
      ' · проходят ' + (s.quota ? s.quota : 'все') + (s.judging_deadline ? ' · оценить до ' + esc(O.when(s.judging_deadline)) : '') + '</p>';
    h += '<h3>Судьи</h3><div class="list">' + s.judges.map(function (j) {
      return '<div class="li static"><span class="t">' + esc(j.name || 'Место ' + j.slot_no) + '</span><span class="s">' + j.done + ' из ' + j.total + '</span><span class="r">' +
        (open ? '<button class="btn ghost small" type="button" data-act="jReplace" data-s="' + s.id + '" data-u="' + j.user_id + '">Заменить</button>' : '') + '</span></div>';
    }).join('') + '</div>';
    if (open) {
      h += '<div class="row">' + (s.pending ? '<button class="btn ghost small" type="button" data-act="jClose" data-s="' + s.id + '">Закрыть недоделанное</button>' : '') +
        (s.pending_tie_break ? '<button class="btn ghost small" type="button" data-act="jCancelTb" data-s="' + s.id + '">Отменить переголосование</button>' : '') +
        '<button class="btn ghost small" type="button" data-act="jStream" data-s="' + s.id + '">Срок оценки и проход</button></div>';
    }
    if (s.border.status === 'tie' && open) {
      h += '<div class="note bad small"><b>Граница прохода:</b> у работ ' + esc(tied.map(function (x) { return nameOf(s, x); }).join(', ')) +
        ' равный результат, а пройдут не все. Проведите переголосование среди них или решите сами.<div class="row">' +
        '<button class="btn small" type="button" data-act="jTieBreak" data-s="' + s.id + '" data-t="' + tied.join(',') + '">Переголосование</button>' +
        '<button class="btn sec small" type="button" data-act="jDecide" data-s="' + s.id + '" data-t="' + tied.join(',') + '">Решить самой</button></div></div>';
    } else if (close.length > 1 && s.quota && open) {
      h += '<p class="small muted">Близко к границе (разница меньше 2 баллов): ' + esc(close.map(function (x) { return nameOf(s, x); }).join(', ')) + '.</p>';
    }
    if (s.border.status === 'unjudged' && open) {
      h += '<div class="note bad small"><b>Без оценки:</b> ' + esc(s.border.unjudged.map(function (x) { return nameOf(s, x); }).join(', ')) +
        ' — ни одного голоса (например, после закрытия недоделанного). Решите, проходят ли они.<div class="row">' +
        '<button class="btn sec small" type="button" data-act="jDecide" data-s="' + s.id + '" data-t="' + s.border.unjudged.join(',') + '">Решить самой</button></div></div>';
    }
    if (s.pending_tie_break) h += '<div class="note warn small">Идёт переголосование: осталось голосов — ' + s.pending_tie_break + '.</div>';
    h += '<div class="table-wrap"><table class="otable jtable"><thead><tr><th scope="col">Место</th><th scope="col">Работа</th><th scope="col">Участница</th><th scope="col" class="c">Балл</th>' +
      '<th scope="col" class="c">' + (s.method === 'pairwise' ? 'Победы' : 'Оценка') + '</th><th scope="col">Итог</th>' + (open ? '<th scope="col" class="c">Выбрать</th>' : '') + '</tr></thead><tbody>' +
      s.rows.map(function (r) {
        var res = r.left ? pill('Не в конкурсе', 'plain') : r.advanced === true ? pill('Проходит', 'ok') : r.advanced === false ? pill('Не проходит', 'warn') :
          r.score == null ? pill('Нет оценки', 'bad') : '';
        var same = s.rows.filter(function (x) { return x.place != null && x.place === r.place; }).length > 1;
        return '<tr class="' + (tied.indexOf(r.target) >= 0 ? 'tied' : '') + '"><td data-label="Место">' + (r.place || '—') + (same ? ' <span class="small muted">(делит)</span>' : '') + '</td>' +
          '<td data-label="Работа">' + (r.photos[0] ? '<a href="' + esc(r.photos[0].view_url) + '" target="_blank" rel="noopener"><img class="jt" src="' + esc(r.photos[0].thumb_url) + '" alt="Работа: ' + esc(r.name) + '"></a>' : '—') +
          (r.source && r.source[0] ? ' <a href="' + esc(r.source[0].view_url) + '" target="_blank" rel="noopener" title="Исходник"><img class="jt jt-src" src="' + esc(r.source[0].thumb_url) + '" alt="Исходник работы: ' + esc(r.name) + '"></a>' : '') + '</td>' +
          '<td data-label="Участница"><button class="lnk" type="button" data-href="/org/participants/' + r.participant_id + '">' + esc(r.name) + '</button>' + (r.top_work ? ' ' + pill(K.topWork(r.league), 'acc') : '') + '</td>' +
          '<td class="c" data-label="Балл"><b class="num">' + (r.score == null ? '—' : r.score) + '</b></td>' +
          '<td class="c" data-label="' + (s.method === 'pairwise' ? 'Победы' : 'Оценка') + '">' + (s.method === 'pairwise' ? (r.comparisons ? r.wins + ' / ' + r.comparisons : '—') : (r.value == null ? '—' : String(r.value).replace('.', ','))) +
          (r.tie_break_wins != null ? '<span class="small muted"> · переголосование ' + r.tie_break_wins + '</span>' : '') + '</td>' +
          '<td data-label="Итог">' + res + '</td>' + (open ? '<td class="c" data-label="Выбрать"><input type="checkbox" class="jpick" data-t="' + r.target + '" aria-label="Выбрать: ' + esc(r.name) + '"></td>' : '') + '</tr>';
      }).join('') + '</tbody></table></div>';
    if (open) h += '<div class="row"><button class="btn sec small" type="button" data-act="jTieBreakPick" data-s="' + s.id + '">Переголосование среди выбранных</button>' +
      '<button class="btn ghost small" type="button" data-act="jDecidePick" data-s="' + s.id + '">Решение по выбранным</button></div>';
    if (s.tie_breaks.length) h += '<details class="more"><summary>Переголосования · ' + s.tie_breaks.length + '</summary><ul class="log">' + s.tie_breaks.map(function (tb) {
      return '<li><b>№ ' + (tb.run_no - 1) + ' · ' + (tb.goal === 'advance' ? 'кто проходит' : 'места') + (tb.finished ? '' : ' · идёт') + '</b><span class="small">' +
        esc(tb.targets.map(function (x) { return nameOf(s, x) + (tb.wins[x] != null ? ' — ' + tb.wins[x] : ''); }).join(', ')) + '</span></li>';
    }).join('') + '</ul></details>';
    if (s.admin_decisions.length) h += '<details class="more"><summary>Решения организатора · ' + s.admin_decisions.length + '</summary><ul class="log">' + s.admin_decisions.map(function (a) {
      return '<li><b>Проходят: ' + esc(a.advance.map(function (x) { return nameOf(s, x); }).join(', ') || 'никто') + '</b><span class="small">' + esc(a.reason) + '</span></li>';
    }).join('') + '</ul></details>';
    return h + '</section>';
  }
  function nameOf(s, target) { var r = s.rows.filter(function (x) { return x.target === target; })[0]; return r ? r.name : '?'; }
  function streamOf(id) { return O.jd.streams.filter(function (s) { return s.id === id; })[0]; }
  function picked(sid) {
    return Array.prototype.map.call(document.querySelectorAll('.jstream[data-stream="' + sid + '"] .jpick:checked'), function (x) { return x.getAttribute('data-t'); });
  }
  var redraw = function (nd) { K.toast('Готово'); draw(O.jid, nd); };

  K.actions.jPublish = function () {
    O.confirm({ title: 'Опубликовать итоги тура ' + O.jd.round.round_no + '?', text: 'Участницы сразу получат уведомления. После публикации итоги и рейтинг не пересчитываются.',
      ok: 'Опубликовать', path: '/api/org/rounds/' + O.jid + '/judging/publish', done: redraw });
  };
  K.actions.jClose = function (b) {
    O.confirm({ title: 'Закрыть недоделанное?', text: 'Неоценённые пары основного голосования не пойдут в счёт — например, если судья не успевает. Лучше сначала попробовать заменить судью.',
      ok: 'Закрыть', danger: true, reason: true, path: '/api/org/judging/streams/' + b.getAttribute('data-s') + '/close',
      body: function (reason) { return { reason: reason }; }, done: redraw });
  };
  function tieBreak(sid, targets) {
    if (targets.length < 2) { K.toast('Выберите хотя бы две работы'); return; }
    var s = streamOf(sid);
    O.confirm({ title: 'Переголосование', html: '<p>Судьи пула сравнят все пары среди работ: ' + esc(targets.map(function (x) { return nameOf(s, x); }).join(', ')) +
      '. Работы займут те же позиции, порядок — по победам в переголосовании.</p>' +
      O.sel('tb-goal', 'Цель', [['advance', 'Решить, кто проходит'], ['places', 'Распределить места']], 'advance'),
      ok: 'Начать переголосование', path: '/api/org/judging/streams/' + sid + '/tie-break',
      body: function () { return { targets: targets, goal: document.getElementById('tb-goal').value }; }, done: redraw });
  }
  K.actions.jTieBreak = function (b) { tieBreak(b.getAttribute('data-s'), b.getAttribute('data-t').split(',')); };
  K.actions.jTieBreakPick = function (b) { tieBreak(b.getAttribute('data-s'), picked(b.getAttribute('data-s'))); };
  function decide(sid, targets) {
    if (!targets.length) { K.toast('Выберите работы'); return; }
    var s = streamOf(sid);
    O.confirm({ title: 'Решение о проходе', html: '<p>Отметьте, кто из выбранных проходит дальше. Решение и причина сохранятся в журнале.</p><div class="stack" data-s="g6">' +
      targets.map(function (x) { return O.chk('dc-' + x, esc(nameOf(s, x)), false, ' data-t="' + x + '"'); }).join('') + '</div>',
      ok: 'Сохранить решение', reason: true, path: '/api/org/judging/streams/' + sid + '/decision',
      body: function (reason) {
        return { targets: targets, reason: reason, advance: Array.prototype.map.call(document.querySelectorAll('.modal input[data-t]:checked'), function (x) { return x.getAttribute('data-t'); }) };
      }, done: redraw });
  }
  K.actions.jCancelTb = function (b) {
    O.confirm({ title: 'Отменить переголосование?', text: 'Голоса этого переголосования не пойдут в счёт. Например, если судья недоступен — потом можно начать новое.',
      ok: 'Отменить', danger: true, path: '/api/org/judging/streams/' + b.getAttribute('data-s') + '/tie-break/cancel', done: redraw });
  };
  K.actions.jDecide = function (b) { decide(b.getAttribute('data-s'), b.getAttribute('data-t').split(',')); };
  K.actions.jDecidePick = function (b) { decide(b.getAttribute('data-s'), picked(b.getAttribute('data-s'))); };
  K.actions.jReplace = function (b) {
    var sid = b.getAttribute('data-s'), old = b.getAttribute('data-u'), s = streamOf(sid);
    var busy = s.judges.map(function (j) { return j.user_id; });
    var free = O.jd.judges.filter(function (j) { return busy.indexOf(j.id) < 0; });
    if (!free.length) { K.toast('Нет свободных судей: назначьте роль «Судья» в разделе «Люди»'); return; }
    O.confirm({ title: 'Заменить судью', html: '<p>Неоценённое перейдёт новому судье, уже выставленные оценки останутся.</p>' +
      O.sel('rp-new', 'Новый судья', free.map(function (j) { return [j.id, j.name]; }), free[0].id),
      ok: 'Заменить', reason: true, path: '/api/org/judging/streams/' + sid + '/replace',
      body: function (reason) { return { old_user_id: old, new_user_id: document.getElementById('rp-new').value, reason: reason }; }, done: redraw });
  };
  K.actions.jStream = function (b) {
    var s = streamOf(b.getAttribute('data-s'));
    K.showModal('<h2 id="mT">' + esc(poolName(s.league)) + '</h2><form id="f-js" class="stack" novalidate>' +
      O.dt('js-dl', 'Оценить до', s.judging_deadline) + O.txt('js-q', 'Проходят дальше (число)', s.quota == null ? '' : s.quota, ' type="number" min="1" inputmode="numeric"', 'Пусто — проходят все.') +
      O.errBox + '<div class="row"><button class="btn" type="submit">Сохранить</button><button class="btn sec" type="button" data-act="closeModal">Отмена</button></div></form>');
    var f = document.getElementById('f-js');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = f.querySelector('#js-q').value.trim();
      if (q && !(/^\d+$/.test(q) && +q >= 1)) { K.formError(f, 'Число прохода — целое больше 0 (или пусто).'); return; }
      O.send('PATCH', '/api/org/judging/streams/' + s.id, { quota: q ? +q : null, judging_deadline: K.fromInput(f.querySelector('#js-dl').value) }, f, function (nd) {
        f.closest('.modal').remove(); K.onEscape = null; redraw(nd);
      });
    });
  };
})();
