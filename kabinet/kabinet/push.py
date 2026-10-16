"""Пуш-уведомления на телефон и компьютер (Web Push, 17.10): кабинет, установленный на экран телефона, получает
уведомления как приложение. Тот же поток, что колокольчик и мессенджеры: всё, что попало в notifications после
подписки устройства, уходит пушем с переходом на нужную страницу кабинета.

- Ключ VAPID (P-256) создаёт сервер (fpl-kabinet-setup → /etc/fpl-kabinet-push.pem), кабинет его только читает.
- Шифрование содержимого — RFC 8291 (aes128gcm), подпись — RFC 8292 (VAPID, ES256). Без сторонних push-библиотек:
  нужен только пакет cryptography.
- Адрес подписки — только у известных служб доставки (Google, Mozilla, Apple, Microsoft): сервер не ходит по чужим адресам.
- Устройство отписалось или удалило подписку (ответ 404/410) — подписка удаляется.
- iPhone: только когда кабинет установлен на экран «Домой» (iOS 16.4+); Android — в браузере.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from kabinet.participation.views import iso
from kabinet.web.routes import browser_user, same_origin

log = logging.getLogger('kabinet.push')
router = APIRouter(prefix='/api/push', tags=['participant'])
PUSH_HOSTS = ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'push.services.mozilla.com',
              'web.push.apple.com', 'notify.windows.com')
MAX_AGE_HOURS = 48
BATCH = 40


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def host_ok(endpoint):
    u = urllib.parse.urlparse(endpoint or '')
    h = (u.hostname or '').lower()
    return u.scheme == 'https' and not u.port and any(h == x or h.endswith('.' + x) for x in PUSH_HOSTS)


# ---------- ключ сервера ----------

_KEY = {}


def server_key(settings):
    path = settings.push_key_file
    if not path:
        return None
    if path not in _KEY:
        try:
            with open(path, 'rb') as f:
                _KEY[path] = serialization.load_pem_private_key(f.read(), password=None)
        except (OSError, ValueError):
            log.warning('push key unreadable')
            return None
    return _KEY[path]


def public_key_b64(key):
    return b64u(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def enabled(settings):
    return server_key(settings) is not None


# ---------- шифрование (RFC 8291) и подпись (RFC 8292) ----------

def _hkdf(salt, ikm, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b'\x01', hashlib.sha256).digest()[:length]


def encrypt(payload, p256dh, auth, salt=None, local=None):
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    local = local or ec.generate_private_key(ec.SECP256R1())
    as_public = local.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = local.exchange(ec.ECDH(), peer)
    ikm = _hkdf(auth_secret, shared, b'WebPush: info\x00' + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!IB', 4096, len(as_public)) + as_public + body


def vapid_header(key, endpoint, subject, now=None):
    u = urllib.parse.urlparse(endpoint)
    claims = {'aud': f'{u.scheme}://{u.netloc}', 'exp': int((now or time.time()) + 12 * 3600), 'sub': subject}
    head = b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    body = b64u(json.dumps(claims, separators=(',', ':')).encode())
    r, s = decode_dss_signature(key.sign(f'{head}.{body}'.encode(), ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={head}.{body}.{sig}, k={public_key_b64(key)}'


class Live:
    def __init__(self, settings):
        self.settings = settings

    def send(self, sub, data):
        """→ 'ok' | 'gone' (подписки больше нет) | 'retry' | 'failed'"""
        key = server_key(self.settings)
        body = encrypt(json.dumps(data, ensure_ascii=False).encode(), sub['p256dh'], sub['auth'])
        req = urllib.request.Request(sub['endpoint'], data=body, method='POST', headers={
            'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': '86400', 'Urgency': 'normal',
            'Authorization': vapid_header(key, sub['endpoint'], self.settings.push_subject)})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return 'ok' if r.status in (200, 201, 202) else 'failed'
        except urllib.error.HTTPError as e:
            return 'gone' if e.code in (404, 410) else 'retry' if e.code in (429, 500, 502, 503) else 'failed'
        except (urllib.error.URLError, TimeoutError, OSError):
            return 'retry'


class Memory:
    def __init__(self):
        self.sent, self.gone = [], set()

    def send(self, sub, data):
        if sub['endpoint'] in self.gone:
            return 'gone'
        self.sent.append({'endpoint': sub['endpoint'], 'data': data})
        return 'ok'


def transport(app):
    t = getattr(app.state, 'push_transport', None)
    if t is None:
        t = app.state.push_transport = Live(app.state.settings)
    return t


# ---------- кабинет ----------

class SubIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: dict


class EndpointIn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    endpoint: str = Field(min_length=20, max_length=1000)


def devices(conn, user_id):
    return conn.execute('SELECT * FROM push_subscriptions WHERE user_id=%s ORDER BY created_at', (user_id,)).fetchall()


@router.get('')
def status(request: Request, user=Depends(browser_user)):
    key = server_key(request.app.state.settings)
    with request.app.state.db.transaction() as conn:
        subs = devices(conn, user['id'])
    return {'available': key is not None, 'public_key': public_key_b64(key) if key else None,
            'devices': [{'endpoint': s['endpoint'], 'device': s['device'], 'created_at': iso(s['created_at'])} for s in subs]}


@router.post('/subscribe', dependencies=[Depends(same_origin)])
def subscribe(body: SubIn, request: Request, user=Depends(browser_user)):
    if not enabled(request.app.state.settings):
        raise HTTPException(409, 'push_off')
    if not host_ok(body.endpoint):
        raise HTTPException(422, 'bad_endpoint')
    p256dh, auth = str(body.keys.get('p256dh') or ''), str(body.keys.get('auth') or '')
    try:
        if len(unb64u(auth)) != 16:
            raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(p256dh))   # настоящий ключ устройства
    except (ValueError, TypeError):
        raise HTTPException(422, 'bad_keys') from None
    ua = (request.headers.get('user-agent') or '')[:300]
    device = 'iPhone' if 'iPhone' in ua else 'iPad' if 'iPad' in ua else 'Android' if 'Android' in ua else \
        'Mac' if 'Macintosh' in ua else 'Windows' if 'Windows' in ua else 'Устройство'
    with request.app.state.db.transaction() as conn:
        n = conn.execute('SELECT count(*) AS n FROM push_subscriptions WHERE user_id=%s', (user['id'],)).fetchone()['n']
        if n >= 10:      # старые устройства уходят, когда подписок слишком много
            conn.execute('''DELETE FROM push_subscriptions WHERE id IN (SELECT id FROM push_subscriptions WHERE user_id=%s
ORDER BY created_at LIMIT %s)''', (user['id'], n - 9))
        conn.execute('''INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,device) VALUES (%s,%s,%s,%s,%s)
ON CONFLICT (endpoint) DO UPDATE SET user_id=EXCLUDED.user_id, p256dh=EXCLUDED.p256dh, auth=EXCLUDED.auth,
device=EXCLUDED.device, created_at=now()''', (user['id'], body.endpoint, p256dh, auth, device))
    return status(request, user)


@router.post('/unsubscribe', dependencies=[Depends(same_origin)])
def unsubscribe(body: EndpointIn, request: Request, user=Depends(browser_user)):
    with request.app.state.db.transaction() as conn:
        conn.execute('DELETE FROM push_subscriptions WHERE user_id=%s AND endpoint=%s', (user['id'], body.endpoint))
    return status(request, user)


@router.post('/test', dependencies=[Depends(same_origin)])
def test_push(request: Request, user=Depends(browser_user)):
    if not enabled(request.app.state.settings):
        raise HTTPException(409, 'push_off')
    with request.app.state.db.transaction() as conn:
        subs = devices(conn, user['id'])
    if not subs:
        raise HTTPException(409, 'no_devices')
    data = {'title': 'Face Painting League', 'body': 'Уведомления работают — сюда придут задания, сроки и итоги.',
            'url': request.app.state.settings.frontend_url.rstrip('/') + '/profile/notifications'}
    ok = sum(1 for s in subs if send_one(request.app, s, data) == 'ok')
    return {'sent': ok, 'devices': len(subs)}


def send_one(app, sub, data):
    res = transport(app).send(sub, data)
    with app.state.db.transaction() as conn:
        if res == 'gone':
            conn.execute('DELETE FROM push_subscriptions WHERE id=%s', (sub['id'],))
        elif res == 'ok':
            conn.execute('UPDATE push_subscriptions SET last_ok_at=now() WHERE id=%s', (sub['id'],))
    return res


# ---------- доставка ----------

def deliver(app, limit=BATCH):
    """Одна порция: уведомления кабинета → на все устройства участницы. Одна строка messenger_deliveries
    (provider webpush) на уведомление — повтора нет."""
    from kabinet.messengers import kabinet_url, notice_path
    if not enabled(app.state.settings):
        return 0
    with app.state.db.transaction() as conn:
        if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('fpl-push-deliver')) AS ok").fetchone()['ok']:
            return 0
        todo = conn.execute('''SELECT n.id, n.user_id, n.payload FROM notifications n
WHERE n.channel='in_app' AND n.created_at > now() - make_interval(hours => %s)
  AND EXISTS (SELECT 1 FROM push_subscriptions s WHERE s.user_id=n.user_id AND s.created_at <= n.created_at)
  AND NOT EXISTS (SELECT 1 FROM messenger_deliveries d WHERE d.notification_id=n.id AND d.provider='webpush')
ORDER BY n.created_at LIMIT %s''', (MAX_AGE_HOURS, limit)).fetchall()
        for t in todo:
            conn.execute('''INSERT INTO messenger_deliveries(notification_id,provider,external_id,status)
VALUES (%s,'webpush','devices','sending')''', (t['id'],))
    sent = 0
    for t in todo:
        p = t['payload'] or {}
        data = {'title': str(p.get('title') or 'Face Painting League')[:120], 'body': str(p.get('text') or '')[:300],
                'url': kabinet_url(app.state.settings, notice_path(p)), 'tag': str(t['id'])}
        with app.state.db.transaction() as conn:
            subs = conn.execute('SELECT * FROM push_subscriptions WHERE user_id=%s', (t['user_id'],)).fetchall()
        results = [send_one(app, s, data) for s in subs]
        ok = results.count('ok')
        retry = not ok and 'retry' in results
        with app.state.db.transaction() as conn:
            if retry:
                conn.execute("DELETE FROM messenger_deliveries WHERE notification_id=%s AND provider='webpush'", (t['id'],))
            else:
                conn.execute('''UPDATE messenger_deliveries SET status=%s, external_id=%s, sent_at=CASE WHEN %s THEN now() END,
error=%s WHERE notification_id=%s AND provider='webpush' ''',
                             ('sent' if ok else 'skipped' if not subs or set(results) == {'gone'} else 'failed',
                              f'devices:{ok}/{len(subs)}', bool(ok), None if ok else ','.join(sorted(set(results)))[:300], t['id']))
        sent += 1 if ok else 0
        if retry:
            break
    return sent
