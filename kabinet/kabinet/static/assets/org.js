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
    relay_opens_before_source_deadline: 'Эстафета: вторая лига должна открываться не раньше срока сдачи первой — иначе исходников ещё нет. Поставьте лиге-получателю своё открытие задания.',
    relay_dates_missing: 'Эстафета: у обеих лиг должны быть дата открытия и срок сдачи.', relay_started: 'Исходники уже розданы — эстафету не поменять.', relay_released: 'Исходники уже отправлены — число лучших не поменять.',
    league_locked_judging: 'Лигу сейчас не поменять: в туре идёт судейство этой лиги. После публикации итогов тура — можно.',
    work_outside_started_pool: 'Работа участницы относится к лиге, которую уже судят, но в её пуле работы нет (лигу поменяли?). Напишите в поддержку кабинета.',
    relay_second_open: 'Второй лиге задание уже открылось — эстафету не поменять.', relay_open_now: 'В туре-эстафете лиги открываются по своим датам — «Открыть сейчас» недоступно.',
    relay_both_leagues: 'Выберите обе лиги.', relay_same_league: 'Лиги должны быть разными.',
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
  /* Счётчики «ждёт ответа» в меню — общие для всего кабинета (core.js, K.attention): без перерисовки страницы. */
  O.refreshCounts = function () { return K.attention.fetch(); };
  O.paintCounts = function () { K.attention.paint(); };
  /* Страница организатора: без роли — понятный отказ. */
  O.guard = function () {
    if (K.isAdmin()) return true;
    K.page('<h1>Раздел организатора</h1><div class="note">Он доступен только администраторам лиги.</div><button class="btn sec" type="button" data-href="/">В кабинет участника</button>');
    return false;
  };
  O.on = function (re, fn) { K.on(re, function () { if (O.guard()) fn.apply(null, arguments); }); };

  /* ---------- Обзор (17.10: дашборд) ----------
     Сверху — «Сейчас»: идущий тур, по лигам — сколько осталось до срока (тикает), сколько сдали; судейство — у кого сколько.
     Дальше — цифры за сутки и неделю, «Требует внимания», ближайшие даты и лента последних событий. */
  var LGNAME = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze', none: 'Без лиги' };
  function left(ms) {
    if (ms <= 0) return 'срок прошёл';
    var m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
    return d ? d + ' д ' + h + ' ч' : h ? h + ' ч ' + mm + ' мин' : mm + ' мин';
  }
  function ago(iso) {
    var m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (m < 1) return 'только что';
    if (m < 60) return m + ' мин назад';
    if (m < 24 * 60) return Math.floor(m / 60) + ' ч назад';
    return K.date(iso);
  }
  function bar(done, total) {
    var pct = total ? Math.round(done / total * 100) : 0;
    return '<span class="jbar" aria-hidden="true"><span data-w="' + Math.min(100, Math.round(pct / 5) * 5) + '"></span></span>';
  }
  function deadlineOf(r, lg) {
    var x = (r.league_dates || []).filter(function (y) { return y.league === lg; })[0];
    return x ? x.deadline : r.deadline;
  }
  function nowCard(g, pulse) {
    if (!g) return '';
    var rounds = g.rounds.filter(function (r) { return ['open', 'closed', 'judging'].indexOf(r.phase) >= 0; });
    var base = '/org/games/' + g.id, h = '';
    if (!rounds.length) {
      var nx = g.rounds.filter(function (r) { return r.phase === 'plan'; })[0];
      return '<section class="card dash-now"><span class="eyebrow">Сейчас · ' + esc(g.title) + '</span><h2>' + (nx ? 'Следующий тур ' + nx.round_no + ' — ' + esc(nx.title || '') : 'Туры не идут') + '</h2>' +
        (nx && nx.opens_at ? '<p class="dash-big"><span data-until="' + esc(nx.opens_at) + '">' + left(new Date(nx.opens_at) - Date.now()) + '</span> <span class="small muted">до открытия · ' + esc(K.date(nx.opens_at)) + '</span></p>' : '') + '</section>';
    }
    rounds.forEach(function (r) {
      h += '<section class="card dash-now"><div class="between"><div><span class="eyebrow">Сейчас · ' + esc(g.title) + '</span><h2>Тур ' + r.round_no + (r.title ? ' · ' + esc(r.title) : '') + '</h2></div>' +
        O.st(O.PHASE, r.phase) + '</div>';
      var lgs = ['gold', 'silver', 'bronze', 'none'].filter(function (k) { return r.by_league && r.by_league[k] && (r.by_league[k].in_now || r.by_league[k].sent); });
      if (!lgs.length && (r.phase === 'open' || r.phase === 'closed')) {   // участниц с лигой ещё нет — общий срок тура
        var open0 = r.deadline && new Date(r.deadline) > Date.now();
        h += '<div class="dash-lgs"><div class="dash-lg"><div class="between"><b>Все лиги</b>' + (r.deadline ? '<span class="dash-left"' + (open0 ? ' data-until="' + esc(r.deadline) + '"' : '') + '>' +
          (open0 ? left(new Date(r.deadline) - Date.now()) : 'приём закрыт') + '</span>' : '') + '</div>' + (r.deadline ? '<span class="small muted">срок ' + esc(K.date(r.deadline)) + '</span>' : '') +
          '<span class="small">сдали <b>' + ((r.works && r.works.sent) || 0) + '</b></span></div></div>';
      }
      if (r.phase === 'open' || r.phase === 'closed') {
        h += '<div class="dash-lgs">' + lgs.map(function (k) {
          var x = r.by_league[k], dl = deadlineOf(r, k), inDone = x.missing_in != null ? x.in_now - x.missing_in : null;
          var open = dl && new Date(dl) > Date.now();
          return '<div class="dash-lg"><div class="between"><b>' + LGNAME[k] + '</b>' +
            (dl ? '<span class="dash-left' + (open && new Date(dl) - Date.now() < 24 * 3600e3 ? ' soon' : '') + '"' + (open ? ' data-until="' + esc(dl) + '"' : '') + '>' + (open ? left(new Date(dl) - Date.now()) : 'приём закрыт') + '</span>' : '') + '</div>' +
            (dl ? '<span class="small muted">срок ' + esc(K.date(dl)) + '</span>' : '') +
            (inDone != null ? bar(inDone, x.in_now) + '<span class="small">в конкурсе сдали <b>' + inDone + '</b> из ' + x.in_now + '</span>' : '<span class="small">сдали <b>' + x.sent + '</b></span>') +
            (x.sent - (inDone || 0) > 0 && inDone != null ? '<span class="small muted">ещё ' + (x.sent - inDone) + ' — вне конкурса или после срока</span>' : '') + '</div>';
        }).join('') + '</div>';
      }
      if (r.judging) {
        var js = (pulse.judges || []).filter(function (j) { return j.round_id === r.id; });
        h += '<div class="dash-judging"><div class="between"><b>Судейство</b><span class="small">' + r.judging.done + ' из ' + r.judging.total + ' (' + (r.judging.total ? Math.round(r.judging.done / r.judging.total * 100) : 0) + '%)</span></div>' + bar(r.judging.done, r.judging.total) +
          (js.length ? '<ul class="dash-judges">' + js.map(function (st) {
            return st.judges.map(function (j) {
              return '<li><span>' + esc(j.name) + (st.league ? ' <span class="muted small">· ' + LGNAME[st.league] + '</span>' : '') + '</span>' + bar(j.done, j.total) +
                '<span class="small' + (j.total && j.done < j.total ? '' : ' muted') + '">' + j.done + '/' + j.total + (j.last_at ? ' · ' + esc(ago(j.last_at)) : j.done ? '' : ' · не начинала') + '</span></li>';
            }).join('');
          }).join('') + '</ul>' : '') +
          (js[0] && js[0].deadline ? '<p class="small muted">Оценить до ' + esc(K.date(js[0].deadline)) + ' · <span data-until="' + esc(js[0].deadline) + '">' + left(new Date(js[0].deadline) - Date.now()) + '</span></p>' : '') +
          '<button class="btn sec small" type="button" data-href="/org/rounds/' + r.id + '/judging">Открыть судейство</button></div>';
      }
      h += '<div class="row"><button class="btn small" type="button" data-href="/org/rounds/' + r.id + '">Тур</button><button class="btn sec small" type="button" data-href="' + base + '/people">Участницы</button></div></section>';
    });
    return h;
  }
  function upcoming(g) {
    if (!g) return [];
    var out = [], now = Date.now(), lim = now + 21 * 24 * 3600e3;
    function add(at, text, href) { if (at && new Date(at) > now && new Date(at) < lim) out.push({ at: at, text: text, href: href }); }
    g.rounds.forEach(function (r) {
      if (r.phase === 'plan') add(r.opens_at, 'Тур ' + r.round_no + ': открытие', '/org/rounds/' + r.id);
      var lgd = r.league_dates || [];
      if (lgd.length) lgd.forEach(function (x) { if (x.opens_at !== r.opens_at && r.phase === 'plan') add(x.opens_at, 'Тур ' + r.round_no + ', ' + LGNAME[x.league] + ': открытие', '/org/rounds/' + r.id); add(x.deadline, 'Тур ' + r.round_no + ', ' + LGNAME[x.league] + ': срок сдачи', '/org/rounds/' + r.id); });
      if (!lgd.length || lgd.length < 2) add(r.deadline, 'Тур ' + r.round_no + ': срок сдачи' + (lgd.length ? ' (остальные лиги)' : ''), '/org/rounds/' + r.id);
      add(r.judging_deadline, 'Тур ' + r.round_no + ': оценка судей до', '/org/rounds/' + r.id + '/judging');
    });
    add(g.ends_at, 'Конец Игры', '/org/games/' + g.id);
    return out.sort(function (a, b) { return new Date(a.at) - new Date(b.at); }).slice(0, 8);
  }
  var FEEDK = { work: ['Работа', 'ok'], join: ['Запись', 'info'], support: ['Поддержка', 'acc'], claim: ['Заявка', 'warn'], feedback: ['Пожелание', 'plain'] };
  var dashTick = null;
  function tick() {
    var els = document.querySelectorAll('[data-until]');
    if (!document.querySelector('.dash')) { clearInterval(dashTick); dashTick = null; return; }
    Array.prototype.forEach.call(els, function (el) { el.textContent = left(new Date(el.getAttribute('data-until')) - Date.now()); });
  }
  O.on(/^\/org$/, function () {
    K.load(['/api/org/home', '/api/org/games/overview', '/api/org/pulse'], function (d, ov, pulse) {
      K.state.orgCounts = d.counts; K.attention.last = Date.now();   // те же цифры, что в меню (/api/org/attention)
      var c = d.counts, n = pulse.numbers, cur = ov.current && ['active', 'registration'].indexOf(ov.current.status) >= 0 ? ov.current : null;
      var h = '<div class="dash"><div class="between"><h1>Обзор лиги</h1><span class="small muted">обновлено ' + esc(K.date(pulse.now)) + ' МСК · <button class="lnk" type="button" data-act="reload">обновить</button></span></div>';
      var missing = ['rules', 'publication', 'personal_data'].filter(function (k) { return !d.documents[k]; });
      if (missing.length) {
        h += '<div class="note warn"><b>Не опубликованы документы:</b> ' + esc(missing.map(function (k) { return { rules: 'Правила', publication: 'согласие на публикацию', personal_data: 'обработка персональных данных' }[k]; }).join(', ')) +
          '. Без Правил и согласия на публикацию Игру не опубликовать. <button class="lnk" type="button" data-href="/org/documents">Открыть документы</button></div>';
      }
      h += nowCard(cur, pulse);
      var m = n.messengers || {};
      h += '<div class="stats dash-kpi">' +
        '<div class="stat"><span>Сдано работ за сутки</span><b class="num">' + n.works_24h + '</b><span>за неделю ' + n.works_7d + '</span></div>' +
        '<div class="stat"><span>Заходили в кабинет за сутки</span><b class="num">' + n.logins_24h + '</b><span>новых аккаунтов за неделю ' + n.accounts_7d + '</span></div>' +
        '<div class="stat"><span>Записались за неделю</span><b class="num">' + n.joined_7d + '</b><span>в Игры</span></div>' +
        '<div class="stat"><span>Уведомления в мессенджерах</span><b class="num">' + (m.any || 0) + ' / ' + (m.people || 0) + '</b><span>' +
          ((m.channels || []).length ? 'Telegram ' + m.telegram + ' · ВКонтакте ' + m.vk : 'бот ещё не подключён') + '</span></div></div>';
      var todo = (d.alerts || []).map(function (x) { return li(esc(x.title), esc(x.text), pill('Шаг', 'warn'), x.href); });
      if (c.support) todo.push(li('Обращения ждут ответа', 'Последней написала участница', pill(String(c.support), 'acc'), '/org/support'));
      if (c.feedback) todo.push(li('Новые пожелания с сайта', 'Анонимные сообщения', pill(String(c.feedback), 'acc'), '/org/feedback'));
      if (c.claims) todo.push(li('Заявки на вход из бота', [c.claims_pending ? 'заявок: ' + c.claims_pending : '', c.accounts ? 'завели кабинет сами, похожи на участницу из бота: ' + c.accounts : ''].filter(Boolean).join(' · ') ||
        'Участницы Игры 01 ждут, когда вы откроете им вход', pill(String(c.claims), 'acc'), '/org/claims'));
      if (!c.moved_games) todo.push(li('Перенос Игры 01 из бота', 'Загрузите таблицу туров 1–2 — Игра продолжится в кабинете', pill('Шаг', 'warn'), '/org/import'));
      if (c.reviews) todo.push(li('Разборы от судьи', 'Новые заказы и оплаченные — ждут действий', pill(String(c.reviews), 'acc'), '/org/reviews'));
      if (c.not_activated) todo.push(li('Не вошли в кабинет', 'Участницы Игр без входа — отправьте им ссылку', pill(String(c.not_activated), 'warn'), '/org/people?kind=not_activated'));
      if (c.drafts) todo.push(li('Черновики Игр', 'Ещё не опубликованы', pill(String(c.drafts), 'plain'), '/org/games'));
      var dates = upcoming(cur);
      h += '<div class="dash-cols"><div class="stack">' +
        '<section class="card"><h2>Требует внимания</h2>' + (todo.length ? '<div class="list">' + todo.join('') + '</div>' : '<p class="muted">Всё спокойно.</p>') + '</section>' +
        (dates.length ? '<section class="card"><h2>Ближайшие даты</h2><ul class="dash-dates">' + dates.map(function (x) {
          return '<li><button class="lnk" type="button" data-href="' + x.href + '">' + esc(x.text) + '</button><span class="small">' + esc(K.date(x.at)) + '</span><span class="small muted" data-until="' + esc(x.at) + '">' + left(new Date(x.at) - Date.now()) + '</span></li>';
        }).join('') + '</ul></section>' : '') + '</div>' +
        '<section class="card"><h2>Последние события</h2>' + (pulse.feed.length ? '<ul class="dash-feed">' + pulse.feed.map(function (x) {
          return '<li><span class="small muted dash-ago" title="' + esc(K.date(x.at)) + '">' + esc(ago(x.at)) + '</span>' + pill(FEEDK[x.kind][0], FEEDK[x.kind][1]) +
            '<span><button class="lnk" type="button" data-href="' + esc(x.href) + '">' + esc(x.name) + '</button> <span class="small">' + esc(x.text) + (x.league ? ' · ' + LGNAME[x.league] : '') + '</span></span></li>';
        }).join('') + '</ul>' : '<p class="muted">За три дня событий не было.</p>') + '</section></div>';
      var others = d.games.filter(function (g) { return !cur || g.id !== cur.id; });
      h += others.map(function (g) {
        return '<section class="card"><div class="between"><div><span class="eyebrow">' + esc(O.EVENT[g.status][0]) + '</span><h2>' + esc(g.title) + '</h2></div>' +
          '<button class="btn sec" type="button" data-href="/org/games/' + g.id + '">Открыть</button></div>' +
          '<p class="small">Участниц: ' + g.people + (g.status === 'registration' ? ' · запись ' + esc(g.registration_closes_at ? 'до ' + K.day(g.registration_closes_at) : 'открыта') + (g.starts_at ? ' · старт ' + K.day(g.starts_at) : '') : '') + '</p></section>';
      }).join('');
      if (!d.games.length) h += '<div class="note">Идущих Игр нет. <button class="lnk" type="button" data-href="/org/games">Создать Игру</button></div>';
      h += '<p class="small muted">Все даты и время — московские (МСК, UTC+3).</p></div>';
      K.page(h);
      if (dashTick) clearInterval(dashTick);
      dashTick = setInterval(tick, 30000);
    });
  });

  /* ---------- Игры и туры (17.10) ----------
     Сверху — текущая Игра большой карточкой: туры по порядку, у каждого — что с ним сейчас и цифры (сдали, после срока,
     в конкурсе ещё не сдали, итоги, ход судейства). Ниже — сезоны и их Игры. Внизу, свёрнуто, — новая Игра и сезоны. */
  O.PHASE = { draft: ['Черновик', 'plain'], plan: ['Запланирован', 'info'], open: ['Идёт сдача', 'acc'], closed: ['Приём закрыт · ждёт судейства', 'warn'],
    judging: ['Судейство', 'acc'], published: ['Итоги опубликованы', 'ok'], bot: ['Прошёл в боте', 'plain'] };
  var LGN = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze', none: 'Без лиги' };
  var LG_ORDER = ['gold', 'silver', 'bronze', 'none'];
  function seasonGameName(e, season) {
    return [season ? season.name || (season.season_no ? 'Сезон ' + season.season_no : '') : '', e.game_no ? 'Игра ' + ('0' + e.game_no).slice(-2) : ''].filter(Boolean).join(' · ');
  }
  function num(n, word) { return '<span class="gn"><b class="num">' + n + '</b> ' + word + '</span>'; }
  function roundCard(r, eid) {
    var w = r.works || {}, j = r.judging, lines = [];
    var dates = r.phase === 'draft' && !r.opens_at ? 'даты не заданы' :
      [r.opens_at ? 'открытие ' + K.date(r.opens_at) : 'нет даты открытия', r.deadline ? 'срок ' + K.date(r.deadline) : 'нет срока',
        r.judging_deadline && r.phase !== 'bot' ? 'оценка до ' + K.date(r.judging_deadline) : ''].filter(Boolean).join(' · ') + ' МСК';
    var lgDates = (r.league_dates || []).map(function (x) {
      return LGN[x.league] + ': ' + (x.opens_at && x.opens_at !== r.opens_at ? 'открытие ' + K.date(x.opens_at) + ', ' : '') + 'срок ' + K.date(x.deadline);
    }).join(' · ');
    var nums = [];
    if (r.phase === 'bot') {
      nums.push(num(w.results || 0, 'итогов из бота'), num(w.advanced || 0, 'прошли дальше'), num(w.sent || 0, 'фото в архиве'));
    } else if (r.phase === 'open' || r.phase === 'closed' || r.phase === 'judging' || r.phase === 'published') {
      nums.push(num(w.sent || 0, 'сдали'));
      if (w.late) nums.push(num(w.late, 'после срока'));
      if (w.missing_in != null && (r.phase === 'open' || r.phase === 'closed')) nums.push(num(w.missing_in, r.phase === 'open' ? 'в конкурсе ещё не сдали' : 'в конкурсе не сдали'));
      if (r.phase === 'published') nums.push(num(w.results || 0, 'с итогом'), num(w.advanced || 0, 'прошли дальше'));
    }
    if (j) {
      var pct = j.total ? Math.round(j.done / j.total * 100) : 0;
      lines.push('<div class="rnd-judge"><span class="small">Судейство: ' + j.works + ' работ · оценено ' + j.done + ' из ' + j.total + ' (' + pct + '%)</span>' +
        '<span class="jbar" aria-hidden="true"><span data-w="' + Math.min(100, Math.round(pct / 5) * 5) + '"></span></span></div>');
    }
    var lg = LG_ORDER.filter(function (k) { return r.by_league && r.by_league[k]; });
    var hasNums = ['open', 'closed', 'judging', 'published', 'bot'].indexOf(r.phase) >= 0;
    if (hasNums && (lg.length > 1 || (lg.length === 1 && lg[0] !== 'none'))) {
      lines.push('<dl class="rnd-lg">' + lg.map(function (k) {
        var x = r.by_league[k], t = [];
        if (r.phase === 'bot') t.push('итогов ' + x.results, 'прошли ' + x.advanced, 'фото ' + x.sent);
        else {
          t.push('сдали ' + x.sent);
          if (x.late) t.push('после срока ' + x.late);
          if (x.missing_in != null) t.push('не сдали в конкурсе ' + x.missing_in + ' из ' + x.in_now);
          if (r.phase === 'published') t.push('итог ' + x.results + ', прошли ' + x.advanced);
        }
        if (j) { var s = j.streams.filter(function (st) { return st.league === k; })[0]; if (s) t.push('судейство ' + s.done + '/' + s.total); }
        return '<dt>' + LGN[k] + '</dt><dd>' + esc(t.join(' · ')) + '</dd>';
      }).join('') + '</dl>');
    }
    // Карточка тура целиком ведёт на страницу тура; с клавиатуры — кнопка-название.
    return '<div class="rnd' + (r.current ? ' now' : '') + '" data-href="/org/rounds/' + r.id + '"><span class="rnd-no" aria-hidden="true">' + r.round_no + '</span>' +
      '<div class="rnd-body"><div class="rnd-head"><button class="lnk rnd-link" type="button" data-href="/org/rounds/' + r.id + '">' + roundName(r) + '</button>' +
      (r.current ? '<span class="small muted">сейчас</span>' : '') + O.st(O.PHASE, r.phase) + '</div>' +
      (r.task_title && r.task_title !== 'Задание тура ' + r.round_no && r.task_title !== r.title ? '<div class="small muted">' + esc(r.task_title) + '</div>' : '') +
      '<div class="small">' + esc(dates) + '</div>' + (lgDates ? '<div class="small muted">' + esc(lgDates) + '</div>' : '') +
      (nums.length ? '<div class="rnd-nums">' + nums.join('') + '</div>' : '') + lines.join('') + '</div></div>';
  }
  function currentCard(e) {
    var p = e.people || {}, base = '/org/games/' + e.id, season = e.season ? { name: e.season } : null;
    var label = { active: 'Идёт сейчас', registration: 'Скоро · идёт запись', finished: 'Последняя Игра', archived: 'Последняя Игра', draft: 'Готовится' }[e.status] || '';
    var done = e.rounds.filter(function (r) { return r.phase === 'published' || r.phase === 'bot'; }).length;
    var h = '<section class="card game-now"><div class="between"><div class="stack" data-s="g4"><span class="eyebrow">' + esc([label, seasonGameName(e, season)].filter(Boolean).join(' · ')) + '</span>' +
      '<h2>' + esc(e.title) + '</h2><span class="small muted">' + esc([e.starts_at ? K.range(e.starts_at, e.ends_at) : 'даты не заданы', e.rounds.length ? 'туров ' + e.rounds.length + ', прошло ' + done : ''].filter(Boolean).join(' · ')) + '</span></div>' +
      O.st(O.EVENT, e.status) + '</div>';
    h += '<div class="stats"><button class="stat-link" type="button" data-href="' + base + '/people"><span>Участниц</span><b class="num">' + p.total + '</b></button>' +
      [['in', 'В конкурсе'], ['outside', 'Вне конкурса'], ['out', 'Выбыли']].map(function (x) {
        return '<button class="stat-link" type="button" data-href="' + base + '/people?status=' + x[0] + '"><span>' + x[1] + '</span><b class="num">' + (p[x[0]] || 0) + '</b></button>';
      }).join('') + '</div>';
    var lgs = LG_ORDER.filter(function (k) { return p.leagues && p.leagues[k]; });
    if (lgs.length) {
      h += '<div class="lg-chips">' + lgs.map(function (k) {
        var x = p.leagues[k];
        return '<button class="lg-chip" type="button" data-href="' + base + '/people?league=' + k + '"><b>' + LGN[k] + ' · ' + x.total + '</b><span>' +
          esc([x['in'] ? 'в конкурсе ' + x['in'] : '', x.outside ? 'вне ' + x.outside : '', x.out ? 'выбыли ' + x.out : ''].filter(Boolean).join(' · ') || '—') + '</span></button>';
      }).join('') + '</div>';
    }
    h += '<div class="row"><button class="btn" type="button" data-href="' + base + '/people">Участницы</button>' +
      '<button class="btn sec" type="button" data-href="' + base + '/results">' + (e.results_published ? 'Итоги Игры' : e.status === 'finished' ? 'Подвести итоги' : 'Итоги Игры') + '</button>' +
      '<button class="btn sec" type="button" data-href="' + base + '">Настройки Игры</button></div>';
    h += '<h3 class="rnd-title">Туры</h3>' + (e.rounds.length ? '<div class="rnds">' + e.rounds.map(function (r) { return roundCard(r, e.id); }).join('') + '</div>' :
      '<p class="muted">Туров пока нет. <button class="lnk" type="button" data-href="' + base + '">Добавить тур в настройках Игры</button></p>');
    return h + '</section>';
  }
  function gameRow(g) {
    var p = g.people;
    return li(esc(g.title) + (g.current ? ' <span class="small muted">· наверху</span>' : ''),
      esc([g.starts_at ? K.range(g.starts_at, g.ends_at) : 'даты не заданы', 'туров: ' + g.rounds_count + (g.rounds_done ? ' (итоги: ' + g.rounds_done + ')' : ''),
        'участниц: ' + p.total + (p.total ? ' (в конкурсе ' + p['in'] + ', вне ' + p.outside + (p.out ? ', выбыли ' + p.out : '') + ')' : '')].join(' · ')),
      O.st(O.EVENT, g.status), '/org/games/' + g.id);
  }
  O.on(/^\/org\/games$/, function () {
    K.load(['/api/org/games/overview'], function (d) {
      var h = '<div class="between"><h1>Игры и туры</h1></div>';
      h += d.current ? currentCard(d.current) : '<div class="note">Игр пока нет. Создайте первую — внизу страницы, «Новая Игра».</div>';
      // Сезоны: сезон текущей Игры раскрыт, остальные свёрнуты.
      var seasons = d.seasons.filter(function (x) { return x.events.length || x.current; }), cur = seasons.filter(function (x) { return x.current; })[0];
      var others = function (x) { return x.events.filter(function (g) { return !g.current; }); };
      if (cur) {
        var rest = others(cur);
        h += '<section class="card"><h2>' + esc(cur.name) + (cur.season_no && cur.name.indexOf(String(cur.season_no)) < 0 ? ' <span class="small muted">· сезон №' + cur.season_no + '</span>' : '') + '</h2>' +
          (rest.length ? '<div class="list">' + rest.map(gameRow).join('') + '</div>' : '<p class="small muted">Других Игр в этом сезоне пока нет.</p>') + '</section>';
      }
      var closed = seasons.filter(function (x) { return x !== cur; });
      if (closed.length || d.no_season.length) {
        h += '<section class="card"><h2>' + (cur ? 'Другие сезоны' : 'Сезоны') + '</h2>' + closed.map(function (x) {
          return '<details class="more"><summary>' + esc(x.name) + (x.season_no ? ' · №' + x.season_no : '') + ' · Игр: ' + x.events.length + '</summary><div class="list">' + x.events.map(gameRow).join('') + '</div></details>';
        }).join('') + (d.no_season.length ? '<details class="more"' + (cur || closed.length ? '' : ' open') + '><summary>Без сезона · Игр: ' + d.no_season.length + '</summary><div class="list">' +
          d.no_season.map(gameRow).join('') + '</div></details>' : '') + '</section>';
      }
      h += '<section class="card"><h2>Создать и настроить</h2>' +
        '<details class="more" id="d-new-game"><summary>＋ Новая Игра</summary><form class="stack" id="f-new-game" novalidate><div class="grid2">' +
        O.txt('ng-title', 'Название', '', ' maxlength="150" placeholder="Игра 02"') +
        O.sel('ng-season', 'Сезон', [['', 'Без сезона']].concat(d.seasons.map(function (x) { return [x.id, x.name]; })), d.seasons.length ? d.seasons[d.seasons.length - 1].id : '') +
        O.sel('ng-type', 'Вид', Object.keys(O.TYPE).map(function (k) { return [k, O.TYPE[k]]; }), 'ranked_game') + '</div>' + O.errBox +
        '<button class="btn" type="submit">Создать черновик</button><p class="small muted">Черновик видите только вы. Сроки, туры и задания настраиваются внутри Игры.</p></form></details>' +
        '<details class="more" id="d-seasons"><summary>Сезоны: добавить или изменить</summary><div class="stack">' +
        (d.seasons.length ? d.seasons.map(function (x) {
          return '<details class="more"><summary>' + esc(x.name) + (x.season_no ? ' · №' + x.season_no : '') + ' · Игр: ' + x.games + '</summary>' + seasonForm(x) + '</details>';
        }).join('') : '<p class="small muted">Сезонов пока нет.</p>') + '<details class="more"><summary>Добавить сезон</summary>' + seasonForm(null) + '</details></div></details></section>';
      h += '<p class="small muted">Все даты и время — московские (МСК, UTC+3).</p>';
      K.page(h, [['Обзор', '/org'], ['Игры и туры']]);
      // Если вернули несохранённый ввод (черновик формы) — раскрыть свёрнутый блок, чтобы его было видно.
      setTimeout(function () {
        Array.prototype.forEach.call(document.querySelectorAll('#main details'), function (x) {
          var f = Array.prototype.some.call(x.querySelectorAll('input, select'), function (i) { return i.type !== 'checkbox' && i.value !== i.defaultValue && i.tagName === 'INPUT'; });
          if (f) x.open = true;
        });
      }, 0);
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

  O.addText({ not_ranked: 'Только для рейтинговой Игры.' });
  K.actions.siteRating = function (b) {
    var on = b.getAttribute('data-v') === '1';
    O.confirm({ title: on ? 'Показывать на сайте текущий рейтинг?' : 'Вернуть рейтинг на начало Игры?',
      html: on ? '<p>Таблица FPL Rating на сайте станет меняться после каждого опубликованного тура этой Игры.</p>' +
        '<div class="note warn small">В Правилах (п. 7.3) сказано, что общий рейтинговый список в ходе Игры не публикуется. Если включаете — стоит предупредить участниц или поправить Правила.</div>'
        : '<p>Сайт снова покажет рейтинг на начало Игры, а новый — после её конца.</p>',
      ok: on ? 'Показывать текущий' : 'Вернуть', path: '/api/org/events/' + O.game.id + '/site-rating', body: function () { return { live: on }; },
      done: function () { K.toast('Сохранено — сайт обновится в течение 10 минут'); K.route(); } });
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
    if (e.type === 'ranked_game' && (e.status === 'registration' || e.status === 'active')) {
      // Рейтинг на сайте во время Игры (17.10): по умолчанию — на начало Игры (Правила, п. 7.3); организатор может разрешить текущий.
      h += '<section class="card"><h2>FPL Rating на сайте</h2><p class="small">' + (e.site_rating_live
        ? '<b>Сейчас: текущий.</b> Таблица на сайте обновляется после каждого опубликованного тура (сайт забирает данные раз в 10 минут). Только участницы, разрешившие публикацию; места считаются среди всех.'
        : '<b>Сейчас: на начало Игры.</b> Во время Игры общий рейтинг на сайте не меняется (Правила, п. 7.3), новый появится после её конца.' +
          (/Игра 01\b/.test(e.title) ? ' У Игры 01 рейтинга на начало ни у кого не было — до конца Игры таблица на сайте пустая.' : '')) + '</p>' +
        '<div class="row"><button class="btn sec" type="button" data-act="siteRating" data-v="' + (e.site_rating_live ? '0' : '1') + '">' +
        (e.site_rating_live ? 'Вернуть: рейтинг на начало Игры' : 'Показывать текущий рейтинг') + '</button></div></section>';
    }
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
    h += '<section class="card"><h2>Состояние</h2><p class="small muted">' + ({ draft: 'Черновик: участницы тур не видят. Заполните даты и задание, нажмите «Сохранить» (любая кнопка «Сохранить» сохраняет всю страницу) и опубликуйте.', plan: 'Опубликован: виден в плане Игры. Задание откроется ' + esc(O.when(r.opens_at)) + '.',
      open: 'Идёт сдача до ' + esc(O.when(r.deadline)) + '.', closed: 'Приём работ закрыт.' }[r.state] || '') + '</p>' + ownDatesNote(r) + O.issues(r.checks) + (acts.length ? '<div class="row">' + acts.join('') + '</div>' : '') +
      (r.status !== 'draft' ? '<div class="row"><button class="btn sec" type="button" data-href="/org/rounds/' + r.id + '/judging">Судейство тура</button>' +
        (r.status === 'published' ? '<button class="btn ghost" type="button" data-href="/gallery?event=' + r.event.id + '&round=' + r.id + '">Галерея тура — как видят участницы</button>' : '') + '</div>' : '') +
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
      }).join('') + O.errBox + (ro ? '' : '<button class="btn" type="submit">Сохранить</button>') + '</form>';
    h += relayCard(r, ro);
    K.page(h, crumbs);
    ['f-round', 'f-task', 'f-relay'].forEach(function (fid) {
      var form = document.getElementById(fid);
      if (form) form.addEventListener('submit', function (ev) { ev.preventDefault(); saveRoundPage(r, fid); });
    });
  }
  /* Страница тура — три блока (сроки, задание, эстафета), но одна кнопка «Сохранить» сохраняет все изменения на странице.
     Раньше каждая кнопка сохраняла только свой блок и перерисовывала страницу — несохранённое в других блоках пропадало. */
  var ROUND_FORMS = ['f-round', 'f-task', 'f-relay'];
  window.addEventListener('beforeunload', function (ev) {
    if (ROUND_FORMS.some(function (fid) { return formDirty(document.getElementById(fid)); })) { ev.preventDefault(); ev.returnValue = ''; }
  });
  function fieldsOf(form) {
    return Array.prototype.filter.call(form.querySelectorAll('input, select, textarea'), function (x) { return x.id; });
  }
  function isDirty(x) {
    if (x.type === 'checkbox') return x.checked !== x.defaultChecked;
    if (x.tagName === 'SELECT') {
      var d = Array.prototype.filter.call(x.options, function (o) { return o.defaultSelected; })[0] || x.options[0];
      return !!d && x.value !== d.value;
    }
    return x.value !== x.defaultValue;
  }
  function formDirty(form) { return !!form && fieldsOf(form).some(function (x) { return !x.disabled && isDirty(x); }); }
  function roundBody(r, f) {
    var title = f.querySelector('#r-title').value.trim();
    if (!title) return { err: 'Название не может быть пустым.' };
    var body = { title: title, deadline: K.fromInput(f.querySelector('#r-deadline').value), judging_deadline: K.fromInput(f.querySelector('#r-judging').value) };
    if (!r.locks.opens_at) body.opens_at = K.fromInput(f.querySelector('#r-open').value);
    if (body.deadline === null && r.deadline === null) delete body.deadline;
    if (body.judging_deadline === null && r.judging_deadline === null) delete body.judging_deadline;
    if (body.opens_at === null && r.opens_at === null) delete body.opens_at;
    return { method: 'PATCH', path: '/api/org/rounds/' + r.id, body: body };
  }
  function taskBody(r, ft) {
    var title = ft.querySelector('#t-title').value.trim();
    if (!title) return { err: 'Введите название задания.' };
    var photo = ft.querySelector('#t-photo').value, link = ft.querySelector('#t-link').value;
    if (photo === 'none' && link === 'none') return { err: 'Включите хотя бы фото или ссылку.' };
    var variants = [{ league: null, instructions: ft.querySelector('#t-all').value }];
    O.LEAGUES.forEach(function (l) {
      if (!ft.querySelector('#lg-' + l[0]).checked) return;
      variants.push({ league: l[0], title: ft.querySelector('#lt-' + l[0]).value.trim() || null, instructions: ft.querySelector('#li-' + l[0]).value,
        opens_at: K.fromInput(ft.querySelector('#lo-' + l[0]).value), deadline: K.fromInput(ft.querySelector('#ld-' + l[0]).value) });
    });
    return { method: 'PUT', path: '/api/org/rounds/' + r.id + '/task', body: { title: title, form: { photo: photo, link: link, photo_max: +ft.querySelector('#t-max').value }, variants: variants } };
  }
  function relayBody(r, fr) {
    var on = fr.querySelector('#rl-on').checked;
    return { method: 'PUT', path: '/api/org/rounds/' + r.id + '/relay', body: on ? { source: fr.querySelector('#rl-from').value, target: fr.querySelector('#rl-to').value,
      mode: fr.querySelector('#rl-mode').value, top_n: +fr.querySelector('#rl-top').value || 10 } : { source: null, target: null } };
  }
  var BUILD = { 'f-round': roundBody, 'f-task': taskBody, 'f-relay': relayBody };
  function setBusy(on) {
    ROUND_FORMS.forEach(function (fid) {
      var form = document.getElementById(fid);
      if (!form) return;
      Array.prototype.forEach.call(form.querySelectorAll('button, input, select, textarea'), function (b) {
        if (on) { b.setAttribute('data-was-disabled', b.disabled ? '1' : ''); b.disabled = true; }
        else { b.disabled = b.getAttribute('data-was-disabled') === '1'; b.removeAttribute('data-was-disabled'); }
      });
    });
  }
  function saveRoundPage(r, submitted) {
    // Сохраняем по порядку: сроки тура → задание (сроки лиг проверяются по срокам тура) → эстафета.
    var steps = ROUND_FORMS.filter(function (fid) { var form = document.getElementById(fid); return form && (fid === submitted || formDirty(form)); });
    var jobs = [];
    for (var i = 0; i < steps.length; i++) {
      var form = document.getElementById(steps[i]);
      K.formError(form, '');
      var job = BUILD[steps[i]](r, form);
      if (job.err) { K.formError(form, job.err); return; }
      job.fid = steps[i]; jobs.push(job);
    }
    setBusy(true);
    K.drafts.manual = true;   // черновики забываем сами — по каждому сохранённому блоку
    var last = null, notified = 0;
    (function next(k) {
      if (k >= jobs.length) {
        setBusy(false); K.drafts.manual = false;
        K.toast(notified ? 'Сохранено. Уведомление получили: ' + notified : 'Сохранено');
        drawRound(last);
        return;
      }
      K.api(jobs[k].method, jobs[k].path, jobs[k].body).then(function (res) {
        if (res.ok) { K.drafts.forget(document.getElementById(jobs[k].fid)); last = res.data; notified += res.data.notified || 0; next(k + 1); return; }
        setBusy(false); K.drafts.manual = false;
        var failed = jobs[k].fid, msg = O.err(res);
        if (last) drawRound(last);   // часть сохранилась — свежие данные; несохранённое вернётся само (K.drafts)
        var f2 = document.getElementById(failed);
        if (f2) K.formError(f2, msg); else K.toast(msg);
      });
    })(0);
  }
  // Тур-эстафета: вторая лига работает по работам первой (исходники раздаются после срока первой лиги).
  function relayCard(r, ro) {
    var rl = r.relay, locked = ro || (rl && (rl.started || rl.second_open || rl.early_judging === 'running' || rl.early_judging === 'done'));
    // число лучших можно менять до отправки исходников (15.10)
    var topOpen = !ro && rl && rl.mode === 'top' && !rl.released;
    var name = function (l) { return (O.LEAGUES.filter(function (x) { return x[0] === l; })[0] || [l, l])[1]; };
    var h = '<form class="card" id="f-relay" novalidate><h2>Эстафета между лигами</h2>' +
      '<p class="small muted">Первая лига делает работу, а после её срока каждой участнице второй лиги случайно выдаётся работа первой — как исходник ' +
      '(повторить или усложнить). Исходник получают и участницы вне конкурса. Работ меньше, чем участниц, — одна работа достаётся нескольким. ' +
      'Второй лиге поставьте в задании своё открытие — не раньше срока первой лиги. Судьи видят исходник рядом с работой.</p>' +
      O.chk('rl-on', 'Тур-эстафета', !!rl, locked ? ' disabled' : '') +
      '<div class="grid2">' + O.sel('rl-from', 'Делает первой (исходники)', O.LEAGUES, rl ? rl.from : 'gold', locked ? ' disabled' : '') +
      O.sel('rl-to', 'Получает исходники', O.LEAGUES, rl ? rl.to : 'silver', locked ? ' disabled' : '') + '</div>' +
      '<div class="grid2">' + O.sel('rl-mode', 'Какие работы раздавать', [['all', 'Все работы в конкурсе'], ['top', 'Лучшие по судейству первой лиги']], rl ? rl.mode : 'all', locked ? ' disabled' : '') +
      O.txt('rl-top', 'Сколько лучших', rl && rl.top_n ? rl.top_n : 10, ' type="number" min="1" max="100" inputmode="numeric"' + (locked && !topOpen ? ' disabled' : ''), 'Для «лучших»: первую лигу судят раньше, равные на границе входят все. Число можно менять до отправки исходников.') + '</div>';
    if (rl) {
      var st = rl.released ? 'Отправлены участницам ' + O.when(rl.released_at) : rl.ready ? (rl.started ? 'Черновик готов — проверьте и отправьте' : 'Можно готовить раздачу') :
        rl.mode === 'top' ? (rl.early_judging === 'running' ? 'Идёт судейство первой лиги — раздача после него' : 'После срока первой лиги начните её судейство (страница «Судейство тура»)') :
        'Раздача подготовится после срока первой лиги';
      h += '<dl class="kv"><dt>Срок первой лиги</dt><dd>' + esc(O.when(rl.source_deadline)) + '</dd><dt>Открытие для ' + esc(name(rl.to)) + '</dt><dd>' + esc(O.when(rl.second_opens_at)) + '</dd>' +
        '<dt>Исходники</dt><dd>' + esc(st) + '</dd>' +
        (rl.started ? '<dt>Работ-исходников</dt><dd>' + rl.sources + (rl.excluded ? ' · убрано ' + rl.excluded : '') + '</dd><dt>' + (rl.released ? 'Выдано' : 'В черновике') + '</dt><dd>' + rl.given +
          (rl.waiting ? ' · без исходника ' + rl.waiting + (rl.released ? ' (получат при открытии задания)' : '') : '') + '</dd>' : '') + '</dl>';
      if (rl.ready || rl.started) h += '<div class="row"><button class="btn' + (rl.released ? ' sec' : '') + '" type="button" data-href="/org/rounds/' + r.id + '/relay">' +
        (rl.released ? 'Посмотреть раздачу' : 'Проверить и отправить исходники') + '</button></div>';
      if (locked && topOpen) h += '<p class="small muted">Лиги и вид эстафеты уже не поменять. Число лучших работ — можно, пока исходники не отправлены' + (rl.started ? ': черновик раздачи пересоберётся.' : '.') + '</p>';
      else if (rl.started) h += '<p class="small muted">Раздача уже готовилась — настройку эстафеты не поменять.</p>';
    }
    return h + O.errBox + (locked && !topOpen ? '' : '<button class="btn" type="submit">Сохранить</button>') + '</form>';
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
