/* Extends the existing round screens without replacing the cabinet navigation. */
(function () {
  'use strict';
  const model = window.FPLGalleryModel;
  const galleryPages = ['gallery-manage', 'gallery-preview'];
  gameMenuPages.push(...galleryPages);
  let previewPhase = 'now', previewLeague = '';
  const config = r => r.gallery || (r.gallery = { enabled: true });
  const rows = r => model.composition(r, demoPeople, demoEntries, demoWorkVersions);
  const invalid = r => !!scheduleError(r, !!(r.fields.theme || r.fields.reference));
  function state(r, phase = 'now') {
    const deadline = scheduleOf(r).workClose, end = model.deadlineTime(deadline);
    const now = phase === 'before' ? end - 1 : phase === 'after' ? end : Date.now();
    return model.availability({ enabled: config(r).enabled, deadline, invalid: invalid(r), now });
  }
  function message(r, status) {
    const at = escape(dateText(scheduleOf(r).workClose)) + ' МСК';
    return {
      disabled: 'Галерея этого тура выключена.',
      unscheduled: 'Укажите срок сдачи работы. После него галерея откроется автоматически.',
      invalid: 'Исправьте сроки тура. До этого галерея закрыта.',
      waiting: 'Галерея откроется ' + at + ', после окончания приёма работ.',
      open: 'Галерея открыта. Приём работ завершился ' + at + '.'
    }[status];
  }
  function navigation(r) {
    const labels = [['Сезоны', 'seasons'], [currentSeason()?.name || 'Сезон', 'season'],
      [currentGame().name, 'game'], ['Тур ' + r.number, 'round']];
    return '<nav class="row crumbs" aria-label="Путь">' + labels.map(([label, target]) => btn(escape(label), target)).join('<span aria-hidden="true">›</span>') + '</nav>';
  }
  function settings(r) {
    let block = content.querySelector('#fpl-gallery-settings');
    if (!block) {
      block = document.createElement('section');
      block.id = 'fpl-gallery-settings';
      block.className = 'schedule-block fpl-gallery-settings';
      block.innerHTML = '<h3>Галерея работ</h3><label class="check"><input id="fpl-gallery-enabled" type="checkbox">Показывать работы участникам после окончания приёма</label>' +
        '<p id="fpl-gallery-window" class="fpl-gallery-state" aria-live="polite"></p>' +
        '<p>Время открытия берётся из поля «Срок сдачи работы» выше. При переносе срока оно изменится автоматически.</p>' +
        '<p class="muted">Последние сданные версии с обязательными материалами. Тема и референс остаются подготовкой. Оценки в галерее не показываются.</p>' +
        '<p id="fpl-gallery-composition"></p><div class="row"><button type="button" data-fpl-gallery-view="gallery-manage">Состав галереи</button>' +
        '<button type="button" data-fpl-gallery-view="gallery-preview">Предпросмотр галереи</button></div>';
      const formPreview = content.querySelector('[data-go="preview"]');
      formPreview.textContent = 'Предпросмотр формы сдачи';
      formPreview.before(block);
    }
    block.querySelector('#fpl-gallery-enabled').checked = config(r).enabled;
    block.querySelector('#fpl-gallery-window').textContent = '';
    block.querySelector('#fpl-gallery-window').innerHTML = message(r, state(r));
    const all = rows(r), ready = all.filter(w => w.ready);
    block.querySelector('#fpl-gallery-composition').textContent = 'Готово для галереи: ' + ready.length + '. Не входят: ' + (all.length - ready.length) + ' — работа не сдана, нет обязательных материалов или участник вышел из Игры.';
  }
  function photoSource(v) {
    return v.photoSrc || 'assets/demo-face-v' + Math.min(v.number, 2) + '.svg';
  }
  function sharePrototypeSnapshot() {
    // Only these fictional gallery materials cross into the separate participant page.
    const snapshot = { version: 1, selected: currentRound() ? { game: gameId, number: currentRound().number } : null,
      games: games.map(g => ({ id: g.id, name: g.name })),
      rounds: rounds.map(r => ({ id: r.id, game: r.game, number: r.number, name: r.name,
        enabled: config(r).enabled, deadline: scheduleOf(r).workClose || '', invalid: invalid(r),
        works: rows(r).filter(w => w.ready).map(w => ({ id: w.person.id, league: w.person.league,
          version: w.version.number, photo: !!(r.fields.photo && w.version.photo),
          photoSrc: r.fields.photo && w.version.photo ? (photoSource(w.version).startsWith('blob:') ? photoSource(w.version) : 'overview/' + photoSource(w.version)) : '',
          link: r.fields.link ? w.version.link || '' : '' })) })) };
    try { sessionStorage.setItem('fpl-gallery-preview-v1', JSON.stringify(snapshot)); }
    catch (_) { /* The on-page preview continues if browser storage is unavailable. */ }
  }
  function manage(r) {
    const all = rows(r), ready = all.filter(w => w.ready);
    content.innerHTML = navigation(r) + '<h1>Состав галереи · Тур ' + r.number + '</h1><p class="muted">' + escape(r.name) + ' · демонстрационные материалы.</p>' +
      '<section class="card fpl-gallery-status"><h2>' + (config(r).enabled ? 'Автоматическое открытие' : 'Галерея выключена') + '</h2><p>' + message(r, state(r)) + '</p>' +
      '<p><strong>' + ready.length + ' работ готовы</strong> · ' + (all.length - ready.length) + ' пока не входят</p><p class="muted">Используется последняя сданная версия каждой работы. После замены состав обновляется из этих же материалов.</p></section>' +
      '<div class="people-list fpl-gallery-list"><table class="participants-table fpl-gallery-table"><caption class="visually-hidden">Состав галереи выбранного тура</caption><thead><tr><th scope="col">Участник / лига</th><th scope="col">Версия</th><th scope="col">Материалы</th><th scope="col">Галерея</th></tr></thead><tbody>' +
      all.map(w => '<tr><td data-label="Участник / лига">' + escape(w.person.name) + '<small>' + leagueLabels[w.person.league] + ' лига</small></td><td data-label="Версия">' + (w.version ? w.version.number + '<small>' + escape(w.version.saved) + '</small>' : '—') +
        '</td><td data-label="Материалы">' + (w.version?.photo && r.fields.photo ? '<img class="fpl-gallery-thumb" src="' + escape(photoSource(w.version)) + '" alt="Пример работы">' : '') +
        (r.fields.link && w.version?.link ? '<span class="fpl-gallery-link-mark">Ссылка добавлена</span>' : '') + '</td><td data-label="Галерея"><span class="status-chip ' + (w.ready ? 'status-participating' : 'status-registered') + '">' + (w.ready ? 'Готова для галереи' : escape(w.reason)) + '</span></td></tr>').join('') +
      '</tbody></table>' + (!all.length ? '<div class="empty-list">В этой Игре ещё нет участников.</div>' : '') + '</div><div class="row"><button data-go="round">К настройкам тура</button><button data-fpl-gallery-view="gallery-preview">Предпросмотр галереи</button></div>';
  }
  function preview(r) {
    content.innerHTML = navigation(r) + '<h1>Галерея глазами участника</h1><p class="muted">Предпросмотр выбранной Игры и тура. Все материалы — примеры.</p>' +
      '<section class="card fpl-gallery-preview-tools"><div class="field"><label for="fpl-gallery-phase">Состояние в предпросмотре</label><select id="fpl-gallery-phase"><option value="now">Сейчас</option><option value="before">До окончания приёма</option><option value="after">После окончания приёма</option></select></div><p class="muted">Проверяет автоматическое открытие. Этот переключатель видит только администратор; он не публикует работы.</p></section>' +
      '<section class="fpl-gallery-frame" aria-label="Вид участника"><h2>Работы участников</h2><p>' + escape(currentGame().name) + '</p><div class="fpl-gallery-filters"><div class="field"><label for="fpl-gallery-round">Тур</label><select id="fpl-gallery-round">' + rounds.filter(x => x.game === gameId).map(x => '<option value="' + x.id + '" ' + (x.id === r.id ? 'selected' : '') + '>Тур ' + x.number + ' · ' + escape(x.name) + '</option>').join('') +
      '</select></div><div class="field"><label for="fpl-gallery-league">Лига</label><select id="fpl-gallery-league"><option value="">Все лиги</option>' + Object.entries(leagueLabels).map(([id, label]) => '<option value="' + id + '">' + label + '</option>').join('') + '</select></div></div><div id="fpl-gallery-preview-body" aria-live="polite"></div></section>' +
      '<div class="row"><button data-go="round">К настройкам тура</button><button data-fpl-gallery-view="gallery-manage">Состав галереи</button><a class="button" href="../index.html#gallery">Открыть кабинет участника</a></div>';
    content.querySelector('#fpl-gallery-phase').value = previewPhase;
    content.querySelector('#fpl-gallery-league').value = previewLeague;
    paintPreview(r);
  }
  function paintPreview(r) {
    const target = content.querySelector('#fpl-gallery-preview-body');
    if (!target) return;
    const status = state(r, previewPhase);
    content.querySelector('#fpl-gallery-league').disabled = status !== 'open';
    if (status !== 'open') {
      target.innerHTML = '<section class="card"><h3>Работы пока закрыты</h3><p>' + message(r, status) + '</p></section>';
      return;
    }
    const ready = rows(r).filter(w => w.ready);
    const shown = ready.map((w, index) => ({ ...w, index: Number(w.person.id.slice(1)) || index + 1 })).filter(w => !previewLeague || w.person.league === previewLeague);
    target.innerHTML = '<p class="fpl-gallery-count">Работ: ' + shown.length + ' · Тур ' + r.number + '</p>' + (shown.length ? '<div class="fpl-gallery-grid">' + shown.map(w => '<button class="fpl-gallery-work" data-fpl-gallery-photo="' + w.person.id + '">' +
      (r.fields.photo && w.version.photo ? '<img src="' + escape(photoSource(w.version)) + '" alt="Работа ' + w.index + ' · демонстрационная иллюстрация" loading="lazy">' : '<span class="fpl-gallery-link-cover">Работа по ссылке</span>') +
      '<strong>Работа ' + w.index + '</strong><span>' + leagueLabels[w.person.league] + ' лига</span><small>' + (r.fields.photo && w.version.photo ? 'Открыть работу' : 'Посмотреть ссылку') + '</small></button>').join('') + '</div>' : '<section class="card"><h3>Работ пока нет</h3><p>' + (ready.length ? 'В выбранной лиге пока нет работ. Выберите другую лигу.' : 'Сданные работы появятся здесь автоматически.') + '</p></section>');
  }
  function openPhoto(id) {
    const r = currentRound();
    if (!r || state(r, previewPhase) !== 'open') return;
    const item = rows(r).find(w => w.ready && w.person.id === id);
    if (!item) return;
    const d = document.createElement('dialog');
    d.className = 'fpl-gallery-dialog';
    d.innerHTML = '<div class="row"><h2>Работа участника</h2><button type="button" data-fpl-gallery-close>Закрыть</button></div>' +
      (r.fields.photo && item.version.photo ? '<img src="' + escape(photoSource(item.version)) + '" alt="Демонстрационная работа крупно">' : '') +
      (r.fields.link && item.version.link ? '<h3>Ссылка на работу</h3><p class="fpl-gallery-demo-link">' + escape(item.version.link) + '</p><p class="muted">Демонстрационный адрес. Переход отключён.</p>' : '');
    document.body.append(d);
    d.querySelector('[data-fpl-gallery-close]').onclick = () => d.close();
    d.addEventListener('close', () => d.remove());
    d.showModal();
  }
  const previousRender = render;
  render = function () {
    previousRender();
    sharePrototypeSnapshot();
    if (role !== 'admin' || !currentRound() || currentRound().game !== gameId) return;
    const r = currentRound();
    if (page === 'round') settings(r);
    if (page === 'gallery-manage') manage(r);
    if (page === 'gallery-preview') preview(r);
    if (galleryPages.includes(page)) {
      document.querySelectorAll('#navigation [aria-current]').forEach(e => e.removeAttribute('aria-current'));
      document.querySelector('#navigation [data-go="game-rounds"]')?.setAttribute('aria-current', 'page');
      document.title = content.querySelector('h1').textContent + ' · FPL';
    }
  };
  document.addEventListener('click', e => {
    const next = e.target.closest('[data-fpl-gallery-view]');
    if (next && role === 'admin' && currentRound()) {
      if (page !== 'gallery-preview') { previewPhase = 'now'; previewLeague = ''; }
      page = next.dataset.fplGalleryView;
      render(); window.scrollTo(0, 0);
    }
    const photo = e.target.closest('[data-fpl-gallery-photo]');
    if (photo && page === 'gallery-preview' && role === 'admin') openPhoto(photo.dataset.fplGalleryPhoto);
  });
  document.addEventListener('change', e => {
    if (role !== 'admin' || !currentRound()) return;
    if (page === 'round' && e.target.id === 'fpl-gallery-enabled') {
      config(currentRound()).enabled = e.target.checked; settings(currentRound()); sharePrototypeSnapshot();
    }
    if (page === 'gallery-preview' && e.target.id === 'fpl-gallery-phase') { previewPhase = e.target.value; paintPreview(currentRound()); }
    if (page === 'gallery-preview' && e.target.id === 'fpl-gallery-league') { previewLeague = e.target.value; paintPreview(currentRound()); }
    if (page === 'gallery-preview' && e.target.id === 'fpl-gallery-round') { roundId = e.target.value; previewLeague = ''; render(); }
    if (page === 'round' && e.target.dataset.field) { settings(currentRound()); sharePrototypeSnapshot(); }
  });
  document.addEventListener('input', e => {
    if (role === 'admin' && page === 'round' && e.target.dataset.date && currentRound()) { settings(currentRound()); sharePrototypeSnapshot(); }
  });
  let lastClockState = '';
  setInterval(() => {
    if (role !== 'admin' || !currentRound() || !['round', 'gallery-manage', 'gallery-preview'].includes(page)) return;
    const next = state(currentRound(), page === 'gallery-preview' ? previewPhase : 'now');
    if (next === lastClockState) return;
    lastClockState = next;
    if (page === 'round') settings(currentRound());
    else if (page === 'gallery-preview') paintPreview(currentRound());
    else manage(currentRound());
  }, 1000);
  render();
})();
