"""Кабинет организатора (этап 3): доступ, Игра и её жизненный цикл, туры и задание, документы, люди и приглашения,
действия с участницей, поддержка, пожелания с сайта. Проверки — через тот же API, которым пользуется страница."""
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import PASSWORD
from game_helpers import ORIGIN, T0, h, login, register, send_work, upload, jpeg

RULES_TEXT = 'Правила лиги. ' * 5


def org(app, seed, email='org@example.com'):
    return login(app, seed, email, roles=('admin',))


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None


def publish_docs(c):
    for kind, version in (('rules', '1.9'), ('publication', '1'), ('personal_data', '1')):
        ok(c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': kind, 'version': version, 'title': f'{kind} {version}',
                                                              'body': RULES_TEXT}), 201)


def game_ready(c, title='Игра 02', rounds=2):
    """Черновик Игры с датами и опубликованными турами: тур 1 открыт сейчас (срок +1 день), тур 2 — через 2 дня."""
    e = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': title}), 201)
    ok(c.patch(f"/api/org/events/{e['id']}", headers=ORIGIN, json={
        'registration_opens_at': h(days=-5).isoformat(), 'registration_closes_at': h(days=3).isoformat(),
        'starts_at': h(days=-1).isoformat(), 'ends_at': h(days=20).isoformat()}))
    ids = []
    for no in range(1, rounds + 1):
        r = ok(c.post(f"/api/org/events/{e['id']}/rounds", headers=ORIGIN, json={}), 201)
        opens, deadline = (h(minutes=-10), h(days=1)) if no == 1 else (h(days=2), h(days=4))
        ok(c.patch(f"/api/org/rounds/{r['id']}", headers=ORIGIN, json={'opens_at': opens.isoformat(), 'deadline': deadline.isoformat()}))
        ok(c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
            'title': f'Бабочка {no}', 'form': {'photo': 'required', 'link': 'optional', 'photo_max': 1},
            'variants': [{'league': None, 'instructions': f'Общий текст {no}'},
                         {'league': 'gold', 'instructions': f'Текст для Gold {no}'}]}))
        ok(c.post(f"/api/org/rounds/{r['id']}/status", headers=ORIGIN, json={'action': 'publish'}))
        ids.append(r['id'])
    return e['id'], ids


# ---------- доступ ----------

def test_only_admin_and_same_origin(app, seed):
    p = login(app, seed, 'p@example.com')
    assert p.get('/api/org/home').status_code == 403
    assert p.post('/api/org/events', headers=ORIGIN, json={'title': 'X'}).status_code == 403
    anon = TestClient(app)
    assert anon.get('/api/org/home').status_code == 401
    c = org(app, seed)
    ok(c.get('/api/org/home'))
    assert c.post('/api/org/events', json={'title': 'Без Origin'}).status_code == 403
    assert c.post('/api/org/events', headers={'Origin': 'https://evil.example'}, json={'title': 'X'}).status_code == 403


def test_role_removed_takes_effect_immediately(app, seed):
    c = org(app, seed)
    with app.state.db.transaction() as conn:
        conn.execute("DELETE FROM user_roles WHERE role='admin'")
    assert c.post('/api/org/events', headers=ORIGIN, json={'title': 'X'}).status_code == 403


# ---------- Игра ----------

def test_game_lifecycle(app, seed, clock):
    c = org(app, seed)
    e = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': '  Игра 02 '}), 201)
    assert e['status'] == 'draft' and e['title'] == 'Игра 02' and e['type'] == 'ranked_game' and e['affects_rating']
    p = login(app, seed, 'p@example.com')
    assert all(x['id'] != e['id'] for x in ok(p.get('/api/events'))['events'])   # черновик не виден
    r = c.post(f"/api/org/events/{e['id']}/status", headers=ORIGIN, json={'action': 'publish'})
    assert r.status_code == 409 and r.json()['detail'] == 'missing_starts_at'
    assert set(ok(c.get(f"/api/org/events/{e['id']}"))['checks']['problems']) >= {'no_rules', 'no_publication'}
    bad = c.patch(f"/api/org/events/{e['id']}", headers=ORIGIN, json={'starts_at': h(days=2).isoformat(), 'ends_at': h(days=1).isoformat()})
    assert bad.status_code == 422 and bad.json()['detail'] == 'game_dates'
    naive = c.patch(f"/api/org/events/{e['id']}", headers=ORIGIN, json={'starts_at': '2026-11-10T12:00:00'})
    assert naive.status_code == 422   # время без часового пояса не принимается
    publish_docs(c)
    eid, rounds = game_ready(c)
    ev = ok(c.get(f'/api/org/events/{eid}'))
    assert ev['completion_deadline'] == ev['ends_at'] and ev['checks']['problems'] == []
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    assert any(x['id'] == eid and x['registration'] == 'open' for x in ok(p.get('/api/events'))['events'])
    ok(register(p, eid), 201)
    r = c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'unpublish'})
    assert r.status_code == 409 and r.json()['detail'] == 'has_participants'
    started = ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    assert started['status'] == 'active' and started['rules_version'] == '1.9'
    r = c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'event_type': 'challenge'})
    assert r.status_code == 409 and r.json()['detail'] == 'locked_after_start'
    ok(c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'description': 'Пять туров'}))
    r = c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'ends_at': h(days=3).isoformat()})
    assert r.status_code == 422 and r.json()['detail'] == 'rounds_after_end'   # тур 2 сдаётся позже
    fin = ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'finish', 'early': True}))
    assert fin['status'] == 'finished'
    game = ok(p.get(f'/api/games/{eid}'))
    assert game['rounds'][0]['closed_reason'] == 'game_over'
    assert c.post(f'/api/org/events/{eid}/rounds', headers=ORIGIN, json={}).status_code == 409
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'reopen'}))
    assert c.delete(f'/api/org/events/{eid}', headers=ORIGIN).status_code == 409


def test_delete_draft_and_prizes(app, seed):
    c = org(app, seed)
    e = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'Черновик'}), 201)
    ok(c.post(f"/api/org/events/{e['id']}/rounds", headers=ORIGIN, json={'title': 'Разминка'}), 201)
    got = ok(c.put(f"/api/org/events/{e['id']}/prizes", headers=ORIGIN, json={'items': [
        {'criterion': '1 место', 'prize': 'Набор красок', 'league': 'gold'}, {'criterion': 'Все', 'prize': 'Диплом'}]}))
    assert [x['prize'] for x in got['prizes']] == ['Набор красок', 'Диплом']
    assert c.put(f"/api/org/events/{e['id']}/prizes", headers=ORIGIN, json={'items': [{'criterion': ' ', 'prize': 'x'}]}).status_code == 422
    ok(c.delete(f"/api/org/events/{e['id']}", headers=ORIGIN), 204)
    assert c.get(f"/api/org/events/{e['id']}").status_code == 404


def test_seasons_and_game_numbers(app, seed):
    c = org(app, seed)
    s = ok(c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Сезон 1', 'season_no': 1}), 201)
    assert c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Дубль', 'season_no': 1}).status_code == 409
    a = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'A', 'season_id': s['id']}), 201)
    b = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'B', 'season_id': s['id']}), 201)
    ok(c.patch(f"/api/org/events/{a['id']}", headers=ORIGIN, json={'game_no': 2}))
    r = c.patch(f"/api/org/events/{b['id']}", headers=ORIGIN, json={'game_no': 2})
    assert r.status_code == 409 and r.json()['detail'] == 'game_no_taken'
    assert ok(c.get('/api/org/seasons'))['seasons'][0]['games'] == 2


# ---------- туры и задание ----------

def test_round_publish_checks_and_task_by_league(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    e = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'Игра 03'}), 201)
    ok(c.patch(f"/api/org/events/{e['id']}", headers=ORIGIN, json={
        'registration_closes_at': h(days=3).isoformat(), 'starts_at': h(days=-1).isoformat(), 'ends_at': h(days=20).isoformat()}))
    r = ok(c.post(f"/api/org/events/{e['id']}/rounds", headers=ORIGIN, json={}), 201)
    assert r['round_no'] == 1 and r['title'] == 'Тур 1' and r['state'] == 'draft'
    bad = c.post(f"/api/org/rounds/{r['id']}/status", headers=ORIGIN, json={'action': 'publish'})
    assert bad.status_code == 409 and bad.json()['detail'] == 'missing_opens_at'
    assert c.patch(f"/api/org/rounds/{r['id']}", headers=ORIGIN, json={
        'opens_at': h(days=1).isoformat(), 'deadline': h(hours=1).isoformat()}).json()['detail'] == 'deadline_before_open'
    ok(c.patch(f"/api/org/rounds/{r['id']}", headers=ORIGIN, json={'opens_at': h(minutes=-5).isoformat(), 'deadline': h(days=2).isoformat()}))
    assert ok(c.get(f"/api/org/rounds/{r['id']}"))['checks']['problems'] == ['empty_instructions']
    assert c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'X', 'form': {'photo': 'none', 'link': 'none'}, 'variants': [{'instructions': 'a'}]}).status_code == 422
    assert c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'X', 'form': {}, 'variants': [{'league': 'gold', 'instructions': 'a'}]}).status_code == 422   # нет общего текста
    ok(c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'Портрет', 'form': {'photo': 'required', 'link': 'required', 'photo_max': 2},
        'variants': [{'league': None, 'instructions': 'Общий'}, {'league': 'gold', 'instructions': 'Для Gold'}]}))
    pub = ok(c.post(f"/api/org/rounds/{r['id']}/status", headers=ORIGIN, json={'action': 'publish'}))
    assert pub['state'] == 'open' and pub['locks']['form']
    ok(c.post(f"/api/org/events/{e['id']}/status", headers=ORIGIN, json={'action': 'publish'}))
    p1, p2 = login(app, seed, 'p1@example.com'), login(app, seed, 'p2@example.com')
    ok(register(p1, e['id']), 201)
    ok(register(p2, e['id']), 201)
    people = ok(c.get(f"/api/org/events/{e['id']}/participants"))
    gold = next(x for x in people['participants'] if x['email'] == 'p2@example.com')
    ok(c.post(f"/api/org/participants/{gold['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    task_id = pub['task']['id']
    t1 = ok(p1.get(f"/api/games/{e['id']}/tasks/{task_id}"))
    t2 = ok(p2.get(f"/api/games/{e['id']}/tasks/{task_id}"))
    assert t1['instructions'] == 'Общий' and t2['instructions'] == 'Для Gold'
    assert t1['form'] == {'photo': 'required', 'link': 'required', 'photo_max': 2}
    # После открытия: форму и набор лиг не поменять, текст — можно, участницы увидят новый и получат уведомление.
    r2 = c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'Портрет', 'form': {'photo': 'required', 'link': 'optional', 'photo_max': 2},
        'variants': [{'league': None, 'instructions': 'Общий'}, {'league': 'gold', 'instructions': 'Для Gold'}]})
    assert r2.status_code == 409 and r2.json()['detail'] == 'form_locked'
    r3 = c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'Портрет', 'form': {'photo': 'required', 'link': 'required', 'photo_max': 2},
        'variants': [{'league': None, 'instructions': 'Общий'}]})
    assert r3.status_code == 409 and r3.json()['detail'] == 'leagues_locked'
    fixed = ok(c.put(f"/api/org/rounds/{r['id']}/task", headers=ORIGIN, json={
        'title': 'Портрет', 'form': {'photo': 'required', 'link': 'required', 'photo_max': 2},
        'variants': [{'league': None, 'instructions': 'Общий, исправлено'}, {'league': 'gold', 'instructions': 'Для Gold'}]}))
    assert fixed['notified'] == 1
    assert ok(p1.get(f"/api/games/{e['id']}/tasks/{task_id}"))['instructions'] == 'Общий, исправлено'
    assert ok(p2.get(f"/api/games/{e['id']}/tasks/{task_id}"))['instructions'] == 'Для Gold'
    assert any(n['title'] == 'Задание тура 1 уточнено' for n in ok(p1.get('/api/notifications'))['notifications'])
    r4 = c.patch(f"/api/org/rounds/{r['id']}", headers=ORIGIN, json={'opens_at': h(hours=1).isoformat()})
    assert r4.status_code == 409 and r4.json()['detail'] == 'opens_locked'
    ok(c.patch(f"/api/org/rounds/{r['id']}", headers=ORIGIN, json={'deadline': h(days=3).isoformat(), 'title': 'Портреты'}))
    assert c.post(f"/api/org/rounds/{r['id']}/status", headers=ORIGIN, json={'action': 'unpublish'}).json()['detail'] == 'round_opened'


def test_round_open_now_unpublish_delete(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    second = ok(c.get(f'/api/org/rounds/{rounds[1]}'))
    assert second['state'] == 'plan'
    assert c.delete(f'/api/org/rounds/{rounds[0]}', headers=ORIGIN).json()['detail'] == 'not_draft'
    ok(c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'unpublish'}))
    assert c.delete(f'/api/org/rounds/{rounds[0]}', headers=ORIGIN).status_code == 409
    ok(c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'publish'}))
    opened = ok(c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'open_now'}))
    assert opened['state'] == 'open' and opened['opens_at'] == T0.isoformat()
    third = ok(c.post(f'/api/org/events/{eid}/rounds', headers=ORIGIN, json={}), 201)
    after = ok(c.delete(f"/api/org/rounds/{third['id']}", headers=ORIGIN))
    assert [r['round_no'] for r in after['rounds']] == [1, 2]
    r = c.patch(f'/api/org/rounds/{rounds[1]}', headers=ORIGIN, json={'deadline': h(days=30).isoformat()})
    assert r.status_code == 422 and r.json()['detail'] == 'deadline_after_game_end'


# ---------- документы ----------

def test_documents_publish_schedule_cancel(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, _ = game_ready(c, rounds=1)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    assert ok(p.get(f'/api/games/{eid}'))['rules_ok']
    assert c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '1.9', 'title': 'x',
                                                             'body': RULES_TEXT}).json()['detail'] == 'version_taken'
    assert c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '2.0', 'title': 'x', 'body': RULES_TEXT,
                                                             'publish_at': h(days=-1).isoformat()}).json()['detail'] == 'publish_in_past'
    later = ok(c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '2.0', 'title': 'Правила 2.0',
                                                                  'body': RULES_TEXT, 'publish_at': h(days=2).isoformat()}), 201)
    assert later['state'] == 'scheduled' and later['notified'] == 0
    docs = ok(c.get('/api/org/documents'))['documents']['rules']
    assert docs['current']['version'] == '1.9' and docs['scheduled']['version'] == '2.0'
    assert c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '2.1', 'title': 'x',
                                                             'body': RULES_TEXT}).json()['detail'] == 'scheduled_exists'
    ok(c.post(f"/api/org/documents/{later['id']}/cancel", headers=ORIGIN))
    docs = ok(c.get('/api/org/documents'))['documents']['rules']
    assert docs['current']['version'] == '1.9' and docs['current']['superseded_at'] is None and docs['scheduled'] is None
    now = ok(c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '2.1', 'title': 'Правила 2.1',
                                                                'body': RULES_TEXT}), 201)
    assert now['state'] == 'current' and now['notified'] == 1
    assert not ok(p.get(f'/api/games/{eid}'))['rules_ok']   # сдача закрыта, пока не примет
    assert any(n['title'].startswith('Новая редакция Правил') for n in ok(p.get('/api/notifications'))['notifications'])
    ok(p.post('/api/consents', headers=ORIGIN, json={'document_id': now['id']}))
    assert ok(c.get('/api/org/documents'))['documents']['rules']['current']['accepted'] == 1


def test_document_text_is_frozen(app, seed):
    c = org(app, seed)
    d = ok(c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'publication', 'version': '1', 'title': 'Публикация',
                                                              'body': RULES_TEXT}), 201)
    with app.state.db.transaction() as conn:
        try:
            conn.execute("UPDATE legal_documents SET body='другое' WHERE id=%s", (d['id'],))
            raise AssertionError('text changed')
        except Exception as exc:
            assert 'cannot change' in str(exc)


# ---------- люди и приглашения ----------

def test_person_invite_and_accept(app, seed):
    c = org(app, seed)
    person = ok(c.post('/api/org/people', headers=ORIGIN, json={'full_name': 'Анна Петрова', 'city': 'Казань',
                                                                'country_code': 'ru', 'telegram_id': 123456}), 201)
    assert person['account_status'] == 'imported' and person['roles'] == ['participant'] and person['country_code'] == 'RU'
    assert c.post('/api/org/people', headers=ORIGIN, json={'full_name': 'Дубль', 'telegram_id': 123456}).json()['detail'] == 'telegram_taken'
    assert c.post(f"/api/org/people/{person['id']}/reset-link", headers=ORIGIN).json()['detail'] == 'not_active'
    first = ok(c.post(f"/api/org/people/{person['id']}/invite", headers=ORIGIN))
    link = ok(c.post(f"/api/org/people/{person['id']}/invite", headers=ORIGIN))
    assert link['link'].startswith('http://localhost:8100/auth/invite#token=')
    token, old = link['link'].split('token=')[1], first['link'].split('token=')[1]
    assert ok(c.get(f"/api/org/people/{person['id']}"))['invite'] is not None
    guest = TestClient(app)
    assert guest.post('/web-auth/invite/check', headers=ORIGIN, json={'token': old}).status_code == 400   # прежняя отменена
    assert ok(guest.post('/web-auth/invite/check', headers=ORIGIN, json={'token': token})) == {'name': 'Анна', 'email': None}
    seed('busy@example.com')
    assert guest.post('/web-auth/invite', headers=ORIGIN, json={'token': token, 'email': 'busy@example.com',
                                                               'password': PASSWORD}).json()['detail'] == 'email_taken'
    me = ok(guest.post('/web-auth/invite', headers=ORIGIN, json={'token': token, 'email': 'Anna@Example.com', 'password': PASSWORD}))
    assert me['email'] == 'anna@example.com' and me['account_status'] == 'active'
    assert ok(guest.get('/web-auth/me'))['full_name'] == 'Анна Петрова'   # сразу в кабинете
    assert guest.post('/web-auth/invite', headers=ORIGIN, json={'token': token, 'email': 'x@example.com',
                                                               'password': PASSWORD}).status_code == 400   # одноразовая
    assert c.post(f"/api/org/people/{person['id']}/invite", headers=ORIGIN).json()['detail'] == 'already_active'
    reset = ok(c.post(f"/api/org/people/{person['id']}/reset-link", headers=ORIGIN))
    assert '/auth/reset-password#' in reset['link'] and 'type=reset_password' in reset['link']
    raw = reset['link'].split('token=')[1].split('&')[0]
    ok(TestClient(app).post('/auth/password/reset', json={'token': raw, 'password': 'Another-strong-password-1'}), 204)
    assert guest.get('/web-auth/me').status_code == 401   # прежние входы завершены
    assert c.patch(f"/api/org/people/{person['id']}", headers=ORIGIN, json={'email': 'new@example.com'}).json()['detail'] == 'email_locked'


def test_invite_with_preset_email(app, seed):
    c = org(app, seed)
    person = ok(c.post('/api/org/people', headers=ORIGIN, json={'full_name': 'Ольга', 'email': 'olga@example.com'}), 201)
    token = ok(c.post(f"/api/org/people/{person['id']}/invite", headers=ORIGIN))['link'].split('token=')[1]
    guest = TestClient(app)
    assert ok(guest.post('/web-auth/invite/check', headers=ORIGIN, json={'token': token}))['email'] == 'olga@example.com'
    assert guest.post('/web-auth/invite', headers=ORIGIN, json={'token': token, 'email': 'other@example.com',
                                                               'password': PASSWORD}).json()['detail'] == 'email_preset'
    ok(guest.post('/web-auth/invite', headers=ORIGIN, json={'token': token, 'email': 'olga@example.com', 'password': PASSWORD}))


def test_people_list_roles_and_suspend(app, seed):
    c = org(app, seed)
    me = ok(c.get('/web-auth/me'))
    for i in range(3):
        ok(c.post('/api/org/people', headers=ORIGIN, json={'full_name': f'Участница {i}', 'city': 'Пермь'}), 201)
    data = ok(c.get('/api/org/people', params={'q': 'пермь'}))
    assert len(data['people']) == 3 and data['counts']['not_activated'] == 3
    assert ok(c.get('/api/org/people', params={'q': '100%'}))['people'] == []
    staff = ok(c.get('/api/org/people', params={'kind': 'staff'}))['people']
    assert [p['email'] for p in staff] == ['org@example.com']
    r = c.post(f"/api/org/people/{me['id']}/roles", headers=ORIGIN, json={'role': 'admin', 'enabled': False})
    assert r.json()['detail'] == 'cannot_remove_own_admin'
    assert c.post(f"/api/org/people/{me['id']}/suspend", headers=ORIGIN, json={'suspended': True}).json()['detail'] == 'cannot_suspend_self'
    p = login(app, seed, 'p@example.com')
    pid = ok(p.get('/web-auth/me'))['id']
    got = ok(c.post(f'/api/org/people/{pid}/roles', headers=ORIGIN, json={'role': 'moderator', 'enabled': True}))
    assert got['roles'] == ['moderator', 'participant']
    ok(c.post(f'/api/org/people/{pid}/suspend', headers=ORIGIN, json={'suspended': True}))
    assert p.get('/web-auth/me').status_code == 401
    assert TestClient(app).post('/web-auth/login', headers=ORIGIN, json={'email': 'p@example.com', 'password': PASSWORD}).status_code == 401
    back = ok(c.post(f'/api/org/people/{pid}/suspend', headers=ORIGIN, json={'suspended': False}))
    assert back['account_status'] == 'active'


# ---------- участница Игры ----------

def test_participant_actions(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    assert ep['mode'] == 'in' and ep['rounds'][0]['work'] == 'none' and ep['rounds'][1]['work'] == 'plan' and ep['rules_ok']
    # Срок тура 1 прошёл, тур 2 открылся — опоздавшая вне конкурса; организатор продлевает срок и возвращает.
    clock.set(h(days=2, hours=1))
    lst = ok(c.get(f'/api/org/events/{eid}/participants'))
    assert lst['participants'][0]['mode'] == 'outside' and lst['participants'][0]['rounds'][0]['work'] == 'missed'
    bad = c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'return', 'reason': 'Ошибка'})
    assert bad.json()['detail'] == 'still_missed'
    assert c.post(f"/api/org/participants/{ep['id']}/deadline", headers=ORIGIN, json={
        'round_id': rounds[0], 'deadline': h(days=3).isoformat()}).json()['detail'] == 'reason_required'
    ext = ok(c.post(f"/api/org/participants/{ep['id']}/deadline", headers=ORIGIN, json={
        'round_id': rounds[0], 'deadline': h(days=3).isoformat(), 'reason': 'Болела'}))
    assert ext['rounds'][0]['personal']['reason'] == 'Болела' and ext['rounds'][0]['deadline_source'] == 'personal'
    back = ok(c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'return', 'reason': 'Продлили срок'}))
    assert back['mode'] == 'in' and back['missed_round'] is None
    task = ok(p.get(f'/api/games/{eid}'))['rounds'][0]
    assert task['can_submit'] and task['deadline'] == h(days=3).isoformat()
    send_work(p, {'event': eid, 'tasks': [task['assignment_id']]}, 0)
    detail = ok(c.get(f"/api/org/participants/{ep['id']}"))
    assert detail['rounds'][0]['work'] == 'sent' and detail['rounds'][0]['submitted']['photos']
    photo = detail['rounds'][0]['submitted']['photos'][0]['thumb_url']
    assert c.get(photo).status_code == 200   # организатор видит фото работы
    assert [x['action'] for x in detail['log']][:2] == ['org_return', 'deadline_extended']
    # Вне конкурса, вывод из Игры и возврат, дисквалификация.
    out = ok(c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'outside', 'reason': 'Просьба'}))
    assert out['mode'] == 'outside' and out['out_source'] == 'admin'
    ok(c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'withdraw', 'reason': 'Сама попросила'}))
    assert ok(p.get(f'/api/games/{eid}'))['me']['mode'] == 'withdrawn'
    ok(c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'restore', 'reason': 'Передумала'}))
    dq = ok(c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'disqualify', 'reason': 'Чужая работа'}))
    assert dq['mode'] == 'disqualified'
    titles = [n['title'] for n in ok(p.get('/api/notifications'))['notifications']]
    assert 'Участие в Игре прекращено' in titles and 'Срок сдачи тура 1 продлён для вас' in titles
    assert c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'outside', 'reason': ' '}).status_code == 422


def test_personal_deadline_rules(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    url = f"/api/org/participants/{ep['id']}/deadline"
    assert c.post(url, headers=ORIGIN, json={'round_id': rounds[0], 'deadline': h(hours=2).isoformat(),
                                             'reason': 'x'}).json()['detail'] == 'not_an_extension'
    assert c.post(url, headers=ORIGIN, json={'round_id': rounds[0], 'deadline': h(days=40).isoformat(),
                                             'reason': 'x'}).json()['detail'] == 'deadline_after_game_end'
    # Тур 2 ещё не открыт — продление всё равно можно назначить заранее.
    ok(c.post(url, headers=ORIGIN, json={'round_id': rounds[1], 'deadline': h(days=6).isoformat(), 'reason': 'Отпуск'}))
    reset = ok(c.post(url, headers=ORIGIN, json={'round_id': rounds[1], 'deadline': None, 'reason': 'Вернулась раньше'}))
    assert reset['rounds'][1]['personal'] is None


# ---------- поддержка и пожелания ----------

def test_support_inbox_reply(app, seed):
    c = org(app, seed)
    p = login(app, seed, 'p@example.com')
    t = ok(p.post('/api/support', headers=ORIGIN, json={'subject': 'Не грузится фото', 'body': 'Помогите'}), 201)
    inbox = ok(c.get('/api/org/support'))
    assert inbox['counts']['waiting'] == 1 and inbox['threads'][0]['no'] == t['no']
    assert ok(c.get('/api/org/support', params={'q': str(t['no'])}))['threads']
    got = ok(c.post(f"/api/org/support/{t['no']}/reply", headers=ORIGIN, json={'body': 'Сожмите фото до 20 МБ'}))
    assert got['status'] == 'waiting_user' and got['messages'][-1]['from'] == 'admin'
    mine = ok(p.get(f"/api/support/{t['no']}"))
    assert mine['status'] == 'waiting_user' and mine['messages'][-1]['author'] == 'Организатор'
    assert any(n['route'] == 'support' for n in ok(p.get('/api/notifications'))['notifications'])
    ok(p.post(f"/api/support/{t['no']}/messages", headers=ORIGIN, json={'body': 'Спасибо, получилось'}))
    assert ok(c.get('/api/org/support'))['counts']['waiting'] == 1
    closed = ok(c.post(f"/api/org/support/{t['no']}/status", headers=ORIGIN, json={'status': 'closed'}))
    assert closed['status'] == 'closed'


def test_anonymous_feedback(app, seed):
    guest = TestClient(app)
    assert guest.post('/api/public/feedback', json={'text': 'Без Origin'}).status_code == 403
    ok(guest.post('/api/public/feedback', headers=ORIGIN, json={'text': '  Хочу тур про зиму ', 'page': '/'}), 201)
    ok(guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'Спам', 'website': 'http://spam'}), 201)
    ok(guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'Ответьте мне', 'contact': '@anna'}), 201)
    assert guest.post('/api/public/feedback', headers=ORIGIN, json={'text': ' '}).status_code == 422
    assert guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'x' * 2001}).status_code == 422
    for _ in range(2):
        guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'ещё'})
    assert guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'шестое'}).status_code == 429
    with app.state.db.transaction() as conn:   # окно — час: через 20 минут всё ещё нельзя, через час — можно
        conn.execute("UPDATE auth_rate_limits SET window_start=now()-interval '20 minutes'")
    assert guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'седьмое'}).status_code == 429
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE auth_rate_limits SET window_start=now()-interval '61 minutes'")
    ok(guest.post('/api/public/feedback', headers=ORIGIN, json={'text': 'через час'}), 201)
    with app.state.db.transaction() as conn:
        conn.execute("DELETE FROM feedback_messages WHERE body='через час'")
    c = org(app, seed)
    items = ok(c.get('/api/org/feedback'))['items']
    texts = [i['text'] for i in items]
    assert 'Хочу тур про зиму' in texts and 'Спам' not in texts and len(items) == 4
    with app.state.db.transaction() as conn:
        cols = {r['column_name'] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='feedback_messages'")}
    assert not cols & {'ip', 'user_agent', 'user_id'}
    first = items[0]
    read = ok(c.post(f"/api/org/feedback/{first['id']}", headers=ORIGIN, json={'status': 'archived'}))
    assert read['status'] == 'archived' and read['read_at']
    assert len(ok(c.get('/api/org/feedback'))['items']) == 3
    assert ok(c.get('/api/org/home'))['counts']['feedback'] == 3
    p = login(app, seed, 'p@example.com')
    assert p.get('/api/org/feedback').status_code == 403


def test_dashboard(app, seed, clock):
    c = org(app, seed)
    home = ok(c.get('/api/org/home'))
    assert home['documents'] == {'rules': False, 'publication': False, 'personal_data': False} and home['games'] == []
    publish_docs(c)
    eid, _ = game_ready(c, rounds=2)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    home = ok(c.get('/api/org/home'))
    g = home['games'][0]
    assert g['people'] == 1 and g['current']['round_no'] == 1 and g['next']['round_no'] == 2


def test_org_pages_served(client):
    for path in ('/org', '/org/games/x', '/auth/invite', '/gallery'):
        r = client.get(path)
        assert r.status_code == 200 and 'core.js' in r.text


# ---------- регистрация самой участницей, название задания для лиги ----------

def test_self_signup(app, seed):
    guest = TestClient(app)
    me = ok(guest.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'New@Example.com', 'password': PASSWORD,
                                                                   'full_name': ' Мария Иванова '}), 201)
    assert me['email'] == 'new@example.com' and me['roles'] == ['participant'] and me['full_name'] == 'Мария Иванова'
    assert ok(guest.get('/web-auth/me'))['id'] == me['id']
    other = TestClient(app)
    assert other.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'new@example.com', 'password': PASSWORD,
                                                                  'full_name': 'X'}).json()['detail'] == 'email_taken'
    c = org(app, seed)
    bot = ok(c.post('/api/org/people', headers=ORIGIN, json={'full_name': 'Из бота', 'email': 'bot@example.com'}), 201)
    assert other.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'bot@example.com', 'password': PASSWORD,
                                                                  'full_name': 'X'}).json()['detail'] == 'email_invited'
    assert other.post('/web-auth/register', json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'z@example.com', 'password': PASSWORD, 'full_name': 'Z'}).status_code == 403
    assert other.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'z@example.com', 'password': 'short',
                                                                  'full_name': 'Z'}).status_code == 422
    assert bot['account_status'] == 'imported'


def test_league_title(app, seed, clock):
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=1)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    r = ok(c.get(f'/api/org/rounds/{rounds[0]}'))
    assert [v['title'] for v in r['task']['variants']] == [None, None]
    # До выдачи заданий лиги меняются свободно — но тур уже открыт, поэтому меняем только тексты и названия.
    got = ok(c.put(f'/api/org/rounds/{rounds[0]}/task', headers=ORIGIN, json={
        'title': 'Бабочка 1', 'form': {'photo': 'required', 'link': 'optional', 'photo_max': 1},
        'variants': [{'league': None, 'instructions': 'Общий текст 1'},
                     {'league': 'gold', 'title': 'Бабочка-махаон', 'instructions': 'Текст для Gold 1'}]}))
    assert [v['title'] for v in got['task']['variants']] == [None, 'Бабочка-махаон']
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    ok(c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    task = ok(p.get(f"/api/games/{eid}/tasks/{got['task']['id']}"))
    assert task['assignment']['title'] == 'Бабочка-махаон' and task['instructions'] == 'Текст для Gold 1'


def test_league_deadline(app, seed, clock):
    """У Gold свой срок сдачи тура 1 — на 2 дня позже общего: опоздание и переход вне конкурса считаются по нему."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    form = {'photo': 'required', 'link': 'optional', 'photo_max': 1}
    assert c.put(f'/api/org/rounds/{rounds[0]}/task', headers=ORIGIN, json={'title': 'Бабочка 1', 'form': form, 'variants': [
        {'league': None, 'instructions': 'Общий текст 1'},
        {'league': 'gold', 'instructions': 'Текст для Gold 1', 'deadline': h(days=40).isoformat()}]}).json()['detail'] \
        == 'league_deadline_after_game_end'
    got = ok(c.put(f'/api/org/rounds/{rounds[0]}/task', headers=ORIGIN, json={'title': 'Бабочка 1', 'form': form, 'variants': [
        {'league': None, 'instructions': 'Общий текст 1'},
        {'league': 'gold', 'instructions': 'Текст для Gold 1', 'deadline': h(days=3).isoformat()}]}))
    assert [v['deadline'] for v in got['task']['variants']] == [None, h(days=3).isoformat()]
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    pg, pb = login(app, seed, 'gold@example.com'), login(app, seed, 'bronze@example.com')
    ok(register(pg, eid), 201)
    ok(register(pb, eid), 201)
    people = ok(c.get(f'/api/org/events/{eid}/participants'))['participants']
    gold = next(x for x in people if x['email'] == 'gold@example.com')
    ok(c.post(f"/api/org/participants/{gold['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    g = ok(pg.get(f'/api/games/{eid}'))['rounds'][0]
    assert g['deadline'] == h(days=3).isoformat()
    clock.set(h(days=2, hours=1))   # общий срок прошёл, тур 2 открыт
    assert ok(pb.get(f'/api/games/{eid}'))['me']['mode'] == 'outside'
    g = ok(pg.get(f'/api/games/{eid}'))
    assert g['me']['mode'] == 'in' and g['rounds'][0]['can_submit']
    send_work(pg, {'event': eid, 'tasks': [g['rounds'][0]['assignment_id']]}, 0)
    lst = {x['email']: x for x in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    assert lst['gold@example.com']['rounds'][0]['work'] == 'sent' and lst['bronze@example.com']['rounds'][0]['work'] == 'missed'
    assert ok(c.get(f'/api/org/rounds/{rounds[0]}'))['state'] == 'open'   # для Gold ещё идёт сдача
    ext = c.post(f"/api/org/participants/{gold['id']}/deadline", headers=ORIGIN, json={
        'round_id': rounds[0], 'deadline': h(days=2, hours=12).isoformat(), 'reason': 'x'})
    assert ext.json()['detail'] == 'not_an_extension'   # раньше срока её лиги — не продление


def test_league_opening_date(app, seed, clock):
    """У Gold своё открытие задания тура 2 (через 3 дня, а не через 2) и свой срок: участница видит задание по дате своей
    лиги; опоздавшая в Gold переходит вне конкурса с открытия тура 2 для Gold; открывшейся лиге дату не поменять."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    form = {'photo': 'required', 'link': 'optional', 'photo_max': 1}

    def task(opens=None, deadline=None, text='Текст для Gold 2'):
        gold = {'league': 'gold', 'instructions': text}
        if opens:
            gold['opens_at'] = opens.isoformat()
        if deadline:
            gold['deadline'] = deadline.isoformat()
        return c.put(f'/api/org/rounds/{rounds[1]}/task', headers=ORIGIN, json={
            'title': 'Бабочка 2', 'form': form, 'variants': [{'league': None, 'instructions': 'Общий текст 2'}, gold]})

    assert task(opens=h(days=5)).json()['detail'] == 'league_open_after_deadline'     # позже общего срока (+4 дня)
    assert task(opens=h(days=3), deadline=h(days=2, hours=12)).json()['detail'] == 'league_deadline_before_open'
    got = ok(task(opens=h(days=3), deadline=h(days=5)))
    gold_v = got['task']['variants'][1]
    assert gold_v['opens_at'] == h(days=3).isoformat() and gold_v['deadline'] == h(days=5).isoformat()
    # общий срок тура нельзя сдвинуть раньше открытия Gold, у которой нет своего срока — тут свой есть, поэтому можно
    ok(c.patch(f'/api/org/rounds/{rounds[1]}', headers=ORIGIN, json={'deadline': h(days=4, hours=6).isoformat()}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))

    pg, pg2, pb = login(app, seed, 'gold@example.com'), login(app, seed, 'gold2@example.com'), login(app, seed, 'bronze@example.com')
    for x in (pg, pg2, pb):
        ok(register(x, eid), 201)
    people = {x['email']: x for x in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    for mail in ('gold@example.com', 'gold2@example.com'):
        ok(c.post(f"/api/org/participants/{people[mail]['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    # страница Игры в каталоге и в «Моих Играх» — даты своей лиги
    cat = {x['round_no']: x for x in ok(pg.get(f'/api/events/{eid}'))['rounds']}
    assert cat[2]['opens_at'] == h(days=3).isoformat() and cat[2]['deadline'] == h(days=5).isoformat()
    cat = {x['round_no']: x for x in ok(pb.get(f'/api/events/{eid}'))['rounds']}
    assert cat[2]['opens_at'] == h(days=2).isoformat() and cat[2]['deadline'] == h(days=4, hours=6).isoformat()
    g = ok(pg.get(f'/api/games/{eid}'))
    send_work(pg, {'event': eid, 'tasks': [g['rounds'][0]['assignment_id']]}, 0)
    send_work(pb, {'event': eid, 'tasks': [ok(pb.get(f'/api/games/{eid}'))['rounds'][0]['assignment_id']]}, 0)

    clock.set(h(days=2, hours=1))   # тур 2 открыт по общей дате, для Gold — ещё нет
    b2 = ok(pb.get(f'/api/games/{eid}'))['rounds'][1]
    assert b2['state'] != 'plan' and b2['can_submit']
    g2 = ok(pg.get(f'/api/games/{eid}'))['rounds'][1]
    assert g2['state'] == 'plan' and not g2['can_submit'] and g2['opens_at'] == h(days=3).isoformat()
    assert pg.get(f"/api/games/{eid}/tasks/{g2['assignment_id']}").json().get('opened') is not True
    # gold2 пропустила срок тура 1, но тур 2 для её лиги ещё не открыт — пока в конкурсе
    assert ok(pg2.get(f'/api/games/{eid}'))['me']['mode'] == 'in'
    det = ok(c.get(f'/api/org/rounds/{rounds[1]}'))
    assert det['state'] == 'open' and det['locks']['form'] and det['locks']['opens_at']
    # Gold ещё не открылась — её дату открытия можно сдвинуть
    ok(task(opens=h(days=2, hours=12), deadline=h(days=5)))
    clock.set(h(days=2, hours=13))
    assert ok(pg.get(f'/api/games/{eid}'))['rounds'][1]['can_submit']
    assert ok(pg2.get(f'/api/games/{eid}'))['me']['mode'] == 'outside'   # с открытия тура 2 для Gold
    assert task(opens=h(days=3), deadline=h(days=5)).json()['detail'] == 'league_opens_locked'
    assert task(deadline=h(days=5)).json()['detail'] == 'league_opens_locked'   # убрать свою дату = сменить открытие
    got = ok(task(opens=h(days=2, hours=12), deadline=h(days=5, hours=6)))      # срок лиги после открытия — можно
    assert got['task']['variants'][1]['deadline'] == h(days=5, hours=6).isoformat()


def test_league_same_text_and_open_now(app, seed, clock):
    """Лига только со своими датами получает общий текст (и его правки); «Открыть сейчас» открывает задание всем лигам."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    form = {'photo': 'required', 'link': 'optional', 'photo_max': 1}

    def task(general, opens=h(days=3)):
        gold = {'league': 'gold', 'instructions': '  '} | ({'opens_at': opens.isoformat()} if opens else {})
        return c.put(f'/api/org/rounds/{rounds[1]}/task', headers=ORIGIN, json={'title': 'Бабочка 2', 'form': form, 'variants': [
            {'league': None, 'instructions': general}, gold]})

    got = ok(task('Общий текст 2'))
    gold_v = got['task']['variants'][1]
    assert gold_v['same_text'] and gold_v['instructions'] == '' and not got['checks']['problems']
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    pg = login(app, seed, 'gold@example.com')
    ok(register(pg, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    ok(c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    clock.set(h(days=1, hours=1))
    assert ok(pg.get(f'/api/games/{eid}'))['rounds'][1]['state'] == 'plan'
    got = ok(c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'open_now'}))
    assert got['task']['variants'][1]['opens_at'] is None and got['state'] == 'open'
    r2 = ok(pg.get(f'/api/games/{eid}'))['rounds'][1]
    assert r2['state'] != 'plan' and r2['can_submit']
    t = ok(pg.get(f"/api/games/{eid}/tasks/{r2['assignment_id']}"))
    assert t['instructions'] == 'Общий текст 2'
    assert task('Общий текст 2, исправленный').json()['detail'] == 'league_opens_locked'   # Gold уже открыта
    got = ok(task('Общий текст 2, исправленный', opens=None))
    assert got['notified'] == 1
    assert ok(pg.get(f"/api/games/{eid}/tasks/{r2['assignment_id']}"))['instructions'] == 'Общий текст 2, исправленный'


def test_review_fixes(app, seed, clock):
    """Отмена дисквалификации возвращает прежнее состояние; конец Игры не раньше сроков лиг и личных сроков;
    снятие личного срока — с причиной и сообщением; срок открытого тура не в прошлом и с сообщением;
    «Открыть сейчас всем лигам», когда общая дата уже прошла; удаление черновика со ссылками — понятный отказ."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c, rounds=2)
    form = {'photo': 'required', 'link': 'optional', 'photo_max': 1}
    ok(c.put(f'/api/org/rounds/{rounds[1]}/task', headers=ORIGIN, json={'title': 'Бабочка 2', 'form': form, 'variants': [
        {'league': None, 'instructions': 'Общий текст 2'},
        {'league': 'gold', 'instructions': 'Gold 2', 'opens_at': h(days=3).isoformat(), 'deadline': h(days=10).isoformat()}]}))
    assert c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'ends_at': h(days=8).isoformat()}).json()['detail'] \
        == 'league_dates_after_end'
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    pa, pb = login(app, seed, 'a@example.com'), login(app, seed, 'b@example.com')
    ok(register(pa, eid), 201)
    ok(register(pb, eid), 201)
    people = {x['email']: x for x in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    a_id, b_id = people['a@example.com']['id'], people['b@example.com']['id']
    # вне конкурса → дисквалификация → отмена: снова вне конкурса, а не «в конкурсе»
    act = lambda ep, action: c.post(f'/api/org/participants/{ep}/action', headers=ORIGIN, json={'action': action, 'reason': 'x'})
    ok(act(a_id, 'outside'))
    ok(act(a_id, 'disqualify'))
    assert ok(act(a_id, 'undisqualify'))['mode'] == 'outside'
    # личный срок: продлить, конец Игры раньше него — нельзя; снять без причины — нельзя; с причиной — сообщение
    ok(c.post(f'/api/org/participants/{b_id}/deadline', headers=ORIGIN, json={
        'round_id': rounds[0], 'deadline': h(days=9).isoformat(), 'reason': 'болела'}))
    assert c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'ends_at': h(days=8, hours=12).isoformat()}).json()['detail'] \
        in ('personal_deadlines_after_end', 'league_dates_after_end')
    assert c.post(f'/api/org/participants/{b_id}/deadline', headers=ORIGIN, json={'round_id': rounds[0], 'deadline': None}) \
        .json()['detail'] == 'reason_required'
    ok(c.post(f'/api/org/participants/{b_id}/deadline', headers=ORIGIN, json={'round_id': rounds[0], 'deadline': None, 'reason': 'ошибка'}))
    titles = [n['title'] for n in ok(pb.get('/api/notifications'))['notifications']]
    assert 'Личный срок сдачи тура 1 отменён' in titles
    # срок открытого тура: не в прошлом; перенос — сообщение участницам
    assert c.patch(f'/api/org/rounds/{rounds[0]}', headers=ORIGIN, json={'deadline': h(minutes=-1).isoformat()}).json()['detail'] \
        == 'deadline_in_past'
    ok(c.patch(f'/api/org/rounds/{rounds[0]}', headers=ORIGIN, json={'deadline': h(days=1, hours=6).isoformat()}))
    assert 'Срок сдачи тура 1 изменён' in [n['title'] for n in ok(pb.get('/api/notifications'))['notifications']]
    # тур 2: общая дата прошла, Gold ещё ждёт — «Открыть сейчас всем лигам»
    clock.set(h(days=2, hours=1))
    det = ok(c.get(f'/api/org/rounds/{rounds[1]}'))
    assert det['state'] == 'open' and not det['all_open']
    det = ok(c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'open_now'}))
    assert det['all_open'] and det['opens_at'] == h(days=2).isoformat() and det['task']['variants'][1]['opens_at'] is None
    assert c.post(f'/api/org/rounds/{rounds[1]}/status', headers=ORIGIN, json={'action': 'open_now'}).status_code == 409
    # черновик, на который ссылается обращение, удалить нельзя — понятный отказ
    e2 = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'Игра 05'}), 201)
    with app.state.db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email='a@example.com'").fetchone()['id']
        conn.execute("""INSERT INTO support_threads(user_id,event_id,subject,status) VALUES (%s,%s,'Вопрос','open')""", (uid, e2['id']))
    assert c.delete(f"/api/org/events/{e2['id']}", headers=ORIGIN).json()['detail'] == 'has_links'
    assert ok(c.get(f"/api/org/events/{e2['id']}"))['status'] == 'draft'


def test_scheduled_rules_notice(app, seed, clock):
    """Правила, вышедшие по расписанию, — сообщение при сверке (fpl-kabinet-sync), один раз и только не принявшим."""
    from kabinet.org.documents import notify_due_rules
    c = org(app, seed)
    publish_docs(c)
    eid, _ = game_ready(c, rounds=1)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ok(c.post('/api/org/documents', headers=ORIGIN, json={'doc_type': 'rules', 'version': '2.0', 'title': 'Правила 2.0',
                                                          'body': RULES_TEXT, 'publish_at': h(days=1).isoformat()}), 201)
    with app.state.db.transaction() as conn:
        assert notify_due_rules(conn, h(hours=1)) == 0       # ещё не вышли: действует 1.9, она её приняла
        assert notify_due_rules(conn, h(days=1, minutes=5)) == 1
        notify_due_rules(conn, h(days=1, minutes=15))         # повтор ничего не дублирует
    titles = [n['title'] for n in ok(p.get('/api/notifications'))['notifications']]
    assert titles.count('Новая редакция Правил — 2.0') == 1


def test_season_for_site_rating(app, seed, clock):
    """Игра стартовала — сезон идёт; лига участницы — её лига в сезоне (сайт показывает рейтинг идущих сезонов)."""
    c = org(app, seed)
    publish_docs(c)
    season = ok(c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Сезон 2', 'season_no': 2}), 201)
    eid, rounds = game_ready(c)
    ok(c.patch(f'/api/org/events/{eid}', headers=ORIGIN, json={'season_id': season['id']}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    ok(c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'silver'}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    ok(c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'gold'}))
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT status FROM seasons WHERE id=%s', (season['id'],)).fetchone()['status'] == 'active'
        sp = conn.execute('SELECT * FROM season_participants WHERE season_id=%s', (season['id'],)).fetchone()
    assert (sp['league_at_start'], sp['current_league']) == ('silver', 'gold')


def test_login_limit_per_address_is_wider(app, seed):
    """Общий адрес мобильного оператора: 30 разных участниц входят с одного адреса; на один email лимит прежний."""
    app.state.auth.settings.login_limit = 3
    c = TestClient(app)
    for i in range(30):
        seed(f'm{i}@example.com')
        assert c.post('/auth/login', json={'email': f'm{i}@example.com', 'password': PASSWORD}).status_code == 200
    codes = [c.post('/auth/login', json={'email': 'm0@example.com', 'password': 'wrong-password-123'}).status_code for _ in range(4)]
    assert codes[-1] == 429


def test_password_checks_are_bounded():
    """Не больше двух проверок пароля одновременно (Argon2id — 64 МБ на проверку)."""
    import threading
    import time
    from kabinet.auth.security import BoundedHasher
    state = {'now': 0, 'max': 0}
    lock = threading.Lock()

    class Slow:
        def verify(self, p, h):
            with lock:
                state['now'] += 1
                state['max'] = max(state['max'], state['now'])
            time.sleep(0.05)
            with lock:
                state['now'] -= 1
            return True
    hasher = BoundedHasher(Slow())
    threads = [threading.Thread(target=hasher.verify, args=('a', 'b')) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state['max'] == 2


def test_league_after_finish_until_results(app, seed, clock):
    """Без лиги диплом не выдать: лигу можно указать и в завершённой Игре — пока итоги не опубликованы."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    p = login(app, seed, 'p@example.com')
    ok(register(p, eid), 201)
    ep = ok(c.get(f'/api/org/events/{eid}/participants'))['participants'][0]
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'finish', 'early': True}))
    ok(c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'bronze'}))
    r = c.post(f"/api/org/participants/{ep['id']}/action", headers=ORIGIN, json={'action': 'outside', 'reason': 'тест'})
    assert r.status_code == 409 and r.json()['detail'] == 'game_finished'     # остальные действия — как раньше
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE events SET settings=jsonb_set(coalesce(settings,'{}'),'{results}','{"published_at":"2026-11-30T00:00:00+00:00"}')
WHERE id=%s''', (eid,))
    r = c.post(f"/api/org/participants/{ep['id']}/league", headers=ORIGIN, json={'league': 'gold'})
    assert r.status_code == 409 and r.json()['detail'] == 'game_finished'


def test_too_many_waiting_logins_get_busy():
    """Лишние ждущие проверки пароля сразу получают «занято» (поток службы не держится)."""
    import threading
    import time
    from kabinet.auth.security import BoundedHasher, Busy

    class Slow:
        def verify(self, p, h):
            time.sleep(0.1)
            return True
    hasher = BoundedHasher(Slow(), limit=1, max_waiting=2)
    out = []

    def one():
        try:
            out.append(hasher.verify('a', 'b'))
        except Busy:
            out.append('busy')
    threads = [threading.Thread(target=one) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert out.count('busy') >= 1 and out.count(True) >= 3


def test_leagues_in_bulk(app, seed, clock):
    """Лиги списком: одним сохранением, уведомления — только тем, у кого лига поменялась; чужой участник — отказ."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    for i in range(5):
        ok(register(login(app, seed, f'b{i}@example.com'), eid), 201)
    lst = ok(c.get(f'/api/org/events/{eid}/participants'))['participants']
    assert all('rating' in p for p in lst)
    items = [{'id': p['id'], 'league': ('gold', 'silver', 'bronze', 'bronze', None)[k]} for k, p in enumerate(lst)]
    r = ok(c.post(f'/api/org/events/{eid}/leagues', headers=ORIGIN, json={'items': items}))
    assert r['changed'] == 4
    again = ok(c.post(f'/api/org/events/{eid}/leagues', headers=ORIGIN, json={'items': items}))
    assert again['changed'] == 0
    got = {p['id']: p['league'] for p in ok(c.get(f'/api/org/events/{eid}/participants'))['participants']}
    assert [got[x['id']] for x in items] == ['gold', 'silver', 'bronze', 'bronze', None]
    dup = c.post(f'/api/org/events/{eid}/leagues', headers=ORIGIN, json={'items': items[:1] * 2})
    assert dup.status_code == 422 and dup.json()['detail'] == 'duplicate_participant'
    other, _ = game_ready(c, title='Игра 03')
    bad = c.post(f'/api/org/events/{other}/leagues', headers=ORIGIN, json={'items': items[:1]})
    assert bad.status_code in (404, 409)
    with app.state.db.transaction() as conn:
        n = conn.execute("SELECT count(*) AS n FROM notifications WHERE notification_type='league'").fetchone()['n']
    assert n == 4
    p = login(app, seed, 'x@example.com')
    assert p.post(f'/api/org/events/{eid}/leagues', headers=ORIGIN, json={'items': items[:1]}).status_code == 403


def test_busy_login_does_not_count(app, seed, monkeypatch):
    """«Занято» при входе — попытка не тратит лимит (повторы после рассылки не упираются в 429)."""
    from kabinet.auth import service as AS
    from kabinet.auth.security import Busy
    seed('busy@example.com')
    app.state.auth.settings.login_limit = 2
    calls = {'n': 0}

    def busy(password, encoded):
        calls['n'] += 1
        raise Busy()
    monkeypatch.setattr(AS, 'verify_password', busy)
    c = TestClient(app)
    codes = [c.post('/auth/login', json={'email': 'busy@example.com', 'password': PASSWORD}).status_code for _ in range(5)]
    assert codes == [503] * 5 and calls['n'] == 5
    monkeypatch.undo()
    assert c.post('/auth/login', json={'email': 'busy@example.com', 'password': PASSWORD}).status_code == 200


def test_home_reminds_org_steps(app, seed, clock):
    """Обзор подсказывает шаги, которые кабинет сам не делает: начать Игру, начать судейство, завершить Игру."""
    c = org(app, seed)
    publish_docs(c)
    eid, rounds = game_ready(c)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    alerts = ok(c.get('/api/org/home'))['alerts']
    assert any('Пора начать' in a['title'] for a in alerts)          # старт был вчера, Игра не начата
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'start'}))
    clock.set(h(days=1, minutes=5))
    alerts = ok(c.get('/api/org/home'))['alerts']
    assert any('тур 1: приём закрыт' in a['title'] and a['href'] == f'/org/rounds/{rounds[0]}/judging' for a in alerts)
    assert not any('Пора начать' in a['title'] for a in alerts)
