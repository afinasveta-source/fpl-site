"""Лента данных для инструмента контента (16.10): ключи организатора, только чтение, согласия, никаких личных данных,
фото по ключу только для разрешённых работ, предел частоты."""
import json

from fastapi.testclient import TestClient

from game_helpers import ORIGIN, h
from test_gallery import publish, setup
from test_org import ok

# Чего в ленте не должно быть ни в одном ответе (ни ключом, ни значением)
FORBIDDEN_KEYS = {'email', 'phone', 'full_name', 'telegram_id', 'contact', 'contacts', 'password', 'password_hash', 'ip',
                  'user_id', 'judge', 'judges_names', 'winner', 'winner_target_id', 'support', 'author_user_id'}


def walk(x, path=''):
    if isinstance(x, dict):
        for k, v in x.items():
            assert k not in FORBIDDEN_KEYS, f'{path}.{k}'
            walk(v, f'{path}.{k}')
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, f'{path}[{i}]')


def make_key(org, name='Codex — посты'):
    r = ok(org.post('/api/org/feed-keys', headers=ORIGIN, json={'name': name, 'comment': 'тест'}), 201)
    return r['key'], r['item']


def feed(app, key):
    c = TestClient(app)
    c.headers['Authorization'] = f'Bearer {key}'
    return c


def test_key_lifecycle(app, seed, clock):
    from game_helpers import login
    org = login(app, seed, 'org@example.com', roles=('admin',))
    assert org.post('/api/org/feed-keys', json={'name': 'x'}).status_code == 403            # только со страницы кабинета
    key, item = make_key(org)
    assert key.startswith('fplf_') and len(key) >= 45 and item['active'] and item['hint'] == key[:9] + '…'
    listed = ok(org.get('/api/org/feed-keys'))['keys']
    assert len(listed) == 1 and key not in json.dumps(listed)                                # ключ виден только один раз
    with app.state.db.transaction() as conn:
        row = conn.execute('SELECT * FROM feed_keys').fetchone()
        import hashlib
        assert row['key_hash'] == hashlib.sha256(key.encode()).hexdigest() and key not in json.dumps({k: str(v) for k, v in row.items()})
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE action='feed_key_created'").fetchone()['n'] == 1
    f = feed(app, key)
    assert ok(f.get('/api/feed/games'))['schema'] == 'fpl.feed.games.v1'
    used = ok(org.get('/api/org/feed-keys'))['keys'][0]
    assert used['use_count'] == 1 and used['last_used_at']
    # без ключа, чужой ключ, другая схема, кука администратора — 401
    anon = TestClient(app)
    assert anon.get('/api/feed/games').status_code == 401
    assert feed(app, key + 'x').get('/api/feed/games').status_code == 401
    assert TestClient(app).get('/api/feed/games', headers={'Authorization': f'Basic {key}'}).status_code == 401
    assert TestClient(app).get('/api/feed/games', headers={'X-FPL-Key': key}).status_code == 401
    assert org.get('/api/feed/games').status_code == 401
    # только чтение
    for method in ('post', 'put', 'patch', 'delete'):
        assert getattr(f, method)('/api/feed/games').status_code in (404, 405)
    # участница ключи не видит и не создаёт
    p = login(app, seed, 'p@example.com')
    assert p.get('/api/org/feed-keys').status_code == 403
    assert p.post('/api/org/feed-keys', headers=ORIGIN, json={'name': 'x'}).status_code == 403
    # отозван — сразу 401
    ok(org.post(f"/api/org/feed-keys/{item['id']}/revoke", headers=ORIGIN))
    assert f.get('/api/feed/games').status_code == 401
    keys = ok(org.get('/api/org/feed-keys'))['keys']
    assert keys[0]['active'] is False and keys[0]['revoked_at']
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE action='feed_key_revoked'").fetchone()['n'] == 1


def test_feed_data_consent_and_no_pii(app, seed, clock):
    game, people, eps = setup(app, seed, clock)
    from game_helpers import login
    org = login(app, seed, 'org@example.com', roles=('admin',))
    key, _ = make_key(org)
    f = feed(app, key)
    base = f"/api/feed/games/{game['event']}"
    g = ok(f.get('/api/feed/games'))
    mine = next(x for x in g['games'] if x['id'] == str(game['event']))
    assert mine['running'] and 'п. 7.3' in g['rules_note'] and mine['participants']['total'] == 5
    r1 = mine['rounds'][0]
    assert r1['submitted']['total'] == 5 and r1['results_published'] is False
    assert f.get(base + '/rounds/1/results').status_code == 404                      # итоги тура ещё не опубликованы
    publish(app, game, eps)
    with app.state.db.transaction() as conn:   # d (отозвала согласие) и x (дисквалифицирована) — тоже с итогом тура
        for k in ('d', 'x'):
            conn.execute('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,is_current,status,display_score,
advanced,league,calculation_snapshot,published_at) VALUES (%s,%s,%s,1,true,'published',50,false,'silver','{}',%s)''',
                         (game['event'], game['rounds'][0], eps[k]['id'], h()))
        conn.execute("UPDATE users SET public_social=false WHERE email='c@example.com'")
        conn.execute("UPDATE users SET public_city=true, city='Казань', country_code='RU' WHERE email='a@example.com'")
    res = ok(f.get(base + '/rounds/1/results'))
    from kabinet.feed import pid
    by = {next(k for k in eps if pid(eps[k]['user_id']) == x['participant']['id']): x for x in res['results']}
    assert set(by) == {'a', 'b', 'c', 'd', 'x'}
    a = by['a']
    assert a['participant']['name'] == 'Анна Альфа' and a['top_work'] and a['league'] == 'gold' and a['score'] == 77.5
    assert a['can_show_work'] and a['can_post_social'] and a['participant']['city'] is None   # город — только с согласием на анкету
    assert len(a['photos']) == 1 and '/api/feed/media/' in a['photos'][0]['url'] and a['photos'][0]['url'].endswith('?size=view')
    assert by['b']['participant']['name'] == 'Бэлла Борисова'                          # без публичного имени — «Имя Фамилия»
    assert by['c']['can_show_work'] and by['c']['photos'] and not by['c']['can_post_social']   # работы можно, соцсети — нет
    d = by['d']                                                                         # отозвала согласие: без имени и фото
    assert d['participant']['name'] is None and not d['photos'] and not d['can_show_work'] and not d['can_post_social']
    assert not by['x']['photos'] and not by['x']['can_show_work'] and not by['x']['can_post_social']   # дисквалифицирована
    # фото по ключу: разрешённая работа — да (view и thumb), запрещённая — 404, без ключа — 401
    assert f.get(a['photos'][0]['url'].replace('/kabinet', '')).status_code == 200
    assert f.get(a['photos'][0]['thumb_url']).headers['content-type'] == 'image/jpeg'
    assert f.get(a['photos'][0]['url'].replace('size=view', 'size=orig')).status_code == 422
    assert TestClient(app).get(a['photos'][0]['url']).status_code == 401
    for k in ('d', 'x'):
        assert f.get(f"/api/feed/media/{people[k]['photo']['id']}?size=view").status_code == 404
    # остальные выдачи — без личных данных
    with app.state.db.transaction() as conn:
        conn.execute('''INSERT INTO participant_stats(user_id,current_rating,calibration_rounds_completed,rating_status)
SELECT user_id, 600 - row_number() OVER (ORDER BY joined_at) * 10, 2, 'calibrating' FROM event_participants WHERE event_id=%s''', (game['event'],))
        conn.execute('''INSERT INTO rating_transactions(user_id,event_id,round_id,method,formula_version,rating_before,delta_after_cap,rating_after,
status,idempotency_key) SELECT user_id, event_id, %s, 'pairwise_elo', 'test', 500, 12, 512, 'active', 'feed:' || id FROM event_participants
WHERE event_id=%s''', (game['rounds'][0], game['event']))
        conn.execute('''INSERT INTO points_transactions(user_id,event_id,lifetime_delta,reason_code,reason_text,idempotency_key)
SELECT user_id, event_id, 1, 'top_work', 'TOP WORK Gold · Игра 02', 'feed-pt:' || id FROM event_participants WHERE id=%s''', (eps['a']['id'],))
    rating = ok(f.get('/api/feed/rating'))
    assert rating['rated'] == 5 and [p['rank'] for p in rating['players']] == [1, 2, 3, 4, 5]
    assert {p['participant']['id'] for p in rating['players'] if not p['can_publish']} == {pid(eps['d']['user_id'])} and rating['games_running'] == ['Игра 02']
    hist = ok(f.get('/api/feed/rating/history', params={'game': str(game['event'])}))
    assert all(x['rounds'][0]['delta'] == 12 for x in hist['participants'])
    pts = ok(f.get('/api/feed/points'))
    assert pts['participants'][0]['participant']['name'] == 'Анна Альфа' and pts['participants'][0]['total'] == 1 and len(pts['participants']) == 1
    st = ok(f.get(base + '/standings'))
    assert st['game']['results_published'] is False and st['rows'] == []
    stats = ok(f.get('/api/feed/stats'))
    everything = [g, res, rating, hist, pts, st, stats]
    walk(everything)
    dumped = json.dumps(everything, ensure_ascii=False)
    with app.state.db.transaction() as conn:
        secrets_ = [r['email'] for r in conn.execute('SELECT email FROM users WHERE email IS NOT NULL')] + \
                   [str(r['id']) for r in conn.execute('SELECT id FROM users')] + ['Борисова Бэлла Игоревна', 'Казань']
    assert not [s for s in secrets_ if s in dumped]


def test_feed_rate_limit(app, seed, clock):
    from game_helpers import login
    org = login(app, seed, 'org@example.com', roles=('admin',))
    key, _ = make_key(org)
    app.state.settings.feed_rate_limit = 5
    try:
        f = feed(app, key)
        assert [f.get('/api/feed/stats').status_code for _ in range(6)] == [200] * 5 + [429]
        key2, _ = make_key(org, 'второй')
        assert feed(app, key2).get('/api/feed/stats').status_code == 200                # предел — на ключ
    finally:
        app.state.settings.feed_rate_limit = 120
