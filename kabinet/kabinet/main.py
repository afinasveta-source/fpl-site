"""Кабинет Face Painting League: приложение FastAPI."""
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kabinet.config import Settings
from kabinet.db import Database
from kabinet.auth.mail import DisabledMailer, MemoryMailer, SMTPMailer
from kabinet.auth.service import AuthService
from kabinet.auth.security import Busy
from kabinet.auth.routes import router as auth_router
from kabinet.users.routes import router as users_router
from kabinet.web.routes import router as web_router, STATIC
from kabinet.participation.routes import router as participant_router
from kabinet.participation.account import router as account_router
from kabinet.participation.media import MediaStore
from kabinet.org import games as org_games, rounds as org_rounds, documents as org_documents, people as org_people
from kabinet.judging import routes as judging_routes
from kabinet.results import routes as results_routes
from kabinet.org import participants as org_participants, support as org_support, home as org_home, overview as org_overview
from kabinet import reviews, claims
from kabinet.org import bot_import as org_bot_import, bot_photos as org_bot_photos

# Версия схемы базы (server/db/schema), под которую написан кабинет. Новее — можно, старее — нельзя.
SCHEMA_REQUIRED = 11  # 011 — эстафета с проверкой организатора (13.10)
# img-src: кроме своих — фото работ из бота прямо с источника (предпросмотр «Фото работ из бота» у организатора, 14.10)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
       "img-src 'self' data: blob: https://files.salebot.pro https://*.userapi.com https://*.vkuserphoto.ru; media-src 'self' blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def schema_version(conn):
    row = conn.execute('SELECT version_num FROM alembic_version').fetchone()
    return int(row['version_num']) if row and str(row['version_num']).isdigit() else None


def utc_now():
    return datetime.now(timezone.utc)


def create_app(settings=None, mailer=None, clock=None):
    settings = settings or Settings()
    if settings.environment == 'PROD' and mailer is not None:
        raise ValueError('Mailer injection is only allowed in TEST')
    if mailer is None:
        mailer = {'memory': MemoryMailer, 'disabled': DisabledMailer}.get(settings.mail_mode)
        mailer = mailer() if mailer else SMTPMailer(settings)
    test = settings.environment == 'TEST' and settings.api_docs
    # Адрес /kabinet снимает nginx (proxy_pass .../), поэтому маршруты приложения — от корня;
    # settings.root_path нужен только страницам — для ссылок на файлы и запросов.
    app = FastAPI(title='Кабинет FPL', version='0.1.0',
                  docs_url='/docs' if test else None, redoc_url=None,
                  openapi_url='/openapi.json' if test else None)
    app.state.settings = settings
    app.state.db = Database(settings)
    app.state.mailer = mailer
    app.state.auth = AuthService(app.state.db, settings, mailer)
    if clock is not None and settings.environment == 'PROD':
        raise ValueError('Clock injection is only allowed in TEST')
    app.state.clock = clock or utc_now
    app.state.media = MediaStore(settings.media_dir, settings.media_min_free_mb)

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if '/assets/' not in request.url.path:
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Content-Security-Policy'] = CSP if not request.url.path.endswith('/docs') else "frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Ответ об ошибке не повторяет введённое: пароли и токены не должны попадать в ответы.
        errors = [{k: e[k] for k in ('loc', 'msg', 'type')} for e in exc.errors()]
        return JSONResponse(status_code=422, content={'detail': errors})

    @app.exception_handler(Busy)
    async def busy(request, exc):
        # Много входов сразу (после рассылки): просим повторить через полминуты, а не держим поток службы.
        return JSONResponse(status_code=503, content={'detail': 'busy'}, headers={'Retry-After': '30'})

    @app.exception_handler(psycopg.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'Data conflicts with existing records'})

    @app.get('/health')
    def health():
        return {'status': 'ok', 'environment': settings.environment}

    @app.get('/ready')
    def ready():
        try:
            with app.state.db.transaction() as conn:
                version = schema_version(conn)
            if version is None or version < SCHEMA_REQUIRED:
                raise ValueError('Migration required')
        except (psycopg.Error, ValueError):
            return JSONResponse(status_code=503, content={'status': 'not_ready'})
        return {'status': 'ready', 'schema': '%03d' % version}

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(web_router)
    app.include_router(participant_router)
    app.include_router(account_router)
    for module in (org_home, org_overview, org_games, org_rounds, org_documents, org_people, org_participants, org_support, org_bot_import, org_bot_photos):
        app.include_router(module.router)
    app.include_router(org_support.public)
    app.include_router(reviews.public)
    app.include_router(claims.public)
    app.include_router(claims.org)
    app.include_router(reviews.org)
    app.include_router(reviews.mine)
    app.include_router(reviews.judge)
    app.include_router(judging_routes.org)
    app.include_router(judging_routes.judge)
    app.include_router(results_routes.router)
    app.mount('/assets', StaticFiles(directory=str(STATIC / 'assets')), name='assets')
    return app
