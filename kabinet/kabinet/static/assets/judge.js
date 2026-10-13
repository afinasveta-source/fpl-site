/* Кабинет судьи (этап 4): назначенные пулы, сравнение пар, оценки по критериям. Имён участниц судья не видит. */
(function () {
  'use strict';
  var K = window.K, esc = K.esc, pill = K.pill, li = K.li;
  var J = {};
  var LEAGUE = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
  var TEXT = { judging_closed: 'Итоги тура уже опубликованы — оценки не меняются.', regular_locked: 'Основное голосование закрыто — эти оценки уже не меняются.',
    all_criteria_required: 'Поставьте оценку по каждому критерию.', score_out_of_range: 'Оценка — целое число от 1 до 100.' };
  var err = function (r) {
    if (r.status === 404) return 'Эта пара или работа больше не в вашем пуле — организатор изменил судейство. Обновляем список.';
    return TEXT[r.detail] || K.errorText(r);
  };
  function poolName(s) { return s.league ? 'Лига ' + LEAGUE[s.league] : 'Общий пул'; }
  function bar(done, total) {
    var pct = total ? Math.round(done * 100 / total) : 0;
    return '<div class="jbar" role="progressbar" aria-valuemin="0" aria-valuemax="' + total + '" aria-valuenow="' + done + '" aria-label="Готово ' + done + ' из ' + total + '">' +
      '<span data-w="' + (Math.round(pct / 5) * 5) + '"></span></div>';
  }

  K.on(/^\/judging$/, function () {
    K.load(['/api/judging', '/api/judging/reviews'], function (d, rv) {
      var h = '<h1>Судейство</h1><p class="muted small">Работы показываются без имён. Оценки можно менять, пока организатор не опубликовал итоги тура.</p>';
      if (rv.items.length) {
        h += '<section class="card"><h2>Разборы работ</h2><p class="small muted">Платные аудиоразборы, которые вам поручил организатор.</p><div class="list">' + rv.items.map(function (o) {
          return li(esc('№ ' + o.no + ' · ' + o.name), esc((o.scope === 'all' ? 'Все работы Игры' : 'Работа тура ' + o.round_no) + (o.game ? ' · ' + o.game : '')),
            o.status === 'done' ? pill('Отправлен', 'ok') : pill('Записать', 'acc'), '/judging/reviews/' + o.no);
        }).join('') + '</div></section>';
      }
      if (!d.streams.length) h += '<div class="note">Сейчас вам не назначены работы. Когда организатор начнёт судейство тура, здесь появится пул и придёт уведомление.</div>';
      else h += '<section class="card"><div class="list">' + d.streams.map(function (s) {
        var left = s.total - s.done;
        var sub = [s.event, 'Тур ' + s.round_no + ' · ' + s.round_title, poolName(s), s.method === 'pairwise' ? 'сравнение пар' : 'оценки по критериям',
          s.deadline ? 'до ' + K.date(s.deadline) + ' МСК' : ''].filter(Boolean).join(' · ');
        var right = !s.open ? pill('Завершено', 'plain') : s.tie_break_pending ? pill('Переголосование', 'warn') : left ? pill('Осталось ' + left, 'acc') : pill('Готово', 'ok');
        return li(esc(s.event + ' · тур ' + s.round_no), esc(sub), right, '/judging/' + s.id);
      }).join('') + '</div></section>';
      K.page(h, [['Главная', '/'], ['Судейство']]);
    }, [['Главная', '/'], ['Судейство']]);
  });

  K.on(/^\/judging\/([0-9a-f-]{36})$/, function (id) {
    K.load(['/api/judging/streams/' + id], function (s) { J.s = s; draw(s); }, [['Судейство', '/judging'], ['Пул']]);
  });

  function taskBlock(s) {
    if (!s.task) return '';
    return '<details class="more card"><summary>Задание тура: ' + esc(s.task.title) + '</summary><p data-s="pre">' + esc(s.task.instructions || '') + '</p></details>';
  }
  function head(s) {
    return '<div class="stack" data-s="g6"><span class="eyebrow">' + esc(s.event + ' · Тур ' + s.round_no + ' · ' + poolName(s)) + '</span><h1>' + esc(s.round_title) + '</h1>' +
      '<p class="small muted">' + (s.deadline ? 'Оценить до ' + esc(K.date(s.deadline)) + ' МСК · ' : '') + 'готово ' + s.done + ' из ' + s.total + '</p>' + bar(s.done, s.total) + '</div>';
  }
  function photos(list, label) {
    if (!list.length) return '<div class="photo">Нет фото</div>';
    return list.map(function (p, i) {
      return '<a class="jphoto" href="' + esc(p.view_url) + '" target="_blank" rel="noopener"><img src="' + esc(p.view_url) + '" alt="' + esc(label) + (list.length > 1 ? ', фото ' + (i + 1) : '') + '"></a>';
    }).join('');
  }

  function draw(s) {
    var crumbs = [['Судейство', '/judging'], ['Тур ' + s.round_no + ' · ' + poolName(s)]];
    if (s.method === 'criteria') { drawCriteria(s, crumbs); return; }
    var h = head(s) + taskBlock(s);
    if (!s.open) h += '<div class="note">Итоги тура опубликованы — оценка завершена. Спасибо!</div>';
    else if (s.next) h += pairBlock(s.next);
    else if (s.locked_regular && s.done < s.total) {
      h += '<div class="note">Организатор закрыл основное голосование — оценивать больше не нужно. Спасибо!</div>';
    } else {
      h += '<div class="note ok"><b>Все пары оценены.</b> Можно проверить и изменить голоса ниже, пока организатор не опубликовал итоги.</div>';
    }
    if (s.voted.length) {
      h += '<details class="more card"><summary>Ваши голоса · ' + s.voted.length + '</summary>' + (s.locked_regular ? '<p class="small muted">Идёт переголосование: основные голоса больше не меняются.</p>' : '') +
        '<div class="list">' + s.voted.slice().reverse().map(function (v) {
          var win = v[v.winner], lose = v[v.winner === 'a' ? 'b' : 'a'];
          var can = s.open && !(s.locked_regular && v.phase === 'regular');
          return '<div class="li static jvoted"><span class="t">№ ' + win.no + ' сильнее № ' + lose.no + (v.phase === 'tie_break' ? ' · переголосование' : '') + '</span>' +
            '<span class="s jthumbs">' + thumb(v.a, v.winner === 'a') + thumb(v.b, v.winner === 'b') + '</span>' +
            (can ? '<span class="r"><button class="btn ghost small" type="button" data-act="jVote" data-id="' + v.id + '" data-w="' + (v.winner === 'a' ? 'b' : 'a') + '">Поменять</button></span>' : '') + '</div>';
        }).join('') + '</div></details>';
    }
    K.page(h, crumbs);
  }
  function pairBlock(n) {
    return '<section class="card jpair"><div class="between"><h2>Какая работа сильнее?</h2>' + (n.phase === 'tie_break' ? pill('Переголосование', 'warn') : '') + '</div>' +
      '<p class="small muted">' + (n.phase === 'tie_break' ? 'У этих работ равный результат — организатор просит сравнить их ещё раз. ' : 'Сравните работы по заданию тура. ') +
      'Нажмите на фото, чтобы открыть его крупно.</p><div class="jgrid">' + ['a', 'b'].map(function (side) {
        return '<div class="jside"><span class="eyebrow">Работа № ' + n[side].no + '</span>' + photos(n[side].photos, 'Работа № ' + n[side].no) +
          '<button class="btn wide" type="button" data-act="jVote" data-id="' + n.id + '" data-w="' + side + '">№ ' + n[side].no + ' сильнее</button></div>';
      }).join('') + '</div></section>';
  }
  function thumb(side, won) {
    var p = side.photos[0];
    return p ? '<img loading="lazy" class="' + (won ? 'won' : '') + '" src="' + esc(p.thumb_url) + '" alt="Работа № ' + side.no + (won ? ' — выбрана' : '') + '">' : '';
  }
  K.actions.jVote = function (b) {
    Array.prototype.forEach.call(document.querySelectorAll('[data-act=jVote]'), function (x) { x.disabled = true; });
    K.api('POST', '/api/judging/comparisons/' + b.getAttribute('data-id'), { winner: b.getAttribute('data-w') }).then(function (r) {
      if (!r.ok) { K.toast(err(r)); K.route(); return; }
      J.s = r.data; draw(r.data); window.scrollTo(0, 0);
    });
  };

  /* ---------- оценки по критериям ---------- */
  function drawCriteria(s, crumbs) {
    var h = head(s) + taskBlock(s);
    if (!s.open) h += '<div class="note">Итоги тура опубликованы — оценка завершена. Спасибо!</div>';
    if (s.open && s.next) h += pairBlock(s.next);
    var next = s.works.filter(function (w) { return !w.done; })[0];
    if (s.open && s.locked_regular) h += '<div class="note small">Оценки по критериям закрыты организатором' + (s.next ? ' — осталось переголосование выше.' : '. Спасибо!') + '</div>';
    else if (s.open && next) h += workForm(s, next, true);
    else if (s.open) h += '<div class="note ok"><b>Все работы оценены.</b> Оценку можно открыть и поправить, пока итоги не опубликованы.</div>';
    h += '<section class="card"><h2>Работы пула</h2><div class="jworks">' + s.works.map(function (w) {
      return '<button class="jwork" type="button" data-act="jOpen" data-id="' + w.id + '">' + (w.photos[0] ? '<img src="' + esc(w.photos[0].thumb_url) + '" alt="">' : '<span class="photo"></span>') +
        '<span>№ ' + w.no + '</span>' + (w.done ? pill('Оценено', 'ok') : pill('Ждёт', 'plain')) + '</button>';
    }).join('') + '</div></section>';
    K.page(h, crumbs);
    bindForm(s);
  }
  function workForm(s, w, isNext) {
    return '<form class="card jform" id="f-score" data-id="' + w.id + '" novalidate><div class="between"><h2>Работа № ' + w.no + '</h2>' + (isNext ? pill('Следующая', 'acc') : '') + '</div>' +
      '<div class="jphotos">' + photos(w.photos, 'Работа № ' + w.no) + '</div><div class="grid3">' + s.criteria.map(function (c) {
        var v = w.scores[c.code];
        return '<div class="field"><label for="sc-' + c.code + '">' + esc(c.label) + '</label><input class="input" id="sc-' + c.code + '" data-code="' + c.code +
          '" type="number" inputmode="numeric" min="1" max="100" step="1" value="' + (v == null ? '' : esc(v)) + '"></div>';
      }).join('') + '</div><p class="small muted">Оценка от 1 до 100 по каждому критерию, целым числом.</p><p class="form-err" role="alert" tabindex="-1" hidden></p>' +
      '<button class="btn" type="submit"' + (s.open && !s.locked_regular ? '' : ' disabled') + '>Сохранить оценку</button></form>';
  }
  function bindForm(s) {
    var f = document.getElementById('f-score');
    if (!f) return;
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var scores = {}, missing = false;
      Array.prototype.forEach.call(f.querySelectorAll('input[data-code]'), function (inp) {
        var t = inp.value.trim(), n = +t;
        if (!/^\d{1,3}$/.test(t) || n < 1 || n > 100) missing = true; else scores[inp.getAttribute('data-code')] = n;
      });
      if (missing) { K.formError(f, 'Поставьте оценку по каждому критерию — целое число от 1 до 100.'); return; }
      K.formError(f, ''); K.busy(f, true);
      K.api('POST', '/api/judging/streams/' + s.id + '/works/' + f.getAttribute('data-id'), { scores: scores }).then(function (r) {
        K.busy(f, false);
        if (!r.ok) { K.formError(f, err(r)); return; }
        K.toast('Оценка сохранена'); J.s = r.data; draw(r.data); window.scrollTo(0, 0);
      });
    });
  }
  K.actions.jOpen = function (b) {
    var s = J.s, w = s.works.filter(function (x) { return x.id === b.getAttribute('data-id'); })[0];
    var old = document.getElementById('f-score');
    var html = workForm(s, w, false);
    if (old) old.outerHTML = html; else document.querySelector('#main .jworks').closest('.card').insertAdjacentHTML('beforebegin', html);
    bindForm(s);
    document.getElementById('f-score').scrollIntoView({ block: 'start' });
  };

  /* ---------- Разбор работы: судья записывает голосом прямо здесь (решение 13.10) ---------- */
  var REC = { rec: null, chunks: [], blob: null, url: null, timer: null, started: 0, stream: null };
  var MAX_SEC = 600;
  function recType() {
    var list = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
    for (var i = 0; i < list.length; i++) if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(list[i])) return list[i];
    return '';
  }
  function mmss(sec) { return Math.floor(sec / 60) + ':' + ('0' + Math.floor(sec % 60)).slice(-2); }
  function resetRec() {
    if (REC.timer) clearInterval(REC.timer);
    if (REC.stream) REC.stream.getTracks().forEach(function (t) { t.stop(); });
    if (REC.url) URL.revokeObjectURL(REC.url);
    REC = { rec: null, chunks: [], blob: null, url: null, timer: null, started: 0, stream: null };
  }
  K.on(/^\/judging\/reviews\/(\d+)$/, function (no) {
    resetRec();
    K.load(['/api/judging/reviews/' + no], function (o) { J.r = o; drawReview(o); }, [['Судейство', '/judging'], ['Разбор']]);
  });
  function drawReview(o) {
    var done = o.status === 'done';
    var h = '<div class="stack" data-s="g6"><span class="eyebrow">Разбор № ' + o.no + (o.game ? ' · ' + esc(o.game) : '') + '</span><h1>' + esc(o.name) + '</h1>' +
      '<p class="small muted">' + (o.scope === 'all' ? 'Все работы Игры' : 'Работа тура ' + o.round_no) + ' · около 5 минут голосом: что получилось, что и как улучшить.</p></div>';
    if (o.comment) h += '<div class="note"><b>Пожелание участницы:</b> ' + esc(o.comment) + '</div>';
    h += o.works.length ? o.works.map(function (w) {
      return '<section class="card"><h2>Тур ' + w.round_no + (w.title ? ' · ' + esc(w.title) : '') + '</h2>' + (w.task ? '<p class="small muted">' + esc(w.task) + '</p>' : '') +
        '<div class="jgrid">' + photos(w.photos, 'Работа тура ' + w.round_no) + '</div>' +
        (w.link ? '<p class="small"><a href="' + esc(w.link) + '" target="_blank" rel="noopener noreferrer">Публикация работы ↗</a></p>' : '') + '</section>';
    }).join('') : '<div class="note">Работ этой участницы в кабинете нет (например, Игра проходила в боте) — организатор пришлёт их вам.</div>';
    if (done) {
      h += '<section class="card"><h2>Разбор отправлен</h2><p class="small muted">' + esc(K.date(o.done_at)) + ' МСК — участница слушает его в своём кабинете.</p>' +
        (o.has_audio ? '<audio controls preload="metadata" class="wide" src="' + K.ROOT + '/api/judging/reviews/' + o.no + '/audio"></audio>' : '') +
        (o.review_text ? '<p data-s="pre">' + esc(o.review_text) + '</p>' : '') + '</section>';
    } else {
      h += '<section class="card" id="rec-box"><h2>Запись разбора</h2>' + recHTML(o) + '</section>';
      h += '<section class="card"><div class="field"><label for="rv-text">Текст (необязательно — коротко главное, участница увидит его под записью)</label>' +
        '<textarea class="input" id="rv-text" rows="4" maxlength="20000">' + esc(o.review_text || '') + '</textarea></div></section>';
      h += '<div class="actbar"><button class="btn wide" type="button" data-act="rvSend"' + (o.has_audio ? '' : ' disabled') + '>Отправить разбор участнице</button></div>';
    }
    K.page(h, [['Судейство', '/judging'], ['Разбор № ' + o.no]]);
    var f = document.getElementById('rv-file');
    if (f) f.addEventListener('change', function (e) { var file = e.target.files && e.target.files[0]; if (file) uploadAudio(file, file.type || 'audio/mpeg'); });
  }
  function recHTML(o) {
    if (REC.rec && REC.rec.state === 'recording') {
      return '<p class="rec-live" role="status"><span class="rec-dot" aria-hidden="true"></span> Идёт запись · <b id="rec-t">' + mmss((Date.now() - REC.started) / 1000) + '</b> (до 10 минут)</p>' +
        '<button class="btn wide" type="button" data-act="recStop">■ Остановить</button>';
    }
    if (REC.blob) {
      return '<p class="small">Послушайте запись. Если всё хорошо — сохраните её.</p><audio controls class="wide" src="' + REC.url + '"></audio>' +
        '<div class="row"><button class="btn" type="button" data-act="recSave">Сохранить запись</button><button class="btn ghost" type="button" data-act="recAgain">Записать заново</button></div>';
    }
    var supported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    return (o.has_audio ? '<p class="small">Сохранённая запись:</p><audio controls preload="metadata" class="wide" src="' + K.ROOT + '/api/judging/reviews/' + o.no + '/audio?v=' + (o.audio_bytes || 0) + '"></audio>' : '') +
      (supported ? '<button class="btn wide" type="button" data-act="recStart">● ' + (o.has_audio ? 'Перезаписать' : 'Начать запись') + '</button>' +
        '<p class="small muted">Телефон спросит разрешение на микрофон — нажмите «Разрешить». Говорите как обычно; паузы не страшны.</p>' :
        '<p class="small">Этот браузер не умеет записывать звук — загрузите готовую запись.</p>') +
      '<p class="small"><label class="lnk" for="rv-file">или загрузить готовый файл (Диктофон, голосовое)</label><input class="sr" id="rv-file" type="file" accept="audio/*"></p>';
  }
  function redrawRec() { var b = document.getElementById('rec-box'); if (b) b.innerHTML = '<h2>Запись разбора</h2>' + recHTML(J.r); }
  K.actions.recStart = function () {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var type = recType();
      var rec = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
      REC.stream = stream; REC.rec = rec; REC.chunks = []; REC.started = Date.now();
      rec.ondataavailable = function (e) { if (e.data && e.data.size) REC.chunks.push(e.data); };
      rec.onstop = function () {
        clearInterval(REC.timer); REC.timer = null;
        stream.getTracks().forEach(function (t) { t.stop(); });
        REC.blob = new Blob(REC.chunks, { type: (rec.mimeType || type || 'audio/webm').split(';')[0] });
        REC.url = URL.createObjectURL(REC.blob);
        redrawRec();
      };
      rec.start(1000);
      REC.timer = setInterval(function () {
        var sec = (Date.now() - REC.started) / 1000, t = document.getElementById('rec-t');
        if (t) t.textContent = mmss(sec);
        if (sec >= MAX_SEC && rec.state === 'recording') rec.stop();
      }, 500);
      redrawRec();
    }, function () { K.toast('Нет доступа к микрофону. Разрешите его в настройках браузера для этого сайта и попробуйте снова.'); });
  };
  K.actions.recStop = function () { if (REC.rec && REC.rec.state === 'recording') REC.rec.stop(); };
  K.actions.recAgain = function () { resetRec(); redrawRec(); };
  K.actions.recSave = function (b) { if (REC.blob) { b.disabled = true; uploadAudio(REC.blob, REC.blob.type || 'audio/webm'); } };
  function uploadAudio(blob, type) {
    var box = document.getElementById('rec-box');
    if (box) box.insertAdjacentHTML('beforeend', '<p class="small" role="status">Сохраняем запись…</p>');
    K.api('POST', '/api/judging/reviews/' + J.r.no + '/audio', undefined, { body: blob, type: type.split(';')[0] }).then(function (r) {
      if (!r.ok) { K.toast(r.detail === 'audio_format' ? 'Нужен аудиофайл (m4a, mp3, ogg, webm, wav).' : K.errorText(r)); redrawRec(); return; }
      var text = document.getElementById('rv-text'); var keep = text ? text.value : '';
      resetRec(); J.r = r.data; drawReview(r.data);
      var t2 = document.getElementById('rv-text'); if (t2 && keep) t2.value = keep;
      K.toast('Запись сохранена — проверьте и отправьте участнице');
    });
  }
  K.actions.rvSend = function (b) {
    var text = document.getElementById('rv-text');
    K.showModal('<h2 id="mT">Отправить разбор?</h2><p>Участница сразу получит его в кабинете и уведомление. После отправки запись уже не поменять.</p>' +
      '<div class="row"><button class="btn" type="button" data-act="rvSendYes">Отправить</button><button class="btn sec" type="button" data-act="closeModal">Отмена</button></div>');
    J.sendText = text ? text.value : '';
  };
  K.actions.rvSendYes = function (b) {
    b.disabled = true;
    K.api('POST', '/api/judging/reviews/' + J.r.no + '/send', { text: J.sendText || null }).then(function (r) {
      var m = b.closest('.modal'); if (m) m.remove();
      if (!r.ok) { K.toast(r.detail === 'no_review' ? 'Сначала запишите и сохраните разбор.' : K.errorText(r)); return; }
      J.r = r.data; drawReview(r.data); K.toast('Разбор отправлен участнице');
    });
  };
})();
