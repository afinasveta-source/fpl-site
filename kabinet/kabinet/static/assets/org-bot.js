/* Кабинет организатора: Игра 01 из бота (решения 13.10, вечер).
   «Перенос из бота» — таблица туров 1–2 (CSV) → предпросмотр → перенос.
   «Заявки» — участницы Игры 01 оставляют заявку по общей ссылке /kabinet/game01; организатор находит её в перенесённом списке
   и нажимает «Это она» — у записи из бота появляется вход. */
(function () {
  'use strict';
  var K = window.K, O = K.org, esc = K.esc, pill = K.pill;
  var LG = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };
  var PROBLEM = {
    empty_file: 'Файл пустой.', missing_columns: 'Нет нужных колонок', no_rows: 'В таблице нет строк.', bad_id: 'ID участника — только цифры',
    duplicate_id: 'Этот ID уже был выше', bad_name: 'Нет ФИО', bad_league: 'Лига — А или Б (Gold / Silver)', bad_advanced: '«Прошёл в тур 3» — Да или Нет',
    not_a_number: 'Не число', bad_score_1: 'Балл тура 1 — от 0 до 100', bad_rating_1: 'Нет рейтинга после тура 1', bad_score_2: 'Балл тура 2 — от 0 до 100',
    advanced_without_round_2: 'Прошла в тур 3, но нет балла или рейтинга тура 2', round_2_incomplete: 'Тур 2: есть балл без рейтинга или наоборот',
    bad_rating_2: 'Рейтинг после тура 2 — не число', top_work_without_score: 'TOP WORK тура 2 без балла',
    delta_mismatch: 'Изменение за тур 2 не равно разнице рейтингов (перенесётся разница)',
    rating_1_first: 'Нет пересчитанного рейтинга после тура 1 — перенесётся первоначальный',
    no_top_work_1: 'В таблице нет колонки «TOP WORK тура 1» — TOP WORK первого тура не перенесётся',
    not_in_table: 'В Игре есть участницы, которых нет в таблице (без входа в кабинет), — они перейдут вне конкурса; вернуть можно в списке участниц Игры',
    no_rules: 'В кабинете не опубликованы Правила. Сначала опубликуйте Правила 1.8 (Документы), потом переносите — иначе у Игры не будет редакции Правил'
  };
  O.addText({ confirm_word: 'Напишите слово ОТМЕНИТЬ.', not_moved: 'Игра 01 ещё не переносилась.', participants_logged_in: 'Отменить нельзя: кто-то из перенесённых уже вошёл в кабинет.',
    game_has_works: 'Отменить нельзя: в Игре уже есть сданные работы или судейство.', rounds_published: 'Отменить нельзя: тур 3 или следующий уже опубликован.' });
  O.addText({ cabinet_rating_started: 'Кабинет уже начислил рейтинг за туры Игры 01 — перенос повторить нельзя.', preview_first: 'Сначала нажмите «Проверить» — переносится ровно то, что вы видели.', table_has_errors: 'В таблице есть ошибки — исправьте их и проверьте снова.',
    claim_decided: 'Заявку уже рассмотрели.', person_has_login: 'У этой записи уже есть вход — выберите другую.',
    person_not_in_game: 'Этой участницы нет в Игре.', email_taken: 'Этот email уже у другого аккаунта.',
    account_not_linkable: 'Этот аккаунт уже в Игре или у него есть роль — привязать нельзя.', account_has_support: 'У аккаунта есть обращения в поддержку — напишите Claude, привяжем вручную.',
    same_person: 'Это та же запись.', merge_from_no_login: 'У этой записи нет входа — переносить нечего.', merge_from_has_works: 'В этой записи уже есть работы или итоги — перенос вручную, напишите Claude.',
    merge_into_logged_in: 'В основную запись уже входили — у неё свой вход. Напишите Claude, решим вручную.' });

  /* ---------- Перенос из бота ---------- */
  var IMP = { text: null, name: null, preview: null };
  O.on(/^\/org\/import$/, function () { loadImport(); });
  function loadImport() {
    K.api('GET', '/api/org/import/game01').then(function (r) { IMP.state = r.ok ? r.data : null; drawImport(); });
  }
  var UNDO_WHY = { cabinet_rating_started: 'кабинет уже начислил рейтинг за туры Игры 01',
    participants_logged_in: 'кто-то из перенесённых уже вошёл в кабинет', game_has_works: 'в Игре уже есть сданные работы или судейство',
    rounds_published: 'тур 3 или следующий уже опубликован' };
  function movedCard(s) {
    if (!s || !s.moved) return '';
    var h = '<section class="card"><h2>Уже перенесено</h2><p>' + esc(s.title) + ': <b>' + s.participants + ' участниц</b>' +
      (s.sample && s.sample.length ? ' — например, ' + s.sample.map(esc).join(', ') : '') + '.</p>' +
      '<p class="small muted">Проверьте имена: если перенеслась не та таблица, перенос можно отменить и загрузить нужную.</p>';
    if (s.undo_blockers && s.undo_blockers.length) {
      h += '<p class="small muted">Отменить перенос уже нельзя: ' + s.undo_blockers.map(function (b) { return esc(UNDO_WHY[b] || b); }).join('; ') + '.</p>';
    } else {
      h += '<div class="row"><button class="btn sec danger" type="button" data-act="impUndo">Отменить перенос</button></div>';
    }
    return h + '</section>';
  }
  K.actions.impUndo = function () {
    var s = IMP.state;
    O.confirm({ title: 'Отменить перенос Игры 01?', danger: true, ok: 'Отменить перенос',
      html: '<p>Будут удалены все ' + s.participants + ' перенесённых участниц Игры 01 — их оценки туров 1–2, рейтинг и записи в Игре. ' +
        'Игра, туры и документы останутся; потом можно перенести правильную таблицу. Вернуть удалённое можно только из резервной копии.</p>' +
        '<div class="field"><label for="undo-word">Чтобы подтвердить, напишите ОТМЕНИТЬ</label><input class="input" id="undo-word" autocomplete="off"></div>',
      validate: function () { return document.getElementById('undo-word').value.trim().toUpperCase() === 'ОТМЕНИТЬ' ? null : 'Напишите слово ОТМЕНИТЬ.'; },
      path: '/api/org/import/game01/undo', body: function () { return { confirm: document.getElementById('undo-word').value.trim() }; },
      done: function (d) { K.toast('Перенос отменён: удалено ' + d.participants + ' участниц'); IMP.done = null; IMP.preview = null; O.refreshCounts(); loadImport(); } });
  };

  function drawImport() {
    var p = IMP.preview;
    var h = '<h1>Перенос Игры 01 из бота</h1><p class="small muted">Таблица туров 1–2 (CSV, разделитель «;»): ID участника SaleBot, ФИО, лига, балл тура 1, рейтинг после тура 1, ' +
      'балл тура 2, прошла ли в тур 3, рейтинг после тура 2, TOP WORK тура 2. Числа переносятся как их видели участницы, без пересчёта. ' +
      'Повторный перенос (например, исправленной таблицы) ничего не дублирует. Файл остаётся только в базе кабинета.</p>' +
      movedCard(IMP.state) +
      '<section class="card"><h2>Файл</h2><label class="drop" for="imp-file"><b>' + (IMP.name ? esc(IMP.name) : 'Выбрать таблицу') + '</b><span class="small muted">CSV в кодировке UTF-8</span></label>' +
      '<input class="sr" id="imp-file" type="file" accept=".csv,text/csv">' +
      (IMP.text ? '<div class="row"><button class="btn sec" type="button" data-act="impPreview">Проверить</button></div>' : '') + '</section>';
    if (p) {
      var leagues = Object.keys(p.leagues).sort().reverse();
      h += '<section class="card"><h2>Что будет записано</h2><dl class="kv"><dt>Игра</dt><dd>' + esc(p.event.title) + (p.event.exists ? (p.event.moved ? ' · уже переносилась — обновится' : ' · уже есть в базе — дополнится') : ' · будет создана') + '</dd>' +
        '<dt>Строк</dt><dd>' + p.rows + (p.already_known ? ' · из них уже в базе: ' + p.already_known : '') + '</dd>' +
        (p.sample && p.sample.length ? '<dt>Первые в таблице</dt><dd>' + p.sample.map(esc).join(', ') + '</dd>' : '') + '</dl>' +
        '<div class="table-wrap"><table class="otable"><thead><tr><th>Лига</th><th>Всего</th><th>В конкурсе (тур 3)</th><th>Не прошли отбор</th><th>Без тура 2</th><th>TOP WORK тура 2</th></tr></thead><tbody>' +
        leagues.map(function (k) { var x = p.leagues[k]; return '<tr><th scope="row">' + LG[k] + '</th><td data-label="Всего">' + x.total + '</td><td data-label="В конкурсе">' + x.in_competition + '</td><td data-label="Не прошли">' + x.judged_out +
          '</td><td data-label="Без тура 2">' + x.no_round_2 + '</td><td data-label="TOP WORK 2">' + x.top_work_2 + '</td></tr>'; }).join('') +
        '</tbody></table></div><p class="small muted">Не прошедшие в тур 3 продолжают вне конкурса. Туры 1–2 — опубликованы, туры 3, 4 и финал — черновики (тур 3 — эстафета Gold → Silver, тур 4 — Silver → Gold).</p>';
      if (p.error_count) h += '<div class="note bad small"><b>Ошибки (' + p.error_count + ') — перенос невозможен, пока их нет:</b><ul>' + p.errors.map(function (e) {
        return '<li>Строка ' + e.line + (e.id ? ' (ID ' + esc(e.id) + ')' : '') + ': ' + esc(PROBLEM[e.problem] || e.problem) + (e.columns ? ': ' + esc(e.columns.join(', ')) : '') + '</li>'; }).join('') + '</ul></div>';
      if (p.warnings.length) h += '<div class="note warn small"><b>Обратите внимание:</b><ul>' + p.warnings.map(function (e) {
        return '<li>' + (e.line > 1 ? 'Строка ' + e.line + ': ' : '') + esc(PROBLEM[e.problem] || e.problem) + (e.count ? ': ' + e.count : '') + '</li>'; }).join('') + '</ul></div>';
      if (p.event.locked) h += '<div class="note bad small">Кабинет уже начислил рейтинг за туры Игры 01 — перенос туров 1–2 повторить нельзя.</div>';
      else if (!p.error_count) h += '<div class="row"><button class="btn" type="button" data-act="impApply">Перенести</button></div>';
      h += '</section>';
    }
    if (IMP.done) h += '<div class="note ok"><b>Перенесено: ' + IMP.done.rows + ' участниц.</b> Дальше — «Заявки»: участницы оставляют их по ссылке <b>facepaintingleague.com/kabinet/game01</b>. ' +
      '<button class="lnk" type="button" data-href="/org/claims">Открыть заявки</button> · <button class="lnk" type="button" data-href="/org/games/' + IMP.done.event_id + '">Открыть Игру</button></div>';
    K.page(h, [['Обзор', '/org'], ['Перенос из бота']]);
    var inp = document.getElementById('imp-file');
    inp.addEventListener('change', function () {
      var f = inp.files[0]; if (!f) return;
      if (f.size > 2000000) { K.toast('Файл больше 2 МБ — это точно та таблица?'); return; }
      var rd = new FileReader();
      rd.onload = function () { IMP.text = String(rd.result); IMP.name = f.name; IMP.preview = null; IMP.done = null; drawImport(); };
      rd.readAsText(f, 'utf-8');
    });
  }
  K.actions.impPreview = function (b) {
    b.disabled = true;
    K.api('POST', '/api/org/import/game01/preview', { csv: IMP.text }).then(function (r) {
      b.disabled = false;
      if (!r.ok) { K.toast(O.text(r.detail) || K.errorText(r)); return; }
      IMP.preview = r.data; drawImport();
    });
  };
  K.actions.impApply = function () {
    var p = IMP.preview;
    O.confirm({ title: 'Перенести ' + p.rows + ' участниц?', text: 'Игра 01 продолжится в кабинете. Повторный перенос ничего не дублирует.', ok: 'Перенести',
      path: '/api/org/import/game01/apply', body: function () { return { csv: IMP.text, sha256: p.sha256 }; },
      done: function (d) { IMP.done = d; IMP.preview = null; K.toast('Перенесено'); O.refreshCounts(); loadImport(); } });
  };

  /* ---------- Тур-эстафета: проверка и отправка исходников ---------- */
  O.addText({ relay_released: 'Исходники уже отправлены — раздача не меняется.', relay_not_ready: 'Рано: первая лига ещё сдаёт работы или (для «лучших») её ещё судят — раздача будет после всех голосов.',
    relay_no_sources: 'Нет ни одной работы-исходника: никто из первой лиги в конкурсе не сдал работу в срок (или все убраны).', not_relay: 'Это не тур-эстафета.' });
  O.on(/^\/org\/rounds\/([0-9a-f-]{36})\/relay$/, function (id) {
    K.load(['/api/org/rounds/' + id, '/api/org/rounds/' + id + '/relay'], function (r, d) { RL.round = r; drawRelay(r, d); },
      [['Игры и туры', '/org/games'], ['Тур', '/org/rounds/' + id], ['Исходники']]);
  });
  var RL = {};
  function drawRelay(r, d) {
    var ov = d.overview, rel = ov.released;
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(r.event.title) + ' · Тур ' + r.round_no + '</span><h1>Исходники: ' + LG[ov.from] + ' → ' + LG[ov.to] + '</h1></div>' +
      '<section class="card"><p>' + (rel ? 'Отправлены участницам ' + esc(O.when(ov.released_at)) + '. Раздача больше не меняется; кто придёт позже — получит одну из этих работ.' :
        'Это черновик — участницы его не видят. Проверьте работы: неподходящую уберите (раздача пересоберётся). Когда всё хорошо — «Отправить исходники».') + '</p>' +
      '<dl class="kv"><dt>Работ-исходников</dt><dd>' + ov.sources + (ov.excluded ? ' · убрано ' + ov.excluded : '') + '</dd><dt>Получательниц</dt><dd>' + ov.given +
      (ov.waiting ? ' · без исходника ' + ov.waiting : '') + '</dd></dl>' +
      (rel ? '' : '<div class="row"><button class="btn" type="button" data-act="rlRelease"' + (ov.sources ? '' : ' disabled') + '>Отправить исходники</button>' +
        '<button class="btn sec" type="button" data-act="rlPrepare">' + (ov.started ? 'Перераздать заново' : 'Подготовить раздачу') + '</button></div>') + '</section>';
    h += d.items.length ? '<div class="stack">' + d.items.map(function (it) {
      var ph = it.photos[0];
      return '<section class="card rl-item' + (it.excluded ? ' rl-off' : '') + '"><div class="rl-row">' +
        (ph ? '<a href="' + esc(ph.view_url) + '" target="_blank" rel="noopener"><img class="rl-ph" src="' + esc(ph.thumb_url) + '" alt="Работа: ' + esc(it.author || '') + '"></a>' : '<span class="photo rl-ph"></span>') +
        '<div class="stack" data-s="g4"><b>' + esc(it.author || 'Участница') + '</b>' +
        (it.excluded ? '<span class="small">Убрана: ' + esc(it.excluded_reason || '') + '</span>' :
          '<span class="small muted">' + (it.recipients.length ? 'Получат: ' + it.recipients.map(function (x) { return esc(x.name) + (x.outside ? ' (вне конкурса)' : ''); }).join(', ') : 'Пока никому') + '</span>') +
        (rel ? '' : '<div class="row"><button class="btn ghost small" type="button" data-act="rlToggle" data-id="' + it.id + '" data-x="' + (it.excluded ? '0' : '1') + '">' +
          (it.excluded ? 'Вернуть в исходники' : 'Убрать из исходников') + '</button></div>') + '</div></div></section>';
    }).join('') + '</div>' : '<div class="note">' + (ov.ready ? 'Раздача ещё не готовилась — нажмите «Подготовить раздачу».' : ov.mode === 'top' ?
      (ov.early_judging === 'running' ? 'Идёт судейство ' + LG[ov.from] + ' — раздача появится, когда все голоса соберутся.' : 'Сначала начните судейство ' + LG[ov.from] + ' (страница «Судейство тура»).') :
      'Первая лига ещё сдаёт работы.') + '</div>';
    K.page(h, [['Игры и туры', '/org/games'], ['Тур ' + r.round_no, '/org/rounds/' + r.id], ['Исходники']]);
  }
  function relayCall(path, body, done) {
    K.api('POST', '/api/org/rounds/' + RL.round.id + '/relay' + path, body).then(function (res) {
      if (!res.ok) { K.toast(O.text(res.detail) || K.errorText(res)); return; }
      if (done) done(res.data);
      drawRelay(RL.round, res.data);
    });
  }
  K.actions.rlPrepare = function () { relayCall('/prepare', {}, function () { K.toast('Раздача пересобрана'); }); };
  K.actions.rlToggle = function (b) {
    var id = b.getAttribute('data-id'), x = b.getAttribute('data-x') === '1';
    if (!x) { relayCall('/items/' + id, { excluded: false }, function () { K.toast('Работа вернулась в исходники'); }); return; }
    O.confirm({ title: 'Убрать работу из исходников?', html: '<div class="field"><label for="rl-why">Причина (для журнала)</label><input class="input" id="rl-why" maxlength="500" value="Не подходит как исходник"></div>',
      ok: 'Убрать', path: '/api/org/rounds/' + RL.round.id + '/relay/items/' + id,
      body: function () { return { excluded: true, reason: document.getElementById('rl-why').value.trim() || 'Не подходит' }; },
      done: function (d) { K.toast('Работа убрана, раздача пересобрана'); drawRelay(RL.round, d); } });
  };
  K.actions.rlRelease = function () {
    O.confirm({ title: 'Отправить исходники?', text: 'Участницы получат исходники и уведомление. После этого раздачу не поменять.', ok: 'Отправить',
      path: '/api/org/rounds/' + RL.round.id + '/relay/release', done: function (d) { K.toast('Исходники отправлены'); O.refreshCounts(); drawRelay(RL.round, d); } });
  };

  /* ---------- Заявки участниц из бота ---------- */
  O.on(/^\/org\/claims$/, function () {
    var status = K.query().get('status') || 'pending';
    K.load(['/api/org/claims?status=' + status, '/api/org/claims/accounts'], function (d, acc) { drawClaims(d, status, acc); }, [['Обзор', '/org'], ['Заявки']]);
  });

  function who(p) {
    return esc(p.full_name) + ' · ' + (LG[p.league] || 'без лиги') + (p.in_competition ? '' : ' · вне конкурса');
  }
  function drawClaims(d, status, acc) {
    var h = '<h1>Заявки на вход' + (d.game ? ' · ' + esc(d.game) : '') + '</h1>' +
      '<p class="small muted">Участницы из бота оставляют заявку по ссылке <b>facepaintingleague.com/kabinet/game01</b>. Найдите её в перенесённом списке и нажмите «Это она» — ' +
      'у её записи появится вход (email и пароль из заявки), она войдёт и увидит свои итоги туров 1–2. Без входа ещё: ' + d.free + '.</p>' +
      '<nav class="row tabs">' + [['pending', 'Ждут'], ['all', 'Все']].map(function (t) {
        return '<button class="btn ' + (t[0] === status ? '' : 'sec') + ' small" type="button" data-href="/org/claims' + (t[0] === 'pending' ? '' : '?status=all') + '">' + t[1] + '</button>'; }).join('') +
      '<button class="btn ghost small" type="button" data-href="/org/import">Перенос из бота</button></nav>';
    var accs = (acc && acc.items) || [];
    if (accs.length) {
      // Завели кабинет сами («Впервые в лиге?»), а не по заявке Игры 01: итоги туров 1–2 остались на записи из бота.
      h += '<section class="card"><h2>Зарегистрировались сами · ' + accs.length + '</h2><p class="small muted">Эти люди завели кабинет через «Впервые в лиге?», а не по заявке Игры 01. ' +
        'Если это участница из бота — нажмите «Это она»: её вход переедет на запись из бота (с итогами туров 1–2), а пустой аккаунт закроется. Новичков не трогайте.</p>' +
        accs.map(function (a) {
          return '<div class="stack claim" data-s="g6"><div class="between"><b>' + esc(a.full_name || '—') + '</b><span class="small muted">' + esc(a.email) + ' · ' + esc(O.when(a.created_at)) + '</span></div>' +
            (a.suggestions.length ? a.suggestions.map(function (p) {
              return '<div class="between"><span>' + who(p) + ' <span class="small muted">· ID ' + esc(p.bot_id || '—') + '</span></span>' +
                '<button class="btn small" type="button" data-act="clLink" data-a="' + a.user_id + '" data-u="' + p.user_id + '" data-n="' + esc(p.full_name) + '" data-e="' + esc(a.email) + '">Это она</button></div>';
            }).join('') : '<p class="small muted">Похожих в списке Игры нет — поищите вручную.</p>') +
            '<form class="search" data-find-acc="' + a.user_id + '" data-e="' + esc(a.email) + '"><label class="sr" for="ac-q-' + a.user_id + '">Поиск</label><input class="input" id="ac-q-' + a.user_id + '" type="search" maxlength="100" placeholder="Фамилия или ID SaleBot">' +
            '<button class="btn sec small" type="submit">Найти</button></form><div class="stack" id="ac-found-' + a.user_id + '"></div></div>';
        }).join('<hr>') + '</section>';
    }
    if (!d.items.length) h += '<div class="note">' + (status === 'pending' ? 'Новых заявок нет.' : 'Заявок нет.') + '</div>';
    h += d.items.map(function (c) {
      var x = '<section class="card claim" data-no="' + c.no + '"><div class="between"><h2>№ ' + c.no + ' · ' + esc(c.full_name) + '</h2>' +
        (c.status === 'pending' ? pill('Ждёт', 'acc') : c.status === 'approved' ? pill('Вход открыт', 'ok') : pill('Отклонена', 'plain')) + '</div>' +
        '<dl class="kv"><dt>Email</dt><dd>' + esc(c.email) + '</dd><dt>Город</dt><dd>' + esc(c.city) + ', ' + esc(c.country_code) + '</dd>' +
        (c.contact ? '<dt>Telegram / VK</dt><dd>' + esc(c.contact) + '</dd>' : '') + '<dt>Заявка</dt><dd>' + esc(O.when(c.created_at)) + '</dd>' +
        (c.decision_note ? '<dt>Причина</dt><dd>' + esc(c.decision_note) + '</dd>' : '') + '</dl>';
      if (c.status === 'pending') {
        if (c.same_name && c.same_name.length) x += '<div class="note warn small"><b>Похоже, это повторная заявка.</b> Вход уже открыт по ' + c.same_name.map(function (d) {
          return 'заявке № ' + d.no + ' (' + esc(d.email) + ')'; }).join(', ') + '. Если это тот же человек и он не может войти — скорее всего, опечатка в email: ' +
          'отклоните эту заявку и откройте его запись в «Людях» (там «Это дубль?» / ссылка для нового пароля).</div>';
        x += (c.suggestions && c.suggestions.length ? '<p class="small"><b>Похожие в списке Игры:</b></p><div class="stack">' + c.suggestions.map(function (p) {
          return '<div class="between"><span>' + who(p) + ' <span class="small muted">· ID ' + esc(p.bot_id || '—') + '</span></span>' +
            '<button class="btn small" type="button" data-act="clApprove" data-no="' + c.no + '" data-u="' + p.user_id + '" data-n="' + esc(p.full_name) + '">Это она</button></div>';
        }).join('') + '</div>' : '<p class="small muted">Похожих ФИО в списке нет — поищите вручную (по фамилии или ID SaleBot).</p>') +
          '<form class="search" data-find="' + c.no + '"><label class="sr" for="cl-q-' + c.no + '">Поиск</label><input class="input" id="cl-q-' + c.no + '" type="search" maxlength="100" placeholder="Фамилия или ID SaleBot">' +
          '<button class="btn sec small" type="submit">Найти</button></form><div class="stack" id="cl-found-' + c.no + '"></div>' +
          '<div class="row"><button class="btn sec small" type="button" data-act="clOutside" data-no="' + c.no + '" data-n="' + esc(c.full_name) + '">Её нет в списке — добавить вне конкурса</button>' +
          '<button class="btn ghost small" type="button" data-act="clReject" data-no="' + c.no + '">Отклонить</button></div>';
      }
      return x + '</section>';
    }).join('');
    K.page(h, [['Обзор', '/org'], ['Заявки']]);
    Array.prototype.forEach.call(document.querySelectorAll('form[data-find-acc]'), function (f) {
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var id = f.getAttribute('data-find-acc'), em = f.getAttribute('data-e'), q = f.querySelector('input').value.trim(), box = document.getElementById('ac-found-' + id);
        K.api('GET', '/api/org/claims/people?q=' + encodeURIComponent(q)).then(function (r) {
          if (!r.ok) { box.innerHTML = '<p class="small">' + esc(K.errorText(r)) + '</p>'; return; }
          box.innerHTML = r.data.items.length ? r.data.items.map(function (p) {
            return '<div class="between"><span>' + who(p) + ' <span class="small muted">· ID ' + esc(p.bot_id || '—') + '</span></span>' +
              '<button class="btn small" type="button" data-act="clLink" data-a="' + id + '" data-u="' + p.user_id + '" data-n="' + esc(p.full_name) + '" data-e="' + esc(em) + '">Это она</button></div>';
          }).join('') : '<p class="small muted">Никого без входа не нашлось.</p>';
        });
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll('form[data-find]'), function (f) {
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var no = f.getAttribute('data-find'), q = f.querySelector('input').value.trim(), box = document.getElementById('cl-found-' + no);
        K.api('GET', '/api/org/claims/people?q=' + encodeURIComponent(q)).then(function (r) {
          if (!r.ok) { box.innerHTML = '<p class="small">' + esc(K.errorText(r)) + '</p>'; return; }
          box.innerHTML = r.data.items.length ? r.data.items.map(function (p) {
            return '<div class="between"><span>' + who(p) + ' <span class="small muted">· ID ' + esc(p.bot_id || '—') + '</span></span>' +
              '<button class="btn small" type="button" data-act="clApprove" data-no="' + no + '" data-u="' + p.user_id + '" data-n="' + esc(p.full_name) + '">Это она</button></div>';
          }).join('') : '<p class="small muted">Никого без входа не нашлось.</p>';
        });
      });
    });
  }
  K.actions.clOutside = function (b) {
    var no = b.getAttribute('data-no');
    O.confirm({ title: 'Добавить «' + b.getAttribute('data-n') + '» в Игру 01 вне конкурса?',
      html: '<p>Для тех, кого нет в таблице бота. Появится новый вход (email и пароль из заявки), участница будет в Игре 01 вне конкурса: ' +
        'может сдать работы всех туров, включая 1 и 2, до конца Игры. Диплом решаете потом.</p>' +
        '<div class="field"><label for="cl-lg">Лига (нужна, чтобы в эстафете получить исходник своей лиги)</label><select class="input" id="cl-lg">' +
        '<option value="">Без лиги</option><option value="gold">Gold (Лига А)</option><option value="silver">Silver (Лига Б)</option></select></div>',
      ok: 'Добавить', path: '/api/org/claims/' + no + '/add-outside',
      body: function () { var v = document.getElementById('cl-lg').value; return { league: v || null }; },
      done: function () { K.toast('Добавлена вне конкурса — вход открыт'); O.refreshCounts(); K.route(); } });
  };
  K.actions.clApprove = function (b) {
    var no = b.getAttribute('data-no');
    O.confirm({ title: 'Открыть вход для заявки № ' + no + '?', text: 'Запись «' + b.getAttribute('data-n') + '» получит email и пароль из заявки. Отменить это можно только через поддержку.',
      ok: 'Это она', path: '/api/org/claims/' + no + '/approve', body: function () { return { user_id: b.getAttribute('data-u') }; },
      done: function () { K.toast('Вход открыт'); O.refreshCounts(); K.route(); } });
  };
  K.actions.clLink = function (b) {
    O.confirm({ title: 'Соединить с записью «' + b.getAttribute('data-n') + '»?',
      text: 'Вход ' + b.getAttribute('data-e') + ' переедет на запись из бота: участница войдёт тем же email и паролем и увидит свои итоги туров 1–2. Пустой аккаунт закроется. Отменить — только через поддержку.',
      ok: 'Соединить', path: '/api/org/claims/accounts/' + b.getAttribute('data-a') + '/link', body: function () { return { user_id: b.getAttribute('data-u') }; },
      done: function () { K.toast('Соединено — вход на записи из бота'); O.refreshCounts(); K.route(); } });
  };
  K.actions.clReject = function (b) {
    var no = b.getAttribute('data-no');
    O.confirm({ title: 'Отклонить заявку № ' + no + '?', html: '<div class="field"><label for="cl-note">Причина (для журнала)</label><input class="input" id="cl-note" maxlength="500" value="Нет в списке Игры 01"></div>',
      ok: 'Отклонить', danger: true, path: '/api/org/claims/' + no + '/reject', body: function () { return { note: document.getElementById('cl-note').value.trim() || 'Отклонена' }; },
      done: function () { K.toast('Заявка отклонена'); O.refreshCounts(); K.route(); } });
  };
})();
