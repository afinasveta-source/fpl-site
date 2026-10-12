"""Кабинет участника: уведомления, поддержка, согласия, публичность, каналы, профиль."""
from game_helpers import ORIGIN, add_docs, build_game, login, register, send_work


def test_notifications_read(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    send_work(c, game, 0)
    items = c.get('/api/notifications').json()['notifications']
    assert [n['type'] for n in items] == ['sent', 'reg'] and not any(n['read'] for n in items)
    assert items[0]['route'] == 'task' and items[0]['params']['assignment_id'] == str(game['tasks'][0])
    assert c.get('/api/home').json()['unread'] == 2
    assert c.post('/api/notifications/read', headers=ORIGIN, json={'ids': [items[0]['id']]}).json() == {'marked': 1}
    assert c.get('/api/home').json()['unread'] == 1
    other = login(app, seed, 'bob@example.com')
    assert other.post('/api/notifications/read', headers=ORIGIN, json={'all': True}).json() == {'marked': 0}   # чужие не трогает
    assert c.post('/api/notifications/read', headers=ORIGIN, json={'all': True}).json() == {'marked': 1}


def test_support_threads(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    bob = login(app, seed, 'bob@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    send_work(c, game, 0)
    t = c.post('/api/support', headers=ORIGIN, json={'subject': ' Фото тёмное ', 'body': 'Можно заменить?',
                                                      'event_id': str(game['event']), 'round_no': 1,
                                                      'assignment_id': str(game['tasks'][0])})
    assert t.status_code == 201, t.text
    t = t.json()
    assert t['subject'] == 'Фото тёмное' and t['context'] == 'Игра 02 · Тур 1 · работа' and t['status'] == 'waiting_admin'
    assert t['messages'] == [{'mine': True, 'author': 'Вы', 'body': 'Можно заменить?', 'at': t['messages'][0]['at']}]
    # Обращение о чужой работе контекст работы не получает.
    sneaky = bob.post('/api/support', headers=ORIGIN, json={'subject': 'x', 'body': 'y', 'event_id': str(game['event']),
                                                             'assignment_id': str(game['tasks'][0])}).json()
    assert sneaky['context'] == 'Игра 02'
    assert bob.get(f"/api/support/{t['no']}").status_code == 404
    assert bob.post(f"/api/support/{t['no']}/messages", headers=ORIGIN, json={'body': 'взлом'}).status_code == 404
    with app.state.db.transaction() as conn:
        conn.execute("""INSERT INTO support_messages(support_thread_id,author_role,body)
SELECT id,'admin','Да, до конца срока' FROM support_threads WHERE thread_no=%s""", (t['no'],))
        conn.execute("UPDATE support_threads SET status='waiting_user' WHERE thread_no=%s", (t['no'],))
    view = c.get(f"/api/support/{t['no']}").json()
    assert view['status'] == 'waiting_user' and view['messages'][1]['author'] == 'Организатор'
    r = c.post(f"/api/support/{t['no']}/messages", headers=ORIGIN, json={'body': 'Спасибо'}).json()
    assert r['status'] == 'waiting_admin' and len(r['messages']) == 3
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE support_threads SET status='closed' WHERE thread_no=%s", (t['no'],))
    assert c.post(f"/api/support/{t['no']}/messages", headers=ORIGIN, json={'body': 'ещё'}).json()['detail'] == 'closed'
    assert [x['no'] for x in c.get('/api/support').json()['threads']] == [t['no']]
    assert c.post('/api/support', headers=ORIGIN, json={'subject': '   ', 'body': 'x'}).status_code == 422
    assert c.post('/api/support', headers=ORIGIN, json={'subject': 'x', 'body': 'y', 'round_no': 1}).status_code == 422


def test_consents_and_publicity(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        docs = add_docs(conn)
        game = build_game(conn)
    assert c.get('/api/publicity').json()['gallery'] is False
    register(c, game['event'])
    p = c.get('/api/publicity').json()
    assert (p['gallery'], p['social'], p['master_page'], p['publication']['status']) == (True, True, False, 'accepted')
    current = {x['doc_type']: x for x in c.get('/api/consents').json()['current']}
    assert current['rules']['current_accepted'] and current['rules']['version'] == '1.9'
    r = c.put('/api/publicity', headers=ORIGIN, json={'social': False}).json()
    assert (r['gallery'], r['social']) == (True, False)
    r = c.post('/api/publicity/revoke', headers=ORIGIN).json()
    assert (r['gallery'], r['social'], r['master_page'], r['publication']['status']) == (False, False, False, 'revoked')
    assert c.put('/api/publicity', headers=ORIGIN, json={'gallery': True}).json()['detail'] == 'consent_required'
    r = c.put('/api/publicity', headers=ORIGIN, json={'gallery': True, 'accept_publication': True}).json()
    assert r['gallery'] and r['publication']['status'] == 'accepted'
    with app.state.db.transaction() as conn:
        statuses = [x['status'] for x in conn.execute("SELECT status FROM consents WHERE consent_type='publication' ORDER BY recorded_at, id")]
        assert statuses == ['accepted', 'revoked', 'accepted']                # журнал, а не перезапись
    hist = c.get('/api/consents').json()['history']
    assert hist[0]['type'] == 'publication' and any(x['event'] == 'Игра 02' for x in hist)
    doc = c.get(f"/api/documents/{docs['rules']}").json()
    assert doc['body'].startswith('rules 1.9') and doc['accepted']
    # Повторное принятие того же документа не плодит записи.
    c.post('/api/consents', headers=ORIGIN, json={'document_id': str(docs['rules'])})
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM consents WHERE consent_type='rules'").fetchone()['n'] == 1


def test_preferences_and_profile(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    assert c.get('/api/preferences').json() == {'telegram': True, 'email': True, 'marketing': False, 'telegram_linked': False}
    assert c.put('/api/preferences', headers=ORIGIN, json={'telegram': False}).json()['telegram'] is False
    assert c.get('/api/preferences').json()['email'] is True
    assert c.patch('/web-auth/profile', headers=ORIGIN, json={'display_name': 'А'}).status_code == 422
    r = c.patch('/web-auth/profile', headers=ORIGIN, json={'display_name': 'Анна П.', 'full_name': 'Анна Петрова',
                                                           'country_code': 'ge', 'city': 'Тбилиси'})
    assert r.status_code == 200 and r.json()['country_code'] == 'GE'
    locked = c.patch('/web-auth/profile', headers=ORIGIN, json={'full_name': 'Другое Имя'})
    assert locked.status_code == 403 and locked.json()['detail'] == 'full_name_locked'
    assert c.patch('/web-auth/profile', headers=ORIGIN, json={'full_name': 'Анна Петрова'}).status_code == 200
    admin = login(app, seed, 'admin2@example.com', ('admin',))
    admin.patch('/web-auth/profile', headers=ORIGIN, json={'full_name': 'Админ'})
    assert admin.patch('/web-auth/profile', headers=ORIGIN, json={'full_name': 'Админ Новый'}).status_code == 200


def test_all_participant_writes_need_same_origin(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    for method, url, body in [('post', '/api/notifications/read', {'all': True}), ('post', '/api/support', {'subject': 'a', 'body': 'b'}),
                              ('post', '/api/consents', {'document_id': '00000000-0000-0000-0000-000000000000'}),
                              ('put', '/api/publicity', {'gallery': False}), ('post', '/api/publicity/revoke', None),
                              ('put', '/api/preferences', {'email': False})]:
        r = getattr(c, method)(url, json=body, headers={'Origin': 'https://attacker.example'}) if body is not None \
            else getattr(c, method)(url, headers={'Origin': 'https://attacker.example'})
        assert r.status_code == 403, url
    anon = app and __import__('fastapi.testclient', fromlist=['TestClient']).TestClient(app)
    for url in ('/api/home', '/api/events', '/api/games', '/api/notifications', '/api/support', '/api/consents', '/api/publicity'):
        assert anon.get(url).status_code == 401, url


def test_achievements_empty_and_filled(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    a = c.get('/api/achievements').json()
    assert a['rating'] == {'value': None, 'status': 'unrated', 'calibration': 0, 'history': []} and a['diplomas'] == []
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    with app.state.db.transaction() as conn:
        ep = conn.execute('SELECT id FROM event_participants').fetchone()['id']
        conn.execute("""INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,status,display_score,top_work,
top_work_rule_version,published_at) VALUES (%s,%s,%s,1,'published',84.1,true,'v1',now())""", (game['event'], game['rounds'][0], ep))
        conn.execute("""INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,status,display_score)
VALUES (%s,%s,%s,1,'draft',50)""", (game['event'], game['rounds'][1], ep))
    a = c.get('/api/achievements').json()
    assert [(r['round_no'], r['score'], r['top_work']) for r in a['results']] == [(1, 84.1, True)]   # черновик итога не виден
    g = c.get(f"/api/games/{game['event']}").json()
    assert g['rounds'][0]['result']['score'] == 84.1 and g['rounds'][1]['result'] is None
