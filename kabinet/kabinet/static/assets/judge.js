/* Кабинет судьи (этап 4): назначенные пулы, сравнение пар, оценки по критериям. Имён участниц судья не видит. */
(function () {
  'use strict';
  var K = window.K, esc = K.esc, pill = K.pill, li = K.li;
  var J = {};
  var LEAGUE = { bronze: 'Bronze', silver: 'Silver', gold: 'Gold' };
  var TEXT = { judging_closed: 'Итоги тура уже опубликованы — оценки не меняются.', regular_locked: 'Идёт переголосование — основные голоса уже не меняются.',
    all_criteria_required: 'Поставьте оценку по каждому критерию.', score_out_of_range: 'Оценка — от 1 до 10.' };
  var err = function (r) { return TEXT[r.detail] || K.errorText(r); };
  function poolName(s) { return s.league ? 'Лига ' + LEAGUE[s.league] : 'Общий пул'; }
  function bar(done, total) {
    var pct = total ? Math.round(done * 100 / total) : 0;
    return '<div class="jbar" role="progressbar" aria-valuemin="0" aria-valuemax="' + total + '" aria-valuenow="' + done + '" aria-label="Готово ' + done + ' из ' + total + '">' +
      '<span data-w="' + (Math.round(pct / 5) * 5) + '"></span></div>';
  }

  K.on(/^\/judging$/, function () {
    K.load(['/api/judging'], function (d) {
      var h = '<h1>Судейство</h1><p class="muted small">Работы показываются без имён. Оценки можно менять, пока организатор не опубликовал итоги тура.</p>';
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
    return p ? '<img class="' + (won ? 'won' : '') + '" src="' + esc(p.thumb_url) + '" alt="Работа № ' + side.no + (won ? ' — выбрана' : '') + '">' : '';
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
        return '<div class="field"><label for="sc-' + c.code + '">' + esc(c.label) + '</label><select class="input" id="sc-' + c.code + '" data-code="' + c.code + '"><option value="">—</option>' +
          [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return '<option value="' + n + '"' + (v === n ? ' selected' : '') + '>' + n + '</option>'; }).join('') + '</select></div>';
      }).join('') + '</div><p class="small muted">Оценка от 1 до 10 по каждому критерию.</p><p class="form-err" role="alert" tabindex="-1" hidden></p>' +
      '<button class="btn" type="submit"' + (s.open && !s.locked_regular ? '' : ' disabled') + '>Сохранить оценку</button></form>';
  }
  function bindForm(s) {
    var f = document.getElementById('f-score');
    if (!f) return;
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var scores = {}, missing = false;
      Array.prototype.forEach.call(f.querySelectorAll('select[data-code]'), function (sel) {
        if (!sel.value) missing = true; else scores[sel.getAttribute('data-code')] = +sel.value;
      });
      if (missing) { K.formError(f, 'Поставьте оценку по каждому критерию.'); return; }
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
})();
