"""Платный аудиоразбор работы от судьи (решения 13.10): проверка спроса.

Заказ открывается ПОСЛЕ окончания Игры (на review_window_days дней) — формой на сайте, без входа. Цена и имя
судьи — настройки кабинета (одна работа 300 ₽, все работы Игры 700 ₽, судья — Милена). Оплата — по счёту: ссылку
присылает организатор и отмечает «оплачено»; привязывает заказ к участнице в кабинете и поручает судье.
Судья видит работы участницы этой Игры, записывает разбор голосом прямо в кабинете и отправляет — разбор сразу
у участницы («Мои разборы»), приходит уведомление. Организатор при необходимости может загрузить файл сам.

Статусы: new → payment_sent → paid → done; cancelled — из любого, кроме done.
Аудио — в папке фото кабинета (audio/<sha256>.<ext>); если на сервере есть ffmpeg, запись переводится в m4a (AAC):
он играет везде, в том числе на iPhone (запись из Chrome на Android приходит в Opus). Отдаётся только хозяйке
заказа, её судье и организатору.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.auth.routes import client_ip, service
from kabinet.org.common import WRITE, audit, db, iso, locked_admin, notify, now_of, org_user, person_name, problem
from kabinet.org.games import clean_text
from kabinet.participation import views as V
from kabinet.web.routes import browser_user, same_origin

public = APIRouter(prefix='/api/public', tags=['public'])
org = APIRouter(prefix='/api/org', tags=['organizer'])
mine = APIRouter(prefix='/api', tags=['participant'])
judge = APIRouter(prefix='/api/judging', tags=['judging'])

AUDIO_TYPES = {'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a', 'audio/aac': 'aac', 'audio/ogg': 'ogg',
               'audio/opus': 'opus', 'audio/webm': 'webm', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/wave': 'wav'}
AUDIO_MAX_MB = 40
NEXT = {'new': ('payment_sent', 'paid', 'cancelled'), 'payment_sent': ('paid', 'cancelled', 'new'),
        'paid': ('cancelled',), 'done': (), 'cancelled': ('new',)}


def offer(conn, settings, now):
    """Что можно заказать сейчас: последняя закончившаяся Игра (в течение окна после конца) и её туры с итогами."""
    game = conn.execute('''SELECT id, title, coalesce(completion_deadline, ends_at) AS ended FROM events
WHERE event_type='ranked_game' AND status<>'draft'
  AND (status IN ('finished','archived') OR coalesce(completion_deadline, ends_at) <= %s)
  AND coalesce(completion_deadline, ends_at, %s) > %s
ORDER BY coalesce(completion_deadline, ends_at) DESC NULLS LAST LIMIT 1''',
                        (now, now, now - timedelta(days=settings.review_window_days))).fetchone()
    rounds = conn.execute("SELECT round_no, title FROM rounds WHERE event_id=%s AND status='published' ORDER BY round_no",
                          (game['id'],)).fetchall() if game else []
    until = (game['ended'] + timedelta(days=settings.review_window_days)) if game and game['ended'] else None
    return {'enabled': settings.review_enabled and game is not None, 'reviewer': settings.review_reviewer,
            'price_one': settings.review_price_one, 'price_all': settings.review_price_all, 'days': settings.review_days,
            'game': game['title'] if game else None, 'game_id': str(game['id']) if game else None, 'until': iso(until),
            'rounds': [{'no': r['round_no'], 'title': r['title']} for r in rounds]}


# ---------- сайт: заказ без входа ----------

@public.get('/review-offer')
def review_offer(request: Request):
    with db(request).transaction() as conn:
        o = offer(conn, request.app.state.settings, now_of(request))
        o.pop('game_id', None)
        return o


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
        o = offer(conn, settings, now_of(request))
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
        row = conn.execute('''INSERT INTO review_orders(name,contact,game_title,event_id,scope,round_no,comment,price_rub,reviewer,
terms_accepted_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING order_no''',
                           (body.name, body.contact, o['game'], o['game_id'], body.scope, body.round_no if body.scope == 'one' else None,
                            body.comment, price, settings.review_reviewer, now_of(request))).fetchone()
    return {'order_no': row['order_no'], 'price': price}


# ---------- организатор ----------

def order_view(conn, r, full=False):
    def who(uid):
        if not uid:
            return None
        u = conn.execute('SELECT id, full_name, display_name, email FROM users WHERE id=%s', (uid,)).fetchone()
        return u and {'id': str(u['id']), 'name': person_name(u), 'email': u['email']}
    person, judge_person = who(r['user_id']), who(r['reviewer_id'])
    out = {'no': r['order_no'], 'name': r['name'], 'contact': r['contact'], 'game': r['game_title'], 'scope': r['scope'],
           'round_no': r['round_no'], 'price': r['price_rub'], 'reviewer': r['reviewer'], 'status': r['status'],
           'person': person, 'judge': judge_person, 'has_audio': bool(r['audio_key']), 'has_text': bool(r['review_text']),
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
                'offer': offer(conn, request.app.state.settings, now_of(request))}


def judges_list(conn):
    rows = conn.execute('''SELECT DISTINCT u.id, u.full_name, u.display_name, u.email FROM users u JOIN user_roles r ON r.user_id=u.id
WHERE r.role IN ('judge','admin') AND u.account_status='active' AND u.deleted_at IS NULL ORDER BY u.full_name''').fetchall()
    return [{'id': str(j['id']), 'name': person_name(j)} for j in rows]


@org.get('/reviews/{no}')
def review(no: int, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return order_view(conn, load(conn, no), full=True) | {'judges': judges_list(conn)}


class OrderChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['new', 'payment_sent', 'paid', 'cancelled'] | None = None
    org_note: str | None = Field(default=None, max_length=2000)
    review_text: str | None = Field(default=None, max_length=20000)
    user_id: UUID | None = None
    unlink: bool = False
    reviewer_id: UUID | None = None


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
        if body.reviewer_id:
            if not conn.execute('''SELECT 1 FROM users u JOIN user_roles r ON r.user_id=u.id WHERE u.id=%s AND r.role IN ('judge','admin')
AND u.account_status='active' AND u.deleted_at IS NULL''', (body.reviewer_id,)).fetchone():
                raise problem('not_a_judge')
            if r['status'] == 'done':
                raise problem('already_done', 409)
            sets += ['reviewer_id=%s']; args += [body.reviewer_id]
        if 'org_note' in body.model_fields_set:
            sets += ['org_note=%s']; args += [clean_text(body.org_note)]
        if 'review_text' in body.model_fields_set:
            sets += ['review_text=%s']; args += [(body.review_text or '').strip() or None]
        if sets:
            conn.execute(f"UPDATE review_orders SET {', '.join(sets)}, updated_at=now() WHERE id=%s", (*args, r['id']))
            audit(conn, user['id'], 'review_order', r['id'], 'review_changed',
                  {k: v for k, v in body.model_dump(mode='json', exclude_unset=True).items() if k != 'review_text'})
        r = load(conn, no)
        if r['status'] == 'paid' and r['reviewer_id'] and r['user_id']:
            # оплачено, участница и судья выбраны — судье задание (один раз на пару заказ+судья)
            notify(conn, r['reviewer_id'], 'review_task', f"review-judge:{r['id']}:{r['reviewer_id']}",
                   {'title': f"Разбор № {r['order_no']}: {what(r)}", 'text': 'Запишите аудиоразбор в разделе «Судейство» → «Разборы».',
                    'route': 'judge_review', 'order_no': r['order_no']})
        return order_view(conn, r, full=True) | {'judges': judges_list(conn)}


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
        deliver(conn, r, user['id'], now_of(request))
        return order_view(conn, load(conn, no), full=True) | {'judges': judges_list(conn)}


def what(r):
    return 'все работы Игры' if r['scope'] == 'all' else f"работа тура {r['round_no']}"


def deliver(conn, r, actor_id, now):
    """Разбор готов: статус done и уведомление участнице."""
    conn.execute("UPDATE review_orders SET status='done', done_at=%s, updated_at=now() WHERE id=%s", (now, r['id']))
    name = 'всех работ Игры' if r['scope'] == 'all' else f"работы тура {r['round_no']}"
    notify(conn, r['user_id'], 'review_ready', f"review:{r['id']}",
           {'title': f"Разбор {name} готов", 'text': f"Разбор от судьи ({r['reviewer']}) — в разделе «Мои разборы».",
            'route': 'reviews'})
    audit(conn, actor_id, 'review_order', r['id'], 'review_done')


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


def _to_m4a(media_root, data):
    """Перевести запись в m4a (AAC, моно 64 кбит/с): играет на любом телефоне. Нет ffmpeg или сбой — None."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return None
    tmpdir = media_root / 'audio' / 'tmp'
    tmpdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmpdir) as d:
        src, dst = os.path.join(d, 'in'), os.path.join(d, 'out.m4a')
        with open(src, 'wb') as f:
            f.write(data)
        try:
            subprocess.run([ffmpeg, '-nostdin', '-loglevel', 'error', '-y', '-i', src, '-vn', '-ac', '1', '-c:a', 'aac', '-b:a', '64k',
                            '-movflags', '+faststart', dst], check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(dst, 'rb') as f:
                out = f.read()
            return out or None
        except (subprocess.SubprocessError, OSError):
            return None


async def receive_audio(request):
    """Принять аудио из тела запроса: проверка типа и размера, перевод в m4a (если можно), сохранение. → (ключ, тип, байт)."""
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
    m4a = await run_in_threadpool(_to_m4a, media.root, data)
    if m4a:
        data, ctype = m4a, 'audio/mp4'
    key = await run_in_threadpool(_save_audio, media.root, data, AUDIO_TYPES[ctype])
    return key, ctype, len(data)


@org.post('/reviews/{no}/audio', dependencies=WRITE)
async def upload_audio(no: int, request: Request, user=Depends(org_user)):
    key, ctype, size = await receive_audio(request)

    def write():
        with db(request).transaction() as conn:
            locked_admin(conn, user)
            r = load(conn, no, lock=True)
            if r['status'] in ('done', 'cancelled'):
                raise problem('wrong_status', 409)
            conn.execute('UPDATE review_orders SET audio_key=%s, audio_mime=%s, audio_bytes=%s, updated_at=now() WHERE id=%s',
                         (key, ctype, size, r['id']))
            audit(conn, user['id'], 'review_order', r['id'], 'review_audio', {'bytes': size})
            return order_view(conn, load(conn, no), full=True) | {'judges': judges_list(conn)}
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


# ---------- судья: записать разбор в кабинете ----------

def judge_user(user=Depends(browser_user)):
    if not ({'judge', 'admin'} & set(user['roles'])):
        raise HTTPException(403, 'judges_only')
    return user


def works(conn, r, root):
    """Работы участницы в этой Игре (последняя сданная версия): для одной работы — только её тур."""
    if not r['user_id'] or not r['event_id']:
        return []
    rows = conn.execute('''SELECT rd.round_no, rd.title AS round_title, a.title AS task, s.latest_version_id AS v,
  (SELECT sv.payload->>'link' FROM submission_versions sv WHERE sv.id=s.latest_version_id) AS link
FROM event_participants ep
JOIN participant_assignments pa ON pa.event_participant_id=ep.id
JOIN assignments a ON a.id=pa.assignment_id
JOIN rounds rd ON rd.id=a.round_id
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
WHERE ep.event_id=%s AND ep.user_id=%s AND s.latest_version_id IS NOT NULL AND (%s::int IS NULL OR rd.round_no=%s::int)
ORDER BY rd.round_no''', (r['event_id'], r['user_id'], r['round_no'], r['round_no'])).fetchall()
    out = []
    for w in rows:
        photos = conn.execute('''SELECT m.* FROM submission_version_media svm JOIN media_files m ON m.id=svm.media_file_id
WHERE svm.submission_version_id=%s AND svm.field_key='photo' AND m.deleted_at IS NULL ORDER BY svm.sort_order''', (w['v'],)).fetchall()
        out.append({'round_no': w['round_no'], 'title': w['round_title'], 'task': w['task'], 'link': w['link'],
                    'photos': [V.photo_view(m, root) for m in photos]})
    return out


def judge_view(conn, r, root):
    return {'no': r['order_no'], 'name': r['name'], 'game': r['game_title'], 'scope': r['scope'], 'round_no': r['round_no'],
            'comment': r['comment'], 'status': r['status'], 'has_audio': bool(r['audio_key']), 'audio_bytes': r['audio_bytes'],
            'review_text': r['review_text'], 'done_at': iso(r['done_at']), 'works': works(conn, r, root)}


def my_task(conn, no, user, lock=False):
    r = conn.execute("SELECT * FROM review_orders WHERE order_no=%s AND reviewer_id=%s AND status IN ('paid','done')"
                     + (' FOR UPDATE' if lock else ''), (no, user['id'])).fetchone()
    if not r:
        raise HTTPException(404, 'Not found')
    return r


@judge.get('/reviews')
def judge_reviews(request: Request, user=Depends(judge_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT * FROM review_orders WHERE reviewer_id=%s AND status IN ('paid','done')
ORDER BY (status='paid') DESC, paid_at DESC NULLS LAST LIMIT 200''', (user['id'],)).fetchall()
    return {'items': [{'no': r['order_no'], 'name': r['name'], 'game': r['game_title'], 'scope': r['scope'], 'round_no': r['round_no'],
                       'status': r['status'], 'paid_at': iso(r['paid_at']), 'done_at': iso(r['done_at'])} for r in rows]}


@judge.get('/reviews/{no}')
def judge_review(no: int, request: Request, user=Depends(judge_user)):
    with db(request).transaction() as conn:
        return judge_view(conn, my_task(conn, no, user), request.app.state.settings.root_path)


@judge.post('/reviews/{no}/audio', dependencies=WRITE)
async def judge_audio_upload(no: int, request: Request, user=Depends(judge_user)):
    with db(request).transaction() as conn:
        if my_task(conn, no, user)['status'] != 'paid':
            raise problem('wrong_status', 409)
    key, ctype, size = await receive_audio(request)

    def write():
        with db(request).transaction() as conn:
            r = my_task(conn, no, user, lock=True)
            if r['status'] != 'paid':
                raise problem('wrong_status', 409)
            conn.execute('UPDATE review_orders SET audio_key=%s, audio_mime=%s, audio_bytes=%s, updated_at=now() WHERE id=%s',
                         (key, ctype, size, r['id']))
            audit(conn, user['id'], 'review_order', r['id'], 'review_audio', {'bytes': size, 'by': 'judge'})
            return judge_view(conn, my_task(conn, no, user), request.app.state.settings.root_path)
    return await run_in_threadpool(write)


class SendIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str | None = Field(default=None, max_length=20000)


@judge.post('/reviews/{no}/send', dependencies=WRITE)
def judge_send(no: int, body: SendIn, request: Request, user=Depends(judge_user)):
    """Отправить разбор участнице: он сразу появляется у неё в «Моих разборах»."""
    with db(request).transaction() as conn:
        r = my_task(conn, no, user, lock=True)
        if r['status'] == 'done':
            return judge_view(conn, r, request.app.state.settings.root_path)
        text = (body.text or '').strip() or None
        if text is not None:
            conn.execute('UPDATE review_orders SET review_text=%s WHERE id=%s', (text, r['id']))
        if not r['audio_key'] and not (text or r['review_text']):
            raise problem('no_review', 409)
        deliver(conn, r, user['id'], now_of(request))
        return judge_view(conn, my_task(conn, no, user), request.app.state.settings.root_path)


@judge.get('/reviews/{no}/audio')
def judge_audio(no: int, request: Request, user=Depends(judge_user)):
    with db(request).transaction() as conn:
        r = my_task(conn, no, user)
    return audio_file(request, r)
