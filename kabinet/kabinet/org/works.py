"""Организатор загружает работу за участницу (15.10): участница прислала фото организатору, а не сдала в кабинете.

Два шага, как у участницы: фото (POST /api/org/participants/{ep}/upload, тело — сам файл JPG/PNG/WebP) — запись фото
на участницу (uploaded_by — она, в metadata — source admin и кто загрузил); затем работа тура
(POST /api/org/participants/{ep}/rounds/{round}/work): сданная версия source='admin', created_by — организатор.
- «Засчитать как сданную в срок» (по умолчанию): is_on_time — да; в конкурс — если она в конкурсе (или её вернули).
  Сверка опоздавших по этому туру её больше не переведёт (тур считается сданным в срок). Если её уже перевели вне конкурса
  из-за этого тура (elimination_reason late, eliminated_round — этот тур) и других пропусков нет — возвращается в конкурс,
  как действием «Вернуть в конкурс».
- Без отметки — как обычная сдача сейчас (после срока: вне конкурса / для диплома).
- Нельзя: туры из бота (там своё — фото из бота), тур с опубликованными итогами, тур, судейство лиги которого уже идёт
  (работа не попала бы к судьям; 409 judging_started).
Черновик участницы этого тура (если был) заменяется — запись в журнале.
"""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from kabinet.participation import game as G
from kabinet.participation import rules as R
from kabinet.participation import views as V
from kabinet.participation.media import MediaError
from kabinet.participation.routes import PHOTO_LOCK, UPLOAD_TYPES, upload_gate
from .common import Jsonb, WRITE, db, iso, locked_admin, notify, now_of, org_user, problem
from .games import clean_text, load_event
from .participants import guard_event, load_ep, participant_detail

router = APIRouter(prefix='/api/org', tags=['organizer'])


def store(request, ep_id, actor, data):
    with db(request).transaction() as conn:
        ep = load_ep(conn, ep_id)
    with PHOTO_LOCK:
        try:
            info = request.app.state.media.save_image(data)
        except MediaError as exc:
            raise HTTPException(507 if exc.code == 'storage_full' else 422, exc.code) from None
    with db(request).transaction() as conn:
        locked_admin(conn, actor)
        uid = ep['user_id']
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"media:{uid}:{info['sha256']}",))
        row = conn.execute('''SELECT * FROM media_files WHERE uploaded_by=%s AND sha256=%s AND deleted_at IS NULL
AND storage_key IS NOT NULL ORDER BY created_at LIMIT 1''', (uid, info['sha256'])).fetchone()
        if row is None:
            media_id = uuid4()
            row = conn.execute('''INSERT INTO media_files(id,uploaded_by,storage_key,mime_type,size_bytes,optimized_storage_key,
thumbnail_storage_key,sha256,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                               (media_id, uid, f"{info['storage_key']}#{media_id}", info['mime_type'], info['size_bytes'],
                                info['optimized_storage_key'], info['thumbnail_storage_key'], info['sha256'],
                                Jsonb({'width': info['width'], 'height': info['height'], 'source': 'admin',
                                       'uploaded_by_admin': str(actor['id'])}))).fetchone()
    return V.photo_view(row, request.app.state.settings.root_path)


@router.post('/participants/{ep_id}/upload', status_code=201, dependencies=WRITE)
async def upload(ep_id: UUID, request: Request, user=Depends(org_user)):
    settings = request.app.state.settings
    ctype = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
    if ctype not in UPLOAD_TYPES:
        raise HTTPException(415, 'unsupported_format')
    limit = settings.upload_max_mb * 1024 * 1024
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, 'too_large')
    async with upload_gate():
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'too_large')
            chunks.append(chunk)
        data = b''.join(chunks)
        chunks.clear()
        if not data:
            raise HTTPException(422, 'empty')
        return await run_in_threadpool(store, request, ep_id, user, data)


class WorkIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photos: list[UUID] = Field(min_length=1, max_length=10)
    link: str | None = Field(default=None, max_length=600)
    on_time: bool = True
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim(cls, value):
        value = clean_text(value)
        if value is None:
            raise ValueError('Reason is required')
        return value


def judging_started(conn, rnd, league):
    """Судейство тура уже идёт для её лиги (или общее для всех лиг)."""
    return conn.execute('''SELECT 1 FROM evaluation_streams WHERE round_id=%s AND active
AND (league IS NULL OR league=%s) LIMIT 1''', (rnd['id'], league)).fetchone() is not None


@router.post('/participants/{ep_id}/rounds/{round_id}/work', dependencies=WRITE)
def work(ep_id: UUID, round_id: UUID, body: WorkIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        ep = load_ep(conn, ep_id, lock=True)
        guard_event(load_event(conn, ep['event_id']))
        game = G.load(conn, ep['event_id'], ep['user_id'], lock=True)
        rnd = next((r for r in game.rounds if str(r['id']) == str(round_id)), None)
        if rnd is None or not game.assignments.get(rnd['id']):
            raise problem('round_not_found', 404)
        if R.bot_round(rnd):
            raise problem('bot_round', 409)
        if rnd['status'] == 'published':
            raise problem('round_published', 409)
        if not R.round_opened(rnd, now):
            raise problem('not_open', 409)
        if game.mode not in (R.IN, R.OUTSIDE, R.OUT_PENDING):
            raise problem('not_participating', 409)
        if judging_started(conn, rnd, ep['entry_league']):
            raise problem('judging_started', 409)
        a = game.assignments[rnd['id']][0]
        form = G.form_of(game, a)
        if form is None:
            raise problem('task_not_ready', 409)
        link = G.clean_link(body.link)
        photos = G.own_media(conn, ep['user_id'], body.photos)       # фото — участницы (загружены на неё)
        if len(photos) > form['photo_max']:
            raise problem('too_many_photos')
        if form['link'] == 'none' and link:
            raise problem('link_not_accepted')
        pa = G.materialize(conn, game, a)                             # задание её лиги (вариант по лиге)
        sub = G.ensure_submission(conn, game, a)
        draft = conn.execute('SELECT id FROM submission_versions WHERE submission_id=%s AND submitted_at IS NULL FOR UPDATE',
                             (sub['id'],)).fetchone()
        if draft:                                                     # её несданный черновик заменяется работой от организатора
            conn.execute('DELETE FROM submission_version_media WHERE submission_version_id=%s', (draft['id'],))
            conn.execute('DELETE FROM submission_versions WHERE id=%s', (draft['id'],))
        no = conn.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM submission_versions WHERE submission_id=%s', (sub['id'],)).fetchone()['n']
        v = conn.execute('''INSERT INTO submission_versions(submission_id,version_no,payload,source,created_by,created_at)
VALUES (%s,%s,%s,'admin',%s,%s) RETURNING *''', (sub['id'], no, Jsonb({'link': link}), user['id'], now)).fetchone()
        for i, mid in enumerate(photos):
            conn.execute("INSERT INTO submission_version_media VALUES (%s,%s,'photo',%s)", (v['id'], mid, i))
        conn.execute('UPDATE submission_versions SET submitted_at=%s, is_final_submit=true WHERE id=%s', (now, v['id']))
        # вернуть в конкурс, если вне конкурса она именно из-за этого тура и других пропущенных туров нет
        restorable = body.on_time and ep['competition_status'] == 'diploma_only' and ep['elimination_reason'] == 'late' \
            and ep['eliminated_round_id'] == rnd['id'] and R.missed_round(
                game.event, game.rounds, game.assignments, game.on_time_ids() | {a['id']}, game.pas, now) is None
        if body.on_time:
            deadline, source = R.competition_deadline(rnd, a, pa)
            marks = {'is_on_time': True, 'deadline_applied_at': deadline or now, 'deadline_source': source or 'completion',
                     'counts_for_competition': game.mode == R.IN or restorable, 'counts_for_diploma': True}
        else:
            marks = R.submission_marks(game.event, rnd, a, pa, game.mode, now, sub['first_submitted_at'])
        conn.execute('''UPDATE submissions SET latest_version_id=%(v)s,
  competition_version_id = CASE WHEN %(comp)s THEN %(v)s ELSE competition_version_id END,
  diploma_version_id = CASE WHEN %(dip)s THEN %(v)s ELSE diploma_version_id END,
  status = CASE WHEN %(on_time)s THEN 'submitted' ELSE 'late' END,
  first_submitted_at = coalesce(first_submitted_at, %(now)s), last_submitted_at=%(now)s,
  is_on_time = %(on_time)s OR coalesce(is_on_time, false), deadline_applied_at=%(dl)s, deadline_source=%(src)s,
  counts_for_competition = CASE WHEN %(comp)s THEN true ELSE coalesce(counts_for_competition, false) END,
  counts_for_diploma=%(dip)s WHERE id=%(id)s''',
                     {'v': v['id'], 'comp': marks['counts_for_competition'], 'dip': marks['counts_for_diploma'],
                      'on_time': marks['is_on_time'], 'now': now, 'dl': marks['deadline_applied_at'],
                      'src': marks['deadline_source'], 'id': sub['id']})
        restored = bool(restorable)
        if restored:
            conn.execute('''UPDATE event_participants SET competition_status='active', elimination_reason=NULL,
eliminated_round_id=NULL, out_of_competition_at=NULL, out_of_competition_source=NULL WHERE id=%s''', (ep['id'],))
        conn.execute('''INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,after_data,reason)
VALUES (%s,'event_participant',%s,'org_work_uploaded',%s,%s)''',
                     (user['id'], ep['id'], Jsonb({'round_no': rnd['round_no'], 'version_no': no, 'photos': len(photos), 'on_time': body.on_time,
                                                   'restored': restored, 'draft_replaced': bool(draft)}), body.reason))
        notify(conn, ep['user_id'], 'sent', f"org-work:{v['id']}",
               {'title': f"Организатор загрузил вашу работу тура {rnd['round_no']}",
                'text': ('Работа засчитана как сданная в срок.' if body.on_time else 'Работа сдана.') +
                        (' Вы снова в конкурсе.' if restored else ''),
                'route': 'task', 'event_id': str(ep['event_id']), 'assignment_id': str(a['id'])}, ep['event_id'], rnd['id'])
        return participant_detail(conn, load_ep(conn, ep_id), request, now) | {'uploaded': {'round_no': rnd['round_no'],
                                                                                            'restored': restored, 'at': iso(now)}}
