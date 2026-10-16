"""Пуш-уведомления (Web Push, 17.10): шифрование по RFC 8291 (проверка расшифровкой, как в браузере), подпись VAPID,
подписка устройства, доставка уведомлений кабинета, удаление умершей подписки, работник страницы и манифест."""
import base64
import json
import os
import tempfile

import psycopg
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from conftest import make_settings
from game_helpers import ORIGIN, h, login
from kabinet import push as P
from kabinet.auth.mail import MemoryMailer
from kabinet.main import create_app
from test_org import ok


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def browser_keys():
    ua = ec.generate_private_key(ec.SECP256R1())
    pub = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return ua, b64(pub), b64(os.urandom(16))


def decrypt(body, ua, p256dh, auth):
    """Как браузер (RFC 8291, получатель)."""
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], 'big'), body[20]
    as_public = body[21:21 + idlen]
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = P._hkdf(P.unb64u(auth), shared, b'WebPush: info\x00' + P.unb64u(p256dh) + as_public, 32)
    cek = P._hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = P._hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    assert rs == 4096 and plain.endswith(b'\x02')
    return plain[:-1]


def test_encrypt_and_vapid():
    ua, p256dh, auth = browser_keys()
    msg = json.dumps({'title': 'Итоги тура 3', 'body': 'Вы проходите дальше'}, ensure_ascii=False).encode()
    assert decrypt(P.encrypt(msg, p256dh, auth), ua, p256dh, auth) == msg
    # известный пример RFC 8291, приложение A: тот же ответ при тех же ключах и соли
    rfc_ua = ec.derive_private_key(int.from_bytes(P.unb64u('q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94'), 'big'), ec.SECP256R1())
    rfc_as = ec.derive_private_key(int.from_bytes(P.unb64u('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), ec.SECP256R1())
    out = P.encrypt(b'When I grow up, I want to be a watermelon',
                    'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
                    'BTBZMqHH6r4Tts7J_aSIgg', salt=P.unb64u('DGv6ra1nlYgDCS1FRnbzlw'), local=rfc_as)
    assert P.b64u(out) == ('DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tlz'
                           'AC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')
    assert rfc_ua   # ключ получателя примера — для расшифровки той же строки
    key = ec.generate_private_key(ec.SECP256R1())
    hdr = P.vapid_header(key, 'https://fcm.googleapis.com/fcm/send/abc', 'https://facepaintingleague.com', now=1_800_000_000)
    t = hdr.split('t=')[1].split(',')[0]
    head, claims, sig = t.split('.')
    assert json.loads(P.unb64u(claims)) == {'aud': 'https://fcm.googleapis.com', 'exp': 1_800_000_000 + 43200,
                                             'sub': 'https://facepaintingleague.com'}
    raw = P.unb64u(sig)
    key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')),
                            f'{head}.{claims}'.encode(), ec.ECDSA(hashes.SHA256()))
    assert P.host_ok('https://fcm.googleapis.com/fcm/send/x') and P.host_ok('https://web.push.apple.com/QA')
    assert not P.host_ok('https://evil.example/fcm.googleapis.com') and not P.host_ok('http://fcm.googleapis.com/x')
    assert not P.host_ok('https://fcm.googleapis.com:8443/x') and not P.host_ok('https://127.0.0.1/x')


def make_app(database_dsn, clock):
    with psycopg.connect(database_dsn) as conn:
        conn.execute("""TRUNCATE users, events, legal_documents, seasons, auth_rate_limits, notifications, consents,
media_files, audit_log, system_errors, feedback_messages CASCADE""")
    fd, path = tempfile.mkstemp(suffix='.pem')
    with os.fdopen(fd, 'wb') as f:
        f.write(ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    app = create_app(make_settings(database_dsn, push_key_file=path, messenger_worker=False), MemoryMailer(), clock=clock)
    app.state.push_transport = P.Memory()
    return app


def test_subscribe_deliver_and_gone(database_dsn, clock):
    from conftest import PASSWORD, password_hasher  # noqa: F401
    clock.set(h())
    app = make_app(database_dsn, clock)

    def seed(email, roles=('participant',)):
        with app.state.db.transaction() as conn:
            u = conn.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status)
VALUES (%s,%s,now(),'active') RETURNING id''', (email, password_hasher.hash(PASSWORD))).fetchone()
            for r in roles:
                conn.execute('INSERT INTO user_roles(user_id,role) VALUES (%s,%s)', (u['id'], r))
            return u['id']
    p = login(app, lambda e, roles=('participant',): seed(e, roles), 'anna@example.com')
    st = ok(p.get('/api/push'))
    assert st['available'] and len(P.unb64u(st['public_key'])) == 65 and st['devices'] == []
    _, p256dh, auth = browser_keys()
    good = {'endpoint': 'https://fcm.googleapis.com/fcm/send/device-1', 'keys': {'p256dh': p256dh, 'auth': auth}}
    assert p.post('/api/push/subscribe', json=good).status_code == 403                       # без Origin
    assert p.post('/api/push/subscribe', headers=ORIGIN, json=good | {'endpoint': 'https://evil.example/x' * 3}).json()['detail'] == 'bad_endpoint'
    assert p.post('/api/push/subscribe', headers=ORIGIN, json=good | {'keys': {'p256dh': 'x' * 87, 'auth': 'y' * 22}}).json()['detail'] == 'bad_keys'
    assert p.post('/api/push/test', headers=ORIGIN).json()['detail'] == 'no_devices'
    st = ok(p.post('/api/push/subscribe', headers={**ORIGIN, 'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)'}, json=good))
    assert [d['device'] for d in st['devices']] == ['iPhone']
    ok(p.post('/api/push/subscribe', headers=ORIGIN, json=good))                             # повтор — та же подписка
    assert len(ok(p.get('/api/push'))['devices']) == 1
    assert ok(p.post('/api/push/test', headers=ORIGIN)) == {'sent': 1, 'devices': 1}
    with app.state.db.transaction() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email='anna@example.com'").fetchone()['id']
        from kabinet.participation import game as G
        G.notify(conn, uid, 'results', 'n1', {'title': 'Итоги тура 2', 'text': 'Вы проходите в тур 3', 'route': 'game',
                                              'event_id': '00000000-0000-0000-0000-000000000002'})
    assert P.deliver(app) == 1 and P.deliver(app) == 0
    last = app.state.push_transport.sent[-1]
    assert last['data']['title'] == 'Итоги тура 2' and last['data']['url'].endswith('/games/00000000-0000-0000-0000-000000000002')
    # устройство удалило подписку — она пропадает, уведомление помечено «пропущено»
    app.state.push_transport.gone.add(good['endpoint'])
    with app.state.db.transaction() as conn:
        G.notify(conn, uid, 'task', 'n2', {'title': 'Тур 3 открыт', 'route': 'task'})
    assert P.deliver(app) == 0 and ok(p.get('/api/push'))['devices'] == []
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT status FROM messenger_deliveries WHERE provider='webpush' ORDER BY created_at DESC LIMIT 1").fetchone()['status'] == 'skipped'
    ok(p.post('/api/push/subscribe', headers=ORIGIN, json=good | {'endpoint': 'https://web.push.apple.com/device-2'}))
    assert ok(p.post('/api/push/unsubscribe', headers=ORIGIN, json={'endpoint': 'https://web.push.apple.com/device-2'}))['devices'] == []


def test_worker_files_and_off(client):
    sw = client.get('/sw.js')
    assert sw.status_code == 200 and 'javascript' in sw.headers['content-type'] and 'showNotification' in sw.text
    man = client.get('/manifest.webmanifest').json()
    assert man['display'] == 'standalone' and man['short_name'] == 'FPL' and len(man['icons']) == 3
    assert '/manifest.webmanifest' in client.get('/').text
    assert P.deliver(client.app) == 0                                                         # ключа нет — пуши выключены
