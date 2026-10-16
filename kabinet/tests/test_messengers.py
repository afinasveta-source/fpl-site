"""Уведомления в Telegram и ВКонтакте (16.10): привязка одноразовым кодом, доставка уведомлений кабинета, «стоп»,
заблокированный бот, рассылка организатора. Мессенджеры — подменённые (Memory), сеть не нужна."""
import psycopg
from fastapi.testclient import TestClient

from conftest import make_settings
from game_helpers import ORIGIN, h, login, register
from kabinet.auth.mail import MemoryMailer
from kabinet.main import create_app
from kabinet import messengers as M
from test_org import game_ready, ok, org, publish_docs

HOOK = 'p' * 32
HEAD = {'X-Telegram-Bot-Api-Secret-Token': 's' * 32}


def make_app(database_dsn, clock, **extra):
    with psycopg.connect(database_dsn) as conn:
        conn.execute("""TRUNCATE users, events, legal_documents, seasons, auth_rate_limits, notifications, consents,
media_files, audit_log, system_errors, feedback_messages CASCADE""")
    values = dict(tg_token='123:abc', tg_username='fpl_test_bot', tg_hook_path=HOOK, tg_hook_secret='s' * 32,
                  vk_token='vk-token', vk_group_id=4242, vk_secret='vk-secret', vk_confirmation='conf123', messenger_worker=False)
    values.update(extra)
    app = create_app(make_settings(database_dsn, **values), MemoryMailer(), clock=clock)
    app.state.messenger_transport = M.Memory()
    return app


def tg(bot, chat, text, username='anna'):
    return bot.post(f'/api/messenger-hook/telegram/{HOOK}', headers=HEAD, json={'update_id': 1, 'message': {
        'message_id': 1, 'chat': {'id': chat, 'type': 'private'}, 'from': {'id': chat, 'first_name': 'Анна', 'username': username},
        'text': text}})


def vk(bot, peer, text='', ref=None, secret='vk-secret'):
    msg = {'peer_id': peer, 'from_id': peer, 'text': text}
    if ref:
        msg['ref'] = ref
    return bot.post('/api/messenger-hook/vk', json={'type': 'message_new', 'group_id': 4242, 'secret': secret, 'object': {'message': msg}})


def test_link_deliver_stop(database_dsn, clock):
    clock.set(h())
    app = make_app(database_dsn, clock)
    from conftest import password_hasher, PASSWORD   # noqa: F401  (seed без фикстуры)

    def seed(email, roles=('participant',)):
        with app.state.db.transaction() as conn:
            u = conn.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,display_name)
VALUES (%s,%s,now(),'active',%s) RETURNING id''', (email, password_hasher.hash(PASSWORD), 'Анна Альфа')).fetchone()
            for r in roles:
                conn.execute('INSERT INTO user_roles(user_id,role) VALUES (%s,%s)', (u['id'], r))
            return u['id']
    p = login(app, lambda e, roles=('participant',): seed(e, roles), 'anna@example.com')
    bot = TestClient(app)
    st = ok(p.get('/api/messengers'))
    assert st['telegram']['available'] and st['vk']['available'] and not st['telegram']['linked']
    # чужой адрес / без секрета — как будто его нет
    assert bot.post('/api/messenger-hook/telegram/wrong', headers=HEAD, json={}).status_code == 404
    assert bot.post(f'/api/messenger-hook/telegram/{HOOK}', json={}).status_code == 404
    assert p.post('/api/messengers/telegram/link').status_code == 403        # без Origin — нельзя
    lk = ok(p.post('/api/messengers/telegram/link', headers=ORIGIN))
    assert lk['url'].startswith('https://t.me/fpl_test_bot?start=') and lk['minutes'] == 15
    code = lk['url'].split('=', 1)[1]
    r = ok(tg(bot, 777, '/start WRONGCOD'))
    assert 'устарела' in r['text']
    r = ok(tg(bot, 777, f'/start {code}'))
    assert r['method'] == 'sendMessage' and r['chat_id'] == 777 and 'Анна Альфа' in r['text']
    assert 'устарела' in ok(tg(bot, 778, f'/start {code}'))['text']             # код одноразовый
    st = ok(p.get('/api/messengers'))
    assert st['telegram']['linked'] and st['telegram']['name'] == '@anna'
    # уведомление кабинета → в Telegram, с кнопкой на нужную страницу; повторная доставка ничего не шлёт
    with app.state.db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email='anna@example.com'").fetchone()['id']
        from kabinet.participation import game as G
        G.notify(conn, uid, 'results', 'k1', {'title': 'Итоги тура 2', 'text': 'Вы проходите <дальше>', 'route': 'game',
                                              'event_id': '00000000-0000-0000-0000-000000000001'})
    assert M.deliver(app) == 1 and M.deliver(app) == 0
    sent = app.state.messenger_transport.sent
    assert sent[-1]['to'] == '777' and sent[-1]['text'] == '<b>Итоги тура 2</b>\nВы проходите &lt;дальше&gt;'
    assert sent[-1]['button'][1].endswith('/games/00000000-0000-0000-0000-000000000001')
    # Telegram выключен в настройках — не шлём
    ok(p.put('/api/preferences', headers=ORIGIN, json={'telegram': False}))
    with app.state.db.transaction() as conn:
        G.notify(conn, uid, 'task', 'k2', {'title': 'Задание тура 3', 'route': 'task'})
    assert M.deliver(app) == 0
    ok(p.put('/api/preferences', headers=ORIGIN, json={'telegram': True}))
    # ВКонтакте: ссылка с ref и код руками; чужие сообщения сообщества бот не трогает
    lk = ok(p.post('/api/messengers/vk/link', headers=ORIGIN))
    assert lk['url'].startswith('https://vk.me/club4242?ref=') and lk['code'].startswith('FPL-')
    assert bot.post('/api/messenger-hook/vk', json={'type': 'confirmation', 'group_id': 4242}).text == 'conf123'
    assert vk(bot, 555, 'Здравствуйте, когда придёт мой заказ?').text == 'ok'
    assert vk(bot, 555, lk['code'], secret='wrong').text == 'ok'                 # без секрета — ничего
    assert not ok(p.get('/api/messengers'))['vk']['linked']
    n = len(sent)
    assert vk(bot, 555, f"мой код {lk['code'].lower()}").text == 'ok'
    assert ok(p.get('/api/messengers'))['vk']['linked'] and sent[n]['provider'] == 'vk' and 'Анна Альфа' in sent[n]['text']
    with app.state.db.transaction() as conn:
        G.notify(conn, uid, 'judging', 'k3', {'title': 'Судейство открыто', 'route': 'judging'})
    assert M.deliver(app) == 2                                                     # и в Telegram, и во ВКонтакте
    assert {x['provider'] for x in sent[-2:]} == {'telegram', 'vk'}
    # заблокировала бота — связка помечается, больше не шлём
    app.state.messenger_transport.blocked.add(('telegram', '777'))
    with app.state.db.transaction() as conn:
        G.notify(conn, uid, 'task', 'k4', {'title': 'Ещё', 'route': 'task'})
    assert M.deliver(app) == 1 and ok(p.get('/api/messengers'))['telegram']['blocked']
    # «стоп» в Telegram и отключение в кабинете
    assert 'отключены' in ok(tg(bot, 777, '/stop'))['text']
    assert not ok(p.get('/api/messengers'))['telegram']['linked']
    assert not ok(p.post('/api/messengers/vk/unlink', headers=ORIGIN))['vk']['linked']
    with app.state.db.transaction() as conn:
        G.notify(conn, uid, 'task', 'k5', {'title': 'После отключения', 'route': 'task'})
    assert M.deliver(app) == 0
    with app.state.db.transaction() as conn:
        acts = [r['action'] for r in conn.execute("SELECT action FROM audit_log WHERE entity_id=%s ORDER BY created_at, id", (uid,))]
    assert acts.count('messenger_linked') == 2 and acts.count('messenger_unlinked') == 2
    # другое сообщение боту — подсказка про поддержку
    assert 'Поддержку' in ok(tg(bot, 999, 'а когда итоги?'))['text']


def test_channels_off_without_tokens(app, seed):
    p = login(app, seed, 'x@example.com')
    st = ok(p.get('/api/messengers'))
    assert not st['telegram']['available'] and not st['vk']['available']
    assert p.post('/api/messengers/telegram/link', headers=ORIGIN).status_code == 409
    assert TestClient(app).post(f'/api/messenger-hook/telegram/{HOOK}', headers=HEAD, json={}).status_code == 404
    assert M.deliver(app) == 0


def test_org_broadcast(app, seed, clock):
    clock.set(h())
    app.state.messenger_transport = M.Memory()
    c = org(app, seed)
    publish_docs(c)
    eid, _ = game_ready(c, rounds=2)
    ok(c.post(f'/api/org/events/{eid}/status', headers=ORIGIN, json={'action': 'publish'}))
    for e in ('a@example.com', 'b@example.com'):
        ok(register(login(app, seed, e), eid), 201)
    body = {'title': 'Тур 3 завтра', 'text': 'Задание откроется в 10:00.', 'audience': 'active'}
    info = ok(c.post(f'/api/org/events/{eid}/broadcast', headers=ORIGIN, json=body))
    assert info['recipients'] == 2 and 'sent' not in info and info['messengers'] == {'telegram': 0, 'vk': 0, 'any': 0}
    assert ok(c.post(f'/api/org/events/{eid}/broadcast', headers=ORIGIN, json=body | {'league': 'gold'}))['recipients'] == 0
    res = ok(c.post(f'/api/org/events/{eid}/broadcast', headers=ORIGIN, json=body | {'send': True}))
    assert res['sent'] and res['recipients'] == 2
    assert c.post(f'/api/org/events/{eid}/broadcast', headers=ORIGIN, json=body | {'send': True, 'league': 'gold'}).json()['detail'] == 'no_recipients'
    a = login(app, seed, 'a2@example.com')
    assert a.post(f'/api/org/events/{eid}/broadcast', headers=ORIGIN, json=body).status_code == 403
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM notifications WHERE notification_type='broadcast'").fetchone()['n'] == 2
        assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE action='broadcast_sent'").fetchone()['n'] == 1
