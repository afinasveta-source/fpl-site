/* Кабинет организатора: заказы аудиоразбора от судьи (решение 13.10).
   Заказ приходит формой с сайта → организатор присылает ссылку на оплату → «оплачено» → находит человека в кабинете
   → загружает аудио (и, если есть, текст) → «Разбор готов» — участница слушает его в кабинете. */
(function () {
  'use strict';
  var K = window.K, O = K.org, esc = K.esc, pill = K.pill, li = K.li;
  var ST = { 'new': ['Новый заказ', 'acc'], payment_sent: ['Ждём оплату', 'info'], paid: ['Оплачен — записать разбор', 'warn'],
    done: ['Готов', 'ok'], cancelled: ['Отменён', 'plain'] };
  var STEP = { payment_sent: 'Ссылка на оплату отправлена', paid: 'Оплачено', cancelled: 'Отменить заказ', 'new': 'Вернуть в новые' };
  O.addText({ not_paid: 'Сначала отметьте оплату.', no_review: 'Загрузите аудио или впишите текст разбора.',
    no_person: 'Найдите и выберите человека в кабинете — разбор появится у неё в «Моих разборах».', unknown_person: 'Такого человека нет.',
    audio_format: 'Нужен аудиофайл: m4a, mp3, ogg, opus, wav или webm.', already_done: 'Разбор уже отправлен.' });
  function what(o) { return o.scope === 'all' ? 'Все работы Игры' : 'Работа тура ' + o.round_no; }

  O.on(/^\/org\/reviews$/, function () {
    var status = K.query().get('status') || 'open';
    K.load(['/api/org/reviews?status=' + encodeURIComponent(status)], function (d) {
      var c = d.counts, open = (c['new'] || 0) + (c.payment_sent || 0) + (c.paid || 0), of = d.offer;
      var h = '<h1>Разборы от судьи</h1><p class="small muted">Заказы с сайта (страница «Разбор от судьи»). Сейчас: ' + esc(of.reviewer) +
        ', одна работа — ' + of.price_one + ' ₽, все работы Игры — ' + of.price_all + ' ₽' + (of.enabled ? '' : ' · <b>заказ на сайте сейчас закрыт</b> (нет идущей Игры)') + '.</p>' +
        '<nav class="row tabs" aria-label="Фильтр">' + [['open', 'В работе', open], ['done', 'Готовы', c.done || 0], ['cancelled', 'Отменены', c.cancelled || 0], ['all', 'Все', null]].map(function (t) {
          return '<button class="btn ' + (t[0] === status ? '' : 'sec') + ' small" type="button" data-href="/org/reviews' + (t[0] === 'open' ? '' : '?status=' + t[0]) + '"' +
            (t[0] === status ? ' aria-current="page"' : '') + '>' + t[1] + (t[2] != null ? ' · ' + t[2] : '') + '</button>';
        }).join('') + '</nav>';
      h += d.items.length ? '<section class="card"><div class="list">' + d.items.map(function (o) {
        return li('№ ' + o.no + ' · ' + esc(o.name), esc(what(o) + ' · ' + o.price + ' ₽ · ' + o.contact + ' · ' + O.when(o.created_at)), O.st(ST, o.status), '/org/reviews/' + o.no);
      }).join('') + '</div></section>' : '<div class="note">Заказов нет.</div>';
      K.page(h, [['Обзор', '/org'], ['Разборы']]);
    }, [['Обзор', '/org'], ['Разборы']]);
  });

  O.on(/^\/org\/reviews\/(\d+)$/, function (no) {
    K.load(['/api/org/reviews/' + no], function (o) { O.review = o; draw(o); }, [['Обзор', '/org'], ['Разборы', '/org/reviews'], ['Заказ']]);
  });

  function draw(o) {
    var closed = o.status === 'done' || o.status === 'cancelled';
    var h = '<div class="between"><h1>Заказ № ' + o.no + '</h1>' + O.st(ST, o.status) + '</div>' +
      '<section class="card"><dl class="kv"><dt>Кто</dt><dd>' + esc(o.name) + '</dd><dt>Контакт</dt><dd>' + esc(o.contact) + '</dd>' +
      '<dt>Что</dt><dd>' + esc(what(o)) + (o.game ? ' · ' + esc(o.game) : '') + '</dd><dt>Цена</dt><dd>' + o.price + ' ₽</dd><dt>Судья</dt><dd>' + esc(o.reviewer) + '</dd>' +
      '<dt>Заказ</dt><dd>' + esc(O.when(o.created_at)) + '</dd>' + (o.paid_at ? '<dt>Оплачен</dt><dd>' + esc(O.when(o.paid_at)) + '</dd>' : '') +
      (o.done_at ? '<dt>Отправлен</dt><dd>' + esc(O.when(o.done_at)) + '</dd>' : '') + '</dl>' +
      (o.comment ? '<p class="small"><b>Пожелание к разбору:</b> ' + esc(o.comment) + '</p>' : '') + '</section>';
    if (o.next.length) {
      h += '<section class="card"><h2>Статус</h2><div class="row">' + o.next.map(function (s) {
        return '<button class="btn ' + (s === 'cancelled' ? 'ghost' : s === 'new' ? 'ghost' : 'sec') + ' small" type="button" data-act="rvStatus" data-st="' + s + '">' + STEP[s] + '</button>';
      }).join('') + '</div><p class="small muted">Ссылку на оплату вы отправляете сами (Telegram, почта) — здесь только отметка.</p></section>';
    }
    // кому отправить: человек в кабинете
    h += '<section class="card"><h2>Участница в кабинете</h2>' + (o.person ? '<p><b>' + esc(o.person.name || '') + '</b> · ' + esc(o.person.email || 'без email') +
      ' <button class="lnk" type="button" data-href="/org/people/' + o.person.id + '">карточка</button></p>' +
      (closed ? '' : '<button class="btn ghost small" type="button" data-act="rvUnlink">Выбрать другого человека</button>') :
      '<p class="small muted">Найдите её по имени, email или Telegram ID. Если её ещё нет в кабинете — «Люди» → «Добавить человека», затем ссылка-приглашение.</p>' +
      '<form class="search" id="rv-find"><label class="sr" for="rv-q">Поиск</label><input class="input" id="rv-q" type="search" maxlength="100" value="' + esc(o.contact.indexOf('@') > 0 && o.contact.charAt(0) !== '@' ? o.contact : o.name.split(/\s+/).pop()) + '"><button class="btn sec" type="submit">Найти</button></form><div id="rv-found"></div>') +
      '</section>';
    // разбор
    if (o.status !== 'cancelled') {
      h += '<section class="card"><h2>Разбор</h2>' +
        (o.has_audio ? '<audio controls preload="metadata" src="' + K.ROOT + '/api/org/reviews/' + o.no + '/audio" class="wide"></audio><p class="small muted">Аудио загружено' + (o.audio_bytes ? ' (' + Math.round(o.audio_bytes / 1024 / 1024 * 10) / 10 + ' МБ)' : '') + '.</p>' : '') +
        (o.status === 'done' ? '' : '<label class="btn sec" for="rv-audio">' + (o.has_audio ? 'Заменить аудио' : 'Загрузить аудио') + '</label><input class="sr" id="rv-audio" type="file" accept="audio/*,.m4a,.mp3,.ogg,.opus,.wav">' +
          '<p class="small muted">Лучше m4a (Диктофон на iPhone) или mp3 — до 40 МБ. Голосовые Telegram (.ogg) на старых iPhone могут не играть.</p>') +
        '<div class="field"><label for="rv-text">Текст разбора (необязательно — если есть расшифровка)</label><textarea class="input" id="rv-text" rows="6" maxlength="20000"' + (o.status === 'done' ? ' readonly' : '') + '>' + esc(o.review_text || '') + '</textarea></div>' +
        (o.status === 'done' ? '' : '<button class="btn ghost small" type="button" data-act="rvSaveText">Сохранить текст</button>') + '</section>';
    }
    h += '<section class="card"><div class="field"><label for="rv-note">Заметка организатора (участница не видит)</label><textarea class="input" id="rv-note" rows="2" maxlength="2000">' + esc(o.org_note || '') + '</textarea></div>' +
      '<button class="btn ghost small" type="button" data-act="rvSaveNote">Сохранить заметку</button></section>';
    if (o.status === 'paid') {
      var ready = (o.has_audio || o.has_text) && o.person;
      h += '<div class="actbar"><button class="btn wide" type="button" data-act="rvDone"' + (ready ? '' : ' disabled') + '>Разбор готов — отправить участнице</button></div>' +
        (ready ? '' : '<p class="small muted">Чтобы отправить: загрузите аудио (или текст) и выберите участницу.</p>');
    }
    K.page(h, [['Обзор', '/org'], ['Разборы', '/org/reviews'], ['№ ' + o.no]]);
    var f = document.getElementById('rv-find');
    if (f) {
      f.addEventListener('submit', function (e) { e.preventDefault(); find(document.getElementById('rv-q').value.trim()); });
      find(document.getElementById('rv-q').value.trim());
    }
    var a = document.getElementById('rv-audio');
    if (a) a.addEventListener('change', upload);
  }

  function find(term) {
    var box = document.getElementById('rv-found');
    if (!box || !term) return;
    K.api('GET', '/api/org/people?q=' + encodeURIComponent(term) + '&limit=10').then(function (r) {
      if (!r.ok) { box.innerHTML = '<p class="small">' + esc(O.err(r)) + '</p>'; return; }
      box.innerHTML = r.data.people.length ? '<div class="list">' + r.data.people.map(function (p) {
        return '<button class="li" type="button" data-act="rvLink" data-id="' + p.id + '"><span class="t">' + esc(p.name || 'Без имени') + '</span><span class="s">' +
          esc([p.email || 'без email', p.city].filter(Boolean).join(' · ')) + '</span><span class="r">Выбрать</span></button>';
      }).join('') + '</div>' : '<p class="small muted">Никого не нашлось — попробуйте фамилию или email.</p>';
    });
  }
  function save(body, msg) {
    O.send('PATCH', '/api/org/reviews/' + O.review.no, body, null, function (o) { O.review = o; K.toast(msg); O.refreshCounts(); draw(o); });
  }
  K.actions.rvStatus = function (b) {
    var st = b.getAttribute('data-st');
    if (st === 'cancelled') {
      O.confirm({ title: 'Отменить заказ № ' + O.review.no + '?', text: 'Если оплата уже пришла — верните её сами.', ok: 'Отменить заказ', danger: true,
        method: 'PATCH', path: '/api/org/reviews/' + O.review.no, body: function () { return { status: 'cancelled' }; }, done: function () { K.toast('Заказ отменён'); K.route(); } });
      return;
    }
    save({ status: st }, STEP[st]);
  };
  K.actions.rvLink = function (b) { save({ user_id: b.getAttribute('data-id') }, 'Участница выбрана'); };
  K.actions.rvUnlink = function () { save({ unlink: true }, 'Выберите другого человека'); };
  K.actions.rvSaveText = function () { save({ review_text: document.getElementById('rv-text').value }, 'Текст сохранён'); };
  K.actions.rvSaveNote = function () { save({ org_note: document.getElementById('rv-note').value }, 'Заметка сохранена'); };
  K.actions.rvDone = function (b) {
    b.disabled = true;
    O.send('POST', '/api/org/reviews/' + O.review.no + '/done', undefined, null, function (o) { O.review = o; K.toast('Разбор отправлен участнице'); O.refreshCounts(); draw(o); });
    setTimeout(function () { b.disabled = false; }, 3000);
  };
  var AUDIO = { m4a: 'audio/mp4', mp3: 'audio/mpeg', ogg: 'audio/ogg', oga: 'audio/ogg', opus: 'audio/ogg', wav: 'audio/wav', webm: 'audio/webm', aac: 'audio/aac' };
  function upload(e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    var ext = (file.name.split('.').pop() || '').toLowerCase();
    var type = AUDIO[ext] || (file.type && file.type.indexOf('audio/') === 0 ? file.type : '');
    if (!type) { K.toast(O.err({ detail: 'audio_format' })); return; }
    if (file.size > 40 * 1024 * 1024) { K.toast('Файл больше 40 МБ.'); return; }
    var lbl = document.querySelector('label[for="rv-audio"]');
    if (lbl) lbl.textContent = 'Загружаем…';
    K.api('POST', '/api/org/reviews/' + O.review.no + '/audio', undefined, { body: file, type: type }).then(function (r) {
      if (!r.ok) { K.toast(O.err(r)); draw(O.review); return; }
      O.review = r.data; K.toast('Аудио загружено'); draw(r.data);
    });
  }
})();
