"""API кабинета участника: Игры лиги, запись, мои Игры, задание, фото, сдача и замена работы."""
import asyncio
import re
import threading
import weakref
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.auth.routes import client_ip, service
from kabinet.web.routes import browser_user, same_origin
from . import game as G
from . import rules as R
from . import views as V
from .media import MediaError

router = APIRouter(prefix='/api', tags=['participant'])
REG_STATUSES = ('registration', 'active')


def now_of(request):
    return request.app.state.clock()


def root(request):
    return request.app.state.settings.root_path


def db(request):
    return request.app.state.db


# ---------- Игры лиги и запись ----------

def registration_state(event, now):
    if event['status'] not in REG_STATUSES:
        return 'closed'
    opens, closes = event['registration_opens_at'], event['registration_closes_at']
    if opens is not None and now < opens:
        return 'soon'
    if closes is not None and now > closes:
        return 'closed'
    if event['status'] == 'active' and opens is None and closes is None:
        return 'closed'   # идущая Игра без окна записи — запись закрыта
    return 'open'


def documents(conn, user_id, now):
    """Документы для записи: действующие Правила, согласие на публикацию, обработка данных."""
    out = {}
    for kind in ('rules', 'publication', 'personal_data'):
        doc = G.current_document(conn, kind, now)
        if doc:
            out[kind] = {'id': str(doc['id']), 'version': doc['version'], 'title': doc['title'],
                         'accepted': G.accepted(conn, user_id, doc['id'])}
    return out


def catalog_item(event, ep, now):
    return V.event_brief(event) | {
        'price': float(event['price']) if event['price'] is not None else None, 'currency': event['currency'],
        'payment_required': event['payment_required'], 'registration': registration_state(event, now),
        'registration_opens_at': V.iso(event['registration_opens_at']),
        'my_mode': R.participation_mode(ep), 'affects_rating': event['affects_rating']}


@router.get('/events')
def catalog(request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        events = conn.execute('''SELECT * FROM events WHERE status IN ('registration','active','finished')
ORDER BY coalesce(starts_at, registration_opens_at, created_at)''').fetchall()
        mine = {r['event_id']: r for r in conn.execute('SELECT * FROM event_participants WHERE user_id=%s', (user['id'],))}
    return {'events': [catalog_item(e, mine.get(e['id']), now) for e in events]}


@router.get('/events/{event_id}')
def event_page(event_id: UUID, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        event = conn.execute("SELECT * FROM events WHERE id=%s AND status<>'draft'", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, 'Game not found')
        ep = conn.execute('SELECT * FROM event_participants WHERE event_id=%s AND user_id=%s', (event_id, user['id'])).fetchone()
        rounds = conn.execute("SELECT id, round_no, title, opens_at, deadline FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no",
                              (event_id,)).fetchall()
        if ep:
            # Записанной — даты её лиги (своё открытие задания и срок сдачи), как на странице её Игры.
            game = G.load(conn, event_id, user['id'])
            mine = {}
            for r in game.rounds:
                items = game.assignments.get(r['id'], [])
                deadline = R.competition_deadline(r, items[0], game.pas.get(items[0]['id']))[0] if items else r['deadline']
                mine[r['id']] = {'opens_at': r['opens_at'], 'deadline': deadline}
            rounds = [dict(r, **mine.get(r['id'], {})) for r in rounds]
        prizes = conn.execute('SELECT criterion, prize, league FROM event_prizes WHERE event_id=%s ORDER BY sort_order, created_at',
                              (event_id,)).fetchall()
        me = conn.execute('SELECT country_code, city FROM users WHERE id=%s', (user['id'],)).fetchone()
        docs = documents(conn, user['id'], now)
    return catalog_item(event, ep, now) | {
        'description': event['description'], 'payment_deadline': V.iso(event['payment_deadline']),
        'rounds': [{'round_no': r['round_no'], 'title': r['title'], 'opens_at': V.iso(r['opens_at']),
                    'deadline': V.iso(r['deadline'])} for r in rounds],
        'prizes': [dict(p) for p in prizes], 'documents': docs,
        'needs_place': not (me['country_code'] and me['city'])}


class Registration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accept_rules: bool
    accept_publication: bool
    accept_personal_data: bool = False
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=120)

    @field_validator('country_code')
    @classmethod
    def upper(cls, value):
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r'[A-Z]{2}', value):
            raise ValueError('Country code must be two letters')
        return value

    @field_validator('city')
    @classmethod
    def trim(cls, value):
        return (value.strip() or None) if value is not None else None


@router.post('/events/{event_id}/registration', status_code=201, dependencies=[Depends(same_origin)])
def register(event_id: UUID, body: Registration, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        event = conn.execute("SELECT * FROM events WHERE id=%s AND status<>'draft' FOR SHARE", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, 'Game not found')
        person = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (user['id'],)).fetchone()
        existing = conn.execute('SELECT * FROM event_participants WHERE event_id=%s AND user_id=%s FOR UPDATE',
                                (event_id, user['id'])).fetchone()
        if existing:
            if existing['registration_status'] == 'cancelled':
                raise HTTPException(409, 'contact_organizer')
            return {'event_id': str(event_id), 'mode': R.participation_mode(existing), 'created': False}
        if registration_state(event, now) != 'open':
            raise HTTPException(409, 'registration_closed')
        docs = documents(conn, user['id'], now)
        if 'rules' not in docs or 'publication' not in docs:
            raise HTTPException(409, 'documents_missing')
        if not body.accept_rules or not body.accept_publication:
            raise HTTPException(422, 'consents_required')
        if 'personal_data' in docs and not docs['personal_data']['accepted'] and not body.accept_personal_data:
            raise HTTPException(422, 'personal_data_required')
        country = body.country_code or person['country_code']
        city = body.city or person['city']
        if not country or not city:
            raise HTTPException(422, 'place_required')
        if (country, city) != (person['country_code'], person['city']):
            conn.execute('UPDATE users SET country_code=%s, city=%s WHERE id=%s', (country, city, user['id']))
        if not (person['display_name'] or '').strip() and R.name_for_site(person['full_name']):
            # публичное имя не заполнено — на сайте будет имя из ФИО (его можно поменять в профиле)
            conn.execute('UPDATE users SET display_name=%s WHERE id=%s', (R.name_for_site(person['full_name']), user['id']))
        paid = event['payment_required']
        conn.execute('SAVEPOINT reg')
        try:
            ep = conn.execute('''INSERT INTO event_participants(event_id,user_id,registration_status,eligibility_status,
payment_status,competition_status,joined_at) VALUES (%s,%s,%s,'eligible',%s,%s,%s) RETURNING *''',
                              (event_id, user['id'], 'payment_pending' if paid else 'participating',
                               'pending' if paid else 'not_required', None if paid else 'active', now)).fetchone()
        except Exception as exc:
            conn.execute('ROLLBACK TO SAVEPOINT reg')
            if 'judge of this Game' in str(exc):
                raise HTTPException(409, 'judge_of_game') from None
            raise
        button = 'Записаться на ' + event['title']
        for kind in ('rules', 'publication', 'personal_data'):
            doc = docs.get(kind)
            if doc is None or (kind == 'personal_data' and doc['accepted']):
                continue
            conn.execute('''INSERT INTO consents(user_id,event_id,consent_type,accepted,status,document_version,legal_document_id,
channel,button_text,idempotency_key) VALUES (%s,%s,%s,true,'accepted',%s,%s,'web',%s,%s) ON CONFLICT (idempotency_key) DO NOTHING''',
                         (user['id'], event_id, kind, doc['version'], doc['id'], button, f"reg:{ep['id']}:{kind}"))
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (user['id'],))
        first_publication = conn.execute("""SELECT 1 FROM consents WHERE user_id=%s AND consent_type='publication'
AND idempotency_key <> %s LIMIT 1""", (user['id'], f"reg:{ep['id']}:publication")).fetchone() is None
        if first_publication:
            # Первое согласие на публикацию: работы видны в галерее сайта и могут выходить в соцсетях лиги.
            # Позже человек сам скрывает их в «Публичности»; новая запись это не перезаписывает.
            # Рейтинг на сайте — по тому же согласию (Политика 1.1: имя, рейтинг и TOP WORK).
            conn.execute('UPDATE users SET public_works=true, public_social=true, public_rating=true WHERE id=%s', (user['id'],))
        if event['season_id']:
            # Участница сезона: по этой записи сайт показывает рейтинг сезона (как у перенесённых из бота).
            conn.execute('''INSERT INTO season_participants(season_id,user_id) VALUES (%s,%s) ON CONFLICT (season_id,user_id) DO NOTHING''',
                         (event['season_id'], user['id']))
        G.audit(conn, user['id'], 'event_participant', ep['id'], 'registered', {'event_id': str(event_id)})
        G.notify(conn, user['id'], 'reg', f"reg:{ep['id']}",
                 {'title': f"Вы записаны на {event['title']}",
                  'text': 'Правила и задания — в кабинете.' + (' Оплата — по условиям Игры.' if paid else ''),
                  'route': 'game', 'event_id': str(event_id)}, event_id)
        return {'event_id': str(event_id), 'mode': R.participation_mode(ep), 'created': True}


# ---------- Мои Игры ----------

def game_summary(conn, game, now, user_id):
    ok = G.rules_ok(conn, user_id, now)
    rounds = V.rounds_view(game, now, rules_ok=ok)
    flags = R.game_flags(game.event, game.mode, game.rounds, game.assignments, game.on_time_ids(), game.by_end_ids(),
                         game.pas, now, more_rounds_planned=len(game.all_round_nos) > len(game.rounds))
    from kabinet.results import service as RS
    result = RS.my_result(conn, game.event['id'], game.ep['id']) if game.ep else None
    return {'event': V.event_brief(game.event), 'me': V.me_view(game), 'flags': flags, 'rules_ok': ok, 'rounds': rounds,
            'result': result}


@router.get('/games')
def my_games(request: Request, user=Depends(browser_user)):
    now = now_of(request)
    out = []
    with db(request).transaction() as conn:
        ids = [r['event_id'] for r in conn.execute('''SELECT p.event_id FROM event_participants p JOIN events e ON e.id=p.event_id
WHERE p.user_id=%s AND p.registration_status<>'cancelled' AND e.status<>'draft' ORDER BY coalesce(e.starts_at, e.created_at) DESC''',
                                                   (user['id'],))]
        for event_id in ids:
            game = G.load(conn, event_id, user['id'], lock=True)
            G.sync_late(conn, game, now)
            out.append(game_summary(conn, game, now, user['id']))
    return {'games': out}


@router.get('/games/{event_id}')
def my_game(event_id: UUID, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game = G.load(conn, event_id, user['id'], lock=True)
        if game.ep is None:
            raise HTTPException(404, 'not_participating')
        G.sync_late(conn, game, now)
        return game_summary(conn, game, now, user['id'])


@router.post('/games/{event_id}/outside', dependencies=[Depends(same_origin)])
def outside(event_id: UUID, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game = G.load(conn, event_id, user['id'], lock=True)
        if game.ep is None:
            raise HTTPException(404, 'not_participating')
        G.choose_outside(conn, game, user['id'], now)
        return game_summary(conn, game, now, user['id'])


# ---------- Задание и работа ----------

def task_response(conn, request, event_id, assignment_id, user_id, now, prepare=False):
    game = G.load(conn, event_id, user_id, lock=True)
    if game.ep is None:
        raise HTTPException(404, 'not_participating')
    G.sync_late(conn, game, now)
    assignment = game.assignment(assignment_id)
    if assignment is None:
        raise HTTPException(404, 'Task not found')
    rnd = game.round_of(assignment)
    if prepare and R.round_opened(rnd, now) and game.mode in (R.IN, R.OUTSIDE) and assignment['id'] not in game.pas:
        try:
            G.materialize(conn, game, assignment)
        except HTTPException:
            pass   # вариант не определён — задание покажется как «ещё не готово»
    return game, assignment


def render_task(conn, request, game, assignment, user_id, now):
    variant = G.variant_for(game, assignment)
    return V.task_view(game, assignment, now, G.rules_ok(conn, user_id, now), root(request), variant)


@router.get('/games/{event_id}/tasks/{assignment_id}')
def task(event_id: UUID, assignment_id: UUID, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game, assignment = task_response(conn, request, event_id, assignment_id, user['id'], now, prepare=True)
        return render_task(conn, request, game, assignment, user['id'], now)


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photos: list[UUID] = Field(default_factory=list, max_length=10)
    link: str | None = Field(default=None, max_length=600)


@router.put('/games/{event_id}/tasks/{assignment_id}/draft', dependencies=[Depends(same_origin)])
def put_draft(event_id: UUID, assignment_id: UUID, body: Draft, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game, assignment = task_response(conn, request, event_id, assignment_id, user['id'], now)
        G.save_draft(conn, game, assignment, body.photos, body.link, user['id'], now)
        game = G.load(conn, event_id, user['id'])
        return render_task(conn, request, game, game.assignment(assignment_id), user['id'], now)


@router.delete('/games/{event_id}/tasks/{assignment_id}/draft', dependencies=[Depends(same_origin)])
def delete_draft(event_id: UUID, assignment_id: UUID, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game, assignment = task_response(conn, request, event_id, assignment_id, user['id'], now)
        G.discard_draft(conn, game, assignment)
        game = G.load(conn, event_id, user['id'])
        return render_task(conn, request, game, game.assignment(assignment_id), user['id'], now)


class Submit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft_id: UUID


@router.post('/games/{event_id}/tasks/{assignment_id}/submit', dependencies=[Depends(same_origin)])
def submit(event_id: UUID, assignment_id: UUID, body: Submit, request: Request, user=Depends(browser_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        game, assignment = task_response(conn, request, event_id, assignment_id, user['id'], now)
        G.submit(conn, game, assignment, body.draft_id, user['id'], now)
        game = G.load(conn, event_id, user['id'])
        return render_task(conn, request, game, game.assignment(assignment_id), user['id'], now)


# ---------- Фото ----------

UPLOAD_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


# Обработка фото — по одной за раз и не в общем потоке запросов: память службы ограничена,
# а остальные страницы не должны ждать, пока уменьшается чужое фото.
PHOTO_LOCK = threading.Semaphore(1)


def store_photo(request, user, data):
    with PHOTO_LOCK:
        try:
            info = request.app.state.media.save_image(data)
        except MediaError as exc:
            raise HTTPException(507 if exc.code == 'storage_full' else 422, exc.code) from None
    with db(request).transaction() as conn:
        # Тот же файл тем же человеком — та же запись (повторная загрузка ничего не дублирует).
        row = conn.execute('''SELECT * FROM media_files WHERE uploaded_by=%s AND sha256=%s AND deleted_at IS NULL
AND storage_key IS NOT NULL ORDER BY created_at LIMIT 1''', (user['id'], info['sha256'])).fetchone()
        if row is None:
            media_id = uuid4()
            # Файл на диске общий для одинаковых фото; ключ записи уникален: «путь#id записи».
            row = conn.execute('''INSERT INTO media_files(id,uploaded_by,storage_key,mime_type,size_bytes,
optimized_storage_key,thumbnail_storage_key,sha256,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                               (media_id, user['id'], f"{info['storage_key']}#{media_id}", info['mime_type'],
                                info['size_bytes'], info['optimized_storage_key'], info['thumbnail_storage_key'],
                                info['sha256'], G.Jsonb({'width': info['width'], 'height': info['height']}))).fetchone()
    return V.photo_view(row, root(request))


@router.post('/uploads', status_code=201, dependencies=[Depends(same_origin)])
async def upload(request: Request, user=Depends(browser_user), auth=Depends(service)):
    settings = request.app.state.settings
    ctype = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
    if ctype not in UPLOAD_TYPES:
        raise HTTPException(415, 'unsupported_format')
    limit = settings.upload_max_mb * 1024 * 1024
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, 'too_large')
    await run_in_threadpool(auth.throttle, 'upload', client_ip(request), str(user['id']), limit=settings.upload_limit, by_ip=False)
    # В памяти службы — не больше UPLOADS_AT_ONCE фото сразу (у срока сдачи их приходят десятки; нагрузочный тест 13.10:
    # 40 одновременных загрузок — 320 МБ при пределе службы 350 МБ). Остальные ждут: тело запроса держит nginx.
    async with upload_gate():
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'too_large')
            chunks.append(chunk)
        data = b''.join(chunks)
        chunks.clear()    # куски больше не нужны: фото ждёт обработки в одном экземпляре, а не в двух
        if not data:
            raise HTTPException(422, 'empty')
        return await run_in_threadpool(store_photo, request, user, data)


UPLOADS_AT_ONCE = 8
_GATES = weakref.WeakKeyDictionary()


def upload_gate():
    """Семафор загрузок своего цикла событий (у сервера цикл один; у тестов их несколько)."""
    loop = asyncio.get_running_loop()
    gate = _GATES.get(loop)
    if gate is None:
        gate = _GATES[loop] = asyncio.Semaphore(UPLOADS_AT_ONCE)
    return gate


@router.get('/media/{media_id}')
def media(media_id: UUID, request: Request, size: str = Query('view', pattern='^(view|thumb)$'), user=Depends(browser_user)):
    with db(request).transaction() as conn:
        row = conn.execute('SELECT * FROM media_files WHERE id=%s AND deleted_at IS NULL', (media_id,)).fetchone()
        staff = conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role IN ('admin','moderator')", (user['id'],)).fetchone()
        # Судья видит фото работ своего пула (замороженная при запуске судейства версия работы).
        judge = row and not staff and row['uploaded_by'] != user['id'] and 'judge' in user['roles'] and conn.execute('''SELECT 1 FROM submission_version_media svm
JOIN evaluation_target_members m ON m.submission_version_id=svm.submission_version_id
JOIN evaluation_targets t ON t.id=m.evaluation_target_id
JOIN evaluation_judge_assignments a ON a.evaluation_stream_id=t.evaluation_stream_id AND a.user_id=%s AND a.status='active'
WHERE svm.media_file_id=%s LIMIT 1''', (user['id'], media_id)).fetchone()
    # Своё фото видит автор; организатор и модератор — любое; судья — работы своего пула. Чужое — как будто его нет.
    if not row or (row['uploaded_by'] != user['id'] and not staff and not judge):
        raise HTTPException(404, 'Not found')
    key = row['optimized_storage_key'] if size == 'view' else row['thumbnail_storage_key']
    path = request.app.state.media.path(key)
    if not path.is_file():
        raise HTTPException(404, 'Not found')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})
