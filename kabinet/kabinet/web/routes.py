"""Вход из браузера: сессия в cookie (HttpOnly, SameSite=Strict), страницы кабинета, первый администратор."""
import hashlib
import re
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
PASSWORD_MIN = 8   # решение 13.10 (было 12)


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
    return {'is_test': s.environment == 'TEST', 'mail_delivery': s.mail_mode == 'smtp', 'signup': s.signup_enabled,
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


class InviteCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=20, max_length=256)


class InviteAccept(EmailInput):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)


class Signup(EmailInput):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    accept_personal_data: bool = False   # решение 14.10: согласие на обработку данных и 18+ — уже при заведении кабинета
    confirm_adult: bool = False

    @field_validator('full_name')
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Full name is required')
        return value


@router.post('/web-auth/register', response_model=UserView, status_code=201, dependencies=[Depends(same_origin)])
def register_account(body: Signup, request: Request, response: Response, auth=Depends(service)):
    """Новая участница регистрируется сама: email, пароль, имя. Участницы из бота входят по ссылке организатора —
    так за ними остаётся история Игр."""
    settings = request.app.state.settings
    if not settings.signup_enabled:
        raise HTTPException(404, 'Not found')
    if not body.accept_personal_data:
        raise HTTPException(422, 'personal_data_required')
    if not body.confirm_adult:
        raise HTTPException(422, 'adult_required')
    auth.throttle('signup', client_ip(request), limit=settings.signup_limit)
    encoded = password_hasher.hash(body.password)
    with auth.db.transaction() as conn:
        existing = conn.execute('SELECT account_status FROM users WHERE lower(email)=%s', (body.email,)).fetchone()
        if existing:
            raise HTTPException(409, 'email_invited' if existing['account_status'] == 'imported' else 'email_taken')
        # Участница Игры 01 из бота заводит новый кабинет вместо заявки — её итоги туров 1–2 остались бы на записи из бота
        # (задвоение, 14.10). Похожие ФИО в перенесённом списке → отправляем на страницу заявки.
        from kabinet import claims as CL
        ev = CL.moved_event(conn)
        if ev and len(CL.words(body.full_name)) >= 2 and any(CL.similarity(body.full_name, p['full_name']) >= 0.9
                                                              for p in CL.free_people(conn, ev['id'])):
            raise HTTPException(409, 'game01_player')
        user = conn.execute("""INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES (%s,%s,now(),'active',%s) RETURNING id""", (body.email, encoded, body.full_name)).fetchone()
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant')", (user['id'],))
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'self_registered')",
                     (user['id'], user['id']))
        from kabinet.participation import game as G
        pd = G.current_document(conn, 'personal_data', request.app.state.clock())
        if pd is not None:
            conn.execute('''INSERT INTO consents(user_id,consent_type,accepted,status,document_version,legal_document_id,channel,button_text,metadata)
VALUES (%s,'personal_data',true,'accepted',%s,%s,'web','Зарегистрироваться',%s)''', (user['id'], pd['version'], pd['id'],
                                                                                G.Jsonb({'adult_confirmed': True})))
    session = auth.login(body.email, body.password, client_ip(request))
    old = request.cookies.get(cookie_name(request))
    if old:
        auth.logout(old)
    set_session_cookie(request, response, session)
    return auth.current_user(session['access_token'])


@router.post('/web-auth/invite/check', dependencies=[Depends(same_origin)])
def invite_check(body: InviteCheck, request: Request, auth=Depends(service)):
    """Ссылка-приглашение ещё действует? Имя — чтобы поприветствовать; email — если организатор его уже указал."""
    auth.throttle('consume', client_ip(request))
    return auth.check_invite(body.token)


@router.post('/web-auth/invite', response_model=UserView, dependencies=[Depends(same_origin)])
def invite_accept(body: InviteAccept, request: Request, response: Response, auth=Depends(service)):
    """Вход по приглашению: человек сам задаёт email и пароль и сразу попадает в кабинет."""
    auth.throttle('consume', client_ip(request))
    auth.consume_invite(body.token, body.email, body.password)
    session = auth.login(body.email, body.password, client_ip(request))
    old = request.cookies.get(cookie_name(request))
    if old:
        auth.logout(old)
    set_session_cookie(request, response, session)
    return auth.current_user(session['access_token'])


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


# Страницы кабинета: адрес обрабатывает сама страница (core.js); сервер на всех отдаёт один index.html.


@router.get('/sw.js', include_in_schema=False)
def service_worker():
    """Пуш-уведомления (17.10): работник страницы лежит в корне кабинета — тогда он отвечает за весь /kabinet/."""
    return Response((STATIC / 'sw.js').read_bytes(), media_type='application/javascript',
                    headers={'Cache-Control': 'no-cache'})


@router.get('/manifest.webmanifest', include_in_schema=False)
def manifest(request: Request):
    """Кабинет на экране телефона как приложение (на iPhone без этого пуши не работают)."""
    root = request.app.state.settings.root_path
    return JSONResponse({'name': 'Face Painting League — кабинет', 'short_name': 'FPL', 'lang': 'ru',
                         'start_url': root + '/', 'scope': root + '/', 'display': 'standalone',
                         'background_color': '#1E1B18', 'theme_color': '#1E1B18',
                         'icons': [{'src': root + '/assets/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                                   {'src': root + '/assets/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                                   {'src': root + '/assets/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png',
                                    'purpose': 'maskable'}]},
                        media_type='application/manifest+json')


@router.get('/', include_in_schema=False)
@router.get('/setup', include_in_schema=False)
@router.get('/games', include_in_schema=False)
@router.get('/events', include_in_schema=False)
@router.get('/notifications', include_in_schema=False)
@router.get('/support', include_in_schema=False)
@router.get('/profile', include_in_schema=False)
@router.get('/achievements', include_in_schema=False)
@router.get('/reviews', include_in_schema=False)
@router.get('/gallery', include_in_schema=False)   # «Галерея» (16.10): без этого обновление страницы давало 404
@router.get('/games/{rest:path}', include_in_schema=False)
@router.get('/events/{rest:path}', include_in_schema=False)
@router.get('/support/{rest:path}', include_in_schema=False)
@router.get('/profile/{rest:path}', include_in_schema=False)
@router.get('/achievements/{rest:path}', include_in_schema=False)
@router.get('/documents/{rest:path}', include_in_schema=False)
@router.get('/judging', include_in_schema=False)
@router.get('/judging/{rest:path}', include_in_schema=False)
@router.get('/org', include_in_schema=False)
@router.get('/org/{rest:path}', include_in_schema=False)
@router.get('/game01', include_in_schema=False)
@router.get('/auth/invite', include_in_schema=False)
@router.get('/auth/set-password', include_in_schema=False)
@router.get('/auth/reset-password', include_in_schema=False)
def page(request: Request):
    index = STATIC / 'index.html'
    if not index.is_file():
        return JSONResponse(status_code=503, content={'detail': 'Interface files are missing'})
    # Адрес кабинета на сервере (/kabinet) подставляется в ссылки на файлы и запросы страницы.
    html = index.read_text(encoding='utf-8').replace('{{ROOT}}', request.app.state.settings.root_path)
    # после обновления браузер берёт новые файлы, а не старые из кеша: к ссылкам добавляется метка версии
    html = re.sub(r'(/assets/[A-Za-z0-9_.-]+\.(?:js|css|svg))"', lambda m: f'{m.group(1)}?v={asset_version()}"', html)
    return HTMLResponse(html)


_ASSET_VERSION = None


def asset_version():
    global _ASSET_VERSION
    if _ASSET_VERSION is None:
        h = hashlib.sha256()
        for f in sorted((STATIC / 'assets').glob('*')):
            if f.is_file():
                h.update(f.name.encode()); h.update(f.read_bytes())
        _ASSET_VERSION = h.hexdigest()[:10]
    return _ASSET_VERSION
