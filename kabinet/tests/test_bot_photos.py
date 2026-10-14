"""Фото работ туров 1–2 Игры 01 из бота (14.10): предпросмотр без скачивания, перенос пачками, повтор и исправление адреса,
работа, сданная участницей самой, не трогается; фото видно в карточке организатора и на странице Игры участницы.
Скачивание подменяется (app.state.fetch_photo) — в проверках сеть не нужна. Люди и адреса — выдуманные."""
import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD
from game_helpers import ORIGIN, add_docs, h, jpeg
from test_bot_import import do_import
from test_org import ok, org
from kabinet.auth.security import password_hasher
from kabinet.org import bot_photos as BP

PATH = '/api/org/import/game01/photos'
U = 'https://sun9-1.userapi.com/impg/{}.jpg'


class Fake:
    """Источник фото: адрес → байты или код ошибки (как у настоящего скачивания)."""
    def __init__(self, files):
        self.files, self.calls = dict(files), []

    def __call__(self, url):
        self.calls.append(url)
        if not BP.allowed_url(url):
            raise BP.FetchError('bad_url')
        v = self.files.get(url, 'http_404')
        if isinstance(v, str):
            raise BP.FetchError(v)
        return v


def item(cid, rnd, url, note=None):
    return {'cid': cid, 'round': rnd, 'url': url, 'note': note}


def setup(app, seed, clock):
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    _, res = do_import(c)
    return c, res['event_id']


def ep_of(app, eid, cid):
    with app.state.db.transaction() as conn:
        return conn.execute('''SELECT p.* FROM event_participants p JOIN external_identities x ON x.user_id=p.user_id
WHERE p.event_id=%s AND x.provider='salebot_client' AND x.external_id=%s''', (eid, cid)).fetchone()


def own_draft(app, eid, cid, rnd):
    """Участница начала работу тура в кабинете сама (черновик с её фото)."""
    ep = ep_of(app, eid, cid)
    with app.state.db.transaction() as conn:
        a = conn.execute('''SELECT a.* FROM assignments a JOIN rounds r ON r.id=a.round_id WHERE r.event_id=%s AND r.round_no=%s''',
                         (eid, rnd)).fetchone()
        v = conn.execute('SELECT id FROM assignment_variants WHERE assignment_id=%s', (a['id'],)).fetchone()
        pa = conn.execute('''INSERT INTO participant_assignments(event_id,event_participant_id,assignment_id,assignment_variant_id)
VALUES (%s,%s,%s,%s) RETURNING id''', (eid, ep['id'], a['id'], v['id'])).fetchone()
        s = conn.execute('INSERT INTO submissions(event_participant_id,participant_assignment_id) VALUES (%s,%s) RETURNING id',
                         (ep['id'], pa['id'])).fetchone()
        conn.execute("INSERT INTO submission_versions(submission_id,version_no,source,created_by) VALUES (%s,1,'web',%s)",
                     (s['id'], ep['user_id']))


def by_index(rows):
    return {r['index']: r for r in rows}


def test_preview_statuses_without_downloads(app, seed, clock):
    c, eid = setup(app, seed, clock)
    fake = app.state.fetch_photo = Fake({})
    with app.state.db.transaction() as conn:       # есть в базе по ID SaleBot, но не в Игре 01
        uid = conn.execute("INSERT INTO users(account_status,full_name) VALUES ('imported','Другая Игра') RETURNING id").fetchone()['id']
        conn.execute('''INSERT INTO external_identities(user_id,provider,project_ref,external_id,linked_at) VALUES (%s,'salebot_client',%s,'2000000001',now())''',
                     (uid, BP.PROJECT))
    own_draft(app, eid, '1000000004', 1)
    items = [item('1000000001', 1, U.format('a'), 'точно'), item('1000000002', 2, 'http://sun9-1.userapi.com/b.jpg'),
             item('999999999', 1, U.format('c')), item('1000000001', 1, U.format('d')),
             item('1000000002', 1, 'https://evil.example.com/x.jpg'), item('1000000003', 3, U.format('e')),
             item('2000000001', 1, U.format('f')), item('1000000004', 1, U.format('g')),
             item('1000000005', 2, 'https://files.salebot.pro/uploads/x.png', 'догадка'),
             item('1000000003', 1, 'https://pp.vkuserphoto.ru/c1/y.jpg'),
             item('1000000003', 2, 'https://user:pw@sun9-1.userapi.com/z.jpg')]
    p = ok(c.post(PATH + '/preview', headers=ORIGIN, json={'items': items}))
    st = {r['index']: r['status'] for r in p['items']}
    assert st == {0: 'ok', 1: 'bad_url', 2: 'unknown_cid', 3: 'duplicate', 4: 'bad_url', 5: 'bad_round', 6: 'not_in_game',
                  7: 'has_own', 8: 'ok', 9: 'ok', 10: 'bad_url'}
    rows = by_index(p['items'])
    assert rows[0]['name'] == 'Иванова Анна Петровна' and rows[0]['league'] == 'gold' and rows[0]['mode'] == 'in'
    assert rows[0]['has_result'] and rows[0]['score'] == 90 and rows[0]['note'] == 'точно'
    assert rows[8]['mode'] == 'outside' and not rows[8]['has_result']          # тура 2 у неё в боте нет
    assert p['counts']['ok'] == 3 and p['counts']['bad_url'] == 3 and p['total'] == 11
    assert fake.calls == []                                                     # предпросмотр ничего не скачивает
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM submissions WHERE event_participant_id IN (SELECT id FROM event_participants WHERE event_id=%s)',
                            (eid,)).fetchone()['n'] == 1


def test_apply_downloads_and_shows_photo(app, seed, clock):
    c, eid = setup(app, seed, clock)
    good = jpeg((200, 10, 10), size=(80, 100))
    fake = app.state.fetch_photo = Fake({U.format('a'): good, U.format('notimg'): b'<html>not a photo</html>',
                                         U.format('r2'): jpeg((10, 200, 10))})
    own_draft(app, eid, '1000000004', 1)
    batch = [item('1000000001', 1, U.format('a')), item('1000000002', 1, U.format('missing')),
             item('1000000003', 1, U.format('notimg')), item('1000000004', 1, U.format('own')),
             item('1000000003', 2, 'https://evil.example.com/x.jpg')]
    r = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': batch}))
    res = by_index(r['items'])
    assert (res[0]['result'], res[0]['reason']) == ('done', None) and res[0]['photo']['thumb_url'].endswith('?size=thumb')
    assert (res[1]['result'], res[1]['reason']) == ('failed', 'http_404')
    assert (res[2]['result'], res[2]['reason']) == ('failed', 'not_image')
    assert (res[3]['result'], res[3]['reason']) == ('skipped', 'has_own')
    assert (res[4]['result'], res[4]['reason']) == ('skipped', 'bad_url')
    assert r['counts'] == {'done': 1, 'failed': 2, 'skipped': 2}
    assert U.format('own') not in fake.calls and not any('evil' in u for u in fake.calls)   # не качается то, что не перенесётся
    # тур 2 без итога из бота — для диплома, не в конкурс
    r2 = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000005', 2, U.format('r2'))]}))
    assert r2['items'][0]['result'] == 'done'
    ep1, ep5 = ep_of(app, eid, '1000000001'), ep_of(app, eid, '1000000005')
    with app.state.db.transaction() as conn:
        s = conn.execute('SELECT * FROM submissions WHERE event_participant_id=%s', (ep1['id'],)).fetchone()
        v = conn.execute('SELECT * FROM submission_versions WHERE id=%s', (s['latest_version_id'],)).fetchone()
        m = conn.execute('''SELECT m.* FROM media_files m JOIN submission_version_media x ON x.media_file_id=m.id
WHERE x.submission_version_id=%s''', (v['id'],)).fetchone()
        pa = conn.execute('SELECT * FROM participant_assignments WHERE id=%s', (s['participant_assignment_id'],)).fetchone()
        mapped = conn.execute("SELECT * FROM import_row_map WHERE source_table='salebot_photo' AND source_key='1000000001/r1'").fetchone()
        s5 = conn.execute('SELECT * FROM submissions WHERE event_participant_id=%s', (ep5['id'],)).fetchone()
        logged = conn.execute("SELECT after_data FROM audit_log WHERE action='bot_photos_game01' ORDER BY created_at").fetchall()
        batch_row = conn.execute("SELECT * FROM import_batches WHERE notes LIKE 'bot_photos game01:%%' ORDER BY started_at LIMIT 1").fetchone()
    assert s['status'] == 'locked' and s['counts_for_competition'] and s['counts_for_diploma'] and s['is_on_time']
    assert s['competition_version_id'] == s['diploma_version_id'] == s['latest_version_id'] and s['deadline_source'] == 'import'
    assert s['first_submitted_at'] == BP.BOT_ROUNDS[1]['deadline'] and v['submitted_at'] == BP.BOT_ROUNDS[1]['deadline']
    assert v['source'] == 'migration' and pa['source'] == 'migration'
    assert m['uploaded_by'] == ep1['user_id'] and m['source_url'] == U.format('a') and m['sha256']
    assert m['metadata']['source'] == 'salebot' and m['metadata']['bot_cid'] == '1000000001' and m['metadata']['url_host'] == 'sun9-1.userapi.com'
    assert mapped['target_id'] == s['id'] and mapped['row_sha256'] == BP.url_sha(U.format('a'))
    assert not s5['counts_for_competition'] and s5['counts_for_diploma'] and s5['is_on_time'] is False and s5['competition_version_id'] is None
    assert len(logged) == 2 and logged[0]['after_data']['counts'] == {'done': 1, 'failed': 2, 'skipped': 2}
    assert batch_row['status'] == 'completed'
    # карточка участницы у организатора — фото тура 1 из бота
    card = ok(c.get(f"/api/org/participants/{ep1['id']}"))
    r1 = next(x for x in card['rounds'] if x['round_no'] == 1)
    assert r1['from_bot'] and r1['result']['score'] == 90 and r1['submitted']['source'] == 'migration'
    assert len(r1['submitted']['photos']) == 1 and c.get(r1['submitted']['photos'][0]['thumb_url'].replace('/kabinet', '')).status_code == 200
    # сама участница: страница Игры и задание тура 1 (работа сдана в боте, заново не сдаётся)
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE users SET email='anna@example.com', password_hash=%s, email_verified_at=now(), account_status='active'
WHERE id=%s''', (password_hasher.hash(PASSWORD), ep1['user_id']))
    p = TestClient(app)
    ok(p.post('/web-auth/login', headers=ORIGIN, json={'email': 'anna@example.com', 'password': PASSWORD}))
    g = ok(p.get(f'/api/games/{eid}'))
    g1 = next(x for x in g['rounds'] if x['round_no'] == 1)
    assert g1['photo'] and g1['photo']['from_bot'] and g1['work'] == 'sent' and g1['result']['score'] == 90
    assert next(x for x in g['rounds'] if x['round_no'] == 2)['photo'] is None
    assert p.get(g1['photo']['view_url'].replace('/kabinet', '')).status_code == 200
    t = ok(p.get(f"/api/games/{eid}/tasks/{g1['assignment_id']}"))
    assert t['window']['reason'] == 'done_in_bot' and t['submitted']['photos'] and t['submitted']['source'] == 'migration'
    # чужое фото участнице не видно
    other = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000005', 1, U.format('a'))]}))['items'][0]
    assert other['result'] == 'done'
    assert p.get(other['photo']['thumb_url'].replace('/kabinet', '')).status_code == 404


def test_repeat_and_replacement(app, seed, clock):
    c, eid = setup(app, seed, clock)
    first, second = jpeg((1, 2, 3)), jpeg((250, 250, 0))
    fake = app.state.fetch_photo = Fake({U.format('v1'): first, U.format('v2'): second, U.format('v2copy'): second})
    ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v1'))]}))
    calls = len(fake.calls)
    again = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v1'))]}))['items'][0]
    assert (again['result'], again['reason']) == ('skipped', 'same') and len(fake.calls) == calls     # повтор — без скачивания
    p = ok(c.post(PATH + '/preview', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v1')), item('1000000002', 1, U.format('v1')),
                                                                      ]}))
    assert [x['status'] for x in p['items']] == ['same', 'ok']
    p = ok(c.post(PATH + '/preview', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v2'))]}))
    cur = p['items'][0]
    assert cur['status'] == 'replace' and cur['current']['source_url'] == U.format('v1') and cur['current']['thumb_url']
    fix = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v2'))]}))['items'][0]
    assert fix['result'] == 'done' and fix['version_no'] == 2
    same_file = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000002', 2, U.format('v2copy'))]}))['items'][0]
    assert (same_file['result'], same_file['reason']) == ('skipped', 'same_file')
    ep = ep_of(app, eid, '1000000002')
    with app.state.db.transaction() as conn:
        s = conn.execute('SELECT * FROM submissions WHERE event_participant_id=%s', (ep['id'],)).fetchone()
        versions = conn.execute('SELECT * FROM submission_versions WHERE submission_id=%s ORDER BY version_no', (s['id'],)).fetchall()
        latest_media = conn.execute('''SELECT m.source_url FROM submission_version_media x JOIN media_files m ON m.id=x.media_file_id
WHERE x.submission_version_id=%s''', (s['latest_version_id'],)).fetchone()
        mapped = conn.execute("SELECT row_sha256 FROM import_row_map WHERE source_table='salebot_photo' AND source_key='1000000002/r2'").fetchone()
    assert [v['version_no'] for v in versions] == [1, 2] and s['latest_version_id'] == versions[1]['id']
    assert s['competition_version_id'] == s['diploma_version_id'] == versions[1]['id'] and s['counts_for_competition']
    assert latest_media['source_url'] == U.format('v2') and mapped['row_sha256'] == BP.url_sha(U.format('v2copy'))
    card = ok(c.get(f"/api/org/participants/{ep['id']}"))
    assert next(x for x in card['rounds'] if x['round_no'] == 2)['submitted']['version_no'] == 2
    # работа, начатая участницей самой, после этого не перезаписывается
    own_draft(app, eid, '1000000003', 2)
    p = ok(c.post(PATH + '/preview', headers=ORIGIN, json={'items': [item('1000000003', 2, U.format('v1'))]}))
    assert p['items'][0]['status'] == 'has_own'


def test_batch_time_budget_and_guards(app, seed, clock, monkeypatch):
    clock.set(h())
    c = org(app, seed)
    assert c.post(PATH + '/preview', headers=ORIGIN, json={'items': [item('1', 1, U.format('a'))]}).json()['detail'] == 'not_moved'
    with app.state.db.transaction() as conn:
        add_docs(conn)
    do_import(c)
    app.state.fetch_photo = Fake({U.format('a'): jpeg(), U.format('b'): jpeg((0, 0, 255))})
    monkeypatch.setattr(BP, 'BUDGET', -1)          # «время пачки вышло» сразу после первой строки
    r = ok(c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000001', 1, U.format('a')), item('1000000002', 1, U.format('b'))]}))
    assert [x['result'] for x in r['items']] == ['done', 'pending']
    assert c.post(PATH + '/apply', headers=ORIGIN, json={'items': [item('1000000001', 1, U.format('a'))] * 11}).status_code == 422
    assert c.post(PATH + '/apply', json={'items': [item('1000000001', 1, U.format('a'))]}).status_code == 403   # без Origin
    p = TestClient(app)
    seed('p@example.com')
    ok(p.post('/web-auth/login', headers=ORIGIN, json={'email': 'p@example.com', 'password': PASSWORD}))
    assert p.post(PATH + '/preview', headers=ORIGIN, json={'items': [item('1', 1, U.format('a'))]}).status_code == 403


@pytest.mark.parametrize('url,allowed', [
    ('https://files.salebot.pro/uploads/a.jpg', True), ('https://sun9-75.userapi.com/s/v1/x.jpg?size=1&quality=95', True),
    ('https://pp.vkuserphoto.ru/c1/a.jpg', True), ('https://userapi.com/a.jpg', True),
    ('http://sun9-75.userapi.com/x.jpg', False), ('https://sun9-75.userapi.com.evil.ru/x.jpg', False),
    ('https://evilsalebot.pro/a.jpg', False), ('https://notuserapi.com/a.jpg', False), ('https://sun9-1.userapi.com:8443/a.jpg', False),
    ('https://a@sun9-1.userapi.com/a.jpg', False), ('https://127.0.0.1/a.jpg', False), ('file:///etc/passwd', False), ('', False),
])
def test_url_allowlist(url, allowed):
    assert BP.allowed_url(url) is allowed


def test_fetch_refuses_foreign_hosts_and_redirects():
    with pytest.raises(BP.FetchError) as e:
        BP.fetch_photo('https://example.com/a.jpg')
    assert e.value.code == 'bad_url'
    with pytest.raises(BP.FetchError) as e:
        BP._Redirects().redirect_request(None, None, 302, 'Found', {}, 'https://169.254.169.254/latest/meta-data')
    assert e.value.code == 'bad_redirect'
