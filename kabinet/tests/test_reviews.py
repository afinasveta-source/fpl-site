"""Платный аудиоразбор от судьи: заказ с сайта, оплата вручную, аудио в кабинете (решение 13.10)."""
from fastapi.testclient import TestClient

from game_helpers import ORIGIN, build_game, login
from test_org import ok, org

AUDIO = b'ID3' + b'\x00' * 4000   # заглушка mp3: кабинет аудио не разбирает, только хранит и отдаёт


def game_with_round_published(app):
    with app.state.db.transaction() as conn:
        g = build_game(conn, title='Игра 01')
        conn.execute("UPDATE rounds SET status='published' WHERE id=%s", (g['rounds'][0],))
    return g


def site(app):
    return TestClient(app, headers=ORIGIN)


def test_order_from_site_validation(app, seed, clock):
    s = site(app)
    assert ok(s.get('/api/public/review-offer'))['enabled'] is False          # Игры нет — заказать нельзя
    game_with_round_published(app)
    o = ok(s.get('/api/public/review-offer'))
    assert o['enabled'] and o['price_one'] == 300 and o['price_all'] == 700 and o['reviewer'] == 'Милена'
    assert [r['no'] for r in o['rounds']] == [1] and o['game'] == 'Игра 01'
    base = {'name': 'Анна', 'contact': '@anna', 'accept_terms': True}
    assert s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 2}).json()['detail'] == 'round_not_published'
    assert s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 1, 'accept_terms': False}).json()['detail'] == 'terms_required'
    assert s.post('/api/public/review-order', json=base | {'scope': 'all', 'name': ' '}).status_code == 422
    assert TestClient(app).post('/api/public/review-order', json=base | {'scope': 'all'}).status_code == 403   # чужой сайт
    one = ok(s.post('/api/public/review-order', json=base | {'scope': 'one', 'round_no': 1, 'comment': 'Про контур'}), 201)
    assert one['price'] == 300 and one['order_no'] > 0
    assert ok(s.post('/api/public/review-order', json=base | {'scope': 'all'}), 201)['price'] == 700
    bot = ok(s.post('/api/public/review-order', json=base | {'scope': 'all', 'website': 'spam'}), 201)
    assert bot['order_no'] == 0
    c = org(app, seed)
    items = ok(c.get('/api/org/reviews'))['items']
    assert len(items) == 2 and {i['scope'] for i in items} == {'one', 'all'}


def test_review_flow_payment_audio_and_access(app, seed, clock):
    game_with_round_published(app)
    s = site(app)
    no = ok(s.post('/api/public/review-order', json={'name': 'Мария', 'contact': 'maria@example.com', 'scope': 'all',
                                                    'accept_terms': True}), 201)['order_no']
    c = org(app, seed)
    p = login(app, seed, 'maria@example.com')
    other = login(app, seed, 'other@example.com')
    with app.state.db.transaction() as conn:
        maria = str(conn.execute("SELECT id FROM users WHERE email='maria@example.com'").fetchone()['id'])
    url = f'/api/org/reviews/{no}'
    assert c.post(url + '/done', headers=ORIGIN).json()['detail'] == 'not_paid'
    assert c.patch(url, headers=ORIGIN, json={'status': 'done'}).status_code == 422          # «готово» — только кнопкой
    ok(c.patch(url, headers=ORIGIN, json={'status': 'payment_sent', 'org_note': 'ссылка отправлена в Telegram'}))
    v = ok(c.patch(url, headers=ORIGIN, json={'status': 'paid', 'user_id': maria}))
    assert v['status'] == 'paid' and v['paid_at'] and v['person']['email'] == 'maria@example.com'
    assert c.post(url + '/done', headers=ORIGIN).json()['detail'] == 'no_review'
    assert c.post(url + '/audio', headers={**ORIGIN, 'Content-Type': 'image/jpeg'}, content=AUDIO).status_code == 415
    v = ok(c.post(url + '/audio', headers={**ORIGIN, 'Content-Type': 'audio/mpeg'}, content=AUDIO))
    assert v['has_audio'] and v['audio_bytes'] == len(AUDIO)
    # до «готово» участница разбора не видит и аудио не получает
    assert ok(p.get('/api/reviews'))['items'][0]['audio'] is False
    assert p.get(f'/api/reviews/{no}/audio').status_code == 404
    ok(c.patch(url, headers=ORIGIN, json={'review_text': 'Контур ровный, но блики стоит смягчить.'}))
    v = ok(c.post(url + '/done', headers=ORIGIN))
    assert v['status'] == 'done' and v['next'] == []
    mine = ok(p.get('/api/reviews'))['items'][0]
    assert mine['audio'] and mine['text'].startswith('Контур') and mine['reviewer'] == 'Милена'
    a = p.get(f'/api/reviews/{no}/audio')
    assert a.status_code == 200 and a.content == AUDIO and a.headers['content-type'].startswith('audio/mpeg')
    part = p.get(f'/api/reviews/{no}/audio', headers={'Range': 'bytes=0-9'})      # Safari на iPhone просит части файла
    assert part.status_code == 206 and part.content == AUDIO[:10]
    assert other.get(f'/api/reviews/{no}/audio').status_code == 404 and ok(other.get('/api/reviews'))['items'] == []
    assert p.get(f'/api/org/reviews/{no}').status_code == 403
    notes = ok(p.get('/api/notifications'))['notifications']
    assert any('Разбор' in str(n) for n in notes)
    assert c.patch(url, headers=ORIGIN, json={'status': 'cancelled'}).json()['detail'] == 'wrong_status'   # готовый — не отменить


def test_cancel_and_reopen(app, seed, clock):
    game_with_round_published(app)
    no = ok(site(app).post('/api/public/review-order', json={'name': 'Ольга', 'contact': '+7 900', 'scope': 'one', 'round_no': 1,
                                                            'accept_terms': True}), 201)['order_no']
    c = org(app, seed)
    ok(c.patch(f'/api/org/reviews/{no}', headers=ORIGIN, json={'status': 'cancelled'}))
    assert ok(c.get('/api/org/reviews'))['items'] == [] and len(ok(c.get('/api/org/reviews?status=cancelled'))['items']) == 1
    ok(c.patch(f'/api/org/reviews/{no}', headers=ORIGIN, json={'status': 'new'}))
    assert c.patch(f'/api/org/reviews/{no}', headers=ORIGIN, json={'user_id': '00000000-0000-0000-0000-000000000000'}).json()['detail'] == 'unknown_person'
