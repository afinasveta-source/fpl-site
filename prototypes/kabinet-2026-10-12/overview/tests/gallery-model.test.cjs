const test = require('node:test');
const assert = require('node:assert/strict');
const { availability, composition, deadlineTime } = require('../gallery-model.js');
const deadline = '2026-10-10T23:59';
const round = { id: 'r3', game: 'g1', fields: { photo: true, link: true, linkRequired: true } };
const people = [{ id: 'p1' }, { id: 'p2' }];
const entries = [{ person: 'p1', game: 'g1' }, { person: 'p2', game: 'g2' }];
const complete = { number: 1, photo: true, link: 'https://example.test/work' };
test('Moscow deadline opens exactly at the boundary', () => {
  assert.equal(deadlineTime(deadline), Date.parse('2026-10-10T20:59:00Z'));
  assert.equal(availability({ deadline, now: deadlineTime(deadline) - 1 }), 'waiting');
  assert.equal(availability({ deadline, now: deadlineTime(deadline) }), 'open');
});
test('deadline moves with the round and closes the gallery until the new time', () => {
  const now = deadlineTime(deadline) + 1;
  assert.equal(availability({ deadline, now }), 'open');
  assert.equal(availability({ deadline: '2026-10-11T23:59', now }), 'waiting');
});
test('disabled, missing and invalid schedules stay closed after a simulated deadline', () => {
  assert.equal(availability({ enabled: false, deadline, now: Infinity }), 'disabled');
  assert.equal(availability({ deadline: '', now: Infinity }), 'unscheduled');
  assert.equal(availability({ deadline: 'bad-date', now: Infinity }), 'invalid');
  assert.equal(availability({ deadline, invalid: true, now: Infinity }), 'invalid');
});
test('impossible calendar dates never open the gallery', () => {
  for (const date of ['2026-02-30T23:59', '2026-02-29T23:59', '2026-04-31T12:00', '2026-10-10T24:00']) {
    assert.equal(availability({ deadline: date, now: Infinity }), 'invalid');
  }
  assert.ok(Number.isFinite(deadlineTime('2028-02-29T23:59')));
});
test('gallery takes the newest version, not the first complete or last array item', () => {
  const latest = { ...complete, number: 3, photo: false };
  const result = composition(round, people, entries, [{ person: 'p1', round: 'r3', versions: [latest, complete] }]);
  assert.equal(result[0].version.number, 3);
  assert.equal(result[0].ready, false);
  assert.equal(result[0].reason, 'Не хватает фото');
});
test('another Game and another round cannot add works to the selected gallery', () => {
  const result = composition(round, people, entries, [
    { person: 'p1', round: 'r2', versions: [complete] },
    { person: 'p2', round: 'r3', versions: [complete] }
  ]);
  assert.equal(result.length, 1);
  assert.equal(result[0].person.id, 'p1');
  assert.equal(result[0].ready, false);
});
test('link-only work requires a valid link even without the optional-link flag', () => {
  const linkRound = { ...round, fields: { photo: false, link: true, linkRequired: false } };
  const records = [{ person: 'p1', round: 'r3', versions: [{ number: 1, photo: false, link: '' }] }];
  assert.equal(composition(linkRound, people, entries, records)[0].ready, false);
  records[0].versions[0].link = 'https://example.test/work';
  assert.equal(composition(linkRound, people, entries, records)[0].ready, true);
  records[0].versions[0].link = 'javascript:alert(1)';
  assert.equal(composition(linkRound, people, entries, records)[0].ready, false);
});
test('photo-only work ignores unused links; preparation cannot create a work', () => {
  const photoRound = { ...round, fields: { photo: true, link: false } };
  const records = [{ person: 'p1', round: 'r3', versions: [{ ...complete, link: '' }] }];
  assert.equal(composition(photoRound, people, entries, records)[0].ready, true);
  assert.equal(composition(photoRound, people, entries, [])[0].ready, false);
  assert.equal(composition({ ...round, fields: {} }, people, entries, records)[0].ready, false);
});
