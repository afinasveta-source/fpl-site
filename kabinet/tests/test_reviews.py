"""Платный аудиоразбор от судьи (решения 13.10): заказ с сайта после конца Игры, оплата по счёту, судья записывает
разбор в кабинете и отправляет участнице."""
import shutil
from datetime import timedelta

from fastapi.testclient import TestClient

from game_helpers import ORIGIN, add_docs, build_game, h, jpeg, login, register, send_work
from test_org import ok, org

AUDIO = b'ID3' + b'\x00' * 4000   # заглушка mp3 (ffmpeg её не переведёт — сохраняется как есть)


def finished_game(app, ended=h(days=-1)):
    with app.state.db.transaction() as conn:
        g = build_game(conn, title='Игра 01')
        conn.execute("UPDATE rounds SET status='published' WHERE id=%s", (g['rounds'][0],))
        conn.execute("UPDATE events SET status='finished', ends_at=%s, completion_deadline=%s WHERE id=%s", (ended, ended, g['event']))
    return g


def site(app):
    return TestClient(app, headers=ORIGIN)


def place(app, no, scope='all', contact='maria@example.com'):
    return ok(site(app).post('/api/public/review-order', json={'name': 'Мария', 'contact': contact, 'scope': scope,
                                                               'round_no': 1 if scope == 'one' else None, 'accept_terms': True}), 201)


def test_offer_opens_after_game_end_for_window(app, seed, clock):
    s = site(app)
    clock.set(h())
    with app.state.db.transaction() as conn:
        g = build_game(conn, title='Игра 01')                       # идёт — заказать нельзя
        conn.execute("UPDATE rounds SET status='published' WHERE id=%s", (g['rounds'][0],))
    assert ok(s.get('/api/public/review-offer'))['enabled'] is False
    clock.set(h(days=21))                                            # Игра кончилась (конец +20 дней)
    o = ok(s.get('/api/public/review-offer'))
    assert o['enabled'] and o['game'] == 'Игра 01' and [r['no'] for r in o['rounds']] == [1] and 'game_id' not in o
    assert o['price_one'] == 300 and o['price_all'] == 700 and o['reviewer'] == 'Милена' and o['until']
    clock.set(h(days=20 + 31))                                       # окно 30 дней прошло
    assert ok(s.get('/api/public/review-offer'))['enabled'] is False


def test_order_validation(app, seed, clock):
    clock.set(h())
    finished_game(app)
    s = site(app)
    base = {'name': 'Анна', 'contact': '@anna', 'accept_terms': True}
    assert s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 2}).json()['detail'] == 'round_not_published'
    assert s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 1, 'accept_terms': False}).json()['detail'] == 'terms_required'
    assert s.post('/api/public/review-order', json=base | {'scope': 'all', 'name': ' '}).status_code == 422
    assert TestClient(app).post('/api/public/review-order', json=base | {'scope': 'all'}).status_code == 403   # чужой сайт
    assert ok(s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 1}), 201)['price'] == 300
    assert ok(s.post('/api/public/review-order', json=base | {'scope': 'all'}), 201)['price'] == 700
    assert ok(s.post('/api/public/review-order', json=base | {'scope': 'all', 'website': 'spam'}), 201)['order_no'] == 0
    c = org(app, seed)
    assert len(ok(c.get('/api/org/reviews'))['items']) == 2


def test_judge_records_in_cabinet_and_participant_listens(app, seed, clock):
    """Судья видит работы участницы этой Игры, записывает разбор и отправляет — он сразу у участницы."""
    with app.state.db.transaction() as conn:
        add_docs(conn)
        g = build_game(conn, title='Игра 01', rounds=2)
    p = login(app, seed, 'maria@example.com')
    ok(register(p, g['event']), 201)
    clock.set(h(minutes=5))
    send_work(p, g, 0)
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE rounds SET status='published' WHERE event_id=%s", (g['event'],))
        conn.execute("UPDATE events SET status='finished', ends_at=%s, completion_deadline=%s WHERE id=%s",
                     (h(days=1), h(days=1), g['event']))
    clock.set(h(days=2))
    no = place(app, 1)['order_no']
    c = org(app, seed)
    jd = login(app, seed, 'milena@example.com', roles=('judge',))
    other_judge = login(app, seed, 'judge2@example.com', roles=('judge',))
    with app.state.db.transaction() as conn:
        ids = {r['email']: str(r['id']) for r in conn.execute("SELECT id, email FROM users")}
    url = f'/api/org/reviews/{no}'
    assert c.patch(url, headers=ORIGIN, json={'reviewer_id': ids['maria@example.com']}).json()['detail'] == 'not_a_judge'
    ok(c.patch(url, headers=ORIGIN, json={'status': 'payment_sent'}))
    # судья пока не видит заказ: не оплачен
    assert ok(jd.get('/api/judging/reviews'))['items'] == []
    v = ok(c.patch(url, headers=ORIGIN, json={'status': 'paid', 'user_id': ids['maria@example.com'], 'reviewer_id': ids['milena@example.com']}))
    assert v['judge']['email'] == 'milena@example.com'
    assert any('Разбор' in str(n) for n in ok(jd.get('/api/notifications'))['notifications'])        # судье — задание
    assert [x['no'] for x in ok(jd.get('/api/judging/reviews'))['items']] == [no]
    task = ok(jd.get(f'/api/judging/reviews/{no}'))
    assert task['name'] == 'Мария' and 'contact' not in task and len(task['works']) == 1 and task['works'][0]['photos']
    photo = task['works'][0]['photos'][0]['view_url'].replace(app.state.settings.root_path, '')
    assert jd.get(photo).status_code == 200                       # судья разбора видит фото участницы
    assert other_judge.get(photo).status_code == 404 and other_judge.get(f'/api/judging/reviews/{no}').status_code == 404
    assert p.get(f'/api/judging/reviews/{no}').status_code == 403
    assert jd.post(f'/api/judging/reviews/{no}/send', headers=ORIGIN, json={}).json()['detail'] == 'no_review'
    assert jd.post(f'/api/judging/reviews/{no}/audio', headers={**ORIGIN, 'Content-Type': 'text/plain'}, content=b'x').status_code == 415
    t = ok(jd.post(f'/api/judging/reviews/{no}/audio', headers={**ORIGIN, 'Content-Type': 'audio/mpeg'}, content=AUDIO))
    assert t['has_audio'] and jd.get(f'/api/judging/reviews/{no}/audio').content == AUDIO   # прослушать перед отправкой
    assert p.get(f'/api/reviews/{no}/audio').status_code == 404                              # до отправки участница не слышит
    t = ok(jd.post(f'/api/judging/reviews/{no}/send', headers=ORIGIN, json={'text': 'Контур ровный.'}))
    assert t['status'] == 'done'
    mine = ok(p.get('/api/reviews'))['items'][0]
    assert mine['audio'] and mine['text'] == 'Контур ровный.'
    assert p.get(f'/api/reviews/{no}/audio').content == AUDIO
    assert p.get(f'/api/reviews/{no}/audio', headers={'Range': 'bytes=0-9'}).status_code == 206
    assert any('Разбор' in str(n) for n in ok(p.get('/api/notifications'))['notifications'])
    # после отправки перезаписать нельзя
    assert jd.post(f'/api/judging/reviews/{no}/audio', headers={**ORIGIN, 'Content-Type': 'audio/mpeg'}, content=AUDIO).status_code == 409


def test_org_upload_and_ffmpeg_m4a(app, seed, clock):
    """Организатор может загрузить файл сам; на сервере с ffmpeg запись переводится в m4a (играет на iPhone)."""
    clock.set(h())
    finished_game(app)
    no = place(app, 1)['order_no']
    c = org(app, seed)
    if shutil.which('ffmpeg'):
        import subprocess, tempfile, os
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'a.webm')
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:a', 'libopus', src], check=True)
            data = open(src, 'rb').read()
        v = ok(c.post(f'/api/org/reviews/{no}/audio', headers={**ORIGIN, 'Content-Type': 'audio/webm'}, content=data))
        a = c.get(f'/api/org/reviews/{no}/audio')
        assert a.headers['content-type'].startswith('audio/mp4') and a.content[4:8] == b'ftyp'
    else:
        ok(c.post(f'/api/org/reviews/{no}/audio', headers={**ORIGIN, 'Content-Type': 'audio/mpeg'}, content=AUDIO))
