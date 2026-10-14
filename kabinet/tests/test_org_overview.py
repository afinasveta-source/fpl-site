"""Кабинет организатора (17.10): «Игры и туры» одним запросом, счётчики «ждёт ответа» в меню, фильтры списков участниц и людей."""
from fastapi.testclient import TestClient

from conftest import PASSWORD
from game_helpers import ORIGIN, add_docs, build_game, h, login, register, send_work


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content else None


def org(app, seed):
    return login(app, seed, 'org@example.com', roles=('admin',))


def game_with_people(app, seed):
    """Игра 02 (идёт, сезон 1, тур 1 открыт): Gold — Анна (в конкурсе, сдала) и Белла (в конкурсе, не сдала);
    Silver — Вера (в конкурсе, сдала после срока); без лиги — Галина (вне конкурса) и Дина (вышла из Игры)."""
    c = org(app, seed)
    with app.state.db.transaction() as conn:
        add_docs(conn)
        game = build_game(conn)
    people = {}
    for name, mail in (('Анна', 'anna'), ('Белла', 'bella'), ('Вера', 'vera'), ('Галина', 'galina'), ('Дина', 'dina')):
        p = login(app, seed, f'{mail}@example.com')
        with app.state.db.transaction() as conn:
            conn.execute('UPDATE users SET full_name=%s WHERE email=%s', (f'{name} Тестова', f'{mail}@example.com'))
        ok(register(p, game['event']), 201)
        people[mail] = p
    send_work(people['anna'], game, 0)
    send_work(people['vera'], game, 0)
    season = ok(c.post('/api/org/seasons', headers=ORIGIN, json={'name': 'Сезон 1', 'season_no': 1}), 201)
    with app.state.db.transaction() as conn:
        eps = {r['email'].split('@')[0]: r['id'] for r in conn.execute('''SELECT p.id, u.email FROM event_participants p
JOIN users u ON u.id=p.user_id WHERE p.event_id=%s''', (game['event'],))}
        conn.execute("UPDATE event_participants SET entry_league='gold' WHERE id = ANY(%s)", ([eps['anna'], eps['bella']],))
        conn.execute("UPDATE event_participants SET entry_league='silver' WHERE id=%s", (eps['vera'],))
        conn.execute('''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='late',
out_of_competition_at=now(), out_of_competition_source='admin' WHERE id=%s''', (eps['galina'],))
        conn.execute("UPDATE event_participants SET registration_status='withdrawn' WHERE id=%s", (eps['dina'],))
        conn.execute('''UPDATE submissions SET is_on_time=false WHERE event_participant_id=%s''', (eps['vera'],))
        conn.execute('UPDATE events SET season_id=%s WHERE id=%s', (season['id'], game['event']))
    return c, game, eps, people


def test_games_overview(app, seed, clock):
    c, game, eps, _ = game_with_people(app, seed)
    other = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'Игра 03 (черновик)'}), 201)
    d = ok(c.get('/api/org/games/overview'))
    cur = d['current']
    assert cur['id'] == str(game['event']) and cur['season'] == 'Сезон 1' and cur['game_no'] == 2
    p = cur['people']
    assert (p['total'], p['in'], p['outside'], p['out']) == (5, 3, 1, 1)
    assert p['leagues']['gold'] == {'total': 2, 'in': 2, 'outside': 0, 'out': 0, 'other': 0}
    assert p['leagues']['none']['outside'] == 1 and p['leagues']['none']['out'] == 1
    r1, r2, r3 = cur['rounds']
    assert (r1['phase'], r2['phase'], r3['phase']) == ('open', 'plan', 'plan') and r1.get('current') and not r2.get('current')
    # тур 1: сдали Анна (в срок) и Вера (после срока); в конкурсе не сдала Белла (Gold)
    assert r1['works'] == {'sent': 2, 'late': 1, 'results': 0, 'advanced': 0, 'missing_in': 1}
    assert r1['by_league']['gold'] == {'sent': 1, 'late': 0, 'in_now': 2, 'results': 0, 'advanced': 0, 'missing_in': 1}
    assert r1['by_league']['silver']['late'] == 1 and r1['by_league']['silver']['missing_in'] == 0
    assert r1['judging'] is None and r2['works']['sent'] == 0
    # тур 3 «прошёл в боте»: итоги из бота и фото в архиве; тур 2 — судейство
    with app.state.db.transaction() as conn:
        conn.execute('''UPDATE rounds SET settings='{"source":"bot"}', status='published' WHERE id=%s''', (game['rounds'][2],))
        conn.execute("UPDATE rounds SET status='judging' WHERE id=%s", (game['rounds'][1],))
        for who, adv in (('anna', True), ('bella', False)):
            conn.execute('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,is_current,status,display_score,advanced,published_at)
VALUES (%s,%s,%s,1,true,'published',70,%s,now())''', (game['event'], game['rounds'][2], eps[who], adv))
    d = ok(c.get('/api/org/games/overview'))
    r1, r2, r3 = d['current']['rounds']
    assert r3['phase'] == 'bot' and r3['works']['results'] == 2 and r3['works']['advanced'] == 1 and 'missing_in' not in r3['by_league']['gold']
    assert r2['phase'] == 'judging' and r2.get('current') and not r1.get('current')
    # сезоны: сезон текущей Игры отмечен; черновик без сезона — отдельно
    s1 = d['seasons'][0]
    assert s1['current'] and [e['id'] for e in s1['events']] == [str(game['event'])] and s1['events'][0]['people']['in'] == 3
    assert [e['id'] for e in d['no_season']] == [other['id']] and not d['no_season'][0]['current']
    p = login(app, seed, 'zoe@example.com')
    assert p.get('/api/org/games/overview').status_code == 403


def test_current_game_choice(app, seed, clock):
    c = org(app, seed)
    assert ok(c.get('/api/org/games/overview'))['current'] is None
    with app.state.db.transaction() as conn:
        done = build_game(conn, status='finished', title='Игра 01')
    assert ok(c.get('/api/org/games/overview'))['current']['id'] == str(done['event'])
    with app.state.db.transaction() as conn:
        reg = build_game(conn, status='registration', title='Игра 02')
    assert ok(c.get('/api/org/games/overview'))['current']['id'] == str(reg['event'])
    with app.state.db.transaction() as conn:
        live = build_game(conn, status='active', title='Игра 03')
    assert ok(c.get('/api/org/games/overview'))['current']['id'] == str(live['event'])


def test_attention_counts(app, seed, clock):
    c = org(app, seed)
    zero = ok(c.get('/api/org/attention'))
    assert zero == {'support': 0, 'feedback': 0, 'reviews': 0, 'claims_pending': 0, 'accounts': 0, 'claims': 0, 'total': 0}
    # поддержка: ждёт, пока последней написала участница
    p = login(app, seed, 'p@example.com')
    t = ok(p.post('/api/support', headers=ORIGIN, json={'subject': 'Фото', 'body': 'Не грузится'}), 201)
    assert ok(c.get('/api/org/attention'))['support'] == 1
    ok(c.post(f"/api/org/support/{t['no']}/reply", headers=ORIGIN, json={'body': 'Сожмите фото'}))
    assert ok(c.get('/api/org/attention'))['support'] == 0
    ok(p.post(f"/api/support/{t['no']}/messages", headers=ORIGIN, json={'body': 'Не помогло'}))
    assert ok(c.get('/api/org/attention'))['support'] == 1
    ok(c.post(f"/api/org/support/{t['no']}/status", headers=ORIGIN, json={'status': 'closed'}))
    assert ok(c.get('/api/org/attention'))['support'] == 0
    # пожелания: новые, пока не открыты
    guest = TestClient(app)
    for text in ('Хочу тур про зиму', 'И про весну'):
        ok(guest.post('/api/public/feedback', headers=ORIGIN, json={'text': text}), 201)
    assert ok(c.get('/api/org/attention'))['feedback'] == 2
    first = ok(c.get('/api/org/feedback'))['items'][0]
    ok(c.post(f"/api/org/feedback/{first['id']}", headers=ORIGIN, json={'status': 'read'}))
    assert ok(c.get('/api/org/attention'))['feedback'] == 1
    # заявки: заявка на вход + завела кабинет сама, похожа на участницу из бота; новичок без похожих — не в счёт
    with app.state.db.transaction() as conn:
        ev = conn.execute('''INSERT INTO events(event_type,status,title,settings) VALUES ('ranked_game','active','Игра 01',
'{"moved_to_kabinet": "2026-10-13"}') RETURNING id''').fetchone()['id']
        bot = conn.execute("INSERT INTO users(full_name,account_status) VALUES ('Смирнова Анна Петровна','imported') RETURNING id").fetchone()['id']
        conn.execute('''INSERT INTO event_participants(event_id,user_id,registration_status,eligibility_status,payment_status)
VALUES (%s,%s,'participating','eligible','not_required')''', (ev, bot))
        conn.execute('''INSERT INTO account_claims(event_id,full_name,email,password_hash,country_code,city)
VALUES (%s,'Кузнецова Ольга','olga@example.com','x','RU','Москва')''', (ev,))
    for mail, name in (('anna.s@example.com', 'Смирнова Анна Ивановна'), ('new@example.com', 'Новикова Дарья')):
        ok(TestClient(app).post('/web-auth/register', headers=ORIGIN, json={
            'accept_personal_data': True, 'confirm_adult': True, 'email': mail, 'password': PASSWORD, 'full_name': name}), 201)
    got = ok(c.get('/api/org/attention'))
    assert (got['claims_pending'], got['accounts'], got['claims'], got['total']) == (1, 1, 2, 3)
    assert ok(c.get('/api/org/home'))['counts']['claims'] == 2   # Обзор — те же цифры
    # Опрос раз в минуту не упирается в ограничения частоты входа
    for _ in range(30):
        assert c.get('/api/org/attention').status_code == 200
    assert p.get('/api/org/attention').status_code == 403
    assert TestClient(app).get('/api/org/attention').status_code == 401


def test_participant_list_filters(app, seed, clock):
    c, game, eps, _ = game_with_people(app, seed)
    base = f"/api/org/events/{game['event']}/participants"
    names = lambda d: sorted(p['name'].split()[0] for p in d['participants'])
    d = ok(c.get(base))
    assert d['groups'] == {'in': 3, 'outside': 1, 'out': 1} and d['shown'] == 5 and d['total'] == 5
    assert d['leagues'] == {'gold': 2, 'silver': 1, 'none': 2}
    assert names(ok(c.get(base, params={'status': 'in'}))) == ['Анна', 'Белла', 'Вера']
    assert names(ok(c.get(base, params={'status': 'outside'}))) == ['Галина']
    assert names(ok(c.get(base, params={'status': 'out'}))) == ['Дина']
    gold_in = ok(c.get(base, params={'status': 'in', 'league': 'gold'}))
    assert names(gold_in) == ['Анна', 'Белла'] and gold_in['shown'] == 2
    # счётчики у кнопок — с учётом другого фильтра и поиска
    assert gold_in['groups'] == {'in': 2, 'outside': 0, 'out': 0} and gold_in['leagues'] == {'gold': 2, 'silver': 1}
    found = ok(c.get(base, params={'q': 'белла', 'league': 'gold'}))
    assert names(found) == ['Белла'] and found['groups']['in'] == 1 and found['league_total'] == 1
    assert names(ok(c.get(base, params={'league': 'none', 'status': 'outside'}))) == ['Галина']
    assert c.get(base, params={'status': 'nobody'}).status_code == 422


def test_people_list_filters(app, seed, clock):
    c, game, eps, _ = game_with_people(app, seed)
    names = lambda d: sorted((p['name'] or '').split()[0] for p in d['people'])
    d = ok(c.get('/api/org/people'))
    assert d['game']['id'] == str(game['event']) and d['counts']['all'] == 6   # пять участниц и организатор
    assert d['league_counts'] == {'gold': 2, 'silver': 1, 'bronze': 0, 'none': 2} and d['status_counts'] == {'in': 3, 'outside': 1, 'out': 1}
    anna = next(p for p in d['people'] if p['name'].startswith('Анна'))
    assert anna['game'] == {'league': 'gold', 'mode': 'in'}
    assert next(p for p in d['people'] if p['email'] == 'org@example.com')['game'] is None
    gold = ok(c.get('/api/org/people', params={'league': 'gold'}))
    assert names(gold) == ['Анна', 'Белла'] and gold['counts']['all'] == 2
    assert gold['status_counts'] == {'in': 2, 'outside': 0, 'out': 0}
    both = ok(c.get('/api/org/people', params={'league': 'none', 'status': 'out'}))
    assert names(both) == ['Дина'] and both['counts']['all'] == 1
    assert names(ok(c.get('/api/org/people', params={'status': 'in', 'q': 'вера'}))) == ['Вера']
    paged = ok(c.get('/api/org/people', params={'status': 'in', 'limit': 2}))
    assert len(paged['people']) == 2 and paged['counts']['all'] == 3
    assert ok(c.get('/api/org/people', params={'status': 'in', 'kind': 'staff'}))['people'] == []
