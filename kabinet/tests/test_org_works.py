"""Организатор загружает работу за участницу (15.10): «в срок» — в конкурс, сверка опоздавших её не переводит;
уже переведённая из-за этого тура — возвращается в конкурс; судейство лиги идёт — нельзя; не организатору — нельзя."""
from game_helpers import ORIGIN, add_docs, build_game, h, jpeg, login, register
from test_org import ok, org


def setup(app, seed, clock, *emails):
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    people = {}
    for e in emails:
        c = login(app, seed, e)
        ok(register(c, game['event']), 201)
        with app.state.db.transaction() as conn:
            people[e] = (c, conn.execute('''SELECT p.* FROM event_participants p JOIN users u ON u.id=p.user_id WHERE u.email=%s''',
                                         (e,)).fetchone())
    return game, people


def upload_for(o, ep, game, i=0, on_time=True, color=(10, 120, 200)):
    photo = o.post(f"/api/org/participants/{ep['id']}/upload", content=jpeg(color), headers={'Content-Type': 'image/jpeg', **ORIGIN})
    assert photo.status_code == 201, photo.text
    return o.post(f"/api/org/participants/{ep['id']}/rounds/{game['rounds'][i]}/work", headers=ORIGIN,
                  json={'photos': [photo.json()['id']], 'link': None, 'on_time': on_time, 'reason': 'Прислала фото организатору'})


def sub_of(app, ep, task):
    with app.state.db.transaction() as conn:
        return conn.execute('''SELECT s.* FROM submissions s JOIN participant_assignments pa ON pa.id=s.participant_assignment_id
WHERE s.event_participant_id=%s AND pa.assignment_id=%s''', (ep['id'], task)).fetchone()


def test_upload_on_time_in_missed_round_and_restore(app, seed, clock):
    game, people = setup(app, seed, clock, 'anna@example.com', 'olga@example.com')
    o = org(app, seed)
    (pa_c, anna), (po_c, olga) = people['anna@example.com'], people['olga@example.com']
    # срок тура 1 прошёл, тур 2 ещё не открыт: обе в конкурсе, тур 1 пропущен
    clock.set(h(days=1, hours=1))
    card = ok(o.get(f"/api/org/participants/{anna['id']}"))
    assert card['mode'] == 'in' and card['missed_round'] == 1 and card['rounds'][0]['can_upload']
    d = ok(upload_for(o, anna, game))
    assert d['missed_round'] is None and d['mode'] == 'in' and d['rounds'][0]['submitted']['source'] == 'admin'
    s = sub_of(app, anna, game['tasks'][0])
    assert s['is_on_time'] and s['counts_for_competition'] and s['competition_version_id'] == s['latest_version_id']
    with app.state.db.transaction() as conn:
        v = conn.execute('SELECT * FROM submission_versions WHERE id=%s', (s['latest_version_id'],)).fetchone()
        m = conn.execute('''SELECT m.* FROM media_files m JOIN submission_version_media x ON x.media_file_id=m.id
WHERE x.submission_version_id=%s''', (v['id'],)).fetchone()
        orgid = conn.execute("SELECT id FROM users WHERE email='org@example.com'").fetchone()['id']
        logged = conn.execute("SELECT * FROM audit_log WHERE action='org_work_uploaded' AND entity_id=%s", (anna['id'],)).fetchone()
    assert v['source'] == 'admin' and v['created_by'] == orgid and m['uploaded_by'] == anna['user_id']
    assert m['metadata']['source'] == 'admin' and m['metadata']['uploaded_by_admin'] == str(orgid)
    assert logged['reason'] == 'Прислала фото организатору' and logged['after_data']['on_time']
    # открылся тур 2: сверка опоздавших переводит Ольгу (не сдала), Анну — нет
    clock.set(h(days=2, hours=1))
    ok(o.get(f"/api/org/events/{game['event']}/participants"))
    g = ok(pa_c.get(f"/api/games/{game['event']}"))
    assert g['me']['mode'] == 'in' and g['rounds'][0]['work'] == 'sent' and g['rounds'][0]['photo']
    t = ok(pa_c.get(f"/api/games/{game['event']}/tasks/{game['tasks'][0]}"))
    assert t['submitted']['photos'] and t['submitted']['source'] == 'admin'
    assert any('Организатор загрузил вашу работу тура 1' in n['title'] for n in ok(pa_c.get('/api/notifications'))['notifications'])
    olga_card = ok(o.get(f"/api/org/participants/{olga['id']}"))
    assert olga_card['mode'] == 'outside' and olga_card['elimination_reason'] == 'late'
    # Ольгу перевели вне конкурса из-за тура 1 — работа «в срок» возвращает её в конкурс
    d = ok(upload_for(o, olga, game, color=(250, 200, 0)))
    assert d['mode'] == 'in' and d['uploaded']['restored'] and d['missed_round'] is None
    assert sub_of(app, olga, game['tasks'][0])['counts_for_competition']
    # идущий тур без отметки «в срок» — как обычная сдача сейчас (до срока — в срок)
    ok(upload_for(o, anna, game, i=1, on_time=False))
    assert sub_of(app, anna, game['tasks'][1])['is_on_time'] and sub_of(app, anna, game['tasks'][1])['counts_for_competition']


def test_late_upload_judging_started_and_access(app, seed, clock):
    game, people = setup(app, seed, clock, 'anna@example.com')
    o = org(app, seed)
    pa_c, anna = people['anna@example.com']
    clock.set(h(days=1, hours=1))
    d = ok(upload_for(o, anna, game, on_time=False))
    s = sub_of(app, anna, game['tasks'][0])
    assert not s['is_on_time'] and not s['counts_for_competition'] and d['missed_round'] == 1
    # не организатор — нельзя (ни фото, ни работу)
    assert pa_c.post(f"/api/org/participants/{anna['id']}/upload", content=jpeg(), headers={'Content-Type': 'image/jpeg', **ORIGIN}).status_code == 403
    assert pa_c.post(f"/api/org/participants/{anna['id']}/rounds/{game['rounds'][0]}/work", headers=ORIGIN,
                     json={'photos': [d['rounds'][0]['submitted']['photos'][0]['id']], 'reason': 'x'}).status_code == 403
    # чужое фото (не на неё) — нельзя
    other = login(app, seed, 'other@example.com')
    foreign = ok(other.post('/api/uploads', content=jpeg((1, 1, 1)), headers={'Content-Type': 'image/jpeg', **ORIGIN}), 201)['id']
    assert o.post(f"/api/org/participants/{anna['id']}/rounds/{game['rounds'][0]}/work", headers=ORIGIN,
                  json={'photos': [foreign], 'reason': 'x'}).json()['detail'] == 'unknown_photo'
    # судейство тура уже идёт — работа не попала бы к судьям
    with app.state.db.transaction() as conn:
        conn.execute('''INSERT INTO evaluation_streams(event_id,round_id,code,target_type,judging_method) VALUES (%s,%s,'main','pair','pairwise')''',
                     (game['event'], game['rounds'][0]))
    r = upload_for(o, anna, game)
    assert r.status_code == 409 and r.json()['detail'] == 'judging_started'
    assert not ok(o.get(f"/api/org/participants/{anna['id']}"))['rounds'][0]['can_upload']
