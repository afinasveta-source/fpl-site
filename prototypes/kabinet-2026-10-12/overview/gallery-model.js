/* Local prototype rules. No database reads or publication side effects. */
(function (root) {
  'use strict';
  function deadlineTime(value) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value || '')) return NaN;
    const parsed = Date.parse(value + ':00+03:00');
    // Date.parse normalizes impossible dates such as February 30.
    if (!Number.isFinite(parsed) || new Date(parsed + 3 * 3600000).toISOString().slice(0, 16) !== value) return NaN;
    return parsed;
  }
  function availability({ enabled = true, deadline, invalid = false, now = Date.now() }) {
    if (!enabled) return 'disabled';
    if (!deadline) return 'unscheduled';
    const end = deadlineTime(deadline);
    if (invalid || !Number.isFinite(end)) return 'invalid';
    return now < end ? 'waiting' : 'open';
  }
  function validLink(value) {
    try { return ['http:', 'https:'].includes(new URL(value).protocol); }
    catch (_) { return false; }
  }
  function composition(round, people, entries, records) {
    const fields = round.fields || {};
    const roster = new Set(entries.filter(e => e.game === round.game).map(e => e.person));
    return people.filter(p => roster.has(p.id)).map(person => {
      const versions = records.filter(w => w.round === round.id && w.person === person.id)
        .flatMap(w => w.versions || []);
      const version = versions.reduce((last, v) => !last || v.number > last.number ? v : last, null);
      let reason = '';
      if (!fields.photo && !fields.link) reason = 'Не настроены поля сдачи';
      else if (!version) reason = 'Нет сданной работы';
      else if (fields.photo && !version.photo) reason = 'Не хватает фото';
      else if (fields.link && (fields.linkRequired || !fields.photo) && !version.link) reason = 'Не хватает обязательной ссылки';
      else if (fields.link && version.link && !validLink(version.link)) reason = 'Нужно исправить ссылку';
      return { person, version, ready: !reason, reason };
    });
  }
  const api = { deadlineTime, availability, composition };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FPLGalleryModel = api;
})(typeof window !== 'undefined' ? window : {});
