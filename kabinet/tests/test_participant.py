"""Кабинет участника: запись на Игру, задание, черновик, сдача и замена, сроки, вне конкурса, Правила."""
import io

from PIL import Image

from game_helpers import (ORIGIN, add_doc, add_docs, build_game, h, jpeg, login, register, send_work, task_url,
                          upload)


def test_registration_rules(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        game = build_game(conn)
    assert register(c, game['event']).json()['detail'] == 'documents_missing'   # без Правил запись закрыта
    with app.state.db.transaction() as conn:
        add_docs(conn)
    page = c.get(f"/api/events/{game['event']}").json()
    assert page['registration'] == 'open' and page['needs_place'] and set(page['documents']) == {'rules', 'publication', 'personal_data'}
    assert register(c, game['event'], accept_publication=False).json()['detail'] == 'consents_required'
    assert register(c, game['event'], accept_personal_data=False).json()['detail'] == 'personal_data_required'
    assert register(c, game['event'], country_code=None, city=None).json()['detail'] == 'place_required'
    r = register(c, game['event'])
    assert r.status_code == 201 and r.json() == {'event_id': str(game['event']), 'mode': 'in', 'created': True}
    again = register(c, game['event'])
    assert again.status_code == 201 and again.json()['created'] is False          # повтор не создаёт вторую запись
    with app.state.db.transaction() as conn:
        rows = conn.execute("SELECT consent_type, status, channel FROM consents ORDER BY consent_type").fetchall()
        assert [(r['consent_type'], r['status'], r['channel']) for r in rows] == [
            ('personal_data', 'accepted', 'web'), ('publication', 'accepted', 'web'), ('rules', 'accepted', 'web')]
        u = conn.execute("SELECT * FROM users WHERE email='anna@example.com'").fetchone()
        assert (u['country_code'], u['city'], u['public_works'], u['public_social']) == ('RU', 'Москва', True, True)
    cat = c.get('/api/events').json()['events']
    assert cat[0]['my_mode'] == 'in'
    assert c.get('/api/notifications').json()['notifications'][0]['title'] == 'Вы записаны на Игра 02'


def test_registration_closed_paid_and_judge(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        closed = build_game(conn, reg_closes=h(hours=-1), title='Закрытая')
        paid = build_game(conn, payment=True, title='Платная')
        judged = build_game(conn, title='Судейская')
        uid = conn.execute("SELECT id FROM users WHERE email='anna@example.com'").fetchone()['id']
        conn.execute("INSERT INTO event_staff(event_id,user_id,role) VALUES (%s,%s,'judge')", (judged['event'], uid))
    assert register(c, closed['event']).json()['detail'] == 'registration_closed'
    r = register(c, paid['event'])
    assert r.status_code == 201 and r.json()['mode'] == 'pending'
    assert c.get(task_url(paid, 0)).json()['window']['reason'] == 'not_participating'
    assert register(c, judged['event']).json()['detail'] == 'judge_of_game'
    assert c.post(f"/api/events/{judged['event']}/registration", json={'accept_rules': True, 'accept_publication': True}).status_code == 403


def test_submit_and_replace_until_deadline(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    overview = c.get(f"/api/games/{game['event']}").json()
    assert [r['state'] for r in overview['rounds']] == ['open', 'plan', 'plan']
    assert overview['flags'] == {'counted': 'ok', 'diploma': 'pending'}
    t = c.get(task_url(game, 0)).json()
    assert t['instructions'] == 'Нарисуйте персонажа 1' and t['window']['open'] and t['form']['photo'] == 'required'
    assert t['work'] == 'none' and t['draft'] is None and t['submitted'] is None
    later = c.get(task_url(game, 1)).json()
    assert later['instructions'] is None and later['window']['reason'] == 'not_open'      # задание до открытия не видно

    photo = upload(c).json()
    bad = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [photo['id']], 'link': 'javascript:alert(1)'})
    assert bad.status_code == 422 and bad.json()['detail'] == 'bad_link'
    empty = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [], 'link': 'https://vk.com/wall1'}).json()
    assert c.post(task_url(game, 0) + '/submit', headers=ORIGIN, json={'draft_id': empty['draft']['id']}).json()['detail'] == 'photo_required'
    d = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [photo['id']], 'link': 'https://vk.com/wall1'}).json()
    assert d['work'] == 'draft' and d['draft']['photos'][0]['id'] == photo['id'] and d['submitted'] is None
    wrong = c.post(task_url(game, 0) + '/submit', headers=ORIGIN, json={'draft_id': photo['id']})
    assert wrong.status_code == 409 and wrong.json()['detail'] == 'draft_changed'
    s1 = c.post(task_url(game, 0) + '/submit', headers=ORIGIN, json={'draft_id': d['draft']['id']}).json()
    assert s1['work'] == 'sent' and s1['draft'] is None and s1['submitted']['version_no'] == 1
    assert s1['submitted']['link'] == 'https://vk.com/wall1' and s1['submitted']['is_on_time']

    clock.shift(hours=20)                         # до срока ещё 4 часа — замена открыта
    s2 = send_work(c, game, 0, color=(1, 200, 1))
    assert s2['submitted']['version_no'] == 2 and s2['submitted']['photos'][0]['id'] != photo['id']
    with app.state.db.transaction() as conn:
        sub = conn.execute('SELECT * FROM submissions').fetchone()
        versions = conn.execute('SELECT version_no, submitted_at FROM submission_versions ORDER BY version_no').fetchall()
        assert sub['latest_version_id'] == sub['competition_version_id'] == sub['diploma_version_id']
        assert [v['version_no'] for v in versions] == [1, 2] and all(v['submitted_at'] for v in versions)
        assert sub['counts_for_competition'] and sub['is_on_time'] and sub['deadline_source'] == 'round'

    clock.shift(hours=5)                          # срок прошёл: замена закрыта
    closed = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [photo['id']]})
    assert closed.status_code == 409 and closed.json()['detail'] == 'deadline_passed'
    assert c.get(task_url(game, 0)).json()['window'] == {'open': False, 'reason': 'deadline_passed',
                                                         'deadline': h(days=1).isoformat(), 'source': 'round'}
    assert c.get(f"/api/games/{game['event']}").json()['rounds'][0]['state'] == 'judging'


def test_personal_extension(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    c.get(task_url(game, 0))                       # задание выдано
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE participant_assignments SET deadline_override=%s, deadline_override_reason='болезнь'", (h(days=1, hours=6),))
    clock.set(h(days=1, hours=3))
    t = c.get(task_url(game, 0)).json()
    assert t['window']['open'] and t['window']['source'] == 'personal'
    send_work(c, game, 0)
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT deadline_source, is_on_time FROM submissions').fetchone() == {'deadline_source': 'personal', 'is_on_time': True}


def test_late_goes_outside_when_next_round_opens(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    clock.set(h(days=1, hours=1))                 # срок тура 1 прошёл, тур 2 ещё не открыт
    g = c.get(f"/api/games/{game['event']}").json()
    assert g['me']['mode'] == 'in' and g['rounds'][0]['work'] == 'missed' and not g['rounds'][0]['can_submit']
    assert g['flags']['counted'] == 'lost'
    clock.set(h(days=2, hours=1))                 # открылся тур 2 — участник вне конкурса
    g = c.get(f"/api/games/{game['event']}").json()
    assert g['me']['mode'] == 'outside' and g['me']['elimination_reason'] == 'late' and g['me']['round_no_of_exit'] == 1
    assert g['rounds'][0]['can_submit'] and g['rounds'][0]['submit_deadline'] == h(days=20).isoformat()
    late = send_work(c, game, 0)
    assert late['work'] == 'sent_late' and late['submitted']['is_on_time'] is False
    assert late['window']['source'] == 'completion'
    send_work(c, game, 1)
    with app.state.db.transaction() as conn:
        ep = conn.execute('SELECT * FROM event_participants').fetchone()
        assert (ep['competition_status'], ep['out_of_competition_source']) == ('diploma_only', 'auto')
        subs = conn.execute('SELECT counts_for_competition, counts_for_diploma, competition_version_id FROM submissions').fetchall()
        assert all(s['counts_for_diploma'] and not s['counts_for_competition'] and s['competition_version_id'] is None for s in subs)
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE notification_type='status'").fetchone()['n'] == 1
    clock.set(h(days=20, hours=1))                # после конца Игры — всё закрыто
    assert c.get(task_url(game, 2)).json()['window']['reason'] == 'game_over'


def test_late_registration_after_start_is_outside(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn, reg_closes=h(days=6))
    clock.set(h(days=2, hours=1))                 # тур 1 уже прошёл, тур 2 открыт
    register(c, game['event'])
    g = c.get(f"/api/games/{game['event']}").json()
    assert g['me']['mode'] == 'outside' and g['me']['round_no_of_exit'] == 1


def test_judged_out_chooses_outside(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    send_work(c, game, 0)
    assert c.post(f"/api/games/{game['event']}/outside", headers=ORIGIN).json()['detail'] == 'not_allowed'
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE event_participants SET competition_status='eliminated', elimination_reason='judged_out'")
    clock.set(h(days=2, hours=1))
    assert c.get(task_url(game, 1)).json()['window']['reason'] == 'choose_first'
    r = c.post(f"/api/games/{game['event']}/outside", headers=ORIGIN)
    assert r.status_code == 200 and r.json()['me']['mode'] == 'outside'
    assert c.post(f"/api/games/{game['event']}/outside", headers=ORIGIN).status_code == 409   # обратно в конкурс нельзя
    send_work(c, game, 1)
    replaced = send_work(c, game, 0, color=(5, 5, 250))                                       # замена после срока тура 1
    assert replaced['submitted']['version_no'] == 2 and replaced['submitted']['is_on_time'] is True  # «в срок» — по первой сдаче
    with app.state.db.transaction() as conn:
        s = conn.execute('''SELECT s.*, v.version_no AS comp_no FROM submissions s JOIN submission_versions v ON v.id=s.competition_version_id
JOIN participant_assignments pa ON pa.id=s.participant_assignment_id WHERE pa.assignment_id=%s''', (game['tasks'][0],)).fetchone()
        assert s['comp_no'] == 1 and s['counts_for_competition']          # жюри видит версию, сданную в конкурсе
    flags = c.get(f"/api/games/{game['event']}").json()['flags']
    assert flags['counted'] == 'ok'


def test_new_rules_edition_closes_submission(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        docs = add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    with app.state.db.transaction() as conn:
        conn.execute('UPDATE legal_documents SET superseded_at=%s WHERE id=%s', (h(hours=-1), docs['rules']))
        new = add_doc(conn, 'rules', '2.0', published=h(hours=-1))
    t = c.get(task_url(game, 0)).json()
    assert t['window']['reason'] == 'rules'
    home = c.get('/api/home').json()
    assert home['rules_update'] == {'id': str(new), 'version': '2.0', 'title': 'rules 2.0'}
    assert c.post('/api/consents', headers=ORIGIN, json={'document_id': str(docs['rules'])}).json()['detail'] == 'not_current'
    assert c.post('/api/consents', headers=ORIGIN, json={'document_id': str(new)}).status_code == 200
    assert c.get(task_url(game, 0)).json()['window']['open']
    assert c.get('/api/home').json()['rules_update'] is None


def test_league_variants(app, seed, clock):
    gold = login(app, seed, 'gold@example.com')
    nobody = login(app, seed, 'none@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn, leagues=['gold', 'silver'])
    register(gold, game['event'])
    register(nobody, game['event'])
    with app.state.db.transaction() as conn:
        conn.execute("""UPDATE event_participants SET entry_league='gold' WHERE user_id=(SELECT id FROM users WHERE email='gold@example.com')""")
    assert gold.get(task_url(game, 0)).json()['instructions'] == 'Текст 1 для gold'
    t = nobody.get(task_url(game, 0)).json()                   # лига не назначена — вариант не выбрать
    assert t['task_ready'] is False and t['instructions'] is None
    assert nobody.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': []}).json()['detail'] == 'task_not_ready'


def test_photos_are_private_and_clean(app, seed, clock):
    a = login(app, seed, 'anna@example.com')
    b = login(app, seed, 'bob@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(a, game['event'])
    register(b, game['event'])
    data = jpeg()
    p = upload(a, data).json()
    assert upload(a, data).json()['id'] == p['id']                  # тот же файл — та же запись
    view = a.get(p['view_url'].replace('/api', '/api', 1))
    assert view.status_code == 200 and view.headers['content-type'] == 'image/jpeg'
    assert not Image.open(io.BytesIO(view.content)).getexif()        # без EXIF и геометки
    assert b.get(p['thumb_url']).status_code == 404                 # чужое фото не видно
    other = upload(b, data).json()
    assert other['id'] != p['id']
    stolen = b.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [p['id']]})
    assert stolen.status_code == 422 and stolen.json()['detail'] == 'unknown_photo'
    assert upload(a, b'not an image at all').json()['detail'] == 'not_an_image'
    assert upload(a, data, 'image/gif').status_code == 415
    assert a.post('/api/uploads', content=data, headers={'Content-Type': 'image/jpeg'}).status_code == 403   # без Origin
    big = io.BytesIO()
    Image.effect_noise((3000, 3000), 100).convert('RGB').save(big, 'PNG')
    app.state.settings.upload_max_mb = 1
    assert upload(a, big.getvalue(), 'image/png').status_code == 413


def test_outsiders_cannot_touch_game(app, seed, clock):
    a = login(app, seed, 'anna@example.com')
    stranger = login(app, seed, 'stranger@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(a, game['event'])
    assert stranger.get(f"/api/games/{game['event']}").status_code == 404
    assert stranger.get(task_url(game, 0)).status_code == 404
    assert stranger.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': []}).status_code == 404
    assert a.get(f"/api/games/{game['event']}/tasks/{game['rounds'][0]}").status_code == 404


def test_next_round_in_draft_still_counts_as_next(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
        conn.execute("UPDATE rounds SET status='draft' WHERE round_no > 1")
    register(c, game['event'])
    clock.set(h(days=3))                          # срок тура 1 прошёл, тур 2 у организатора ещё в черновике
    g = c.get(f"/api/games/{game['event']}").json()
    assert g['me']['mode'] == 'in' and g['rounds'][0]['work'] == 'missed'
    assert g['flags']['diploma'] == 'pending'


def test_late_transfer_time_and_sweep_without_visit(app, seed, clock):
    from kabinet.participation.game import sync_event
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])                    # дальше участница в кабинет не заходит
    with app.state.db.transaction() as conn:
        assert sync_event(conn, game['event'], h(days=1, hours=1)) == 0        # тур 2 ещё не открыт
        assert sync_event(conn, game['event'], h(days=2, hours=5)) == 1
        assert sync_event(conn, game['event'], h(days=2, hours=6)) == 0        # повтор ничего не меняет
        ep = conn.execute('SELECT * FROM event_participants').fetchone()
        assert ep['competition_status'] == 'diploma_only' and ep['out_of_competition_at'] == h(days=2)   # время открытия тура 2


def test_submit_sends_exactly_what_was_seen(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    register(c, game['event'])
    a = upload(c, jpeg((1, 1, 1))).json()
    b = upload(c, jpeg((250, 250, 250))).json()
    first = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [a['id']]}).json()['draft']
    second = c.put(task_url(game, 0) + '/draft', headers=ORIGIN, json={'photos': [b['id']]}).json()['draft']   # другое окно
    assert second['id'] != first['id']
    stale = c.post(task_url(game, 0) + '/submit', headers=ORIGIN, json={'draft_id': first['id']})
    assert stale.status_code == 409 and stale.json()['detail'] == 'draft_changed'
    ok = c.post(task_url(game, 0) + '/submit', headers=ORIGIN, json={'draft_id': second['id']}).json()
    assert ok['submitted']['photos'][0]['id'] == b['id'] and ok['submitted']['version_no'] == 1


def test_big_phone_photo_is_processed(app, seed, clock):
    c = login(app, seed, 'anna@example.com')
    big = io.BytesIO()
    Image.new('RGB', (8160, 6120), (90, 60, 30)).save(big, 'JPEG', quality=70)   # 50 Мп, как у современных телефонов
    r = upload(c, big.getvalue())
    assert r.status_code == 201, r.text
    view = Image.open(io.BytesIO(c.get(r.json()['view_url']).content))
    assert max(view.size) == 1600
