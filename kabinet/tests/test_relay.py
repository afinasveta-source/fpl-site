"""Тур-эстафета (решение 13.10): после срока Gold каждой участнице Silver выдаётся работа Gold как исходник —
и в конкурсе, и вне конкурса; судья видит исходник рядом с работой."""
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


def ep_of(app, email):
    with app.state.db.transaction() as conn:
        return conn.execute('''SELECT p.* FROM event_participants p JOIN users u ON u.id=p.user_id WHERE u.email=%s''',
                            (email,)).fetchone()


def test_relay_sources_to_everyone_in_second_league(app, seed, clock):
    g, people = relay_game(app, seed, clock)
    with app.state.db.transaction() as conn:   # s4 — вне конкурса: исходник ей тоже положен (дыра бота 03.10)
        conn.execute('''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='admin',
out_of_competition_at=%s, out_of_competition_source='admin' WHERE id=%s''', (h(), ep_of(app, 's4@example.com')['id']))
    # пока Gold сдаёт — у Silver задание закрыто, исходников нет
    t = ok(people['s1'].get(task_url(g, 0)))
    assert t['source'] is None and t['instructions'] is None
    clock.set(h(days=1, hours=2))
    t = ok(people['s1'].get(task_url(g, 0)))                     # первое открытие — исходник выдан ей
    assert t['source'] and t['source']['league'] == 'gold' and len(t['source']['photos']) == 1
    photo = t['source']['photos'][0]['view_url'].replace(app.state.settings.root_path, '')
    assert people['s1'].get(photo).status_code == 200            # получательница видит исходник
    assert people['g3'].get(photo).status_code == 404            # посторонняя — нет
    assert t['window']['open']
    with app.state.db.transaction() as conn:                     # сверка раздаёт остальным
        rnd = conn.execute('SELECT * FROM rounds WHERE id=%s', (g['rounds'][0],)).fetchone()
        assert relay.distribute(conn, rnd, h(days=1, hours=2), rng=random.Random(1)) == 3
        assert relay.distribute(conn, rnd, h(days=1, hours=2)) == 0          # повтор ничего не меняет
        rows = conn.execute('''SELECT ea.recipient_event_participant_id AS ep, ei.event_participant_id AS author
FROM exchange_assignments ea JOIN exchange_items ei ON ei.id=ea.exchange_item_id WHERE ea.round_id=%s AND ea.active''',
                            (g['rounds'][0],)).fetchall()
    authors = Counter(r['author'] for r in rows)
    assert len(rows) == 4 and sorted(authors.values()) == [2, 2]           # 4 получательницы на 2 работы — поровну
    assert ep_of(app, 'g3@example.com')['id'] not in authors              # не сдавшая — не исходник
    assert ep_of(app, 's4@example.com')['id'] in {r['ep'] for r in rows}  # вне конкурса — тоже получила
    send_work(people['s1'], g, 0, color=(1, 2, 3))                         # сдаёт по исходнику
    # автор (Gold) не видит, кому досталась её работа: в её задании исходника нет
    assert 'source' not in ok(people['g1'].get(task_url(g, 0)))


def test_no_source_blocks_submission(app, seed, clock):
    g, people = relay_game(app, seed, clock, gold=('g1',), silver=('s1',), submit=())
    clock.set(h(days=1, hours=2))
    t = ok(people['s1'].get(task_url(g, 0)))
    assert t['source'] is None and t['window'] == {'open': False, 'reason': 'no_source', 'deadline': t['window']['deadline'],
                                                    'source': t['window']['source']}
    photo = people['s1'].post('/api/uploads', content=__import__('game_helpers').jpeg(), headers={'Content-Type': 'image/jpeg', **ORIGIN}).json()
    r = people['s1'].put(task_url(g, 0) + '/draft', headers=ORIGIN, json={'photos': [photo['id']]})
    assert r.status_code == 409 and r.json()['detail'] == 'no_source'


def test_org_relay_settings_and_judge_sees_source(app, seed, clock):
    g, people = relay_game(app, seed, clock)
    c = org(app, seed)
    url = f"/api/org/rounds/{g['rounds'][0]}"
    view = ok(c.get(url))
    assert view['relay']['from'] == 'gold' and view['relay']['waiting'] == 4 and not view['relay']['started']
    # Silver не может открыться раньше срока Gold
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
    for n in ('s1', 's2', 's3'):
        ok(people[n].get(task_url(g, 0)))
        send_work(people[n], g, 0, color=(5 * len(n), 7, 9))
    v = ok(c.get(url))['relay']
    assert v['started'] and v['given'] == 3 and v['sources'] == 2
    assert c.put(url + '/relay', headers=ORIGIN, json={'source': None, 'target': None}).json()['detail'] == 'relay_started'
    # судейство Silver после срока: судья видит исходник рядом с работой
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
    assert g_stream['next']['a']['source'] is None                       # у первой лиги исходника нет
    org_view = ok(c.get(jurl))
    silver_rows = next(st for st in org_view['streams'] if st['league'] == 'silver')['rows']
    assert all(r['source'] for r in silver_rows)


def test_sync_skips_busy_participant_no_deadlock(app, seed, clock):
    """Сверка раздаёт исходники, пока участница держит свою запись (открывает задание) — без взаимной блокировки:
    занятую сверка пропускает, исходник ей выдаёт её же запрос."""
    import threading
    import psycopg
    from psycopg.rows import dict_row
    g, people = relay_game(app, seed, clock)
    s2 = ep_of(app, 's2@example.com')['id']
    dsn = app.state.settings.database_dsn.get_secret_value()
    a = psycopg.connect(dsn, row_factory=dict_row)
    b = psycopg.connect(dsn, row_factory=dict_row)
    now = h(days=1, hours=2)
    rnd = a.execute('SELECT * FROM rounds WHERE id=%s', (g['rounds'][0],)).fetchone()
    a.execute('SELECT id FROM event_participants WHERE id=%s FOR UPDATE', (s2,))
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
    assert not t.is_alive() and 'err' not in out and out['n'] == 3         # s2 занята — пропущена
    assert relay.distribute(a, rnd, now, only_ep=s2) == 1
    a.commit()
    a.close()
    b.close()


def test_league_change_and_own_work(app, seed, clock):
    g, people = relay_game(app, seed, clock, gold=('g1', 'g2'), silver=('s1', 's2'), submit=('g1', 'g2'))
    c = org(app, seed)
    clock.set(h(days=1, hours=2))
    ok(people['s1'].get(task_url(g, 0)))
    s1 = ep_of(app, 's1@example.com')['id']
    g1 = ep_of(app, 'g1@example.com')['id']
    ok(c.post(f'/api/org/participants/{s1}/league', headers=ORIGIN, json={'league': 'gold'}))     # s1 → Gold: выдача снята
    ok(c.post(f'/api/org/participants/{g1}/league', headers=ORIGIN, json={'league': 'silver'}))   # g1 → Silver: свою работу не получит
    with app.state.db.transaction() as conn:
        assert not relay.has_source(conn, g['rounds'][0], s1)
        rnd = conn.execute('SELECT * FROM rounds WHERE id=%s', (g['rounds'][0],)).fetchone()
        for _ in range(5):
            relay.distribute(conn, rnd, h(days=1, hours=2))
        got = conn.execute('''SELECT ei.event_participant_id AS author FROM exchange_assignments ea JOIN exchange_items ei ON ei.id=ea.exchange_item_id
WHERE ea.recipient_event_participant_id=%s AND ea.active''', (g1,)).fetchone()
    assert got and got['author'] != g1
