"""Кабинет организатора: юридические документы и их редакции.

Текст опубликованной редакции не меняется (это защищено в базе); исправление — новая редакция.
Новая редакция выходит сразу или в выбранную дату; предыдущая действует до этого момента.
Запланированную (ещё не вышедшую) редакцию можно отменить. Новые Правила участницы принимают в кабинете:
до этого сдача и замена работ закрыты (participation/rules.submission_window).
"""
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .common import WRITE, audit, db, iso, locked_admin, notify, now_of, org_user, problem
from .games import clean_text

router = APIRouter(prefix='/api/org', tags=['organizer'])
KINDS = ('rules', 'publication', 'personal_data', 'privacy_policy')
REQUIRED = ('rules', 'publication', 'personal_data')


def doc_state(d, now):
    if d['superseded_at'] is not None and d['superseded_at'] <= d['published_at']:
        return 'cancelled'
    if d['published_at'] > now:
        return 'scheduled'
    if d['superseded_at'] is not None and d['superseded_at'] <= now:
        return 'old'
    return 'current'


def doc_view(d, now, accepted=None, body=False):
    out = {'id': str(d['id']), 'type': d['doc_type'], 'version': d['version'], 'title': d['title'],
           'published_at': iso(d['published_at']), 'superseded_at': iso(d['superseded_at']), 'state': doc_state(d, now)}
    if accepted is not None:
        out['accepted'] = accepted
    if body:
        out['body'] = d['body']
    return out


def accepted_counts(conn, ids):
    if not ids:
        return {}
    rows = conn.execute('''SELECT legal_document_id AS id, count(DISTINCT user_id) AS n FROM (
  SELECT DISTINCT ON (user_id, legal_document_id) user_id, legal_document_id, status FROM consents
  WHERE legal_document_id = ANY(%s) AND user_id IS NOT NULL ORDER BY user_id, legal_document_id, recorded_at DESC, id DESC) x
WHERE status='accepted' GROUP BY legal_document_id''', (ids,)).fetchall()
    return {r['id']: r['n'] for r in rows}


@router.get('/documents')
def documents(request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        rows = conn.execute('SELECT * FROM legal_documents ORDER BY doc_type, published_at DESC').fetchall()
        counts = accepted_counts(conn, [d['id'] for d in rows])
    out = {}
    for kind in KINDS + tuple(sorted({d['doc_type'] for d in rows} - set(KINDS))):
        items = [doc_view(d, now, counts.get(d['id'], 0)) for d in rows if d['doc_type'] == kind]
        out[kind] = {'current': next((x for x in items if x['state'] == 'current'), None),
                     'scheduled': next((x for x in items if x['state'] == 'scheduled'), None),
                     'history': items, 'required': kind in REQUIRED}
    return {'documents': out}


@router.get('/documents/{doc_id}')
def document(doc_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        d = conn.execute('SELECT * FROM legal_documents WHERE id=%s', (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, 'Document not found')
        return doc_view(d, now, accepted_counts(conn, [d['id']]).get(d['id'], 0), body=True)


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_type: Literal['rules', 'publication', 'personal_data', 'privacy_policy']
    version: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=20, max_length=200000)
    publish_at: AwareDatetime | None = None

    @field_validator('version', 'title')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)

    @field_validator('body')
    @classmethod
    def normalize(cls, value):
        value = value.replace('\r\n', '\n').strip()
        if len(value) < 20:
            raise ValueError('Body is too short')
        return value


def notify_due_rules(conn, now):
    """Правила, вышедшие по расписанию (за последнюю неделю): сообщение тем, кто их ещё не принял. Повтор ничего
    не дублирует (ключ уведомления). Вызывает сверка fpl-kabinet-sync каждые 10 минут."""
    from kabinet.participation import game as G
    from datetime import timedelta
    d = G.rules_document(conn, now)
    if d is None or d['published_at'] < now - timedelta(days=7):
        return 0
    return notify_rules(conn, d, now)


def notify_rules(conn, d, now):
    """Новые Правила вышли: всем, кто участвует в незавершённых Играх, — сообщение в кабинете."""
    users = conn.execute('''SELECT DISTINCT p.user_id FROM event_participants p JOIN events e ON e.id=p.event_id
WHERE e.status IN ('registration','active') AND p.registration_status IN ('participating','pre_registered','payment_pending')
AND NOT EXISTS (SELECT 1 FROM consents c WHERE c.user_id=p.user_id AND c.legal_document_id=%s AND c.status='accepted')''',
                         (d['id'],)).fetchall()
    for u in users:
        notify(conn, u['user_id'], 'rules', f"rules:{d['id']}:{u['user_id']}",
               {'title': f"Новая редакция Правил — {d['version']}",
                'text': 'Примите её в кабинете: до этого сдача и замена работ закрыты.',
                'route': 'document', 'document_id': str(d['id'])})
    return len(users)


@router.post('/documents', status_code=201, dependencies=WRITE)
def publish(body: DocumentIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    at = body.publish_at or now
    if at < now:
        raise problem('publish_in_past')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        conn.execute('SELECT pg_advisory_xact_lock(712436903)')  # одна публикация документов за раз
        if conn.execute('SELECT 1 FROM legal_documents WHERE doc_type=%s AND version=%s', (body.doc_type, body.version)).fetchone():
            raise problem('version_taken', 409)
        future = [d for d in conn.execute('''SELECT * FROM legal_documents WHERE doc_type=%s AND published_at > %s''',
                                          (body.doc_type, now)) if doc_state(d, now) == 'scheduled']
        if future:
            raise problem('scheduled_exists', 409)
        # Действующая к моменту выхода редакция действует до него.
        conn.execute('''UPDATE legal_documents SET superseded_at=%s WHERE doc_type=%s AND published_at <= %s
AND (superseded_at IS NULL OR superseded_at > %s)''', (at, body.doc_type, at, at))
        d = conn.execute('''INSERT INTO legal_documents(doc_type,version,title,body,body_sha256,published_at)
VALUES (%s,%s,%s,%s,%s,%s) RETURNING *''', (body.doc_type, body.version, body.title, body.body,
                                            hashlib.sha256(body.body.encode()).hexdigest(), at)).fetchone()
        notified = notify_rules(conn, d, now) if body.doc_type == 'rules' and at <= now else 0
        audit(conn, user['id'], 'legal_document', d['id'], 'document_published',
              {'type': body.doc_type, 'version': body.version, 'at': iso(at), 'notified': notified})
        return doc_view(d, now, 0, body=True) | {'notified': notified}


@router.post('/documents/{doc_id}/cancel', dependencies=WRITE)
def cancel(doc_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        conn.execute('SELECT pg_advisory_xact_lock(712436903)')
        d = conn.execute('SELECT * FROM legal_documents WHERE id=%s FOR UPDATE', (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, 'Document not found')
        if doc_state(d, now) != 'scheduled':
            raise problem('not_scheduled', 409)
        conn.execute('UPDATE legal_documents SET superseded_at=published_at WHERE id=%s', (doc_id,))
        # Предыдущая редакция снова действует без срока окончания.
        conn.execute('''UPDATE legal_documents SET superseded_at=NULL WHERE doc_type=%s AND id<>%s AND superseded_at=%s
AND published_at < %s''', (d['doc_type'], doc_id, d['published_at'], d['published_at']))
        audit(conn, user['id'], 'legal_document', doc_id, 'document_cancelled', {'version': d['version']})
        d = conn.execute('SELECT * FROM legal_documents WHERE id=%s', (doc_id,)).fetchone()
        return doc_view(d, now, 0, body=True)
