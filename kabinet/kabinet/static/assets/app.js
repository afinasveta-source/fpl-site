/* Кабинет FPL — этап 1: вход, первый администратор, установка и сброс пароля, профиль, роли. */
(function () {
  'use strict';
  var ROOT = document.body.getAttribute('data-root') || '';
  var app = document.getElementById('app');
  var ctx = document.getElementById('ctx');
  var state = { config: null, me: null };
  var ROLE = { admin: 'Администратор', moderator: 'Модератор', judge: 'Судья', participant: 'Участник' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function api(method, path, body) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(ROOT + path, opts).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
        return { status: r.status, ok: r.ok, data: data };
      });
    }, function () { return { status: 0, ok: false, data: null }; });
  }

  function errorText(res, context) {
    var d = res.data && res.data.detail;
    if (res.status === 0) return 'Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.';
    if (res.status === 429) return 'Слишком много попыток. Попробуйте через 15 минут.';
    if (res.status === 401) return context === 'login' ? 'Неверный email или пароль.' : 'Войдите заново.';
    if (res.status === 403 && d === 'Invalid setup key') return 'Ключ сервера не подходит.';
    if (res.status === 403) return 'Действие недоступно. Обновите страницу и попробуйте ещё раз.';
    if (res.status === 409 && d === 'An administrator already exists') return 'Администратор уже создан — войдите со своим email и паролем.';
    if (res.status === 409) return 'Этот email уже занят.';
    if (res.status === 400) return 'Ссылка устарела или уже использована. Запросите новую.';
    if (res.status === 422) return 'Проверьте поля: email, пароль не короче ' + minLen() + ' символов.';
    if (res.status === 503) return 'Отправка писем пока не настроена. Напишите организатору.';
    return 'Что-то пошло не так (' + res.status + '). Попробуйте ещё раз.';
  }

  function minLen() { return (state.config && state.config.password_min_length) || 12; }

  function toast(text) {
    var t = document.getElementById('toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.hidden = true; }, 3500);
  }

  function render(html) { app.innerHTML = html; var h = app.querySelector('h1'); if (h) { h.tabIndex = -1; } }

  function field(id, label, type, extra) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><input class="input" id="' + id + '" name="' + id +
      '" type="' + type + '" ' + (extra || '') + '></div>';
  }

  function formError(form, text) {
    var el = form.querySelector('.form-err');
    el.textContent = text || ''; el.hidden = !text;
    if (text) el.focus();
  }

  function busy(form, on) {
    Array.prototype.forEach.call(form.querySelectorAll('button, input'), function (b) { b.disabled = on; });
  }

  function path() {
    var p = location.pathname;
    return ROOT && p.indexOf(ROOT) === 0 ? p.slice(ROOT.length) || '/' : p;
  }

  function go(p) { history.pushState(null, '', ROOT + p); route(); }

  /* ---------- экраны ---------- */

  function loginView() {
    ctx.textContent = 'Вход';
    var mail = state.config && state.config.mail_delivery;
    render('<div class="stack"><h1>Вход в кабинет</h1><p class="muted">Кабинет Face Painting League. Сейчас идёт закрытая проверка.</p></div>' +
      '<form class="card" id="f-login" novalidate>' +
      field('email', 'Email', 'email', 'autocomplete="username" required') +
      field('password', 'Пароль', 'password', 'autocomplete="current-password" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p>' +
      '<button class="btn" type="submit">Войти</button>' +
      (mail ? '<button class="lnk" type="button" id="to-reset">Забыли пароль?</button>'
            : '<p class="small muted">Забыли пароль? Напишите организатору — он пришлёт ссылку для нового пароля.</p>') +
      '</form>' +
      (state.config && state.config.setup_needed ? '<div class="note info">Администратор ещё не создан. <a href="' + ROOT + '/setup" id="to-setup">Создать первого администратора</a></div>' : ''));
    var f = document.getElementById('f-login');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); formError(f, '');
      var email = f.email.value.trim(), pw = f.password.value;
      if (!email || !pw) { formError(f, 'Введите email и пароль.'); return; }
      busy(f, true);
      api('POST', '/web-auth/login', { email: email, password: pw }).then(function (res) {
        busy(f, false);
        if (!res.ok) { formError(f, errorText(res, 'login')); return; }
        state.me = res.data; go('/');
      });
    });
    var r = document.getElementById('to-reset');
    if (r) r.addEventListener('click', resetRequestView);
    var s = document.getElementById('to-setup');
    if (s) s.addEventListener('click', function (e) { e.preventDefault(); go('/setup'); });
    f.email.focus();
  }

  function resetRequestView() {
    ctx.textContent = 'Новый пароль';
    render('<div class="stack"><h1>Новый пароль</h1><p class="muted">Пришлём ссылку для нового пароля на email, с которым вы входите.</p></div>' +
      '<form class="card" id="f-reset" novalidate>' + field('email', 'Email', 'email', 'autocomplete="username" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn" type="submit">Прислать ссылку</button>' +
      '<button class="lnk" type="button" id="back">Назад ко входу</button></form>');
    var f = document.getElementById('f-reset');
    document.getElementById('back').addEventListener('click', loginView);
    f.addEventListener('submit', function (e) {
      e.preventDefault(); formError(f, '');
      busy(f, true);
      api('POST', '/auth/password/reset-request', { email: f.email.value.trim() }).then(function (res) {
        busy(f, false);
        if (!res.ok) { formError(f, errorText(res)); return; }
        render('<div class="card"><h1>Проверьте почту</h1><p>Если такой email есть в кабинете, письмо со ссылкой придёт в течение нескольких минут. Ссылка действует 30 минут.</p>' +
          '<button class="btn sec" type="button" id="back">Ко входу</button></div>');
        document.getElementById('back').addEventListener('click', loginView);
      });
    });
  }

  function setPasswordView(kind) {
    ctx.textContent = 'Пароль';
    var params = new URLSearchParams(location.hash.slice(1));
    var token = params.get('token') || '';
    if (params.get('type') === 'reset_password') kind = 'reset';
    var title = kind === 'set' ? 'Придумайте пароль' : 'Новый пароль';
    if (!token) {
      render('<div class="card"><h1>' + title + '</h1><p>В ссылке нет кода. Откройте ссылку из письма целиком или запросите новую.</p>' +
        '<a class="btn sec" href="' + ROOT + '/">Ко входу</a></div>');
      return;
    }
    render('<div class="stack"><h1>' + title + '</h1><p class="muted">Не короче ' + minLen() + ' символов. Пароль знаете только вы.</p></div>' +
      '<form class="card" id="f-pw" novalidate>' +
      field('password', 'Пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '"') +
      field('password2', 'Ещё раз', 'password', 'autocomplete="new-password" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn" type="submit">Сохранить пароль</button></form>');
    var f = document.getElementById('f-pw');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); formError(f, '');
      if (f.password.value.length < minLen()) { formError(f, 'Пароль — не короче ' + minLen() + ' символов.'); return; }
      if (f.password.value !== f.password2.value) { formError(f, 'Пароли не совпадают.'); return; }
      busy(f, true);
      api('POST', kind === 'set' ? '/auth/password/set' : '/auth/password/reset', { token: token, password: f.password.value }).then(function (res) {
        busy(f, false);
        if (!res.ok) { formError(f, errorText(res)); return; }
        history.replaceState(null, '', ROOT + '/');  // код из ссылки больше не нужен в адресе
        toast('Пароль сохранён. Войдите с новым паролем.');
        loginView();
      });
    });
  }

  function setupView() {
    ctx.textContent = 'Первый администратор';
    if (!state.config || !state.config.setup_needed) { go('/'); return; }
    render('<div class="stack"><h1>Первый администратор</h1><p class="muted">Нужен один раз. Ключ сервера — тот же, что вы вводили на странице копий базы (ключ приёмника данных).</p></div>' +
      '<form class="card" id="f-setup" novalidate>' +
      field('key', 'Ключ сервера', 'password', 'autocomplete="off" required') +
      field('full_name', 'Имя и фамилия', 'text', 'autocomplete="name" required maxlength="200"') +
      field('email', 'Email для входа', 'email', 'autocomplete="username" required') +
      field('password', 'Пароль', 'password', 'autocomplete="new-password" required minlength="' + minLen() + '"') +
      field('password2', 'Пароль ещё раз', 'password', 'autocomplete="new-password" required') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn" type="submit">Создать администратора</button></form>');
    var f = document.getElementById('f-setup');
    f.addEventListener('submit', function (e) {
      e.preventDefault(); formError(f, '');
      if (!f.key.value || !f.full_name.value.trim() || !f.email.value.trim()) { formError(f, 'Заполните все поля.'); return; }
      if (f.password.value.length < minLen()) { formError(f, 'Пароль — не короче ' + minLen() + ' символов.'); return; }
      if (f.password.value !== f.password2.value) { formError(f, 'Пароли не совпадают.'); return; }
      busy(f, true);
      api('POST', '/web-auth/setup', { key: f.key.value, full_name: f.full_name.value.trim(), email: f.email.value.trim(), password: f.password.value }).then(function (res) {
        busy(f, false);
        if (!res.ok) { formError(f, errorText(res)); return; }
        state.me = res.data; state.config.setup_needed = false;
        toast('Администратор создан.');
        go('/');
      });
    });
    f.key.focus();
  }

  function homeView() {
    var me = state.me;
    var name = me.display_name || me.full_name || me.email;
    ctx.textContent = name;
    var roles = me.roles.length ? me.roles.map(function (r) { return '<span class="pill ok">' + esc(ROLE[r] || r) + '</span>'; }).join(' ') : '<span class="pill">Роль не назначена</span>';
    render('<div class="stack"><span class="muted small">Здравствуйте</span><h1>' + esc(name) + '</h1><div class="row roles">' + roles + '</div></div>' +
      '<section class="card"><h2>Кабинет переносится по этапам</h2><p>Сейчас работают вход, пароль, профиль и роли. Следующими появятся Игры и задания, сдача работ, раздел организатора, судейство и итоги.</p></section>' +
      '<form class="card" id="f-profile" novalidate><h2>Профиль</h2>' +
      field('display_name', 'Публичное имя', 'text', 'maxlength="100" autocomplete="nickname"') +
      '<p class="small muted">Так вас видят в рейтинге и галерее. Если не указано — на дипломе будет полное имя.</p>' +
      field('full_name', 'Полное имя', 'text', 'maxlength="200" autocomplete="name"') +
      field('city', 'Город', 'text', 'maxlength="120" autocomplete="address-level2"') +
      '<p class="form-err" role="alert" tabindex="-1" hidden></p><button class="btn sec" type="submit">Сохранить</button></form>' +
      '<section class="card"><dl class="kv"><dt>Email</dt><dd>' + esc(me.email || '—') + '</dd></dl>' +
      '<button class="btn ghost" type="button" id="logout">Выйти</button></section>');
    var f = document.getElementById('f-profile');
    f.display_name.value = me.display_name || ''; f.full_name.value = me.full_name || ''; f.city.value = me.city || '';
    f.addEventListener('submit', function (e) {
      e.preventDefault(); formError(f, '');
      busy(f, true);
      api('PATCH', '/web-auth/profile', { display_name: f.display_name.value, full_name: f.full_name.value, city: f.city.value }).then(function (res) {
        busy(f, false);
        if (!res.ok) { formError(f, errorText(res)); return; }
        state.me = res.data; toast('Сохранено.'); homeView();
      });
    });
    document.getElementById('logout').addEventListener('click', function () {
      api('POST', '/web-auth/logout').then(function () { state.me = null; go('/'); });
    });
  }

  function route() {
    var p = path();
    if (p === '/auth/set-password') return setPasswordView('set');
    if (p === '/auth/reset-password') return setPasswordView('reset');
    if (p === '/setup') return setupView();
    if (state.me) return homeView();
    return loginView();
  }

  window.addEventListener('popstate', route);
  Promise.all([api('GET', '/web-auth/config'), api('GET', '/web-auth/me')]).then(function (r) {
    state.config = r[0].ok ? r[0].data : { password_min_length: 12, mail_delivery: false, setup_needed: false };
    state.me = r[1].ok ? r[1].data : null;
    if (r[0].status === 0) {
      render('<div class="card"><h1>Нет связи</h1><p>Сервер кабинета не отвечает. Попробуйте обновить страницу через минуту.</p></div>');
      return;
    }
    route();
  });
})();
