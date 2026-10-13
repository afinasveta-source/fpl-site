"""Игра 01 из бота в кабинет (решения 13.10): перенос таблицы туров 1–2, заявки на вход по общей ссылке, продолжение с 3 тура.
Таблица — выдуманная, в формате настоящей (ID SaleBot; ФИО; лига А/Б; баллы; рейтинги; проход; TOP WORK)."""
from fastapi.testclient import TestClient

from conftest import PASSWORD
from game_helpers import ORIGIN, add_docs, h
from test_org import ok, org

HEAD = ('ID участника;Имя;Лига;Оценка тура 1 (исходная 40–100);Рейтинг после тура 1 (первоначальный);'
        'Рейтинг после тура 1 (пересчитанный, использован в туре 2);Оценка работы тура 2 (объявленная);Прошёл в тур 3;'
        'Рейтинг после тура 2;Изменение за тур 2;TOP WORK тура 2;Примечание')
ROWS = [
    '1000000001;Иванова Анна Петровна;А;90;599;607.;96.07;Да;711.;+104.;Да;',
    '1000000002;Петрова Мария Ивановна;А;75;523;530.;60.50;Да;540.;+10.;Нет;',
    '1000000003;Сидорова Ольга;А;50;402;410.;20.00;Нет;380.;-30.;Нет;',
    '1000000004;Кузнецова Елена Сергеевна;Б;70;492;495.;88.00;Да;560.;+65.;Да;',
    '1000000005;Смирнова Дарья;Б;40;361;370.;;Нет;;;Нет;Нет конкурсного результата тура 2',
]


def table(rows=ROWS):
    return '﻿' + HEAD + '\n' + '\n'.join(rows) + '\n'


def do_import(c, text=None):
    text = text or table()
    p = ok(c.post('/api/org/import/game01/preview', headers=ORIGIN, json={'csv': text}))
    return p, ok(c.post('/api/org/import/game01/apply', headers=ORIGIN, json={'csv': text, 'sha256': p['sha256']}))


def test_preview_and_import_are_idempotent(app, seed, clock):
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    bad = table(ROWS + ['abc;Без ID;А;50;400;400;;Нет;;;Нет;', '1000000006;Икс Игрек;В;50;400;400;;Нет;;;Нет;'])
    p = ok(c.post('/api/org/import/game01/preview', headers=ORIGIN, json={'csv': bad}))
    assert p['error_count'] == 2 and {e['problem'] for e in p['errors']} == {'bad_id', 'bad_league'}
    assert c.post('/api/org/import/game01/apply', headers=ORIGIN, json={'csv': bad, 'sha256': p['sha256']}).json()['detail'] == 'table_has_errors'
    assert c.post('/api/org/import/game01/apply', headers=ORIGIN, json={'csv': table()}).json()['detail'] == 'preview_first'
    p, res = do_import(c)
    assert p['leagues']['gold'] == {'total': 3, 'in_competition': 2, 'judged_out': 1, 'no_round_2': 0, 'top_work_2': 1}
    assert p['leagues']['silver']['no_round_2'] == 1 and any(w['problem'] == 'no_top_work_1' for w in p['warnings'])
    eid = res['event_id']
    _, again = do_import(c)                                         # повтор — ничего не дублирует
    assert again['event_id'] == eid
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users WHERE account_status='imported'").fetchone()['n'] == 5
        assert conn.execute('SELECT count(*) AS n FROM event_participants WHERE event_id=%s', (eid,)).fetchone()['n'] == 5
        assert conn.execute("SELECT count(*) AS n FROM round_results WHERE event_id=%s AND is_current", (eid,)).fetchone()['n'] == 9
        assert conn.execute("SELECT count(*) AS n FROM rating_transactions WHERE event_id=%s AND status='active'", (eid,)).fetchone()['n'] == 9
        rounds = {r['round_no']: r for r in conn.execute('SELECT * FROM rounds WHERE event_id=%s', (eid,))}
        assert [rounds[i]['status'] for i in range(1, 6)] == ['published', 'published', 'draft', 'draft', 'draft']
        assert rounds[3]['settings']['relay'] == {'from': 'gold', 'to': 'silver', 'sources': 'top', 'top_n': 10} and rounds[4]['settings']['relay']['to'] == 'gold'
        st = {r['full_name']: r for r in conn.execute('''SELECT u.full_name, p.competition_status, p.elimination_reason, p.entry_league,
s.current_rating, s.calibration_rounds_completed FROM event_participants p JOIN users u ON u.id=p.user_id
LEFT JOIN participant_stats s ON s.user_id=u.id WHERE p.event_id=%s''', (eid,))}
    assert st['Иванова Анна Петровна']['competition_status'] == 'active' and float(st['Иванова Анна Петровна']['current_rating']) == 711
    assert st['Сидорова Ольга']['elimination_reason'] == 'judged_out' and st['Смирнова Дарья']['elimination_reason'] == 'late'
    assert st['Смирнова Дарья']['calibration_rounds_completed'] == 1 and float(st['Смирнова Дарья']['current_rating']) == 370
    assert ok(c.get('/api/org/home'))['counts']['moved_games'] == 1


def claim(app, **extra):
    body = {'full_name': 'Иванова Анна', 'email': 'anna@example.com', 'password': PASSWORD, 'country_code': 'ru', 'city': 'Казань',
            'contact': '@anna', 'accept_rules': True, 'accept_publication': True, 'accept_personal_data': True, 'confirm_adult': True} | extra
    return TestClient(app).post('/api/public/claims', headers=ORIGIN, json=body)


def test_claim_approve_and_continue_from_round_3(app, seed, clock):
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    assert not ok(TestClient(app).get('/api/public/claims/config'))['open']   # Игры из бота ещё нет
    assert claim(app).json()['detail'] == 'claims_closed'
    c = org(app, seed)
    _, res = do_import(c)
    eid = res['event_id']
    cfg = ok(TestClient(app).get('/api/public/claims/config'))
    assert cfg['open'] and cfg['game'] == 'Игра 01' and cfg['documents']['rules']['body']
    assert claim(app, confirm_adult=False).json()['detail'] == 'adult_required'
    assert claim(app, accept_rules=False).json()['detail'] == 'consents_required'
    no = ok(claim(app), 201)['claim_no']
    assert claim(app).json()['detail'] == 'claim_pending'
    seed('taken@example.com', ('participant',))
    assert claim(app, email='taken@example.com').json()['detail'] == 'email_taken'
    # до подтверждения войти нельзя
    anon = TestClient(app)
    assert anon.post('/web-auth/login', headers=ORIGIN, json={'email': 'anna@example.com', 'password': PASSWORD}).status_code == 401
    lst = ok(c.get('/api/org/claims'))
    item = lst['items'][0]
    assert item['no'] == no and item['suggestions'][0]['full_name'] == 'Иванова Анна Петровна' and lst['free'] == 5
    assert ok(c.get('/api/org/home'))['counts']['claims'] == 1
    found = ok(c.get('/api/org/claims/people?q=1000000002'))['items']
    assert [p['full_name'] for p in found] == ['Петрова Мария Ивановна']
    uid = item['suggestions'][0]['user_id']
    ok(c.post(f'/api/org/claims/{no}/approve', headers=ORIGIN, json={'user_id': uid}))
    assert c.post(f'/api/org/claims/{no}/approve', headers=ORIGIN, json={'user_id': uid}).json()['detail'] == 'claim_decided'
    no2 = ok(claim(app, email='anna2@example.com'), 201)['claim_no']
    assert c.post(f'/api/org/claims/{no2}/approve', headers=ORIGIN, json={'user_id': uid}).json()['detail'] == 'person_has_login'
    ok(c.post(f'/api/org/claims/{no2}/reject', headers=ORIGIN, json={'note': 'Дубль'}))
    # вошла — видит Игру 01 и итоги туров 1–2
    p = TestClient(app)
    me = ok(p.post('/web-auth/login', headers=ORIGIN, json={'email': 'anna@example.com', 'password': PASSWORD}))
    assert me['email'] == 'anna@example.com'
    g = ok(p.get(f'/api/games/{eid}'))
    assert g['me']['mode'] == 'in' and g['me']['league'] == 'gold'
    with app.state.db.transaction() as conn:
        u = conn.execute('SELECT * FROM users WHERE id=%s', (uid,)).fetchone()
        kinds = {r['consent_type'] for r in conn.execute("SELECT consent_type FROM consents WHERE user_id=%s AND status='accepted'", (uid,))}
        stored = conn.execute('SELECT password_hash FROM account_claims WHERE claim_no=%s', (no,)).fetchone()['password_hash']
    assert u['city'] == 'Казань' and u['country_code'] == 'RU' and u['display_name'] == 'Анна Иванова' and u['full_name'] == 'Иванова Анна Петровна'
    assert kinds == {'rules', 'publication', 'personal_data'} and stored == '-'       # пароль из заявки не хранится после решения


def test_import_over_active_game_without_rules_and_lock_after_cabinet_rating(app, seed, clock):
    """Игра 01 уже есть (как после переноса из SaleBot: идёт, без Правил, туры 3–5 без заданий) — перенос не падает,
    туры 3–5 становятся черновиками кабинета с эстафетой; после рейтинга кабинета повтор переноса запрещён."""
    clock.set(h())
    with app.state.db.transaction() as conn:
        s = conn.execute("INSERT INTO seasons(name,status,season_no) VALUES ('Сезон 1','active',1) RETURNING id").fetchone()['id']
        e = conn.execute('''INSERT INTO events(season_id,event_type,status,title,starts_at,ends_at,game_no)
VALUES (%s,'ranked_game','active','Игра 01',%s,%s,1) RETURNING id''', (s, h(days=-14), h(days=27))).fetchone()['id']
        for no in (3, 4, 5):
            conn.execute("INSERT INTO rounds(event_id,round_no,title,status) VALUES (%s,%s,%s,'scheduled')", (e, no, f'Тур {no}'))
        add_docs(conn)
    c = org(app, seed)
    p, res = do_import(c)
    assert res['event_id'] == str(e)
    with app.state.db.transaction() as conn:
        rounds = {r['round_no']: r for r in conn.execute('SELECT * FROM rounds WHERE event_id=%s', (e,))}
        assert rounds[3]['status'] == 'draft' and rounds[3]['settings']['relay']['from'] == 'gold'
        assert conn.execute('SELECT count(*) AS n FROM assignments WHERE round_id=%s', (rounds[3]['id'],)).fetchone()['n'] == 1
        conn.execute('''INSERT INTO rating_transactions(user_id,event_id,round_id,method,formula_version,rating_after,idempotency_key)
SELECT p.user_id, p.event_id, %s, 'pairwise_elo', 'x', 500, 'elo:test:' || p.user_id FROM event_participants p WHERE p.event_id=%s LIMIT 1''',
                     (rounds[3]['id'], e))
    p2 = ok(c.post('/api/org/import/game01/preview', headers=ORIGIN, json={'csv': table()}))
    assert p2['event']['locked']
    assert c.post('/api/org/import/game01/apply', headers=ORIGIN, json={'csv': table(), 'sha256': p2['sha256']}).json()['detail'] == 'cabinet_rating_started'


def test_undo_wrong_table_then_import_right_one(app, seed, clock):
    """13.10: перенесли тестовую таблицу вместо настоящей — «Отменить перенос» удаляет всё перенесённое, пока Игра не началась."""
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    assert not ok(c.get('/api/org/import/game01'))['moved']
    _, res = do_import(c)
    eid = res['event_id']
    st = ok(c.get('/api/org/import/game01'))
    assert st['moved'] and st['participants'] == 5 and st['undo_blockers'] == [] and len(st['sample']) == 5
    assert c.post('/api/org/import/game01/undo', headers=ORIGIN, json={'confirm': 'да'}).json()['detail'] == 'confirm_word'
    d = ok(c.post('/api/org/import/game01/undo', headers=ORIGIN, json={'confirm': 'отменить'}))
    assert d['participants'] == 5 and d['users'] == 5
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM event_participants WHERE event_id=%s', (eid,)).fetchone()['n'] == 0
        assert conn.execute("SELECT count(*) AS n FROM users WHERE account_status='imported'").fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM rating_transactions WHERE event_id=%s', (eid,)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM round_results WHERE event_id=%s', (eid,)).fetchone()['n'] == 0
        assert conn.execute("SELECT count(*) AS n FROM import_row_map WHERE source_table IN ('salebot_client','salebot_participant')").fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM rounds WHERE event_id=%s', (eid,)).fetchone()['n'] == 5
    assert not ok(TestClient(app).get('/api/public/claims/config'))['open']          # заявки закрыты до нового переноса
    assert not ok(c.get('/api/org/import/game01'))['moved']
    # правильная таблица — другие люди
    right = [r.replace('100000000', '200000000').replace('Иванова', 'Орлова') for r in ROWS[:4]]
    p = ok(c.post('/api/org/import/game01/preview', headers=ORIGIN, json={'csv': table(right)}))
    assert p['sample'][0].startswith('Орлова')
    _, res2 = do_import(c, table(right))
    assert res2['event_id'] == eid
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM event_participants WHERE event_id=%s', (eid,)).fetchone()['n'] == 4
        r3 = conn.execute('SELECT count(*) AS n FROM assignments a JOIN rounds r ON r.id=a.round_id WHERE r.event_id=%s AND r.round_no=3', (eid,)).fetchone()['n']
    assert r3 == 1
    # вошла хоть одна — отменить уже нельзя
    no = ok(claim(app, full_name='Орлова Анна Петровна'), 201)['claim_no']
    uid = ok(c.get('/api/org/claims'))['items'][0]['suggestions'][0]['user_id']
    ok(c.post(f'/api/org/claims/{no}/approve', headers=ORIGIN, json={'user_id': uid}))
    assert ok(c.get('/api/org/import/game01'))['undo_blockers'] == ['participants_logged_in']
    assert c.post('/api/org/import/game01/undo', headers=ORIGIN, json={'confirm': 'ОТМЕНИТЬ'}).json()['detail'] == 'participants_logged_in'
