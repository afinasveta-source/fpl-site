"""Кабинет организатора: обращения участниц в поддержку и анонимные пожелания с сайта.

Обращение: участница пишет — статус «ждёт организатора» (open / waiting_admin); организатор отвечает —
«ждём участницу» (waiting_user) или сразу «закрыто» (closed). Участница получает уведомление в кабинете.

Пожелания: форма на сайте без входа. Хранятся текст, время и (если человек сам указал) контакт.
IP-адрес не записывается: он только ограничивает частоту отправки (в таблице лимитов — отпечаток, не адрес).
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.auth.routes import client_ip, service
from kabinet.participation.account import context_label
from kabinet.web.routes import same_origin
from .common import WRITE, audit, db, iso, locked_admin, notify, now_of, org_user, person_name, problem
from .games import clean_text

router = APIRouter(prefix='/api/org', tags=['organizer'])
public = APIRouter(prefix='/api/public', tags=['public'])
STATUS_FILTER = {'waiting': ('open', 'waiting_admin'), 'answered': ('waiting_user',), 'closed': ('closed',)}


def thread_row(conn, t):
    last = conn.execute('''SELECT body, author_role, created_at FROM support_messages WHERE support_thread_id=%s
ORDER BY created_at DESC, id DESC LIMIT 1''', (t['id'],)).fetchone()
    return {'no': t['thread_no'], 'subject': t['subject'], 'status': t['status'], 'context': context_label(conn, t),
            'person': {'id': str(t['user_id']), 'name': person_name(t)}, 'updated_at': iso(t['updated_at']),
            'created_at': iso(t['created_at']),
            'last': {'text': last['body'][:160], 'from': last['author_role'], 'at': iso(last['created_at'])} if last else None}


@router.get('/support')
def inbox(request: Request, status: str = Query('waiting', pattern='^(waiting|answered|closed|all)$'),
          q: str = Query('', max_length=100), user=Depends(org_user)):
    term = q.strip()
    with db(request).transaction() as conn:
        statuses = STATUS_FILTER.get(status, ('open', 'waiting_admin', 'waiting_user', 'closed'))
        rows = conn.execute('''SELECT t.*, u.full_name, u.display_name, u.email FROM support_threads t JOIN users u ON u.id=t.user_id
WHERE t.status = ANY(%(st)s) AND (%(q)s = '' OR t.subject ILIKE %(like)s OR u.full_name ILIKE %(like)s
  OR u.display_name ILIKE %(like)s OR u.email ILIKE %(like)s OR t.thread_no::text = %(q)s)
ORDER BY t.updated_at DESC LIMIT 200''', {'st': list(statuses), 'q': term, 'like': f'%{term}%'}).fetchall()
        counts = {k: conn.execute('SELECT count(*) AS n FROM support_threads WHERE status = ANY(%s)', (list(v),)).fetchone()['n']
                  for k, v in STATUS_FILTER.items()}
        return {'threads': [thread_row(conn, t) for t in rows], 'counts': counts}


def load_thread(conn, no, lock=False):
    t = conn.execute('''SELECT t.*, u.full_name, u.display_name, u.email FROM support_threads t JOIN users u ON u.id=t.user_id
WHERE t.thread_no=%s''' + (' FOR UPDATE OF t' if lock else ''), (no,)).fetchone()
    if not t:
        raise HTTPException(404, 'Thread not found')
    return t


def thread_detail(conn, t):
    msgs = conn.execute('''SELECT m.*, u.full_name, u.display_name, u.email FROM support_messages m
LEFT JOIN users u ON u.id=m.author_user_id WHERE m.support_thread_id=%s ORDER BY m.created_at, m.id''', (t['id'],)).fetchall()
    return thread_row(conn, t) | {
        'event_id': str(t['event_id']) if t['event_id'] else None,
        'messages': [{'from': m['author_role'], 'author': person_name(m) if m['author_user_id'] else 'Лига',
                      'body': m['body'], 'at': iso(m['created_at'])} for m in msgs]}


@router.get('/support/{no}')
def thread(no: int, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return thread_detail(conn, load_thread(conn, no))


class ReplyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=4000)
    status: Literal['waiting_user', 'closed'] = 'waiting_user'

    @field_validator('body')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)


@router.post('/support/{no}/reply', dependencies=WRITE)
def reply(no: int, body: ReplyIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        t = load_thread(conn, no, lock=True)
        m = conn.execute('''INSERT INTO support_messages(support_thread_id,author_user_id,author_role,body,delivery_channel,delivery_status)
VALUES (%s,%s,'admin',%s,'in_app','sent') RETURNING id''', (t['id'], user['id'], body.body)).fetchone()
        conn.execute('UPDATE support_threads SET status=%s WHERE id=%s', (body.status, t['id']))
        notify(conn, t['user_id'], 'support', f"support:{m['id']}",
               {'title': f"Ответ на обращение №{no}", 'text': body.body[:120], 'route': 'support', 'thread_no': no},
               t['event_id'], t['round_id'])
        audit(conn, user['id'], 'support_thread', t['id'], 'support_replied', {'status': body.status})
        return thread_detail(conn, load_thread(conn, no))


class StatusIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['waiting_admin', 'waiting_user', 'closed']


@router.post('/support/{no}/status', dependencies=WRITE)
def thread_status(no: int, body: StatusIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        t = load_thread(conn, no, lock=True)
        conn.execute('UPDATE support_threads SET status=%s WHERE id=%s', (body.status, t['id']))
        audit(conn, user['id'], 'support_thread', t['id'], 'support_status', {'status': body.status})
        return thread_detail(conn, load_thread(conn, no))


# ---------- Пожелания с сайта ----------

class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=2000)
    contact: str | None = Field(default=None, max_length=200)
    page: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=200)   # ловушка для ботов: людям поле не видно

    @field_validator('text')
    @classmethod
    def trim_text(cls, value):
        return clean_text(value, required=True)

    @field_validator('contact', 'page')
    @classmethod
    def trim(cls, value):
        return clean_text(value)


FEEDBACK_PER_HOUR = 300   # общий предел на случай потока мусора: дальше — «попробуйте позже»


@public.post('/feedback', status_code=201, dependencies=[Depends(same_origin)])
def send_feedback(body: FeedbackIn, request: Request, auth=Depends(service)):
    auth.throttle('feedback', client_ip(request), limit=5, window=3600)   # 5 сообщений в час с одного адреса
    if body.website:
        return {'ok': True}   # бот заполнил скрытое поле — делаем вид, что приняли
    with db(request).transaction() as conn:
        recent = conn.execute("SELECT count(*) AS n FROM feedback_messages WHERE created_at > now() - interval '1 hour'").fetchone()['n']
        if recent >= FEEDBACK_PER_HOUR:
            raise HTTPException(429, 'Too many requests')
        conn.execute('INSERT INTO feedback_messages(body,contact,page) VALUES (%s,%s,%s)', (body.text, body.contact, body.page))
    return {'ok': True}


def feedback_view(f):
    return {'id': str(f['id']), 'text': f['body'], 'contact': f['contact'], 'page': f['page'], 'status': f['status'],
            'created_at': iso(f['created_at']), 'read_at': iso(f['read_at'])}


@router.get('/feedback')
def feedback(request: Request, status: str = Query('inbox', pattern='^(inbox|new|archived|all)$'), user=Depends(org_user)):
    where = {'inbox': "status IN ('new','read')", 'new': "status='new'", 'archived': "status='archived'", 'all': 'TRUE'}[status]
    with db(request).transaction() as conn:
        rows = conn.execute(f'SELECT * FROM feedback_messages WHERE {where} ORDER BY created_at DESC LIMIT 300').fetchall()
        counts = {r['status']: r['n'] for r in conn.execute('SELECT status, count(*) AS n FROM feedback_messages GROUP BY status')}
    return {'items': [feedback_view(f) for f in rows], 'counts': counts}


class FeedbackStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['new', 'read', 'archived']


@router.post('/feedback/{item_id}', dependencies=WRITE)
def mark_feedback(item_id: UUID, body: FeedbackStatus, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        f = conn.execute('''UPDATE feedback_messages SET status=%s,
read_at = CASE WHEN %s='new' THEN NULL ELSE coalesce(read_at, now()) END,
read_by = CASE WHEN %s='new' THEN NULL ELSE coalesce(read_by, %s) END WHERE id=%s RETURNING *''',
                         (body.status, body.status, body.status, user['id'], item_id)).fetchone()
        if not f:
            raise HTTPException(404, 'Not found')
        return feedback_view(f)
