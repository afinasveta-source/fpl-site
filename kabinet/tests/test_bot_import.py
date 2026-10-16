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


def test_outside_newcomer_can_upload_rounds_1_2(app, seed, clock):
    """14.10: кого нет в таблице (рисовала вне конкурса) — «добавить вне конкурса» из заявки; фото работ туров 1–2
    загружают в кабинете все, у кого фото нет (с оценкой из бота тоже — решение 14.10, позже); на зачёт, диплом и «опоздавших» задания туров 1–2 не влияют."""
    from kabinet.participation import game as G
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    _, res = do_import(c)
    eid = res['event_id']
    with app.state.db.transaction() as conn:
        tasks = {r['round_no']: r for r in conn.execute('''SELECT a.*, r.round_no FROM assignments a JOIN rounds r ON r.id=a.round_id
WHERE r.event_id=%s''', (eid,))}
        assert not tasks[1]['required_for_competition'] and not tasks[1]['required_for_diploma'] and not tasks[2]['required_for_game_count']
        assert G.sync_event(conn, eid, h()) == 0            # задания туров 1–2 никого не делают «опоздавшим»
    no = ok(claim(app, full_name='Новикова Мария', email='maria@example.com'), 201)['claim_no']
    assert ok(c.get('/api/org/claims'))['items'][0]['suggestions'] == []
    ok(c.post(f'/api/org/claims/{no}/add-outside', headers=ORIGIN, json={'league': 'silver'}))
    assert c.post(f'/api/org/claims/{no}/add-outside', headers=ORIGIN, json={}).json()['detail'] == 'claim_decided'
    p = TestClient(app)
    ok(p.post('/web-auth/login', headers=ORIGIN, json={'email': 'maria@example.com', 'password': PASSWORD}))
    g = ok(p.get(f'/api/games/{eid}'))
    assert g['me']['mode'] == 'outside' and g['me']['league'] == 'silver'
    t1 = ok(p.get(f"/api/games/{eid}/tasks/{tasks[1]['id']}"))
    assert t1['window']['open'], t1['window']
    # перенесённая участница с оценкой тура 1 из бота: фото работы не сохранилось — может загрузить его в архив (решение 14.10)
    no2 = ok(claim(app, email='anna@example.com'), 201)['claim_no']
    uid = ok(c.get('/api/org/claims'))['items'][0]['suggestions'][0]['user_id']
    ok(c.post(f'/api/org/claims/{no2}/approve', headers=ORIGIN, json={'user_id': uid}))
    a = TestClient(app)
    ok(a.post('/web-auth/login', headers=ORIGIN, json={'email': 'anna@example.com', 'password': PASSWORD}))
    w = ok(a.get(f"/api/games/{eid}/tasks/{tasks[1]['id']}"))['window']
    assert w['open'] and w['source'] == 'completion'
    assert ok(c.get('/api/org/import/game01'))['undo_blockers'] == ['participants_logged_in']


def test_self_registered_player_is_linked_to_bot_record(app, seed, clock):
    """14.10: участница из бота завела кабинет через «Впервые в лиге?» — задвоение. Организатор соединяет вход
    с записью из бота; новые такие регистрации отправляются на заявку."""
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    _, res = do_import(c)
    eid = res['event_id']
    # до переноса так зарегистрироваться можно было: заведём аккаунт напрямую, как это сделал сайт
    s = TestClient(app)
    r = s.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'elena@example.com', 'password': PASSWORD,
                                                           'full_name': 'Кузнецова Елена Сергеевна'})
    assert r.status_code == 409 and r.json()['detail'] == 'game01_player'     # теперь — на заявку
    r = s.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'elena@example.com', 'password': PASSWORD,
                                                           'full_name': 'Елена К.'})
    assert r.status_code == 201, r.text                                          # имя не узнали — завела (как было на сервере)
    new = TestClient(app)
    ok(new.post('/web-auth/register', headers=ORIGIN, json={'accept_personal_data': True, 'confirm_adult': True, 'email': 'newbie@example.com', 'password': PASSWORD,
                                                            'full_name': 'Новенькая Вера Павловна'}), 201)
    acc = ok(c.get('/api/org/claims/accounts'))['items']
    assert {a['email'] for a in acc} == {'elena@example.com', 'newbie@example.com'}
    elena = next(a for a in acc if a['email'] == 'elena@example.com')
    with app.state.db.transaction() as conn:
        bot = conn.execute("SELECT id FROM users WHERE full_name='Кузнецова Елена Сергеевна'").fetchone()['id']
        conn.execute("INSERT INTO consents(user_id,consent_type,accepted,status,channel,idempotency_key) VALUES (%s,'marketing',true,'accepted','web','t-mk')",
                     (elena['user_id'],))
        # как на сервере: у самостоятельного аккаунта была включена публичность (из-за неё падало соединение 14.10)
        conn.execute('UPDATE users SET public_works=true, public_social=true, public_rating=true, public_city=true WHERE id=%s',
                     (elena['user_id'],))
    # 14.10: до соединения она написала в поддержку — обращение переходит на запись из бота вместе со входом
    ok(s.post('/api/support', headers=ORIGIN, json={'subject': 'Не вижу туров', 'body': 'Где мои баллы?'}), 201)
    ok(c.post(f"/api/org/claims/accounts/{elena['user_id']}/link", headers=ORIGIN, json={'user_id': str(bot)}))
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM support_threads WHERE user_id=%s', (bot,)).fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM support_threads WHERE user_id=%s', (elena['user_id'],)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM support_messages WHERE author_user_id=%s', (bot,)).fetchone()['n'] == 1
    assert c.post(f"/api/org/claims/accounts/{elena['user_id']}/link", headers=ORIGIN,
                  json={'user_id': str(bot)}).json()['detail'] == 'account_not_linkable'
    # старая сессия закрыта, вход тем же email и паролем — уже на записи из бота с итогами туров 1–2
    assert s.get(f'/api/games/{eid}').status_code == 401
    e = TestClient(app)
    ok(e.post('/web-auth/login', headers=ORIGIN, json={'email': 'elena@example.com', 'password': PASSWORD}))
    g = ok(e.get(f'/api/games/{eid}'))
    assert g['me']['league'] == 'silver'
    assert [t['subject'] for t in ok(e.get('/api/support'))['threads']] == ['Не вижу туров']
    # согласий из кабинета у неё нет (в боте давала) — сдавать нельзя, пока не примет документы одним экраном
    assert not g['rules_ok']
    miss = ok(e.get('/api/consents/missing'))['missing']
    assert {d['doc_type'] for d in miss} == {'rules', 'publication'}      # обработку данных приняла при регистрации
    assert e.post('/api/consents/missing', headers=ORIGIN, json={'accept': ['rules']}).json()['detail'] == 'consents_required'
    assert e.post('/api/consents/missing', headers=ORIGIN,
                  json={'accept': ['rules', 'publication']}).json()['detail'] == 'adult_required'
    ok(e.post('/api/consents/missing', headers=ORIGIN, json={'accept': ['rules', 'publication'], 'confirm_adult': True}))
    assert ok(e.get(f'/api/games/{eid}'))['rules_ok'] and ok(e.get('/api/consents/missing'))['missing'] == []
    with app.state.db.transaction() as conn:
        u = conn.execute('SELECT * FROM users WHERE id=%s', (bot,)).fetchone()
        assert u['account_status'] == 'active' and u['email'] == 'elena@example.com'
        old = conn.execute('SELECT * FROM users WHERE id=%s', (elena['user_id'],)).fetchone()
        assert old['account_status'] == 'deleted' and old['email'] is None and old['deleted_at'] is not None
        assert conn.execute("SELECT count(*) AS n FROM consents WHERE user_id=%s AND consent_type='marketing'", (bot,)).fetchone()['n'] == 1
    # организатор видит итоги туров 1–2 из бота и в карточке, и в списке участниц (14.10)
    ep = ok(c.get(f'/api/org/events/{eid}/participants?q=' + 'Кузнецова'))['participants'][0]
    assert [x['score'] for x in ep['rounds'][:2]] == [70.0, 88.0] and ep['rounds'][0]['from_bot']
    card = ok(c.get(f"/api/org/participants/{ep['id']}"))
    assert {k: card['rounds'][1]['result'][k] for k in ('score', 'advanced')} == {'score': 88.0, 'advanced': True} and card['rounds'][1]['from_bot']
    left = ok(c.get('/api/org/claims/accounts'))['items']
    assert [a['email'] for a in left] == ['newbie@example.com']
    # новичка с запись из бота, у которой уже есть вход, не соединить
    assert c.post(f"/api/org/claims/accounts/{left[0]['user_id']}/link", headers=ORIGIN,
                  json={'user_id': str(bot)}).json()['detail'] == 'person_has_login'


def test_two_claims_same_person_merge_login_into_bot_record(app, seed, clock):
    """14.10 (Антонова): две заявки с разными email — одну соединили с записью из бота, вторую добавили вне конкурса,
    человек входит во вторую. Вход переносится на запись из бота, лишняя запись закрывается и уходит из Игры."""
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    _, res = do_import(c)
    eid = res['event_id']
    no1 = ok(claim(app, full_name='Петрова Мария', email='typo@example.com'), 201)['claim_no']
    bot = ok(c.get('/api/org/claims'))['items'][0]['suggestions'][0]['user_id']
    ok(c.post(f'/api/org/claims/{no1}/approve', headers=ORIGIN, json={'user_id': bot}))
    no2 = ok(claim(app, full_name='Петрова Мария', email='real@example.com'), 201)['claim_no']
    assert ok(c.get('/api/org/claims'))['items'][0]['same_name'] == [{'no': no1, 'email': 'typo@example.com', 'note': None}]
    ok(c.post(f'/api/org/claims/{no2}/add-outside', headers=ORIGIN, json={}))
    p = TestClient(app)
    ok(p.post('/web-auth/login', headers=ORIGIN, json={'email': 'real@example.com', 'password': PASSWORD}))
    with app.state.db.transaction() as conn:
        dup = str(conn.execute("SELECT id FROM users WHERE email='real@example.com'").fetchone()['id'])
        conn.execute('UPDATE users SET public_works=true, public_social=true WHERE id=%s', (dup,))
    # в основную запись уже входили бы — нельзя; сначала проверим запреты
    assert c.post('/api/org/claims/merge', headers=ORIGIN, json={'from_user_id': dup, 'into_user_id': dup}).json()['detail'] == 'same_person'
    ok(c.post('/api/org/claims/merge', headers=ORIGIN, json={'from_user_id': dup, 'into_user_id': bot}))
    assert p.get(f'/api/games/{eid}').status_code == 401
    q = TestClient(app)
    ok(q.post('/web-auth/login', headers=ORIGIN, json={'email': 'real@example.com', 'password': PASSWORD}))
    g = ok(q.get(f'/api/games/{eid}'))
    assert g['me']['mode'] == 'in' and g['me']['league'] == 'gold'
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM event_participants WHERE user_id=%s', (dup,)).fetchone()['n'] == 0
        u = conn.execute('SELECT * FROM users WHERE id=%s', (dup,)).fetchone()
        assert u['account_status'] == 'deleted' and u['email'] is None
    # теперь в основную входили — второй перенос в неё запрещён
    other = ok(claim(app, full_name='Сидорова Ольга', email='olga@example.com'), 201)['claim_no']
    ok(c.post(f'/api/org/claims/{other}/add-outside', headers=ORIGIN, json={}))
    with app.state.db.transaction() as conn:
        olga = str(conn.execute("SELECT id FROM users WHERE email='olga@example.com'").fetchone()['id'])
    assert c.post('/api/org/claims/merge', headers=ORIGIN,
                  json={'from_user_id': olga, 'into_user_id': bot}).json()['detail'] == 'merge_into_logged_in'


def test_org_marks_top_work_of_round_1_and_reimport_keeps_it(app, seed, clock):
    """16.10: в таблице не было TOP WORK тура 1 — организатор отмечает в карточке; очки и галерея берут отметку,
    повторный перенос таблицы её не затирает."""
    clock.set(h())
    with app.state.db.transaction() as conn:
        add_docs(conn)
    c = org(app, seed)
    _, res = do_import(c)
    eid = res['event_id']
    with app.state.db.transaction() as conn:
        ep = conn.execute('''SELECT p.id FROM event_participants p JOIN users u ON u.id=p.user_id
WHERE p.event_id=%s AND u.full_name=%s''', (eid, 'Петрова Мария Ивановна')).fetchone()['id']
        r1 = conn.execute('SELECT id FROM rounds WHERE event_id=%s AND round_no=1', (eid,)).fetchone()['id']
        r3 = conn.execute('SELECT id FROM rounds WHERE event_id=%s AND round_no=3', (eid,)).fetchone()['id']
    card = ok(c.get(f'/api/org/participants/{ep}'))
    row = next(r for r in card['rounds'] if r['round_no'] == 1)
    assert row['can_top_work'] and not row['result']['top_work']
    url = f'/api/org/participants/{ep}/rounds/{r1}/top_work'
    assert c.post(url, headers=ORIGIN, json={'top_work': True, 'reason': '  '}).json()['detail'] == 'reason_required'
    assert c.post(f'/api/org/participants/{ep}/rounds/{r3}/top_work', headers=ORIGIN,
                  json={'top_work': True, 'reason': 'x'}).status_code == 404       # у тура 3 итога нет
    d = ok(c.post(url, headers=ORIGIN, json={'top_work': True, 'reason': 'TOP WORK тура 1 по судейству в боте'}))
    assert next(r for r in d['rounds'] if r['round_no'] == 1)['result']['top_work']
    assert d['log'][0]['action'] == 'org_top_work'
    ok(c.post(url, headers=ORIGIN, json={'top_work': True, 'reason': 'повтор'}))          # повтор — без второй записи
    rows = {r['name']: r for r in ok(c.get(f'/api/org/events/{eid}/results'))['rows']}
    assert rows['Петрова Мария Ивановна']['top_works'] == 1 and rows['Петрова Мария Ивановна']['points']['top_work'] == 1
    do_import(c)                                                                         # повторный перенос не затирает
    with app.state.db.transaction() as conn:
        assert conn.execute('''SELECT top_work FROM round_results WHERE round_id=%s AND event_participant_id=%s AND is_current''',
                            (r1, ep)).fetchone()['top_work']
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE entity_id=%s AND action='org_top_work'", (ep,)).fetchone()['n'] == 1
    d = ok(c.post(url, headers=ORIGIN, json={'top_work': False, 'reason': 'ошибка'}))
    assert not next(r for r in d['rounds'] if r['round_no'] == 1)['result']['top_work']
