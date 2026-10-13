"""Платный аудиоразбор работы от судьи (решение 13.10): проверка спроса в Игре 01.

Заказ — формой на сайте (без входа: участницы Игры 01 ещё в боте). Цена и имя судьи — настройки кабинета
(одна работа 300 ₽, все работы Игры 700 ₽, судья — Милена). Оплата — по ссылке, которую организатор присылает
вручную; затем организатор отмечает «оплачено», привязывает заказ к человеку в кабинете и загружает аудио
(и, если есть, текст разбора). Участница слушает разбор в кабинете («Мои разборы»), приходит уведомление.

Статусы: new → payment_sent → paid → done; cancelled — из любого, кроме done.
Аудио — в папке фото кабинета (audio/<sha256>.<ext>), отдаётся только хозяйке заказа и организатору.
"""
import hashlib
import os
import tempfile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.auth.routes import client_ip, service
from kabinet.org.common import WRITE, audit, db, iso, locked_admin, notify, now_of, org_user, person_name, problem
from kabinet.org.games import clean_text
from kabinet.web.routes import browser_user, same_origin

public = APIRouter(prefix='/api/public', tags=['public'])
org = APIRouter(prefix='/api/org', tags=['organizer'])
mine = APIRouter(prefix='/api', tags=['participant'])

AUDIO_TYPES = {'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a', 'audio/aac': 'aac', 'audio/ogg': 'ogg',
               'audio/opus': 'opus', 'audio/webm': 'webm', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/wave': 'wav'}
AUDIO_MAX_MB = 40
NEXT = {'new': ('payment_sent', 'paid', 'cancelled'), 'payment_sent': ('paid', 'cancelled', 'new'),
        'paid': ('cancelled',), 'done': (), 'cancelled': ('new',)}


def offer(conn, settings):
    """Что можно заказать сейчас: Игра, которая идёт, и её туры с опубликованными итогами."""
    game = conn.execute('''SELECT id, title FROM events WHERE status='active' AND event_type='ranked_game'
ORDER BY starts_at NULLS LAST LIMIT 1''').fetchone()
    rounds = conn.execute("SELECT round_no, title FROM rounds WHERE event_id=%s AND status='published' ORDER BY round_no",
                          (game['id'],)).fetchall() if game else []
    return {'enabled': settings.review_enabled and game is not None, 'reviewer': settings.review_reviewer,
            'price_one': settings.review_price_one, 'price_all': settings.review_price_all, 'days': settings.review_days,
            'game': game['title'] if game else None, 'rounds': [{'no': r['round_no'], 'title': r['title']} for r in rounds]}


# ---------- сайт: заказ без входа ----------

@public.get('/review-offer')
def review_offer(request: Request):
    with db(request).transaction() as conn:
        return offer(conn, request.app.state.settings)


class OrderIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=120)
    contact: str = Field(min_length=3, max_length=200)
    scope: Literal['one', 'all']
    round_no: int | None = Field(default=None, ge=1, le=30)
    comment: str | None = Field(default=None, max_length=1000)
    accept_terms: bool = False
    website: str | None = Field(default=None, max_length=200)   # ловушка для ботов

    @field_validator('name', 'contact')
    @classmethod
    def required(cls, value):
        return clean_text(value, required=True)

    @field_validator('comment')
    @classmethod
    def optional(cls, value):
        return clean_text(value)


@public.post('/review-order', status_code=201, dependencies=[Depends(same_origin)])
def order(body: OrderIn, request: Request, auth=Depends(service)):
    auth.throttle('review', client_ip(request), limit=5, window=3600)
    if body.website:
        return {'order_no': 0, 'price': 0}
    if not body.accept_terms:
        raise problem('terms_required')
    settings = request.app.state.settings
    with db(request).transaction() as conn:
        o = offer(conn, settings)
        if not o['enabled']:
            raise problem('not_available', 409)
        if body.scope == 'one':
            if body.round_no not in {r['no'] for r in o['rounds']}:
                raise problem('round_not_published')
            price = settings.review_price_one
        else:
            price = settings.review_price_all
        recent = conn.execute("SELECT count(*) AS n FROM review_orders WHERE created_at > now() - interval '1 hour'").fetchone()['n']
        if recent >= 200:
            raise HTTPException(429, 'Too many requests')
        row = conn.execute('''INSERT INTO review_orders(name,contact,game_title,scope,round_no,comment,price_rub,reviewer,terms_accepted_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING order_no''',
                           (body.name, body.contact, o['game'], body.scope, body.round_no if body.scope == 'one' else None,
                            body.comment, price, settings.review_reviewer, now_of(request))).fetchone()
    return {'order_no': row['order_no'], 'price': price}


# ---------- организатор ----------

def order_view(conn, r, full=False):
    person = None
    if r['user_id']:
        u = conn.execute('SELECT id, full_name, display_name, email FROM users WHERE id=%s', (r['user_id'],)).fetchone()
        person = u and {'id': str(u['id']), 'name': person_name(u), 'email': u['email']}
    out = {'no': r['order_no'], 'name': r['name'], 'contact': r['contact'], 'game': r['game_title'], 'scope': r['scope'],
           'round_no': r['round_no'], 'price': r['price_rub'], 'reviewer': r['reviewer'], 'status': r['status'],
           'person': person, 'has_audio': bool(r['audio_key']), 'has_text': bool(r['review_text']),
           'created_at': iso(r['created_at']), 'paid_at': iso(r['paid_at']), 'done_at': iso(r['done_at'])}
    if full:
        out.update({'comment': r['comment'], 'org_note': r['org_note'], 'review_text': r['review_text'],
                    'next': list(NEXT[r['status']]), 'audio_bytes': r['audio_bytes']})
    return out


def load(conn, no, lock=False):
    r = conn.execute('SELECT * FROM review_orders WHERE order_no=%s' + (' FOR UPDATE' if lock else ''), (no,)).fetchone()
    if not r:
        raise HTTPException(404, 'Not found')
    return r


@org.get('/reviews')
def reviews(request: Request, status: str = Query('open', pattern='^(open|done|cancelled|all)$'), user=Depends(org_user)):
    where = {'open': "status IN ('new','payment_sent','paid')", 'done': "status='done'", 'cancelled': "status='cancelled'",
             'all': 'TRUE'}[status]
    with db(request).transaction() as conn:
        rows = conn.execute(f'SELECT * FROM review_orders WHERE {where} ORDER BY created_at DESC LIMIT 500').fetchall()
        counts = {r['status']: r['n'] for r in conn.execute('SELECT status, count(*) AS n FROM review_orders GROUP BY status')}
        return {'items': [order_view(conn, r) for r in rows], 'counts': counts,
                'offer': offer(conn, request.app.state.settings)}


@org.get('/reviews/{no}')
def review(no: int, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return order_view(conn, load(conn, no), full=True)


class OrderChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['new', 'payment_sent', 'paid', 'cancelled'] | None = None
    org_note: str | None = Field(default=None, max_length=2000)
    review_text: str | None = Field(default=None, max_length=20000)
    user_id: UUID | None = None
    unlink: bool = False


@org.patch('/reviews/{no}', dependencies=WRITE)
def change(no: int, body: OrderChange, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load(conn, no, lock=True)
        sets, args = [], []
        if body.status and body.status != r['status']:
            if body.status not in NEXT[r['status']]:
                raise problem('wrong_status', 409)
            sets += ['status=%s']; args += [body.status]
            if body.status == 'paid':
                sets += ['paid_at=%s']; args += [now]
        if body.user_id:
            if not conn.execute('SELECT 1 FROM users WHERE id=%s AND deleted_at IS NULL', (body.user_id,)).fetchone():
                raise problem('unknown_person')
            sets += ['user_id=%s']; args += [body.user_id]
        elif body.unlink:
            if r['status'] == 'done':
                raise problem('already_done', 409)
            sets += ['user_id=NULL']
        if 'org_note' in body.model_fields_set:
            sets += ['org_note=%s']; args += [clean_text(body.org_note)]
        if 'review_text' in body.model_fields_set:
            sets += ['review_text=%s']; args += [(body.review_text or '').strip() or None]
        if sets:
            conn.execute(f"UPDATE review_orders SET {', '.join(sets)}, updated_at=now() WHERE id=%s", (*args, r['id']))
            audit(conn, user['id'], 'review_order', r['id'], 'review_changed',
                  {k: v for k, v in body.model_dump(mode='json', exclude_unset=True).items() if k != 'review_text'})
        return order_view(conn, load(conn, no), full=True)


@org.post('/reviews/{no}/done', dependencies=WRITE)
def done(no: int, request: Request, user=Depends(org_user)):
    """Разбор готов: участница видит его в кабинете и получает уведомление."""
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load(conn, no, lock=True)
        if r['status'] == 'done':
            return order_view(conn, r, full=True)
        if r['status'] != 'paid':
            raise problem('not_paid', 409)
        if not r['audio_key'] and not r['review_text']:
            raise problem('no_review', 409)
        if not r['user_id']:
            raise problem('no_person', 409)
        conn.execute("UPDATE review_orders SET status='done', done_at=%s, updated_at=now() WHERE id=%s", (now_of(request), r['id']))
        what = 'всех работ Игры' if r['scope'] == 'all' else f"работы тура {r['round_no']}"
        notify(conn, r['user_id'], 'review_ready', f"review:{r['id']}",
               {'title': f"Разбор {what} готов", 'text': f"Разбор от судьи ({r['reviewer']}) — в разделе «Мои разборы».",
                'route': 'reviews'})
        audit(conn, user['id'], 'review_order', r['id'], 'review_done')
        return order_view(conn, load(conn, no), full=True)


def _save_audio(root, data, ext):
    digest = hashlib.sha256(data).hexdigest()
    key = f'audio/{digest[:2]}/{digest}.{ext}'
    target = root / key
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, target)
    return key


@org.post('/reviews/{no}/audio', dependencies=WRITE)
async def upload_audio(no: int, request: Request, user=Depends(org_user)):
    ctype = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
    if ctype not in AUDIO_TYPES:
        raise problem('audio_format', 415)
    limit = AUDIO_MAX_MB * 1024 * 1024
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise problem('too_large', 413)
        chunks.append(chunk)
    data = b''.join(chunks)
    if not data:
        raise problem('empty')
    media = request.app.state.media
    if not await run_in_threadpool(media.free_ok, len(data)):
        raise problem('storage_full', 507)
    key = await run_in_threadpool(_save_audio, media.root, data, AUDIO_TYPES[ctype])

    def write():
        with db(request).transaction() as conn:
            locked_admin(conn, user)
            r = load(conn, no, lock=True)
            if r['status'] in ('done', 'cancelled'):
                raise problem('wrong_status', 409)
            conn.execute('UPDATE review_orders SET audio_key=%s, audio_mime=%s, audio_bytes=%s, updated_at=now() WHERE id=%s',
                         (key, ctype, len(data), r['id']))
            audit(conn, user['id'], 'review_order', r['id'], 'review_audio', {'bytes': len(data)})
            return order_view(conn, load(conn, no), full=True)
    return await run_in_threadpool(write)


def audio_file(request, r):
    if not r['audio_key']:
        raise HTTPException(404, 'Not found')
    path = request.app.state.media.path(r['audio_key'])
    if not path.is_file():
        raise HTTPException(404, 'Not found')
    # FileResponse отвечает и на запросы части файла (Range) — без этого Safari на iPhone аудио не играет
    return FileResponse(path, media_type=r['audio_mime'] or 'audio/mpeg', headers={'Cache-Control': 'private, max-age=86400'})


@org.get('/reviews/{no}/audio')
def org_audio(no: int, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        r = load(conn, no)
    return audio_file(request, r)


# ---------- участница: «Мои разборы» ----------

@mine.get('/reviews')
def my_reviews(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT * FROM review_orders WHERE user_id=%s AND status<>'cancelled' ORDER BY created_at DESC''',
                            (user['id'],)).fetchall()
    return {'items': [{'no': r['order_no'], 'game': r['game_title'], 'scope': r['scope'], 'round_no': r['round_no'],
                       'reviewer': r['reviewer'], 'status': r['status'], 'price': r['price_rub'],
                       'created_at': iso(r['created_at']), 'done_at': iso(r['done_at']),
                       'audio': bool(r['audio_key']) and r['status'] == 'done',
                       'text': r['review_text'] if r['status'] == 'done' else None} for r in rows]}


@mine.get('/reviews/{no}/audio')
def my_audio(no: int, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        r = conn.execute("SELECT * FROM review_orders WHERE order_no=%s AND user_id=%s AND status='done'", (no, user['id'])).fetchone()
    if not r:
        raise HTTPException(404, 'Not found')
    return audio_file(request, r)
