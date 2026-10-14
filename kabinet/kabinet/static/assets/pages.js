/* Кабинет FPL — экраны участника на настоящих данных (по согласованному прототипу 08–12.10.2026). */
(function () {
  'use strict';
  var K = window.K, esc = K.esc, pill = K.pill, li = K.li;
  var TYPE = { ranked_game: 'Рейтинговая Игра', challenge: 'Челлендж', final: 'Финал сезона', team: 'Командная Игра', special: 'Спецпроект' };

  /* ---------- состояние участия ---------- */
  function modePill(me, event) {
    if (!me) return '';
    if (event && (event.status === 'finished' || event.status === 'archived') && me.mode !== 'withdrawn') return pill('Игра завершена', 'ok');
    return {
      'in': pill('В конкурсе', 'ok'), outside: pill('Вне конкурса', 'warn'), out_pending: pill('Не прошли в отбор', 'warn'),
      withdrawn: pill('Вы вышли из Игры', 'plain'), pending: pill(me.payment_status === 'pending' ? 'Ожидает оплаты' : 'Заявка на проверке', 'info'),
      completed: pill('Завершена', 'ok'), eliminated: pill('Сдача закрыта', 'plain'), disqualified: pill('Участие прекращено', 'bad')
    }[me.mode] || '';
  }
  function outsideNote(g) {
    var late = g.me.elimination_reason === 'late';
    return 'Вне конкурса сроков туров нет: сдавайте задания, когда удобно, но все — до конца Игры. Тогда выдаётся диплом. ' +
      (late ? 'Зачёта Игры не будет: работа тура ' + (g.me.round_no_of_exit || '') + ' не сдана в срок. ' :
        'Если каждую работу сдать в срок её тура — Игра ещё и засчитается. ') + 'Работы вне конкурса не судят.';
  }
  function tsteps(rounds) {
    var lbl = { pub: 'итог опубликован', open: 'идёт сдача', judging: 'оценивание', plan: 'впереди', miss: 'работа не сдана', lsub: 'сдана после срока' };
    var done = rounds.filter(function (r) { return r.state === 'pub'; }).length;
    return '<ol class="tsteps" aria-label="Туры Игры: итогов опубликовано ' + done + ' из ' + rounds.length + '">' + rounds.map(function (r) {
      var st = r.work === 'missed' && r.state !== 'pub' ? 'miss' : r.work === 'sent_late' ? 'lsub' : r.state;
      var c = st === 'pub' ? 'done' : st === 'open' || st === 'judging' ? 'now' : st === 'miss' ? 'miss' : st === 'lsub' ? 'lsub' : '';
      return '<li class="' + c + '"' + (c === 'now' ? ' aria-current="step"' : '') + '><i aria-hidden="true"></i><span><span class="vh">Тур </span>' + r.round_no +
        '<span class="vh">: ' + (lbl[st] || lbl[r.state]) + '</span></span></li>';
    }).join('') + '</ol>';
  }
  /* Что сейчас главное в Игре: сдать, заменить, ждать итога, выбрать путь. */
  function nextAction(g) {
    var me = g.me, rs = g.rounds;
    if (!me) return { kind: 'none' };
    if (me.mode === 'out_pending') return { kind: 'choose' };
    var i;
    for (i = 0; i < rs.length; i++) if (rs[i].can_submit && ['none', 'draft', 'missed'].indexOf(rs[i].work) >= 0) return { kind: 'submit', round: rs[i] };
    for (i = rs.length - 1; i >= 0; i--) if (rs[i].can_submit && (rs[i].work === 'sent' || rs[i].work === 'sent_late')) return { kind: 'replace', round: rs[i] };
    if (!g.rules_ok) { for (i = 0; i < rs.length; i++) if (rs[i].closed_reason === 'rules') return { kind: 'rules', round: rs[i] }; }
    for (i = rs.length - 1; i >= 0; i--) if (rs[i].state === 'judging' && rs[i].work === 'sent') return { kind: 'wait', round: rs[i] };
    for (i = 0; i < rs.length; i++) if (rs[i].state === 'open' && rs[i].work === 'missed' && me.mode === 'in') return { kind: 'missed', round: rs[i] };
    for (i = 0; i < rs.length; i++) if (rs[i].state === 'plan') return { kind: 'upcoming', round: rs[i] };
    return { kind: 'none' };
  }
  function taskHref(g, r, extra) { return '/games/' + g.event.id + '/tasks/' + r.assignment_id + (extra || ''); }
  function submitLabel(g, r) { return 'Сдать работу ' + r.round_no + (g.me.mode === 'outside' ? ' — вне конкурса' : ''); }
  function gameTitle(e) { return e.title; }
  function isFinished(g) { return g.event.status === 'finished' || g.event.status === 'archived' || ['completed', 'withdrawn'].indexOf(g.me.mode) >= 0; }

  function actionBlock(g, act, compact) {
    var r = act.round, outside = g.me.mode === 'outside';
    if (act.kind === 'submit') {
      return '<span class="eyebrow">' + (outside ? 'Без сроков туров · все работы до конца Игры' : 'Сдать до') + '</span>' +
        K.deadline(r.submit_deadline, outside ? 'конец Игры' : null) + (outside && !compact ? '<p class="small muted">' + esc(outsideNote(g)) + '</p>' : '') +
        (r.work === 'draft' ? '<div class="row">' + pill('Фото сохранено. Работа ещё не сдана', 'warn') + '</div>' : '') +
        '<div class="row"><button class="btn" type="button" data-href="' + taskHref(g, r) + '">' + esc(submitLabel(g, r)) + '</button>' +
        (compact ? '' : '<button class="btn ghost" type="button" data-href="/games/' + g.event.id + '">Обзор Игры</button>') + '</div>';
    }
    if (act.kind === 'replace') {
      return '<h2>' + (outside ? 'Работа вне конкурса сдана' : 'Ваша работа сдана') + '. До срока можно заменить её</h2>' +
        (outside ? '<p class="muted">Работы вне конкурса не судят и не оценивают.</p>' : (r.judging_deadline ? '<p class="muted">Итог тура опубликуют</p>' + K.deadline(r.judging_deadline, false) : '')) +
        '<div class="row"><button class="btn sec" type="button" data-href="' + taskHref(g, r) + '">Посмотреть работу</button>' +
        '<button class="btn sec" type="button" data-href="' + taskHref(g, r, '?edit=1') + '">Заменить работу ' + r.round_no + (outside ? ' — вне конкурса' : '') + '</button></div>';
    }
    if (act.kind === 'wait') {
      return '<h2>Работа к туру ' + r.round_no + ' у жюри</h2>' + (r.judging_deadline ? '<p class="muted">Итог тура опубликуют</p>' + K.deadline(r.judging_deadline, false) : '') +
        '<div class="row"><button class="btn sec" type="button" data-href="' + taskHref(g, r) + '">Посмотреть работу</button></div>';
    }
    if (act.kind === 'choose') {
      return '<span class="eyebrow">' + (g.me.round_no_of_exit ? 'После тура ' + g.me.round_no_of_exit : 'После отбора') + '</span><h2>В отбор не прошли — диплом и зачёт за вами</h2>' +
        '<p class="muted">Можно продолжить Игру вне конкурса: те же задания, работы не судят и на призы они не претендуют. Диплом и зачёт Игры сохраняются, если оставшиеся работы сданы вовремя. Вернуться в конкурс в этой Игре нельзя.</p>' +
        '<div class="row"><button class="btn" type="button" data-act="chooseOutside" data-id="' + g.event.id + '">Участвовать вне конкурса</button></div>';
    }
    if (act.kind === 'rules') {
      return '<h2>Подтвердите документы</h2><p class="muted">Чтобы сдавать работы, примите Правила и согласия — это один экран.</p>' +
        '<div class="row"><button class="btn" type="button" data-act="docsGate">Посмотреть и принять</button></div>';
    }
    if (act.kind === 'missed') {
      return '<h2>Срок сдачи тура ' + r.round_no + ' прошёл</h2><p class="muted">Работа не сдана. Продолжить Игру можно вне конкурса — с открытия следующего тура.</p>';
    }
    if (act.kind === 'upcoming') {
      return '<h2>Ждём открытия тура ' + r.round_no + '</h2>' + (r.opens_at ? '<p class="muted">Задание откроется ' + esc(K.date(r.opens_at)) + ' МСК</p>' : '') +
        '<p class="small muted">Сейчас сдавать ничего не нужно.</p>';
    }
    return '';
  }

  K.actions.chooseOutside = function (b) {
    b.disabled = true;
    K.api('POST', '/api/games/' + b.getAttribute('data-id') + '/outside').then(function (r) {
      if (!r.ok) { b.disabled = false; K.toast(K.errorText(r)); return; }
      K.toast('Вы участвуете вне конкурса');
      K.route();
    });
  };

  /* ---------- Главная ---------- */
  K.on(/^\/$/, function () {
    K.load(['/api/home', '/api/games', '/api/events', '/api/achievements'], function (home, games, events, ach) {
      K.state.home = home; K.state.unread = home.unread;
      var me = K.state.me, name = me.display_name || me.full_name || me.email;
      var current = games.games.filter(function (g) { return !isFinished(g); });
      var g = current[0], act = g ? nextAction(g) : null, h = '';
      var title = g ? (act.kind === 'submit' ? 'Сдайте работу к ' + gameTitle(g.event).replace(/^Игра(?=\s)/, 'Игре') : act.kind === 'choose' ? 'Посмотрите дальнейший путь' :
        act.kind === 'replace' || act.kind === 'wait' ? 'Работа сдана' : g.event.title) : (games.games.length ? 'Ваши Игры' : 'Выберите первую Игру');
      h += '<div class="stack" data-s="g4"><span class="muted small">Здравствуйте, ' + esc(name) + '</span><h1>' + esc(title) + '</h1></div>';
      if (home.rules_update) {
        h += '<section class="card rules-upd"><span class="eyebrow">Правила обновились</span><h2>Редакция ' + esc(home.rules_update.version) + '</h2>' +
          '<p class="small">До принятия новой редакции сдать работу нельзя.</p><button class="btn" type="button" data-href="/documents/' + home.rules_update.id + '">Посмотреть и принять</button></section>';
      }
      if (g) {
        var r = act.round, head = r && act.kind !== 'choose' ? K.roundName(r.round_no, r.title) : esc(g.event.title);
        h += '<div class="card hero"><div class="hero-game"><span class="hg-name">' + head + '</span>' + modePill(g.me, g.event) + '</div>' +
          (g.rounds.length ? tsteps(g.rounds) : '') + (actionBlock(g, act) || '<div class="row"><button class="btn sec" type="button" data-href="/games/' + g.event.id + '">Обзор Игры</button></div>') + '</div>';
        var pubs = g.rounds.filter(function (x) { return x.result; });
        if (pubs.length) {
          var lp = pubs[pubs.length - 1];
          h += '<section class="card last-res"><h2>Итоги туров</h2><div class="lr-main"><span class="eyebrow">Последний · ' + K.roundName(lp.round_no, lp.title) + '</span>' +
            '<div class="between"><div class="score num">' + K.score(lp.result.score) + ' <small>из 100</small></div>' + (lp.result.top_work ? pill(K.topWork(lp.result.league), 'acc') : '') + '</div>' +
            '<button class="btn sec" type="button" data-href="/games/' + g.event.id + '/rounds/' + lp.round_no + '">Подробнее о туре ' + lp.round_no + '</button></div>' +
            (pubs.length > 1 ? '<div class="lr-prev"><span class="eyebrow">Предыдущие туры</span><div class="list">' + pubs.slice(0, -1).reverse().map(function (x) {
              return li(K.roundName(x.round_no, x.title), 'Оценка ' + K.score(x.result.score), x.result.top_work ? pill(K.topWork(x.result.league), 'acc') : '', '/games/' + g.event.id + '/rounds/' + x.round_no);
            }).join('') + '</div></div>' : '') + '</section>';
        }
      }
      if (home.important) {
        var n = home.important;
        h += '<section class="card"><div class="between"><h3>Важное уведомление</h3><span class="small muted">' + esc(K.date(n.created_at)) + ' МСК</span></div>' +
          '<p><b>' + esc(n.title) + '</b>' + (n.text ? '<br><span class="muted small">' + esc(n.text) + '</span>' : '') + '</p>' +
          '<div class="row"><button class="btn sec" type="button" data-act="openNotice" data-n="' + K.attr(n) + '">Открыть</button>' +
          '<button class="btn ghost" type="button" data-href="/notifications">Все уведомления</button></div></section>';
      }
      var mine = {};
      games.games.forEach(function (x) { mine[x.event.id] = true; });
      var others = events.events.filter(function (e) { return !mine[e.id] && e.status !== 'finished'; });
      var rating = ach.rating;
      h += '<div class="grid2"><section class="card"><span class="eyebrow">Рейтинг FPL</span>' + (rating.value == null ? '<p class="muted">Появится после первого опубликованного тура.</p>' :
        '<div class="score num">' + Math.round(rating.value) + ' <small>' + (rating.status === 'established' ? 'установлен' : 'калибровка ' + rating.calibration + ' из 3') + '</small></div>') +
        '<button class="btn ghost" type="button" data-href="/achievements">Мои достижения</button></section>';
      h += '<section class="card"><span class="eyebrow">' + (g ? 'Другие события' : 'Игры лиги') + '</span>' + (others.length ? others.slice(0, 4).map(function (e) {
        return li(esc(e.title), esc(regLine(e)), regPill(e), '/events/' + e.id);
      }).join('') : '<p class="muted small">Новых событий пока нет.</p>') + '<button class="btn ghost" type="button" data-href="/events">Все Игры лиги</button></section></div>';
      if (K.isAdmin()) {
        h += '<div class="note info small">Вы администратор лиги. <button class="lnk" type="button" data-href="/org">Открыть кабинет организатора</button></div>';
      }
      K.page(h);
    });
  });

  /* ---------- Уведомления (общие действия) ---------- */
  function noticeHref(n) {
    var p = n.params || {};
    if (n.route === 'task' && p.event_id && p.assignment_id) return '/games/' + p.event_id + '/tasks/' + p.assignment_id;
    if ((n.route === 'game' || n.route === 'results') && p.event_id) return '/games/' + p.event_id;
    if (n.route === 'publicity') return '/profile/publicity';
    if (n.route === 'reviews') return '/reviews';
    if (n.route === 'judge_review') return p.order_no ? '/judging/reviews/' + p.order_no : '/judging';
    if (n.route === 'support' && p.thread_no) return '/support/' + p.thread_no;
    if (n.route === 'document' && p.document_id) return '/documents/' + p.document_id;
    if (n.route === 'judging') return p.stream_id ? '/judging/' + p.stream_id : '/judging';
    return null;
  }
  K.actions.openNotice = function (b) {
    var n = JSON.parse(b.getAttribute('data-n'));
    K.api('POST', '/api/notifications/read', { ids: [n.id] }).then(function () {
      K.refreshUnread();
      var href = noticeHref(n);
      if (href) K.go(href); else K.route();
    });
  };

  /* ---------- Игры лиги ---------- */
  function regLine(e) {
    if (e.registration === 'open') return e.registration_closes_at ? 'Запись до ' + K.day(e.registration_closes_at) : 'Запись открыта';
    if (e.registration === 'soon') return e.registration_opens_at ? 'Запись с ' + K.day(e.registration_opens_at) : 'Запись скоро';
    return 'Запись закрыта';
  }
  function regPill(e) {
    if (e.my_mode) return pill('Вы участвуете', 'ok');
    return { open: pill('Запись открыта', 'ok'), soon: pill('Скоро', 'plain'), closed: pill(e.status === 'finished' ? 'Завершена' : 'Запись закрыта', 'plain') }[e.registration];
  }
  function price(e) { return e.payment_required && e.price != null ? Math.round(e.price).toLocaleString('ru-RU') + ' ₽' : 'Бесплатно'; }

  K.on(/^\/events$/, function () {
    K.load(['/api/events'], function (data) {
      var own = data.events.filter(function (e) { return e.my_mode; }), rest = data.events.filter(function (e) { return !e.my_mode; });
      function card(e) {
        return '<article class="card ev-card"><div class="between"><span class="eyebrow">' + esc(TYPE[e.type] || 'Событие') + '</span>' + regPill(e) + '</div>' +
          '<h2>' + esc(e.title) + '</h2><p class="small muted">' + esc([K.range(e.starts_at, e.ends_at), regLine(e).toLowerCase(), price(e)].filter(Boolean).join(' · ')) + '</p>' +
          '<div class="row">' + (e.my_mode ? '<button class="btn sec" type="button" data-href="/games/' + e.id + '">Моя Игра</button>' :
            '<button class="btn' + (e.registration === 'open' ? '' : ' sec') + '" type="button" data-href="/events/' + e.id + '">' + (e.registration === 'open' ? 'Записаться' : 'Подробнее') + '</button>') +
          '</div></article>';
      }
      K.page('<h1>Игры лиги</h1><p class="muted">Все события сезона. Запись — на каждую Игру отдельно.</p>' +
        (own.length ? '<section class="stack"><h2>Ваши Игры</h2>' + own.map(card).join('') + '</section>' : '') +
        '<section class="stack"><h2>' + (own.length ? 'Другие Игры и события' : 'Открытые и будущие события') + '</h2>' +
        (rest.length ? rest.map(card).join('') : '<div class="card empty"><p class="muted">Новых событий пока нет. Анонсы приходят в уведомления.</p></div>') + '</section>');
    });
  });

  var COUNTRIES = [['RU', 'Россия'], ['BY', 'Беларусь'], ['KZ', 'Казахстан'], ['AM', 'Армения'], ['GE', 'Грузия'], ['AZ', 'Азербайджан'], ['KG', 'Кыргызстан'],
    ['UZ', 'Узбекистан'], ['RS', 'Сербия'], ['ME', 'Черногория'], ['TR', 'Турция'], ['AE', 'ОАЭ'], ['IL', 'Израиль'], ['DE', 'Германия'], ['CY', 'Кипр'],
    ['TH', 'Таиланд'], ['UA', 'Украина'], ['MD', 'Молдова'], ['LV', 'Латвия'], ['LT', 'Литва'], ['EE', 'Эстония'], ['PL', 'Польша'], ['FI', 'Финляндия'],
    ['ES', 'Испания'], ['IT', 'Италия'], ['FR', 'Франция'], ['GB', 'Великобритания'], ['US', 'США'], ['CA', 'Канада'], ['ID', 'Индонезия'], ['VN', 'Вьетнам']];
  function countryName(code) { var c = COUNTRIES.filter(function (x) { return x[0] === code; })[0]; return c ? c[1] : code || ''; }
  function countrySelect(id, value) {
    return '<select class="input" id="' + id + '"><option value="">Выберите страну</option>' + COUNTRIES.map(function (c) {
      return '<option value="' + c[0] + '"' + (c[0] === value ? ' selected' : '') + '>' + c[1] + '</option>';
    }).join('') + '</select>';
  }

  function prizesCard(prizes) {
    if (!prizes || !prizes.length) return '';
    return '<section class="card prizes-p"><h2>Призы</h2><dl class="kv">' + prizes.map(function (p) {
      return '<dt>' + esc(p.criterion) + (p.league ? ' · ' + esc(K.LEAGUE[p.league]) : '') + '</dt><dd>' + esc(p.prize) + '</dd>';
    }).join('') + '</dl><p class="small muted">Места считаются отдельно в каждой лиге. Скидки в магазине для всех, кто прошёл Игру, приходят вместе с итогом Игры.</p></section>';
  }

  K.on(/^\/events\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/events/' + id], function (e) {
      var docs = e.documents || {}, me = K.state.me;
      var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(TYPE[e.type] || 'Событие') + '</span><h1>' + esc(e.title) + '</h1></div>' +
        '<section class="card"><dl class="kv"><dt>Даты</dt><dd>' + esc(K.range(e.starts_at, e.ends_at) || 'Будут объявлены') + '</dd>' +
        '<dt>Запись</dt><dd>' + esc(regLine(e)) + (e.registration === 'open' && e.registration_closes_at ? ', ' + esc(K.date(e.registration_closes_at).split(', ')[1]) + ' МСК' : '') + '</dd>' +
        '<dt>Стоимость</dt><dd>' + esc(price(e)) + '</dd>' +
        (e.rounds.length ? '<dt>Туры</dt><dd>' + e.rounds.length + ' ' + (e.rounds.length === 1 ? 'тур' : e.rounds.length < 5 ? 'тура' : 'туров') + '</dd>' : '') +
        '<dt>Рейтинг</dt><dd>' + (e.affects_rating ? 'Каждый тур влияет на рейтинг FPL' : 'Не влияет на рейтинг FPL') + '</dd></dl>' +
        (e.description ? '<p>' + esc(e.description) + '</p>' : '') + '</section>' + prizesCard(e.prizes);
      if (e.rounds.length) {
        h += '<details class="more card"><summary>Этапы и сроки</summary><div class="list">' + e.rounds.map(function (r) {
          return li(K.roundName(r.round_no, r.title), r.opens_at ? esc(K.day(r.opens_at)) + (r.deadline ? ' — ' + esc(K.msk(r.deadline)) : '') : '', '', null);
        }).join('') + '</div><p class="small muted">Все сроки — ' + K.TZ + '.</p></details>';
      }
      if (e.my_mode) {
        h += '<div class="note ok"><b>Вы записаны.</b> Задания и сроки — на странице вашей Игры.</div><div class="actbar"><button class="btn wide" type="button" data-href="/games/' + e.id + '">Перейти к моей Игре</button></div>';
      } else if (e.registration !== 'open') {
        h += '<div class="actbar"><button class="btn wide" type="button" disabled>' + (e.registration === 'soon' ? 'Запись ещё не открыта' : 'Запись закрыта') + '</button></div>';
      } else if (!docs.rules || !docs.publication) {
        h += '<div class="note info">Организатор ещё публикует Правила этой Игры. Запись откроется, как только они появятся.</div>';
      } else {
        h += '<section class="card" id="reg"><h2>Запись на ' + esc(K.acc(e.title)) + '</h2>' +
          (e.needs_place ? '<div class="field"><label for="reg-country">Страна</label>' + countrySelect('reg-country', me.country_code) + '</div>' +
            '<div class="field"><label for="reg-city">Город</label><input class="input" id="reg-city" maxlength="120" autocomplete="address-level2" value="' + esc(me.city || '') + '"></div>' : '') +
          '<label class="chk"><input type="checkbox" id="c-rules" data-reg> <span>Принимаю <a href="' + K.ROOT + '/documents/' + docs.rules.id + '" data-href="/documents/' + docs.rules.id + '">Правила Игры</a> (редакция ' + esc(docs.rules.version) + ')</span></label>' +
          '<label class="chk"><input type="checkbox" id="c-pub" data-reg> <span>Даю согласие на <a href="' + K.ROOT + '/documents/' + docs.publication.id + '" data-href="/documents/' + docs.publication.id + '">публикацию моих работ</a> на сайте и в соцсетях лиги</span></label>' +
          (docs.personal_data && !docs.personal_data.accepted ? '<label class="chk"><input type="checkbox" id="c-pd" data-reg> <span>Даю согласие на <a href="' + K.ROOT + '/documents/' + docs.personal_data.id + '" data-href="/documents/' + docs.personal_data.id + '">обработку персональных данных</a></span></label>' : '') +
          '<label class="chk"><input type="checkbox" id="c-adult" data-reg> <span>Мне есть 18 лет</span></label>' +
          (e.payment_required ? '<p class="small muted">Участие платное. Оплата подключается отдельно — после записи организатор пришлёт условия.</p>' : '') +
          '<p class="small muted" id="reg-hint">Чтобы записаться, ' + (e.needs_place ? 'укажите страну и город и ' : '') + 'отметьте все пункты.</p>' +
          '<p class="form-err" role="alert" tabindex="-1" hidden></p></section>' +
          '<div class="actbar"><button class="btn wide" type="button" id="reg-btn" data-act="register" data-id="' + e.id + '" disabled>Записаться на ' + esc(K.acc(e.title)) + '</button></div>';
      }
      K.page(h, [['Игры лиги', '/events'], [e.title]]);
      var form = document.getElementById('reg');
      if (form) {
        var check = function () {
          var ok = Array.prototype.every.call(form.querySelectorAll('[data-reg]'), function (c) { return c.checked; });
          var c = document.getElementById('reg-country'), t = document.getElementById('reg-city');
          if (c && (!c.value || !t.value.trim())) ok = false;
          document.getElementById('reg-btn').disabled = !ok;
        };
        form.addEventListener('change', check); form.addEventListener('input', check);
      }
    }, [['Игры лиги', '/events'], ['Игра']]);
  });
  K.actions.register = function (b) {
    var form = document.getElementById('reg'), id = b.getAttribute('data-id');
    var c = document.getElementById('reg-country'), t = document.getElementById('reg-city'), pd = document.getElementById('c-pd');
    var body = { accept_rules: document.getElementById('c-rules').checked, accept_publication: document.getElementById('c-pub').checked, accept_personal_data: !!(pd && pd.checked),
      confirm_adult: document.getElementById('c-adult').checked };
    if (c) { body.country_code = c.value; body.city = t.value.trim(); }
    b.disabled = true; b.textContent = 'Записываем…';
    K.api('POST', '/api/events/' + id + '/registration', body).then(function (r) {
      if (!r.ok) { b.disabled = false; b.textContent = 'Записаться'; K.formError(form, K.errorText(r)); return; }
      if (c) { K.state.me.country_code = body.country_code; K.state.me.city = body.city; }
      K.refreshUnread();
      showModal('<span class="eyebrow">Готово</span><h2 id="mT">Вы записаны</h2><p>' + (r.data.mode === 'pending' ? 'Заявка принята. Организатор пришлёт условия оплаты.' : 'Задания и сроки — на странице вашей Игры.') + '</p>' +
        '<div class="row"><button class="btn" type="button" data-act="closeModal" data-to="/games/' + id + '">К моей Игре</button><button class="btn ghost" type="button" data-act="closeModal" data-to="/events">Все Игры</button></div>');
    });
  };
  function showModal(inner) {
    var m = document.createElement('div');
    m.className = 'modal'; m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true'); m.setAttribute('aria-labelledby', 'mT');
    m.innerHTML = '<div class="card">' + inner + '</div>';
    document.getElementById('app').appendChild(m);
    var f = m.querySelector('button'); if (f) f.focus();
    K.onEscape = function () { m.remove(); K.onEscape = null; };
  }
  K.showModal = showModal;
  K.actions.closeModal = function (b) {
    var m = b.closest('.modal'); if (m) m.remove();
    K.onEscape = null;
    var to = b.getAttribute('data-to'); if (to) K.go(to);
  };

  /* Документы, без которых нельзя сдавать работы (14.10): Правила, обработка данных, публикация + «мне есть 18 лет».
     Нужны тем, у кого в кабинете нет согласий (участницы из бота с самостоятельно заведённым кабинетом) и после новой редакции Правил. */
  var DOC_LABEL = { rules: 'Принимаю Правила лиги', personal_data: 'Даю согласие на обработку персональных данных',
    publication: 'Даю согласие на публикацию моих работ на сайте и в соцсетях лиги' };
  K.actions.docsGate = function (b) {
    if (b) b.disabled = true;
    K.api('GET', '/api/consents/missing').then(function (r) {
      if (b) b.disabled = false;
      if (!r.ok) { K.toast(K.errorText(r)); return; }
      var miss = r.data.missing;
      if (!miss.length) { K.toast('Всё уже принято'); K.route(); return; }
      showModal('<h2 id="mT">Подтвердите документы</h2><p class="small muted">Без этого сдавать работы нельзя. Каждый документ можно открыть и прочитать.</p>' +
        '<form id="f-docs" class="stack" novalidate>' + miss.map(function (d) {
          return '<label class="chk"><input type="checkbox" name="doc" value="' + esc(d.doc_type) + '"> <span>' + esc(DOC_LABEL[d.doc_type] || d.title) +
            ' (редакция ' + esc(d.version) + ')</span></label><details class="doc-inline"><summary>Прочитать</summary><div class="small" data-s="pre">' + esc(d.body || '') + '</div></details>';
        }).join('') + '<label class="chk"><input type="checkbox" id="d-adult"> <span>Мне есть 18 лет</span></label>' +
        '<p class="form-err" role="alert" tabindex="-1" hidden></p><div class="row"><button class="btn" type="submit">Принять и продолжить</button>' +
        '<button class="btn ghost" type="button" data-act="closeModal">Позже</button></div></form>');
      var f = document.getElementById('f-docs');
      f.addEventListener('submit', function (e) {
        e.preventDefault(); K.formError(f, '');
        var acc = Array.prototype.filter.call(f.querySelectorAll('input[name=doc]'), function (x) { return x.checked; }).map(function (x) { return x.value; });
        if (acc.length < miss.length) { K.formError(f, 'Отметьте все документы — без них сдавать работы нельзя.'); return; }
        if (!document.getElementById('d-adult').checked) { K.formError(f, 'Участие — с 18 лет.'); return; }
        K.busy(f, true);
        K.api('POST', '/api/consents/missing', { accept: acc, confirm_adult: true }).then(function (res) {
          K.busy(f, false);
          if (!res.ok) { K.formError(f, K.errorText(res)); return; }
          var m = f.closest('.modal'); if (m) m.remove(); K.onEscape = null;
          K.toast('Готово — можно сдавать работы'); K.route();
        });
      });
    });
  };

  /* ---------- Мои Игры ---------- */
  function gameLine(g) {
    var act = nextAction(g), r = act.round, me = g.me;
    if (me.mode === 'withdrawn') return 'Вы вышли из Игры';
    if (isFinished(g)) return 'Игра завершена';
    if (me.mode === 'pending') return 'Заявка принята · ожидает подтверждения или оплаты';
    if (act.kind === 'submit') return 'Тур ' + r.round_no + ' · ' + (me.mode === 'outside' ? 'вне конкурса · все работы до ' + K.msk(r.submit_deadline) : 'сдать до ' + K.msk(r.submit_deadline));
    if (act.kind === 'replace') return 'Тур ' + r.round_no + ' · работа сдана · замена до ' + K.msk(r.submit_deadline);
    if (act.kind === 'wait') return 'Тур ' + r.round_no + ' · работа у жюри' + (r.judging_deadline ? ' · итог ' + K.msk(r.judging_deadline) : '');
    if (act.kind === 'choose') return 'В отбор не прошли · можно продолжить вне конкурса';
    if (act.kind === 'missed') return 'Тур ' + r.round_no + ' · срок прошёл, работа не сдана';
    if (act.kind === 'upcoming') return 'Тур ' + r.round_no + ' откроется ' + K.msk(r.opens_at);
    return '';
  }
  function myGameCard(g) {
    var act = nextAction(g), r = act.round, acts = '';
    if (act.kind === 'submit') acts = '<button class="btn" type="button" data-href="' + taskHref(g, r) + '">' + esc(submitLabel(g, r)) + '</button>';
    else if (act.kind === 'replace') acts = '<button class="btn sec" type="button" data-href="' + taskHref(g, r, '?edit=1') + '">Заменить работу ' + r.round_no + '</button>';
    else if (act.kind === 'choose') acts = '<button class="btn" type="button" data-act="chooseOutside" data-id="' + g.event.id + '">Участвовать вне конкурса</button>';
    return '<section class="card my-game"><div class="between"><div><h3>' + esc(g.event.title) + '</h3><span class="small muted">' +
      esc([g.me.league ? 'Лига ' + K.LEAGUE[g.me.league] : '', K.range(g.event.starts_at, g.event.ends_at)].filter(Boolean).join(' · ')) + '</span></div>' + modePill(g.me, g.event) + '</div>' +
      (g.rounds.length ? tsteps(g.rounds) : '') + '<p class="small">' + esc(gameLine(g)) + '</p><div class="row">' + acts +
      '<button class="btn ' + (acts ? 'ghost' : 'sec') + '" type="button" data-href="/games/' + g.event.id + '">Обзор Игры</button></div></section>';
  }
  K.on(/^\/games$/, function () {
    K.load(['/api/games'], function (data) {
      var cur = data.games.filter(function (g) { return !isFinished(g); }), done = data.games.filter(isFinished);
      if (!data.games.length) {
        K.page('<h1>Мои Игры</h1><div class="card"><p>У вас пока нет Игр.</p><p class="muted small">Выберите событие в «Играх лиги» и запишитесь.</p><button class="btn" type="button" data-href="/events">Игры лиги</button></div>');
        return;
      }
      K.page('<h1>Мои Игры</h1><section class="stack"><h2>Текущие</h2>' + (cur.length ? cur.map(myGameCard).join('') :
        '<div class="card empty"><p class="muted">Сейчас вы не участвуете в Играх.</p><button class="btn ghost" type="button" data-href="/events">Записаться на следующую Игру</button></div>') + '</section>' +
        '<section class="stack"><h2>Завершённые</h2>' + (done.length ? done.map(myGameCard).join('') :
          '<div class="card empty"><p class="muted">Здесь появятся завершённые Игры.</p><button class="btn ghost" type="button" data-href="/events">Записаться на следующую Игру</button></div>') + '</section>');
    });
  });

  /* ---------- Игра ---------- */
  function roundRow(g, r) {
    var outside = g.me.mode === 'outside', href = null, sub = '', right;
    var stateP = { pub: pill('Итог опубликован', 'ok'), open: pill('Идёт сдача', 'acc'), judging: pill('Судейство', 'info'), plan: pill('Запланирован', 'plain') }[r.state];
    if (r.state === 'plan') sub = r.opens_at ? 'Откроется ' + K.day(r.opens_at) : 'Дата будет объявлена';
    else if (r.result) sub = 'Оценка ' + K.score(r.result.score) + (r.result.top_work ? ' · ' + K.topWork(r.result.league) : '');
    else if (r.work === 'missed') sub = outside && r.can_submit ? 'Не сдана в срок · можно сдать до конца Игры' : 'Работа не сдана в срок';
    else if (r.work === 'sent_late') sub = 'Сдана после срока · идёт в диплом' + (r.can_submit ? ' · заменить до конца Игры' : '');
    else if (r.work === 'sent') sub = outside ? 'Сдана' + (r.can_submit ? ' · заменить до конца Игры' : '') : 'Работа сдана' + (r.can_submit ? ' · замена до ' + K.msk(r.deadline) : '');
    else if (r.work === 'draft') sub = 'Фото сохранено, работа ещё не сдана';
    else if (r.state === 'open') sub = outside ? 'Вне конкурса · до конца Игры' : 'Сдача до ' + K.msk(r.deadline);
    else sub = r.deadline ? 'Срок был ' + K.msk(r.deadline) : '';
    right = r.work === 'missed' && r.state !== 'pub' ? pill('Не сдана', 'bad') : stateP;
    if (r.state !== 'plan' && r.assignment_id) href = r.result ? '/games/' + g.event.id + '/rounds/' + r.round_no : taskHref(g, r);
    return li(K.roundName(r.round_no, r.title), esc(sub), right, href, r.state === 'open' || r.state === 'judging' ? 'now' : '');
  }
  function statusCard(g) {
    var me = g.me, f = g.flags;
    var comp = me.mode === 'outside' ? pill(me.elimination_reason === 'late' ? 'Вне конкурса · срок тура ' + (me.round_no_of_exit || '') + ' пропущен' : 'Вне конкурса · после отбора', 'warn') : modePill(me, g.event);
    var counted = { ok: pill('Все работы пока в срок', 'info'), lost: pill('Не будет · не все работы сданы в срок', 'plain'), no: pill('Не засчитана', 'plain') }[f.counted];
    var dip = { pending: pill(me.mode === 'outside' ? 'Будет, если все работы сданы до конца Игры' : 'После итогов', me.mode === 'outside' ? 'info' : 'plain'),
      all_sent: pill('Все работы сданы', 'ok'), no: pill('Не выдаётся', 'plain') }[f.diploma];
    var reg = { participating: 'Вы участвуете', completed: 'Завершено', payment_pending: 'Ожидает оплаты', pre_registered: 'Заявка принята', withdrawn: 'Вышли', cancelled: 'Отменена' }[me.registration_status];
    var pay = { not_required: 'Не требовалась', pending: 'Ожидается', paid: 'Оплачено', failed: 'Не прошла', refunded: 'Возвращена' }[me.payment_status];
    return '<section class="card"><h2>Статус участия</h2><dl class="kv"><dt>Соревнование</dt><dd>' + comp + '</dd><dt>Зачёт Игры</dt><dd>' + counted + '</dd><dt>Диплом</dt><dd>' + dip + '</dd></dl>' +
      '<details class="more"><summary>Запись и оплата</summary><dl class="kv"><dt>Запись</dt><dd>' + pill(reg || '—', 'ok') + (me.joined_at ? ' <span class="small muted">' + esc(K.dateY(me.joined_at)) + '</span>' : '') + '</dd>' +
      '<dt>Оплата</dt><dd>' + pill(pay || '—', 'plain') + '</dd></dl></details></section>';
  }
  /* Итоги Игры (этап 5): места показываются только здесь — в конце Игры. */
  function resultCard(g) {
    var r = g.result;
    if (!r) return '';
    var L = r.league ? K.LEAGUE[r.league] : '';
    var head = r.award_place ? ['🥇', '🥈', '🥉'][r.award_place - 1] + ' ' + r.award_place + ' место' + (L ? ' · лига ' + L : '') :
      r.top10 ? 'TOP-10' + (L ? ' · ' + L : '') : r.top25 ? 'TOP-25' + (L ? ' · ' + L : '') : 'Игра завершена';
    var cells = [];
    if (r.total != null) cells.push(['Итог Игры', String(r.total).replace('.', ',')]);
    if (r.league_rank) cells.push(['Место в лиге', r.league_rank + (L ? ' · ' + L : '')]);
    cells.push(['Очки FPL', '+' + (r.points || 0)]);
    if (r.top_works) cells.push([K.topWork(r.league), String(r.top_works)]);
    var h = '<section class="card next-step"><span class="eyebrow">Итоги Игры</span><h2>' + esc(head) + '</h2>' +
      '<div class="res-grid">' + cells.map(function (c) { return '<div><span class="small muted">' + esc(c[0]) + '</span><b class="num">' + esc(c[1]) + '</b></div>'; }).join('') + '</div>';
    h += '<dl class="kv"><dt>Зачёт Игры</dt><dd>' + (r.game_counted ? pill('Засчитана', 'ok') : pill('Не засчитана', 'plain')) + '</dd>' +
      '<dt>Диплом</dt><dd>' + (r.diploma ? '<b>' + esc(r.diploma) + '</b>' + (r.diploma_title ? ' <span class="small muted">' + esc(r.diploma_title) + '</span>' : '') : pill('Не выдаётся', 'plain')) + '</dd></dl>';
    if (r.diploma) h += '<div class="row"><a class="btn sec" href="/ru/diploma.html?n=' + encodeURIComponent(r.diploma) + '" target="_blank" rel="noopener">Проверить диплом на сайте</a></div>';
    return h + '</section>';
  }
  K.on(/^\/games\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/games/' + id, '/api/events/' + id], function (g, e) {
      var act = nextAction(g), next = actionBlock(g, act);
      var h = '<div class="stack"><span class="eyebrow">' + esc(TYPE[g.event.type] || 'Игра') + '</span><h1>' + esc(g.event.title) + '</h1>' +
        '<p class="muted">' + esc([K.range(g.event.starts_at, g.event.ends_at), g.me.league ? 'Лига Игры: ' + K.LEAGUE[g.me.league] : ''].filter(Boolean).join(' · ')) + '</p></div>';
      h += resultCard(g);
      if (next) h += '<section class="card next-step' + (act.kind === 'choose' || g.me.mode === 'outside' ? ' out-step' : '') + '">' + (act.kind === 'submit' ? '<span class="eyebrow">Следующий шаг</span><h2>' +
        (g.me.mode === 'outside' ? 'Сдавайте задания, когда удобно' : 'Сдать работу к туру ' + act.round.round_no) + '</h2>' : '') + next + '</section>';
      if (g.me.mode === 'withdrawn') h += '<section class="card next-step out-step"><h2>Вы вышли из Игры</h2><p>Задания и напоминания этой Игры больше не приходят. Рейтинг за пройденные туры сохранён. Передумали — напишите организатору, пока Игра не закончилась.</p>' +
        '<div class="row"><button class="btn sec" type="button" data-href="/support/new?event=' + id + '">Написать организатору</button></div></section>';
      h += '<section class="card"><h2>Туры</h2>' + (g.rounds.length ? '<div class="list">' + g.rounds.map(function (r) { return roundRow(g, r); }).join('') + '</div>' :
        '<p class="muted">Расписание туров появится до старта Игры.</p>') + '</section>';
      h += (g.result ? '' : statusCard(g)) + prizesCard(e.prizes);
      h += '<section class="card game-more"><h2>Ещё по Игре</h2><div class="list">' + li('Задать вопрос организатору', 'Обращение сохранит контекст этой Игры', '', '/support/new?event=' + id) + '</div></section>';
      K.page(h, [['Мои Игры', '/games'], [g.event.title]]);
    }, [['Мои Игры', '/games'], ['Игра']]);
  });

  /* ---------- Итог тура ---------- */
  K.on(/^\/games\/([0-9a-f-]{36})\/rounds\/(\d+)$/, function (id, no) {
    K.load(['/api/games/' + id], function (g) {
      var r = g.rounds.filter(function (x) { return String(x.round_no) === no; })[0];
      var crumbs = [['Мои Игры', '/games'], [g.event.title, '/games/' + id], ['Тур ' + no + ' · итог']];
      if (!r || !r.result) {
        K.page('<h1>Итог ещё не опубликован</h1><section class="card"><p>До публикации здесь нет оценки и решения о дальнейшем участии.</p><button class="btn sec" type="button" data-href="/games/' + id + '">К Игре</button></section>', crumbs);
        return;
      }
      var res = r.result, idx = g.rounds.indexOf(r), nextR = g.rounds[idx + 1];
      var adv = res.advanced == null ? '' : res.advanced ? pill(nextR ? 'Проходите в тур ' + nextR.round_no : 'Проходите дальше', 'ok') : pill('В отбор не прошли', 'warn');
      K.page('<div class="stack"><span class="eyebrow">' + K.roundName(r.round_no, r.title) + '</span><h1>Итог тура ' + r.round_no + '</h1></div>' +
        '<section class="card"><div class="between"><div><div class="score num">' + K.score(res.score) + ' <small>из 100</small></div><p class="small muted">Опубликовано ' + esc(K.date(res.published_at)) + ' МСК</p></div>' +
        (res.top_work ? pill(K.topWork(res.league), 'acc') : '') + '</div>' + (res.top_work ? '<p class="small">Ваша работа вошла в число лучших работ тура' + (res.league ? ' в лиге ' + esc(K.LEAGUE[res.league]) : '') + '.</p>' : '') +
        '<dl class="kv">' + (adv ? '<dt>Дальше</dt><dd>' + adv + '</dd>' : '') + (res.league ? '<dt>Лига</dt><dd>' + esc(K.LEAGUE[res.league]) + '</dd>' : '') +
        (res.rating ? '<dt>FPL Rating</dt><dd><b class="num">' + res.rating.after + '</b>' + (res.rating.delta != null ? ' <span class="num">(' + (res.rating.delta > 0 ? '+' : '') + res.rating.delta + ')</span>' : '') + '</dd>' +
          '<dt>Калибровка</dt><dd>' + (res.rating.calibration >= 3 ? 'завершена' : res.rating.calibration + ' из 3') + '</dd>' : '') + '</dl>' +
        '<p class="small muted">Места в туре не показываются — только в итогах Игры.' + (res.rating ? ' Рейтинг учитывает силу соперников и не равен оценке тура.' : '') + '</p></section>' +
        '<div class="row">' + (idx > 0 && g.rounds[idx - 1].result ? '<button class="btn ghost" type="button" data-href="/games/' + id + '/rounds/' + g.rounds[idx - 1].round_no + '">← Итог тура ' + g.rounds[idx - 1].round_no + '</button>' : '') +
        (nextR && nextR.result ? '<button class="btn ghost" type="button" data-href="/games/' + id + '/rounds/' + nextR.round_no + '">Итог тура ' + nextR.round_no + ' →</button>' : '') +
        '<button class="btn sec" type="button" data-href="/games/' + id + '">Все туры Игры</button>' +
        (r.assignment_id ? '<button class="btn ghost" type="button" data-href="' + taskHref(g, r) + '">Ваша работа</button>' : '') + '</div>', crumbs);
    });
  });

  /* ---------- Задание и сдача ---------- */
  var T = { data: null, pending: null, uploading: false, progress: 0, sheet: false, ids: null };

  function currentWork(t) { return t.draft || t.submitted || { photos: [], link: null }; }
  // Адреса фото приходят с сервера уже полными (с /kabinet).
  function photoImg(p, alt, cls) { return '<div class="photo ' + (cls || '') + '"><img alt="' + esc(alt) + '" src="' + esc(p.view_url) + '"></div>'; }

  // Тур-эстафета: работа участницы другой лиги, по которой выполняется задание (без имени автора).
  var LEAGUE_NAMES = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
  function sourceBlock(t) {
    if (!t.source_expected) return '';
    if (!t.source) return '';
    return '<section class="card"><h2>Ваш исходник</h2><p class="small muted">Работа участницы лиги ' + esc(LEAGUE_NAMES[t.source.league] || t.source.league) +
      '. Выдана случайно, имя автора не показывается.</p>' +
      t.source.photos.map(function (p, i) { return photoImg(p, 'Исходник' + (t.source.photos.length > 1 ? ', фото ' + (i + 1) : ''), 'big'); }).join('') + '</section>';
  }

  function closedCard(t, base) {
    var w = t.window, r = t.round, me = t.me;
    var msg = {
      not_open: ['Тур ' + r.round_no + ' ещё не открыт', r.opens_at ? 'Задание откроется ' + K.date(r.opens_at) + ' МСК.' : 'Дата открытия будет объявлена.'],
      deadline_passed: ['Срок сдачи прошёл', 'Приём завершился ' + K.date(w.deadline) + ' МСК. ' + (me && me.mode === 'in' ? 'После срока работа в конкурс не идёт. С открытия следующего тура вы продолжите Игру вне конкурса — тогда же можно будет сдать и эту работу: она нужна для диплома.' : '')],
      game_over: ['Приём работ закрыт', 'Игра завершена или закончился срок всех работ.'],
      choose_first: ['Сначала выберите, как продолжить', 'В отбор вы не прошли. Можно продолжить Игру вне конкурса: те же задания, работы не судят.'],
      rules: ['Сначала подтвердите документы', 'Чтобы сдать или заменить работу, примите действующие Правила и согласия — это один экран.'],
      withdrawn: ['Вы вышли из Игры', 'Сдача закрыта. Передумали — напишите организатору.'],
      eliminated: ['Сдача закрыта', 'Вопросы по участию — организатору.'],
      not_participating: ['Участие ещё не подтверждено', 'Задание станет доступно, когда участие будет оформлено.'],
      judging_started: ['Работа у жюри', 'Работы вашей лиги уже оценивают — сданная работа зафиксирована. Итог тура опубликуют для всех лиг одновременно.'],
      done_in_bot: ['Работа сдана в боте', 'Этот тур прошёл в боте, ваша работа уже оценена — итог тура в «Итогах туров».'],
      source_pending: ['Исходник готовится', 'В этом туре вы работаете по работе участницы другой лиги. Организатор проверяет работы и пришлёт исходник — придёт уведомление.'],
      no_source: ['Исходник ещё не выдан', 'В этом туре вы работаете по работе участницы другой лиги. Исходник выдаётся после её срока сдачи — если его всё ещё нет, напишите организатору.']
    }[w.reason] || ['Сдача закрыта', ''];
    var btn = w.reason === 'choose_first' ? '<button class="btn" type="button" data-act="chooseOutside" data-id="' + t.event.id + '">Участвовать вне конкурса</button>' :
      w.reason === 'rules' ? '<button class="btn" type="button" data-act="docsGate">Посмотреть и принять</button>' : '';
    return '<section class="card"><span class="eyebrow">' + esc(t.event.title) + ' · Тур ' + r.round_no + '</span><h2>' + esc(msg[0]) + '</h2><p>' + esc(msg[1]) + '</p>' +
      '<div class="row">' + btn + '<button class="btn sec" type="button" data-href="' + base + '">К моей Игре</button>' +
      '<button class="btn ghost" type="button" data-href="/support/new?event=' + t.event.id + '&round=' + r.round_no + '">Сообщить о проблеме</button></div></section>';
  }

  function sentView(t, base, editHref) {
    var s = t.submitted, w = t.window, r = t.round, outside = t.me.mode === 'outside', form = t.form || { link: 'optional', photo: 'required' };
    var status = s.is_on_time === false ? 'Сдана после срока тура' : 'Сдана';
    var h = '<div class="done-head"><span class="ok-ic" aria-hidden="true">✓</span><h1>Работа к туру ' + r.round_no + ' сдана</h1></div>' +
      sourceBlock(t) +
      '<section class="card"><span class="eyebrow">' + esc(t.event.title) + ' · Тур ' + r.round_no + (outside ? ' · вне конкурса' : '') + '</span>' +
      (s.photos.length ? s.photos.map(function (p, i) { return photoImg(p, 'Ваша работа' + (s.photos.length > 1 ? ', фото ' + (i + 1) : '')); }).join('') : '') +
      '<dl class="kv"><dt>Статус</dt><dd>' + status + '</dd>' +
      (form.link !== 'none' ? '<dt>Ссылка на публикацию</dt><dd>' + (s.link ? '<a href="' + esc(s.link) + '" target="_blank" rel="noopener noreferrer">' + esc(s.link) + '</a>' : 'Не добавлена') + '</dd>' : '') +
      '<dt>Сдана</dt><dd>' + esc(K.date(s.submitted_at)) + ' МСК' + (s.version_no > 1 ? ' · версия ' + s.version_no : '') + '</dd>' +
      (w.open ? '<dt>Изменить можно до</dt><dd>' + esc(K.date(w.deadline)) + ' МСК' + (outside ? ' (конец Игры)' : '') + '</dd>' : '<dt>Изменения</dt><dd>Срок сдачи завершился</dd>') +
      (!outside && r.judging_deadline && !t.result ? '<dt>Итог тура</dt><dd>' + esc(K.date(r.judging_deadline)) + ' МСК</dd>' : '') + '</dl>' +
      (w.open ? '<p>' + (outside ? 'Пока не закончилась Игра, фото и ссылку можно менять. В диплом пойдёт последняя сданная версия. Работы вне конкурса не оценивают.' :
        'Пока срок не закончился, фото и ссылку можно менять сколько угодно. Жюри оценит последнюю сданную версию.') + '</p>' +
        '<div class="row"><button class="btn sec" type="button" data-href="' + editHref + '">Заменить работу ' + r.round_no + '</button>' +
        (form.link !== 'none' ? '<button class="btn sec" type="button" data-href="' + editHref + '&focus=link">' + (s.link ? 'Заменить ссылку' : 'Сдать ссылку') + '</button>' : '') + '</div>'
        : '<p class="small muted">' + (t.result ? 'Итог тура опубликован.' : 'Последняя сданная версия зафиксирована' + (outside ? '.' : ' для оценивания. Результат появится после публикации.')) + '</p>') +
      '</section>';
    if (t.result) h += '<div class="row"><button class="btn" type="button" data-href="/games/' + t.event.id + '/rounds/' + r.round_no + '">Итог тура ' + r.round_no + '</button></div>';
    h += '<div class="row"><button class="btn ghost" type="button" data-href="/">На главную</button><button class="btn ghost" type="button" data-href="' + base + '">Обзор Игры</button>' +
      '<button class="btn ghost" type="button" data-href="/support/new?event=' + t.event.id + '&round=' + r.round_no + '&task=' + t.assignment.id + '">Сообщить об ошибке</button></div>';
    return h;
  }

  function formView(t, base) {
    var w = t.window, r = t.round, form = t.form, outside = t.me.mode === 'outside', work = currentWork(t);
    var replacing = !!t.submitted, photos = work.photos, needPhoto = form.photo !== 'none';
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">Тур ' + r.round_no + ' · ' + esc(t.event.title) + (outside ? ' · вне конкурса' : '') + '</span><h1>' + esc(t.assignment.title) + '</h1></div>' +
      '<section class="focus"><span class="lbl">' + (outside ? 'Все работы до' : 'Сдать до') + '</span>' + K.deadline(w.deadline, outside ? 'конец Игры' : null) + '</section>';
    if (outside) {
      h += '<p class="small muted">' + esc(outsideNote({ me: t.me })) + '</p>';
      if (t.me.elimination_reason !== 'late' && t.competition_deadline) h += '<p class="small">Срок тура для зачёта Игры — ' + esc(K.date(t.competition_deadline)) + ' МСК.</p>';
    }
    h += '<section class="stack"><h2>Задание</h2><p class="lead" data-s="pre">' + esc(t.instructions || 'Описание задания появится здесь.') + '</p>' +
      (t.me.mode === 'in' ? '<p class="small muted">После срока работа в конкурс не идёт — продолжить можно вне конкурса.</p>' : '') + '</section>' +
      sourceBlock(t);
    if (replacing && t.draft) h += '<div class="note warn small">Вы меняете сданную работу. Пока изменения не сохранены, действует предыдущая сданная версия.</div>';
    if (needPhoto) {
      var max = form.photo_max || 1;
      h += '<section class="card"><h2>' + (max > 1 ? 'Ваши фото' : 'Ваше фото') + '</h2>' + (photos.length ? photos.map(function (p, i) {
        return photoImg(p, 'Фото работы' + (photos.length > 1 ? ' ' + (i + 1) : ''), 'big') +
          (T.uploading ? '' : '<div class="row">' + (max === 1 ? '<label class="btn sec" for="file">Заменить фото</label>' : '') +
          '<button class="btn ghost" type="button" data-act="removePhoto" data-i="' + i + '">Убрать</button></div>');
      }).join('') + (t.draft ? '<p class="small muted">Сохранено ' + esc(K.date(t.draft.saved_at)) + ' МСК. ' + (replacing ? 'Замена ещё не сохранена.' : 'Ещё не сдано — до сдачи его можно заменить.') + '</p>' : '') : '') +
        (T.uploading ? '<div class="note info" role="status"><b>' + uploadText() + '</b><br><span class="small">Не закрывайте страницу, пока фото не загрузится.</span></div>' :
          photos.length < max ? '<label class="drop" for="file"><b>Добавить фото</b><span class="small muted">С камеры или из галереи. JPG, PNG или WebP, до 20 МБ.' +
          (form.photo === 'optional' ? ' Необязательно.' : '') + '</span></label>' : '') +
        '<input class="sr" id="file" type="file" accept="image/jpeg,image/png,image/webp"' + (T.uploading ? ' disabled' : '') + '></section>';
    }
    if (form.link !== 'none') {
      h += '<section class="card"><h2>Ссылка на публикацию</h2><label for="work-link">Ссылка на публикацию · ' + (form.link === 'required' ? 'обязательно' : 'необязательно') + '</label>' +
        '<input class="input" id="work-link" type="url" inputmode="url" maxlength="500" placeholder="https://…" value="' + esc(work.link || '') + '">' +
        '<p class="small muted">Фото и ссылку можно заменить до ' + esc(K.date(w.deadline)) + ' МСК.</p><p class="err" id="link-err" hidden></p></section>';
    }
    if (replacing && t.draft) h += '<button class="btn ghost" type="button" data-act="discardDraft">Отменить изменения</button>';
    h += '<button class="btn ghost" type="button" data-href="/support/new?event=' + t.event.id + '&round=' + r.round_no + '">Вопрос по заданию</button>';
    var noPhotoYet = needPhoto && form.photo === 'required' && !photos.length;
    var label = replacing ? 'Заменить работу ' + r.round_no : 'Сдать работу ' + r.round_no + (outside ? ' — вне конкурса' : '');
    h += '<div class="actbar">' + (T.uploading ? '<button class="btn wide" type="button" disabled>' + uploadText() + '</button>' :
      noPhotoYet ? '<label class="btn wide" for="file">Добавить фото</label>' :
      '<button class="btn wide" type="button" data-act="askSubmit"' + (replacing && !t.draft ? ' disabled' : '') + '>' + esc(replacing && !t.draft ? 'Изменений нет' : label) + '</button>') + '</div>';
    if (T.sheet) h += submitSheet(t, label);
    return h;
  }

  function submitSheet(t, label) {
    var work = currentWork(t), outside = t.me.mode === 'outside', repl = !!t.submitted, form = t.form;
    return '<div class="sheet confirm-sheet"><div class="panel" role="dialog" aria-modal="true" aria-labelledby="askTitle"><span class="grip"></span>' +
      '<h2 id="askTitle">' + (repl ? 'Заменить работу ' + t.round.round_no + '?' : 'Сдать работу к туру ' + t.round.round_no + '?') + '</h2>' +
      '<div class="ask-row">' + (work.photos[0] ? '<div class="photo ask-ph"><img alt="Ваше фото" src="' + esc(work.photos[0].thumb_url) + '"></div>' : '') +
      '<dl class="kv"><dt>Участие</dt><dd>' + (outside ? 'Вне конкурса — без оценки' : 'В конкурсе — оценит жюри') + '</dd>' +
      (form.link !== 'none' ? '<dt>Ссылка</dt><dd>' + (work.link ? esc(work.link) : 'Не добавлена') + '</dd>' : '') + '</dl></div>' +
      '<p class="small">После сдачи фото и ссылку можно поменять до ' + (outside ? 'конца Игры, ' : '') + esc(K.date(t.window.deadline)) + ' МСК. ' +
      (outside ? 'В диплом пойдёт последняя сданная версия.' : 'Жюри оценит последнюю сданную версию.') + '</p>' +
      '<button class="btn wide" type="button" data-act="submitWork">' + esc(label) + '</button><button class="btn sec wide" type="button" data-act="closeAsk">Отмена</button></div></div>';
  }

  function drawTask() {
    var t = T.data, q = K.query(), base = '/games/' + t.event.id;
    var self = base + '/tasks/' + t.assignment.id, crumbs = [['Мои Игры', '/games'], [t.event.title, base], ['Тур ' + t.round.round_no]];
    var h;
    if (!t.task_ready && t.window.reason !== 'not_open') {
      h = '<section class="card"><span class="eyebrow">' + esc(t.event.title) + ' · Тур ' + t.round.round_no + '</span><h2>Задание ещё готовится</h2>' +
        '<p>Организатор ещё не выдал ваш вариант задания. Загляните позже или напишите организатору.</p><div class="row"><button class="btn sec" type="button" data-href="' + base + '">К моей Игре</button>' +
        '<button class="btn ghost" type="button" data-href="/support/new?event=' + t.event.id + '&round=' + t.round.round_no + '">Написать организатору</button></div></section>';
    } else if (t.window.open && (t.draft || !t.submitted || q.get('edit'))) {
      h = formView(t, base);
    } else if (t.submitted) {
      h = sentView(t, base, self + '?edit=1');
    } else {
      h = closedCard(t, base);
    }
    K.page(h, crumbs);
    var f = document.getElementById('file');
    if (f) f.addEventListener('change', onFile);
    var l = document.getElementById('work-link');
    if (l) {
      l.addEventListener('change', onLink);
      if (q.get('focus') === 'link') l.focus();
    }
    if (T.sheet) {
      var b = document.querySelector('.confirm-sheet [data-act="submitWork"]'); if (b) b.focus();
      K.onEscape = function () { T.sheet = false; drawTask(); };
    }
  }

  function loadTask(id, aid) {
    var stamp = K.route.stamp;
    T.sheet = false; T.uploading = false; T.progress = 0; T.upSeq = (T.upSeq || 0) + 1;
    K.loading();
    K.api('GET', '/api/games/' + id + '/tasks/' + aid).then(function (r) {
      if (stamp !== K.route.stamp) return;
      if (r.status === 401) { K.route(); return; }
      if (!r.ok) { K.failed(r, [['Мои Игры', '/games'], ['Задание']]); return; }
      T.data = r.data; T.ids = [id, aid];
      drawTask();
    });
  }
  K.on(/^\/games\/([0-9a-f-]{36})\/tasks\/([0-9a-f-]{36})$/, loadTask);

  function taskUrl() { return '/api/games/' + T.ids[0] + '/tasks/' + T.ids[1]; }
  /* Страница задания всё ещё на экране? (за время загрузки человек мог уйти в другой раздел) */
  function stillHere(stamp) { return stamp === K.route.stamp; }
  function saveDraft(photos, link) {
    var stamp = K.route.stamp;
    var p = K.api('PUT', taskUrl() + '/draft', { photos: photos, link: link || null }).then(function (r) {
      if (!stillHere(stamp)) return r;   // человек уже на другой странице: её данные не трогаем
      if (r.ok) { T.data = r.data; drawTask(); } else K.toast(K.errorText(r));
      return r;
    });
    T.pending = p;
    return p;
  }
  function photoIds() { return currentWork(T.data).photos.map(function (p) { return p.id; }); }
  function linkValue() { var l = document.getElementById('work-link'); return l ? l.value.trim() : currentWork(T.data).link; }
  function linkOk(v) { return !v || /^https?:\/\/\S{3,}$/i.test(v); }

  function uploadText() { return 'Загружаем фото…' + (T.progress > 0 && T.progress < 100 ? ' ' + T.progress + '%' : ''); }
  // Фото с телефона — уменьшить до 3000 px по длинной стороне (JPEG 0,9): на мобильном интернете в разы быстрее.
  // Поворот по EXIF браузер применяет сам; метаданные (в т.ч. геопозиция) не уходят. Любая ошибка — отправляем как есть.
  var MAX_SIDE = 3000;
  // Размер в пикселях из заголовка (JPEG — маркер SOF, PNG — IHDR), не декодируя фото.
  function headDims(file) {
    return file.slice(0, 256 * 1024).arrayBuffer().then(function (buf) {
      var d = new DataView(buf), n = d.byteLength;
      if (n > 24 && d.getUint32(0) === 0x89504E47) return { w: d.getUint32(16), h: d.getUint32(20) };
      if (n < 4 || d.getUint16(0) !== 0xFFD8) return null;
      var i = 2;
      while (i + 9 < n) {
        if (d.getUint8(i) !== 0xFF) { i++; continue; }
        var m = d.getUint8(i + 1);
        if (m >= 0xC0 && m <= 0xCF && m !== 0xC4 && m !== 0xC8 && m !== 0xCC) return { h: d.getUint16(i + 5), w: d.getUint16(i + 7) };
        if (m === 0xD8 || m === 0x01 || (m >= 0xD0 && m <= 0xD7)) { i += 2; continue; }
        i += 2 + d.getUint16(i + 2);
      }
      return null;
    }).catch(function () { return null; });
  }
  function withTimeout(p, ms, fallback) {
    return Promise.race([p, new Promise(function (ok) { setTimeout(function () { ok(fallback); }, ms); })]);
  }
  function shrink(file) {
    if (file.size < 1.5 * 1024 * 1024 || !window.HTMLCanvasElement || !file.slice || !window.Promise) return Promise.resolve(file);
    // Огромные снимки (50–200 Мп) не декодируем на телефоне — вкладка может упасть; сервер уменьшит сам.
    return headDims(file).then(function (dim) {
      if (dim && dim.w * dim.h > 30000000) return file;
      return withTimeout(shrinkNow(file), 20000, file);   // зависло (мало памяти) — отправляем как есть
    });
  }
  function shrinkNow(file) {
    // Через <img>: поворот по EXIF браузеры применяют сами (Safari с iOS 13.4, Chrome с 81) — и при рисовании на canvas.
    var load = new Promise(function (ok, bad) {
      var img = new Image(), url = URL.createObjectURL(file);
      img.onload = function () { URL.revokeObjectURL(url); ok(img); };
      img.onerror = function () { URL.revokeObjectURL(url); bad(new Error('decode')); };
      img.src = url;
    });
    return load.then(function (img) {
      var w = img.naturalWidth || img.width, h = img.naturalHeight || img.height, k = Math.min(1, MAX_SIDE / Math.max(w, h));
      var c = document.createElement('canvas');
      c.width = Math.round(w * k); c.height = Math.round(h * k);
      var ctx = c.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);   // прозрачный PNG — на белом
      ctx.drawImage(img, 0, 0, c.width, c.height);
      return new Promise(function (ok) {
        c.toBlob(function (b) { c.width = c.height = 0; ok(b && b.size > 0 && b.size < file.size ? b : file); }, 'image/jpeg', 0.9);
      });
    }).catch(function () { return file; });
  }
  // Загрузка с процентами (fetch их не даёт); ответ — в том же виде, что у K.api.
  function sendPhoto(blob, onProgress) {
    return new Promise(function (done) {
      var x = new XMLHttpRequest();
      x.open('POST', K.ROOT + '/api/uploads');
      x.withCredentials = true;
      x.timeout = 300000;
      x.setRequestHeader('Content-Type', blob.type || 'image/jpeg');
      x.upload.onprogress = function (e) { if (e.lengthComputable) onProgress(Math.floor(e.loaded * 100 / e.total)); };
      x.onload = function () {
        var data = null;
        try { data = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { data = null; }
        if (x.status === 401) K.state.me = null;
        done({ status: x.status, ok: x.status >= 200 && x.status < 300, data: data, detail: data && typeof data.detail === 'string' ? data.detail : null });
      };
      x.onerror = x.ontimeout = x.onabort = function () { done({ status: 0, ok: false, data: null, detail: null }); };
      x.send(blob);
    });
  }
  function onFile(e) {
    var file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file || T.uploading) return;
    var type = (file.type || '').toLowerCase(), name = (file.name || '').toLowerCase();
    if (/heic|heif/.test(type) || /\.(heic|heif)$/.test(name)) {
      K.toast('Это фото в формате HEIC — его кабинет не принимает. Сохраните фото как JPG (например, перешлите себе в Telegram и сохраните оттуда) или сделайте скриншот.');
      return;
    }
    if (['image/jpeg', 'image/png', 'image/webp'].indexOf(type) < 0) { K.toast('Выберите фото JPG, PNG или WebP.'); return; }
    if (file.size === 0) { K.toast('Файл пустой — фото ещё не скачалось на телефон. Откройте его в галерее и попробуйте снова.'); return; }
    if (file.size > 40 * 1024 * 1024) { K.toast('Файл больше 40 МБ. Выберите другой.'); return; }
    var link = linkValue();
    var stamp = K.route.stamp;
    var my = T.upSeq = (T.upSeq || 0) + 1;   // загрузка «этой» страницы; старая, завершившись позже, ничего не трогает
    T.uploading = true; T.progress = 0; T.sheet = false; drawTask();
    shrink(file).then(function (blob) {
      if (blob.size > 20 * 1024 * 1024) return { status: 413, ok: false, data: null, detail: null };
      var last = 0;
      return sendPhoto(blob, function (pct) {
        if (my !== T.upSeq) return;
        T.progress = pct;
        if (pct - last >= 5 && stillHere(stamp)) { last = pct; var b = document.querySelector('.actbar .btn'); if (b) b.textContent = uploadText(); }
      });
    }).then(function (r) {
      if (my === T.upSeq) { T.uploading = false; T.progress = 0; }
      if (!stillHere(stamp)) { if (r.ok) K.toast('Фото загружено. Откройте задание снова и добавьте его в работу.'); return; }
      if (!r.ok) { drawTask(); K.toast(K.errorText(r)); return; }
      var ids = photoIds(), max = (T.data.form && T.data.form.photo_max) || 1;
      if (max > 1 && ids.indexOf(r.data.id) >= 0) { drawTask(); K.toast(K.errorText({ status: 422, detail: 'duplicate_photo' })); return; }
      ids = max === 1 ? [r.data.id] : ids.concat([r.data.id]).slice(0, max);
      saveDraft(ids, linkOk(link) ? link : currentWork(T.data).link).then(function (s) { if (s.ok) K.toast('Фото загружено'); });
    });
  }
  function onLink(e) {
    var v = e.target.value.trim(), err = document.getElementById('link-err');
    if (!linkOk(v)) { err.textContent = 'Проверьте ссылку: нужен адрес, начинающийся с https://'; err.hidden = false; return; }
    err.hidden = true;
    if (v === (currentWork(T.data).link || '')) return;
    saveDraft(photoIds(), v);
  }
  K.actions.removePhoto = function (b) {
    if (T.uploading) return;
    var ids = photoIds(); ids.splice(+b.getAttribute('data-i'), 1);
    saveDraft(ids, linkValue());
  };
  K.actions.discardDraft = function () {
    K.api('DELETE', taskUrl() + '/draft').then(function (r) {
      if (!r.ok) { K.toast(K.errorText(r)); return; }
      T.data = r.data;
      K.go('/games/' + T.ids[0] + '/tasks/' + T.ids[1], true);
    });
  };
  K.actions.askSubmit = function () {
    if (T.uploading) { K.toast('Дождитесь, пока загрузится фото.'); return; }
    var v = linkValue(), form = T.data.form;
    if (!linkOk(v)) { K.toast('Проверьте ссылку: нужен адрес, начинающийся с https://'); return; }
    if (form.link === 'required' && !v) { K.toast('Добавьте ссылку на свою публикацию.'); return; }
    var ready = (T.pending || Promise.resolve({ ok: true })).then(function () {
      var w = currentWork(T.data);
      if (v !== (w.link || '') || !T.data.draft) return saveDraft(photoIds(), v);
      return { ok: true };
    });
    ready.then(function (r) {
      if (!r.ok) return;
      if (form.photo === 'required' && !currentWork(T.data).photos.length) { K.toast('Добавьте фото работы.'); return; }
      T.sheet = true; drawTask();
    });
  };
  K.actions.closeAsk = function () { T.sheet = false; drawTask(); };
  K.actions.submitWork = function (b) {
    b.disabled = true; b.textContent = 'Отправляем…';
    var replaced = !!T.data.submitted;
    K.api('POST', taskUrl() + '/submit', { draft_id: T.data.draft && T.data.draft.id }).then(function (r) {
      T.sheet = false;
      if (!r.ok) {
        // обрыв связи: работа могла уже сдаться — показать, что на сервере сейчас
        if (r.status === 0) { K.toast('Связь прервалась — проверяем, сдана ли работа…'); loadTask(T.ids[0], T.ids[1]); return; }
        if (r.detail === 'draft_changed') { K.toast('Эта версия уже сдана или изменена в другом окне — показываем, что сейчас сдано.'); loadTask(T.ids[0], T.ids[1]); return; }
        K.toast(K.errorText(r)); if (r.status === 409) { loadTask(T.ids[0], T.ids[1]); } else drawTask(); return;
      }
      T.data = r.data;
      K.refreshUnread();
      K.toast(replaced ? 'Замена сохранена' : 'Работа сдана. До срока её можно заменить.');
      K.go('/games/' + T.ids[0] + '/tasks/' + T.ids[1], true);
    });
  };
})();
