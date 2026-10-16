"""Уведомления кабинета в Telegram и ВКонтакте (решение 16.10: свой бот лиги вместо SaleBot).

Привязка. Участница в кабинете нажимает «Подключить Telegram / ВКонтакте» → одноразовый код (15 минут, один раз; в базе
только sha256) → ссылка на бота: t.me/<бот>?start=<код> или vk.me/club<id>?ref=<код>. Бот получает код и id человека
в мессенджере, кабинет сверяет код и запоминает связку (external_identities, provider telegram / vk). Бот не входит в
кабинет и ничего в нём не меняет: только присылает уведомления. Одна учётная запись мессенджера — один аккаунт кабинета;
у аккаунта — один Telegram и один ВКонтакте.

Доставка. Всё, что кабинет пишет в колокольчик (notifications), после привязки уходит и в мессенджер — заголовок, текст
и кнопка «Открыть в кабинете». Одна строка messenger_deliveries на уведомление и канал — повтора не бывает. Telegram
выключен в настройках уведомлений участницы — в Telegram не шлём. Заблокировала бота — связка помечается blocked.
Старше двух суток не досылаем (например, если бот был выключен).

ВКонтакте может быть общим с магазином: бот отвечает только на код подключения и «стоп»; остальные сообщения не трогает —
их видят менеджеры в сообщениях сообщества.
"""
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from kabinet.web.routes import browser_user, same_origin
from kabinet.participation import game as G
from kabinet.participation.views import iso

log = logging.getLogger('kabinet.messengers')
mine = APIRouter(prefix='/api/messengers', tags=['participant'])
hooks = APIRouter(prefix='/api/messenger-hook', tags=['messengers'])

PROVIDERS = ('telegram', 'vk')
CODE_MINUTES = 15
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'      # без 0/O и 1/I — код могут набрать руками (ВКонтакте)
CODE_RX = re.compile(r'\bFPL[-\s]?([A-HJ-NP-Z2-9]{8})\b', re.I)
MAX_AGE_HOURS = 48
BATCH = 40
NAME = {'telegram': 'Telegram', 'vk': 'ВКонтакте'}


def db(request):
    return request.app.state.db


def secret(v):
    return v.get_secret_value() if v is not None else None


def enabled(settings):
    out = []
    if settings.tg_token and settings.tg_username and settings.tg_hook_path and settings.tg_hook_secret:
        out.append('telegram')
    if settings.vk_token and settings.vk_group_id and settings.vk_secret:
        out.append('vk')
    return out


def code_hash(code):
    return hashlib.sha256(code.upper().encode()).hexdigest()


# ---------- куда ведёт кнопка ----------

def notice_path(payload):
    """Как noticeHref в кабинете (pages.js): адрес страницы кабинета для уведомления."""
    p = payload or {}
    r = p.get('route')
    if r == 'task' and p.get('event_id') and p.get('assignment_id'):
        return f"/games/{p['event_id']}/tasks/{p['assignment_id']}"
    if r in ('game', 'results') and p.get('event_id'):
        return f"/games/{p['event_id']}"
    if r == 'publicity':
        return '/profile/publicity'
    if r == 'reviews':
        return '/reviews'
    if r == 'judge_review':
        return f"/judging/reviews/{p['order_no']}" if p.get('order_no') else '/judging'
    if r == 'support' and p.get('thread_no'):
        return f"/support/{p['thread_no']}"
    if r == 'document' and p.get('document_id'):
        return f"/documents/{p['document_id']}"
    if r == 'judging':
        return f"/judging/{p['stream_id']}" if p.get('stream_id') else '/judging'
    return '/'


def kabinet_url(settings, path='/'):
    return settings.frontend_url.rstrip('/') + (path if path.startswith('/') else '/' + path)


# ---------- отправка ----------

class SendError(Exception):
    def __init__(self, kind, detail=''):
        super().__init__(f'{kind}: {detail}')
        self.kind = kind          # blocked — человек закрыл бота; retry — подождать; failed — не получилось
        self.detail = str(detail)[:300]


def _post(url, data, timeout=15):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode() or '{}') | {'_http': exc.code}
        except ValueError:
            raise SendError('failed', f'http {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SendError('retry', type(exc).__name__) from None


class Live:
    """Настоящие Telegram Bot API и VK API (без сторонних библиотек)."""

    def __init__(self, settings):
        self.settings = settings

    def send(self, provider, external_id, text, button=None):
        if provider == 'telegram':
            data = {'chat_id': int(external_id), 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
            if button:
                data['reply_markup'] = {'inline_keyboard': [[{'text': button[0], 'url': button[1]}]]}
            r = _post(f"https://api.telegram.org/bot{secret(self.settings.tg_token)}/sendMessage", data)
            if r.get('ok'):
                return
            code = r.get('error_code') or r.get('_http')
            if code == 403:
                raise SendError('blocked', r.get('description', ''))
            if code == 429:
                raise SendError('retry', 'too many requests')
            raise SendError('failed', f"{code} {r.get('description', '')}")
        params = {'peer_id': int(external_id), 'random_id': secrets.randbelow(2 ** 31), 'message': plain(text),
                  'access_token': secret(self.settings.vk_token), 'v': '5.199', 'dont_parse_links': 1}
        if button:
            params['keyboard'] = json.dumps({'inline': True, 'buttons': [[{'action': {
                'type': 'open_link', 'link': button[1], 'label': button[0][:40]}}]]}, ensure_ascii=False)
        req = urllib.request.Request('https://api.vk.com/method/messages.send', data=urllib.parse.urlencode(params).encode())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                r = json.loads(resp.read().decode() or '{}')
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SendError('retry', type(exc).__name__) from None
        err = r.get('error')
        if not err:
            return
        code = err.get('error_code')
        if code in (900, 901, 902):      # запретил сообщения / в чёрном списке / не писал сообществу
            raise SendError('blocked', err.get('error_msg', ''))
        if code in (6, 9, 10):
            raise SendError('retry', err.get('error_msg', ''))
        raise SendError('failed', f"{code} {err.get('error_msg', '')}")


class Memory:
    """Для тестов: запоминает отправленное; blocked — id, для которых «человек закрыл бота»."""

    def __init__(self):
        self.sent, self.blocked = [], set()

    def send(self, provider, external_id, text, button=None):
        if (provider, str(external_id)) in self.blocked:
            raise SendError('blocked', 'test')
        self.sent.append({'provider': provider, 'to': str(external_id), 'text': text, 'button': button})


def plain(text):
    """HTML Telegram → обычный текст ВКонтакте."""
    return html.unescape(re.sub(r'<[^>]+>', '', text))


def transport(app):
    t = getattr(app.state, 'messenger_transport', None)
    if t is None:
        t = app.state.messenger_transport = Live(app.state.settings)
    return t


# ---------- привязка ----------

def links_of(conn, user_id):
    rows = conn.execute('''SELECT provider, external_id, linked_at, metadata FROM external_identities
WHERE user_id=%s AND provider IN ('telegram','vk')''', (user_id,)).fetchall()
    return {r['provider']: r for r in rows}


def status_view(conn, settings, user_id):
    on = enabled(settings)
    links = links_of(conn, user_id)
    p = conn.execute('SELECT telegram_service_enabled FROM communication_preferences WHERE user_id=%s', (user_id,)).fetchone()
    out = {}
    for prov in PROVIDERS:
        x = links.get(prov)
        meta = (x['metadata'] or {}) if x else {}
        out[prov] = {'available': prov in on, 'linked': bool(x), 'linked_at': iso(x['linked_at']) if x else None,
                     'name': meta.get('username') or meta.get('name'), 'blocked': bool(meta.get('blocked'))}
    out['telegram']['enabled'] = p['telegram_service_enabled'] if p else True
    return out


def link(conn, provider, external_id, meta, code, now):
    """Код → привязка. Возвращает (user, 'linked' | 'bad_code')."""
    row = conn.execute('''SELECT c.*, u.full_name, u.display_name, u.email FROM messenger_link_codes c JOIN users u ON u.id=c.user_id
WHERE c.code_hash=%s AND c.provider=%s FOR UPDATE OF c''', (code_hash(code), provider)).fetchone()
    if row is None or row['used_at'] is not None or row['expires_at'] < now:
        return None, 'bad_code'
    uid = row['user_id']
    conn.execute('UPDATE messenger_link_codes SET used_at=%s WHERE code_hash=%s', (now, row['code_hash']))
    # у аккаунта — одна учётная запись этого мессенджера: прежняя отвязывается
    conn.execute('''UPDATE external_identities SET user_id=NULL, metadata=metadata || '{"unlinked":"replaced"}'::jsonb
WHERE user_id=%s AND provider=%s AND external_id<>%s''', (uid, provider, str(external_id)))
    prev = conn.execute('''SELECT user_id FROM external_identities WHERE provider=%s AND project_ref='' AND external_id=%s FOR UPDATE''',
                        (provider, str(external_id))).fetchone()
    meta = {k: v for k, v in (meta or {}).items() if v} | {'blocked': False}
    conn.execute('''INSERT INTO external_identities(user_id,provider,project_ref,external_id,verified_at,linked_at,metadata)
VALUES (%s,%s,'',%s,now(),now(),%s) ON CONFLICT (provider,project_ref,external_id) DO UPDATE SET user_id=EXCLUDED.user_id,
verified_at=EXCLUDED.verified_at, linked_at=EXCLUDED.linked_at, metadata=EXCLUDED.metadata''',
                 (uid, provider, str(external_id), G.Jsonb(meta)))   # время базы — как у уведомлений (created_at)
    G.audit(conn, uid, 'user', uid, 'messenger_linked', {'provider': provider, 'moved_from_other_account':
                                                         bool(prev and prev['user_id'] and prev['user_id'] != uid)})
    return row, 'linked'


def unlink(conn, provider, external_id=None, user_id=None, reason='user'):
    where, args = ['provider=%s', 'user_id IS NOT NULL'], [provider]
    if external_id is not None:
        where.append('external_id=%s')
        args.append(str(external_id))
    if user_id is not None:
        where.append('user_id=%s')
        args.append(user_id)
    rows = conn.execute(f"""UPDATE external_identities x SET user_id=NULL, metadata=x.metadata || %s
FROM (SELECT id, user_id FROM external_identities WHERE {' AND '.join(where)} FOR UPDATE) old
WHERE x.id=old.id RETURNING old.user_id""", [G.Jsonb({'unlinked': reason})] + args).fetchall()
    for r in rows:
        G.audit(conn, r['user_id'], 'user', r['user_id'], 'messenger_unlinked', {'provider': provider, 'reason': reason})
    return len(rows)


def who(row):
    return row['display_name'] or row['full_name'] or 'ваш аккаунт'


# ---------- кабинет участницы ----------

@mine.get('')
def my_status(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        return status_view(conn, request.app.state.settings, user['id'])


@mine.post('/{provider}/link', dependencies=[Depends(same_origin)])
def start_link(provider: str, request: Request, user=Depends(browser_user)):
    settings = request.app.state.settings
    if provider not in PROVIDERS:
        raise HTTPException(404, 'Not found')
    if provider not in enabled(settings):
        raise HTTPException(409, 'channel_off')
    now = request.app.state.clock()
    code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    with db(request).transaction() as conn:
        n = conn.execute('''SELECT count(*) AS n FROM messenger_link_codes WHERE user_id=%s AND created_at > %s''',
                         (user['id'], now - timedelta(hours=1))).fetchone()['n']
        if n >= 10:
            raise HTTPException(429, 'too_many_codes')
        conn.execute('DELETE FROM messenger_link_codes WHERE user_id=%s AND provider=%s AND used_at IS NULL', (user['id'], provider))
        conn.execute('INSERT INTO messenger_link_codes(code_hash,user_id,provider,created_at,expires_at) VALUES (%s,%s,%s,%s,%s)',
                     (code_hash(code), user['id'], provider, now, now + timedelta(minutes=CODE_MINUTES)))
    if provider == 'telegram':
        url = f"https://t.me/{settings.tg_username}?start={code}"
    else:
        url = f"https://vk.me/club{settings.vk_group_id}?ref={code}&ref_source=kabinet"
    return {'url': url, 'code': f'FPL-{code}', 'expires_at': iso(now + timedelta(minutes=CODE_MINUTES)), 'minutes': CODE_MINUTES}


@mine.post('/{provider}/unlink', dependencies=[Depends(same_origin)])
def stop_link(provider: str, request: Request, user=Depends(browser_user)):
    if provider not in PROVIDERS:
        raise HTTPException(404, 'Not found')
    with db(request).transaction() as conn:
        unlink(conn, provider, user_id=user['id'], reason='user_cabinet')
        return status_view(conn, request.app.state.settings, user['id'])


# ---------- входящие от мессенджеров ----------

def tg_reply(chat_id, text, button=None):
    out = {'method': 'sendMessage', 'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if button:
        out['reply_markup'] = {'inline_keyboard': [[{'text': button[0], 'url': button[1]}]]}
    return out


@hooks.post('/telegram/{path_secret}')
async def telegram_hook(path_secret: str, request: Request):
    settings = request.app.state.settings
    if 'telegram' not in enabled(settings) or not hmac.compare_digest(path_secret, secret(settings.tg_hook_path)) or \
            not hmac.compare_digest(request.headers.get('x-telegram-bot-api-secret-token', ''), secret(settings.tg_hook_secret)):
        raise HTTPException(404, 'Not found')
    try:
        update = await request.json()
    except ValueError:
        return {}
    msg = update.get('message') if isinstance(update, dict) else None
    if not isinstance(msg, dict) or (msg.get('chat') or {}).get('type') != 'private':
        return {}
    chat, frm, text = msg['chat']['id'], msg.get('from') or {}, (msg.get('text') or '').strip()
    home = ('Открыть кабинет', kabinet_url(settings))
    now = request.app.state.clock()
    if text.startswith('/start'):
        arg = text[6:].strip()
        if not arg:
            with db(request).transaction() as conn:
                linked = conn.execute('''SELECT 1 FROM external_identities WHERE provider='telegram' AND external_id=%s
AND user_id IS NOT NULL''', (str(chat),)).fetchone()
            if linked:
                return tg_reply(chat, 'Уведомления Face Painting League подключены. Отключить — /stop или в кабинете: Профиль → Уведомления.', home)
            return tg_reply(chat, '<b>Бот уведомлений Face Painting League</b>\nЧтобы получать задания, сроки и итоги, '
                                  'войдите в кабинет и нажмите «Подключить Telegram» (Профиль → Уведомления).', home)
        meta = {'username': ('@' + frm['username']) if frm.get('username') else None,
                'name': ' '.join(x for x in (frm.get('first_name'), frm.get('last_name')) if x) or None}
        with db(request).transaction() as conn:
            row, res = link(conn, 'telegram', chat, meta, arg, now)
        if res != 'linked':
            return tg_reply(chat, 'Ссылка устарела или уже использована. Нажмите «Подключить Telegram» в кабинете ещё раз.', home)
        return tg_reply(chat, f'Готово: уведомления лиги будут приходить сюда.\nАккаунт кабинета: <b>{html.escape(who(row))}</b>.\n'
                              'Если это не вы — нажмите /stop.', home)
    if text in ('/stop', 'стоп', 'Стоп'):
        with db(request).transaction() as conn:
            n = unlink(conn, 'telegram', external_id=chat, reason='user_bot')
        return tg_reply(chat, 'Уведомления отключены. Подключить снова — в кабинете: Профиль → Уведомления.' if n else
                        'Уведомления сюда и так не приходят.', home)
    return tg_reply(chat, 'Это бот уведомлений лиги — сообщения здесь не читаются. Вопрос по Игре — в «Поддержку» кабинета.',
                    ('Написать в поддержку', kabinet_url(settings, '/support')))


@hooks.post('/vk')
async def vk_hook(request: Request):
    settings = request.app.state.settings
    if 'vk' not in enabled(settings):
        raise HTTPException(404, 'Not found')
    try:
        body = await request.json()
    except ValueError:
        return PlainTextResponse('ok')
    if not isinstance(body, dict) or str(body.get('group_id')) != str(settings.vk_group_id):
        return PlainTextResponse('ok')
    if body.get('type') == 'confirmation':
        return PlainTextResponse(settings.vk_confirmation or '')
    if not hmac.compare_digest(str(body.get('secret') or ''), secret(settings.vk_secret)):
        return PlainTextResponse('ok')
    if body.get('type') != 'message_new':
        return PlainTextResponse('ok')
    m = ((body.get('object') or {}).get('message')) or {}
    peer, frm, text, ref = m.get('peer_id'), m.get('from_id'), (m.get('text') or '').strip(), (m.get('ref') or '').strip()
    if not peer or peer != frm or peer >= 2_000_000_000:        # только личные сообщения человека
        return PlainTextResponse('ok')
    found = CODE_RX.search(text)
    code = ref if re.fullmatch(r'[A-Za-z0-9]{8}', ref or '') else (found.group(1) if found else None)
    now = request.app.state.clock()
    home = ('Открыть кабинет', kabinet_url(settings))
    reply = None
    if code:
        with db(request).transaction() as conn:
            row, res = link(conn, 'vk', peer, {'name': f'id{peer}'}, code, now)
        reply = (f'Готово: уведомления Face Painting League будут приходить сюда.\nАккаунт кабинета: {who(row)}.\n'
                 'Если это не вы — напишите «стоп».') if res == 'linked' else \
            'Код устарел или уже использован. Нажмите «Подключить ВКонтакте» в кабинете ещё раз.'
    elif text.lower() in ('стоп', '/stop', 'stop'):
        with db(request).transaction() as conn:
            if unlink(conn, 'vk', external_id=peer, reason='user_bot'):
                reply = 'Уведомления лиги отключены. Подключить снова — в кабинете: Профиль → Уведомления.'
    # всё остальное — не наше (сообщество может быть общим с магазином): молчим, сообщение видят менеджеры
    if reply:
        try:
            transport(request.app).send('vk', peer, reply, home)
        except SendError as exc:
            log.warning('vk reply failed: %s', exc.kind)
    return PlainTextResponse('ok')


# ---------- доставка ----------

def message_of(n):
    p = n['payload'] or {}
    title = html.escape(str(p.get('title') or 'Face Painting League'))
    text = html.escape(str(p.get('text') or ''))
    return f'<b>{title}</b>' + (f'\n{text}' if text else '')


def deliver(app, now=None, limit=BATCH):
    """Одна порция доставки. Возвращает число отправленных. Безопасно вызывать сколько угодно раз и из нескольких мест:
    уведомление и канал «занимаются» строкой sending до отправки."""
    settings = app.state.settings
    on = enabled(settings)
    if not on:
        return 0
    now = now or app.state.clock()
    with app.state.db.transaction() as conn:
        if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('fpl-messenger-deliver'))").fetchone()['pg_try_advisory_xact_lock']:
            return 0
        todo = conn.execute('''SELECT n.id, n.payload, x.provider, x.external_id,
  (x.provider <> 'telegram' OR coalesce(cp.telegram_service_enabled, true)) AS wanted FROM notifications n
JOIN external_identities x ON x.user_id=n.user_id AND x.provider = ANY(%s) AND NOT coalesce((x.metadata->>'blocked')::boolean, false)
LEFT JOIN communication_preferences cp ON cp.user_id=n.user_id
WHERE n.created_at >= x.linked_at AND n.created_at > now() - make_interval(hours => %s) AND n.channel='in_app'
  AND NOT EXISTS (SELECT 1 FROM messenger_deliveries d WHERE d.notification_id=n.id AND d.provider=x.provider)
ORDER BY n.created_at LIMIT %s''', (list(on), MAX_AGE_HOURS, limit)).fetchall()
        for t in todo:                    # выключила Telegram в настройках — это уведомление туда не уходит и потом
            conn.execute('''INSERT INTO messenger_deliveries(notification_id,provider,external_id,status,created_at,error)
VALUES (%s,%s,%s,%s,%s,%s)''', (t['id'], t['provider'], t['external_id'], 'sending' if t['wanted'] else 'skipped', now,
                                None if t['wanted'] else 'turned_off'))
    todo = [t for t in todo if t['wanted']]
    sent = 0
    tr = transport(app)
    for t in todo:
        button = ('Открыть в кабинете', kabinet_url(settings, notice_path(t['payload'])))
        status, error, retry = 'sent', None, False
        try:
            tr.send(t['provider'], t['external_id'], message_of(t), button)
            sent += 1
        except SendError as exc:
            status, error, retry = ('failed', exc.detail, exc.kind == 'retry')
            if exc.kind == 'blocked':
                status = 'skipped'
                with app.state.db.transaction() as conn:
                    conn.execute('''UPDATE external_identities SET metadata=metadata || '{"blocked":true}'::jsonb
WHERE provider=%s AND external_id=%s''', (t['provider'], t['external_id']))
        except Exception as exc:          # не роняем доставку из-за одного сообщения
            status, error = 'failed', type(exc).__name__
        with app.state.db.transaction() as conn:
            if retry:                     # сеть / лимит: снять отметку — попробуем в следующий раз
                conn.execute('DELETE FROM messenger_deliveries WHERE notification_id=%s AND provider=%s', (t['id'], t['provider']))
            else:
                conn.execute('''UPDATE messenger_deliveries SET status=%s, error=%s, sent_at=%s WHERE notification_id=%s AND provider=%s''',
                             (status, error, now if status == 'sent' else None, t['id'], t['provider']))
        if retry:
            break
        if t['provider'] == 'telegram':
            time.sleep(0.04)              # Telegram: не больше ~25 сообщений в секунду
    return sent


def start_worker(app, every=10):
    from kabinet import push
    if not app.state.settings.messenger_worker or not (enabled(app.state.settings) or push.enabled(app.state.settings)):
        return None
    stop = threading.Event()

    def loop():
        while not stop.wait(every):
            for name, fn, batch in (('messenger', deliver, BATCH), ('push', push.deliver, push.BATCH)):
                try:
                    while fn(app) >= batch:
                        pass
                except Exception:
                    log.exception('%s delivery failed', name)
    th = threading.Thread(target=loop, name='messenger-delivery', daemon=True)
    th.start()
    app.state.messenger_stop = stop
    return th


def org_status(conn, user_ids):
    """Для организатора: у кого подключён Telegram / ВКонтакте."""
    if not user_ids:
        return {}
    out = {}
    for r in conn.execute('''SELECT user_id, provider, coalesce((metadata->>'blocked')::boolean,false) AS blocked FROM external_identities
WHERE user_id = ANY(%s) AND provider IN ('telegram','vk')''', (list(user_ids),)):
        out.setdefault(str(r['user_id']), {})[r['provider']] = 'blocked' if r['blocked'] else 'on'
    return out


def counts(conn, user_ids):
    st = org_status(conn, user_ids)
    return {'telegram': sum(1 for v in st.values() if v.get('telegram') == 'on'),
            'vk': sum(1 for v in st.values() if v.get('vk') == 'on'),
            'any': sum(1 for v in st.values() if 'on' in v.values())}



# ---------- организатор: рассылка участницам Игры ----------

from pydantic import BaseModel, ConfigDict, Field   # noqa: E402

from kabinet.participation import rules as R          # noqa: E402
from kabinet.org.common import WRITE, locked_admin, org_user, problem   # noqa: E402

org = APIRouter(prefix='/api/org', tags=['organizer'])
AUDIENCE = {'active': (R.IN, R.OUTSIDE, R.OUT_PENDING), 'in': (R.IN,), 'outside': (R.OUTSIDE, R.OUT_PENDING),
            'all': (R.IN, R.OUTSIDE, R.OUT_PENDING, R.ELIMINATED, R.COMPLETED)}


class BroadcastIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=1500)
    audience: str = Field(default='active', pattern='^(active|in|outside|all)$')
    league: str | None = Field(default=None, pattern='^(gold|silver|bronze|none)$')
    link: str = Field(default='game', pattern='^(game|none)$')
    send: bool = False                  # false — только посчитать, кому уйдёт


def audience(conn, event_id, body):
    rows = conn.execute('''SELECT * FROM event_participants WHERE event_id=%s''', (event_id,)).fetchall()
    out = []
    for ep in rows:
        if R.participation_mode(ep) not in AUDIENCE[body.audience]:
            continue
        lg = ep['entry_league'] or 'none'
        if body.league and lg != body.league:
            continue
        out.append(ep['user_id'])
    return out


@org.post('/events/{event_id}/broadcast', dependencies=WRITE)
def broadcast(event_id: str, body: BroadcastIn, request: Request, user=Depends(org_user)):
    """Сообщение участницам Игры: в колокольчик кабинета и, у кого подключено, в Telegram / ВКонтакте.
    Сначала send=false — сколько человек получат; затем send=true. Повторная отправка — новая рассылка."""
    title, text = body.title.strip(), body.text.strip()
    if not title or not text:
        raise problem('empty')
    now = request.app.state.clock()
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = conn.execute('SELECT * FROM events WHERE id=%s', (event_id,)).fetchone()
        if e is None:
            raise HTTPException(404, 'Not found')
        uids = audience(conn, e['id'], body)
        info = {'recipients': len(uids), 'messengers': counts(conn, uids), 'channels': enabled(request.app.state.settings)}
        if not body.send:
            return info
        if not uids:
            raise problem('no_recipients', 409)
        bid = secrets.token_hex(8)
        payload = {'title': title, 'text': text, 'route': 'game' if body.link == 'game' else None, 'event_id': str(e['id'])}
        for uid in uids:
            G.notify(conn, uid, 'broadcast', f'broadcast:{bid}:{uid}', payload, e['id'])
        G.audit(conn, user['id'], 'event', e['id'], 'broadcast_sent', {'id': bid, 'title': title, 'audience': body.audience,
                                                                       'league': body.league, 'recipients': len(uids)})
        return info | {'sent': True, 'id': bid, 'at': iso(now)}
