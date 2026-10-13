/* Кабинет организатора (этап 3): люди, участницы Игры, документы, поддержка, пожелания с сайта. */
(function () {
  'use strict';
  var K = window.K, O = K.org, esc = K.esc, pill = K.pill, li = K.li;

  var ACCOUNT = { active: ['Входит в кабинет', 'ok'], imported: ['Ещё не входила', 'warn'], suspended: ['Приостановлен', 'bad'], deleted: ['Удалён', 'plain'] };
  var ROLE = { participant: 'Участница', judge: 'Судья', moderator: 'Модератор', admin: 'Администратор' };
  var KIND = [['all', 'Все'], ['participants', 'Участницы'], ['staff', 'Команда'], ['not_activated', 'Не входили'], ['suspended', 'Приостановлены']];
  var DOC = { rules: 'Правила лиги', publication: 'Согласие на публикацию работ', personal_data: 'Согласие на обработку персональных данных', privacy_policy: 'Политика конфиденциальности' };
  var DOC_STATE = { current: ['Действует', 'ok'], scheduled: ['Запланирована', 'info'], old: ['Прежняя', 'plain'], cancelled: ['Отменена', 'plain'] };
  var SUPPORT = { open: ['Ждёт ответа', 'acc'], waiting_admin: ['Ждёт ответа', 'acc'], waiting_user: ['Ответили', 'info'], closed: ['Закрыто', 'plain'] };
  var LEAGUE = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
  var qs = function (o) {
    var p = new URLSearchParams();
    Object.keys(o).forEach(function (k) { if (o[k] !== '' && o[k] != null) p.set(k, o[k]); });
    var s = p.toString(); return s ? '?' + s : '';
  };
  var tabs = function (items, cur, base, extra) {
    return '<nav class="row tabs" aria-label="Фильтр">' + items.map(function (t) {
      return '<button class="btn ' + (t[0] === cur ? '' : 'sec') + ' small" type="button" data-href="' + esc(base + qs(Object.assign({}, extra || {}, t[2] || {}))) + '"' +
        (t[0] === cur ? ' aria-current="page"' : '') + '>' + esc(t[1]) + (t[3] != null ? ' · ' + t[3] : '') + '</button>';
    }).join('') + '</nav>';
  };
  /* Поиск: форма меняет адрес страницы (?q=…), чтобы «Назад» возвращал к тому же списку. */
  var searchForm = function (id, value, placeholder) {
    return '<form class="search" id="' + id + '" role="search"><label class="sr" for="' + id + '-q">Поиск</label><input class="input" id="' + id + '-q" type="search" maxlength="100" value="' + esc(value) +
      '" placeholder="' + esc(placeholder) + '"><button class="btn sec" type="submit">Найти</button></form>';
  };
  var bindSearch = function (id, apply) {
    var f = document.getElementById(id);
    if (f) f.addEventListener('submit', function (e) { e.preventDefault(); apply(f.querySelector('input').value.trim()); });
  };
  var withCounts = function () { if (!K.state.orgCounts) O.refreshCounts(); };

  /* ---------- Люди ---------- */
  O.on(/^\/org\/people$/, function () {
    var q = K.query(), term = q.get('q') || '', kind = q.get('kind') || 'all', offset = +(q.get('offset') || 0);
    if (!KIND.some(function (k) { return k[0] === kind; })) kind = 'all';
    K.load(['/api/org/people' + qs({ q: term, kind: kind, offset: offset || '', limit: 50 })], function (d) {
      withCounts();
      var h = '<div class="between"><h1>Люди</h1><button class="btn" type="button" data-act="newPerson">Добавить человека</button></div>' +
        '<p class="small muted">Все, у кого есть аккаунт: участницы, судьи, команда. Здесь же — ссылки для входа.</p>' +
        searchForm('f-people', term, 'ФИО, имя, email, город или Telegram ID') +
        tabs(KIND.map(function (k) { return [k[0], k[1], { kind: k[0] === 'all' ? '' : k[0] }, d.counts[k[0]]]; }), kind, '/org/people', { q: term });
      if (kind === 'not_activated') h += '<div class="note small">Эти люди ещё не входили в кабинет (например, перенесены из бота). Откройте карточку и создайте ссылку-приглашение — перешлите её человеку сами.</div>';
      h += d.people.length ? '<section class="card"><div class="list">' + d.people.map(function (p) {
        var sub = [p.email || 'без email', p.city, p.roles.filter(function (r) { return r !== 'participant'; }).map(function (r) { return ROLE[r]; }).join(', '), p.games ? 'Игр: ' + p.games : ''].filter(Boolean).join(' · ');
        return li(esc(p.name || 'Без имени'), esc(sub), O.st(ACCOUNT, p.account_status), '/org/people/' + p.id);
      }).join('') + '</div></section>' : '<div class="note">Никого не нашлось.</div>';
      var total = d.counts[kind];
      if (offset || total > offset + d.people.length) {
        h += '<div class="row">' + (offset ? '<button class="btn sec" type="button" data-href="/org/people' + esc(qs({ q: term, kind: kind === 'all' ? '' : kind, offset: Math.max(0, offset - 50) || '' })) + '">← Предыдущие</button>' : '') +
          '<span class="muted small">' + (offset + 1) + '–' + (offset + d.people.length) + ' из ' + total + '</span>' +
          (total > offset + d.people.length ? '<button class="btn sec" type="button" data-href="/org/people' + esc(qs({ q: term, kind: kind === 'all' ? '' : kind, offset: offset + 50 })) + '">Следующие →</button>' : '') + '</div>';
      }
      K.page(h, [['Обзор', '/org'], ['Люди']]);
      bindSearch('f-people', function (v) { K.go('/org/people' + qs({ q: v, kind: kind === 'all' ? '' : kind })); });
    }, [['Обзор', '/org'], ['Люди']]);
  });
  function personFields(p) {
    var imported = !p || p.account_status === 'imported';
    return '<div class="grid2">' + O.txt('pf-full', 'ФИО', p && p.full_name, ' maxlength="200" autocomplete="off"', 'Для согласий и диплома.') +
      O.txt('pf-disp', 'Имя на сайте', p && p.display_name, ' maxlength="40" autocomplete="off"', 'Необязательно, 2–40 символов.') +
      O.txt('pf-email', 'Email', p && p.email, ' type="email" maxlength="254" autocomplete="off"' + (imported ? '' : ' disabled'),
        imported ? 'Необязательно: человек укажет его сам по ссылке-приглашению.' : 'Email — логин; меняет сам человек.') +
      O.txt('pf-tg', 'Telegram ID', p && p.telegram_id, ' inputmode="numeric" maxlength="15" autocomplete="off"', 'Числовой ID из бота, если есть.') +
      O.txt('pf-city', 'Город', p && p.city, ' maxlength="120"') + O.txt('pf-country', 'Код страны', p && p.country_code, ' maxlength="2" autocapitalize="characters"', 'Две латинские буквы: RU, KZ, BY…') + '</div>';
  }
  function readPerson(f, p) {
    var tg = f.querySelector('#pf-tg').value.trim(), body = {
      full_name: f.querySelector('#pf-full').value.trim(), display_name: f.querySelector('#pf-disp').value.trim() || null,
      city: f.querySelector('#pf-city').value.trim() || null, country_code: f.querySelector('#pf-country').value.trim() || null
    };
    if (tg && !/^\d{1,15}$/.test(tg)) return 'Telegram ID — только цифры.';
    body.telegram_id = tg ? +tg : null;
    var email = f.querySelector('#pf-email');
    if (!email.disabled) body.email = email.value.trim() || null;
    if (!body.full_name) return 'Укажите ФИО.';
    if (body.display_name && body.display_name.length < 2) return 'Имя на сайте — от 2 символов.';
    if (body.country_code && !/^[A-Za-z]{2}$/.test(body.country_code)) return 'Код страны — две латинские буквы.';
    if (p) Object.keys(body).forEach(function (k) { if ((body[k] || null) === (p[k] == null ? null : p[k])) delete body[k]; });
    return body;
  }
  K.actions.newPerson = function () {
    K.showModal('<h2 id="mT">Новый человек</h2><p class="small muted">Аккаунт без пароля. Чтобы человек вошёл, создайте в его карточке ссылку-приглашение и перешлите её.</p>' +
      '<form id="f-person-new" class="stack" novalidate>' + personFields(null) + O.errBox +
      '<div class="row"><button class="btn" type="submit">Добавить</button><button class="btn sec" type="button" data-act="closeModal">Отмена</button></div></form>');
    var f = document.getElementById('f-person-new');
    f.querySelector('#pf-full').focus();
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = readPerson(f, null);
      if (typeof body === 'string') { K.formError(f, body); return; }
      O.send('POST', '/api/org/people', body, f, function (p) {
        f.closest('.modal').remove(); K.onEscape = null; K.toast('Человек добавлен'); K.go('/org/people/' + p.id);
      });
    });
  };

  O.on(/^\/org\/people\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/org/people/' + id], drawPerson, [['Люди', '/org/people'], ['Человек']]);
  });
  function drawPerson(p) {
    O.person = p;
    var crumbs = [['Люди', '/org/people'], [p.name || 'Человек']];
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(p.roles.map(function (r) { return ROLE[r]; }).join(' · ') || 'Без ролей') + '</span>' +
      '<div class="between"><h1>' + esc(p.name || 'Без имени') + '</h1>' + O.st(ACCOUNT, p.account_status) + '</div></div>';
    /* вход */
    h += '<section class="card"><h2>Вход в кабинет</h2>';
    if (p.account_status === 'imported') {
      h += '<p>Человек ещё не входил. Создайте ссылку-приглашение и перешлите её (например, в Telegram): по ней он укажет email и пароль. Ссылка действует 7 дней и показывается один раз.</p>' +
        (p.invite ? '<p class="small muted">Есть действующее приглашение до ' + esc(O.when(p.invite.expires_at)) + '. Новая ссылка отменит его.</p>' : '') +
        '<div id="link-box"></div><button class="btn" type="button" data-act="makeLink" data-k="invite">' + (p.invite ? 'Создать новую ссылку' : 'Создать ссылку-приглашение') + '</button>';
    } else if (p.account_status === 'active') {
      h += '<dl class="kv"><dt>Email (логин)</dt><dd>' + esc(p.email || '—') + '</dd><dt>Последний вход</dt><dd>' + esc(p.last_login ? O.when(p.last_login) : '—') + '</dd></dl>' +
        '<p class="small muted">Забыл пароль? Человек может сам запросить сброс на странице входа. Если письмо не доходит — создайте ссылку для нового пароля и перешлите её: она действует сутки.</p>' +
        '<div id="link-box"></div><button class="btn sec" type="button" data-act="makeLink" data-k="reset">Ссылка для нового пароля</button>';
    } else if (p.account_status === 'suspended') {
      h += '<div class="note bad small">Аккаунт приостановлен: войти нельзя, ссылки не работают.</div>';
    }
    h += '</section>';
    /* данные */
    h += '<form class="card" id="f-person" novalidate><h2>Данные</h2>' + personFields(p) + O.errBox + '<button class="btn" type="submit">Сохранить</button></form>';
    /* Игры */
    h += '<section class="card"><h2>Игры</h2>' + (p.games.length ? '<div class="list">' + p.games.map(function (g) {
      return li(esc(g.title), esc([O.EVENT[g.event_status] ? O.EVENT[g.event_status][0] : g.event_status, g.league ? LEAGUE[g.league] : 'лига не указана', g.joined_at ? 'с ' + K.day(g.joined_at) : ''].filter(Boolean).join(' · ')),
        O.st(O.MODE, g.mode), '/org/participants/' + g.participant_id);
    }).join('') + '</div>' : '<p class="muted">Не участвовала.</p>') + '</section>';
    /* согласия */
    var cons = p.consents;
    h += '<section class="card"><h2>Согласия</h2><dl class="kv">' + ['rules', 'publication', 'personal_data'].map(function (k) {
      var c = cons[k], v;
      if (!c.current_version) v = '<span class="muted">документ не опубликован</span>';
      else if (c.current_accepted) v = pill('Принято, ред. ' + c.current_version, 'ok');
      else if (c.last_status === 'revoked') v = pill('Отозвано', 'bad');
      else if (c.last_version) v = pill('Принята ред. ' + c.last_version + ', нужна ' + c.current_version, 'warn');
      else v = pill('Не принято', 'plain');
      return '<dt>' + esc(DOC[k]) + '</dt><dd>' + v + (c.at ? ' <span class="small muted">' + esc(K.dateY(c.at)) + '</span>' : '') + '</dd>';
    }).join('') + '<dt>Работы в галерее сайта</dt><dd>' + (p.publicity.gallery ? 'да' : 'нет') + '</dd><dt>Посты в соцсетях лиги</dt><dd>' + (p.publicity.social ? 'да' : 'нет') + '</dd>' +
      '<dt>Страница мастера</dt><dd>' + (p.publicity.master_page ? 'да' : 'нет') + '</dd></dl></section>';
    /* поддержка */
    if (p.support.length) h += '<section class="card"><h2>Обращения</h2><div class="list">' + p.support.map(function (t) {
      return li('№' + t.no + ' · ' + esc(t.subject), esc(K.date(t.updated_at)), O.st(SUPPORT, t.status), '/org/support/' + t.no);
    }).join('') + '</div></section>';
    /* роли и доступ */
    h += '<section class="card"><h2>Роли</h2><p class="small muted">Администратор видит этот кабинет организатора и может всё менять. Судейство и модерация — следующие этапы.</p><div class="stack" data-s="g6">' +
      ['participant', 'judge', 'moderator', 'admin'].map(function (r) {
        var on = p.roles.indexOf(r) >= 0, self = p.me && r === 'admin';
        return O.chk('role-' + r, ROLE[r] + (self ? ' (это вы)' : ''), on, (self ? ' disabled' : '') + ' data-act="toggleRole" data-r="' + r + '"');
      }).join('') + '</div></section>';
    if (!p.me) {
      h += '<section class="card"><h2>Доступ</h2>' + (p.account_status === 'suspended' ?
        '<p class="small muted">Вернуть доступ: аккаунт снова станет активным (или будет ждать приглашения, если человек ещё не входил).</p><button class="btn sec" type="button" data-act="suspend" data-v="0">Вернуть доступ</button>' :
        '<p class="small muted">Приостановка закрывает вход и все ссылки. Данные и участие в Играх сохраняются.</p><button class="btn danger" type="button" data-act="suspend" data-v="1">Приостановить аккаунт</button>') + '</section>';
    }
    h += '<p class="small muted">Аккаунт создан ' + esc(K.dateY(p.created_at)) + (p.telegram_id ? ' · Telegram ID ' + esc(p.telegram_id) : '') + '</p>';
    K.page(h, crumbs);
    var f = document.getElementById('f-person');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = readPerson(f, p);
      if (typeof body === 'string') { K.formError(f, body); return; }
      if (!Object.keys(body).length) { K.formError(f, 'Ничего не изменилось.'); return; }
      O.send('PATCH', '/api/org/people/' + p.id, body, f, function (d) { K.toast('Сохранено'); drawPerson(d); });
    });
  }
  K.actions.makeLink = function (b) {
    var p = O.person, kind = b.getAttribute('data-k');
    b.disabled = true;
    K.api('POST', '/api/org/people/' + p.id + (kind === 'invite' ? '/invite' : '/reset-link')).then(function (r) {
      b.disabled = false;
      if (!r.ok) { K.toast(O.err(r)); return; }
      document.getElementById('link-box').innerHTML = '<div class="note ok"><b>' + (kind === 'invite' ? 'Ссылка-приглашение' : 'Ссылка для нового пароля') + '</b>' +
        '<p class="small">Действует до ' + esc(O.when(r.data.expires_at)) + '. Скопируйте сейчас — повторно её не показать (можно создать новую).</p>' +
        '<div class="copy"><input class="input" id="new-link" readonly value="' + esc(r.data.link) + '" aria-label="Ссылка"><button class="btn" type="button" data-act="copyText" data-for="new-link">Копировать</button></div>' +
        '<p class="small muted">Пересылайте лично этому человеку: по ссылке входят в его аккаунт.</p></div>';
      b.textContent = 'Создать ещё одну';
      var i = document.getElementById('new-link'); i.focus(); i.select();
    });
  };
  K.actions.toggleRole = function (el) {
    var p = O.person, r = el.getAttribute('data-r'), want = el.checked;
    el.checked = !want;   // меняем только после ответа сервера
    var go = function () {
      el.disabled = true;
      K.api('POST', '/api/org/people/' + p.id + '/roles', { role: r, enabled: want }).then(function (res) {
        el.disabled = false;
        if (!res.ok) { K.toast(O.err(res)); return; }
        K.toast(want ? 'Роль добавлена' : 'Роль снята'); drawPerson(res.data);
      });
    };
    if (r === 'admin' && want) {
      O.confirm({ title: 'Сделать администратором?', text: 'Человек получит полный доступ к кабинету организатора: Игры, люди, документы, ссылки для входа.', ok: 'Сделать администратором',
        path: '/api/org/people/' + p.id + '/roles', body: function () { return { role: 'admin', enabled: true }; }, done: drawPerson });
      return;
    }
    go();
  };
  K.actions.suspend = function (b) {
    var p = O.person, on = b.getAttribute('data-v') === '1';
    O.confirm({ title: on ? 'Приостановить аккаунт?' : 'Вернуть доступ?', text: on ? 'Человек выйдет из кабинета на всех устройствах, ссылки для входа перестанут работать.' : 'Человек снова сможет войти.',
      ok: on ? 'Приостановить' : 'Вернуть доступ', danger: on, path: '/api/org/people/' + p.id + '/suspend', body: function () { return { suspended: on }; },
      done: function (d) { K.toast('Готово'); drawPerson(d); } });
  };

  /* ---------- Участницы Игры ---------- */
  var CELL = { sent: '✓ сдана', sent_late: '✓ после срока', missed: '✕ не сдана', draft: 'черновик', none: 'ещё нет', plan: '' };
  O.on(/^\/org\/games\/([0-9a-f-]{36})\/people$/, function (id) {
    var q = K.query(), term = q.get('q') || '', mode = q.get('mode') || '', league = q.get('league') || '';
    K.load(['/api/org/events/' + id + '/participants' + qs({ q: term, mode: mode, league: league })], function (d) {
      var base = '/org/games/' + id + '/people', crumbs = [['Игры и туры', '/org/games'], [d.event.title, '/org/games/' + id], ['Участницы']];
      var canLeagues = d.total && ['registration', 'active', 'finished'].indexOf(d.event.status) >= 0;
      var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(d.event.title) + '</span><div class="between"><h1>Участницы · ' + d.total + '</h1>' +
        (canLeagues ? '<button class="btn sec small" type="button" data-href="/org/games/' + id + '/leagues">Расставить лиги</button>' : '') + '</div></div>' +
        searchForm('f-parts', term, 'ФИО, имя, email или город') +
        tabs([['', 'Все', { mode: '' }, d.total]].concat(Object.keys(O.MODE).filter(function (k) { return d.counts[k]; }).map(function (k) {
          return [k, O.MODE[k][0], { mode: k }, d.counts[k]];
        })), mode, base, { q: term, league: league });
      var lg = Object.keys(d.leagues);
      if (lg.length > 1) h += tabs([['', 'Все лиги', { league: '' }]].concat(['bronze', 'silver', 'gold', 'none'].filter(function (k) { return d.leagues[k]; }).map(function (k) {
        return [k, k === 'none' ? 'Без лиги' : LEAGUE[k], { league: k }, d.leagues[k]];
      })), league, base, { q: term, mode: mode });
      if (d.current_round) h += '<p class="small muted">Сейчас тур ' + d.current_round + '. «✕ не сдана» — срок прошёл, а работы нет; «ещё нет» — срок не прошёл.</p>';
      if (!d.participants.length) h += '<div class="note">' + (d.total ? 'Никого не нашлось.' : 'В Игру пока никто не записался.') + '</div>';
      else {
        h += '<div class="table-wrap"><table class="otable"><thead><tr><th scope="col">Участница</th><th scope="col">Статус</th><th scope="col">Лига</th>' +
          d.rounds.map(function (r) { return '<th scope="col" class="c">Тур ' + r.round_no + '</th>'; }).join('') + '</tr></thead><tbody>' +
          d.participants.map(function (p) {
            return '<tr data-href="/org/participants/' + p.id + '"><th scope="row" data-label="Участница"><button class="lnk" type="button" data-href="/org/participants/' + p.id + '">' + esc(p.name || 'Без имени') + '</button>' +
              '<span class="small muted">' + esc([p.city, p.account_status === 'imported' ? 'не входила в кабинет' : ''].filter(Boolean).join(' · ')) + '</span>' +
              (p.rules_ok ? '' : '<span class="small">' + pill('Правила не приняты', 'warn') + '</span>') + '</th>' +
              '<td data-label="Статус">' + O.st(O.MODE, p.mode) + '</td><td data-label="Лига">' + esc(p.league ? LEAGUE[p.league] : '—') + '</td>' +
              p.rounds.map(function (c) {
                var w = c.work, txt = w ? CELL[w] : '—';
                return '<td class="c" data-label="Тур ' + c.round_no + '"><div>' + (w && w !== 'plan' ? '<span class="cell ' + w + '" title="' + esc(O.WORK[w][0]) + '">' + esc(txt) + '</span>' : '<span class="muted">' + (w === 'plan' ? 'не открыт' : '—') + '</span>') +
                  (c.personal_deadline ? '<span class="small muted">личный срок до ' + esc(K.day(c.personal_deadline)) + '</span>' : '') + '</div></td>';
              }).join('') + '</tr>';
          }).join('') + '</tbody></table></div>';
      }
      K.page(h, crumbs);
      bindSearch('f-parts', function (v) { K.go(base + qs({ q: v, mode: mode, league: league })); });
    }, [['Игры и туры', '/org/games'], ['Участницы']]);
  });

  /* ---------- Лиги списком ---------- */
  var LG_OPTS = [['', 'Без лиги']].concat(O.LEAGUES);
  O.on(/^\/org\/games\/([0-9a-f-]{36})\/leagues$/, function (id) {
    K.load(['/api/org/events/' + id + '/participants'], function (d) {
      var crumbs = [['Игры и туры', '/org/games'], [d.event.title, '/org/games/' + id], ['Участницы', '/org/games/' + id + '/people'], ['Лиги']];
      var list = d.participants.filter(function (p) { return p.mode !== 'withdrawn'; });
      O.lg = { id: id, rows: list };
      var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(d.event.title) + '</span><h1>Лиги участниц · ' + list.length + '</h1>' +
        '<p class="muted">Выберите лигу каждой участнице или заполните по рейтингу, проверьте и нажмите «Сохранить лиги». Участницы получат уведомление о своей лиге.</p></div>' +
        '<section class="card"><h2>Заполнить по рейтингу</h2><form id="f-lgfill" class="stack" novalidate><div class="grid3">' +
        O.txt('lg-gold', 'Gold — рейтинг от', '', ' type="number" inputmode="numeric" min="0" max="5000"') +
        O.txt('lg-silver', 'Silver — рейтинг от', '', ' type="number" inputmode="numeric" min="0" max="5000"') +
        O.sel('lg-none', 'У кого рейтинга нет', [['keep', 'Не менять'], ['bronze', 'Bronze'], ['silver', 'Silver'], ['gold', 'Gold']], 'keep') + '</div>' +
        '<p class="small muted">Остальные с рейтингом — Bronze. Пока не нажата «Сохранить лиги», ничего не меняется.</p>' + O.errBox +
        '<div class="row"><button class="btn sec" type="submit">Заполнить</button></div></form></section>' +
        '<section class="card"><div class="between"><h2>Участницы</h2><span class="small muted" id="lg-count"></span></div>' +
        '<div class="table-wrap"><table class="otable"><thead><tr><th scope="col">Участница</th><th scope="col" class="c">Рейтинг</th><th scope="col">Статус</th><th scope="col">Лига</th></tr></thead><tbody>' +
        list.map(function (p) {
          return '<tr><th scope="row" data-label="Участница">' + esc(p.name || 'Без имени') + '<span class="small muted">' + esc(p.city || '') + '</span></th>' +
            '<td class="c" data-label="Рейтинг">' + (p.rating == null ? '—' : p.rating) + '</td><td data-label="Статус">' + O.st(O.MODE, p.mode) + '</td>' +
            '<td data-label="Лига"><label class="sr" for="lg-' + p.id + '">Лига: ' + esc(p.name || '') + '</label><select class="input lg-sel" id="lg-' + p.id + '" data-id="' + p.id + '" data-was="' + (p.league || '') + '">' +
            LG_OPTS.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === (p.league || '') ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select></td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<form id="f-lgsave" class="stack" novalidate>' + O.errBox + '<div class="row"><button class="btn" type="submit">Сохранить лиги</button>' +
        '<button class="btn sec" type="button" data-href="/org/games/' + id + '/people">Отмена</button></div></form></section>';
      K.page(h, crumbs);
      lgCount();
      document.getElementById('main').addEventListener('change', function (e) { if (e.target.classList.contains('lg-sel')) lgCount(); });
      document.getElementById('f-lgfill').addEventListener('submit', function (e) {
        e.preventDefault();
        var f = e.target, gold = f.querySelector('#lg-gold').value.trim(), silver = f.querySelector('#lg-silver').value.trim(), none = f.querySelector('#lg-none').value;
        if (gold === '' || silver === '' || Number(gold) < Number(silver)) { K.formError(f, 'Укажите оба порога: порог Gold не ниже порога Silver.'); return; }
        K.formError(f, '');
        O.lg.rows.forEach(function (p) {
          var el = document.getElementById('lg-' + p.id), v;
          if (p.rating == null) { if (none === 'keep') return; v = none; }
          else v = p.rating >= Number(gold) ? 'gold' : p.rating >= Number(silver) ? 'silver' : 'bronze';
          el.value = v;
        });
        lgCount();
        K.toast('Лиги заполнены — проверьте и сохраните');
      });
      document.getElementById('f-lgsave').addEventListener('submit', function (e) {
        e.preventDefault();
        var items = Array.prototype.filter.call(document.querySelectorAll('.lg-sel'), function (el) { return el.value !== el.getAttribute('data-was'); })
          .map(function (el) { return { id: el.getAttribute('data-id'), league: el.value || null }; });
        if (!items.length) { K.formError(e.target, 'Ничего не изменилось.'); return; }
        O.send('POST', '/api/org/events/' + id + '/leagues', { items: items }, e.target, function (r) {
          K.toast('Лиги сохранены: ' + r.changed); K.go('/org/games/' + id + '/people');
        });
      });
    }, [['Игры и туры', '/org/games'], ['Лиги']]);
  });
  function lgCount() {
    var n = { gold: 0, silver: 0, bronze: 0, '': 0 }, changed = 0;
    Array.prototype.forEach.call(document.querySelectorAll('.lg-sel'), function (el) { n[el.value]++; if (el.value !== el.getAttribute('data-was')) changed++; });
    var c = document.getElementById('lg-count');
    if (c) c.textContent = 'Gold ' + n.gold + ' · Silver ' + n.silver + ' · Bronze ' + n.bronze + ' · без лиги ' + n[''] + (changed ? ' · изменено ' + changed : '');
  }

  /* ---------- Участница в Игре ---------- */
  var ACTIONS = {
    outside: ['Перевести вне конкурса', 'Перевести вне конкурса?', 'Участница продолжит без сроков туров: работы — до конца Игры, тогда будет диплом. Она получит уведомление.'],
    'return': ['Вернуть в конкурс', 'Вернуть в конкурс?', 'Если у неё есть пропущенный срок, сначала продлите ей срок этого тура.'],
    withdraw: ['Вывести из Игры', 'Вывести из Игры?', 'Сдача работ закроется. Участница получит уведомление.'],
    restore: ['Вернуть участие', 'Вернуть участие в Игре?', 'Участница снова сможет сдавать работы.'],
    disqualify: ['Дисквалифицировать', 'Дисквалифицировать?', 'Участие прекратится. Участница получит уведомление и увидит, что подробности — в «Поддержке».'],
    undisqualify: ['Отменить дисквалификацию', 'Отменить дисквалификацию?', 'Участие продолжится.']
  };
  function actionsFor(x) {
    var m = x.mode, list = [];
    if (m === 'in') list.push('outside');
    if (m === 'outside' || m === 'out_pending' || m === 'eliminated') list.push('return');
    if (m === 'disqualified') list.push('undisqualify');
    if (m === 'withdrawn') { if (x.registration_status === 'withdrawn') list.push('restore'); }
    else if (m !== 'completed') list.push('withdraw');
    if (m !== 'disqualified' && m !== 'withdrawn' && x.registration_status === 'participating') list.push('disqualify');
    return list;
  }
  O.on(/^\/org\/participants\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/org/participants/' + id], drawParticipant, [['Игры и туры', '/org/games'], ['Участница']]);
  });
  var LOG = { org_outside: 'Переведена вне конкурса', org_return: 'Возвращена в конкурс', org_withdraw: 'Выведена из Игры', org_restore: 'Участие возвращено',
    org_disqualify: 'Дисквалифицирована', org_undisqualify: 'Дисквалификация отменена', league_set: 'Лига изменена', deadline_extended: 'Продлён срок', deadline_reset: 'Личный срок снят',
    registered: 'Записалась', chose_outside: 'Сама выбрала «вне конкурса»', late_to_outside: 'Пропущен срок — вне конкурса', withdrew: 'Сама вышла из Игры' };
  function drawParticipant(x) {
    O.part = x;
    var live = x.event.status === 'active' || x.event.status === 'registration';
    var crumbs = [['Игры и туры', '/org/games'], [x.event.title, '/org/games/' + x.event.id], ['Участницы', '/org/games/' + x.event.id + '/people'], [x.person.name || 'Участница']];
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(x.event.title) + '</span><div class="between"><h1>' + esc(x.person.name || 'Без имени') + '</h1>' + O.st(O.MODE, x.mode) + '</div></div>';
    h += '<section class="card"><dl class="kv"><dt>Лига</dt><dd>' + esc(x.league ? LEAGUE[x.league] : 'не указана') + '</dd><dt>Записалась</dt><dd>' + esc(x.joined_at ? K.dateY(x.joined_at) : '—') + '</dd>' +
      '<dt>Правила</dt><dd>' + (x.rules_ok ? pill('Приняты', 'ok') : pill('Не приняты действующие', 'warn')) + '</dd>' +
      (x.out_of_competition_at ? '<dt>Вне конкурса с</dt><dd>' + esc(K.dateY(x.out_of_competition_at)) + ' · ' + esc(x.out_source === 'admin' ? 'решение организатора' : x.out_source === 'participant' ? 'выбор участницы' : 'пропущен срок') + '</dd>' : '') +
      '<dt>Аккаунт</dt><dd>' + O.st(ACCOUNT, x.person.account_status) + ' <button class="lnk" type="button" data-href="/org/people/' + x.person.id + '">карточка</button></dd></dl>' +
      (x.missed_round ? '<div class="note warn small">Пропущен срок тура ' + x.missed_round + '. Чтобы вернуть в конкурс, сначала продлите ей срок этого тура.</div>' : '') + '</section>';
    if (live) {
      h += '<section class="card"><h2>Действия</h2><form id="f-league" class="row" novalidate>' + O.sel('p-league', 'Лига', [['', 'Не указана']].concat(O.LEAGUES), x.league || '') +
        '<button class="btn sec" type="submit">Сменить лигу</button></form><p class="small muted">Новая лига действует для туров, задание которых участница ещё не открыла.</p>' +
        '<div class="row">' + actionsFor(x).map(function (a) {
          return '<button class="btn ' + (a === 'disqualify' || a === 'withdraw' ? 'ghost' : 'sec') + '" type="button" data-act="partAction" data-a="' + a + '">' + ACTIONS[a][0] + '</button>';
        }).join('') + '</div><p class="small muted">Каждое действие — с причиной: она остаётся в журнале, участница получает уведомление.</p></section>';
    } else {
      h += '<div class="note small">' + (x.event.status === 'draft' ? 'Игра ещё черновик.' : 'Игра завершена — менять участие нельзя.') + '</div>';
    }
    h += '<section class="card"><h2>Туры</h2>' + (x.rounds.length ? x.rounds.map(function (r) {
      var src = { personal: 'личный срок', assignment: 'срок её лиги', round: 'общий срок тура' }[r.deadline_source] || '';
      var s = r.submitted;
      return '<div class="round-row"><div class="between"><h3>Тур ' + r.round_no + ' · ' + esc(r.title) + '</h3>' + (r.opened ? O.st(O.WORK, r.work) : pill('Не открыт', 'plain')) + '</div>' +
        '<p class="small muted">Срок: ' + esc(O.when(r.deadline)) + (src ? ' (' + src + ')' : '') + (r.personal ? ' · причина: ' + esc(r.personal.reason || '—') : '') + '</p>' +
        (s ? '<div class="thumbs">' + s.photos.map(function (ph) {
          return '<a href="' + esc(ph.view_url) + '" target="_blank" rel="noopener"><img src="' + esc(ph.thumb_url) + '" alt="Фото работы, тур ' + r.round_no + '" loading="lazy"></a>';
        }).join('') + '</div><p class="small muted">Сдана ' + esc(O.when(s.submitted_at)) + (s.is_on_time ? '' : ' · после срока') + (s.version_no > 1 ? ' · версия ' + s.version_no : '') +
          (s.link ? ' · <a href="' + esc(s.link) + '" target="_blank" rel="noopener nofollow">ссылка</a>' : '') + '</p>' : '') +
        (live && r.opened && !s ? '<button class="btn sec small" type="button" data-act="partDeadline" data-r="' + r.round_id + '">' + (r.personal ? 'Изменить личный срок' : 'Продлить срок') + '</button>' : '') + '</div>';
    }).join('') : '<p class="muted">Туры ещё не опубликованы.</p>') + '</section>';
    h += '<section class="card"><h2>Журнал</h2>' + (x.log.length ? '<ul class="log">' + x.log.map(function (l) {
      var extra = l.data && l.data.round_no ? ' · тур ' + l.data.round_no : '';
      if (l.action === 'league_set' && l.data) extra = ' · ' + (l.data.league ? LEAGUE[l.data.league] : 'без лиги');
      if (l.action === 'deadline_extended' && l.data && l.data.deadline) extra += ' до ' + K.date(l.data.deadline);
      return '<li><b>' + esc(LOG[l.action] || l.action) + esc(extra) + '</b><span class="small muted">' + esc(K.date(l.at)) + ' · ' + esc(l.by) + '</span>' + (l.reason || (l.data && l.data.reason) ? '<span class="small">' + esc(l.reason || l.data.reason) + '</span>' : '') + '</li>';
    }).join('') + '</ul>' : '<p class="muted small">Действий организатора пока не было.</p>') + '</section>';
    K.page(h, crumbs);
    var fl = document.getElementById('f-league');
    if (fl) fl.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = fl.querySelector('#p-league').value || null;
      if (v === x.league) { K.toast('Лига та же'); return; }
      O.send('POST', '/api/org/participants/' + x.id + '/league', { league: v }, null, function (d) { K.toast('Лига изменена'); drawParticipant(d); });
    });
  }
  K.actions.partAction = function (b) {
    var x = O.part, a = b.getAttribute('data-a'), t = ACTIONS[a];
    O.confirm({ title: t[1], text: t[2], ok: t[0], danger: a === 'disqualify' || a === 'withdraw', reason: true, path: '/api/org/participants/' + x.id + '/action',
      body: function (reason) { return { action: a, reason: reason }; }, done: function (d) { K.toast('Готово'); drawParticipant(d); } });
  };
  K.actions.partDeadline = function (b) {
    var x = O.part, r = x.rounds.filter(function (y) { return y.round_id === b.getAttribute('data-r'); })[0];
    K.showModal('<h2 id="mT">Личный срок · тур ' + r.round_no + '</h2><p class="small muted">Сейчас её срок — ' + esc(O.when(r.deadline)) +
      '. Новый должен быть позже обычного срока (тура или её лиги) и не позже конца Игры. Работа, сданная до нового срока, идёт в конкурс; участница получит уведомление.</p><form id="f-dl" class="stack" novalidate>' +
      O.dt('dl-at', 'Новый срок', r.personal ? r.personal.deadline : null) + '<div class="field"><label for="dl-reason">Причина (видна в журнале)</label><textarea class="input" id="dl-reason" maxlength="500">' + esc(r.personal ? r.personal.reason || '' : '') + '</textarea></div>' +
      O.errBox + '<div class="row"><button class="btn" type="submit">Сохранить срок</button>' + (r.personal ? '<button class="btn ghost" type="button" id="dl-reset">Убрать личный срок</button>' : '') +
      '<button class="btn sec" type="button" data-act="closeModal">Отмена</button></div></form>');
    var f = document.getElementById('f-dl'), done = function (d) { f.closest('.modal').remove(); K.onEscape = null; K.toast('Срок сохранён'); drawParticipant(d); };
    f.querySelector('#dl-at').focus();
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var at = K.fromInput(f.querySelector('#dl-at').value), reason = f.querySelector('#dl-reason').value.trim();
      if (!at) { K.formError(f, 'Укажите новый срок.'); return; }
      if (!reason) { K.formError(f, 'Укажите причину.'); return; }
      O.send('POST', '/api/org/participants/' + x.id + '/deadline', { round_id: r.round_id, deadline: at, reason: reason }, f, done);
    });
    var rs = document.getElementById('dl-reset');
    if (rs) rs.addEventListener('click', function () {
      var reason = f.querySelector('#dl-reason').value.trim();
      if (!reason) { K.formError(f, 'Укажите причину — участница получит уведомление.'); return; }
      O.send('POST', '/api/org/participants/' + x.id + '/deadline', { round_id: r.round_id, deadline: null, reason: reason }, f, done);
    });
  };

  /* ---------- Документы ---------- */
  O.on(/^\/org\/documents$/, function () {
    K.load(['/api/org/documents'], function (d) {
      var h = '<h1>Документы</h1><p class="small muted">Опубликованный текст не меняется — исправление выходит новой редакцией. Новую редакцию Правил участницы принимают в кабинете; до этого сдача работ у них закрыта.</p>';
      Object.keys(d.documents).forEach(function (k) {
        var x = d.documents[k], cur = x.current, sch = x.scheduled;
        h += '<section class="card"><div class="between"><h2>' + esc(DOC[k] || k) + '</h2>' + (cur ? pill('Ред. ' + cur.version, 'ok') : pill(x.required ? 'Не опубликован' : 'Нет', x.required ? 'warn' : 'plain')) + '</div>' +
          (cur ? '<p class="small muted">Действует с ' + esc(O.when(cur.published_at)) + ' · приняли: ' + cur.accepted + '</p>' : '') +
          (sch ? '<div class="note info small">Запланирована ред. ' + esc(sch.version) + ' на ' + esc(O.when(sch.published_at)) +
            '. <button class="lnk" type="button" data-act="docCancel" data-id="' + sch.id + '" data-v="' + esc(sch.version) + '">Отменить</button></div>' : '') +
          '<div class="row">' + (sch ? '' : '<button class="btn sec" type="button" data-href="/org/documents/new?type=' + k + '">' + (cur ? 'Новая редакция' : 'Опубликовать') + '</button>') +
          (cur ? '<button class="btn ghost" type="button" data-href="/org/documents/' + cur.id + '">Читать</button>' : '') + '</div>' +
          (x.history.length > 1 || (x.history.length && !cur) ? '<details class="more"><summary>Все редакции · ' + x.history.length + '</summary><div class="list">' + x.history.map(function (v) {
            return li('Редакция ' + esc(v.version), esc(O.when(v.published_at) + (v.state === 'current' || v.state === 'old' ? ' · приняли: ' + v.accepted : '')), O.st(DOC_STATE, v.state), '/org/documents/' + v.id);
          }).join('') + '</div></details>' : '') + '</section>';
      });
      K.page(h, [['Обзор', '/org'], ['Документы']]);
    }, [['Обзор', '/org'], ['Документы']]);
  });
  K.actions.docCancel = function (b) {
    O.confirm({ title: 'Отменить редакцию ' + b.getAttribute('data-v') + '?', text: 'Она не выйдет; продолжит действовать текущая редакция.', ok: 'Отменить выход', danger: true,
      path: '/api/org/documents/' + b.getAttribute('data-id') + '/cancel', done: function () { K.toast('Выход отменён'); K.route(); } });
  };
  O.on(/^\/org\/documents\/new$/, function () {
    var type = K.query().get('type');
    if (!DOC[type]) type = 'rules';
    K.load(['/api/org/documents'], function (d) {
      var cur = d.documents[type] && d.documents[type].current, crumbs = [['Документы', '/org/documents'], ['Новая редакция']];
      var h = '<h1>' + esc(DOC[type]) + ': новая редакция</h1>' + (cur ? '<p class="small muted">Сейчас действует ред. ' + esc(cur.version) + '. Текст ниже — её копия: правьте его.</p>' : '') +
        '<form class="card" id="f-doc" novalidate><div class="grid2">' + O.txt('dc-ver', 'Номер редакции', '', ' maxlength="20" placeholder="например, 2.0"', 'Должен отличаться от прежних.') +
        O.txt('dc-title', 'Заголовок', cur ? cur.title : DOC[type], ' maxlength="200"') + '</div>' +
        O.area('dc-body', 'Текст', '', ' maxlength="200000" data-s="h400"', 'Обычный текст; абзацы — пустой строкой.') +
        '<fieldset class="stack" data-s="g6"><legend>Когда вступает в силу</legend><label class="chk"><input type="radio" name="when" value="now" checked> <span>Сразу после публикации</span></label>' +
        '<label class="chk"><input type="radio" name="when" value="at"> <span>В выбранную дату</span></label>' + O.dt('dc-at', 'Дата и время (МСК)', null) + '</fieldset>' +
        (type === 'rules' ? '<div class="note warn small">Участницы идущих Игр получат уведомление. Пока они не примут новые Правила, сдача и замена работ у них закрыты.</div>' : '') +
        O.errBox + '<div class="row"><button class="btn" type="submit">Опубликовать</button><button class="btn sec" type="button" data-href="/org/documents">Отмена</button></div></form>';
      K.page(h, crumbs);
      var f = document.getElementById('f-doc');
      if (cur) K.api('GET', '/api/org/documents/' + cur.id).then(function (r) { if (r.ok && !f.querySelector('#dc-body').value) f.querySelector('#dc-body').value = r.data.body; });
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var at = f.querySelector('input[name=when]:checked').value === 'at' ? K.fromInput(f.querySelector('#dc-at').value) : null;
        var body = { doc_type: type, version: f.querySelector('#dc-ver').value.trim(), title: f.querySelector('#dc-title').value.trim(), body: f.querySelector('#dc-body').value.trim(), publish_at: at };
        if (!body.version) { K.formError(f, 'Укажите номер редакции.'); return; }
        if (!body.title) { K.formError(f, 'Укажите заголовок.'); return; }
        if (body.body.length < 20) { K.formError(f, 'Текст слишком короткий.'); return; }
        if (f.querySelector('input[name=when]:checked').value === 'at' && !at) { K.formError(f, 'Укажите дату вступления в силу.'); return; }
        O.confirm({ title: 'Опубликовать редакцию ' + body.version + '?', text: at ? 'Она вступит в силу ' + O.when(at) + '. До этого её можно отменить.' : 'Она сразу станет действующей. Текст потом не поменять — только новой редакцией.',
          ok: 'Опубликовать', path: '/api/org/documents', body: function () { return body; }, done: function () { K.toast('Опубликовано'); K.go('/org/documents'); } });
      });
    }, [['Документы', '/org/documents'], ['Новая редакция']]);
  });
  O.on(/^\/org\/documents\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/org/documents/' + id], function (d) {
      K.page('<div class="stack" data-s="g6"><span class="eyebrow">' + esc(DOC[d.type] || d.type) + ' · редакция ' + esc(d.version) + '</span><div class="between"><h1>' + esc(d.title) + '</h1>' + O.st(DOC_STATE, d.state) + '</div></div>' +
        '<p class="small muted">' + esc((d.state === 'scheduled' ? 'Вступит в силу ' : 'Опубликована ') + O.when(d.published_at)) + (d.superseded_at && d.state === 'old' ? ' · действовала до ' + esc(O.when(d.superseded_at)) : '') +
        (d.state !== 'scheduled' && d.state !== 'cancelled' ? ' · приняли: ' + d.accepted : '') + '</p><section class="card doc-body"><div data-s="pre">' + esc(d.body) + '</div></section>',
      [['Документы', '/org/documents'], ['Редакция ' + d.version]]);
    }, [['Документы', '/org/documents'], ['Документ']]);
  });

  /* ---------- Поддержка ---------- */
  O.on(/^\/org\/support$/, function () {
    var q = K.query(), status = q.get('status') || 'waiting', term = q.get('q') || '';
    K.load(['/api/org/support' + qs({ status: status, q: term })], function (d) {
      withCounts();
      var h = '<h1>Поддержка</h1>' + searchForm('f-sup', term, 'Тема, имя, email или номер') +
        tabs([['waiting', 'Ждут ответа', { status: '' }, d.counts.waiting], ['answered', 'Ответили', { status: 'answered' }, d.counts.answered],
          ['closed', 'Закрыты', { status: 'closed' }, d.counts.closed], ['all', 'Все', { status: 'all' }]], status, '/org/support', { q: term });
      h += d.threads.length ? '<section class="card"><div class="list">' + d.threads.map(function (t) {
        return li('№' + t.no + ' · ' + esc(t.subject), esc([t.person.name, t.context, K.date(t.updated_at)].filter(Boolean).join(' · ')) +
          (t.last ? '<br><span class="muted">' + esc((t.last.from === 'admin' ? 'Вы: ' : '') + t.last.text) + '</span>' : ''), O.st(SUPPORT, t.status), '/org/support/' + t.no);
      }).join('') + '</div></section>' : '<div class="note">' + (status === 'waiting' && !term ? 'Все обращения отвечены.' : 'Ничего не нашлось.') + '</div>';
      K.page(h, [['Обзор', '/org'], ['Поддержка']]);
      bindSearch('f-sup', function (v) { K.go('/org/support' + qs({ q: v, status: status === 'waiting' ? '' : status })); });
    }, [['Обзор', '/org'], ['Поддержка']]);
  });
  O.on(/^\/org\/support\/(\d+)$/, function (no) {
    K.load(['/api/org/support/' + no], drawThread, [['Поддержка', '/org/support'], ['Обращение']]);
  });
  function drawThread(t) {
    O.thread = t;
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">№' + t.no + ' · ' + esc(t.context) + '</span><div class="between"><h1>' + esc(t.subject) + '</h1>' + O.st(SUPPORT, t.status) + '</div></div>' +
      '<p class="small"><button class="lnk" type="button" data-href="/org/people/' + t.person.id + '">' + esc(t.person.name || 'Участница') + '</button></p>' +
      '<section class="card"><div class="msgs">' + t.messages.map(function (m) {
        return '<div class="msg ' + (m.from === 'admin' ? 'me' : 'them') + '"><span class="small muted">' + esc(m.from === 'admin' ? m.author + ' · лига' : m.author) + ' · ' + esc(K.date(m.at)) + '</span><p data-s="pre">' + esc(m.body) + '</p></div>';
      }).join('') + '</div></section>' +
      '<form class="card" id="f-answer" novalidate><h2>Ответ</h2><div class="field"><label for="ans">Текст</label><textarea class="input" id="ans" maxlength="4000" data-s="h120"></textarea>' +
      '<span class="hint">Участница увидит ответ в кабинете и получит уведомление.</span></div>' + O.errBox +
      '<div class="row"><button class="btn" type="submit" data-st="waiting_user">Ответить</button><button class="btn sec" type="submit" data-st="closed">Ответить и закрыть</button></div></form>' +
      '<div class="row">' + (t.status === 'closed' ? '<button class="btn ghost" type="button" data-act="threadStatus" data-st="waiting_admin">Открыть снова</button>' :
        '<button class="btn ghost" type="button" data-act="threadStatus" data-st="closed">Закрыть без ответа</button>') + '</div>';
    K.page(h, [['Поддержка', '/org/support'], ['№' + t.no]]);
    var f = document.getElementById('f-answer');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = f.querySelector('#ans').value.trim(), st = (e.submitter && e.submitter.getAttribute('data-st')) || 'waiting_user';
      if (!body) { K.formError(f, 'Напишите ответ.'); return; }
      O.send('POST', '/api/org/support/' + t.no + '/reply', { body: body, status: st }, f, function (d) { K.toast('Ответ отправлен'); O.refreshCounts(); drawThread(d); });
    });
  }
  K.actions.threadStatus = function (b) {
    var t = O.thread;
    O.send('POST', '/api/org/support/' + t.no + '/status', { status: b.getAttribute('data-st') }, null, function (d) { K.toast('Готово'); O.refreshCounts(); drawThread(d); });
  };

  /* ---------- Пожелания с сайта ---------- */
  O.on(/^\/org\/feedback$/, function () {
    var status = K.query().get('status') || 'inbox';
    K.load(['/api/org/feedback' + qs({ status: status })], function (d) {
      var c = d.counts;
      var h = '<h1>Пожелания</h1><p class="small muted">Анонимные сообщения с сайта (страница «Пожелания лиге»). Кто написал, не известно, если человек сам не оставил контакт.</p>' +
        tabs([['inbox', 'Входящие', { status: '' }, (c['new'] || 0) + (c.read || 0)], ['new', 'Новые', { status: 'new' }, c['new'] || 0], ['archived', 'Архив', { status: 'archived' }, c.archived || 0]], status, '/org/feedback');
      h += d.items.length ? d.items.map(function (f) {
        return '<article class="card fb' + (f.status === 'new' ? ' fb-new' : '') + '"><div class="between"><span class="small muted">' + esc(O.when(f.created_at)) + (f.page ? ' · со страницы ' + esc(f.page) : '') + '</span>' +
          (f.status === 'new' ? pill('новое', 'acc') : '') + '</div><p data-s="pre">' + esc(f.text) + '</p>' + (f.contact ? '<p class="small"><b>Контакт:</b> ' + esc(f.contact) + '</p>' : '') +
          '<div class="row">' + (f.status === 'new' ? '<button class="btn sec small" type="button" data-act="fb" data-id="' + f.id + '" data-st="read">Прочитано</button>' : '') +
          (f.status !== 'archived' ? '<button class="btn ghost small" type="button" data-act="fb" data-id="' + f.id + '" data-st="archived">В архив</button>' :
            '<button class="btn ghost small" type="button" data-act="fb" data-id="' + f.id + '" data-st="read">Вернуть во входящие</button>') + '</div></article>';
      }).join('') : '<div class="note">' + (status === 'archived' ? 'Архив пуст.' : 'Новых пожеланий нет.') + '</div>';
      K.page(h, [['Обзор', '/org'], ['Пожелания']]);
    }, [['Обзор', '/org'], ['Пожелания']]);
  });
  K.actions.fb = function (b) {
    b.disabled = true;
    K.api('POST', '/api/org/feedback/' + b.getAttribute('data-id'), { status: b.getAttribute('data-st') }).then(function (r) {
      if (!r.ok) { b.disabled = false; K.toast(O.err(r)); return; }
      O.refreshCounts().then(function () { K.route(); });
    });
  };
})();
