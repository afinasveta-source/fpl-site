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


def test_rating_for_organizer(app, seed, clock):
    """FPL Rating у организатора (17.10): колонка и сортировка в списке участниц, рейтинг и изменения за туры в карточке,
    столбец в итогах Игры. TOP WORK в списке и карточке — с лигой работы в туре."""
    c, game, eps, _ = game_with_people(app, seed)
    with app.state.db.transaction() as conn:
        uid = {k: conn.execute('SELECT user_id FROM event_participants WHERE id=%s', (v,)).fetchone()['user_id'] for k, v in eps.items()}
        for who, rating, cal, st in (('anna', 612, 2, 'calibrating'), ('bella', 540, 3, 'established'), ('vera', 700, 3, 'established')):
            conn.execute('''INSERT INTO participant_stats(user_id,current_rating,calibration_rounds_completed,rating_status)
VALUES (%s,%s,%s,%s)''', (uid[who], rating, cal, st))
        conn.execute("UPDATE rounds SET settings='{\"source\":\"bot\"}', status='published' WHERE id=%s", (game['rounds'][2],))
        for no, before, after in ((1, None, 590), (3, 590, 612)):
            conn.execute('''INSERT INTO rating_transactions(user_id,event_id,round_id,method,formula_version,rating_before,delta_after_cap,
rating_after,status,idempotency_key) VALUES (%s,%s,%s,%s,'test',%s,%s,%s,'active',%s)''',
                         (uid['anna'], game['event'], game['rounds'][no - 1], 'initial_seeding' if before is None else 'pairwise_elo',
                          before, None if before is None else after - before, after, f'test:{no}'))
        conn.execute('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,is_current,status,display_score,advanced,
league,top_work,top_work_rule_version,published_at) VALUES (%s,%s,%s,1,true,'published',91,true,'gold',true,'FPL_TOPWORK_V1',now())''', (game['event'], game['rounds'][2], eps['anna']))
    base = f"/api/org/events/{game['event']}/participants"
    first = lambda d: [p['name'].split()[0] for p in d['participants']]
    assert first(ok(c.get(base, params={'sort': 'rating_desc'}))) == ['Вера', 'Анна', 'Белла', 'Галина', 'Дина']
    asc = ok(c.get(base, params={'sort': 'rating_asc', 'status': 'in'}))
    assert first(asc) == ['Белла', 'Анна', 'Вера']   # фильтр сохраняется; без рейтинга — в конце
    anna = next(p for p in asc['participants'] if p['name'].startswith('Анна'))
    assert (anna['rating'], anna['rating_status'], anna['calibration']) == (612, 'calibrating', 2)
    cell = anna['rounds'][2]
    assert cell['top_work'] and cell['top_work_league'] == 'gold'
    assert c.get(base, params={'sort': 'name'}).status_code == 422
    card = ok(c.get(f"/api/org/participants/{eps['anna']}"))
    assert card['rating']['current'] == 612 and card['rating']['status'] == 'calibrating' and card['rating']['calibration'] == 2
    assert [(t['round_no'], t['before'], t['after'], t['delta']) for t in card['rating']['rounds']] == [(1, None, 590, None), (3, 590, 612, 22)]
    r3 = next(r for r in card['rounds'] if r['round_no'] == 3)
    assert r3['result']['top_work'] and r3['result']['league'] == 'gold'
    galina = ok(c.get(f"/api/org/participants/{eps['galina']}"))['rating']
    assert galina == {'current': None, 'status': 'unrated', 'calibration': 0, 'rounds': []}
    res = ok(c.get(f"/api/org/events/{game['event']}/results"))
    by = {r['name'].split()[0]: r.get('rating') for r in res['rows']}
    assert by['Анна'] == {'value': 612, 'status': 'calibrating', 'calibration': 2} and by['Галина'] is None


def test_site_rating_switch(app, seed, clock):
    """Рейтинг на сайте во время Игры: по умолчанию — на начало (Правила, п. 7.3); организатор может разрешить текущий."""
    c = org(app, seed)
    with app.state.db.transaction() as conn:
        game = build_game(conn)
    url = f"/api/org/events/{game['event']}"
    assert ok(c.get(url))['site_rating_live'] is False
    assert c.post(url + '/site-rating', json={'live': True}).status_code == 403   # только со страницы кабинета
    assert ok(c.post(url + '/site-rating', headers=ORIGIN, json={'live': True}))['site_rating_live'] is True
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT settings FROM events WHERE id=%s', (game['event'],)).fetchone()['settings']['site_rating_live'] is True
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE action='site_rating_live'").fetchone()['n'] == 1
    assert ok(c.post(url + '/site-rating', headers=ORIGIN, json={'live': False}))['site_rating_live'] is False
    other = ok(c.post('/api/org/events', headers=ORIGIN, json={'title': 'Челлендж', 'event_type': 'challenge'}), 201)
    assert c.post(f"/api/org/events/{other['id']}/site-rating", headers=ORIGIN, json={'live': True}).json()['detail'] == 'not_ranked'
    assert login(app, seed, 'p@example.com').post(url + '/site-rating', headers=ORIGIN, json={'live': True}).status_code == 403


def test_pulse_for_dashboard(app, seed, clock):
    """17.10: Обзор лиги — цифры за сутки и неделю и лента последних событий."""
    c, game, eps, people = game_with_people(app, seed)
    d = ok(c.get('/api/org/pulse'))
    assert d['numbers']['works_24h'] == 2 and d['numbers']['works_7d'] == 2
    assert d['numbers']['messengers']['people'] == 4 and d['numbers']['messengers']['any'] == 0
    works = [x for x in d['feed'] if x['kind'] == 'work']
    assert {x['name'] for x in works} == {'Анна Тестова', 'Вера Тестова'}
    assert all(x['href'].startswith('/org/participants/') for x in works) and d['judges'] == []
    assert login(app, seed, 'zoe@example.com').get('/api/org/pulse').status_code == 403
