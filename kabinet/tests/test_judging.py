"""Этап 4: судейство тура — настройка, запуск, голоса судей, переголосование, решение, публикация, рейтинг."""
from game_helpers import ORIGIN, h, login, register, send_work
from test_org import game_ready, ok, org, publish_docs


def setup_game(app, seed, clock, names, leagues=None):
    """Идущая Игра, тур 1 открыт; участницы записаны и сдали работы. Возвращает (клиент орг., eid, туры, участницы)."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    people = {}
    for n in names:
        p = login(app, seed, f'{n}@example.com')
        ok(register(p, eid), 201)
        people[n] = p
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    lst = {x['email'].split('@')[0]: x for x in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    for n, lg in (leagues or {}).items():
        ok(c.post(f"/api/org/participants/{lst[n]['id']}/league", headers=ORIGIN, json={'league': lg}))
    for n, p in people.items():
        g = ok(p.get(f'/api/games/{eid}'))
        send_work(p, {'event': eid, 'tasks': [g['rounds'][0]['assignment_id']]}, 0, color=(10 * len(n), 20, 30))
    return c, eid, rounds, people, lst


def judges(app, seed, n=3):
    out = []
    for i in range(n):
        uid = seed(f'judge{i}@example.com', ('judge',))
        out.append((str(uid), login_only(app, f'judge{i}@example.com')))
    return out


def login_only(app, email):
    from fastapi.testclient import TestClient
    from conftest import PASSWORD
    c = TestClient(app)
    ok(c.post('/web-auth/login', headers=ORIGIN, json={'email': email, 'password': PASSWORD}))
    return c


def strength(app, names):
    """Цель → сила (чем раньше имя в списке, тем сильнее) — судьи голосуют за более сильную работу."""
    with app.state.db.transaction() as conn:
        rows = conn.execute('''SELECT t.id, u.email FROM evaluation_targets t JOIN evaluation_target_members m ON m.evaluation_target_id=t.id
JOIN event_participants p ON p.id=m.event_participant_id JOIN users u ON u.id=p.user_id''').fetchall()
    return {str(r['id']): len(names) - names.index(r['email'].split('@')[0]) for r in rows}


def vote_all(app, jc, stream_id, power, phase=None):
    """Судья голосует за все пары (по силе работы); номер работы для судьи — не имя, поэтому берём цель из базы."""
    with app.state.db.transaction() as conn:
        comps = {str(r['id']): r for r in conn.execute('SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s', (stream_id,))}
    n = 0
    while True:
        s = ok(jc.get(f'/api/judging/streams/{stream_id}'))
        nxt = s['next']
        if not nxt or (phase and nxt['phase'] != phase):
            return n
        c = comps[nxt['id']]
        win = 'a' if power[str(c['target_a_id'])] > power[str(c['target_b_id'])] else 'b'
        ok(jc.post(f"/api/judging/comparisons/{nxt['id']}", headers=ORIGIN, json={'winner': win}))
        n += 1


NAMES = ['ann', 'bea', 'cat', 'dia', 'eve', 'fay']


def test_pairwise_judging_flow(app, seed, clock):
    c, eid, rounds, people, lst = setup_game(app, seed, clock, NAMES)
    js = judges(app, seed)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    view = ok(c.get(url))
    assert not view['started'] and 'acceptance_not_over' in view['checks']['problems'] and 'no_judges' in view['checks']['problems']
    assert {j['id'] for j in view['judges']} >= {j for j, _ in js}
    # участница не может судить свою Игру
    ann_id = lst['ann']['user_id']
    assert c.put(url, headers=ORIGIN, json={'pools': 'common', 'judges': {'all': [ann_id]}}).json()['detail'] == 'judge_not_eligible'
    cfg = {'method': 'pairwise', 'pools': 'common', 'per_target': 2, 'judges': {'all': [j for j, _ in js]}, 'quota': {'all': 3}}
    view = ok(c.put(url, headers=ORIGIN, json=cfg))
    assert view['checks']['pools'] == [{'league': None, 'works': 6, 'judges': 3, 'quota': 3}]
    assert c.post(url + '/start', headers=ORIGIN).json()['detail'] == 'acceptance_not_over'
    clock.set(h(days=1, minutes=5))
    view = ok(c.post(url + '/start', headers=ORIGIN))
    assert view['started'] and len(view['streams']) == 1
    st = view['streams'][0]
    assert st['works'] == 6 and all(j['total'] == 6 for j in st['judges'])     # каждая работа — 2 раза у судьи
    assert c.put(url, headers=ORIGIN, json=cfg).json()['detail'] == 'judging_started'
    # участница больше не может заменить работу (приём в конкурсе закрыт)
    g = ok(people['ann'].get(f'/api/games/{eid}'))
    assert not g['rounds'][0]['can_submit']
    # судья видит только назначенное; фото работы — да, имени — нет
    jid, jc = js[0]
    home = ok(jc.get('/api/judging'))['streams']
    assert len(home) == 1 and home[0]['total'] == 6 and home[0]['done'] == 0
    s = ok(jc.get(f"/api/judging/streams/{st['id']}"))
    assert s['next'] and s['next']['a']['photos'] and 'name' not in s['next']['a'] and s['task']['title']
    photo = s['next']['a']['photos'][0]['thumb_url']
    assert jc.get(photo).status_code == 200
    stranger = login(app, seed, 'stranger@example.com')
    assert stranger.get(photo).status_code == 404
    assert stranger.get(f"/api/judging/streams/{st['id']}").status_code == 404
    # голосование
    power = strength(app, NAMES)
    publish_url = f'/api/org/rounds/{rounds[0]}/judging/publish'
    assert c.post(publish_url, headers=ORIGIN).json()['detail'] == 'votes_pending'
    for _, jc2 in js:
        assert vote_all(app, jc2, st['id'], power) == 6
    # повторный голос (смена решения) до публикации — можно
    first = ok(jc.get(f"/api/judging/streams/{st['id']}"))['voted'][0]
    ok(jc.post(f"/api/judging/comparisons/{first['id']}", headers=ORIGIN, json={'winner': first['winner']}))
    view = ok(c.get(url))
    st = view['streams'][0]
    assert st['pending'] == 0
    # пары жеребьёвки случайны: сильнейшая (ann) всегда без поражений, слабейшая (fay) — без побед;
    # Брэдли–Терри: баллы строго внутри 1–100 (поправка), без поражений — выше среднего, без побед — ниже
    by = {r['name'].split('@')[0]: r for r in st['rows']}
    assert by['ann']['wins'] == by['ann']['comparisons'] and by['fay']['wins'] == 0
    assert by['ann']['score'] > 51 > by['fay']['score'] and all(1 < r['score'] < 100 for r in st['rows'])
    assert st['rows'][0]['wins'] == st['rows'][0]['comparisons'] and st['rows'][0]['score'] == max(r['score'] for r in st['rows'])
    tops = [r for r in st['rows'] if r['top_work']]
    assert tops and all(r['wins'] == r['comparisons'] for r in tops)   # 20% от 6 = 1 (+ равные на границе)
    if st['border']['status'] == 'tie':
        tied = st['border']['tied']
        view = ok(c.post(f"/api/org/judging/streams/{st['id']}/tie-break", headers=ORIGIN, json={'targets': tied}))
        assert c.post(publish_url, headers=ORIGIN).json()['detail'] == 'tie_break_running'
        for _, jc2 in js:
            vote_all(app, jc2, st['id'], power, phase='tie_break')
        st = ok(c.get(url))['streams'][0]
    assert st['border']['status'] == 'ok' and sum(1 for r in st['rows'] if r['advanced']) == 3
    assert [r['advanced'] for r in st['rows']] == sorted([r['advanced'] for r in st['rows']], reverse=True)
    view = ok(c.post(publish_url, headers=ORIGIN))
    assert view['published']
    assert c.post(publish_url, headers=ORIGIN).json()['detail'] == 'already_published'
    # судья после публикации голос не меняет
    assert jc.post(f"/api/judging/comparisons/{first['id']}", headers=ORIGIN, json={'winner': 'a'}).json()['detail'] == 'judging_closed'
    # участница видит балл, рейтинг, калибровку, TOP WORK и проход — без места
    ga = ok(people['ann'].get(f'/api/games/{eid}'))
    res = ga['rounds'][0]['result']
    assert res['score'] == by['ann']['score'] and res['advanced'] is True and res['top_work'] == by['ann']['top_work'] and 'league_rank' not in res
    assert res['rating']['calibration'] == 1 and res['rating']['delta'] > 0 and res['rating']['before'] == 500
    gf = ok(people['fay'].get(f'/api/games/{eid}'))
    assert gf['rounds'][0]['result']['advanced'] is False and gf['me']['mode'] == 'out_pending'
    assert gf['rounds'][0]['result']['rating']['delta'] < 0
    titles = [n['title'] for n in ok(people['fay'].get('/api/notifications'))['notifications']]
    assert 'Итоги тура 1' in titles
    ach = ok(people['ann'].get('/api/achievements'))
    assert ach['rating']['value'] > 500 and ach['rating']['calibration'] == 1 and 'league_rank' not in ach['results'][0]
    with app.state.db.transaction() as conn:
        n = conn.execute("SELECT count(*) AS n FROM rating_transactions WHERE round_id=%s", (rounds[0],)).fetchone()['n']
        assert n == 6
        assert conn.execute("SELECT status FROM rounds WHERE id=%s", (rounds[0],)).fetchone()['status'] == 'published'


def test_criteria_by_league_replace_close_decision(app, seed, clock):
    names = ['ann', 'bea', 'cat', 'dia']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names,
                                             leagues={'ann': 'gold', 'bea': 'gold', 'cat': 'silver', 'dia': 'silver'})
    js = judges(app, seed, 3)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    crit = [{'label': 'Идея', 'weight': 2}, {'label': 'Техника', 'weight': 1}]
    cfg = {'method': 'criteria', 'pools': 'leagues', 'criteria': crit,
           'judges': {'gold': [js[0][0], js[1][0]], 'silver': [js[2][0]]}, 'quota': {'gold': 1, 'silver': 1}}
    ok(c.put(url, headers=ORIGIN, json=cfg))
    clock.set(h(days=1, minutes=5))
    view = ok(c.post(url + '/start', headers=ORIGIN))
    gold = next(s for s in view['streams'] if s['league'] == 'gold')
    silver = next(s for s in view['streams'] if s['league'] == 'silver')
    assert gold['works'] == 2 and silver['works'] == 2 and gold['method'] == 'criteria'
    # судья gold не видит silver
    assert js[0][1].get(f"/api/judging/streams/{silver['id']}").status_code == 404
    s = ok(js[0][1].get(f"/api/judging/streams/{gold['id']}"))
    codes = [x['code'] for x in s['criteria']]
    assert len(s['works']) == 2 and codes == ['c1', 'c2']
    w1, w2 = s['works']
    assert js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w1['id']}", headers=ORIGIN,
                         json={'scores': {'c1': 90}}).json()['detail'] == 'all_criteria_required'
    assert js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w1['id']}", headers=ORIGIN,
                         json={'scores': {'c1': 101, 'c2': 50}}).json()['detail'] == 'score_out_of_range'
    assert js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w1['id']}", headers=ORIGIN,
                         json={'scores': {'c1': 0, 'c2': 50}}).json()['detail'] == 'score_out_of_range'
    assert js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w1['id']}", headers=ORIGIN,
                         json={'scores': {'c1': 7.5, 'c2': 50}}).status_code == 422          # только целые
    ok(js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w1['id']}", headers=ORIGIN, json={'scores': {'c1': 90, 'c2': 60}}))
    ok(js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{w2['id']}", headers=ORIGIN, json={'scores': {'c1': 90, 'c2': 60}}))
    # второй судья gold пропал — замена: новый судья доделывает
    new = str(seed('judge9@example.com', ('judge',)))
    jn = login_only(app, 'judge9@example.com')
    ok(c.post(f"/api/org/judging/streams/{gold['id']}/replace", headers=ORIGIN,
              json={'old_user_id': js[1][0], 'new_user_id': new, 'reason': 'заболела'}))
    assert js[1][1].get(f"/api/judging/streams/{gold['id']}").status_code == 404
    s = ok(jn.get(f"/api/judging/streams/{gold['id']}"))
    for w in s['works']:
        ok(jn.post(f"/api/judging/streams/{gold['id']}/works/{w['id']}", headers=ORIGIN, json={'scores': {'c1': 70, 'c2': 70}}))
    # silver: судья оценил одну работу из двух — организатор закрывает недостающее? (критерии — нельзя закрыть,
    # поэтому дооцениваем)
    s = ok(js[2][1].get(f"/api/judging/streams/{silver['id']}"))
    ok(js[2][1].post(f"/api/judging/streams/{silver['id']}/works/{s['works'][0]['id']}", headers=ORIGIN, json={'scores': {'c1': 100, 'c2': 100}}))
    view = ok(c.get(url))
    assert 'votes_pending' in view['publish_problems']
    ok(js[2][1].post(f"/api/judging/streams/{silver['id']}/works/{s['works'][1]['id']}", headers=ORIGIN, json={'scores': {'c1': 50, 'c2': 20}}))
    view = ok(c.get(url))
    gold = next(x for x in view['streams'] if x['league'] == 'gold')
    # в gold обе работы равны (90/60 и 70/70 → у обеих (2·90+60)/3=80 и 70 → среднее 75) — граница не разведена
    assert gold['border']['status'] == 'tie' and 'border_tie' in view['publish_problems']
    a, b = gold['border']['tied']
    assert c.post(f"/api/org/judging/streams/{gold['id']}/decision", headers=ORIGIN,
                  json={'targets': [a, b], 'advance': [a], 'reason': ' '}).json()['detail'] == 'reason_required'
    view = ok(c.post(f"/api/org/judging/streams/{gold['id']}/decision", headers=ORIGIN,
                     json={'targets': [a, b], 'advance': [a], 'reason': 'Лучше раскрыта тема'}))
    gold = next(x for x in view['streams'] if x['league'] == 'gold')
    assert gold['border']['status'] == 'ok' and {r['target']: r['advanced'] for r in gold['rows']} == {a: True, b: False}
    assert view['publish_problems'] == []
    view = ok(c.post(f'/api/org/rounds/{rounds[0]}/judging/publish', headers=ORIGIN))
    silver_rows = next(x for x in view['streams'] if x['league'] == 'silver')['rows']
    assert [r['score'] for r in silver_rows] == [100, 40]          # (2·50+20)/3 = 40 — шкала 1–100 без пересчёта
    # рейтинг: пул из 2 работ меньше 3 — рейтинг не меняется
    assert ok(people['cat'].get(f'/api/games/{eid}'))['rounds'][0]['result']['rating'] is None
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM advancement_decisions WHERE method='admin'").fetchone()['n'] == 1


def test_start_checks_and_close_pending(app, seed, clock):
    names = ['ann', 'bea', 'cat', 'dia']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names, leagues={'ann': 'gold', 'bea': 'gold', 'cat': 'gold'})
    js = judges(app, seed, 2)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'pools': 'leagues', 'judges': {'gold': [j for j, _ in js]}}))
    clock.set(h(days=1, minutes=5))
    view = ok(c.get(url))
    assert 'participants_without_league' in view['checks']['problems'] and 'even_judges' in view['checks']['warnings']
    ok(c.put(url, headers=ORIGIN, json={'pools': 'common', 'judges': {'all': [j for j, _ in js]}, 'quota': {'all': 2}}))
    view = ok(c.post(url + '/start', headers=ORIGIN))
    st = view['streams'][0]
    power = strength(app, names)
    vote_all(app, js[0][1], st['id'], power)              # второй судья не голосует
    assert 'votes_pending' in ok(c.get(url))['publish_problems']
    assert c.post(f"/api/org/judging/streams/{st['id']}/tie-break", headers=ORIGIN,
                  json={'targets': [st['rows'][0]['target'], st['rows'][1]['target']]}).json()['detail'] == 'votes_pending'
    view = ok(c.post(f"/api/org/judging/streams/{st['id']}/close", headers=ORIGIN, json={'reason': 'судья не успела'}))
    st = view['streams'][0]
    assert st['pending'] == 0 and next(j for j in st['judges'] if j['user_id'] == js[1][0])['total'] == 0
    if st['border']['status'] == 'tie':
        tied = st['border']['tied']
        ok(c.post(f"/api/org/judging/streams/{st['id']}/decision", headers=ORIGIN,
                  json={'targets': tied, 'advance': tied[:1], 'reason': 'решение организатора'}))
    ok(c.post(f'/api/org/rounds/{rounds[0]}/judging/publish', headers=ORIGIN))
    # личный срок не прошёл — судейство не начать
    other = f'/api/org/rounds/{rounds[1]}/judging'
    ok(c.put(other, headers=ORIGIN, json={'pools': 'common', 'judges': {'all': [js[0][0]]}}))
    assert 'acceptance_not_over' in ok(c.get(other))['checks']['problems']


def stream_of(view, league=None):
    return next(s for s in view['streams'] if s['league'] == league)


def test_review_fixes_judging(app, seed, clock):
    """Пул из одной работы проходит; работа без оценки — решением; выбывшая во время судейства не занимает место;
    равные делят место; замена судьи не открывает чужие голоса; переголосование в пуле по критериям и его отмена."""
    names = ['ann', 'bea', 'cat', 'dia', 'eve']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names,
                                             leagues={'ann': 'gold', 'bea': 'silver', 'cat': 'silver', 'dia': 'silver', 'eve': 'silver'})
    js = judges(app, seed, 3)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'method': 'criteria', 'pools': 'leagues', 'criteria': [{'label': 'Идея', 'weight': 1}],
                                        'judges': {'gold': [js[0][0]], 'silver': [js[1][0], js[2][0]]}, 'quota': {'gold': 1, 'silver': 2}}))
    clock.set(h(days=1, minutes=5))
    view = ok(c.post(url + '/start', headers=ORIGIN))
    gold, silver = stream_of(view, 'gold'), stream_of(view, 'silver')
    # gold: одна работа — сравнивать не с кем, но оценки по критериям ставятся; проходит
    s = ok(js[0][1].get(f"/api/judging/streams/{gold['id']}"))
    ok(js[0][1].post(f"/api/judging/streams/{gold['id']}/works/{s['works'][0]['id']}", headers=ORIGIN, json={'scores': {'c1': 6}}))
    # silver: судья 1 ставит всем 5 (равенство), судья 2 — заменён до начала работы
    s = ok(js[1][1].get(f"/api/judging/streams/{silver['id']}"))
    for w in s['works']:
        ok(js[1][1].post(f"/api/judging/streams/{silver['id']}/works/{w['id']}", headers=ORIGIN, json={'scores': {'c1': 5}}))
    new = str(seed('judge9@example.com', ('judge',)))
    jn = login_only(app, 'judge9@example.com')
    ok(c.post(f"/api/org/judging/streams/{silver['id']}/replace", headers=ORIGIN,
              json={'old_user_id': js[2][0], 'new_user_id': new, 'reason': 'нет связи'}))
    s = ok(jn.get(f"/api/judging/streams/{silver['id']}"))
    for w in s['works']:
        ok(jn.post(f"/api/judging/streams/{silver['id']}/works/{w['id']}", headers=ORIGIN, json={'scores': {'c1': 5}}))
    # eve выходит из Игры во время судейства — за проход не борется
    ok(c.post(f"/api/org/participants/{lst['eve']['id']}/action", headers=ORIGIN, json={'action': 'withdraw', 'reason': 'сама'}))
    view = ok(c.get(url))
    silver = stream_of(view, 'silver')
    rows = {r['name'].split('@')[0]: r for r in silver['rows']}
    assert rows['eve']['left'] and rows['eve']['advanced'] is None
    assert {r['place'] for r in silver['rows'] if not r['left']} == {1}      # все равны — одно место на всех
    assert silver['border']['status'] == 'tie' and len(silver['border']['tied']) == 3   # bea, cat, dia; eve не в счёт
    # переголосование в пуле по критериям: судьи видят пары
    tied = silver['border']['tied']
    ok(c.post(f"/api/org/judging/streams/{silver['id']}/tie-break", headers=ORIGIN, json={'targets': tied}))
    s = ok(jn.get(f"/api/judging/streams/{silver['id']}"))
    assert s['next'] and s['next']['phase'] == 'tie_break' and s['tie_break_pending'] == 3
    assert jn.post(f"/api/judging/streams/{silver['id']}/works/{s['works'][0]['id']}", headers=ORIGIN,
                   json={'scores': {'c1': 9}}).json()['detail'] == 'regular_locked'
    assert 'tie_break_running' in ok(c.get(url))['publish_problems']
    # отмена переголосования, потом новое — и голосуем
    ok(c.post(f"/api/org/judging/streams/{silver['id']}/tie-break/cancel", headers=ORIGIN))
    assert 'tie_break_running' not in ok(c.get(url))['publish_problems']
    ok(c.post(f"/api/org/judging/streams/{silver['id']}/tie-break", headers=ORIGIN, json={'targets': tied}))
    power = strength(app, names)
    for jc in (js[1][1], jn):
        vote_all(app, jc, silver['id'], power, phase='tie_break')
    view = ok(c.get(url))
    silver = stream_of(view, 'silver')
    assert silver['border']['status'] == 'ok' and view['publish_problems'] == []
    adv = {r['name'].split('@')[0]: r['advanced'] for r in silver['rows']}
    assert adv == {'bea': True, 'cat': True, 'dia': False, 'eve': None}
    ok(c.post(f'/api/org/rounds/{rounds[0]}/judging/publish', headers=ORIGIN))
    assert ok(people['ann'].get(f'/api/games/{eid}'))['rounds'][0]['result']['advanced'] is True
    assert ok(people['dia'].get(f'/api/games/{eid}'))['me']['mode'] == 'out_pending'
    eve = ok(people['eve'].get(f'/api/games/{eid}'))
    assert eve['me']['mode'] == 'withdrawn' and eve['rounds'][0]['result']['advanced'] is None
    # после публикации организатор видит итог как опубликован: не прошедшая — с местом и «не проходит», а не «не в конкурсе»
    after = {r['name'].split('@')[0]: r for r in stream_of(ok(c.get(url)), 'silver')['rows']}
    assert after['dia']['left'] is False and after['dia']['advanced'] is False and after['dia']['place'] == 3
    assert after['eve']['left'] is True and after['eve']['place'] is None and after['bea']['advanced'] is True
    with app.state.db.transaction() as conn:
        ranks = conn.execute('''SELECT league_rank FROM round_results WHERE round_id=%s AND league='silver' ORDER BY league_rank''',
                             (rounds[0],)).fetchall()
        assert [r['league_rank'] for r in ranks] == [1, 2, 3, None]   # вышедшая — без места


def test_replaced_judge_votes_hidden_and_unjudged(app, seed, clock):
    names = ['ann', 'bea', 'cat']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names)
    js = judges(app, seed, 1)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'pools': 'common', 'judges': {'all': [js[0][0]]}, 'quota': {'all': 2}}))
    clock.set(h(days=1, minutes=5))
    st = ok(c.post(url + '/start', headers=ORIGIN))['streams'][0]
    s = ok(js[0][1].get(f"/api/judging/streams/{st['id']}"))
    first = s['next']['id']
    ok(js[0][1].post(f'/api/judging/comparisons/{first}', headers=ORIGIN, json={'winner': 'a'}))
    new = str(seed('judge9@example.com', ('judge',)))
    jn = login_only(app, 'judge9@example.com')
    ok(c.post(f"/api/org/judging/streams/{st['id']}/replace", headers=ORIGIN,
              json={'old_user_id': js[0][0], 'new_user_id': new, 'reason': 'нет связи'}))
    s = ok(jn.get(f"/api/judging/streams/{st['id']}"))
    assert s['voted'] == [] and s['done'] == 1                               # чужие голоса не видны
    assert jn.post(f'/api/judging/comparisons/{first}', headers=ORIGIN, json={'winner': 'b'}).status_code == 404
    # закрыть недоделанное: у кого-то из работ может не остаться оценок — решение организатора
    view = ok(c.post(f"/api/org/judging/streams/{st['id']}/close", headers=ORIGIN, json={'reason': 'срок'}))
    st = view['streams'][0]
    unj = st['border']['unjudged']
    assert len(unj) == 1 and 'unjudged_works' in view['publish_problems']
    assert jn.post(f'/api/judging/comparisons/{first}', headers=ORIGIN, json={'winner': 'b'}).status_code == 404
    judged = [r['target'] for r in st['rows'] if r['score'] is not None]
    assert c.post(f"/api/org/judging/streams/{st['id']}/decision", headers=ORIGIN,
                  json={'targets': judged[:1], 'advance': [], 'reason': 'x'}).json()['detail'] == 'decision_targets'
    view = ok(c.post(f"/api/org/judging/streams/{st['id']}/decision", headers=ORIGIN,
                     json={'targets': unj + unj, 'advance': [], 'reason': 'не оценена'}))
    assert view['publish_problems'] == []
    ok(c.post(f'/api/org/rounds/{rounds[0]}/judging/publish', headers=ORIGIN))
    with app.state.db.transaction() as conn:
        ep = conn.execute('''SELECT p.competition_status FROM evaluation_target_members m JOIN event_participants p ON p.id=m.event_participant_id
WHERE m.evaluation_target_id=%s''', (unj[0],)).fetchone()
        assert ep['competition_status'] == 'eliminated'


def test_personal_extension_blocks_start(app, seed, clock):
    names = ['ann', 'bea', 'cat']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names)
    js = judges(app, seed, 1)
    ok(c.post(f"/api/org/participants/{lst['ann']['id']}/deadline", headers=ORIGIN,
              json={'round_id': rounds[0], 'deadline': h(days=2).isoformat(), 'reason': 'болела'}))
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'pools': 'common', 'judges': {'all': [js[0][0]]}}))
    clock.set(h(days=1, minutes=5))
    assert 'personal_deadlines_pending' in ok(c.get(url))['checks']['problems']    # работа сдана, но её ещё можно заменить


def test_second_review_fixes(app, seed, clock):
    """Переголосование — только среди равных; новый судья не переписывает оценки прежнего; номер переголосования после
    отменённого — новый (уведомление приходит); вышедшая не занимает TOP WORK; судья без роли не судит."""
    names = ['ann', 'bea', 'cat', 'dia', 'eve', 'fay']
    c, eid, rounds, people, lst = setup_game(app, seed, clock, names)
    js = judges(app, seed, 1)
    url = f'/api/org/rounds/{rounds[0]}/judging'
    ok(c.put(url, headers=ORIGIN, json={'method': 'criteria', 'pools': 'common', 'criteria': [{'label': 'Идея', 'weight': 1}],
                                        'judges': {'all': [js[0][0]]}, 'quota': {'all': 3}}))
    clock.set(h(days=1, minutes=5))
    st = stream_of(ok(c.post(url + '/start', headers=ORIGIN)))
    sid = st['id']
    with app.state.db.transaction() as conn:
        who = {r['email'].split('@')[0]: str(r['id']) for r in conn.execute('''SELECT t.id, u.email FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id JOIN event_participants p ON p.id=m.event_participant_id
JOIN users u ON u.id=p.user_id WHERE t.evaluation_stream_id=%s''', (sid,))}
    marks = {'ann': 10, 'bea': 8, 'cat': 6, 'dia': 6, 'eve': 4, 'fay': 2}
    for n, v in marks.items():
        ok(js[0][1].post(f"/api/judging/streams/{sid}/works/{who[n]}", headers=ORIGIN, json={'scores': {'c1': v}}))
    # замена судьи: оценки прежнего остаются за ним, новый их не переписывает
    new = str(seed('judge9@example.com', ('judge',)))
    jn = login_only(app, 'judge9@example.com')
    ok(c.post(f"/api/org/judging/streams/{sid}/replace", headers=ORIGIN,
              json={'old_user_id': js[0][0], 'new_user_id': new, 'reason': 'нет связи'}))
    assert jn.post(f"/api/judging/streams/{sid}/works/{who['ann']}", headers=ORIGIN, json={'scores': {'c1': 1}}).status_code == 404
    with app.state.db.transaction() as conn:
        assert conn.execute('''SELECT score FROM criterion_scores WHERE evaluation_target_id=%s AND status='valid' ''',
                            (who['ann'],)).fetchone()['score'] == 10
    # ann выходит — TOP WORK считается среди оставшихся 5: одна работа, bea
    ok(c.post(f"/api/org/participants/{lst['ann']['id']}/action", headers=ORIGIN, json={'action': 'withdraw', 'reason': 'сама'}))
    rows = {r['name'].split('@')[0]: r for r in stream_of(ok(c.get(url)))['rows']}
    assert [n for n, r in rows.items() if r['top_work']] == ['bea']
    # переголосование среди неравных — нельзя; среди равных cat и dia — можно; после отмены номер новый
    bad = c.post(f"/api/org/judging/streams/{sid}/tie-break", headers=ORIGIN, json={'targets': [who['bea'], who['eve']]})
    assert bad.status_code == 422 and bad.json()['detail'] == 'tie_break_not_tied'
    ok(c.post(f"/api/org/judging/streams/{sid}/tie-break", headers=ORIGIN, json={'targets': [who['cat'], who['dia']]}))
    ok(c.post(f"/api/org/judging/streams/{sid}/tie-break/cancel", headers=ORIGIN))
    ok(c.post(f"/api/org/judging/streams/{sid}/tie-break", headers=ORIGIN, json={'targets': [who['cat'], who['dia']]}))
    with app.state.db.transaction() as conn:
        runs = conn.execute('''SELECT DISTINCT run_no FROM pairwise_comparisons WHERE evaluation_stream_id=%s ORDER BY run_no''',
                            (sid,)).fetchall()
        assert [r['run_no'] for r in runs] == [2, 3]
        assert conn.execute('''SELECT count(*) AS n FROM notifications WHERE user_id=%s AND idempotency_key LIKE 'judging:tie_break:%%' ''',
                            (new,)).fetchone()['n'] == 2
        # роль судьи снята — судить больше нельзя
        conn.execute("DELETE FROM user_roles WHERE user_id=%s AND role='judge'", (new,))
    assert jn.get(f'/api/judging/streams/{sid}').status_code == 404
    assert ok(jn.get('/api/judging'))['streams'] == []
