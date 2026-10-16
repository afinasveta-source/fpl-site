"""Галерея тура в кабинете участницы (15.10): только опубликованные туры, только работы с разрешением на показ (своя — всегда),
без баллов и мест; TOP WORK отдельно; фото — копии для показа, оригинал не отдаётся; чужая Игра — недоступна."""
import json

from game_helpers import ORIGIN, add_docs, build_game, h, login, register, send_work
from test_org import ok


def setup(app, seed, clock):
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    people = {}
    for name, color in (('a', (200, 0, 0)), ('b', (0, 200, 0)), ('c', (0, 0, 200)), ('d', (90, 90, 90)), ('x', (1, 1, 1))):
        c = login(app, seed, f'{name}@example.com')
        ok(register(c, game['event']), 201)
        work = send_work(c, game, 0, color=color)
        people[name] = {'c': c, 'photo': work['submitted']['photos'][0]}
    with app.state.db.transaction() as conn:
        eps = {r['email'][0]: r for r in conn.execute('''SELECT p.*, u.email FROM event_participants p JOIN users u ON u.id=p.user_id
WHERE p.event_id=%s''', (game['event'],))}
        conn.execute("UPDATE users SET display_name='Анна Альфа' WHERE email='a@example.com'")
        conn.execute("UPDATE users SET display_name=NULL, full_name='Борисова Бэлла Игоревна' WHERE email='b@example.com'")
        conn.execute("UPDATE event_participants SET entry_league='gold' WHERE id=%s", (eps['a']['id'],))
        conn.execute("UPDATE event_participants SET entry_league='silver' WHERE id IN (%s,%s)", (eps['b']['id'], eps['c']['id']))
        conn.execute("UPDATE event_participants SET competition_status='disqualified' WHERE id=%s", (eps['x']['id'],))
    ok(people['d']['c'].post('/api/publicity/revoke', headers=ORIGIN))      # d отозвала согласие на публикацию
    return game, people, eps


def publish(app, game, eps):
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE rounds SET status='published' WHERE id=%s", (game['rounds'][0],))
        for k, top in (('a', True), ('b', False), ('c', False)):
            conn.execute('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,is_current,status,display_score,
advanced,competition_status_after,league,top_work,top_work_rule_version,calculation_snapshot,published_at)
VALUES (%s,%s,%s,1,true,'published',77.5,true,'active',%s,%s,%s,'{}',%s)''',
                         (game['event'], game['rounds'][0], eps[k]['id'], 'gold' if k == 'a' else 'silver', top,
                          'FPL_TOPWORK_V1' if top else None, h()))


def url(game, i=0):
    return f"/api/gallery/{game['event']}/rounds/{game['rounds'][i]}"


def media(c, photo, size='thumb'):
    return c.get(photo['thumb_url'].split('?')[0] + f'?size={size}')


def test_gallery_visibility_and_media(app, seed, clock):
    game, people, eps = setup(app, seed, clock)
    a, b, d = people['a']['c'], people['b']['c'], people['d']['c']
    outsider = login(app, seed, 'out@example.com')
    judge = login(app, seed, 'judge@example.com', roles=('judge',))
    other_judge = login(app, seed, 'judge2@example.com', roles=('judge',))
    with app.state.db.transaction() as conn:     # судья этой Игры (назначен в судейство тура 1)
        st = conn.execute('''INSERT INTO evaluation_streams(event_id,round_id,code,target_type,judging_method)
VALUES (%s,%s,'main','pair','pairwise') RETURNING id''', (game['event'], game['rounds'][0])).fetchone()['id']
        slot = conn.execute('INSERT INTO evaluation_judge_slots(evaluation_stream_id,slot_no) VALUES (%s,1) RETURNING id', (st,)).fetchone()['id']
        jid = conn.execute("SELECT id FROM users WHERE email='judge@example.com'").fetchone()['id']
        conn.execute('INSERT INTO evaluation_judge_assignments(judge_slot_id,user_id) VALUES (%s,%s)', (slot, jid))
    org = login(app, seed, 'org@example.com', roles=('admin',))
    # тур ещё не опубликован (идёт сдача / судейство): работ не видно никому, фото чужих — тоже
    g = ok(a.get(url(game)))
    assert g['round']['published'] is False and g['items'] == [] and g['top'] == []
    assert media(a, people['b']['photo']).status_code == 404
    assert ok(a.get('/api/gallery'))['default'] == {'event_id': str(game['event']), 'round_id': str(game['rounds'][-1])}
    publish(app, game, eps)
    ov = ok(a.get('/api/gallery'))
    assert ov['default'] == {'event_id': str(game['event']), 'round_id': str(game['rounds'][0])}
    assert [r['published'] for r in ov['games'][0]['rounds']] == [True, False, False]
    g = ok(a.get(url(game)))
    by = {x['author']: x for x in g['items']}
    # d отозвала согласие, x дисквалифицирована — не видны; имя: публичное, иначе из ФИО («Имя Фамилия»)
    assert set(by) == {'Анна Альфа', 'Бэлла Борисова', 'Участница'}
    assert len(g['items']) == 3 and g['total'] == 3
    assert by['Анна Альфа']['own'] and by['Анна Альфа']['top_work'] and by['Анна Альфа']['league'] == 'gold'
    assert not by['Бэлла Борисова']['own'] and by['Бэлла Борисова']['league'] == 'silver'
    assert [x['author'] for x in g['top']] == ['Анна Альфа'] and g['leagues'] == {'gold': 1, 'silver': 2}
    text = json.dumps(g, ensure_ascii=False)
    assert all(k not in text for k in ('score', 'place', 'rank', 'rating', '77.5', 'email'))    # ни баллов, ни мест, ни почты
    # своя работа видна, даже если показ запрещён
    gd = ok(d.get(url(game)))
    mine = [x for x in gd['items'] if x['own']]
    assert len(mine) == 1 and mine[0]['only_you'] and len(gd['items']) == 4
    # фото: копии для показа — участницам Игры; оригинал — никому; отозвавшей согласие — только ей самой
    assert media(a, people['b']['photo']).status_code == 200 and media(a, people['b']['photo'], 'view').status_code == 200
    assert media(a, people['b']['photo'], 'orig').status_code == 422
    assert media(a, people['d']['photo']).status_code == 404 and media(d, people['d']['photo']).status_code == 200
    assert media(a, people['x']['photo']).status_code == 404
    assert media(outsider, people['b']['photo']).status_code == 404
    assert media(judge, people['b']['photo']).status_code == 200 and media(other_judge, people['b']['photo']).status_code == 404
    # 16.10: чужую работу в галерее видят со знаком FPL (и судья вне своего пула); автор — без знака
    own, seen, judged = (media(x, people['b']['photo'], 'view').content for x in (b, a, judge))
    assert seen != own and judged == seen and seen[:3] == b'\xff\xd8\xff'
    assert media(a, people['b']['photo'], 'view').content == seen                       # копия со знаком — одна, из кэша
    assert media(org, people['b']['photo'], 'view').content == own                      # организатор — без знака
    # чужая Игра — недоступна; судья и организатор — могут
    assert outsider.get(url(game)).status_code == 404 and ok(outsider.get('/api/gallery')) == {'games': [], 'default': None}
    assert len(ok(judge.get(url(game)))['items']) == 3 and len(ok(org.get(url(game)))['items']) == 3
    assert other_judge.get(url(game)).status_code == 404 and ok(other_judge.get('/api/gallery'))['games'] == []
    assert [x['id'] for x in ok(judge.get('/api/gallery'))['games']] == [str(game['event'])]
    # следующий тур не опубликован — пусто
    assert ok(b.get(url(game, 1)))['round']['published'] is False
    # участница скрыла работы в «Публичности» — пропадает из галереи
    ok(b.put('/api/publicity', headers=ORIGIN, json={'gallery': False}))
    assert len(ok(a.get(url(game)))['items']) == 2 and media(a, people['b']['photo']).status_code == 404


def test_bot_round_photos_in_gallery(app, seed, clock):
    """Туры 1–2 Игры 01 из бота опубликованы: фото, перенесённые организатором, — в галерее (по тем же правилам показа)."""
    from test_bot_photos import Fake, U, as_participant, item, setup as bot_setup
    from game_helpers import jpeg
    c, eid = bot_setup(app, seed, clock)
    app.state.fetch_photo = Fake({U.format('1'): jpeg((1, 2, 3)), U.format('2'): jpeg((3, 2, 1))})
    ok(c.post('/api/org/import/game01/photos/apply', headers=ORIGIN,
              json={'items': [item('1000000001', 1, U.format('1')), item('1000000002', 1, U.format('2'))]}))
    p1, _ = as_participant(app, eid, '1000000001', 'anna@example.com')     # согласие есть, «Показывать работы» выключено
    p2, ep2 = as_participant(app, eid, '1000000002', 'maria@example.com')
    with app.state.db.transaction() as conn:
        conn.execute('UPDATE users SET public_works=true WHERE id=%s', (ep2['user_id'],))
        r1 = conn.execute('SELECT id FROM rounds WHERE event_id=%s AND round_no=1', (eid,)).fetchone()['id']
    g = ok(p1.get(f'/api/gallery/{eid}/rounds/{r1}'))
    assert g['round']['published'] and g['round']['from_bot'] and len(g['items']) == 2
    mine = next(x for x in g['items'] if x['own'])
    other = next(x for x in g['items'] if not x['own'])
    assert mine['only_you'] and other['league'] == 'gold' and not other['top_work']
    assert p1.get(other['photo']['thumb_url']).status_code == 200
    assert len(ok(p2.get(f'/api/gallery/{eid}/rounds/{r1}'))['items']) == 1          # чужая без разрешения — не видна
