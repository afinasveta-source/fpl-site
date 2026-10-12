"""Вход из браузера: сессия в cookie (HttpOnly, SameSite=Strict), страницы кабинета, первый администратор."""
import hashlib
import hmac
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from psycopg import sql

from kabinet.auth.routes import client_ip, service
from kabinet.auth.schemas import EmailInput, Login, UserView
from kabinet.auth.security import password_hasher
from kabinet.auth.service import user_view

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / 'static'
PASSWORD_MIN = 12


def cookie_name(request):
    return '__Host-fpl_session' if request.app.state.settings.environment == 'PROD' else 'fpl_session'


def same_origin(request: Request):
    # Origin — только схема и домен; адрес кабинета может быть в подпапке (/kabinet).
    base = urlsplit(str(request.base_url))
    if request.headers.get('origin') != f'{base.scheme}://{base.netloc}':
        raise HTTPException(403, 'Same-origin request required')


def browser_user(request: Request, auth=Depends(service)):
    raw = request.cookies.get(cookie_name(request))
    if not raw:
        raise HTTPException(401, 'Authentication required')
    return auth.current_user(raw)


def set_session_cookie(request, response, session):
    response.set_cookie(cookie_name(request), session['access_token'], max_age=session['expires_in'],
                        httponly=True, secure=request.app.state.settings.environment == 'PROD',
                        samesite='strict', path='/')


def setup_needed(request, conn=None):
    """Нужен ли первый администратор: ключ сервера задан и администратора ещё нет."""
    if not request.app.state.settings.setup_key_sha256:
        return False
    def check(c):
        return c.execute("SELECT 1 FROM user_roles WHERE role='admin'").fetchone() is None
    if conn is not None:
        return check(conn)
    with request.app.state.db.transaction() as c:
        return check(c)


@router.get('/web-auth/config')
def browser_config(request: Request):
    s = request.app.state.settings
    return {'is_test': s.environment == 'TEST', 'mail_delivery': s.mail_mode == 'smtp',
            'password_min_length': PASSWORD_MIN, 'setup_needed': setup_needed(request)}


@router.post('/web-auth/login', response_model=UserView, dependencies=[Depends(same_origin)])
def browser_login(body: Login, request: Request, response: Response, auth=Depends(service)):
    session = auth.login(body.email, body.password, client_ip(request))
    old = request.cookies.get(cookie_name(request))
    if old:
        auth.logout(old)  # не оставлять прежнюю сессию этого браузера рабочей
    set_session_cookie(request, response, session)
    return auth.current_user(session['access_token'])


@router.get('/web-auth/me', response_model=UserView)
def browser_me(user=Depends(browser_user)):
    return user


@router.post('/web-auth/logout', status_code=204, dependencies=[Depends(same_origin)])
def browser_logout(request: Request, auth=Depends(service)):
    raw = request.cookies.get(cookie_name(request))
    if raw:
        auth.logout(raw)
    response = Response(status_code=204)
    response.delete_cookie(cookie_name(request), path='/', secure=request.app.state.settings.environment == 'PROD',
                           httponly=True, samesite='strict')
    return response


class Setup(EmailInput):
    key: str = Field(min_length=8, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator('full_name')
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Full name is required')
        return value


@router.post('/web-auth/setup', response_model=UserView, status_code=201, dependencies=[Depends(same_origin)])
def first_admin(body: Setup, request: Request, response: Response, auth=Depends(service)):
    """Первый администратор: один раз, по ключу сервера. Когда администратор есть — больше не работает."""
    expected = request.app.state.settings.setup_key_sha256
    if not expected:
        raise HTTPException(404, 'Not found')
    auth.throttle('setup', client_ip(request))
    given = hashlib.sha256(body.key.encode()).hexdigest()
    if not hmac.compare_digest(given, expected):
        raise HTTPException(403, 'Invalid setup key')
    encoded = password_hasher.hash(body.password)
    with auth.db.transaction() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(712436902)')  # тот же замок, что у смены ролей и CLI
        if not setup_needed(request, conn):
            raise HTTPException(409, 'An administrator already exists')
        if conn.execute('SELECT 1 FROM users WHERE lower(email)=%s', (body.email,)).fetchone():
            raise HTTPException(409, 'Email unavailable')
        user = conn.execute("""INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES (%s,%s,now(),'active',%s) RETURNING id""", (body.email, encoded, body.full_name)).fetchone()
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'admin')", (user['id'],))
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'admin_setup')",
                     (user['id'], user['id']))
    session = auth.login(body.email, body.password, client_ip(request))
    set_session_cookie(request, response, session)
    return auth.current_user(session['access_token'])


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str | None = Field(default=None, max_length=100)
    full_name: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, max_length=2)

    @field_validator('display_name', 'full_name', 'city', 'country_code')
    @classmethod
    def trim_optional(cls, value):
        return (value.strip() or None) if value is not None else None

    @field_validator('display_name')
    @classmethod
    def public_name(cls, value):
        # Публичное имя необязательно; заполненное — от 2 до 40 символов.
        if value is not None and not 2 <= len(value) <= 40:
            raise ValueError('Public name must be 2 to 40 characters')
        return value

    @field_validator('country_code')
    @classmethod
    def country(cls, value):
        if value is not None and not (len(value) == 2 and value.isascii() and value.isalpha()):
            raise ValueError('Country code must be two letters')
        return value.upper() if value else value

    @model_validator(mode='after')
    def supplied_fields(self):
        if not self.model_fields_set:
            raise ValueError('At least one profile field is required')
        return self


@router.patch('/web-auth/profile', response_model=UserView, dependencies=[Depends(same_origin)])
def update_profile(body: ProfileChange, user=Depends(browser_user), auth=Depends(service)):
    with auth.db.transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=%s AND account_status='active' AND deleted_at IS NULL FOR UPDATE",
                           (user['id'],)).fetchone()
        if not row:
            raise HTTPException(401, 'Authentication required')
        changes = body.model_dump(exclude_unset=True)
        if 'full_name' in changes and row['full_name'] and changes['full_name'] != row['full_name']:
            # ФИО по документам указано в согласиях: участник меняет его через организатора.
            staff = conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role IN ('admin','moderator')",
                                 (user['id'],)).fetchone()
            if not staff:
                raise HTTPException(403, 'full_name_locked')
        # Пишутся только проверенные поля своего профиля; не переданные — не трогаются.
        assignments = sql.SQL(', ').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
        row = conn.execute(sql.SQL('UPDATE users SET {} WHERE id=%s RETURNING *').format(assignments),
                           (*changes.values(), user['id'])).fetchone()
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'profile_updated')",
                     (user['id'], user['id']))
        return user_view(conn, row)


@router.get('/', include_in_schema=False)
@router.get('/setup', include_in_schema=False)
@router.get('/auth/set-password', include_in_schema=False)
@router.get('/auth/reset-password', include_in_schema=False)
def page(request: Request):
    index = STATIC / 'index.html'
    if not index.is_file():
        return JSONResponse(status_code=503, content={'detail': 'Interface files are missing'})
    # Адрес кабинета на сервере (/kabinet) подставляется в ссылки на файлы и запросы страницы.
    html = index.read_text(encoding='utf-8').replace('{{ROOT}}', request.app.state.settings.root_path)
    return HTMLResponse(html)
