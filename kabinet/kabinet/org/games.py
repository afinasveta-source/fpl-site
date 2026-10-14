"""Кабинет организатора: сезоны, Игры, призы, жизненный цикл Игры.

Жизненный цикл Игры (статусы базы):
  draft (черновик, участницы не видят) → registration («Опубликовать»: Игра в каталоге, запись по датам)
  → active («Начать»: редакция Правил закрепляется за Игрой) → finished («Завершить»: приём работ закрыт у всех).
Вернуть можно: registration → draft (пока никто не записался), finished → active (исправить ошибку).
Черновик без участниц можно удалить. Платные Игры на этом этапе не включаются: оплаты в кабинете ещё нет.
"""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from kabinet.participation import game as G
from kabinet.participation import rules as R
from .common import LEAGUES, WRITE, audit, db, iso, locked_admin, now_of, org_user, problem

router = APIRouter(prefix='/api/org', tags=['organizer'])

EVENT_TYPES = ('ranked_game', 'challenge', 'final', 'special')
# Что нельзя менять после старта Игры: от этого зависят рейтинг, зачёт и уже принятые работы.
LOCKED_AFTER_START = ('event_type', 'season_id', 'game_no', 'affects_rating', 'counts_for_final', 'awards_points',
                      'has_diploma')
DATE_FIELDS = ('registration_opens_at', 'registration_closes_at', 'starts_at', 'ends_at')


def clean_text(value, required=False):
    if value is None:
        return None
    value = value.strip()
    if not value:
        if required:
            raise ValueError('Required')
        return None
    return value


# ---------- Сезоны ----------

class SeasonIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=150)
    season_no: int | None = Field(default=None, ge=1, le=99)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None

    @field_validator('name')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)


def season_view(s, games=0):
    return {'id': str(s['id']), 'name': s['name'], 'season_no': s['season_no'], 'starts_at': iso(s['starts_at']),
            'ends_at': iso(s['ends_at']), 'status': s['status'], 'games': games}


def check_season_dates(starts, ends):
    if starts is not None and ends is not None and ends <= starts:
        raise problem('season_dates')


@router.get('/seasons')
def seasons(request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT s.*, (SELECT count(*) FROM events e WHERE e.season_id=s.id) AS games
FROM seasons s ORDER BY s.season_no NULLS LAST, s.created_at''').fetchall()
    return {'seasons': [season_view(s, s['games']) for s in rows]}


@router.post('/seasons', status_code=201, dependencies=WRITE)
def create_season(body: SeasonIn, request: Request, user=Depends(org_user)):
    check_season_dates(body.starts_at, body.ends_at)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        if body.season_no is not None and conn.execute('SELECT 1 FROM seasons WHERE season_no=%s', (body.season_no,)).fetchone():
            raise problem('season_no_taken', 409)
        s = conn.execute('''INSERT INTO seasons(name,season_no,starts_at,ends_at,status) VALUES (%s,%s,%s,%s,'active')
RETURNING *''', (body.name, body.season_no, body.starts_at, body.ends_at)).fetchone()
        audit(conn, user['id'], 'season', s['id'], 'season_created', {'name': body.name})
        return season_view(s)


@router.patch('/seasons/{season_id}', dependencies=WRITE)
def change_season(season_id: UUID, body: SeasonIn, request: Request, user=Depends(org_user)):
    check_season_dates(body.starts_at, body.ends_at)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        if not conn.execute('SELECT 1 FROM seasons WHERE id=%s FOR UPDATE', (season_id,)).fetchone():
            raise HTTPException(404, 'Season not found')
        if body.season_no is not None and conn.execute('SELECT 1 FROM seasons WHERE season_no=%s AND id<>%s',
                                                       (body.season_no, season_id)).fetchone():
            raise problem('season_no_taken', 409)
        s = conn.execute('UPDATE seasons SET name=%s, season_no=%s, starts_at=%s, ends_at=%s WHERE id=%s RETURNING *',
                         (body.name, body.season_no, body.starts_at, body.ends_at, season_id)).fetchone()
        audit(conn, user['id'], 'season', season_id, 'season_changed', {'name': body.name})
        return season_view(s)


# ---------- Игры ----------

class EventCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    season_id: UUID | None = None
    event_type: Literal['ranked_game', 'challenge', 'final', 'special'] = 'ranked_game'

    @field_validator('title')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)


class EventChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    event_type: Literal['ranked_game', 'challenge', 'final', 'special'] | None = None
    season_id: UUID | None = None
    game_no: int | None = Field(default=None, ge=1, le=99)
    registration_opens_at: AwareDatetime | None = None
    registration_closes_at: AwareDatetime | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    affects_rating: bool | None = None
    has_diploma: bool | None = None
    awards_points: bool | None = None
    counts_for_final: bool | None = None

    @field_validator('title')
    @classmethod
    def trim_title(cls, value):
        return clean_text(value, required=True) if value is not None else None

    @field_validator('description')
    @classmethod
    def trim_description(cls, value):
        return clean_text(value)


def mode_counts(conn, event_id):
    counts = {}
    for ep in conn.execute('SELECT * FROM event_participants WHERE event_id=%s', (event_id,)):
        mode = R.participation_mode(ep)
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def current_docs(conn, now):
    return {kind: G.current_document(conn, kind, now) for kind in ('rules', 'publication', 'personal_data')}


def non_draft_rounds(conn, event_id):
    return conn.execute("SELECT * FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no", (event_id,)).fetchall()


def numbering_problems(conn, e):
    """Номер диплома строится из номера сезона и номера Игры — после старта их не поменять, поэтому нужны до старта."""
    if not e['has_diploma']:
        return []
    out = []
    season = conn.execute('SELECT season_no FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
    if season is None or season['season_no'] is None:
        out.append('no_season_number')
    if e['game_no'] is None:
        out.append('no_game_number')
    return out


def event_checks(conn, e, now):
    """Что мешает следующему шагу Игры (problems) и на что обратить внимание (warnings)."""
    problems, warnings = [], []
    docs = current_docs(conn, now)
    rounds = non_draft_rounds(conn, e['id'])
    all_rounds = conn.execute('SELECT round_no, status FROM rounds WHERE event_id=%s', (e['id'],)).fetchall()
    if e['status'] == 'draft':
        for field in ('starts_at', 'ends_at', 'registration_closes_at'):
            if e[field] is None:
                problems.append('missing_' + field)
        if docs['rules'] is None:
            problems.append('no_rules')
        if docs['publication'] is None:
            problems.append('no_publication')
        if docs['personal_data'] is None:
            warnings.append('no_personal_data')
        if not rounds:
            warnings.append('no_rounds')
        warnings.extend(numbering_problems(conn, e))
        if e['registration_closes_at'] and e['ends_at'] and e['registration_closes_at'] > e['ends_at']:
            warnings.append('registration_after_end')
    elif e['status'] == 'registration':
        if docs['rules'] is None:
            problems.append('no_rules')
        warnings.extend(numbering_problems(conn, e))
        if not rounds:
            warnings.append('no_rounds')
        if any(r['status'] == 'draft' for r in all_rounds):
            warnings.append('draft_rounds')
        if e['starts_at'] and e['starts_at'] > now:
            warnings.append('starts_later')
    elif e['status'] == 'active':
        from .rounds import league_dates, round_state
        dates = {r['id']: league_dates(conn, r['id']) for r in rounds}
        if any(round_state(r, now, dates[r['id']]) == 'open' for r in rounds):
            warnings.append('rounds_accepting')
        # Впереди — тур, который ещё не открылся хотя бы одной лиге (или общей датой).
        ahead = any(r['status'] not in R.OPENED and any(d is None or d > now for d in [r['opens_at']] + dates[r['id']]['opens'])
                    for r in rounds)
        if ahead or any(r['status'] == 'draft' for r in all_rounds):
            warnings.append('rounds_ahead')
        warnings.append('results_not_ready')
    return {'problems': problems, 'warnings': warnings}


def locked_fields(e):
    """Что уже не поменять после старта. Пустые сезон и номер Игры можно дописать до публикации итогов."""
    published = ((e['settings'] or {}).get('results') or {}).get('published_at')
    return [k for k in LOCKED_AFTER_START if published or k not in ('season_id', 'game_no') or e[k] is not None]


def event_view(e, season=None):
    started = e['status'] in ('active', 'finished', 'archived')
    return {'id': str(e['id']), 'title': e['title'], 'description': e['description'], 'type': e['event_type'],
            'status': e['status'], 'season_id': str(e['season_id']) if e['season_id'] else None,
            'season': season['name'] if season else None, 'game_no': e['game_no'],
            'registration_opens_at': iso(e['registration_opens_at']), 'registration_closes_at': iso(e['registration_closes_at']),
            'starts_at': iso(e['starts_at']), 'ends_at': iso(e['ends_at']), 'completion_deadline': iso(R.game_deadline(e)),
            'affects_rating': e['affects_rating'], 'has_diploma': e['has_diploma'], 'awards_points': e['awards_points'],
            'counts_for_final': e['counts_for_final'], 'payment_required': e['payment_required'],
            'locked': locked_fields(e) if started else [],
            'site_rating_live': bool((e['settings'] or {}).get('site_rating_live')),
            'readonly': e['status'] in ('finished', 'archived')}


def round_brief(conn, r, now):
    from .rounds import league_dates, round_state
    task = conn.execute('''SELECT a.id, a.title FROM assignments a WHERE a.round_id=%s
ORDER BY (a.assignment_type='competition_work') DESC, a.code LIMIT 1''', (r['id'],)).fetchone()
    sent = 0
    if task:
        sent = conn.execute('''SELECT count(*) AS n FROM submissions s JOIN participant_assignments pa ON pa.id=s.participant_assignment_id
WHERE pa.assignment_id=%s AND pa.active AND s.deleted_at IS NULL AND s.latest_version_id IS NOT NULL''', (task['id'],)).fetchone()['n']
    return {'id': str(r['id']), 'round_no': r['round_no'], 'title': r['title'], 'status': r['status'],
            'state': round_state(r, now, league_dates(conn, r['id'])), 'opens_at': iso(r['opens_at']), 'deadline': iso(r['deadline']),
            'judging_deadline': iso(r['judging_deadline']), 'task_title': task['title'] if task else None, 'sent': sent}


def current_event(conn):
    """«Текущая» Игра для организатора: идущая (самая поздняя по старту), иначе опубликованная с записью,
    иначе последняя завершённая, иначе последний черновик. Её показывают «Игры и туры» сверху и фильтры «Людей»."""
    return conn.execute('''SELECT * FROM events ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'registration' THEN 1
  WHEN 'finished' THEN 2 WHEN 'archived' THEN 3 ELSE 4 END, coalesce(starts_at, created_at) DESC, created_at DESC LIMIT 1''').fetchone()


def load_event(conn, event_id, lock=False):
    e = conn.execute('SELECT * FROM events WHERE id=%s' + (' FOR UPDATE' if lock else ''), (event_id,)).fetchone()
    if not e:
        raise HTTPException(404, 'Game not found')
    return e


def event_detail(conn, e, now):
    season = conn.execute('SELECT * FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
    rounds = conn.execute('SELECT * FROM rounds WHERE event_id=%s ORDER BY round_no', (e['id'],)).fetchall()
    prizes = conn.execute('SELECT criterion, prize, league FROM event_prizes WHERE event_id=%s ORDER BY sort_order, created_at',
                          (e['id'],)).fetchall()
    rules = conn.execute('SELECT version FROM legal_documents WHERE id=%s', (e['rules_document_id'],)).fetchone() \
        if e['rules_document_id'] else None
    return event_view(e, season) | {
        'rules_version': rules['version'] if rules else None,
        'rounds': [round_brief(conn, r, now) for r in rounds],
        'prizes': [dict(p) for p in prizes],
        'participants': mode_counts(conn, e['id']),
        'checks': event_checks(conn, e, now)}


@router.get('/events')
def events(request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT e.*, s.name AS season_name,
  (SELECT count(*) FROM event_participants p WHERE p.event_id=e.id AND p.registration_status<>'cancelled') AS people,
  (SELECT count(*) FROM rounds r WHERE r.event_id=e.id) AS rounds
FROM events e LEFT JOIN seasons s ON s.id=e.season_id
ORDER BY CASE e.status WHEN 'active' THEN 0 WHEN 'registration' THEN 1 WHEN 'draft' THEN 2 ELSE 3 END,
  coalesce(e.starts_at, e.created_at) DESC''').fetchall()
    return {'events': [event_view(e, {'name': e['season_name']} if e['season_name'] else None)
                       | {'people': e['people'], 'rounds_count': e['rounds']} for e in rows]}


@router.post('/events', status_code=201, dependencies=WRITE)
def create_event(body: EventCreate, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        if body.season_id and not conn.execute('SELECT 1 FROM seasons WHERE id=%s', (body.season_id,)).fetchone():
            raise problem('season_not_found', 404)
        ranked = body.event_type == 'ranked_game'
        e = conn.execute('''INSERT INTO events(event_type,status,title,season_id,official_timezone,affects_rating,awards_points,
has_diploma,created_by) VALUES (%s,'draft',%s,%s,'Europe/Moscow',%s,%s,true,%s) RETURNING *''',
                         (body.event_type, body.title, body.season_id, ranked, ranked, user['id'])).fetchone()
        audit(conn, user['id'], 'event', e['id'], 'event_created', {'title': body.title})
        return event_detail(conn, e, now_of(request))


@router.get('/events/{event_id}')
def event(event_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return event_detail(conn, load_event(conn, event_id), now_of(request))


def validate_dates(conn, e, values):
    merged = {k: values.get(k, e[k]) for k in DATE_FIELDS}
    if merged['registration_opens_at'] and merged['registration_closes_at'] \
            and merged['registration_closes_at'] <= merged['registration_opens_at']:
        raise problem('registration_dates')
    if merged['starts_at'] and merged['ends_at'] and merged['ends_at'] <= merged['starts_at']:
        raise problem('game_dates')
    if 'ends_at' in values and merged['ends_at'] is not None:
        late = conn.execute('''SELECT round_no FROM rounds WHERE event_id=%s AND status<>'draft' AND deadline > %s
ORDER BY round_no LIMIT 1''', (e['id'], merged['ends_at'])).fetchone()
        if late:
            raise problem('rounds_after_end')
        # свои сроки лиг и личные продления тоже должны уложиться в Игру
        end = merged['ends_at']
        for v in conn.execute('''SELECT v.* FROM assignment_variants v JOIN assignments a ON a.id=v.assignment_id
WHERE a.event_id=%s AND v.active''', (e['id'],)):
            if (R.variant_deadline(v) and R.variant_deadline(v) > end) or (R.variant_opens_at(v) and R.variant_opens_at(v) >= end):
                raise problem('league_dates_after_end')
        if conn.execute('''SELECT 1 FROM participant_assignments WHERE event_id=%s AND active AND deadline_override > %s LIMIT 1''',
                        (e['id'], end)).fetchone():
            raise problem('personal_deadlines_after_end')


@router.patch('/events/{event_id}', dependencies=WRITE)
def change_event(event_id: UUID, body: EventChange, request: Request, user=Depends(org_user)):
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise problem('nothing_to_change')
    if 'title' in values and values['title'] is None:
        raise problem('title_required')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        if e['status'] in ('finished', 'archived') and set(values) - {'title', 'description', 'season_id', 'game_no'}:
            raise problem('game_finished', 409)
        if e['status'] in ('active', 'finished', 'archived'):
            # сезон и номер Игры можно дописать после старта, если их не было (нужны для номеров дипломов), — до итогов
            fill = {'season_id', 'game_no'} if not ((e['settings'] or {}).get('results') or {}).get('published_at') else set()
            blocked = [k for k in LOCKED_AFTER_START if k in values and values[k] != e[k] and not (k in fill and e[k] is None)]
            if blocked:
                raise problem('locked_after_start', 409)
        if e['status'] != 'draft':
            for k in DATE_FIELDS:
                if k in values and values[k] is None and e[k] is not None:
                    raise problem('date_required', 422)
        kind = values.get('event_type', e['event_type'])
        if values.get('counts_for_final') and kind != 'ranked_game':
            raise problem('final_only_ranked')
        if 'event_type' in values and kind != 'ranked_game' and e['counts_for_final'] and 'counts_for_final' not in values:
            values['counts_for_final'] = False
        if values.get('season_id') and not conn.execute('SELECT 1 FROM seasons WHERE id=%s', (values['season_id'],)).fetchone():
            raise problem('season_not_found', 404)
        season = values.get('season_id', e['season_id'])
        game_no = values.get('game_no', e['game_no'])
        if game_no is not None and ('game_no' in values or 'season_id' in values) and conn.execute(
                'SELECT 1 FROM events WHERE season_id IS NOT DISTINCT FROM %s AND game_no=%s AND id<>%s',
                (season, game_no, event_id)).fetchone():
            raise problem('game_no_taken', 409)
        validate_dates(conn, e, values)
        if 'ends_at' in values:
            # Срок всех работ вне конкурса — конец Игры (отдельного поля у организатора нет).
            values['completion_deadline'] = values['ends_at']
        sets = ', '.join(f'{k}=%({k})s' for k in values)
        e = conn.execute(f'UPDATE events SET {sets} WHERE id=%(id)s RETURNING *', values | {'id': event_id}).fetchone()
        audit(conn, user['id'], 'event', event_id, 'event_changed',
              {k: (iso(v) if hasattr(v, 'isoformat') else str(v) if isinstance(v, UUID) else v) for k, v in values.items()})
        return event_detail(conn, e, now_of(request))


class PrizeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    criterion: str = Field(min_length=1, max_length=200)
    prize: str = Field(min_length=1, max_length=200)
    league: Literal['bronze', 'silver', 'gold'] | None = None

    @field_validator('criterion', 'prize')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)


class PrizesIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[PrizeIn] = Field(default_factory=list, max_length=30)


@router.put('/events/{event_id}/prizes', dependencies=WRITE)
def put_prizes(event_id: UUID, body: PrizesIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        conn.execute('DELETE FROM event_prizes WHERE event_id=%s', (event_id,))
        for i, p in enumerate(body.items):
            conn.execute('INSERT INTO event_prizes(event_id,sort_order,criterion,prize,league) VALUES (%s,%s,%s,%s,%s)',
                         (event_id, i, p.criterion, p.prize, p.league))
        audit(conn, user['id'], 'event', event_id, 'prizes_changed', {'count': len(body.items)})
        return event_detail(conn, e, now_of(request))


class StatusChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['publish', 'unpublish', 'start', 'finish', 'reopen']
    early: bool = False   # «завершить раньше конца Игры» — организатор подтвердил, что сдача вне конкурса закроется


TRANSITIONS = {'publish': ('draft', 'registration'), 'unpublish': ('registration', 'draft'),
               'start': ('registration', 'active'), 'finish': ('active', 'finished'), 'reopen': ('finished', 'active')}


@router.post('/events/{event_id}/status', dependencies=WRITE)
def change_status(event_id: UUID, body: StatusChange, request: Request, user=Depends(org_user)):
    now = now_of(request)
    source, target = TRANSITIONS[body.action]
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        if e['status'] != source:
            raise problem('wrong_status', 409)
        if body.action in ('publish', 'start'):
            checks = event_checks(conn, e, now)
            if checks['problems']:
                raise problem(checks['problems'][0], 409)
        if body.action == 'finish' and not body.early:
            end = R.game_deadline(e)
            if end is not None and now < end:
                raise problem('game_not_over', 409)   # до конца Игры работы вне конкурса ещё принимаются (дипломы)
        if body.action == 'reopen' and ((e['settings'] or {}).get('results') or {}).get('published_at'):
            raise problem('results_published', 409)   # итоги, очки и дипломы выданы — Игру не вернуть в работу
        if body.action == 'unpublish' and conn.execute('SELECT 1 FROM event_participants WHERE event_id=%s LIMIT 1',
                                                       (event_id,)).fetchone():
            raise problem('has_participants', 409)
        extra = ''
        args = {'id': event_id, 'status': target}
        if body.action == 'start':
            extra = ', rules_document_id=%(rules)s'
            args['rules'] = G.rules_document(conn, now)['id']
        e = conn.execute(f'UPDATE events SET status=%(status)s{extra} WHERE id=%(id)s RETURNING *', args).fetchone()
        if body.action == 'start' and e['season_id']:
            # сезон начался с первой Игрой — сайт показывает рейтинг только идущих и завершённых сезонов
            conn.execute("UPDATE seasons SET status='active' WHERE id=%s AND status='draft'", (e['season_id'],))
        audit(conn, user['id'], 'event', event_id, 'event_' + body.action, {'from': source, 'to': target})
        return event_detail(conn, e, now)


class SiteRatingIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    live: bool


@router.post('/events/{event_id}/site-rating', dependencies=WRITE)
def site_rating(event_id: UUID, body: SiteRatingIn, request: Request, user=Depends(org_user)):
    """Рейтинг на сайте во время этой Игры (17.10). По умолчанию (Правила, п. 7.3; решение 13.10) сайт показывает рейтинг
    на начало идущей Игры, а новый — после её конца. Организатор может разрешить показывать текущий рейтинг (после каждого
    опубликованного тура) — флаг settings.site_rating_live этой Игры; его читает выгрузка сайта (server/db/site_views.sql)."""
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        if e['event_type'] != 'ranked_game':
            raise problem('not_ranked', 409)
        e = conn.execute('''UPDATE events SET settings = coalesce(settings, '{}'::jsonb) || jsonb_build_object('site_rating_live', %s::boolean)
WHERE id=%s RETURNING *''', (body.live, event_id)).fetchone()
        audit(conn, user['id'], 'event', event_id, 'site_rating_live', {'live': body.live})
        return event_detail(conn, e, now_of(request))


@router.delete('/events/{event_id}', status_code=204, dependencies=WRITE)
def delete_event(event_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        if e['status'] != 'draft':
            raise problem('not_draft', 409)
        if conn.execute('SELECT 1 FROM event_participants WHERE event_id=%s LIMIT 1', (event_id,)).fetchone():
            raise problem('has_participants', 409)
        # Черновик: всё, что под ним (туры, задания, призы), создано организатором и ещё никому не выдано.
        try:
            with conn.transaction():   # точка сохранения: на Игру ссылаются другие записи — понятный отказ, а не сбой
                conn.execute('''DELETE FROM assignment_variants WHERE assignment_id IN (SELECT id FROM assignments WHERE event_id=%s)''',
                             (event_id,))
                conn.execute('DELETE FROM assignments WHERE event_id=%s', (event_id,))
                conn.execute('DELETE FROM rounds WHERE event_id=%s', (event_id,))
                conn.execute('DELETE FROM event_prizes WHERE event_id=%s', (event_id,))
                conn.execute('DELETE FROM events WHERE id=%s', (event_id,))
        except psycopg.errors.ForeignKeyViolation:
            raise problem('has_links', 409) from None
        audit(conn, user['id'], 'event', None, 'event_deleted', {'id': str(event_id), 'title': e['title']})
    return None
