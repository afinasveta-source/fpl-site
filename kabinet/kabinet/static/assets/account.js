/* Кабинет FPL — достижения, уведомления, поддержка, профиль, публичность, согласия, документы. */
(function () {
  'use strict';
  var K = window.K, esc = K.esc, pill = K.pill, li = K.li;

  /* ---------- Мои достижения ---------- */
  /* ---------- Мои разборы: аудиоразбор работ от судьи (заказ — на сайте лиги) ---------- */
  var RV = { 'new': ['Заказ принят — пришлём ссылку на оплату', 'info'], payment_sent: ['Ждём оплату', 'info'], paid: ['Оплачен — судья записывает разбор', 'warn'],
    done: ['Готов', 'ok'] };
  K.on(/^\/reviews$/, function () {
    K.load(['/api/reviews'], function (d) {
      var h = '<h1>Мои разборы</h1><p class="muted">Аудиоразбор вашей работы от судьи лиги — что получилось и что улучшить. ' +
        'Заказать — на сайте лиги: <a href="/ru/review.html">«Разбор от судьи»</a>.</p>';
      h += d.items.length ? d.items.map(function (o) {
        var title = (o.scope === 'all' ? 'Все работы Игры' : 'Работа тура ' + o.round_no) + (o.game ? ' · ' + esc(o.game) : '');
        return '<section class="card"><div class="between"><h2>' + title + '</h2>' + pill(RV[o.status][0], RV[o.status][1]) + '</div>' +
          '<p class="small muted">Разбирает: ' + esc(o.reviewer) + ' · заказ № ' + o.no + ' от ' + esc(K.date(o.created_at)) + ' МСК</p>' +
          (o.audio ? '<audio controls preload="metadata" class="wide" src="' + K.ROOT + '/api/reviews/' + o.no + '/audio"></audio>' +
            '<p class="small"><a href="' + K.ROOT + '/api/reviews/' + o.no + '/audio" download>Скачать аудио</a></p>' : '') +
          (o.text ? '<div class="stack"><h3>Текст разбора</h3><p data-s="pre">' + esc(o.text) + '</p></div>' : '') + '</section>';
      }).join('') : '<div class="note">Разборов пока нет. Заказать разбор работы можно на сайте лиги — <a href="/ru/review.html">«Разбор от судьи»</a>. ' +
        'Укажите в заказе тот же email, что в кабинете, — разбор появится здесь.</div>';
      K.page(h, [['Мои разборы']]);
    }, [['Мои разборы']]);
  });

  K.on(/^\/achievements$/, function () {
    K.load(['/api/achievements'], function (a) {
      var none = a.rating.value == null && !a.results.length;
      var h = '<h1>Мои достижения</h1>' + (none ? '<div class="note">Результатов пока нет. Это не ноль — просто ещё нечего показать. Первые цифры появятся после опубликованного тура.</div>' : '') +
        '<div class="stats"><div class="stat"><span>Рейтинг FPL</span><b class="num">' + (a.rating.value == null ? '—' : Math.round(a.rating.value)) + '</b><span>' +
        (a.rating.value == null ? 'нет данных' : a.rating.status === 'established' ? 'установлен' : 'калибровка ' + a.rating.calibration + ' из 3') + '</span></div>' +
        '<div class="stat"><span>Лига сезона</span><b>' + (a.league && a.league.league ? esc(K.LEAGUE[a.league.league]) : '—') + '</b><span>' + esc(a.league ? a.league.season : '') + '</span></div>' +
        '<div class="stat"><span>Очки FPL</span><b class="num">' + a.points.total + '</b><span>за всё время</span></div>' +
        '<div class="stat"><span>Зачтено Игр</span><b class="num">' + a.counted_games + '</b><span>для финала сезона</span></div></div>';
      if (a.rating.history.length) {
        h += '<section class="card"><h2>Рейтинг: история изменений</h2><div class="list">' + a.rating.history.slice().reverse().map(function (x) {
          var d = x.before == null ? '' : Math.round(x.after - x.before);
          return li(esc((x.game || '') + (x.round_no ? ' · Тур ' + x.round_no : '')), (x.before == null ? '' : Math.round(x.before) + ' → ') + Math.round(x.after),
            d === '' ? '' : '<b class="num">' + (d > 0 ? '+' : '') + d + '</b>', null);
        }).join('') + '</div><p class="small muted">Рейтинг считается с учётом силы соперников. Он не равен оценке тура.</p></section>';
      }
      h += '<section class="card"><h2>История результатов</h2>' + (a.results.length ? '<div class="list">' + a.results.map(function (r) {
        return li(esc(r.game) + ' · ' + K.roundName(r.round_no, r.round_title), 'Оценка ' + K.score(r.score) + (r.league ? ' · ' + K.LEAGUE[r.league] : ''),
          r.top_work ? pill(K.topWork(r.league), 'acc') : '', '/games/' + r.event_id + '/rounds/' + r.round_no);
      }).join('') + '</div>' : '<p class="muted">История пуста.</p>') + '</section>';
      h += '<section class="card"><h2>Очки FPL</h2>' + (a.points.items.length ? '<div class="list">' + a.points.items.map(function (p) {
        return li(esc(p.reason), esc(K.dateY(p.at)), '<b class="num">' + (p.delta > 0 ? '+' : '') + p.delta + '</b>', null);
      }).join('') + '</div>' : '<p class="muted">Начислений ещё не было.</p>') + '<p class="small muted">Очки — не рейтинг: они копятся за достижения и не сгорают.</p></section>';
      var medals = (a.games || []).filter(function (g) { return g.award_place; });
      if (medals.length) h += '<section class="card"><h2>Медали</h2><div class="list">' + medals.map(function (g) {
        return li(esc(['🥇', '🥈', '🥉'][g.award_place - 1] + ' ' + g.award_place + ' место · ' + (g.league ? K.LEAGUE[g.league] : '')), esc(g.game), '', '/games/' + g.event_id);
      }).join('') + '</div></section>';
      h += '<section class="card"><h2>Дипломы и награды</h2>' + (a.diplomas.length ? '<div class="list">' + a.diplomas.map(function (d) {
        return li(esc((d.title || 'Диплом участника') + ' · ' + d.game), esc('№ ' + d.number + ' · ' + K.dateY(d.issued_at) + (d.league ? ' · лига ' + (K.LEAGUE[d.league] || d.league) : '')), pill('Выдан', 'ok'), null);
      }).join('') + '</div><p class="small muted">Подлинность диплома проверяется по номеру на главной странице сайта лиги.</p>' :
        '<p class="muted">Дипломы появятся после итогов Игры.</p>') + '</section>';
      K.page(h);
    });
  });

  /* ---------- Уведомления и поддержка ---------- */
  function tabs(active) {
    return '<nav class="row" aria-label="Сообщения кабинета" data-s="mb18"><button class="btn ' + (active === 'n' ? '' : 'sec') + '" type="button" data-href="/notifications"' +
      (active === 'n' ? ' aria-current="page"' : '') + '>Уведомления</button><button class="btn ' + (active === 's' ? '' : 'sec') + '" type="button" data-href="/support"' +
      (active === 's' ? ' aria-current="page"' : '') + '>Поддержка</button></nav>';
  }
  K.on(/^\/notifications$/, function () {
    K.load(['/api/notifications'], function (d) {
      var list = d.notifications, unread = list.filter(function (n) { return !n.read; }).length;
      K.page(tabs('n') + '<div class="between"><h1>Уведомления</h1>' + (unread ? '<button class="btn ghost" type="button" data-act="readAll">Отметить все прочитанными</button>' : '') + '</div>' +
        (list.length ? '<div class="list">' + list.map(function (n) {
          return '<button class="li" type="button" data-act="openNotice" data-n="' + K.attr(n) + '"><span class="t">' + (n.read ? '' : '<span class="pill acc" data-s="mr8">новое</span>') +
            esc(n.title) + '</span><span class="s">' + esc((n.text ? n.text + ' · ' : '') + K.date(n.created_at)) + '</span><span class="r"></span></button>';
        }).join('') + '</div>' : '<div class="note">Уведомлений пока нет. Здесь появятся сроки, открытие туров и итоги.</div>') +
        '<p class="small muted">Ваши обращения и ответы организатора — во вкладке «Поддержка».</p>');
    });
  });
  K.actions.readAll = function () {
    K.api('POST', '/api/notifications/read', { all: true }).then(function () { K.state.unread = 0; K.route(); });
  };

  var TSTATUS = { waiting_admin: pill('Ждём организатора', 'info'), waiting_user: pill('Нужен ваш ответ', 'acc'), closed: pill('Закрыто', 'plain') };
  K.on(/^\/support$/, function () {
    K.load(['/api/support'], function (d) {
      K.page(tabs('s') + '<div class="between"><h1>Поддержка</h1><button class="btn" type="button" data-href="/support/new">Новое обращение</button></div>' +
        (d.threads.length ? '<div class="list">' + d.threads.map(function (t) {
          return li('№' + t.no + ' · ' + esc(t.subject), esc(t.context + ' · ' + K.date(t.updated_at)), TSTATUS[t.status] || '', '/support/' + t.no);
        }).join('') + '</div>' : '<div class="note">Обращений пока нет. Если что-то не получается — напишите, организатор ответит здесь.</div>'));
    });
  });

  K.on(/^\/support\/new$/, function () {
    var q = K.query(), ev = q.get('event'), round = q.get('round'), task = q.get('task'), topic = q.get('topic');
    var draw = function (games) {
      var g = ev && games ? games.games.filter(function (x) { return x.event.id === ev; })[0] : null;
      var ctx = g ? g.event.title + (round ? ' · Тур ' + round : '') + (task ? ' · работа' : '') : (topic || '');
      K.page('<h1>Новое обращение</h1><form class="card" id="f-ticket" novalidate>' +
        (ctx ? '<div class="note small">Привязано к: <b>' + esc(ctx) + '</b> — номер Игры и работы переписывать не нужно.</div>' : '') +
        '<div class="field"><label for="tt">Тема</label><input class="input" id="tt" maxlength="120" value="' + esc(topic || '') + '"></div>' +
        '<div class="field"><label for="tx">Сообщение</label><textarea class="input" id="tx" maxlength="4000"></textarea></div>' +
        '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Отправить</button></form>' +
        '<button class="btn ghost" type="button" data-href="/support">К списку обращений</button>', [['Поддержка', '/support'], ['Новое обращение']]);
      var f = document.getElementById('f-ticket');
      f.addEventListener('submit', function (e) {
        e.preventDefault(); K.formError(f, '');
        var tx = f.tx.value.trim(), tt = f.tt.value.trim() || tx.slice(0, 60);
        if (!tx) { K.formError(f, 'Опишите вопрос — без текста обращение не отправить.'); return; }
        var body = { subject: tt, body: tx };
        if (g) { body.event_id = ev; if (round) body.round_no = +round; if (task) body.assignment_id = task; }
        K.busy(f, true);
        K.api('POST', '/api/support', body).then(function (r) {
          K.busy(f, false);
          if (!r.ok) { K.formError(f, K.errorText(r)); return; }
          K.toast('Обращение №' + r.data.no + ' создано');
          K.go('/support/' + r.data.no, true);
        });
      });
      f.tt.focus();
    };
    if (ev) K.load(['/api/games'], draw, [['Поддержка', '/support'], ['Новое обращение']]); else draw(null);
  });

  K.on(/^\/support\/(\d+)$/, function (no) {
    K.load(['/api/support/' + no], function (t) {
      var who = { closed: 'Обращение закрыто. Можно открыть новое.', waiting_admin: 'Обращение отправлено. Ждём ответа организатора.', waiting_user: 'Организатор ждёт вашего ответа.' }[t.status];
      K.page('<div class="stack"><span class="eyebrow">№' + t.no + ' · ' + esc(t.context) + '</span><h1>' + esc(t.subject) + '</h1></div><div class="note small">' + esc(who || '') + '</div>' +
        '<section class="card"><div class="stack">' + t.messages.map(function (m) {
          return '<div class="msg' + (m.mine ? ' me' : '') + '"><span class="who">' + esc(m.author + ' · ' + K.date(m.at)) + '</span>' + esc(m.body).replace(/\n/g, '<br>') + '</div>';
        }).join('') + '</div>' + (t.status !== 'closed' ? '<form id="f-reply" novalidate><div class="field"><label for="rep">Ответ</label><textarea class="input" id="rep" data-s="h80" maxlength="4000"></textarea></div>' +
          '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn" type="submit">Отправить ответ</button></form>' : '') + '</section>' +
        '<div class="row"><button class="btn sec" type="button" data-href="/support">К списку обращений</button>' + (t.status === 'closed' ? '<button class="btn ghost" type="button" data-href="/support/new">Новое обращение</button>' : '') + '</div>',
        [['Поддержка', '/support'], ['Обращение №' + t.no]]);
      var f = document.getElementById('f-reply');
      if (f) f.addEventListener('submit', function (e) {
        e.preventDefault(); K.formError(f, '');
        var v = f.rep.value.trim();
        if (!v) { K.formError(f, 'Напишите текст ответа.'); return; }
        K.busy(f, true);
        K.api('POST', '/api/support/' + no + '/messages', { body: v }).then(function (r) {
          K.busy(f, false);
          if (!r.ok) { K.formError(f, K.errorText(r)); return; }
          K.toast('Ответ отправлен'); K.route();
        });
      });
    }, [['Поддержка', '/support'], ['Обращение']]);
  });

  /* ---------- Профиль ---------- */
  var COUNTRY = {};
  function countryName(code) {
    if (!code) return '';
    try { return new Intl.DisplayNames(['ru'], { type: 'region' }).of(code); } catch (e) { return COUNTRY[code] || code; }
  }
  var P = [['Профиль', '/profile']];
  function backLink() { return '<button class="btn ghost" type="button" data-href="/profile">К профилю и настройкам</button>'; }

  K.on(/^\/profile$/, function () {
    K.load(['/web-auth/me', '/api/preferences'], function (me, prefs) {
      K.state.me = me;
      var place = [countryName(me.country_code), me.city].filter(Boolean).join(', ');
      K.page('<h1>Профиль и настройки</h1><section class="card"><div class="between"><div><h2>' + esc(me.full_name || me.display_name || me.email) + '</h2>' +
        '<p class="muted small">Публичное имя: ' + esc(me.display_name || 'не указано — используется имя профиля') + '</p></div>' + pill('Аккаунт активен', 'ok') + '</div>' +
        '<dl class="kv"><dt>Email</dt><dd>' + esc(me.email || '—') + '</dd><dt>Страна, город</dt><dd>' + (place ? esc(place) : '<span class="muted">Не указаны</span> · <button class="lnk" type="button" data-href="/profile/place">Указать</button>') + '</dd>' +
        '<dt>Telegram</dt><dd>' + (prefs.telegram_linked ? 'привязан' : '<span class="muted">не привязан</span>') + '</dd></dl></section>' +
        '<div class="list">' + li('Имя и публичное имя', 'Как вас видят в рейтинге и галерее', '', '/profile/name') + li('Страна и город', esc(place || 'Не указаны'), '', '/profile/place') +
        li('Публичность профиля и работ', 'Что из вашего профиля и работ видно на сайте и в соцсетях', '', '/profile/publicity') +
        li('Вход и пароль', 'Email и пароль', '', '/profile/security') + li('Уведомления', 'Telegram, ВКонтакте, email', '', '/profile/notifications') +
        li('Согласия и документы', 'Что и когда вы приняли', '', '/profile/consents') + '</div><button class="btn sec" type="button" data-act="logout">Выйти</button>');
    });
  });

  function saveProfile(f, body, done) {
    K.busy(f, true);
    K.api('PATCH', '/web-auth/profile', body).then(function (r) {
      K.busy(f, false);
      if (!r.ok) { K.formError(f, r.status === 422 ? 'Проверьте поля: публичное имя — от 2 до 40 символов, страна — две буквы.' : K.errorText(r)); return; }
      K.state.me = r.data; K.toast('Сохранено'); done();
    });
  }

  K.on(/^\/profile\/name$/, function () {
    var me = K.state.me;
    K.page('<h1>Имя и публичное имя</h1><form class="card" id="f-name" novalidate><div class="field"><label for="pn">Публичное имя</label>' +
      '<input class="input" id="pn" maxlength="40" value="' + esc(me.display_name || '') + '"><span class="hint">Так вас видят в рейтинге и галерее. Можно оставить пустым — тогда показываем имя из профиля. От 2 до 40 символов.</span></div>' +
      (me.full_name ? '<div class="field"><span class="lbl-static">ФИО по документам</span><div class="static-val">' + esc(me.full_name) + '</div>' +
        '<span class="hint">Указано в согласиях и на дипломе. Изменить ФИО можно через организатора. <button class="lnk" type="button" data-href="/support/new?topic=' + encodeURIComponent('Исправить ФИО в профиле') + '">Написать</button></span></div>'
        : '<div class="field"><label for="fn">ФИО по документам</label><input class="input" id="fn" maxlength="200" autocomplete="name"><span class="hint">Пишется на дипломе, если не указано публичное имя. После сохранения меняется через организатора.</span></div>') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><div class="row"><button class="btn" type="submit">Сохранить</button><button class="btn sec" type="button" data-href="/profile">Отменить</button></div></form>' +
      '<p class="small muted">Контакты (email, Telegram) другим участникам не показываются — кроме партнёров по совместному заданию.</p>' + backLink(), P.concat([['Имя']]));
    var f = document.getElementById('f-name');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      var v = f.pn.value.trim();
      if (v && (Array.from(v).length < 2 || Array.from(v).length > 40)) { K.formError(f, 'Публичное имя — от 2 до 40 символов.'); return; }
      var body = { display_name: v };
      if (f.fn && f.fn.value.trim()) body.full_name = f.fn.value.trim();
      saveProfile(f, body, function () { K.go('/profile'); });
    });
  });

  var COUNTRIES = ['RU', 'BY', 'KZ', 'AM', 'GE', 'AZ', 'KG', 'UZ', 'TJ', 'MD', 'UA', 'RS', 'ME', 'TR', 'AE', 'IL', 'CY', 'DE', 'PL', 'LV', 'LT', 'EE', 'FI', 'ES', 'IT', 'FR', 'GB', 'US', 'CA', 'TH', 'VN', 'ID'];
  K.on(/^\/profile\/place$/, function () {
    var me = K.state.me;
    var opts = COUNTRIES.map(function (c) { return [c, countryName(c)]; }).sort(function (a, b) { return a[0] === 'RU' ? -1 : b[0] === 'RU' ? 1 : a[1].localeCompare(b[1], 'ru'); });
    K.page('<h1>Страна и город</h1><form class="card" id="f-place" novalidate><div class="field"><label for="pc">Страна</label><select class="input" id="pc"><option value="">Выберите страну</option>' +
      opts.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === me.country_code ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') +
      (me.country_code && COUNTRIES.indexOf(me.country_code) < 0 ? '<option value="' + esc(me.country_code) + '" selected>' + esc(countryName(me.country_code)) + '</option>' : '') + '</select></div>' +
      '<div class="field"><label for="ci">Город</label><input class="input" id="ci" maxlength="120" autocomplete="address-level2" value="' + esc(me.city || '') + '"></div>' +
      '<p class="small muted">Нужны для записи на Игры и для групп по городу. На сайте город показывается, только если вы включите страницу мастера.</p>' +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><div class="row"><button class="btn" type="submit">Сохранить</button><button class="btn sec" type="button" data-href="/profile">Отменить</button></div></form>' + backLink(),
      P.concat([['Страна и город']]));
    var f = document.getElementById('f-place');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      if (!f.pc.value || !f.ci.value.trim()) { K.formError(f, 'Укажите страну и город.'); return; }
      saveProfile(f, { country_code: f.pc.value, city: f.ci.value.trim() }, function () { K.go('/profile'); });
    });
  });

  K.on(/^\/profile\/security$/, function () {
    var me = K.state.me, mail = K.state.config && K.state.config.mail_delivery;
    K.page('<h1>Вход и пароль</h1><section class="card"><dl class="kv"><dt>Email для входа</dt><dd>' + esc(me.email || '—') + '</dd></dl>' +
      (mail ? '<p>Сменить пароль можно по ссылке, которую пришлём на ваш email.</p><button class="btn sec" type="button" data-act="resetLink">Прислать ссылку для нового пароля</button>' :
        '<p>Чтобы сменить пароль или email, напишите организатору — он пришлёт ссылку.</p><button class="btn sec" type="button" data-href="/support/new?topic=' + encodeURIComponent('Сменить пароль или email') + '">Написать организатору</button>') +
      '</section>' + backLink(), P.concat([['Вход и пароль']]));
  });
  K.actions.resetLink = function (b) {
    b.disabled = true;
    K.api('POST', '/auth/password/reset-request', { email: K.state.me.email }).then(function (r) {
      if (!r.ok) { b.disabled = false; K.toast(K.errorText(r)); return; }
      K.toast('Если почта работает, письмо придёт в течение нескольких минут.');
    });
  };

  function sw(id, title, sub, on, extra) {
    return '<div class="switch"><div><b>' + title + '</b><div class="small muted">' + sub + '</div></div><input class="tg" type="checkbox" data-nodraft id="' + id + '" aria-label="' + esc(title) + '"' +
      (on ? ' checked' : '') + (extra || '') + '></div>';
  }
  /* Уведомления (16.10): Telegram и ВКонтакте подключаются одноразовой ссылкой на бота лиги (15 минут, один раз).
     Бот только присылает уведомления — войти в кабинет или сменить пароль через него нельзя. */
  var MSG = { telegram: ['Telegram', 'бот лиги в Telegram'], vk: ['ВКонтакте', 'сообщения сообщества лиги'] };
  var msgPoll = null;
  function msgCard(k, m, prefs) {
    var name = MSG[k][0], h = '<div class="msgr" id="msgr-' + k + '"><div class="between"><div><b>' + name + '</b><div class="small muted">' +
      (m.linked ? 'Подключён' + (m.name ? ' · ' + esc(m.name) : '') + (m.linked_at ? ' · ' + esc(K.dateY(m.linked_at)) : '') : 'Задания, сроки, итоги туров — ' + MSG[k][1]) + '</div></div>' +
      (m.linked ? (m.blocked ? pill('Бот заблокирован', 'warn') : pill('Подключён', 'ok')) : m.available ? '' : pill('Скоро', 'plain')) + '</div>';
    if (m.linked && m.blocked) h += '<p class="small">Сообщения не доходят: бот заблокирован или сообщения от сообщества запрещены. Отключите и подключите заново.</p>';
    if (m.linked && k === 'telegram') h += sw('p-tg', 'Присылать в Telegram', 'Можно временно выключить, не отвязывая', prefs.telegram);
    if (m.linked) h += '<button class="btn ghost small" type="button" data-act="msgrUnlink" data-k="' + k + '">Отключить ' + name + '</button>';
    else if (m.available) h += '<button class="btn small" type="button" data-act="msgrLink" data-k="' + k + '">Подключить ' + name + '</button><div class="msgr-wait small" hidden></div>';
    return h + '</div>';
  }
  function drawNotifications(m, p) {
    K.page('<h1>Уведомления</h1><section class="card stack"><h3>Мессенджеры</h3>' + msgCard('telegram', m.telegram, p) + msgCard('vk', m.vk, p) +
      '<p class="small muted">Бот только присылает уведомления — войти в кабинет, сменить пароль или сдать работу через него нельзя. Отключить можно здесь или словом «стоп» в чате.</p>' +
      '<p class="small muted" id="tg-warn"' + (m.telegram.linked || m.vk.linked ? ' hidden' : '') + '>Без мессенджера вы можете пропустить срок сдачи. Сроки всегда видны здесь, в кабинете.</p></section>' +
      '<section class="card"><h3>Другие каналы</h3>' + sw('p-email', 'Email', 'Дублирование важных сроков', p.email) +
      '<div class="switch"><div><b>Кабинет</b><div class="small muted">Колокольчик и раздел «Уведомления»</div></div><span class="pill plain always">Всегда</span></div>' +
      '<p class="small muted">Уведомления в кабинете приходят всегда — чтобы вы ничего не пропустили.</p></section>' +
      '<section class="card"><h3>Новости лиги</h3>' + sw('p-mkt', 'Анонсы Игр и челленджей', 'Анонсы новых событий', p.marketing) +
      '<p class="small muted">Отказ от новостей не отключает сообщения по вашему участию.</p></section>' + backLink(), P.concat([['Уведомления']]));
  }
  function stopPoll() { if (msgPoll) { clearInterval(msgPoll); msgPoll = null; } }
  K.on(/^\/profile\/notifications$/, function () {
    stopPoll();
    K.load(['/api/messengers', '/api/preferences'], function (m, p) {
      drawNotifications(m, p);
      document.getElementById('main').addEventListener('change', function (e) {
        var key = { 'p-tg': 'telegram', 'p-email': 'email', 'p-mkt': 'marketing' }[e.target.id];
        if (!key) return;
        var body = {}; body[key] = e.target.checked;
        e.target.disabled = true;
        K.api('PUT', '/api/preferences', body).then(function (r) {
          e.target.disabled = false;
          if (!r.ok) { e.target.checked = !e.target.checked; K.toast(K.errorText(r)); return; }
          K.toast('Сохранено');
        });
      });
    }, P.concat([['Уведомления']]));
  });
  K.actions.msgrLink = function (b) {
    var k = b.getAttribute('data-k'), wait = b.parentNode.querySelector('.msgr-wait');
    var win = null;
    try { win = window.open('', '_blank'); } catch (e) { win = null; }   // окно — сразу по нажатию, иначе браузер заблокирует
    b.disabled = true;
    K.api('POST', '/api/messengers/' + k + '/link', {}).then(function (r) {
      b.disabled = false;
      if (!r.ok) { if (win) win.close(); K.toast(r.detail === 'channel_off' ? MSG[k][0] + ' пока не подключён к кабинету.' : K.errorText(r)); return; }
      var d = r.data;
      if (win) { try { win.opener = null; win.location.href = d.url; } catch (e) { win = null; } }
      wait.hidden = false;
      wait.innerHTML = (k === 'telegram' ? 'Откроется бот — нажмите в нём «Старт» (Start).' : 'Откроется чат сообщества — нажмите «Начать» или отправьте код <b class="num">' + esc(d.code) + '</b>.') +
        ' Ссылка действует ' + d.minutes + ' минут. <a href="' + esc(d.url) + '" target="_blank" rel="noopener">Открыть ещё раз</a>' +
        '<br><span class="muted">Ждём подтверждения…</span>';
      stopPoll();
      var tries = 0;
      msgPoll = setInterval(function () {
        if (!document.getElementById('msgr-' + k) || ++tries > 100) { stopPoll(); return; }
        K.api('GET', '/api/messengers').then(function (s) {
          if (!s.ok || !s.data[k].linked) return;
          stopPoll();
          K.api('GET', '/api/preferences').then(function (p) { drawNotifications(s.data, p.ok ? p.data : {}); K.toast(MSG[k][0] + ' подключён'); });
        });
      }, 3000);
    });
  };
  K.actions.msgrUnlink = function (b) {
    var k = b.getAttribute('data-k');
    b.disabled = true;
    K.api('POST', '/api/messengers/' + k + '/unlink', {}).then(function (r) {
      if (!r.ok) { b.disabled = false; K.toast(K.errorText(r)); return; }
      K.api('GET', '/api/preferences').then(function (p) { drawNotifications(r.data, p.ok ? p.data : {}); K.toast(MSG[k][0] + ' отключён'); });
    });
  };

  /* ---------- Публичность ---------- */
  K.on(/^\/profile\/publicity$/, function () {
    K.load(['/api/publicity'], function (p) {
      var revoked = p.publication.status === 'revoked';
      K.page('<h1>Публичность профиля и работ</h1><p class="muted">Вы сами решаете, что из вашего профиля и работ видно другим. Изменения применяются сразу.</p>' +
        (revoked ? '<div class="note warn small">Согласие на публикацию отозвано ' + esc(K.dateY(p.publication.at)) + '. Включите любой пункт — и согласие будет дано снова.</div>' : '') +
        '<section class="card"><h2>Работы</h2>' + sw('pb-gallery', 'Галерея на сайте лиги', 'Ваши работы туров видны в галерее facepaintingleague.com', p.gallery) +
        sw('pb-social', 'Соцсети лиги', 'Лига может публиковать ваши работы в своих соцсетях', p.social) + '</section>' +
        '<section class="card"><h2>Страница мастера</h2>' + sw('pb-master', 'Показывать мою страницу заказчикам', 'Ваше имя, лига, рейтинг и лучшие работы — в поиске мастеров на сайте', p.master_page) +
        '<p class="small muted">Email и Telegram на странице мастера не показываются. Имя на сайте: <b>' + esc(p.name || '—') + '</b> · <button class="lnk" type="button" data-href="/profile/name">Изменить</button></p></section>' +
        (revoked ? '' : '<button class="btn danger wide" type="button" data-act="askRevoke">Скрыть всё и отозвать согласие на публикацию</button>') + backLink(), P.concat([['Публичность']]));
      document.getElementById('main').addEventListener('change', function (e) {
        var key = { 'pb-gallery': 'gallery', 'pb-social': 'social', 'pb-master': 'master_page' }[e.target.id];
        if (!key) return;
        var body = {}; body[key] = e.target.checked;
        if (revoked && e.target.checked) body.accept_publication = true;
        e.target.disabled = true;
        K.api('PUT', '/api/publicity', body).then(function (r) {
          e.target.disabled = false;
          if (!r.ok) { e.target.checked = !e.target.checked; K.toast(K.errorText(r)); return; }
          K.toast('Сохранено');
          if (revoked) K.route();
        });
      });
    }, P.concat([['Публичность']]));
  });
  K.actions.askRevoke = function () {
    K.showModal('<h2 id="mT">Скрыть всё и отозвать согласие?</h2><p>Ваши работы перестанут показываться в галерее сайта и больше не будут уходить в соцсети лиги. Уже вышедшие посты в соцсетях останутся.</p>' +
      '<div class="row"><button class="btn danger" type="button" data-act="revoke">Отозвать согласие</button><button class="btn sec" type="button" data-act="closeModal">Отмена</button></div>');
  };
  K.actions.revoke = function (b) {
    b.disabled = true;
    K.api('POST', '/api/publicity/revoke').then(function (r) {
      var m = b.closest('.modal'); if (m) m.remove();
      if (!r.ok) { K.toast(K.errorText(r)); return; }
      K.toast('Согласие отозвано'); K.refreshUnread(); K.route();
    });
  };

  /* ---------- Согласия и документы ---------- */
  var DOC = { rules: 'Правила лиги', personal_data: 'Обработка персональных данных', publication: 'Публикация работ на сайте и в соцсетях лиги',
    model_confirmation: 'Подтверждение модели', privacy_policy: 'Политика конфиденциальности', guardian_consent: 'Согласие родителя (законного представителя)',
    offer: 'Оферта', marketing: 'Анонсы и рассылки', public_profile: 'Публичный профиль', public_contacts: 'Публичные контакты' };
  K.on(/^\/profile\/consents$/, function () {
    K.load(['/api/consents', '/api/publicity'], function (c, p) {
      var rows = c.current.filter(function (x) { return x.document || x.status; }).map(function (x) {
        var title = DOC[x.doc_type], st;
        if (x.document && !x.current_accepted && x.status === 'accepted') {
          st = pill('Нужно принять ' + x.document.version, 'acc');
          return li(esc(title), 'Действует ' + esc(x.document.version) + ' · вы приняли ' + esc(x.version || '—'), st, '/documents/' + x.document.id);
        }
        st = x.status === 'accepted' ? pill('Принято', 'ok') : x.status === 'revoked' ? pill('Отозвано', 'plain') : pill('Не принято', 'plain');
        return li(esc(title), esc([x.version ? 'Редакция ' + x.version : '', x.at ? K.dateY(x.at) : ''].filter(Boolean).join(' · ')), st, x.document ? '/documents/' + x.document.id : null);
      });
      K.page('<h1>Согласия и документы</h1><section class="card"><h2>Что вы приняли</h2>' + (rows.length ? '<div class="list">' + rows.join('') + '</div>' : '<p class="muted">Пока ничего. Согласия даются при записи на Игру.</p>') + '</section>' +
        '<section class="card"><h2>Публичность профиля и работ</h2><dl class="kv"><dt>Галерея на сайте</dt><dd>' + (p.gallery ? 'Видны' : 'Скрыты') + '</dd><dt>Соцсети лиги</dt><dd>' +
        (p.social ? 'Разрешено' : 'Нет') + '</dd><dt>Страница мастера</dt><dd>' + (p.master_page ? 'Показывается' : 'Скрыта') + '</dd></dl><button class="btn sec" type="button" data-href="/profile/publicity">Настроить</button></section>' +
        (c.history.length ? '<details class="more card"><summary>История согласий</summary><div class="list">' + c.history.map(function (h) {
          return li(esc((DOC[h.type] || h.type) + (h.version ? ' · ' + h.version : '')), esc(K.date(h.at) + ' МСК' + (h.event ? ' · ' + h.event : '')),
            pill({ accepted: 'Принято', revoked: 'Отозвано', declined: 'Отказ' }[h.status] || h.status, h.status === 'accepted' ? 'ok' : 'plain'), null);
        }).join('') + '</div></details>' : '') +
        '<section class="card"><p class="small muted">Отозвать согласие на публикацию можно в разделе «Публичность профиля и работ». Остальные вопросы по документам — организатору.</p>' +
        '<button class="btn sec" type="button" data-href="/support/new?topic=' + encodeURIComponent('Вопрос о согласиях') + '">Написать организатору</button></section>' + backLink(), P.concat([['Согласия и документы']]));
    }, P.concat([['Согласия и документы']]));
  });

  K.on(/^\/documents\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/documents/' + id], function (d) {
      K.page('<div class="stack" data-s="g6"><span class="eyebrow">Редакция ' + esc(d.version) + ' · ' + esc(K.dateY(d.published_at)) + '</span><h1>' + esc(d.title) + '</h1></div>' +
        (d.current ? '' : '<div class="note warn small">Эта редакция больше не действует.</div>') +
        '<section class="card"><div data-s="pre">' + esc(d.body) + '</div></section>' +
        (d.current && !d.accepted ? '<section class="card"><label class="chk"><input type="checkbox" id="acc-doc"> <span>Я прочитал(а) и принимаю «' + esc(d.title) + '»</span></label>' +
          '<button class="btn" type="button" id="acc-btn" data-act="acceptDoc" data-id="' + d.id + '" disabled>Принять</button></section>' :
          d.accepted ? '<div class="note ok small">Вы приняли эту редакцию.</div>' : '') +
        '<button class="btn ghost" type="button" data-act="back">Назад</button>', [['Профиль', '/profile'], ['Согласия', '/profile/consents'], [d.title]]);
      var c = document.getElementById('acc-doc');
      if (c) c.addEventListener('change', function () { document.getElementById('acc-btn').disabled = !c.checked; });
    });
  });
  K.actions.acceptDoc = function (b) {
    b.disabled = true;
    K.api('POST', '/api/consents', { document_id: b.getAttribute('data-id') }).then(function (r) {
      if (!r.ok) { b.disabled = false; K.toast(K.errorText(r)); return; }
      K.toast('Принято'); K.refreshUnread(); K.route();
    });
  };
  K.actions.back = function () { if (history.length > 1) history.back(); else K.go('/'); };

  K.start();
})();
