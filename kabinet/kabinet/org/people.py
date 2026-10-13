"""Кабинет организатора: люди лиги — список, карточка, новый человек, ссылки для входа, роли, приостановка.

Писем кабинет пока не отправляет. Поэтому ссылку для входа организатор получает здесь и сам пересылает
человеку (например, в Telegram):
- приглашение — для аккаунта, который ещё не активирован (заведён организатором или перенесён из бота):
  по ссылке человек сам указывает email и пароль; действует 7 дней;
- новый пароль — для активного аккаунта; действует сутки.
Новая ссылка отменяет прежнюю неиспользованную того же вида. Ссылка показывается один раз.
"""
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from kabinet.auth.security import new_token, token_hash
from kabinet.participation import game as G
from kabinet.participation import rules as R
from .common import WRITE, audit, db, iso, locked_admin, now_of, org_user, person_name, problem
from .games import clean_text

router = APIRouter(prefix='/api/org', tags=['organizer'])
ROLES = ('participant', 'judge', 'moderator', 'admin')
STAFF = ('judge', 'moderator', 'admin')
KINDS = ('all', 'participants', 'staff', 'not_activated', 'suspended')
DOCS = ('rules', 'publication', 'personal_data')


def roles_of(conn, user_id):
    return [r['role'] for r in conn.execute('SELECT role FROM user_roles WHERE user_id=%s ORDER BY role', (user_id,))]


def person_brief(u, roles):
    return {'id': str(u['id']), 'name': person_name(u), 'full_name': u['full_name'], 'display_name': u['display_name'],
            'email': u['email'], 'city': u['city'], 'country_code': u['country_code'], 'telegram_id': u['telegram_id'],
            'account_status': u['account_status'], 'roles': roles}


KIND_SQL = {
    'all': 'TRUE',
    'participants': "EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role='participant')",
    'staff': "EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role IN ('judge','moderator','admin'))",
    'not_activated': "u.account_status='imported'",
    'suspended': "u.account_status='suspended'",
}


@router.get('/people')
def people(request: Request, q: str = Query('', max_length=100), kind: str = Query('all', pattern='^(' + '|'.join(KINDS) + ')$'),
           offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=200), user=Depends(org_user)):
    term = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    search = '''(%(q)s = '%%%%' OR u.full_name ILIKE %(q)s OR u.display_name ILIKE %(q)s OR u.email ILIKE %(q)s
  OR u.city ILIKE %(q)s OR u.telegram_id::text ILIKE %(q)s)'''
    with db(request).transaction() as conn:
        base = f"FROM users u WHERE u.deleted_at IS NULL AND {search}"
        rows = conn.execute(f'''SELECT u.*, (SELECT count(*) FROM event_participants p WHERE p.user_id=u.id
  AND p.registration_status<>'cancelled') AS games,
  (SELECT array_agg(role ORDER BY role) FROM user_roles r WHERE r.user_id=u.id) AS roles
{base} AND {KIND_SQL[kind]} ORDER BY coalesce(u.full_name, u.display_name, u.email) NULLS LAST, u.created_at
LIMIT %(limit)s OFFSET %(offset)s''', {'q': term, 'limit': limit, 'offset': offset}).fetchall()
        counts = {k: conn.execute(f'SELECT count(*) AS n {base} AND {KIND_SQL[k]}', {'q': term}).fetchone()['n'] for k in KINDS}
    return {'people': [person_brief(u, u['roles'] or []) | {'games': u['games']} for u in rows], 'counts': counts,
            'offset': offset, 'limit': limit}


def load_person(conn, user_id, lock=False):
    u = conn.execute('SELECT * FROM users WHERE id=%s AND deleted_at IS NULL' + (' FOR UPDATE' if lock else ''), (user_id,)).fetchone()
    if not u:
        raise HTTPException(404, 'Person not found')
    return u


def consents_state(conn, user_id, now):
    out = {}
    for kind in DOCS:
        doc = G.current_document(conn, kind, now)
        last = conn.execute('''SELECT status, document_version, recorded_at FROM consents WHERE user_id=%s AND consent_type=%s
ORDER BY recorded_at DESC, id DESC LIMIT 1''', (user_id, kind)).fetchone()
        out[kind] = {'current_version': doc['version'] if doc else None,
                     'current_accepted': bool(doc and G.accepted(conn, user_id, doc['id'])),
                     'last_status': last['status'] if last else None, 'last_version': last['document_version'] if last else None,
                     'at': iso(last['recorded_at']) if last else None}
    return out


def person_detail(conn, u, now, actor_id):
    roles = roles_of(conn, u['id'])
    games = conn.execute('''SELECT p.*, e.title, e.status AS event_status FROM event_participants p JOIN events e ON e.id=p.event_id
WHERE p.user_id=%s ORDER BY coalesce(e.starts_at, e.created_at) DESC''', (u['id'],)).fetchall()
    threads = conn.execute('''SELECT thread_no, subject, status, updated_at FROM support_threads WHERE user_id=%s
ORDER BY updated_at DESC LIMIT 20''', (u['id'],)).fetchall()
    invite = conn.execute('''SELECT expires_at, created_at FROM auth_tokens WHERE user_id=%s AND token_type='invite'
AND used_at IS NULL AND expires_at > clock_timestamp() ORDER BY created_at DESC LIMIT 1''', (u['id'],)).fetchone()
    last_login = conn.execute('SELECT max(created_at) AS at FROM auth_sessions WHERE user_id=%s', (u['id'],)).fetchone()['at']
    return person_brief(u, roles) | {
        'created_at': iso(u['created_at']), 'last_login': iso(last_login), 'me': str(u['id']) == str(actor_id),
        'invite': {'expires_at': iso(invite['expires_at']), 'created_at': iso(invite['created_at'])} if invite else None,
        'games': [{'event_id': str(g['event_id']), 'participant_id': str(g['id']), 'title': g['title'],
                   'event_status': g['event_status'], 'mode': R.participation_mode(g), 'league': g['entry_league'],
                   'joined_at': iso(g['joined_at'])} for g in games],
        'support': [{'no': t['thread_no'], 'subject': t['subject'], 'status': t['status'], 'updated_at': iso(t['updated_at'])}
                    for t in threads],
        'consents': consents_state(conn, u['id'], now),
        'publicity': {'gallery': u['public_works'], 'social': u['public_social'], 'master_page': u['public_profile']}}


@router.get('/people/{user_id}')
def person(user_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return person_detail(conn, load_person(conn, user_id), now_of(request), user['id'])


def country(value):
    if value is None:
        return None
    value = value.strip().upper()
    if not value:
        return None
    if len(value) != 2 or not value.isascii() or not value.isalpha():
        raise ValueError('Country code must be two letters')
    return value


class PersonIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    full_name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    city: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, max_length=2)
    telegram_id: int | None = Field(default=None, gt=0, lt=2**63)

    @field_validator('full_name', 'display_name', 'city')
    @classmethod
    def trim(cls, value):
        return clean_text(value)

    @field_validator('display_name')
    @classmethod
    def public_name(cls, value):
        if value is not None and not 2 <= len(value) <= 40:
            raise ValueError('Public name must be 2 to 40 characters')
        return value

    @field_validator('email')
    @classmethod
    def normalize(cls, value):
        return str(value).strip().lower() if value is not None else None

    @field_validator('country_code')
    @classmethod
    def code(cls, value):
        return country(value)


class PersonCreate(PersonIn):
    full_name: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def named(self):
        if not self.full_name:
            raise ValueError('Full name is required')
        return self


def unique_contacts(conn, values, user_id=None):
    if values.get('email') and conn.execute('SELECT 1 FROM users WHERE lower(email)=%s AND id IS DISTINCT FROM %s',
                                            (values['email'], user_id)).fetchone():
        raise problem('email_taken', 409)
    if values.get('telegram_id') and conn.execute('SELECT 1 FROM users WHERE telegram_id=%s AND id IS DISTINCT FROM %s',
                                                  (values['telegram_id'], user_id)).fetchone():
        raise problem('telegram_taken', 409)


@router.post('/people', status_code=201, dependencies=WRITE)
def create_person(body: PersonCreate, request: Request, user=Depends(org_user)):
    values = body.model_dump()
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        unique_contacts(conn, values)
        u = conn.execute('''INSERT INTO users(full_name,display_name,email,city,country_code,telegram_id,account_status)
VALUES (%(full_name)s,%(display_name)s,%(email)s,%(city)s,%(country_code)s,%(telegram_id)s,'imported') RETURNING *''',
                         values).fetchone()
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant')", (u['id'],))
        audit(conn, user['id'], 'user', u['id'], 'person_created', {'by': 'organizer'})
        return person_detail(conn, u, now_of(request), user['id'])


@router.patch('/people/{user_id}', dependencies=WRITE)
def change_person(user_id: UUID, body: PersonIn, request: Request, user=Depends(org_user)):
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise problem('nothing_to_change')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        u = load_person(conn, user_id, lock=True)
        if 'full_name' in values and not values['full_name']:
            raise problem('full_name_required')
        if 'email' in values and values['email'] != u['email']:
            # Email активного аккаунта — его логин: меняет сам человек (через ссылку нового пароля это не делается).
            if u['account_status'] != 'imported':
                raise problem('email_locked', 409)
        unique_contacts(conn, values, user_id)
        sets = ', '.join(f'{k}=%({k})s' for k in values)
        u = conn.execute(f'UPDATE users SET {sets} WHERE id=%(id)s RETURNING *', values | {'id': user_id}).fetchone()
        audit(conn, user['id'], 'user', user_id, 'person_changed', {'fields': sorted(values)})
        return person_detail(conn, u, now_of(request), user['id'])


def make_link(conn, settings, user_id, kind, target_email, minutes):
    raw = new_token()
    conn.execute('UPDATE auth_tokens SET used_at=now() WHERE user_id=%s AND token_type=%s AND used_at IS NULL', (user_id, kind))
    row = conn.execute('''INSERT INTO auth_tokens(user_id,token_hash,token_type,target_email,expires_at)
VALUES (%s,%s,%s,%s,now()+make_interval(mins => %s)) RETURNING expires_at''',
                       (user_id, token_hash(raw), kind, target_email, minutes)).fetchone()
    base = settings.frontend_url.rstrip('/')
    if kind == 'invite':
        link = base + '/auth/invite#' + urlencode({'token': raw})
    else:
        link = base + '/auth/reset-password#' + urlencode({'token': raw, 'type': 'reset_password'})
    return {'link': link, 'expires_at': iso(row['expires_at'])}


@router.post('/people/{user_id}/invite', dependencies=WRITE)
def invite(user_id: UUID, request: Request, user=Depends(org_user)):
    settings = request.app.state.settings
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        u = load_person(conn, user_id, lock=True)
        if u['account_status'] != 'imported':
            raise problem('already_active', 409)
        out = make_link(conn, settings, user_id, 'invite', None, settings.invite_days * 24 * 60)
        audit(conn, user['id'], 'user', user_id, 'invite_link_created')
        return out


@router.post('/people/{user_id}/reset-link', dependencies=WRITE)
def reset_link(user_id: UUID, request: Request, user=Depends(org_user)):
    settings = request.app.state.settings
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        u = load_person(conn, user_id, lock=True)
        if u['account_status'] != 'active' or not u['email']:
            raise problem('not_active', 409)
        out = make_link(conn, settings, user_id, 'reset_password', u['email'], settings.reset_link_hours * 60)
        audit(conn, user['id'], 'user', user_id, 'reset_link_created')
        return out


class RoleIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['participant', 'judge', 'moderator', 'admin']
    enabled: bool


def active_admins(conn):
    return conn.execute('''SELECT count(*) AS n FROM user_roles r JOIN users u ON u.id=r.user_id
WHERE r.role='admin' AND u.account_status='active' AND u.deleted_at IS NULL''').fetchone()['n']


@router.post('/people/{user_id}/roles', dependencies=WRITE)
def change_role(user_id: UUID, body: RoleIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(712436902)')  # тот же замок, что у первого администратора и CLI
        locked_admin(conn, user)
        u = load_person(conn, user_id, lock=True)
        has = conn.execute('SELECT 1 FROM user_roles WHERE user_id=%s AND role=%s', (user_id, body.role)).fetchone() is not None
        if body.role == 'admin' and not body.enabled and has:
            if str(user_id) == str(user['id']):
                raise problem('cannot_remove_own_admin', 409)
            if u['account_status'] == 'active' and active_admins(conn) <= 1:
                raise problem('last_admin', 409)
        if body.enabled:
            conn.execute('INSERT INTO user_roles(user_id,role) VALUES (%s,%s) ON CONFLICT DO NOTHING', (user_id, body.role))
        else:
            conn.execute('DELETE FROM user_roles WHERE user_id=%s AND role=%s', (user_id, body.role))
        if body.enabled != has:
            audit(conn, user['id'], 'user', user_id, 'role_changed', {'role': body.role, 'enabled': body.enabled})
        return person_detail(conn, u, now_of(request), user['id'])


class SuspendIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suspended: bool


@router.post('/people/{user_id}/suspend', dependencies=WRITE)
def suspend(user_id: UUID, body: SuspendIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(712436902)')
        locked_admin(conn, user)
        u = load_person(conn, user_id, lock=True)
        if body.suspended:
            if str(user_id) == str(user['id']):
                raise problem('cannot_suspend_self', 409)
            if u['account_status'] == 'suspended':
                return person_detail(conn, u, now_of(request), user['id'])
            is_admin = conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role='admin'", (user_id,)).fetchone()
            if is_admin and u['account_status'] == 'active' and active_admins(conn) <= 1:
                raise problem('last_admin', 409)
            u = conn.execute("UPDATE users SET account_status='suspended' WHERE id=%s RETURNING *", (user_id,)).fetchone()
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (user_id,))
            conn.execute('UPDATE auth_tokens SET used_at=now() WHERE user_id=%s AND used_at IS NULL', (user_id,))
        else:
            if u['account_status'] != 'suspended':
                return person_detail(conn, u, now_of(request), user['id'])
            # Вход был настроен — аккаунт снова активен; не был — снова ждёт приглашения.
            status = 'active' if u['email'] and u['password_hash'] and u['email_verified_at'] else 'imported'
            u = conn.execute('UPDATE users SET account_status=%s WHERE id=%s RETURNING *', (status, user_id)).fetchone()
        audit(conn, user['id'], 'user', user_id, 'suspended' if body.suspended else 'unsuspended')
        return person_detail(conn, u, now_of(request), user['id'])
