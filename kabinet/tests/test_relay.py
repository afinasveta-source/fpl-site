"""Тур-эстафета (решения 13.10): после срока Gold кабинет готовит раздачу — каждой участнице Silver (и вне конкурса) работа
участницы Gold в конкурсе; организатор проверяет, убирает неподходящие и отправляет; судья видит исходник рядом с работой."""
import random
from collections import Counter

from psycopg.types.json import Jsonb

from game_helpers import ORIGIN, add_docs, build_game, h, login, register, send_work, task_url
from test_judging import judges, ok
from test_org import org

from kabinet import relay


def relay_game(app, seed, clock, gold=('g1', 'g2', 'g3'), silver=('s1', 's2', 's3', 's4'), submit=('g1', 'g2')):
    """Тур 1 — эстафета Gold → Silver: Gold сдаёт до h(days=1), Silver открывается h(days=1, hours=1), срок h(days=3)."""
    with app.state.db.transaction() as conn:
        add_docs(conn)
        g = build_game(conn, rounds=1, leagues=('gold', 'silver'))
        conn.execute('''UPDATE assignment_variants SET release_rules=%s WHERE code='silver' AND assignment_id=%s''',
                     (Jsonb({'opens_at': h(days=1, hours=1).isoformat(), 'deadline': h(days=3).isoformat()}), g['tasks'][0]))
        conn.execute('''UPDATE assignment_variants SET release_rules=%s WHERE code='gold' AND assignment_id=%s''',
                     (Jsonb({'deadline': h(days=1).isoformat()}), g['tasks'][0]))
        conn.execute("UPDATE rounds SET settings=%s, deadline=%s, judging_deadline=%s WHERE id=%s",
                     (Jsonb({'relay': {'from': 'gold', 'to': 'silver'}}), h(days=3), h(days=5), g['rounds'][0]))
    people = {}
    clock.set(h())
    for n in gold + silver:
        p = login(app, seed, f'{n}@example.com')
        ok(register(p, g['event']), 201)
        people[n] = p
    with app.state.db.transaction() as conn:
        for n in gold + silver:
            conn.execute('''UPDATE event_participants p SET entry_league=%s FROM users u
WHERE u.id=p.user_id AND u.email=%s''', ('gold' if n in gold else 'silver', f'{n}@example.com'))
    for i, n in enumerate(submit):
        send_work(people[n], g, 0, color=(30 * i, 90, 150))
    return g, people


def rnd_of(conn, g):
    return conn.execute('SELECT * FROM rounds WHERE id=%s', (g['rounds'][0],)).fetchone()


def given(app, g):
    with app.state.db.transaction() as conn:
        return conn.execute('''SELECT ea.recipient_event_participant_id AS ep, ei.event_participant_id AS author, ei.id AS item
FROM exchange_assignments ea JOIN exchange_items ei ON ei.id=ea.exchange_item_id WHERE ea.round_id=%s AND ea.active''',
                            (g['rounds'][0],)).fetchall()



def ep_of(app, email):
    with app.state.db.transaction() as conn:
        return conn.execute('''SELECT p.* FROM event_participants p JOIN users u ON u.id=p.user_id WHERE u.email=%s''',
                            (email,)).fetchone()


def make_outside(app, email, at):
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='admin',
out_of_competition_at=%s, out_of_competition_source='admin' WHERE id=%s''', (at, ep_of(app, email)['id']))


def test_check_then_release_only_competition_works(app, seed, clock):
    g, people = relay_game(app, seed, clock, submit=('g1', 'g2', 'g3'))
    make_outside(app, 's4@example.com', h())          # вне конкурса во второй лиге — исходник ей тоже положен
    make_outside(app, 'g3@example.com', h(hours=1))  # вне конкурса в первой лиге — её работа исходником не бывает
    c = org(app, seed)
    url = f"/api/org/rounds/{g['rounds'][0]}/relay"
    assert c.post(url + '/prepare', headers=ORIGIN).json()['detail'] == 'relay_not_ready'     # Gold ещё сдаёт
    clock.set(h(days=1, hours=2))
    t = ok(people['s1'].get(task_url(g, 0)))           # открылось, но исходник ещё не отправлен
    assert t['source'] is None and t['window']['reason'] == 'source_pending'
    with app.state.db.transaction() as conn:          # сверка готовит черновик — участницы его не видят
        assert relay.distribute(conn, rnd_of(conn, g), h(days=1, hours=2), rng=random.Random(1)) == 4
    assert ok(people['s1'].get(task_url(g, 0)))['window']['reason'] == 'source_pending'
    d = ok(c.get(url))
    assert not d['overview']['released'] and d['overview']['sources'] == 2 and d['overview']['given'] == 4
    authors = {it['author'] for it in d['items']}
    assert len(d['items']) == 2 and all(sum(len(it['recipients']) for it in d['items']) == 4 for _ in [0])
    g3 = ep_of(app, 'g3@example.com')['id']
    assert g3 not in {r['author'] for r in given(app, g)}                     # только работы в конкурсе
    photo = d['items'][0]['photos'][0]['view_url'].replace(app.state.settings.root_path, '')
    assert people['s1'].get(photo).status_code == 404                        # черновик не виден
    # организатор убирает одну работу — раздача пересобирается на оставшуюся
    bad = d['items'][0]['id']
    assert c.post(f'{url}/items/{bad}', headers=ORIGIN, json={'excluded': True}).json()['detail'] == 'reason_required'
    d = ok(c.post(f'{url}/items/{bad}', headers=ORIGIN, json={'excluded': True, 'reason': 'Размытое фото'}))
    assert d['overview']['sources'] == 1 and d['overview']['excluded'] == 1
    assert {str(r['item']) for r in given(app, g)} == {d['items'][1]['id'] if d['items'][0]['excluded'] else d['items'][0]['id']}
    d = ok(c.post(f'{url}/items/{bad}', headers=ORIGIN, json={'excluded': False}))     # вернула
    assert d['overview']['sources'] == 2
    ok(c.post(url + '/prepare', headers=ORIGIN))                                      # перераздать заново
    d = ok(c.post(url + '/release', headers=ORIGIN))
    assert d['overview']['released'] and d['overview']['given'] == 4
    rows = given(app, g)
    assert sorted(Counter(r['author'] for r in rows).values()) == [2, 2]
    assert ep_of(app, 's4@example.com')['id'] in {r['ep'] for r in rows}
    t = ok(people['s1'].get(task_url(g, 0)))
    assert t['source'] and t['source']['league'] == 'gold' and t['window']['open']
    photo = t['source']['photos'][0]['view_url'].replace(app.state.settings.root_path, '')
    assert people['s1'].get(photo).status_code == 200 and people['g3'].get(photo).status_code == 404
    assert any('исходник' in str(n) for n in ok(people['s2'].get('/api/notifications'))['notifications'])
    assert c.post(url + '/prepare', headers=ORIGIN).json()['detail'] == 'relay_released'
    send_work(people['s1'], g, 0, color=(1, 2, 3))
    assert 'source' not in ok(people['g1'].get(task_url(g, 0)))           # автор не видит, кому досталась её работа
    assert authors


def test_no_competition_works_cannot_release(app, seed, clock):
    g, people = relay_game(app, seed, clock, gold=('g1',), silver=('s1',), submit=())
    c = org(app, seed)
    clock.set(h(days=1, hours=2))
    t = ok(people['s1'].get(task_url(g, 0)))
    assert t['source'] is None and t['window']['reason'] == 'source_pending'
    url = f"/api/org/rounds/{g['rounds'][0]}/relay"
    assert c.post(url + '/release', headers=ORIGIN).json()['detail'] == 'relay_no_sources'
    photo = people['s1'].post('/api/uploads', content=__import__('game_helpers').jpeg(), headers={'Content-Type': 'image/jpeg', **ORIGIN}).json()
    r = people['s1'].put(task_url(g, 0) + '/draft', headers=ORIGIN, json={'photos': [photo['id']]})
    assert r.status_code == 409 and r.json()['detail'] == 'source_pending'
    assert any('исходники' in a['title'] for a in ok(c.get('/api/org/home'))['alerts'])


def test_org_relay_settings_and_judge_sees_source(app, seed, clock):
    g, people = relay_game(app, seed, clock)
    c = org(app, seed)
    url = f"/api/org/rounds/{g['rounds'][0]}"
    view = ok(c.get(url))
    assert view['relay']['from'] == 'gold' and view['relay']['waiting'] == 4 and not view['relay']['started']
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE assignment_variants SET release_rules=%s WHERE code='silver' AND assignment_id=%s''',
                     (Jsonb({'opens_at': h(hours=12).isoformat(), 'deadline': h(days=3).isoformat()}), g['tasks'][0]))
    assert 'relay_opens_before_source_deadline' in ok(c.get(url))['checks']['problems']
    assert c.put(url + '/relay', headers=ORIGIN, json={'source': 'gold', 'target': 'silver'}).json()['detail'] == \
        'relay_opens_before_source_deadline'
    assert c.put(url + '/relay', headers=ORIGIN, json={'source': 'gold', 'target': 'gold'}).status_code == 422
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE assignment_variants SET release_rules=%s WHERE code='silver' AND assignment_id=%s''',
                     (Jsonb({'opens_at': h(days=1, hours=1).isoformat(), 'deadline': h(days=3).isoformat()}), g['tasks'][0]))
    clock.set(h(days=1, hours=2))
    ok(c.post(url + '/relay/release', headers=ORIGIN))
    for n in ('s1', 's2', 's3'):
        ok(people[n].get(task_url(g, 0)))
        send_work(people[n], g, 0, color=(5 * len(n), 7, 9))
    v = ok(c.get(url))['relay']
    assert v['started'] and v['released'] and v['given'] == 4 and v['sources'] == 2
    assert c.put(url + '/relay', headers=ORIGIN, json={'source': None, 'target': None}).json()['detail'] == 'relay_started'
    clock.set(h(days=3, hours=1))
    js = judges(app, seed, 1)
    jurl = url + '/judging'
    ok(c.put(jurl, headers=ORIGIN, json={'method': 'pairwise', 'pools': 'leagues', 'per_target': 2,
                                         'judges': {'gold': [js[0][0]], 'silver': [js[0][0]]}, 'quota': {}}))
    ok(c.post(jurl + '/start', headers=ORIGIN))
    jc = js[0][1]
    streams = {s['league']: s for s in ok(jc.get('/api/judging'))['streams']}
    s = ok(jc.get(f"/api/judging/streams/{streams['silver']['id']}"))
    assert s['next']['a']['source'] and s['next']['b']['source']
    assert jc.get(s['next']['a']['source'][0]['view_url'].replace(app.state.settings.root_path, '')).status_code == 200
    g_stream = ok(jc.get(f"/api/judging/streams/{streams['gold']['id']}"))
    assert g_stream['next']['a']['source'] is None
    org_view = ok(c.get(jurl))
    silver_rows = next(st for st in org_view['streams'] if st['league'] == 'silver')['rows']
    assert all(r['source'] for r in silver_rows)


def test_after_release_newcomer_gets_sent_work_no_deadlock(app, seed, clock):
    """После отправки: пришедшей позже (перевели в Silver) — одна из уже отправленных работ, не своя; сверка не ждёт
    участницу, которая держит свою запись (открывает задание)."""
    import threading
    import psycopg
    from psycopg.rows import dict_row
    g, people = relay_game(app, seed, clock, gold=('g1', 'g2', 'g3'), silver=('s1', 's2'), submit=('g1', 'g2'))
    c = org(app, seed)
    clock.set(h(days=1, hours=2))
    ok(c.post(f"/api/org/rounds/{g['rounds'][0]}/relay/release", headers=ORIGIN))
    g1, g3 = ep_of(app, 'g1@example.com')['id'], ep_of(app, 'g3@example.com')['id']
    ok(c.post(f'/api/org/participants/{g1}/league', headers=ORIGIN, json={'league': 'silver'}))
    ok(c.post(f'/api/org/participants/{g3}/league', headers=ORIGIN, json={'league': 'silver'}))
    dsn = app.state.settings.database_dsn.get_secret_value()
    a = psycopg.connect(dsn, row_factory=dict_row)
    b = psycopg.connect(dsn, row_factory=dict_row)
    now = h(days=1, hours=3)
    rnd = a.execute('SELECT * FROM rounds WHERE id=%s', (g['rounds'][0],)).fetchone()
    a.execute('SELECT id FROM event_participants WHERE id=%s FOR UPDATE', (g3,))
    out = {}

    def sync():
        try:
            out['n'] = relay.distribute(b, rnd, now)
            b.commit()
        except Exception as exc:   # noqa: BLE001
            out['err'] = exc
    t = threading.Thread(target=sync)
    t.start()
    t.join(10)
    assert not t.is_alive() and 'err' not in out and out['n'] == 1          # g1 получила; g3 занята — пропущена
    assert relay.distribute(a, rnd, now, only_ep=g3) == 1
    a.commit()
    a.close()
    b.close()
    rows = {r['ep']: r for r in given(app, g)}
    assert rows[g1]['author'] != g1 and rows[g3]['author'] in {ep_of(app, 'g2@example.com')['id'], g1}
