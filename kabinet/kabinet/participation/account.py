"""API кабинета участника: главная, уведомления, поддержка, согласия, публичность, каналы уведомлений."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kabinet.auth.routes import client_ip, service
from kabinet.web.routes import browser_user, same_origin
from . import game as G
from .views import iso

router = APIRouter(prefix='/api', tags=['participant'])


def db(request):
    return request.app.state.db


def now_of(request):
    return request.app.state.clock()


def notification_view(n):
    p = n['payload'] or {}
    return {'id': str(n['id']), 'type': n['notification_type'], 'title': p.get('title') or n['notification_type'],
            'text': p.get('text'), 'route': p.get('route'),
            'params': {k: v for k, v in p.items() if k.endswith('_id') or k in ('thread_no',)},
            'created_at': iso(n['created_at']), 'read': n['status'] == 'read'}


# ---------- Главная ----------

@router.get('/home')
def home(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        unread = conn.execute("SELECT count(*) AS n FROM notifications WHERE user_id=%s AND channel='in_app' AND status<>'read'",
                              (user['id'],)).fetchone()['n']
        latest = conn.execute('''SELECT * FROM notifications WHERE user_id=%s AND channel='in_app' AND status<>'read'
ORDER BY created_at DESC LIMIT 1''', (user['id'],)).fetchone()
        doc = G.rules_document(conn, now_of(request))
        rules = None
        if doc is not None:
            ok = G.accepted(conn, user['id'], doc['id'])
            # Карточку «Правила обновились» видят только участники, уже принимавшие Правила раньше.
            before = conn.execute("SELECT 1 FROM consents WHERE user_id=%s AND consent_type='rules' LIMIT 1", (user['id'],)).fetchone()
            if not ok and before:
                rules = {'id': str(doc['id']), 'version': doc['version'], 'title': doc['title']}
    return {'unread': unread, 'important': notification_view(latest) if latest else None, 'rules_update': rules}


# ---------- Уведомления ----------

@router.get('/notifications')
def notifications(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT * FROM notifications WHERE user_id=%s AND channel='in_app'
ORDER BY created_at DESC, id LIMIT 100''', (user['id'],)).fetchall()
    return {'notifications': [notification_view(n) for n in rows]}


class ReadMark(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ids: list[UUID] = Field(default_factory=list, max_length=200)
    all: bool = False


@router.post('/notifications/read', dependencies=[Depends(same_origin)])
def mark_read(body: ReadMark, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        if body.all:
            n = conn.execute("""UPDATE notifications SET status='read', read_at=now()
WHERE user_id=%s AND channel='in_app' AND status<>'read'""", (user['id'],)).rowcount
        else:
            n = conn.execute("""UPDATE notifications SET status='read', read_at=now()
WHERE user_id=%s AND channel='in_app' AND status<>'read' AND id = ANY(%s)""", (user['id'], body.ids)).rowcount
    return {'marked': n}


# ---------- Поддержка ----------

THREAD_STATUS = {'open': 'waiting_admin', 'waiting_admin': 'waiting_admin', 'waiting_user': 'waiting_user', 'closed': 'closed'}


def context_label(conn, t):
    parts = []
    if t['event_id']:
        e = conn.execute('SELECT title FROM events WHERE id=%s', (t['event_id'],)).fetchone()
        parts.append(e['title'] if e else 'Игра')
    if t['round_id']:
        r = conn.execute('SELECT round_no FROM rounds WHERE id=%s', (t['round_id'],)).fetchone()
        parts.append('Тур %s' % r['round_no'] if r else 'Тур')
    if t['submission_id']:
        parts.append('работа')
    return ' · '.join(parts) or 'Общий вопрос'


def thread_view(conn, t, messages=None):
    out = {'no': t['thread_no'], 'subject': t['subject'], 'status': THREAD_STATUS.get(t['status'], t['status']),
           'context': context_label(conn, t), 'created_at': iso(t['created_at']), 'updated_at': iso(t['updated_at'])}
    if messages is not None:
        out['messages'] = [{'mine': m['author_role'] == 'participant', 'author': 'Вы' if m['author_role'] == 'participant'
                            else ('Организатор' if m['author_role'] == 'admin' else 'Лига'),
                            'body': m['body'], 'at': iso(m['created_at'])} for m in messages]
    return out


@router.get('/support')
def support(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('SELECT * FROM support_threads WHERE user_id=%s ORDER BY updated_at DESC LIMIT 100',
                            (user['id'],)).fetchall()
        return {'threads': [thread_view(conn, t) for t in rows]}


class NewThread(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    event_id: UUID | None = None
    round_no: int | None = Field(default=None, ge=1, le=99)
    assignment_id: UUID | None = None

    @field_validator('subject', 'body')
    @classmethod
    def not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Required')
        return value

    @model_validator(mode='after')
    def context(self):
        if (self.round_no is not None or self.assignment_id is not None) and self.event_id is None:
            raise ValueError('Round or work needs a Game')
        return self


@router.post('/support', status_code=201, dependencies=[Depends(same_origin)])
def new_thread(body: NewThread, request: Request, user=Depends(browser_user), auth=Depends(service)):
    auth.throttle('support', client_ip(request), str(user['id']), limit=10, by_ip=False)
    with db(request).transaction() as conn:
        round_id = submission_id = None
        if body.event_id is not None:
            if not conn.execute("SELECT 1 FROM events WHERE id=%s AND status<>'draft'", (body.event_id,)).fetchone():
                raise HTTPException(404, 'Game not found')
        if body.round_no is not None:
            r = conn.execute("SELECT id FROM rounds WHERE event_id=%s AND round_no=%s AND status<>'draft'",
                             (body.event_id, body.round_no)).fetchone()
            if not r:
                raise HTTPException(404, 'Round not found')
            round_id = r['id']
        if body.assignment_id is not None:
            # Обращение о работе — только о своей работе.
            s = conn.execute('''SELECT s.id, a.round_id FROM submissions s
JOIN participant_assignments pa ON pa.id = s.participant_assignment_id
JOIN assignments a ON a.id = pa.assignment_id
JOIN event_participants p ON p.id = s.event_participant_id
WHERE pa.assignment_id=%s AND p.user_id=%s AND p.event_id=%s AND pa.active''',
                             (body.assignment_id, user['id'], body.event_id)).fetchone()
            if s:
                submission_id, round_id = s['id'], s['round_id']
        t = conn.execute('''INSERT INTO support_threads(user_id,event_id,round_id,submission_id,status,subject)
VALUES (%s,%s,%s,%s,'waiting_admin',%s) RETURNING *''',
                         (user['id'], body.event_id, round_id, submission_id, body.subject)).fetchone()
        conn.execute('''INSERT INTO support_messages(support_thread_id,author_user_id,author_role,body,delivery_channel,delivery_status)
VALUES (%s,%s,'participant',%s,'in_app','not_required')''', (t['id'], user['id'], body.body))
        G.audit(conn, user['id'], 'support_thread', t['id'], 'support_opened')
        msgs = conn.execute('SELECT * FROM support_messages WHERE support_thread_id=%s ORDER BY created_at, id', (t['id'],)).fetchall()
        return thread_view(conn, t, msgs)


def own_thread(conn, no, user_id, lock=False):
    t = conn.execute('SELECT * FROM support_threads WHERE thread_no=%s AND user_id=%s' + (' FOR UPDATE' if lock else ''),
                     (no, user_id)).fetchone()
    if not t:
        raise HTTPException(404, 'Not found')
    return t


@router.get('/support/{no}')
def thread(no: int, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        t = own_thread(conn, no, user['id'])
        msgs = conn.execute('SELECT * FROM support_messages WHERE support_thread_id=%s ORDER BY created_at, id', (t['id'],)).fetchall()
        return thread_view(conn, t, msgs)


class Reply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=4000)

    @field_validator('body')
    @classmethod
    def not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Required')
        return value


@router.post('/support/{no}/messages', dependencies=[Depends(same_origin)])
def reply(no: int, body: Reply, request: Request, user=Depends(browser_user), auth=Depends(service)):
    auth.throttle('support_reply', client_ip(request), str(user['id']), limit=30, by_ip=False)
    with db(request).transaction() as conn:
        t = own_thread(conn, no, user['id'], lock=True)
        if t['status'] == 'closed':
            raise HTTPException(409, 'closed')
        conn.execute('''INSERT INTO support_messages(support_thread_id,author_user_id,author_role,body,delivery_channel,delivery_status)
VALUES (%s,%s,'participant',%s,'in_app','not_required')''', (t['id'], user['id'], body.body))
        t = conn.execute("UPDATE support_threads SET status='waiting_admin' WHERE id=%s RETURNING *", (t['id'],)).fetchone()
        msgs = conn.execute('SELECT * FROM support_messages WHERE support_thread_id=%s ORDER BY created_at, id', (t['id'],)).fetchall()
        return thread_view(conn, t, msgs)


# ---------- Документы и согласия ----------

DOC_TYPES = ('rules', 'personal_data', 'publication')


def latest_consent(conn, user_id, kind):
    return conn.execute('''SELECT c.*, d.version AS doc_version FROM consents c LEFT JOIN legal_documents d ON d.id=c.legal_document_id
WHERE c.user_id=%s AND c.consent_type=%s ORDER BY c.recorded_at DESC, c.id DESC LIMIT 1''', (user_id, kind)).fetchone()


@router.get('/consents')
def consents(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        current = []
        for kind in DOC_TYPES:
            doc = G.current_document(conn, kind, now_of(request))
            last = latest_consent(conn, user['id'], kind)
            current.append({'doc_type': kind, 'document': {'id': str(doc['id']), 'version': doc['version'], 'title': doc['title']}
                            if doc else None,
                            'status': last['status'] if last else None, 'version': last['doc_version'] if last else None,
                            'at': iso(last['recorded_at']) if last else None,
                            'current_accepted': bool(doc and G.accepted(conn, user['id'], doc['id']))})
        history = conn.execute('''SELECT c.consent_type, c.status, c.recorded_at, d.version, d.title, e.title AS event_title
FROM consents c LEFT JOIN legal_documents d ON d.id=c.legal_document_id LEFT JOIN events e ON e.id=c.event_id
WHERE c.user_id=%s ORDER BY c.recorded_at DESC, c.id DESC LIMIT 200''', (user['id'],)).fetchall()
    return {'current': current, 'history': [{'type': h['consent_type'], 'status': h['status'], 'at': iso(h['recorded_at']),
                                             'version': h['version'], 'title': h['title'], 'event': h['event_title']}
                                            for h in history]}


@router.get('/documents/{document_id}')
def document(document_id: UUID, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        now = now_of(request)
        d = conn.execute('SELECT * FROM legal_documents WHERE id=%s AND published_at<=%s', (document_id, now)).fetchone()
        if not d:
            raise HTTPException(404, 'Not found')
        return {'id': str(d['id']), 'doc_type': d['doc_type'], 'version': d['version'], 'title': d['title'], 'body': d['body'],
                'published_at': iso(d['published_at']), 'current': d['superseded_at'] is None or d['superseded_at'] > now,
                'accepted': G.accepted(conn, user['id'], d['id'])}


class Accept(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: UUID


def record_consent(conn, user_id, doc, status, button):
    conn.execute('''INSERT INTO consents(user_id,consent_type,accepted,status,document_version,legal_document_id,channel,button_text)
VALUES (%s,%s,%s,%s,%s,%s,'web',%s)''', (user_id, doc['doc_type'], status == 'accepted', status, doc['version'], doc['id'], button))


@router.post('/consents', dependencies=[Depends(same_origin)])
def accept(body: Accept, request: Request, user=Depends(browser_user)):
    """Принять действующую редакцию документа (новые Правила, обработка данных, публикация)."""
    with db(request).transaction() as conn:
        conn.execute('SELECT 1 FROM users WHERE id=%s FOR UPDATE', (user['id'],))
        doc = conn.execute('SELECT * FROM legal_documents WHERE id=%s AND doc_type = ANY(%s)',
                           (body.document_id, list(DOC_TYPES))).fetchone()
        current = G.current_document(conn, doc['doc_type'], now_of(request)) if doc else None
        if not doc or current is None or current['id'] != doc['id']:
            raise HTTPException(409, 'not_current')
        if not G.accepted(conn, user['id'], doc['id']):
            record_consent(conn, user['id'], doc, 'accepted', 'Принять')
            G.audit(conn, user['id'], 'consent', doc['id'], 'consent_accepted', {'type': doc['doc_type'], 'version': doc['version']})
    return {'accepted': True}


# ---------- Публичность ----------

def publication_state(conn, user_id):
    last = latest_consent(conn, user_id, 'publication')
    return {'status': last['status'] if last else None, 'at': iso(last['recorded_at']) if last else None}


def publicity_view(conn, user_id):
    u = conn.execute('SELECT * FROM users WHERE id=%s', (user_id,)).fetchone()
    return {'gallery': u['public_works'], 'social': u['public_social'], 'master_page': u['public_profile'],
            'name': u['display_name'] or u['full_name'], 'publication': publication_state(conn, user_id)}


@router.get('/publicity')
def publicity(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        return publicity_view(conn, user['id'])


class Publicity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gallery: bool | None = None
    social: bool | None = None
    master_page: bool | None = None
    accept_publication: bool = False


def current_publication_doc(conn, now):
    return G.current_document(conn, 'publication', now)


@router.put('/publicity', dependencies=[Depends(same_origin)])
def set_publicity(body: Publicity, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        conn.execute('SELECT 1 FROM users WHERE id=%s FOR UPDATE', (user['id'],))
        enabling = any(v is True for v in (body.gallery, body.social, body.master_page))
        if enabling and publication_state(conn, user['id'])['status'] != 'accepted':
            doc = current_publication_doc(conn, now_of(request))
            if not body.accept_publication or doc is None:
                raise HTTPException(409, 'consent_required')
            record_consent(conn, user['id'], doc, 'accepted', 'Показывать мои работы')
        if enabling:
            # рейтинг на сайте — по тому же согласию на публикацию (отдельного переключателя нет)
            conn.execute('UPDATE users SET public_rating=true WHERE id=%s', (user['id'],))
        changes = {k: v for k, v in (('public_works', body.gallery), ('public_social', body.social),
                                     ('public_profile', body.master_page)) if v is not None}
        for column, value in changes.items():
            conn.execute(f'UPDATE users SET {column}=%s WHERE id=%s', (value, user['id']))   # имена колонок — из списка выше
        G.audit(conn, user['id'], 'user', user['id'], 'publicity_changed', {k: v for k, v in changes.items()})
        return publicity_view(conn, user['id'])


@router.post('/publicity/revoke', dependencies=[Depends(same_origin)])
def revoke(request: Request, user=Depends(browser_user)):
    """«Скрыть всё и отозвать согласие на публикацию». Уже вышедшие посты в соцсетях остаются (решение 11.10)."""
    with db(request).transaction() as conn:
        conn.execute('SELECT 1 FROM users WHERE id=%s FOR UPDATE', (user['id'],))
        conn.execute('''UPDATE users SET public_works=false, public_social=false, public_profile=false, public_rating=false
WHERE id=%s''', (user['id'],))
        last = latest_consent(conn, user['id'], 'publication')
        if last and last['status'] == 'accepted':
            doc = conn.execute('SELECT * FROM legal_documents WHERE id=%s', (last['legal_document_id'],)).fetchone() \
                if last['legal_document_id'] else None
            conn.execute('''INSERT INTO consents(user_id,consent_type,accepted,status,document_version,legal_document_id,channel,button_text)
VALUES (%s,'publication',false,'revoked',%s,%s,'web','Скрыть всё и отозвать согласие')''',
                         (user['id'], doc['version'] if doc else last['document_version'], doc['id'] if doc else None))
            G.notify(conn, user['id'], 'revoke', f"revoke:{user['id']}:{last['id']}",
                     {'title': 'Согласие на публикацию отозвано',
                      'text': 'Ваши работы больше не показываются в галерее и не уходят в соцсети лиги.', 'route': 'publicity'})
        G.audit(conn, user['id'], 'user', user['id'], 'publication_revoked')
        return publicity_view(conn, user['id'])


# ---------- Каналы уведомлений ----------

def preferences_view(conn, user_id):
    p = conn.execute('SELECT * FROM communication_preferences WHERE user_id=%s', (user_id,)).fetchone()
    tg = conn.execute("SELECT 1 FROM external_identities WHERE user_id=%s AND provider='telegram'", (user_id,)).fetchone()
    return {'telegram': p['telegram_service_enabled'] if p else True, 'email': p['email_service_enabled'] if p else True,
            'marketing': p['marketing_opt_in'] if p else False, 'telegram_linked': bool(tg)}


@router.get('/preferences')
def preferences(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        return preferences_view(conn, user['id'])


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    telegram: bool | None = None
    email: bool | None = None
    marketing: bool | None = None


@router.put('/preferences', dependencies=[Depends(same_origin)])
def set_preferences(body: Preferences, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        conn.execute('INSERT INTO communication_preferences(user_id) VALUES (%s) ON CONFLICT DO NOTHING', (user['id'],))
        conn.execute('''UPDATE communication_preferences SET
telegram_service_enabled=coalesce(%s, telegram_service_enabled), email_service_enabled=coalesce(%s, email_service_enabled),
marketing_opt_in=coalesce(%s, marketing_opt_in) WHERE user_id=%s''', (body.telegram, body.email, body.marketing, user['id']))
        G.audit(conn, user['id'], 'user', user['id'], 'preferences_changed', body.model_dump(exclude_none=True))
        return preferences_view(conn, user['id'])


# ---------- Достижения (только чтение: данные появляются после итогов туров и Игр) ----------

@router.get('/achievements')
def achievements(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        stats = conn.execute('SELECT * FROM participant_stats WHERE user_id=%s', (user['id'],)).fetchone()
        league = conn.execute('''SELECT sp.current_league, s.name FROM season_participants sp JOIN seasons s ON s.id=sp.season_id
WHERE sp.user_id=%s ORDER BY s.starts_at DESC NULLS LAST LIMIT 1''', (user['id'],)).fetchone()
        rating = conn.execute('''SELECT t.rating_before, t.rating_after, t.applied_at, e.title, r.round_no FROM rating_transactions t
LEFT JOIN events e ON e.id=t.event_id LEFT JOIN rounds r ON r.id=t.round_id
WHERE t.user_id=%s AND t.status='active' ORDER BY t.ledger_seq''', (user['id'],)).fetchall()
        points = conn.execute('''SELECT lifetime_delta, reason_code, reason_text, created_at FROM points_transactions
WHERE user_id=%s ORDER BY created_at DESC LIMIT 200''', (user['id'],)).fetchall()
        results = conn.execute('''SELECT e.id AS event_id, e.title, r.round_no, r.title AS round_title, rr.display_score, rr.top_work,
rr.league, rr.published_at FROM round_results rr
JOIN event_participants p ON p.id=rr.event_participant_id JOIN events e ON e.id=rr.event_id JOIN rounds r ON r.id=rr.round_id
WHERE p.user_id=%s AND rr.is_current AND rr.status='published' ORDER BY rr.published_at DESC''', (user['id'],)).fetchall()
        games = conn.execute('''SELECT e.id AS event_id, e.title, er.game_counted, er.league, er.league_rank, er.award_place, er.overall_rank,
er.final_score, er.published_at
FROM event_results er JOIN event_participants p ON p.id=er.event_participant_id JOIN events e ON e.id=er.event_id
WHERE p.user_id=%s AND er.is_current AND er.status='published' AND er.result_kind='personal' ORDER BY er.published_at DESC''',
                             (user['id'],)).fetchall()
        diplomas = conn.execute('''SELECT c.certificate_number, c.issued_at, c.issue_snapshot, e.title FROM certificates c
JOIN event_participants p ON p.id=c.event_participant_id JOIN events e ON e.id=p.event_id
WHERE p.user_id=%s AND c.status='issued' ORDER BY c.issued_at DESC''', (user['id'],)).fetchall()

    def num(v):
        return float(v) if v is not None else None
    return {
        'rating': {'value': num(stats['current_rating']) if stats else None, 'status': stats['rating_status'] if stats else 'unrated',
                   'calibration': stats['calibration_rounds_completed'] if stats else 0,
                   'history': [{'before': num(r['rating_before']), 'after': num(r['rating_after']), 'at': iso(r['applied_at']),
                                'game': r['title'], 'round_no': r['round_no']} for r in rating]},
        'league': {'league': league['current_league'], 'season': league['name']} if league else None,
        'points': {'total': stats['lifetime_points'] if stats else 0,
                   'items': [{'delta': p['lifetime_delta'], 'reason': p['reason_text'] or p['reason_code'], 'at': iso(p['created_at'])}
                             for p in points]},
        'counted_games': sum(1 for g in games if g['game_counted']),
        'results': [{'event_id': str(r['event_id']), 'game': r['title'], 'round_no': r['round_no'], 'round_title': r['round_title'],
                     'score': num(r['display_score']), 'top_work': r['top_work'], 'league': r['league'],
                     'at': iso(r['published_at'])} for r in results],
        'games': [{'event_id': str(g['event_id']), 'game': g['title'], 'counted': g['game_counted'], 'league': g['league'],
                   'league_rank': g['league_rank'], 'award_place': g['award_place'], 'overall_rank': g['overall_rank'],
                   'score': num(g['final_score']), 'at': iso(g['published_at'])} for g in games],
        'diplomas': [{'number': d['certificate_number'], 'game': d['title'], 'issued_at': iso(d['issued_at']),
                      'place': (d['issue_snapshot'] or {}).get('place'), 'league': (d['issue_snapshot'] or {}).get('league'),
                      'title': (d['issue_snapshot'] or {}).get('result')}
                     for d in diplomas],
    }
