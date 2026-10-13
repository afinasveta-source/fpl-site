/* Кабинет организатора (этап 3): обзор, Игры, туры и задание тура, сезоны, призы.
   Люди, участницы Игры, документы, поддержка и пожелания — в org-people.js. */
(function () {
  'use strict';
  var K = window.K, esc = K.esc, pill = K.pill, li = K.li;
  var O = K.org = {};

  /* ---------- тексты ---------- */
  O.EVENT = { draft: ['Черновик', 'plain'], registration: ['Опубликована · запись', 'info'], active: ['Идёт', 'ok'], finished: ['Завершена', 'plain'], archived: ['В архиве', 'plain'] };
  O.ROUND = { draft: ['Черновик', 'plain'], plan: ['Запланирован', 'info'], open: ['Идёт сдача', 'acc'], closed: ['Приём закрыт', 'plain'] };
  O.TYPE = { ranked_game: 'Рейтинговая Игра', challenge: 'Открытый челлендж', final: 'Финал сезона', special: 'Особое событие' };
  O.MODE = { 'in': ['В конкурсе', 'ok'], outside: ['Вне конкурса', 'info'], out_pending: ['Не прошла отбор · выбирает', 'warn'], eliminated: ['Выбыла', 'plain'],
    withdrawn: ['Вышла из Игры', 'plain'], disqualified: ['Дисквалифицирована', 'bad'], pending: ['Ждёт подтверждения', 'warn'], completed: ['Завершила', 'plain'] };
  O.WORK = { sent: ['Сдана', 'ok'], sent_late: ['Сдана после срока', 'warn'], missed: ['Не сдана', 'bad'], draft: ['Черновик', 'plain'], none: ['Не начата', 'plain'], plan: ['—', 'plain'] };
  O.LEAGUES = [['bronze', 'Bronze'], ['silver', 'Silver'], ['gold', 'Gold']];
  var TEXT = {
    organizer_only: 'Раздел только для организатора.', nothing_to_change: 'Нечего сохранять — ничего не изменилось.',
    missing_starts_at: 'Укажите начало Игры.', missing_ends_at: 'Укажите конец Игры.', missing_registration_closes_at: 'Укажите конец записи.',
    no_rules: 'Опубликуйте Правила в «Документах» — без них запись не работает.', no_publication: 'Опубликуйте согласие на публикацию работ в «Документах».',
    no_personal_data: 'Нет документа об обработке персональных данных — запись пройдёт без этого согласия.',
    no_rounds: 'Ни одного опубликованного тура — участницы не увидят план Игры.', registration_after_end: 'Запись заканчивается позже конца Игры.',
    draft_rounds: 'Есть туры-черновики: участницы их не видят.', starts_later: 'Дата начала Игры ещё не наступила.',
    rounds_accepting: 'Ещё идёт приём работ: после завершения сдавать будет нельзя ни в конкурсе, ни вне конкурса.',
    rounds_ahead: 'Не все туры прошли.', no_season_number: 'У Игры с дипломом нужен сезон с номером: номер диплома строится из номера сезона и Игры (после старта не меняются).', no_game_number: 'Укажите номер Игры в сезоне: он нужен для номеров дипломов (после старта не меняется).',
    results_not_ready: 'Итоги Игры, очки и дипломы — после завершения Игры, в разделе «Итоги Игры». Скидки — позже.',
    registration_dates: 'Конец записи должен быть позже её начала.', game_dates: 'Конец Игры должен быть позже начала.',
    rounds_after_end: 'Срок сдачи какого-то тура позже нового конца Игры. Сначала поменяйте срок тура.',
    locked_after_start: 'После старта Игры это поле не меняется.', game_finished: 'Игра завершена — её нельзя менять.', date_required: 'Опубликованной Игре или туру нужна эта дата.',
    final_only_ranked: 'В финал сезона идут только рейтинговые Игры.', season_not_found: 'Сезон не найден.', game_no_taken: 'Этот номер Игры в сезоне уже занят.',
    season_no_taken: 'Сезон с таким номером уже есть.', season_dates: 'Конец сезона должен быть позже начала.',
    wrong_status: 'Статус уже изменился. Обновите страницу.', has_participants: 'В Игру уже записались — снять с публикации или удалить нельзя.', not_draft: 'Удалить можно только черновик.',
    missing_opens_at: 'Укажите дату открытия тура.', missing_deadline: 'Укажите срок сдачи.', deadline_before_open: 'Срок сдачи должен быть позже открытия тура.',
    judging_before_deadline: 'Срок оценки — не раньше срока сдачи.', deadline_after_game_end: 'Срок сдачи позже конца Игры — работы вне конкурса до него не успеют.',
    league_deadline_before_open: 'Срок сдачи лиги должен быть позже открытия задания для неё.', league_deadline_after_game_end: 'Срок сдачи лиги позже конца Игры.',
    league_open_after_deadline: 'Открытие задания для лиги должно быть раньше срока сдачи (у лиги без своего срока — раньше общего срока тура).',
    league_open_after_game_end: 'Открытие задания для лиги позже конца Игры.', league_opens_locked: 'Этой лиге задание уже открылось — дату открытия не поменять.',
    no_task: 'Заполните задание.', no_general_text: 'Нужен общий текст задания.', empty_instructions: 'Заполните общий текст задания «для всех» — он нужен, даже если у каждой лиги свой текст (его видят участницы без лиги). И тексты лиг, которые вы включили.',
    opens_before_game: 'Тур открывается раньше начала Игры.', opens_before_previous: 'Тур открывается раньше предыдущего.', opens_in_past: 'Дата открытия уже прошла — тур откроется сразу после публикации.',
    opens_locked: 'Тур уже открыт — дату открытия не поменять.', round_opened: 'Тур уже открыт.', task_issued: 'Задание уже выдано участницам.',
    not_last_round: 'Удалить можно только последний тур.', form_locked: 'Тур открыт — форма сдачи не меняется.', leagues_locked: 'Тур уже открыт — набор лиг не меняется (тексты и сроки — можно).',
    game_draft: 'Игра ещё черновик.', reason_required: 'Укажите причину.', deadline_in_past: 'Новый срок уже прошёл.', not_an_extension: 'Новый срок должен быть позже обычного срока.',
    not_participating: 'Участница не в Игре.', round_not_found: 'Тур не найден.', not_in_competition: 'Участница не в конкурсе.', wrong_state: 'Это действие сейчас недоступно.',
    duplicate_participant: 'Одна участница в списке дважды.', participant_not_in_game: 'Кого-то из списка уже нет в этой Игре — обновите страницу.',
    still_missed: 'Есть пропущенный срок — сверка снова переведёт вне конкурса. Сначала продлите ей срок этого тура.',
    email_taken: 'Этот email уже занят.', telegram_taken: 'Этот Telegram уже у другого человека.', email_locked: 'Email активного аккаунта меняет сам человек.',
    already_active: 'Аккаунт уже активен — нужна ссылка для нового пароля.', not_active: 'Аккаунт ещё не активирован — нужна ссылка-приглашение.',
    cannot_remove_own_admin: 'Снять роль администратора с себя нельзя.', last_admin: 'Это последний администратор.', cannot_suspend_self: 'Нельзя приостановить себя.',
    full_name_required: 'ФИО не может быть пустым.', version_taken: 'Такая редакция уже есть.', scheduled_exists: 'Уже есть запланированная редакция — отмените её или дождитесь выхода.',
    publish_in_past: 'Дата выхода уже прошла.', not_scheduled: 'Отменить можно только ещё не вышедшую редакцию.', title_required: 'Название не может быть пустым.',
    has_links: 'На это уже ссылаются другие записи (например, обращения в поддержку) — удалить нельзя. Оставьте черновиком.',
    league_dates_after_end: 'У какой-то лиги срок сдачи или открытие задания позже нового конца Игры. Сначала поменяйте даты лиги в задании тура.',
    game_not_over: 'Конец Игры ещё не наступил — работы вне конкурса ещё принимаются. Завершите Игру после её конца.',
    personal_deadlines_after_end: 'У кого-то из участниц личный срок позже нового конца Игры. Сначала поменяйте этот срок.'
  };
  O.text = function (code) { return TEXT[code] || code; };
  O.addText = function (map) { Object.keys(map).forEach(function (k) { TEXT[k] = map[k]; }); };
  O.err = function (res) {
    if (res.detail && TEXT[res.detail]) return TEXT[res.detail];
    if (res.status === 422 && res.data && Array.isArray(res.data.detail)) {
      var m = res.data.detail.map(function (e) { return e.msg || ''; }).join(' ');
      if (/one_general_text/.test(m)) return 'Нужен ровно один общий текст задания.';
      if (/nothing_to_submit/.test(m)) return 'Включите хотя бы фото или ссылку.';
      if (/timezone/.test(m)) return 'Укажите дату и время полностью.';
      if (/duplicate_league/.test(m)) return 'Для одной лиги два варианта задания — оставьте один.';
      if (/judges_list/.test(m)) return 'В пуле — не больше 15 судей, без повторов.';
      if (/quota_range/.test(m)) return 'Сколько проходят — число от 1 до 10 000.';
      if (/three values/.test(m)) return 'Нужны три значения от 0 до 1000.';
      return 'Проверьте заполненные поля.';
    }
    if (res.status === 409 && res.detail === 'Data conflicts with existing records') return 'Такая запись уже есть (номер, email или повтор). Обновите страницу и проверьте данные.';
    return K.errorText(res);
  };
  O.st = function (map, key) { var x = map[key] || [key, 'plain']; return pill(x[0], x[1]); };
  O.when = function (iso) { return iso ? K.date(iso) + ' МСК' : '—'; };
  O.dt = function (id, label, iso, extra, hint) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><input class="input" type="datetime-local" id="' + id + '" value="' + esc(K.toInput(iso)) + '"' + (extra || '') + '>' +
      (hint ? '<span class="hint">' + hint + '</span>' : '') + '</div>';
  };
  O.sel = function (id, label, options, value, extra) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><select class="input" id="' + id + '"' + (extra || '') + '>' + options.map(function (o) {
      return '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(value == null ? '' : value) ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
    }).join('') + '</select></div>';
  };
  O.txt = function (id, label, value, extra, hint) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><input class="input" id="' + id + '" value="' + esc(value || '') + '"' + (extra || '') + '>' +
      (hint ? '<span class="hint">' + hint + '</span>' : '') + '</div>';
  };
  O.area = function (id, label, value, extra, hint) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><textarea class="input" id="' + id + '"' + (extra || '') + '>' + esc(value || '') + '</textarea>' +
      (hint ? '<span class="hint">' + hint + '</span>' : '') + '</div>';
  };
  O.chk = function (id, label, on, extra) {
    return '<label class="chk"><input type="checkbox" id="' + id + '"' + (on ? ' checked' : '') + (extra || '') + '> <span>' + label + '</span></label>';
  };
  O.errBox = '<p class="form-err" role="alert" tabindex="-1" hidden></p>';
  O.issues = function (checks) {
    var h = '';
    if (checks.problems.length) h += '<div class="note bad small"><b>Чтобы продолжить:</b><ul>' + checks.problems.map(function (p) { return '<li>' + esc(O.text(p)) + '</li>'; }).join('') + '</ul></div>';
    if (checks.warnings.length) h += '<div class="note warn small"><b>Обратите внимание:</b><ul>' + checks.warnings.map(function (p) { return '<li>' + esc(O.text(p)) + '</li>'; }).join('') + '</ul></div>';
    return h;
  };
  /* Отправить изменения; при ошибке — текст в форме (или во всплывающем сообщении). */
  O.send = function (method, path, body, form, done) {
    if (form) { K.formError(form, ''); K.busy(form, true); }
    return K.api(method, path, body).then(function (r) {
      if (form) K.busy(form, false);
      if (!r.ok) { if (form) K.formError(form, O.err(r)); else K.toast(O.err(r)); return; }
      if (done) done(r.data);
    });
  };
  /* Подтверждение действия (с причиной, если нужна). */
  O.confirm = function (opt) {
    O.pending = opt;
    K.showModal('<h2 id="mT">' + esc(opt.title) + '</h2>' + (opt.html || (opt.text ? '<p>' + esc(opt.text) + '</p>' : '')) +
      (opt.reason ? '<div class="field"><label for="cf-reason">Причина (видна в журнале)</label><textarea class="input" id="cf-reason" maxlength="500"></textarea></div>' : '') +
      '<p class="form-err" role="alert" tabindex="-1" hidden id="cf-err"></p><div class="row"><button class="btn' + (opt.danger ? ' danger' : '') + '" type="button" data-act="orgConfirmed">' + esc(opt.ok || 'Подтвердить') +
      '</button><button class="btn sec" type="button" data-act="closeModal">Отмена</button></div>');
    if (opt.reason) document.getElementById('cf-reason').focus();
  };
  K.actions.orgConfirmed = function (b) {
    var opt = O.pending, r = document.getElementById('cf-reason'), err = document.getElementById('cf-err');
    var reason = r ? r.value.trim() : null;
    if (opt.reason && !reason) { err.textContent = 'Укажите причину.'; err.hidden = false; return; }
    var bad = opt.validate ? opt.validate() : null;
    if (bad) { err.textContent = bad; err.hidden = false; return; }
    b.disabled = true;
    K.api(opt.method || 'POST', opt.path, opt.body ? opt.body(reason) : undefined).then(function (res) {
      if (!res.ok) { b.disabled = false; err.textContent = O.err(res); err.hidden = false; return; }
      var m = b.closest('.modal'); if (m) m.remove(); K.onEscape = null;
      if (opt.done) opt.done(res.data); else K.route();
    });
  };
  O.copy = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { K.toast('Скопировано'); }, function () { K.toast('Выделите ссылку и скопируйте вручную'); });
    }
    K.toast('Выделите ссылку и скопируйте вручную');
  };
  K.actions.copyText = function (b) {
    var i = document.getElementById(b.getAttribute('data-for'));
    if (i) { i.select(); O.copy(i.value); }
  };
  O.refreshCounts = function () {
    return K.api('GET', '/api/org/home').then(function (r) { if (r.ok) { K.state.orgCounts = r.data.counts; O.paintCounts(); } return r; });
  };
  /* Счётчики в меню — без перерисовки страницы (иначе пропали бы обработчики форм и открытое окно). */
  O.paintCounts = function () {
    var c = K.state.orgCounts || {};
    [['/org/support', c.support], ['/org/feedback', c.feedback]].forEach(function (x) {
      Array.prototype.forEach.call(document.querySelectorAll('nav.nav [data-href="' + x[0] + '"]'), function (b) {
        var s = b.querySelector('.cnt');
        if (!x[1]) { if (s) s.remove(); return; }
        if (!s) { s = document.createElement('span'); s.className = 'cnt'; b.appendChild(s); }
        s.textContent = String(x[1]);
      });
    });
  };
  /* Страница организатора: без роли — понятный отказ. */
  O.guard = function () {
    if (K.isAdmin()) return true;
    K.page('<h1>Раздел организатора</h1><div class="note">Он доступен только администраторам лиги.</div><button class="btn sec" type="button" data-href="/">В кабинет участника</button>');
    return false;
  };
  O.on = function (re, fn) { K.on(re, function () { if (O.guard()) fn.apply(null, arguments); }); };

  /* ---------- Обзор ---------- */
  O.on(/^\/org$/, function () {
    K.load(['/api/org/home'], function (d) {
      K.state.orgCounts = d.counts;
      var c = d.counts, h = '<div class="between"><h1>Обзор лиги</h1><button class="btn" type="button" data-href="/org/games">Игры и туры</button></div>';
      var missing = ['rules', 'publication', 'personal_data'].filter(function (k) { return !d.documents[k]; });
      if (missing.length) {
        h += '<div class="note warn"><b>Не опубликованы документы:</b> ' + esc(missing.map(function (k) { return { rules: 'Правила', publication: 'согласие на публикацию', personal_data: 'обработка персональных данных' }[k]; }).join(', ')) +
          '. Без Правил и согласия на публикацию Игру не опубликовать. <button class="lnk" type="button" data-href="/org/documents">Открыть документы</button></div>';
      }
      var todo = (d.alerts || []).map(function (x) { return li(esc(x.title), esc(x.text), pill('Шаг', 'warn'), x.href); });
      if (c.support) todo.push(li('Обращения ждут ответа', c.support + ' в поддержке', pill(String(c.support), 'acc'), '/org/support'));
      if (c.feedback) todo.push(li('Новые пожелания с сайта', 'Анонимные сообщения', pill(String(c.feedback), 'acc'), '/org/feedback'));
      if (c.not_activated) todo.push(li('Не вошли в кабинет', 'Участницы Игр без входа — отправьте им ссылку', pill(String(c.not_activated), 'warn'), '/org/people?kind=not_activated'));
      if (c.drafts) todo.push(li('Черновики Игр', 'Ещё не опубликованы', pill(String(c.drafts), 'plain'), '/org/games'));
      h += '<section class="card"><h2>Требует внимания</h2>' + (todo.length ? '<div class="list">' + todo.join('') + '</div>' : '<p class="muted">Всё спокойно.</p>') + '</section>';
      h += d.games.length ? d.games.map(function (g) {
        var cur = g.current, nx = g.next;
        return '<section class="card"><div class="between"><div><span class="eyebrow">' + esc(O.EVENT[g.status][0]) + '</span><h2>' + esc(g.title) + '</h2></div>' +
          '<button class="btn sec" type="button" data-href="/org/games/' + g.id + '">Открыть</button></div>' +
          '<div class="stats"><div class="stat"><span>Участниц</span><b class="num">' + g.people + '</b><span><button class="lnk" type="button" data-href="/org/games/' + g.id + '/people">список</button></span></div>' +
          (cur ? '<div class="stat"><span>Тур ' + cur.round_no + ' · ' + esc(O.ROUND[cur.state][0]) + '</span><b class="num">' + cur.sent + ' / ' + g.people + '</b><span>сдали' +
            (cur.deadline ? ' · срок ' + esc(K.date(cur.deadline)) : '') + '</span></div>' : '') +
          (nx ? '<div class="stat"><span>Дальше: тур ' + nx.round_no + '</span><b>' + esc(K.day(nx.opens_at) || '—') + '</b><span>открытие</span></div>' : '') +
          (g.status === 'registration' ? '<div class="stat"><span>Запись</span><b>' + esc(g.registration_closes_at ? 'до ' + K.day(g.registration_closes_at) : 'открыта') + '</b><span>' + esc(g.starts_at ? 'старт ' + K.day(g.starts_at) : '') + '</span></div>' : '') +
          '</div></section>';
      }).join('') : '<div class="note">Идущих Игр нет. <button class="lnk" type="button" data-href="/org/games">Создать Игру</button></div>';
      h += '<p class="small muted">Все даты и время — московские (МСК, UTC+3).</p>';
      K.page(h);
    });
  });

  /* ---------- Игры и сезоны ---------- */
  O.on(/^\/org\/games$/, function () {
    K.load(['/api/org/events', '/api/org/seasons'], function (d, s) {
      var groups = [['active', 'Идут'], ['registration', 'Опубликованы, идёт запись'], ['draft', 'Черновики'], ['finished', 'Завершены']];
      var h = '<h1>Игры и туры</h1><form class="card" id="f-new-game" novalidate><h2>Новая Игра</h2><div class="grid2">' +
        O.txt('ng-title', 'Название', '', ' maxlength="150" placeholder="Игра 02"') +
        O.sel('ng-season', 'Сезон', [['', 'Без сезона']].concat(s.seasons.map(function (x) { return [x.id, x.name]; })), s.seasons.length ? s.seasons[s.seasons.length - 1].id : '') +
        O.sel('ng-type', 'Вид', Object.keys(O.TYPE).map(function (k) { return [k, O.TYPE[k]]; }), 'ranked_game') + '</div>' + O.errBox +
        '<button class="btn" type="submit">Создать черновик</button><p class="small muted">Черновик видите только вы. Сроки, туры и задания настраиваются внутри Игры.</p></form>';
      groups.forEach(function (g) {
        var items = d.events.filter(function (e) { return e.status === g[0] || (g[0] === 'finished' && e.status === 'archived'); });
        if (!items.length) return;
        h += '<section class="card"><h2>' + g[1] + '</h2><div class="list">' + items.map(function (e) {
          return li(esc(e.title), esc([e.season, O.TYPE[e.type], e.starts_at ? K.range(e.starts_at, e.ends_at) : 'даты не заданы', 'туров: ' + e.rounds_count, 'участниц: ' + e.people].filter(Boolean).join(' · ')),
            O.st(O.EVENT, e.status), '/org/games/' + e.id);
        }).join('') + '</div></section>';
      });
      if (!d.events.length) h += '<div class="note">Игр пока нет — создайте первую.</div>';
      h += '<section class="card"><h2>Сезоны</h2>' + (s.seasons.length ? '<div class="list">' + s.seasons.map(function (x) {
        return '<details class="more"><summary>' + esc(x.name) + (x.season_no ? ' · №' + x.season_no : '') + ' · Игр: ' + x.games + '</summary>' + seasonForm(x) + '</details>';
      }).join('') + '</div>' : '<p class="muted">Сезонов нет.</p>') + '<details class="more"><summary>Добавить сезон</summary>' + seasonForm(null) + '</details></section>';
      K.page(h, [['Обзор', '/org'], ['Игры и туры']]);
      var f = document.getElementById('f-new-game');
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var title = f.querySelector('#ng-title').value.trim();
        if (!title) { K.formError(f, 'Введите название.'); return; }
        O.send('POST', '/api/org/events', { title: title, season_id: f.querySelector('#ng-season').value || null, event_type: f.querySelector('#ng-type').value }, f, function (ev) {
          K.toast('Черновик создан'); K.go('/org/games/' + ev.id);
        });
      });
      Array.prototype.forEach.call(document.querySelectorAll('form.f-season'), function (sf) {
        sf.addEventListener('submit', function (e) {
          e.preventDefault();
          var id = sf.getAttribute('data-id'), no = sf.querySelector('[name=no]').value;
          var body = { name: sf.querySelector('[name=name]').value.trim(), season_no: no ? +no : null,
            starts_at: K.fromInput(sf.querySelector('[name=starts]').value), ends_at: K.fromInput(sf.querySelector('[name=ends]').value) };
          if (!body.name) { K.formError(sf, 'Введите название сезона.'); return; }
          O.send(id ? 'PATCH' : 'POST', '/api/org/seasons' + (id ? '/' + id : ''), body, sf, function () { K.toast('Сезон сохранён'); K.route(); });
        });
      });
    }, [['Обзор', '/org'], ['Игры и туры']]);
  });
  function seasonForm(x) {
    var id = x ? x.id : 'new';
    return '<form class="stack f-season" novalidate data-id="' + (x ? x.id : '') + '"><div class="grid2">' +
      '<div class="field"><label for="sn-' + id + '">Название</label><input class="input" name="name" id="sn-' + id + '" maxlength="150" value="' + esc(x ? x.name : '') + '"></div>' +
      '<div class="field"><label for="so-' + id + '">Номер сезона</label><input class="input" name="no" id="so-' + id + '" type="number" min="1" max="99" value="' + esc(x && x.season_no ? x.season_no : '') + '"></div>' +
      '<div class="field"><label for="ss-' + id + '">Начало</label><input class="input" name="starts" id="ss-' + id + '" type="datetime-local" value="' + esc(K.toInput(x && x.starts_at)) + '"></div>' +
      '<div class="field"><label for="se-' + id + '">Конец</label><input class="input" name="ends" id="se-' + id + '" type="datetime-local" value="' + esc(K.toInput(x && x.ends_at)) + '"></div></div>' +
      O.errBox + '<button class="btn sec" type="submit">' + (x ? 'Сохранить сезон' : 'Добавить сезон') + '</button></form>';
  }

  /* «Тур 2 · Бабочка»; название по умолчанию («Тур 2») не повторяем. */
  function roundName(r) { return 'Тур ' + r.round_no + (r.title && r.title !== 'Тур ' + r.round_no ? ' · ' + esc(r.title) : ''); }

  /* ---------- Игра ---------- */
  var NEXT = {
    draft: [['publish', 'Опубликовать', 'Опубликовать Игру?', 'Игра появится в каталоге участниц. Запись — по датам записи.']],
    registration: [['start', 'Начать Игру', 'Начать Игру?', 'За Игрой закрепится действующая редакция Правил. После старта нельзя менять вид Игры, сезон, номер и настройки зачёта.'],
      ['unpublish', 'Снять с публикации', 'Снять с публикации?', 'Игра пропадёт из каталога и снова станет черновиком. Можно, пока никто не записался.']],
    active: [['finish', 'Завершить Игру', 'Завершить Игру?', 'Приём работ закроется у всех — и в конкурсе, и вне конкурса.']],
    finished: [['reopen', 'Вернуть в «Идёт»', 'Вернуть Игру в «Идёт»?', 'Только чтобы исправить ошибку: приём работ снова откроется по срокам туров и конца Игры.']]
  };

  O.on(/^\/org\/games\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/org/events/' + id, '/api/org/seasons'], function (e, s) { drawGame(e, s.seasons); }, [['Игры и туры', '/org/games'], ['Игра']]);
  });

  function drawGame(e, seasons) {
    var locked = function (k) { return e.locked.indexOf(k) >= 0 || (e.readonly && k !== 'season_id' && k !== 'game_no'); };
    var dis = function (k) { return locked(k) ? ' disabled' : ''; };
    var p = e.participants || {}, total = 0;
    Object.keys(p).forEach(function (k) { total += p[k]; });
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc([e.season, O.TYPE[e.type]].filter(Boolean).join(' · ')) + '</span>' +
      '<div class="between"><h1>' + esc(e.title) + '</h1>' + O.st(O.EVENT, e.status) + '</div></div>';
    var next = NEXT[e.status] || [];
    h += '<section class="card"><h2>Статус</h2><p class="muted small">' + ({ draft: 'Черновик: участницы Игру не видят.', registration: 'Игра в каталоге, запись — по датам.' + (e.registration_closes_at ? ' Конец записи — ' + esc(O.when(e.registration_closes_at)) + '.' : ''),
      active: 'Игра идёт. Редакция Правил: ' + esc(e.rules_version || '—') + '.', finished: 'Игра завершена: приём работ закрыт.' }[e.status] || '') + '</p>' +
      O.issues(e.checks) + '<div class="row">' + next.map(function (n, i) {
        return '<button class="btn' + (i ? ' sec' : '') + '" type="button" data-act="gameStatus" data-a="' + n[0] + '"' + (n[0] !== 'unpublish' && n[0] !== 'finish' && n[0] !== 'reopen' && e.checks.problems.length ? ' disabled' : '') + '>' + n[1] + '</button>';
      }).join('') + (e.status === 'draft' ? '<button class="btn ghost" type="button" data-act="gameDelete">Удалить черновик</button>' : '') + '</div></section>';
    h += '<section class="card"><div class="between"><h2>Туры</h2>' + (e.readonly ? '' : '<button class="btn sec" type="button" data-act="addRound">Добавить тур</button>') + '</div>' +
      (e.rounds.length ? '<div class="list">' + e.rounds.map(function (r) {
        return li(roundName(r), esc([r.task_title, r.opens_at ? 'открытие ' + K.date(r.opens_at) : 'нет даты открытия', r.deadline ? 'срок ' + K.date(r.deadline) : 'нет срока', r.state !== 'draft' && r.state !== 'plan' ? 'сдали: ' + r.sent : ''].filter(Boolean).join(' · ')),
          O.st(O.ROUND, r.state), '/org/rounds/' + r.id);
      }).join('') + '</div>' : '<p class="muted">Туров пока нет.</p>') + '</section>';
    h += '<section class="card"><div class="between"><h2>Итоги Игры</h2><button class="btn sec" type="button" data-href="/org/games/' + e.id + '/results">' +
      (e.status === 'finished' ? 'Подвести итоги' : 'Формат итогов') + '</button></div><p class="small muted">' +
      (e.status === 'draft' || e.status === 'registration' ? 'Как считается итог, места и очки FPL — задаётся до старта Игры.' : e.status === 'finished' ? 'Места, очки FPL и дипломы.' : 'Подводятся после завершения Игры.') + '</p></section>';
    h += '<section class="card"><div class="between"><h2>Участницы</h2><button class="btn sec" type="button" data-href="/org/games/' + e.id + '/people">Список</button></div>' +
      (total ? '<div class="stats">' + Object.keys(O.MODE).filter(function (k) { return p[k]; }).map(function (k) {
        return '<button class="stat stat-link" type="button" data-href="/org/games/' + e.id + '/people?mode=' + k + '"><span>' + esc(O.MODE[k][0]) + '</span><b class="num">' + p[k] + '</b></button>';
      }).join('') + '</div>' : '<p class="muted">Пока никто не записался.</p>') + '</section>';
    h += '<form class="card" id="f-game" novalidate><h2>Основное</h2><div class="grid2">' + O.txt('g-title', 'Название', e.title, ' maxlength="150"' + (e.readonly ? '' : '')) +
      O.sel('g-type', 'Вид', Object.keys(O.TYPE).map(function (k) { return [k, O.TYPE[k]]; }), e.type, dis('event_type')) +
      O.sel('g-season', 'Сезон', [['', 'Без сезона']].concat(seasons.map(function (x) { return [x.id, x.name]; })), e.season_id || '', dis('season_id')) +
      O.txt('g-no', 'Номер Игры в сезоне', e.game_no || '', ' type="number" min="1" max="99"' + dis('game_no')) + '</div>' +
      O.area('g-desc', 'Описание для участниц', e.description, ' maxlength="5000" data-s="h120"', 'Показывается на странице Игры в каталоге.') +
      '<div class="stack" data-s="g6">' + O.chk('g-rating', 'Влияет на рейтинг FPL', e.affects_rating, dis('affects_rating')) + O.chk('g-points', 'Даёт очки FPL', e.awards_points, dis('awards_points')) +
      O.chk('g-diploma', 'Диплом за прохождение', e.has_diploma, dis('has_diploma')) + O.chk('g-final', 'Засчитывается для финала сезона', e.counts_for_final, dis('counts_for_final')) + '</div>' +
      (e.locked.length && !e.readonly ? '<p class="small muted">Игра началась: вид, сезон, номер и настройки зачёта больше не меняются.</p>' : '') + O.errBox +
      '<button class="btn" type="submit">Сохранить</button></form>';
    h += '<form class="card" id="f-dates" novalidate><h2>Сроки Игры</h2><div class="grid2">' +
      O.dt('d-ro', 'Начало записи', e.registration_opens_at, e.readonly ? ' disabled' : '', 'Пусто — запись открыта сразу после публикации.') +
      O.dt('d-rc', 'Конец записи', e.registration_closes_at, e.readonly ? ' disabled' : '') + O.dt('d-s', 'Начало Игры', e.starts_at, e.readonly ? ' disabled' : '') +
      O.dt('d-e', 'Конец Игры', e.ends_at, e.readonly ? ' disabled' : '', 'Это и срок всех работ вне конкурса.') + '</div>' +
      '<p class="small muted">Время московское (МСК, UTC+3).</p>' + O.errBox + (e.readonly ? '' : '<button class="btn" type="submit">Сохранить сроки</button>') + '</form>';
    h += '<form class="card" id="f-prizes" novalidate><h2>Призы</h2><p class="small muted">Строки «за что — приз» на странице Игры у участниц. Пустые строки не сохраняются.</p><div class="stack" id="prize-rows">' +
      (e.prizes.length ? e.prizes : [{ criterion: '', prize: '', league: null }]).map(prizeRow).join('') + '</div>' +
      '<div class="row"><button class="btn sec" type="button" data-act="addPrize">Добавить строку</button><button class="btn" type="submit">Сохранить призы</button></div>' + O.errBox + '</form>';
    K.page(h, [['Игры и туры', '/org/games'], [e.title]]);
    O.game = e;
    var f = document.getElementById('f-game');
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var title = f.querySelector('#g-title').value.trim(), no = f.querySelector('#g-no').value;
      if (!title) { K.formError(f, 'Название не может быть пустым.'); return; }
      var body = { title: title, description: f.querySelector('#g-desc').value };
      if (!locked('event_type')) body.event_type = f.querySelector('#g-type').value;
      if (!locked('season_id')) body.season_id = f.querySelector('#g-season').value || null;
      if (!locked('game_no')) body.game_no = no ? +no : null;
      [['affects_rating', 'g-rating'], ['awards_points', 'g-points'], ['has_diploma', 'g-diploma'], ['counts_for_final', 'g-final']].forEach(function (x) {
        if (!locked(x[0])) body[x[0]] = f.querySelector('#' + x[1]).checked;
      });
      O.send('PATCH', '/api/org/events/' + e.id, body, f, function (d) { K.toast('Сохранено'); drawGame(d, seasons); });
    });
    var fd = document.getElementById('f-dates');
    fd.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var body = {};
      [['registration_opens_at', 'd-ro'], ['registration_closes_at', 'd-rc'], ['starts_at', 'd-s'], ['ends_at', 'd-e']].forEach(function (x) {
        var v = K.fromInput(fd.querySelector('#' + x[1]).value);
        if (v !== null || e[x[0]] !== null) body[x[0]] = v;
      });
      O.send('PATCH', '/api/org/events/' + e.id, body, fd, function (d) { K.toast('Сроки сохранены'); drawGame(d, seasons); });
    });
    var fp = document.getElementById('f-prizes');
    fp.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var items = Array.prototype.map.call(fp.querySelectorAll('.prize-row'), function (r) {
        return { criterion: r.querySelector('[name=c]').value.trim(), prize: r.querySelector('[name=p]').value.trim(), league: r.querySelector('[name=l]').value || null };
      }).filter(function (x) { return x.criterion || x.prize; });
      if (items.some(function (x) { return !x.criterion || !x.prize; })) { K.formError(fp, 'В каждой строке нужны и «за что», и «приз».'); return; }
      O.send('PUT', '/api/org/events/' + e.id + '/prizes', { items: items }, fp, function (d) { K.toast('Призы сохранены: ' + d.prizes.length); drawGame(d, seasons); });
    });
  }
  var prizeNo = 0;
  function prizeRow(p) {
    var i = ++prizeNo;
    return '<div class="prize-row grid3"><div class="field"><label for="pc' + i + '">За что</label><input class="input" name="c" id="pc' + i + '" maxlength="200" value="' + esc(p.criterion) + '"></div>' +
      '<div class="field"><label for="pp' + i + '">Приз</label><input class="input" name="p" id="pp' + i + '" maxlength="200" value="' + esc(p.prize) + '"></div>' +
      O.sel('pl' + i, 'Лига', [['', 'Все лиги']].concat(O.LEAGUES), p.league || '').replace('<select class="input"', '<select class="input" name="l"') +
      '<button class="btn ghost" type="button" data-act="dropPrize">Убрать</button></div>';
  }
  K.actions.addPrize = function () { document.getElementById('prize-rows').insertAdjacentHTML('beforeend', prizeRow({ criterion: '', prize: '', league: null })); };
  K.actions.dropPrize = function (b) { b.closest('.prize-row').remove(); };
  K.actions.gameStatus = function (b) {
    var e = O.game, a = b.getAttribute('data-a'), n = (NEXT[e.status] || []).filter(function (x) { return x[0] === a; })[0];
    if (!n) return;
    var end = e.completion_deadline || e.ends_at, early = a === 'finish' && end && new Date(end) > new Date();
    var warnEarly = early ? '<div class="note warn"><b>Конец Игры ещё не наступил (' + esc(O.when(end)) + ').</b> До него участницы вне конкурса могут сдавать работы для диплома. ' +
      'Если завершить сейчас, приём закроется у всех и кто не успел — останется без диплома. Обычно Игру завершают после её конца.</div>' : '';
    O.confirm({ title: n[2], html: warnEarly + '<p>' + esc(n[3]) + '</p>' + (e.checks.warnings.length && a !== 'unpublish' ? O.issues({ problems: [], warnings: e.checks.warnings }) : ''),
      ok: early ? 'Всё равно завершить' : n[1], danger: a === 'finish', path: '/api/org/events/' + e.id + '/status', body: function () { return early ? { action: a, early: true } : { action: a }; },
      done: function () { K.toast('Готово'); K.route(); } });
  };
  K.actions.gameDelete = function () {
    var e = O.game;
    O.confirm({ title: 'Удалить черновик «' + e.title + '»?', text: 'Вместе с турами, заданиями и призами. Это не отменить.', ok: 'Удалить', danger: true, method: 'DELETE',
      path: '/api/org/events/' + e.id, done: function () { K.toast('Черновик удалён'); K.go('/org/games'); } });
  };
  K.actions.addRound = function (b) {
    b.disabled = true;
    K.api('POST', '/api/org/events/' + O.game.id + '/rounds', {}).then(function (r) {
      b.disabled = false;
      if (!r.ok) { K.toast(O.err(r)); return; }
      K.toast('Тур ' + r.data.round_no + ' добавлен — заполните его'); K.go('/org/rounds/' + r.data.id);
    });
  };

  /* ---------- Тур ---------- */
  O.on(/^\/org\/rounds\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/org/rounds/' + id], drawRound, [['Игры и туры', '/org/games'], ['Тур']]);
  });

  var FIELD = [['required', 'Обязательно'], ['optional', 'Можно добавить'], ['none', 'Не нужно']];
  function drawRound(r) {
    O.round = r;
    var ro = r.readonly, t = r.task || { title: '', form: { photo: 'required', link: 'required', photo_max: 1 }, variants: [{ league: null, instructions: '' }] };
    var byLeague = {};
    t.variants.forEach(function (v) { byLeague[v.league || 'all'] = v; });
    var crumbs = [['Игры и туры', '/org/games'], [r.event.title, '/org/games/' + r.event.id], ['Тур ' + r.round_no]];
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(r.event.title) + '</span><div class="between"><h1>' + roundName(r) + '</h1>' + O.st(O.ROUND, r.state) + '</div></div>';
    var acts = [];
    if (!ro && r.status === 'draft') acts.push('<button class="btn" type="button" data-act="roundAct" data-a="publish"' + (r.checks.problems.length ? ' disabled' : '') + '>Опубликовать тур</button>');
    if (!ro && r.status === 'scheduled' && !r.all_open) acts.push('<button class="btn" type="button" data-act="roundAct" data-a="open_now">' + (r.state === 'plan' ? 'Открыть сейчас' : 'Открыть сейчас всем лигам') + '</button>');
    if (!ro && r.state === 'plan') acts.push('<button class="btn sec" type="button" data-act="roundAct" data-a="unpublish">Вернуть в черновик</button>');
    if (!ro && r.status === 'draft' && r.is_last) acts.push('<button class="btn ghost" type="button" data-act="roundDelete">Удалить тур</button>');
    h += '<section class="card"><h2>Состояние</h2><p class="small muted">' + ({ draft: 'Черновик: участницы тур не видят. Заполните даты и задание и опубликуйте.', plan: 'Опубликован: виден в плане Игры. Задание откроется ' + esc(O.when(r.opens_at)) + '.',
      open: 'Идёт сдача до ' + esc(O.when(r.deadline)) + '.', closed: 'Приём работ закрыт.' }[r.state] || '') + '</p>' + ownDatesNote(r) + O.issues(r.checks) + (acts.length ? '<div class="row">' + acts.join('') + '</div>' : '') +
      (r.status !== 'draft' ? '<div class="row"><button class="btn sec" type="button" data-href="/org/rounds/' + r.id + '/judging">Судейство тура</button></div>' : '') +
      (r.state !== 'draft' ? '<div class="stats"><div class="stat"><span>Участниц в Игре</span><b class="num">' + r.stats.participants + '</b></div><div class="stat"><span>Открыли задание</span><b class="num">' + r.stats.issued + '</b></div>' +
        '<div class="stat"><span>Сдали в срок</span><b class="num">' + r.stats.on_time + '</b></div><div class="stat"><span>Сдали после срока</span><b class="num">' + r.stats.late + '</b></div>' +
        (r.stats.personal_deadlines ? '<div class="stat"><span>Личных продлений</span><b class="num">' + r.stats.personal_deadlines + '</b></div>' : '') + '</div>' : '') + '</section>';
    h += '<form class="card" id="f-round" novalidate><h2>Название и сроки</h2>' + O.txt('r-title', 'Название тура', r.title, ' maxlength="150"' + (ro ? ' disabled' : '')) + '<div class="grid2">' +
      O.dt('r-open', 'Открытие задания', r.opens_at, ro || r.locks.opens_at ? ' disabled' : '', r.locks.opens_at ? 'Тур уже открыт — дата не меняется.' : '') +
      O.dt('r-deadline', 'Срок сдачи работы', r.deadline, ro ? ' disabled' : '', 'Общий срок. У лиги могут быть свои даты — в задании ниже.') +
      O.dt('r-judging', 'Срок оценки (судьям)', r.judging_deadline, ro ? ' disabled' : '', 'Необязательно. Судейство — следующий этап.') + '</div>' +
      '<p class="small muted">Время московское (МСК, UTC+3).</p>' + O.errBox + (ro ? '' : '<button class="btn" type="submit">Сохранить</button>') + '</form>';
    var lock = r.locks.form, lockedOpen = function (l) { return (r.locks.league_opens || []).indexOf(l) >= 0; };
    h += '<form class="card" id="f-task" novalidate><h2>Задание</h2>' + O.txt('t-title', 'Название задания', t.title, ' maxlength="150"' + (ro ? ' disabled' : ''), 'Своё название у лиги — в её блоке ниже.') +
      O.area('t-all', 'Текст задания (для всех)', (byLeague.all || {}).instructions, ' maxlength="8000" data-s="h160"' + (ro ? ' disabled' : ''),
        'Его получают участницы, у которых лига не указана или у лиги нет своего задания.') +
      '<h3>Что сдаёт участница</h3><div class="grid3">' + O.sel('t-photo', 'Фото работы', FIELD, t.form.photo, lock || ro ? ' disabled' : '') +
      O.sel('t-link', 'Ссылка на публикацию', FIELD, t.form.link, lock || ro ? ' disabled' : '') +
      O.sel('t-max', 'Сколько фото можно', [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return [n, n]; }), t.form.photo_max, lock || ro ? ' disabled' : '') + '</div>' +
      (lock ? '<p class="small muted">Тур открыт — форма сдачи и набор лиг не меняются. Тексты, названия и сроки лиг поправить можно: участницы увидят новый текст и получат уведомление.</p>' : '') +
      '<h3>Отдельно для лиг</h3><p class="small muted">Включите лигу, если у неё своё задание или свои даты: открытие задания и срок сдачи. Пустые поля — общие текст и даты тура.</p>' +
      O.LEAGUES.map(function (l) {
        var v = byLeague[l[0]], on = !!v;
        return '<fieldset class="league-box" data-league="' + l[0] + '"><legend>' + O.chk('lg-' + l[0], 'Отдельно для ' + l[1], on, (lock || ro ? ' disabled' : '') + ' data-act="toggleLeague" data-l="' + l[0] + '"') + '</legend>' +
          '<div class="stack league-fields"' + (on ? '' : ' hidden') + '>' + O.txt('lt-' + l[0], 'Название для ' + l[1], v ? v.title : '', ' maxlength="150"' + (ro ? ' disabled' : ''), 'Пусто — общее название.') +
          O.area('li-' + l[0], 'Текст для ' + l[1], v ? v.instructions : '', ' maxlength="8000" data-s="h120"' + (ro ? ' disabled' : ''), 'Пусто — общий текст задания (и его будущие правки).') +
          '<div class="grid2">' + O.dt('lo-' + l[0], 'Открытие задания для ' + l[1], v ? v.opens_at : null, ro || lockedOpen(l[0]) ? ' disabled' : '',
            lockedOpen(l[0]) ? 'Задание этой лиге уже открылось.' : 'Пусто — общее открытие тура.') +
          O.dt('ld-' + l[0], 'Срок сдачи для ' + l[1], v ? v.deadline : null, ro ? ' disabled' : '', 'Пусто — общий срок тура.') + '</div></div></fieldset>';
      }).join('') + O.errBox + (ro ? '' : '<button class="btn" type="submit">Сохранить задание</button>') + '</form>';
    K.page(h, crumbs);
    var f = document.getElementById('f-round');
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var title = f.querySelector('#r-title').value.trim();
      if (!title) { K.formError(f, 'Название не может быть пустым.'); return; }
      var body = { title: title, deadline: K.fromInput(f.querySelector('#r-deadline').value), judging_deadline: K.fromInput(f.querySelector('#r-judging').value) };
      if (!r.locks.opens_at) body.opens_at = K.fromInput(f.querySelector('#r-open').value);
      if (body.deadline === null && r.deadline === null) delete body.deadline;
      if (body.judging_deadline === null && r.judging_deadline === null) delete body.judging_deadline;
      if (body.opens_at === null && r.opens_at === null) delete body.opens_at;
      O.send('PATCH', '/api/org/rounds/' + r.id, body, f, function (d) { K.toast('Сохранено'); drawRound(d); });
    });
    var ft = document.getElementById('f-task');
    ft.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var title = ft.querySelector('#t-title').value.trim();
      if (!title) { K.formError(ft, 'Введите название задания.'); return; }
      var photo = ft.querySelector('#t-photo').value, link = ft.querySelector('#t-link').value;
      if (photo === 'none' && link === 'none') { K.formError(ft, 'Включите хотя бы фото или ссылку.'); return; }
      var variants = [{ league: null, instructions: ft.querySelector('#t-all').value }];
      O.LEAGUES.forEach(function (l) {
        if (!ft.querySelector('#lg-' + l[0]).checked) return;
        variants.push({ league: l[0], title: ft.querySelector('#lt-' + l[0]).value.trim() || null, instructions: ft.querySelector('#li-' + l[0]).value,
          opens_at: K.fromInput(ft.querySelector('#lo-' + l[0]).value), deadline: K.fromInput(ft.querySelector('#ld-' + l[0]).value) });
      });
      O.send('PUT', '/api/org/rounds/' + r.id + '/task', { title: title, form: { photo: photo, link: link, photo_max: +ft.querySelector('#t-max').value }, variants: variants }, ft, function (d) {
        K.toast(d.notified ? 'Сохранено. Уведомление получили: ' + d.notified : 'Задание сохранено'); drawRound(d);
      });
    });
  }
  K.actions.toggleLeague = function (el) {
    var box = el.closest('.league-box');
    box.querySelector('.league-fields').hidden = !el.checked;
  };
  K.actions.roundAct = function (b) {
    var r = O.round, a = b.getAttribute('data-a');
    var info = { publish: ['Опубликовать тур?', 'Тур появится в плане Игры, задание откроется ' + O.when(r.opens_at) + '.', 'Опубликовать'],
      open_now: ['Открыть задание сейчас?', 'Задание сразу увидят участницы всех лиг (свои будущие даты открытия у лиг снимутся). Срок сдачи — ' + O.when(r.deadline) + (ownDates(r).length ? ', у лиг со своим сроком — свой' : '') + '.', 'Открыть всем'],
      unpublish: ['Вернуть тур в черновик?', 'Участницы перестанут видеть его в плане Игры.', 'В черновик'] }[a];
    O.confirm({ title: info[0], html: '<p>' + esc(info[1]) + '</p>' + (a === 'publish' && r.checks.warnings.length ? O.issues({ problems: [], warnings: r.checks.warnings }) : ''), ok: info[2],
      path: '/api/org/rounds/' + r.id + '/status', body: function () { return { action: a }; }, done: function (d) { K.toast('Готово'); drawRound(d); } });
  };
  function ownDates(r) {
    return ((r.task && r.task.variants) || []).filter(function (v) { return v.league && (v.opens_at || v.deadline); });
  }
  function ownDatesNote(r) {
    var list = ownDates(r);
    if (!list.length) return '';
    return '<ul class="small muted league-dates">' + list.map(function (v) {
      return '<li><b>' + esc(K.LEAGUE[v.league]) + ':</b> открытие ' + esc(O.when(v.opens_at || r.opens_at)) + ', срок ' + esc(O.when(v.deadline || r.deadline)) + '</li>';
    }).join('') + '</ul>';
  }
  K.actions.roundDelete = function () {
    var r = O.round;
    O.confirm({ title: 'Удалить тур ' + r.round_no + '?', text: 'Вместе с заданием. Это не отменить.', ok: 'Удалить', danger: true, method: 'DELETE', path: '/api/org/rounds/' + r.id,
      done: function () { K.toast('Тур удалён'); K.go('/org/games/' + r.event.id); } });
  };
})();
