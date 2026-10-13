/* Кабинет FPL — основа: запросы к серверу, даты по Москве, каркас (шапка, меню, нижняя панель), переходы, вход. */
(function () {
  'use strict';
  var K = window.K = {};
  var ROOT = K.ROOT = document.body.getAttribute('data-root') || '';
  var app = document.getElementById('app');
  K.state = { config: null, me: null, unread: 0, menu: false, more: false };

  /* ---------- мелочи ---------- */
  K.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var esc = K.esc;
  K.pill = function (text, kind) { return '<span class="pill ' + (kind || '') + '">' + esc(text) + '</span>'; };
  K.attr = function (obj) { return esc(JSON.stringify(obj)); };

  K.api = function (method, path, body, raw) {
    // Любой исход — ответ { status, ok, data, detail }: обрыв связи и таймаут дают status 0, кнопки не «зависают».
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (raw) { opts.body = raw.body; opts.headers['Content-Type'] = raw.type; }
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = null;
    if (ctl) {
      opts.signal = ctl.signal;
      timer = setTimeout(function () { ctl.abort(); }, raw ? 300000 : 30000);   // фото на мобильном — до 5 минут
    }
    var fail = { status: 0, ok: false, data: null, detail: null };
    return fetch(ROOT + path, opts).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
        if (r.status === 401 && path.indexOf('/web-auth/') !== 0) { K.state.me = null; }
        return { status: r.status, ok: r.ok, data: data, detail: data && typeof data.detail === 'string' ? data.detail : null };
      });
    }).catch(function () { return fail; }).then(function (res) { if (timer) clearTimeout(timer); return res; });
  };

  var REASONS = {
    registration_closed: 'Запись на эту Игру закрыта.', documents_missing: 'Организатор ещё не опубликовал Правила — запись откроется позже.',
    consents_required: 'Отметьте оба пункта: Правила и согласие на публикацию.', adult_required: 'Участвовать в Играх можно с 18 лет — отметьте пункт «Мне есть 18 лет».', personal_data_required: 'Нужно согласие на обработку персональных данных.',
    place_required: 'Укажите страну и город.', judge_of_game: 'Вы судья этой Игры — участвовать в ней нельзя.', contact_organizer: 'Запись отменена. Напишите организатору.',
    deadline_passed: 'Срок сдачи прошёл.', game_over: 'Приём работ закрыт.', not_open: 'Тур ещё не открыт.', rules: 'Сначала примите новые Правила.',
    choose_first: 'Сначала выберите, как продолжить.', withdrawn: 'Вы вышли из Игры.', eliminated: 'Сдача работ закрыта.', not_participating: 'Вы не участвуете в этой Игре.',
    task_not_ready: 'Задание ещё готовится. Загляните позже.', draft_changed: 'Работа изменилась в другом окне. Обновите страницу.',
    photo_required: 'Добавьте фото работы.', link_required: 'Добавьте ссылку на публикацию.', too_many_photos: 'Слишком много фото для этого задания.',
    link_not_accepted: 'Ссылка в этом задании не принимается.', photo_not_accepted: 'Фото в этом задании не принимаются.', empty: 'Добавьте фото или ссылку.',
    bad_link: 'Проверьте ссылку: нужен адрес, начинающийся с https://', unknown_photo: 'Фото не найдено. Загрузите его ещё раз.',
    not_an_image: 'Файл не похож на фото. Выберите JPG, PNG или WebP.', too_many_pixels: 'Фото слишком большое по размеру в пикселях. Сохраните его поменьше и загрузите снова.', unsupported_format: 'Выберите фото JPG, PNG или WebP.', too_large: 'Файл слишком большой. До 20 МБ.',
    storage_full: 'Фото не сохранилось: на сервере закончилось место. Напишите организатору и попробуйте позже.',
    duplicate_photo: 'Это фото уже добавлено. Выберите другое.', organizer_only: 'Этот раздел только для организатора.', consent_required: 'Чтобы снова показывать работы, нужно согласие на публикацию.',
    closed: 'Обращение закрыто. Создайте новое.', email_taken: 'Этот email уже занят. Войдите с ним или напишите организатору.',
    email_invited: 'Этот email уже есть у участницы из бота. Попросите у организатора ссылку для входа — так сохранится история Игр.',
    email_preset: 'Для этой ссылки организатор уже указал email. Введите его.', full_name_locked: 'ФИО меняется через организатора.', not_current: 'Эта редакция уже не действует.', not_allowed: 'Это действие сейчас недоступно.'
  };
  K.errorText = function (res) {
    if (res.status === 0) return 'Нет связи с сервером. Проверьте интернет и повторите.';
    if (res.status === 429) return 'Слишком много попыток подряд. Попробуйте через 15 минут.';
    if (res.status === 401) return 'Вход в кабинет закончился — войдите снова.';
    if (res.status === 502 || res.status === 504 || (res.status === 503 && res.detail !== 'busy')) return 'Кабинет на минуту перезагружается. Подождите немного и повторите.';
    if (res.detail && REASONS[res.detail]) return REASONS[res.detail];
    if (res.status === 403) return 'Действие недоступно. Обновите страницу.';
    if (res.status === 404) return 'Не найдено.';
    if (res.status === 413) return REASONS.too_large;
    if (res.status === 422) return 'Проверьте заполненные поля.';
    return 'Что-то пошло не так (' + res.status + '). Попробуйте ещё раз.';
  };

  K.toast = function (text) {
    var t = document.getElementById('toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(K.toast.timer);
    K.toast.timer = setTimeout(function () { t.hidden = true; }, Math.max(3500, String(text).length * 70));   // длинное — дольше
  };

  /* ---------- даты: все сроки лиги — по Москве ---------- */
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  function parts(iso) {
    var d = new Date(iso);
    var p = {};
    new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
      .formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
    return { y: +p.year, m: +p.month, d: +p.day, hm: p.hour + ':' + p.minute };
  }
  K.TZ = 'МСК (UTC+3)';
  K.day = function (iso) { if (!iso) return ''; var p = parts(iso); return p.d + ' ' + MONTHS[p.m - 1]; };
  K.date = function (iso) { if (!iso) return ''; var p = parts(iso); return p.d + ' ' + MONTHS[p.m - 1] + ', ' + p.hm; };
  // Человек не в Москве — подсказать его время: «21:00 МСК (у вас — 20:00)». В Москве — ничего лишнего.
  var LOCAL_TZ = (function () { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; } })();
  K.localHint = function (iso) {
    if (!iso || !LOCAL_TZ || LOCAL_TZ === 'Europe/Moscow') return '';
    var d = new Date(iso), msk = parts(iso);
    var hm = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    if (hm === msk.hm && d.getDate() === msk.d) return '';
    return ' (у вас — ' + (d.getDate() !== msk.d ? d.getDate() + ' ' + MONTHS[d.getMonth()] + ', ' : '') + hm + ')';
  };
  K.msk = function (iso) { return iso ? K.date(iso) + ' МСК' + K.localHint(iso) : ''; };
  K.dateY = function (iso) { if (!iso) return ''; var p = parts(iso); return p.d + ' ' + MONTHS[p.m - 1] + ' ' + p.y; };
  K.range = function (a, b) {
    if (!a && !b) return '';
    if (!a || !b) return K.dateY(a || b);
    var x = parts(a), y = parts(b);
    if (x.y === y.y && x.m === y.m) return x.d + ' — ' + y.d + ' ' + MONTHS[y.m - 1] + ' ' + y.y;
    if (x.y === y.y) return x.d + ' ' + MONTHS[x.m - 1] + ' — ' + y.d + ' ' + MONTHS[y.m - 1] + ' ' + y.y;
    return K.dateY(a) + ' — ' + K.dateY(b);
  };
  function plural(n, a, b, c) { var m = n % 10, h = n % 100; return n + ' ' + (m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 12 || h > 14) ? b : c); }
  K.left = function (iso) {
    if (!iso) return '';
    var ms = new Date(iso) - Date.now();
    if (ms <= 0) return 'срок прошёл';
    var h = Math.floor(ms / 3600000), d = Math.floor(h / 24);
    if (d >= 1) return 'осталось ' + plural(d, 'день', 'дня', 'дней') + (h % 24 ? ' ' + plural(h % 24, 'час', 'часа', 'часов') : '');
    if (h >= 1) return 'осталось ' + plural(h, 'час', 'часа', 'часов');
    return 'осталось ' + plural(Math.max(1, Math.floor(ms / 60000)), 'минута', 'минуты', 'минут');
  };
  K.deadline = function (iso, rel) {
    return '<div class="deadline"><span class="d num">' + esc(K.date(iso)) + '</span><span class="tz">' + K.TZ + esc(K.localHint(iso)) +
      (rel === false ? '' : ' · ' + esc(rel || K.left(iso))) + '</span></div>';
  };
  /* Поля даты и времени — по Москве (UTC+3, без перехода на летнее время). */
  K.toInput = function (iso) {
    if (!iso) return '';
    var d = new Date(new Date(iso).getTime() + 3 * 3600000);
    return d.toISOString().slice(0, 16);
  };
  K.fromInput = function (v) { return v ? v + ':00+03:00' : null; };
  /* «TOP WORK · Gold» — отметка всегда с лигой (решение 13.10: лучшие работы выбираются в каждой лиге). */
  K.topWork = function (league) { return 'TOP WORK' + (league && K.LEAGUE[league] ? ' · ' + K.LEAGUE[league] : ''); };
  K.score = function (v) { return v == null ? '—' : String(Math.round(v * 10) / 10).replace('.', ','); };
  /* «Записаться на Игру 02»: название Игры в винительном падеже. */
  K.acc = function (title) { return String(title || '').replace(/^Игра(?=\s)/, 'Игру'); };
  K.LEAGUE = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };

  /* ---------- переходы ---------- */
  K.path = function () {
    var p = location.pathname;
    p = ROOT && p.indexOf(ROOT) === 0 ? p.slice(ROOT.length) : p;
    return p || '/';
  };
  // «Тур 3 · Цветы Пандоры»; если у тура нет своего названия (просто «Тур 3») — без повтора. Возвращает уже экранированный текст.
  K.roundName = function (no, title) {
    var t = (title || '').trim();
    return 'Тур ' + no + (t && !/^(Тур|Round)\s*\d+$/i.test(t) ? ' · ' + K.esc(t) : '');
  };
  K.query = function () { return new URLSearchParams(location.search); };
  K.go = function (to, replace) {
    history[replace ? 'replaceState' : 'pushState'](null, '', ROOT + to);
    K.state.menu = false; K.state.more = false;
    K.route();
    window.scrollTo(0, 0);
  };
  K.routes = [];
  K.on = function (re, fn) { K.routes.push([re, fn]); };
  K.actions = {};

  K.li = function (title, sub, right, href, cls) {
    return '<button class="li ' + (cls || '') + (href ? '' : ' static') + '" type="button"' + (href ? ' data-href="' + esc(href) + '"' : '') +
      '><span class="t">' + title + '</span>' + (sub ? '<span class="s">' + sub + '</span>' : '') + '<span class="r">' + (right || '') + '</span></button>';
  };
  K.crumbs = function (items) {
    if (!items || !items.length) return '';
    var up = items[items.length - 2];
    return '<nav class="crumb" aria-label="Путь">' + (up ? '<button type="button" class="up" data-href="' + esc(up[1]) + '" aria-label="Назад: ' + esc(up[0]) + '">‹</button>' : '') +
      items.map(function (x, i) {
        return (i ? '<span aria-hidden="true">/</span>' : '') + (x[1] && i < items.length - 1 ? '<button type="button" data-href="' + esc(x[1]) + '">' + esc(x[0]) + '</button>' : '<span>' + esc(x[0]) + '</span>');
      }).join('') + '</nav>';
  };

  /* ---------- каркас ---------- */
  var SECTIONS = [['/', 'Главная'], ['/events', 'Игры лиги'], ['/games', 'Мои Игры'], ['/achievements', 'Мои достижения'],
    ['/reviews', 'Мои разборы'], ['/notifications', 'Уведомления'], ['/support', 'Поддержка'], ['/profile', 'Профиль и настройки']];
  /* Кабинет организатора — свой раздел /org со своим меню (этап 3). */
  var ORG = [['/org', 'Обзор'], ['/org/games', 'Игры и туры'], ['/org/people', 'Люди'], ['/org/support', 'Поддержка'],
    ['/org/claims', 'Заявки'], ['/org/feedback', 'Пожелания'], ['/org/reviews', 'Разборы'], ['/org/documents', 'Документы']];
  K.inOrg = function () { var p = K.path(); return p === '/org' || p.indexOf('/org/') === 0; };
  K.isAdmin = function () { return !!(K.state.me && K.state.me.roles && K.state.me.roles.indexOf('admin') >= 0); };
  /* Судейство (этап 4): раздел видят судьи и администраторы — организатор тоже может судить. */
  K.isJudge = function () { var r = (K.state.me && K.state.me.roles) || []; return r.indexOf('judge') >= 0 || r.indexOf('admin') >= 0; };
  function sections() {
    if (!K.isJudge()) return SECTIONS;
    return SECTIONS.slice(0, 3).concat([['/judging', 'Судейство']], SECTIONS.slice(3));
  }
  function section() {
    var p = K.path(), list = K.inOrg() ? ORG : sections();
    if (p === list[0][0]) return p;
    for (var i = 1; i < list.length; i++) if (p === list[i][0] || p.indexOf(list[i][0] + '/') === 0) return list[i][0];
    if (p.indexOf('/documents/') === 0) return '/profile';
    return '';
  }
  function navHTML() {
    var cur = section(), n = K.state.unread, org = K.inOrg(), c = K.state.orgCounts || {};
    var list = org ? ORG : sections();
    var badge = function (s) {
      if (org) { var x = s[0] === '/org/support' ? c.support : s[0] === '/org/feedback' ? c.feedback : s[0] === '/org/reviews' ? c.reviews : s[0] === '/org/claims' ? c.claims : 0; return x ? '<span class="cnt">' + x + '</span>' : ''; }
      return s[0] === '/notifications' && n ? '<span class="cnt">' + n + '</span>' : '';
    };
    return '<nav class="nav" aria-label="' + (org ? 'Разделы организатора' : 'Разделы кабинета') + '">' + list.map(function (s) {
      return '<button type="button" data-href="' + s[0] + '"' + (cur === s[0] ? ' aria-current="page"' : '') + '><span>' + s[1] + '</span>' + badge(s) + '</button>';
    }).join('') + '<div class="sep"></div>' +
      (org ? '<button type="button" data-href="/"><span>Кабинет участника</span></button>' :
        K.isAdmin() ? '<button type="button" data-href="/org"><span>Кабинет организатора</span></button>' : '') +
      '<button type="button" data-act="toSite"><span>Сайт лиги ↗</span></button>' +
      '<button type="button" class="out" data-act="logout"><span>Выйти</span></button></nav>';
  }
  var ICON = {
    '/': '<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
    '/games': '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    '/notifications': '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    '/profile': '<circle cx="12" cy="8" r="4"/><path d="M4 20c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
    more: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>'
  };
  function ico(k) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true">' + ICON[k] + '</svg>'; }
  function tabbarHTML() {
    var cur = section(), n = K.state.unread;
    var tabs = [['/', 'Главная'], ['/games', 'Мои Игры'], ['/notifications', 'Уведомления'], ['/profile', 'Профиль']];
    var inMore = ['/events', '/achievements', '/support', '/judging', '/reviews'].indexOf(cur) >= 0;
    return '<nav class="tabbar" aria-label="Разделы кабинета">' + tabs.map(function (t) {
      return '<button type="button" data-href="' + t[0] + '"' + (cur === t[0] ? ' aria-current="page"' : '') + '>' + ico(t[0]) +
        (t[0] === '/notifications' && n ? '<span class="cnt">' + n + '</span>' : '') + '<span>' + t[1] + '</span></button>';
    }).join('') + '<button type="button" data-act="more"' + (inMore ? ' aria-current="page"' : '') + ' aria-haspopup="dialog">' + ico('more') + '<span>Ещё</span></button></nav>';
  }
  function moreHTML() {
    return '<div class="sheet" data-act="closeMore"><div class="panel" role="dialog" aria-label="Ещё разделы"><span class="grip"></span><div class="list">' +
      (K.isAdmin() ? K.li('Кабинет организатора', 'Игры, туры, люди, заявки', '', '/org') : '') +
      K.li('Игры лиги', 'Каталог Игр и челленджей', '', '/events') + (K.isJudge() ? K.li('Судейство', 'Оценка работ туров', '', '/judging') : '') +
      K.li('Мои достижения', 'Рейтинг, баллы, дипломы', '', '/achievements') + K.li('Мои разборы', 'Аудиоразбор работ от судьи', '', '/reviews') +
      K.li('Поддержка', 'Вопросы организатору', '', '/support') +
      '<button class="li" type="button" data-act="toSite"><span class="t">Сайт лиги ↗</span><span class="s">Рейтинг, Игры, Правила — вход в кабинет сохранится</span><span class="r"></span></button>' +
      '</div><button class="btn sec" type="button" data-act="logout">Выйти</button></div></div>';
  }
  function header(auth) {
    var n = K.state.unread;
    var org = !auth && K.inOrg();
    return '<header class="hdr"><button class="logo" type="button" data-href="' + (org ? '/org' : '/') + '">FPL<small>' + (org ? 'ОРГАНИЗАТОР' : 'КАБИНЕТ') + '</small></button><span class="ctx"></span>' +
      (auth ? '' : '<button class="burger" type="button" data-act="menu" aria-label="Открыть меню" aria-expanded="' + K.state.menu + '"><span></span><span></span><span></span></button>' +
        '<button class="bell" type="button" data-href="/notifications" aria-label="Уведомления' + (n ? ', новых: ' + n : '') + '">' +
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>' +
        (n ? '<i>' + n + '</i>' : '') + '</button>') + '</header>';
  }

  K.last = { body: '', crumbs: null };
  /* Страница внутри кабинета (после входа). */
  K.page = function (body, crumbs) {
    K.last = { body: body, crumbs: crumbs };
    var s = K.state;
    var org = K.inOrg();
    document.body.classList.toggle('org', org);
    app.innerHTML = header(false) + '<div class="shell"><aside class="rail">' + navHTML() + '</aside><main id="main" tabindex="-1">' +
      K.crumbs(crumbs) + body + '</main></div>' + (org ? '' : tabbarHTML()) + (s.more ? moreHTML() : '') +
      (s.menu ? '<div class="drawer" data-act="closeMenu"><div class="panel" role="dialog" aria-label="Меню" aria-modal="true"><div class="phead"><b>Меню</b>' +
        '<button class="x" type="button" data-act="closeMenu" aria-label="Закрыть меню">×</button></div>' + navHTML() + '</div></div>' : '');
    document.body.classList.toggle('menu-open', s.menu);
    if (s.menu) { var x = app.querySelector('.drawer .x'); if (x) x.focus(); }
  };
  K.rerender = function () { K.page(K.last.body, K.last.crumbs); };
  /* Экран до входа. */
  K.authPage = function (body) {
    app.innerHTML = header(true) + '<main id="main" tabindex="-1"><div class="auth stack" data-s="auth">' + body +
      '<p class="small muted"><a href="/ru/">← Сайт лиги</a></p></div></main>';
  };
  K.loading = function () {
    K.page('<div class="stack" aria-busy="true"><div class="skel" data-s="w40"></div><div class="skel" data-s="h120"></div><div class="skel"></div><div class="skel" data-s="w70"></div></div>', K.last.crumbs);
  };
  K.failed = function (res, crumbs) {
    K.page('<div class="note bad"><b>' + esc(K.errorText(res)) + '</b></div><div class="row"><button class="btn sec" type="button" data-act="reload">Повторить</button>' +
      '<button class="btn ghost" type="button" data-href="/">На главную</button></div>', crumbs);
  };
  /* Загрузить данные и показать страницу; при обрыве — понятная ошибка с «Повторить». */
  K.load = function (requests, draw, crumbs) {
    var stamp = K.route.stamp;
    K.loading();
    return Promise.all(requests.map(function (r) { return K.api('GET', r); })).then(function (res) {
      if (stamp !== K.route.stamp) return;
      for (var i = 0; i < res.length; i++) {
        if (res[i].status === 401) { K.route(); return; }
        if (!res[i].ok) { K.failed(res[i], crumbs); return; }
      }
      draw.apply(null, res.map(function (r) { return r.data; }));
    });
  };

  K.refreshUnread = function () {
    return K.api('GET', '/api/home').then(function (r) {
      if (r.ok) { K.state.home = r.data; if (r.data.unread !== K.state.unread) { K.state.unread = r.data.unread; } }
      return r;
    });
  };

  /* ---------- общие действия ---------- */
  K.actions.menu = function () { K.state.menu = true; K.rerender(); };
  K.actions.closeMenu = function (el, e) { if (e.target === el || el.classList.contains('x')) { K.state.menu = false; K.rerender(); } };
  K.actions.more = function () { K.state.more = true; K.rerender(); };
  K.actions.closeMore = function (el, e) { if (e.target === el) { K.state.more = false; K.rerender(); } };
  K.actions.reload = function () { K.route(); };
  // Сайт лиги — на том же адресе (facepaintingleague.com), кабинет — его раздел /kabinet/: вход при переходе не теряется
  K.actions.toSite = function () { location.href = '/ru/'; };
  K.actions.logout = function () {
    K.api('POST', '/web-auth/logout').then(function () { K.state.me = null; K.state.menu = false; K.state.more = false; K.go('/'); });
  };
  K.actions.showpw = function (b) { var i = b.parentNode.querySelector('input'); var s = i.type === 'password'; i.type = s ? 'text' : 'password'; b.textContent = s ? 'Скрыть' : 'Показать'; };

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-href],[data-act]');
    if (!el || !app.contains(el)) return;
    if (el.hasAttribute('data-act')) {
      var a = K.actions[el.getAttribute('data-act')];
      if (a) { if (el.tagName !== 'INPUT' && el.tagName !== 'LABEL') e.preventDefault(); a(el, e); }
      return;
    }
    e.preventDefault();
    K.go(el.getAttribute('data-href'));
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && (K.state.menu || K.state.more)) { K.state.menu = false; K.state.more = false; K.rerender(); }
    if (e.key === 'Escape' && K.onEscape) K.onEscape();
  });
  window.addEventListener('popstate', function () { K.route(); });

  /* ---------- вход и пароли (этап 1) ---------- */
  function minLen() { return (K.state.config && K.state.config.password_min_length) || 8; }
  function field(id, label, type, extra) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><input class="input" id="' + id + '" name="' + id + '" type="' + type + '" ' + (extra || '') + '></div>';
  }
  K.field = field;
  K.formError = function (form, text) {
    var el = form.querySelector('.form-err');
    el.textContent = text || ''; el.hidden = !text;
    if (text) el.focus();
  };
  K.busy = function (form, on) { Array.prototype.forEach.call(form.querySelectorAll('button, input, select, textarea'), function (b) { b.disabled = on; }); };
  function authError(res) {
    if (res.status === 401) return 'Неверный email или пароль. Проверьте раскладку.';
    if (res.status === 403 && res.detail === 'Invalid setup key') return 'Ключ сервера не подходит.';
    if (res.status === 409 && res.detail === 'An administrator already exists') return 'Администратор уже создан — войдите со своим email и паролем.';
    if (res.status === 409) return 'Этот email уже занят.';
    if (res.status === 400) return 'Ссылка уже использована или устарела. Если вы только что задали пароль — войдите с ним. Если нет — попросите у организатора новую ссылку.';
    if (res.status === 422) return 'Проверьте email (нужен вид name@mail.ru) и пароль — от ' + minLen() + ' до 128 символов.';
    if (res.status === 503 && res.detail === 'busy') return 'Сейчас в кабинет входит много людей. Подождите полминуты и нажмите ещё раз.';
    if (res.status === 503 && res.detail === 'Email delivery unavailable') return 'Отправка писем пока не настроена. Напишите организатору.';
    return K.errorText(res);
  }

  function loginView() {
    var mail = K.state.config && K.state.config.mail_delivery;
    K.authPage('<div class="stack"><span class="eyebrow">Face Painting League</span><h1>Вход в кабинет</h1>' +
      '<p class="small">Играете в Игре 01 и ещё не входили? <a href="' + ROOT + '/game01">Продолжить Игру в кабинете</a></p></div>' +
      '<form class="card" id="f-login" novalidate>' + field('email', 'Email', 'email', 'autocomplete="username" required') +
      '<div class="field"><label for="password">Пароль</label><div class="pw"><input class="input" id="password" name="password" type="password" autocomplete="current-password" required>' +
      '<button type="button" data-act="showpw">Показать</button></div></div>' +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Войти</button>' +
      (mail ? '<button class="btn ghost" type="button" id="to-reset">Не помню пароль</button>'
        : '<p class="small muted">Забыли пароль? <a href="/ru/feedback.html">Напишите организатору</a> (укажите email кабинета) — он пришлёт ссылку для нового пароля.</p>') + '</form>' +
      (K.state.config && K.state.config.signup ? '<div class="card"><b>Впервые в лиге?</b><p class="small muted">Заведите кабинет: имя, email и пароль. Играли в Игре 01 — нажмите «Продолжить Игру в кабинете» выше, чтобы сохранилась история.</p>' +
        '<button class="btn sec" type="button" id="to-signup">Зарегистрироваться</button></div>' : '') +
      (K.state.config && K.state.config.setup_needed ? '<div class="note info">Администратор ещё не создан. <a href="' + ROOT + '/setup" id="to-setup">Создать первого администратора</a></div>' : ''));
    var f = document.getElementById('f-login');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      var email = f.email.value.trim(), pw = f.password.value;
      if (!email || !pw) { K.formError(f, 'Введите email и пароль.'); return; }
      K.busy(f, true);
      K.api('POST', '/web-auth/login', { email: email, password: pw }).then(function (res) {
        K.busy(f, false);
        if (!res.ok) { K.formError(f, res.status === 422 ? 'Проверьте email — похоже, в нём опечатка (нужен вид name@mail.ru).' : authError(res)); return; }
        K.state.me = res.data; K.go(K.path() === '/' ? '/' : K.path() + location.search, true);
      });
    });
    var r = document.getElementById('to-reset');
    if (r) r.addEventListener('click', resetRequestView);
    var su = document.getElementById('to-signup');
    if (su) su.addEventListener('click', signupView);
    var s = document.getElementById('to-setup');
    if (s) s.addEventListener('click', function (e) { e.preventDefault(); K.go('/setup'); });
    f.email.focus();
  }

  function signupView() {
    K.authPage('<div class="stack"><span class="eyebrow">Face Painting League</span><h1>Регистрация</h1><p class="muted">Пароль — от ' + minLen() + ' до 128 символов. Имя и фамилия нужны для согласий и диплома.</p></div>' +
      '<form class="card" id="f-signup" novalidate>' + field('full_name', 'Имя и фамилия', 'text', 'autocomplete="name" required maxlength="200"') +
      field('email', 'Email', 'email', 'autocomplete="username" required') +
      field('password', 'Пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '" maxlength="128"') +
      field('password2', 'Пароль ещё раз', 'password', 'autocomplete="new-password" required maxlength="128"') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Зарегистрироваться</button>' +
      '<button class="btn ghost" type="button" id="back">У меня уже есть кабинет</button></form>');
    var f = document.getElementById('f-signup');
    document.getElementById('back').addEventListener('click', loginView);
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      if (!f.full_name.value.trim() || !f.email.value.trim()) { K.formError(f, 'Заполните имя и email.'); return; }
      if (f.password.value.length < minLen() || f.password.value.length > 128) { K.formError(f, 'Пароль должен содержать от ' + minLen() + ' до 128 символов.'); return; }
      if (f.password.value !== f.password2.value) { K.formError(f, 'Пароли не совпадают.'); return; }
      K.busy(f, true);
      K.api('POST', '/web-auth/register', { full_name: f.full_name.value.trim(), email: f.email.value.trim(), password: f.password.value }).then(function (res) {
        K.busy(f, false);
        if (!res.ok) { K.formError(f, res.detail && REASONS[res.detail] ? REASONS[res.detail] : authError(res)); return; }
        K.state.me = res.data; K.toast('Кабинет создан. Добро пожаловать!');
        K.refreshUnread().then(function () { K.go('/', true); });
      });
    });
    f.full_name.focus();
  }

  function inviteView() {
    var token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
    if (!token) {
      K.authPage('<div class="card"><h1>Вход по приглашению</h1><p>В ссылке нет кода. Скопируйте ссылку от организатора целиком.</p><a class="btn sec" href="' + ROOT + '/">Ко входу</a></div>');
      return;
    }
    K.authPage('<div class="card" aria-busy="true"><p class="muted">Проверяем ссылку…</p></div>');
    K.api('POST', '/web-auth/invite/check', { token: token }).then(function (res) {
      if (!res.ok) {
        var why = res.status === 0 ? 'Нет связи с сервером. Проверьте интернет и обновите страницу.'
          : res.status === 429 ? 'Сейчас по ссылкам входит много людей. Подождите 15 минут и откройте ссылку снова — она действует.'
          : res.status >= 500 ? 'Кабинет на минуту перезагружается. Обновите страницу чуть позже — ссылка действует.'
          : res.status === 422 ? 'Ссылка открылась не целиком. Скопируйте её из сообщения полностью.'
          : 'Ссылка устарела или уже использована. Если вы уже задали пароль — войдите с ним. Если нет — попросите у организатора новую.';
        K.authPage('<div class="card"><h1>Ссылка не работает</h1><p>' + why +
          '</p><a class="btn sec" href="' + ROOT + '/">Ко входу</a></div>');
        return;
      }
      var preset = res.data.email;
      K.authPage('<div class="stack"><span class="eyebrow">Face Painting League</span><h1>' + (res.data.name ? esc(res.data.name) + ', добро пожаловать' : 'Добро пожаловать') + '</h1>' +
        '<p class="muted">Это ваш аккаунт лиги — история Игр уже в нём. Укажите email и пароль: дальше вы будете входить с ними. Пароль — от ' + minLen() + ' до 128 символов.</p></div>' +
        '<form class="card" id="f-inv" novalidate>' + field('email', 'Email', 'email', 'autocomplete="username" required' + (preset ? ' value="' + esc(preset) + '" readonly' : '')) +
        field('password', 'Пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '" maxlength="128"') +
        field('password2', 'Пароль ещё раз', 'password', 'autocomplete="new-password" required maxlength="128"') +
        '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Войти в кабинет</button></form>');
      var f = document.getElementById('f-inv');
      f.addEventListener('submit', function (e) {
        e.preventDefault(); K.formError(f, '');
        if (!f.email.value.trim()) { K.formError(f, 'Укажите email.'); return; }
        if (f.password.value.length < minLen() || f.password.value.length > 128) { K.formError(f, 'Пароль должен содержать от ' + minLen() + ' до 128 символов.'); return; }
        if (f.password.value !== f.password2.value) { K.formError(f, 'Пароли не совпадают.'); return; }
        K.busy(f, true);
        K.api('POST', '/web-auth/invite', { token: token, email: f.email.value.trim(), password: f.password.value }).then(function (r) {
          K.busy(f, false);
          if (!r.ok) { K.formError(f, r.detail && REASONS[r.detail] ? REASONS[r.detail] : authError(r)); return; }
          history.replaceState(null, '', ROOT + '/');   // код из ссылки больше не нужен в адресе
          K.state.me = r.data; K.toast('Готово! Вы в кабинете.');
          K.refreshUnread().then(function () { K.route(); });
        });
      });
      (preset ? f.password : f.email).focus();
    });
  }

  // Участницы Игры 01 из бота: заявка на вход (организатор находит её в перенесённом списке и подтверждает).
  K.COUNTRIES = [['RU', 'Россия'], ['BY', 'Беларусь'], ['KZ', 'Казахстан'], ['AM', 'Армения'], ['GE', 'Грузия'], ['AZ', 'Азербайджан'], ['KG', 'Кыргызстан'],
    ['UZ', 'Узбекистан'], ['RS', 'Сербия'], ['ME', 'Черногория'], ['TR', 'Турция'], ['AE', 'ОАЭ'], ['IL', 'Израиль'], ['DE', 'Германия'], ['CY', 'Кипр'],
    ['TH', 'Таиланд'], ['UA', 'Украина'], ['MD', 'Молдова'], ['LV', 'Латвия'], ['LT', 'Литва'], ['EE', 'Эстония'], ['PL', 'Польша'], ['FI', 'Финляндия'],
    ['ES', 'Испания'], ['IT', 'Италия'], ['FR', 'Франция'], ['GB', 'Великобритания'], ['US', 'США'], ['CA', 'Канада'], ['ID', 'Индонезия'], ['VN', 'Вьетнам']];
  var CLAIM_ERR = {
    email_taken: 'Этот email уже есть в кабинете. Войдите с ним — или напишите организатору, если не помните пароль.',
    claim_pending: 'Заявка с этим email уже отправлена — организатор её проверяет. Повторять не нужно.',
    claims_closed: 'Сейчас заявки не принимаются. Напишите организатору.',
    consents_required: 'Отметьте согласия — без них участвовать нельзя.', adult_required: 'Участие — с 18 лет.',
    name_required: 'Укажите ФИО и город.'
  };
  function docBox(d, label) {
    if (!d) return esc(label);
    return '<details class="doc-inline"><summary>' + esc(label) + '</summary><div class="small" data-s="pre">' + esc(d.body || '') + '</div></details>';
  }
  function game01View() {
    if (K.state.me) {
      K.authPage('<div class="card"><h1>Вы уже в кабинете</h1><p>Вы вошли как ' + esc(K.state.me.email || '') + '. Игра — в разделе «Мои Игры».</p>' +
        '<a class="btn" href="' + ROOT + '/">В кабинет</a></div>');
      return;
    }
    K.authPage('<div class="card" aria-busy="true"><p class="muted">Загружаем…</p></div>');
    K.api('GET', '/api/public/claims/config').then(function (res) {
      if (!res.ok || !res.data.open) {
        K.authPage('<div class="card"><h1>Заявки сейчас не принимаются</h1><p>Если вы участвуете в Игре и не можете войти — напишите организатору.</p>' +
          '<a class="btn sec" href="/ru/feedback.html">Написать организатору</a> <a class="btn ghost" href="' + ROOT + '/">Ко входу</a></div>');
        return;
      }
      var c = res.data, docs = c.documents || {};
      K.authPage('<div class="stack"><span class="eyebrow">Face Painting League · ' + esc(c.game) + '</span><h1>Продолжить Игру в кабинете</h1>' +
        '<p class="muted">Бот лиги временно не работает, поэтому ' + esc(c.game) + ' продолжается здесь — с 3 тура. Ваши баллы туров 1–2, лига и рейтинг уже перенесены. ' +
        'Заполните форму: организатор найдёт вас в списке участниц и откроет вход — обычно в течение дня. Потом входите с этим email и паролем.</p></div>' +
        '<form class="card" id="f-claim" novalidate>' +
        field('full_name', 'Фамилия, имя, отчество — как в боте', 'text', 'autocomplete="name" required maxlength="200"') +
        field('email', 'Email', 'email', 'autocomplete="username" required') +
        field('password', 'Придумайте пароль (от ' + minLen() + ' символов)', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '" maxlength="128"') +
        field('password2', 'Пароль ещё раз', 'password', 'autocomplete="new-password" required maxlength="128"') +
        '<div class="field"><label for="country">Страна</label><select class="input" id="country" name="country"><option value="">Выберите страну</option>' +
        K.COUNTRIES.map(function (x) { return '<option value="' + x[0] + '">' + x[1] + '</option>'; }).join('') + '</select></div>' +
        field('city', 'Город', 'text', 'autocomplete="address-level2" required maxlength="120"') +
        field('contact', 'Telegram или VK (необязательно) — поможет быстрее вас найти', 'text', 'maxlength="200" placeholder="@username или ссылка"') +
        '<label class="chk"><input type="checkbox" id="c-rules"> <span>Принимаю Правила лиги' + (docs.rules ? ' (редакция ' + esc(docs.rules.version) + ')' : '') + '</span></label>' + docBox(docs.rules, 'Прочитать Правила') +
        '<label class="chk"><input type="checkbox" id="c-pub"> <span>Даю согласие на публикацию моих работ на сайте и в соцсетях лиги</span></label>' + docBox(docs.publication, 'Прочитать согласие') +
        '<label class="chk"><input type="checkbox" id="c-pd"> <span>Даю согласие на обработку персональных данных</span></label>' + docBox(docs.personal_data, 'Прочитать согласие') +
        '<label class="chk"><input type="checkbox" id="c-adult"> <span>Мне есть 18 лет</span></label>' +
        '<div class="sr" aria-hidden="true"><label for="website">Не заполняйте</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>' +
        '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Отправить заявку</button>' +
        '<a class="btn ghost wide" href="' + ROOT + '/">У меня уже есть вход</a></form>');
      var f = document.getElementById('f-claim');
      f.addEventListener('submit', function (e) {
        e.preventDefault(); K.formError(f, '');
        var name = f.full_name.value.trim(), email = f.email.value.trim(), city = f.city.value.trim(), country = f.country.value;
        if (name.split(/\s+/).length < 2) { K.formError(f, 'Укажите фамилию и имя — как в боте.'); return; }
        if (!email) { K.formError(f, 'Укажите email.'); return; }
        if (f.password.value.length < minLen() || f.password.value.length > 128) { K.formError(f, 'Пароль должен содержать от ' + minLen() + ' до 128 символов.'); return; }
        if (f.password.value !== f.password2.value) { K.formError(f, 'Пароли не совпадают.'); return; }
        if (!country || !city) { K.formError(f, 'Укажите страну и город.'); return; }
        var ok = ['c-rules', 'c-pub', 'c-pd'].every(function (id) { return document.getElementById(id).checked; });
        if (!ok) { K.formError(f, 'Отметьте согласия — без них участвовать нельзя.'); return; }
        if (!document.getElementById('c-adult').checked) { K.formError(f, 'Участие — с 18 лет.'); return; }
        K.busy(f, true);
        K.api('POST', '/api/public/claims', { full_name: name, email: email, password: f.password.value, country_code: country, city: city,
          contact: f.contact.value.trim() || null, accept_rules: true, accept_publication: true, accept_personal_data: true, confirm_adult: true,
          website: f.website.value || null }).then(function (r) {
          K.busy(f, false);
          if (!r.ok) {
            K.formError(f, CLAIM_ERR[r.detail] || (r.status === 429 ? 'Слишком много заявок с этого адреса. Попробуйте через час.' :
              r.status === 422 ? 'Проверьте email (нужен вид name@mail.ru) и пароль — от ' + minLen() + ' до 128 символов.' : authError(r)));
            return;
          }
          K.authPage('<div class="card"><h1>Заявка № ' + esc(String(r.data.claim_no)) + ' отправлена</h1>' +
            '<div class="note info">Организатор проверит её и откроет вход — обычно в течение дня. Потом войдите с email <b>' + esc(email) + '</b> и вашим паролем.</div>' +
            '<p class="small muted">Не получается войти больше суток — напишите организатору и укажите номер заявки.</p>' +
            '<a class="btn sec" href="' + ROOT + '/">Ко входу</a></div>');
        });
      });
      f.full_name.focus();
    });
  }

  function resetRequestView() {
    K.authPage('<div class="stack"><h1>Восстановление доступа</h1><p class="muted">Укажите email, с которым вы входите. Пришлём ссылку для нового пароля.</p></div>' +
      '<form class="card" id="f-reset" novalidate>' + field('email', 'Email', 'email', 'autocomplete="username" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Получить ссылку</button>' +
      '<button class="btn ghost" type="button" id="back">Ко входу</button></form>');
    var f = document.getElementById('f-reset');
    document.getElementById('back').addEventListener('click', loginView);
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      if (!f.email.value.trim()) { K.formError(f, 'Введите email, с которым вы входите в кабинет.'); return; }
      K.busy(f, true);
      K.api('POST', '/auth/password/reset-request', { email: f.email.value.trim() }).then(function (res) {
        K.busy(f, false);
        if (!res.ok) { K.formError(f, authError(res)); return; }
        K.authPage('<div class="card"><h1>Проверьте почту</h1><div class="note info">Если такой email есть в лиге, на него придёт ссылка для нового пароля. Ссылка действует 30 минут и работает один раз.</div>' +
          '<button class="btn sec" type="button" id="back">Ко входу</button></div>');
        document.getElementById('back').addEventListener('click', loginView);
      });
    });
  }

  function setPasswordView(kind) {
    var params = new URLSearchParams(location.hash.slice(1));
    var token = params.get('token') || '';
    if (params.get('type') === 'reset_password') kind = 'reset';
    var title = kind === 'set' ? 'Активация кабинета' : 'Новый пароль';
    if (!token) {
      K.authPage('<div class="card"><h1>' + title + '</h1><p>В ссылке нет кода. Откройте ссылку из письма целиком или попросите новую у организатора.</p><a class="btn sec" href="' + ROOT + '/">Ко входу</a></div>');
      return;
    }
    K.authPage('<div class="stack"><h1>' + title + '</h1><p class="muted">' + (kind === 'set' ? 'Это ваш аккаунт лиги: история Игр уже в нём. Осталось задать пароль. ' : 'После сохранения прежние входы на других устройствах завершатся. ') +
      'Пароль — от ' + minLen() + ' до 128 символов.</p></div>' +
      '<form class="card" id="f-pw" novalidate>' + field('password', 'Новый пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '" maxlength="128"') +
      field('password2', 'Повторите пароль', 'password', 'autocomplete="new-password" required maxlength="128"') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Сохранить пароль</button></form>');
    var f = document.getElementById('f-pw');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      if (f.password.value.length < minLen() || f.password.value.length > 128) { K.formError(f, 'Пароль должен содержать от ' + minLen() + ' до 128 символов.'); return; }
      if (f.password.value !== f.password2.value) { K.formError(f, 'Пароли не совпадают.'); return; }
      K.busy(f, true);
      K.api('POST', kind === 'set' ? '/auth/password/set' : '/auth/password/reset', { token: token, password: f.password.value }).then(function (res) {
        K.busy(f, false);
        if (!res.ok) { K.formError(f, authError(res)); return; }
        history.replaceState(null, '', ROOT + '/');  // код из ссылки больше не нужен в адресе
        K.toast('Пароль сохранён. Войдите с новым паролем.');
        loginView();
      });
    });
  }

  function setupView() {
    if (!K.state.config || !K.state.config.setup_needed) { K.go('/', true); return; }
    K.authPage('<div class="stack"><h1>Первый администратор</h1><p class="muted">Нужен один раз. Ключ сервера — тот же, что вы вводили на странице копий базы (ключ приёмника данных).</p></div>' +
      '<form class="card" id="f-setup" novalidate>' + field('key', 'Ключ сервера', 'password', 'autocomplete="off" required') +
      field('full_name', 'Имя и фамилия', 'text', 'autocomplete="name" required maxlength="200"') + field('email', 'Email для входа', 'email', 'autocomplete="username" required') +
      field('password', 'Пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '"') + field('password2', 'Пароль ещё раз', 'password', 'autocomplete="new-password" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn wide" type="submit">Создать администратора</button></form>');
    var f = document.getElementById('f-setup');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); K.formError(f, '');
      if (!f.key.value || !f.full_name.value.trim() || !f.email.value.trim()) { K.formError(f, 'Заполните все поля.'); return; }
      if (f.password.value.length < minLen()) { K.formError(f, 'Пароль — не короче ' + minLen() + ' символов.'); return; }
      if (f.password.value !== f.password2.value) { K.formError(f, 'Пароли не совпадают.'); return; }
      K.busy(f, true);
      K.api('POST', '/web-auth/setup', { key: f.key.value, full_name: f.full_name.value.trim(), email: f.email.value.trim(), password: f.password.value }).then(function (res) {
        K.busy(f, false);
        if (!res.ok) { K.formError(f, authError(res)); return; }
        K.state.me = res.data; K.state.config.setup_needed = false;
        K.toast('Администратор создан.');
        K.go('/', true);
      });
    });
    f.key.focus();
  }

  // Сервер не ответил или перезапускается — не показывать форму входа вошедшей участнице
  function unavailableView() {
    K.authPage('<div class="card"><h1>Кабинет временно недоступен</h1><p>Сервер не ответил — обычно это минута. Проверьте интернет и нажмите «Повторить».</p>' +
      '<button class="btn" type="button" id="retry">Повторить</button></div>');
    document.getElementById('retry').addEventListener('click', function () { K.start(); });
  }

  /* ---------- маршрутизатор ---------- */
  K.route = function () {
    K.route.stamp = (K.route.stamp || 0) + 1;
    K.onEscape = null;
    var p = K.path();
    if (p === '/auth/set-password') return setPasswordView('set');
    if (p === '/auth/reset-password') return setPasswordView('reset');
    if (p === '/setup') return setupView();
    if (p === '/auth/invite') return inviteView();
    if (p === '/game01') return game01View();
    if (!K.state.me) {
      // Проверить сессию заново (например, после 401) и показать вход.
      return K.api('GET', '/web-auth/me').then(function (r) {
        if (r.ok) { K.state.me = r.data; K.route(); } else if (r.status === 401) { loginView(); } else { unavailableView(); }
      });
    }
    for (var i = 0; i < K.routes.length; i++) {
      var m = p.match(K.routes[i][0]);
      if (m) { K.routes[i][1].apply(null, m.slice(1)); return; }
    }
    K.page('<h1>Страница не найдена</h1><p class="muted">Возможно, ссылка устарела.</p><button class="btn sec" type="button" data-href="/">На главную</button>');
  };

  K.start = function () {
    Promise.all([K.api('GET', '/web-auth/config'), K.api('GET', '/web-auth/me')]).then(function (r) {
      if (r[0].status === 0) {
        K.authPage('<div class="card"><h1>Нет связи</h1><p>Сервер кабинета не отвечает. Попробуйте обновить страницу через минуту.</p></div>');
        return;
      }
      K.state.config = r[0].ok ? r[0].data : { password_min_length: 12, mail_delivery: false, setup_needed: false };
      if (K.state.config.is_test && !document.querySelector('.test-band')) {
        document.body.insertAdjacentHTML('afterbegin', '<div class="test-band" role="note">Тестовый кабинет — репетиция. Данные здесь не настоящие и будут удалены.</div>');
      }
      K.state.me = r[1].ok ? r[1].data : null;
      if (!r[1].ok && r[1].status !== 401) { unavailableView(); return; }
      if (K.state.me) K.refreshUnread().then(K.route); else K.route();
    });
  };
})();
