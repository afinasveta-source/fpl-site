"""Этап 5: итоги Игры — формат, черновик, публикация, очки FPL, дипломы, что видит участница."""
from game_helpers import ORIGIN, h, login, register, send_work
from test_judging import judges, strength, vote_all
from test_org import game_ready, ok, org, publish_docs

NAMES = ['ann', 'bea', 'cat', 'dia', 'eve']
LEAGUES = {'ann': 'gold', 'bea': 'gold', 'cat': 'gold', 'dia': 'silver', 'eve': 'silver'}


def game_with_season(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    season = ok(c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Сезон 1', 'season_no': 1}), 201)
    eid, rounds = game_ready(c, rounds=2)
    ok(c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'season_id': season['id'], 'game_no': 2}))
    return c, eid, rounds


def test_format_before_start_only(app, seed, clock):
    c, eid, rounds = game_with_season(app, seed, clock)
    url = f'/api/org/events/{eid}/results'
    v = ok(c.get(url))
    assert v['config']['final_round'] == 2 and v['config']['path_rounds'] == [1] and v['config']['path_weight'] == 40
    assert v['config_editable'] and 'game_not_finished' in v['checks']['problems']
    v = ok(c.put(url + '/format', headers=ORIGIN, json={'final_round': 2, 'path_rounds': [1, 2], 'path_weight': 30,
                                                       'points': {'places': {'bronze': [9, 7, 5]}, 'top10': 10}}))
    cfg = v['config']
    assert cfg['path_rounds'] == [1] and cfg['path_weight'] == 30 and cfg['points']['places']['bronze'] == [9, 7, 5]
    assert cfg['points']['places']['gold'] == [20, 15, 12] and cfg['points']['top10'] == 10 and cfg['points']['top25'] == 5
    assert c.put(url + '/format', headers=ORIGIN, json={'final_round': 7}).json()['detail'] == 'unknown_round'
    assert c.put(url + '/format', headers=ORIGIN, json={'no_final': True}).json()['detail'] == 'no_rounds'
    assert c.put(url + '/format', headers=ORIGIN, json={'points': {'places': {'gold': [1, 2]}}}).status_code == 422
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    assert c.put(url + '/format', headers=ORIGIN, json={'path_weight': 50}).json()['detail'] == 'locked_after_start'
    p = login(app, seed, 'x@example.com')
    assert p.get(url).status_code == 403


def test_game_results_flow(app, seed, clock):
    c, eid, rounds = game_with_season(app, seed, clock)
    # маленькая тестовая Игра: TOP-10 включаем с 1 человека (по умолчанию — от 30)
    ok(c.put(f'/api/org/events/{eid}/results/format', headers=ORIGIN, json={'final_round': 2, 'path_rounds': [1], 'path_weight': 40,
                                                                          'points': {'top10_min': 1}}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    people = {}
    for n in NAMES:
        p = login(app, seed, f'{n}@example.com')
        ok(register(p, eid), 201)
        people[n] = p
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    lst = {x['email'].split('@')[0]: x for x in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    for n, lg in LEAGUES.items():
        ok(c.post(f"/api/org/participants/{lst[n]['id']}/league", headers=ORIGIN, json={'league': lg}))
    for n, p in people.items():
        g = ok(p.get(f'/api/games/{eid}'))
        send_work(p, {'event': eid, 'tasks': [g['rounds'][0]['assignment_id']]}, 0, color=(10 * len(n), 20, 30))
    js = judges(app, seed, 3)
    # тур 1 — пары, общий пул, проходят 4 (eve — слабейшая — выбывает)
    url1 = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url1, headers=ORIGIN, json={'method': 'pairwise', 'pools': 'common', 'per_target': 2,
                                         'judges': {'all': [j for j, _ in js]}, 'quota': {'all': 4}}))
    clock.set(h(days=1, minutes=5))
    st = ok(c.post(url1 + '/start', headers=ORIGIN))['streams'][0]
    power = strength(app, NAMES)
    for _, jc in js:
        vote_all(app, jc, st['id'], power)
    v = ok(c.get(url1))
    st = v['streams'][0]
    if st['border']['status'] != 'ok':
        tied = st['border']['tied'] or st['border']['unjudged']
        weakest = min(tied, key=lambda t: power[t])
        ok(c.post(f"/api/org/judging/streams/{st['id']}/decision", headers=ORIGIN,
                  json={'targets': tied, 'advance': [t for t in tied if t != weakest], 'reason': 'тест'}))
    ok(c.post(url1 + '/publish', headers=ORIGIN))
    assert ok(people['eve'].get(f'/api/games/{eid}'))['me']['mode'] == 'out_pending'
    # тур 2 — финал: сдают четверо, критерии 1–100
    clock.set(h(days=2, minutes=5))
    for n in ('ann', 'bea', 'cat', 'dia'):
        g = ok(people[n].get(f'/api/games/{eid}'))
        send_work(people[n], {'event': eid, 'tasks': [g['rounds'][1]['assignment_id']]}, 0)
    url2 = f'/api/org/rounds/{rounds[1]}/judging'
    ok(c.put(url2, headers=ORIGIN, json={'method': 'criteria', 'pools': 'common', 'criteria': [{'label': 'Идея', 'weight': 1}],
                                         'judges': {'all': [js[0][0]]}}))
    clock.set(h(days=4, minutes=5))
    st2 = ok(c.post(url2 + '/start', headers=ORIGIN))['streams'][0]
    marks = {'ann': 95, 'bea': 70, 'cat': 60, 'dia': 80}
    with app.state.db.transaction() as conn:
        who = {r['email'].split('@')[0]: str(r['id']) for r in conn.execute('''SELECT t.id, u.email FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id JOIN event_participants p ON p.id=m.event_participant_id
JOIN users u ON u.id=p.user_id WHERE t.evaluation_stream_id=%s''', (st2['id'],))}
    for n, v_ in marks.items():
        ok(js[0][1].post(f"/api/judging/streams/{st2['id']}/works/{who[n]}", headers=ORIGIN, json={'scores': {'c1': v_}}))
    ok(c.post(url2 + '/publish', headers=ORIGIN))

    url = f'/api/org/events/{eid}/results'
    v = ok(c.get(url))
    assert 'game_not_finished' in v['checks']['problems'] and not v['config_editable']
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'finish'}))
    # Игра, перенесённая из бота, — итоги не пересчитываются
    with app.state.db.transaction() as conn:
        rid = conn.execute('SELECT id FROM round_results WHERE event_id=%s LIMIT 1', (eid,)).fetchone()['id']
        conn.execute('''UPDATE round_results SET calculation_snapshot=calculation_snapshot || '{"source":"salebot"}' WHERE id=%s''', (rid,))
    assert 'imported_game' in ok(c.get(url))['checks']['problems']
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE round_results SET calculation_snapshot=calculation_snapshot - 'source' WHERE id=%s", (rid,))
    v = ok(c.get(url))
    assert v['checks']['problems'] == [], v['checks']
    rows = {r['name'].split('@')[0] if '@' in r['name'] else r['name']: r for r in v['rows']}
    by = {lst[n]['id']: n for n in NAMES}
    rows = {by[r['id']]: r for r in v['rows']}
    # итог 40/60: путь — балл тура 1, финал — оценка
    for n in ('ann', 'bea', 'cat', 'dia'):
        r = rows[n]
        assert r['finalist'] and abs(r['total'] - round(0.4 * r['scores']['1'] + 0.6 * r['scores']['2'], 2)) < 0.011
    assert not rows['eve']['finalist'] and rows['eve']['overall_rank'] is None and rows['eve']['excluded'] == 'not_qualified_round1'
    assert rows['ann']['award_place'] == 1 and rows['dia']['award_place'] == 1        # 1 место в каждой лиге
    assert {rows['bea']['award_place'], rows['cat']['award_place']} == {2, 3}
    # равенства нет — решение не принимается
    assert c.post(url + '/tie', headers=ORIGIN, json={'league': 'gold', 'order': [lst['bea']['id'], lst['cat']['id']],
                                                      'reason': 'x'}).json()['detail'] == 'tie_targets'
    # очки: ann — 1 место Gold (20) + TOP WORK; dia — 1 место Silver (12); eve — нет достижений (не все работы сданы)
    assert rows['ann']['points']['result'] == 20 and rows['dia']['points']['result'] == 12 and rows['eve']['points']['best'] is None   # в Silver 2 человека: 20% = 0, TOP-10 нет
    assert rows['eve']['diploma'] is False and rows['ann']['diploma'] is True and rows['ann']['counted'] is True

    v = ok(c.post(url + '/publish', headers=ORIGIN))
    assert v['summary']['diplomas'] == 4 and v['published_at']
    assert c.post(url + '/publish', headers=ORIGIN).json()['detail'] == 'already_published'
    assert c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'reopen'}).json()['detail'] == 'results_published'
    pub = {by[r['id']]: r for r in v['rows']}
    assert pub['ann']['certificate'] == 'FPL-S1-02-G-0001' and pub['dia']['certificate'] == 'FPL-S1-02-S-0001'
    assert pub['eve']['certificate'] is None
    # участница видит итог Игры: место, диплом, очки
    g = ok(people['ann'].get(f'/api/games/{eid}'))
    res = g['result']
    assert res['award_place'] == 1 and res['league'] == 'gold' and res['diploma'] == 'FPL-S1-02-G-0001'
    assert res['diploma_title'] == 'Победитель, 1 место' and res['points'] == 20 + res['top_works']
    assert ok(people['eve'].get(f'/api/games/{eid}'))['result']['diploma'] is None
    with app.state.db.transaction() as conn:
        cert = conn.execute("SELECT * FROM certificates WHERE certificate_number='FPL-S1-02-G-0001'").fetchone()
        assert cert['issue_snapshot']['league'] == 'Gold' and cert['issue_snapshot']['place'] == 1
        u = conn.execute('SELECT display_name, full_name, email FROM users WHERE id=%s', (lst['ann']['user_id'],)).fetchone()
        # на сайт — только публичное имя (Политика 4.3); почта не попадает никуда
        assert cert['issue_snapshot']['public_name'] == u['display_name'] and u['email'] not in str(cert['issue_snapshot'])
        import pathlib
        conn.execute((pathlib.Path(__file__).resolve().parents[2] / 'server' / 'db' / 'site_views.sql').read_text(encoding='utf-8'))
        site = conn.execute('SELECT site_export_certificates() AS j').fetchone()['j']['certificates']['FPL-S1-02-G-0001']
        assert site['name'] == u['display_name'] and 'city' not in site and site['result'] == 'Победитель, 1 место'
        stats = conn.execute('SELECT lifetime_points FROM participant_stats WHERE user_id=%s', (lst['ann']['user_id'],)).fetchone()
        assert stats['lifetime_points'] == res['points']
        n = conn.execute("SELECT count(*) AS n FROM points_transactions WHERE event_id=%s AND reason_code='game_result'", (eid,)).fetchone()['n']
        assert n == 4                                                              # одно достижение у каждой, у кого оно есть
    titles = [x['title'] for x in ok(people['dia'].get('/api/notifications'))['notifications']]
    assert any(t.startswith('Итоги Игры') for t in titles)


def test_numbers_can_be_filled_after_start(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=1)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    e = ok(c.get(f'/api/org/events/{eid}'))
    assert {'no_season_number', 'no_game_number'} <= set(e['checks']['warnings'])
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    e = ok(c.get(f'/api/org/events/{eid}'))
    assert 'season_id' not in e['locked'] and 'game_no' not in e['locked'] and 'event_type' in e['locked']
    season = ok(c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Сезон 2', 'season_no': 2}), 201)
    ok(c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'season_id': season['id'], 'game_no': 5}))
    assert c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'game_no': 6}).json()['detail'] == 'locked_after_start'
    e = ok(c.get(f'/api/org/events/{eid}'))
    assert 'game_no' in e['locked'] and 'season_id' in e['locked']


def test_top_work_per_league_in_common_pool(app, seed, clock):
    """TOP WORK — в каждой лиге отдельно, даже когда тур судят общим пулом (решение 13.10)."""
    from test_judging import setup_game, stream_of
    gold = ['ga', 'gb', 'gc', 'gd', 'ge']
    silver = ['sa', 'sb', 'sc', 'sd', 'se']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, gold + silver,
                                             leagues={**{n: 'gold' for n in gold}, **{n: 'silver' for n in silver}})
    js = judges(app, seed, 1)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'method': 'criteria', 'pools': 'common', 'criteria': [{'label': 'Идея', 'weight': 1}],
                                        'judges': {'all': [js[0][0]]}}))
    clock.set(h(days=1, minutes=5))
    st = stream_of(ok(c.post(url + '/start', headers=ORIGIN)))
    with app.state.db.transaction() as conn:
        who = {r['email'].split('@')[0]: str(r['id']) for r in conn.execute('''SELECT t.id, u.email FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id JOIN event_participants p ON p.id=m.event_participant_id
JOIN users u ON u.id=p.user_id WHERE t.evaluation_stream_id=%s''', (st['id'],))}
    marks = dict(zip(gold, [99, 98, 97, 96, 95])) | dict(zip(silver, [50, 40, 30, 20, 10]))   # Gold вся выше Silver
    for n, v in marks.items():
        ok(js[0][1].post(f"/api/judging/streams/{st['id']}/works/{who[n]}", headers=ORIGIN, json={'scores': {'c1': v}}))
    rows = {r['name'].split('@')[0]: r for r in stream_of(ok(c.get(url)))['rows']}
    assert sorted(n for n, r in rows.items() if r['top_work']) == ['ga', 'sa']    # 20% от 5 в каждой лиге = 1
    ok(c.post(url + '/publish', headers=ORIGIN))
    with app.state.db.transaction() as conn:
        lg = conn.execute('''SELECT league FROM round_results rr JOIN event_participants p ON p.id=rr.event_participant_id
JOIN users u ON u.id=p.user_id WHERE rr.round_id=%s AND u.email='sa@example.com' ''', (rounds[0],)).fetchone()['league']
        assert lg == 'silver'                                                      # в итоге тура — лига участницы
