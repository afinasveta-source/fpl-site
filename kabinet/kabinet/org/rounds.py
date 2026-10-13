"""Кабинет организатора: туры и задание тура.

Тур: черновик (участницы не видят) → «Опубликовать» (виден в плане Игры; задание откроется в дату открытия)
→ открыт по дате (или «Открыть сейчас») → приём закрывается в срок сдачи. Черновик последнего тура можно удалить.

Задание тура: общее (название и текст) и, если нужно, отдельное для лиги (Bronze / Silver / Gold) — своё название, текст,
своё открытие задания и свой срок сдачи (по умолчанию — даты тура; хранятся в release_rules.opens_at / .deadline варианта).
Текст лиги пустой — лига получает общий текст (копия в варианте, release_rules.same_text; обновляется вместе с общим).
«Открыть сейчас» открывает задание всем лигам сразу.
Участнице выдаётся текст её лиги, а если его нет — общий (правило выбора — participation/rules.pick_variant).
Форма сдачи (фото / ссылка / сколько фото) и набор лиг не меняются после открытия тура: участницы уже сдают по ним.
Текст задания после открытия исправить можно: участницы, уже получившие задание, видят новый текст и уведомление.
"""
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from kabinet.participation import rules as R
from .common import LEAGUES, WRITE, Jsonb, audit, db, iso, locked_admin, notify, now_of, org_user, problem
from .games import clean_text, event_detail, load_event

router = APIRouter(prefix='/api/org', tags=['organizer'])
DEFAULT_FORM = {'photo': 'required', 'link': 'required', 'photo_max': 1}   # ссылка на пост обязательна по умолчанию (Правила: работа сдана, когда есть фото и ссылка; решение 13.10)
FIELD = Literal['required', 'optional', 'none']


def round_state(r, now, dates=None):
    """Как тур выглядит организатору: draft / plan (опубликован, ещё не открыт) / open (идёт сдача) / closed.
    dates — свои даты лиг (league_dates): тур открыт, когда открылся хотя бы одной лиге, закрыт — после самого позднего срока."""
    if r['status'] == 'draft':
        return 'draft'
    dates = dates or {'opens': [], 'deadlines': []}
    first = min([d for d in [r['opens_at']] + dates['opens'] if d is not None], default=None)
    if r['status'] not in R.OPENED and (first is None or first > now):
        return 'plan'
    ends = [d for d in [r['deadline']] + dates['deadlines'] if d is not None]
    end = max(ends) if ends else None
    if r['status'] in R.ACCEPTANCE_OVER or (end is not None and now > end):
        return 'closed'
    return 'open'


def round_variants(conn, round_id):
    return conn.execute('''SELECT v.* FROM assignment_variants v JOIN assignments a ON a.id=v.assignment_id
WHERE a.round_id=%s AND v.active''', (round_id,)).fetchall()


def league_dates(conn, round_id):
    """Свои даты лиг тура: {'opens': [...], 'deadlines': [...]} — только заданные."""
    rows = round_variants(conn, round_id)
    return {'opens': [d for d in (R.variant_opens_at(v) for v in rows) if d is not None],
            'deadlines': [d for d in (R.variant_deadline(v) for v in rows) if d is not None]}


def opened(conn, r, now):
    """Задание тура уже открыто хотя бы одной лиге: дальше форма сдачи и набор лиг не меняются."""
    return r['status'] != 'draft' and R.round_opened_any(r, round_variants(conn, r['id']), now)


def all_opened(conn, r, now):
    """Задание открыто всем: по общей дате и каждой лиге со своей датой."""
    if r['status'] == 'draft':
        return False
    return R.round_opened(r, now) and all(R.round_opened(R.effective_round(r, v), now) for v in round_variants(conn, r['id']))


def notify_deadline(conn, e, r, league=None, own_leagues=()):
    """Срок сдачи открытого тура изменён — сообщение тем, кого он касается: лиге со своим сроком (league)
    или всем остальным (общий срок: без лиги и лиги без своего срока)."""
    if league:
        rows = conn.execute('''SELECT id, user_id FROM event_participants WHERE event_id=%s AND registration_status='participating'
AND entry_league=%s''', (e['id'], league)).fetchall()
    else:
        rows = conn.execute('''SELECT id, user_id FROM event_participants WHERE event_id=%s AND registration_status='participating'
AND (entry_league IS NULL OR NOT entry_league = ANY(%s))''', (e['id'], list(own_leagues))).fetchall()
    stamp = uuid4().hex[:12]
    for p in rows:
        notify(conn, p['user_id'], 'deadline', f"round-deadline:{r['id']}:{stamp}:{p['id']}",
               {'title': f"Срок сдачи тура {r['round_no']} изменён", 'text': 'Новый срок — в задании тура.',
                'route': 'game', 'event_id': str(e['id'])}, e['id'], r['id'])
    return len(rows)


def own_deadline_leagues(conn, r):
    return [variant_league(v) for v in round_variants(conn, r['id']) if variant_league(v) and R.variant_deadline(v)]


def general_opened(r, now):
    """Открыто по общей дате тура: общую дату открытия уже не поменять."""
    return r['status'] != 'draft' and R.round_opened(r, now)


def load_round(conn, round_id, lock=False):
    r = conn.execute('SELECT * FROM rounds WHERE id=%s' + (' FOR UPDATE' if lock else ''), (round_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'Round not found')
    return r


def main_task(conn, r):
    return conn.execute('''SELECT * FROM assignments WHERE round_id=%s
ORDER BY (assignment_type='competition_work') DESC, code LIMIT 1''', (r['id'],)).fetchone()


def localized(value):
    if isinstance(value, dict):
        return value.get('ru') or next(iter(value.values()), '')
    return value or ''


def variant_league(v):
    leagues = (v['audience_rules'] or {}).get('leagues') or []
    return leagues[0] if len(leagues) == 1 else None


def form_of(v):
    schema = dict(DEFAULT_FORM)
    schema.update({k: v2 for k, v2 in (v['submission_schema'] or {}).items() if k in DEFAULT_FORM})
    return schema


def task_view(conn, a):
    if a is None:
        return None
    variants = conn.execute('SELECT * FROM assignment_variants WHERE assignment_id=%s AND active ORDER BY code', (a['id'],)).fetchall()
    general = next((v for v in variants if variant_league(v) is None), None)
    return {'id': str(a['id']), 'title': a['title'],
            'form': form_of(general or variants[0]) if variants else dict(DEFAULT_FORM),
            'variants': [{'id': str(v['id']), 'league': variant_league(v),
                          'instructions': '' if same_text(v) else localized(v['instructions_i18n']),
                          'same_text': same_text(v),
                          'deadline': iso(R.variant_deadline(v)) if variant_league(v) else None,
                          'opens_at': iso(R.variant_opens_at(v)) if variant_league(v) else None,
                          'title': localized(v['title_i18n']) if variant_league(v) and localized(v['title_i18n']) != a['title'] else None}
                         for v in sorted(variants, key=lambda v: (variant_league(v) is not None,
                                                                  LEAGUES.index(variant_league(v)) if variant_league(v) else 0))]}


def same_text(v):
    """Лига без своего текста: в варианте — копия общего текста, которая обновляется вместе с ним."""
    return bool(variant_league(v) and (v['release_rules'] or {}).get('same_text'))


def league_problems(own_open, own_deadline, round_open, round_deadline, game_end):
    """Свои даты лиги в паре с общими датами тура: открытие лиги раньше её срока сдачи, срок — не позже конца Игры."""
    out = []
    open_at, deadline = own_open or round_open, own_deadline or round_deadline
    if open_at and deadline and deadline <= open_at:
        out.append('league_deadline_before_open' if own_deadline else 'league_open_after_deadline')
    if own_deadline and game_end and own_deadline > game_end:
        out.append('league_deadline_after_game_end')
    if own_open and game_end and own_open >= game_end:
        out.append('league_open_after_game_end')
    return out


def round_checks(conn, e, r, a, now):
    problems, warnings = [], []
    if r['opens_at'] is None:
        problems.append('missing_opens_at')
    if r['deadline'] is None:
        problems.append('missing_deadline')
    if r['opens_at'] and r['deadline'] and r['deadline'] <= r['opens_at']:
        problems.append('deadline_before_open')
    if r['judging_deadline'] and r['deadline'] and r['judging_deadline'] < r['deadline']:
        problems.append('judging_before_deadline')
    if e['ends_at'] and r['deadline'] and r['deadline'] > e['ends_at']:
        problems.append('deadline_after_game_end')
    for v in round_variants(conn, r['id']):
        if variant_league(v):
            problems += [p for p in league_problems(R.variant_opens_at(v), R.variant_deadline(v), r['opens_at'], r['deadline'],
                                                     e['ends_at']) if p not in problems]
    task = task_view(conn, a)
    if task is None or not task['title']:
        problems.append('no_task')
    else:
        if not any(v['league'] is None for v in task['variants']):
            problems.append('no_general_text')
        if any(not v['instructions'].strip() and not v['same_text'] for v in task['variants']):
            problems.append('empty_instructions')
    if e['starts_at'] and r['opens_at'] and r['opens_at'] < e['starts_at']:
        warnings.append('opens_before_game')
    prev = conn.execute('''SELECT opens_at, deadline FROM rounds WHERE event_id=%s AND round_no<%s AND status<>'draft'
ORDER BY round_no DESC LIMIT 1''', (e['id'], r['round_no'])).fetchone()
    if prev and prev['opens_at'] and r['opens_at'] and r['opens_at'] < prev['opens_at']:
        warnings.append('opens_before_previous')
    if r['opens_at'] and r['status'] == 'draft' and r['opens_at'] < now:
        warnings.append('opens_in_past')
    return {'problems': problems, 'warnings': warnings}


def round_stats(conn, e, a):
    people = conn.execute('''SELECT count(*) AS n FROM event_participants WHERE event_id=%s
AND registration_status='participating' ''', (e['id'],)).fetchone()['n']
    if a is None:
        return {'participants': people, 'issued': 0, 'sent': 0, 'on_time': 0, 'late': 0, 'personal_deadlines': 0}
    row = conn.execute('''SELECT count(pa.id) AS issued,
  count(s.latest_version_id) AS sent,
  count(*) FILTER (WHERE s.latest_version_id IS NOT NULL AND s.is_on_time) AS on_time,
  count(*) FILTER (WHERE s.latest_version_id IS NOT NULL AND NOT s.is_on_time) AS late,
  count(pa.deadline_override) AS personal
FROM participant_assignments pa LEFT JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
WHERE pa.assignment_id=%s AND pa.active''', (a['id'],)).fetchone()
    return {'participants': people, 'issued': row['issued'], 'sent': row['sent'], 'on_time': row['on_time'],
            'late': row['late'], 'personal_deadlines': row['personal']}


def round_detail(conn, r, now):
    e = load_event(conn, r['event_id'])
    a = main_task(conn, r)
    is_open = opened(conn, r, now)
    return {'id': str(r['id']), 'event': {'id': str(e['id']), 'title': e['title'], 'status': e['status'],
                                          'starts_at': iso(e['starts_at']), 'ends_at': iso(e['ends_at'])},
            'round_no': r['round_no'], 'title': r['title'], 'status': r['status'],
            'state': round_state(r, now, league_dates(conn, r['id'])),
            'opens_at': iso(r['opens_at']), 'deadline': iso(r['deadline']), 'judging_deadline': iso(r['judging_deadline']),
            'task': task_view(conn, a), 'stats': round_stats(conn, e, a),
            'all_open': all_opened(conn, r, now),
            'locks': {'opens_at': general_opened(r, now), 'form': is_open, 'leagues': is_open,
                      # лигам, которым задание уже открылось, дату открытия не поменять
                      'league_opens': sorted({variant_league(v) for v in round_variants(conn, r['id']) if variant_league(v)
                                              and r['status'] != 'draft' and R.round_opened(R.effective_round(r, v), now)})},
            'is_last': conn.execute('SELECT max(round_no) AS n FROM rounds WHERE event_id=%s', (e['id'],)).fetchone()['n'] == r['round_no'],
            'readonly': e['status'] in ('finished', 'archived'),
            'checks': round_checks(conn, e, r, a, now)}


class RoundCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, max_length=150)


@router.post('/events/{event_id}/rounds', status_code=201, dependencies=WRITE)
def create_round(event_id: UUID, body: RoundCreate, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        if e['status'] in ('finished', 'archived'):
            raise problem('game_finished', 409)
        no = conn.execute('SELECT coalesce(max(round_no),0)+1 AS n FROM rounds WHERE event_id=%s', (event_id,)).fetchone()['n']
        title = clean_text(body.title) or f'Тур {no}'
        r = conn.execute('''INSERT INTO rounds(event_id,round_no,title,status) VALUES (%s,%s,%s,'draft') RETURNING *''',
                         (event_id, no, title)).fetchone()
        a = conn.execute('''INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work',%s) RETURNING *''',
                         (event_id, r['id'], f'Задание тура {no}')).fetchone()
        conn.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n,submission_schema)
VALUES (%s,'all',%s,%s,%s)''', (a['id'], Jsonb({'ru': a['title']}), Jsonb({'ru': ''}), Jsonb(DEFAULT_FORM)))
        audit(conn, user['id'], 'round', r['id'], 'round_created', {'event_id': str(event_id), 'round_no': no})
        return round_detail(conn, r, now)


@router.get('/rounds/{round_id}')
def round_page(round_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return round_detail(conn, load_round(conn, round_id), now_of(request))


class RoundChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=150)
    opens_at: AwareDatetime | None = None
    deadline: AwareDatetime | None = None
    judging_deadline: AwareDatetime | None = None

    @field_validator('title')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True) if value is not None else None


def check_round_values(e, r, values):
    merged = {k: values.get(k, r[k]) for k in ('opens_at', 'deadline', 'judging_deadline')}
    if merged['opens_at'] and merged['deadline'] and merged['deadline'] <= merged['opens_at']:
        raise problem('deadline_before_open')
    if merged['judging_deadline'] and merged['deadline'] and merged['judging_deadline'] < merged['deadline']:
        raise problem('judging_before_deadline')
    if r['status'] != 'draft':
        if merged['opens_at'] is None or merged['deadline'] is None:
            raise problem('date_required')
        if e['ends_at'] and merged['deadline'] > e['ends_at']:
            raise problem('deadline_after_game_end')


def check_league_dates(conn, e, r, values):
    """Общие даты тура меняются — лигам без своих дат достаются новые: у каждой лиги открытие должно остаться раньше срока."""
    opens, deadline = values.get('opens_at', r['opens_at']), values.get('deadline', r['deadline'])
    for v in round_variants(conn, r['id']):
        if variant_league(v):
            found = league_problems(R.variant_opens_at(v), R.variant_deadline(v), opens, deadline, e['ends_at'])
            if found:
                raise problem(found[0])


@router.patch('/rounds/{round_id}', dependencies=WRITE)
def change_round(round_id: UUID, body: RoundChange, request: Request, user=Depends(org_user)):
    now = now_of(request)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise problem('nothing_to_change')
    if 'title' in values and values['title'] is None:
        raise problem('title_required')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load_round(conn, round_id, lock=True)
        e = load_event(conn, r['event_id'], lock=True)
        if e['status'] in ('finished', 'archived'):
            raise problem('game_finished', 409)
        if general_opened(r, now) and 'opens_at' in values and values['opens_at'] != r['opens_at']:
            raise problem('opens_locked', 409)
        check_round_values(e, r, values)
        check_league_dates(conn, e, r, values)
        was_open = opened(conn, r, now)
        moved = 'deadline' in values and values['deadline'] != r['deadline']
        if was_open and moved and values['deadline'] is not None and values['deadline'] <= now:
            raise problem('deadline_in_past')
        sets = ', '.join(f'{k}=%({k})s' for k in values)
        r = conn.execute(f'UPDATE rounds SET {sets} WHERE id=%(id)s RETURNING *', values | {'id': round_id}).fetchone()
        if was_open and moved:
            notify_deadline(conn, e, r, own_leagues=own_deadline_leagues(conn, r))
        audit(conn, user['id'], 'round', round_id, 'round_changed', {k: iso(v) if hasattr(v, 'isoformat') else v
                                                                     for k, v in values.items()})
        return round_detail(conn, r, now)


class RoundAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['publish', 'unpublish', 'open_now']


@router.post('/rounds/{round_id}/status', dependencies=WRITE)
def round_status(round_id: UUID, body: RoundAction, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load_round(conn, round_id, lock=True)
        e = load_event(conn, r['event_id'], lock=True)
        if e['status'] in ('finished', 'archived'):
            raise problem('game_finished', 409)
        a = main_task(conn, r)
        if body.action == 'publish':
            if r['status'] != 'draft':
                raise problem('wrong_status', 409)
            checks = round_checks(conn, e, r, a, now)
            if checks['problems']:
                raise problem(checks['problems'][0], 409)
            r = conn.execute("UPDATE rounds SET status='scheduled' WHERE id=%s RETURNING *", (round_id,)).fetchone()
        elif body.action == 'unpublish':
            if r['status'] != 'scheduled' or opened(conn, r, now):
                raise problem('round_opened', 409)
            if a and conn.execute('SELECT 1 FROM participant_assignments WHERE assignment_id=%s LIMIT 1', (a['id'],)).fetchone():
                raise problem('task_issued', 409)
            r = conn.execute("UPDATE rounds SET status='draft' WHERE id=%s RETURNING *", (round_id,)).fetchone()
        else:
            # «Открыть сейчас» — всем лигам: общая дата открытия — сейчас, будущие свои даты открытия лиг снимаются.
            if r['status'] != 'scheduled' or all_opened(conn, r, now):
                raise problem('wrong_status', 409)
            if r['deadline'] is None or r['deadline'] <= now:
                raise problem('deadline_before_open', 409)
            for v in round_variants(conn, round_id):
                own = R.variant_opens_at(v)
                if own is not None and own > now:
                    kept = {k: x for k, x in (v['release_rules'] or {}).items() if k != 'opens_at'}
                    conn.execute('UPDATE assignment_variants SET release_rules=%s WHERE id=%s', (Jsonb(kept), v['id']))
            if not general_opened(r, now):
                r = conn.execute('UPDATE rounds SET opens_at=%s WHERE id=%s RETURNING *', (now, round_id)).fetchone()
        audit(conn, user['id'], 'round', round_id, 'round_' + body.action)
        return round_detail(conn, r, now)


@router.delete('/rounds/{round_id}', dependencies=WRITE)
def delete_round(round_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load_round(conn, round_id, lock=True)
        e = load_event(conn, r['event_id'], lock=True)
        if r['status'] != 'draft':
            raise problem('not_draft', 409)
        last = conn.execute('SELECT max(round_no) AS n FROM rounds WHERE event_id=%s', (e['id'],)).fetchone()['n']
        if r['round_no'] != last:
            raise problem('not_last_round', 409)
        tasks = [x['id'] for x in conn.execute('SELECT id FROM assignments WHERE round_id=%s', (round_id,))]
        if tasks and conn.execute('SELECT 1 FROM participant_assignments WHERE assignment_id = ANY(%s) LIMIT 1', (tasks,)).fetchone():
            raise problem('task_issued', 409)
        try:
            with conn.transaction():   # точка сохранения: на тур ссылаются другие записи — понятный отказ, а не сбой
                conn.execute('DELETE FROM assignment_variants WHERE assignment_id = ANY(%s)', (tasks,))
                conn.execute('DELETE FROM assignments WHERE round_id=%s', (round_id,))
                conn.execute('DELETE FROM rounds WHERE id=%s', (round_id,))
        except psycopg.errors.ForeignKeyViolation:
            raise problem('has_links', 409) from None
        audit(conn, user['id'], 'round', None, 'round_deleted', {'event_id': str(e['id']), 'round_no': r['round_no']})
        return event_detail(conn, e, now)


class FormIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    photo: FIELD = 'required'
    link: FIELD = 'optional'
    photo_max: int = Field(default=1, ge=1, le=10)

    @model_validator(mode='after')
    def something(self):
        if self.photo == 'none' and self.link == 'none':
            raise ValueError('nothing_to_submit')
        return self


class VariantIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    league: Literal['bronze', 'silver', 'gold'] | None = None
    title: str | None = Field(default=None, max_length=150)   # своё название для лиги; пусто — общее название задания
    instructions: str = Field(default='', max_length=8000)
    deadline: AwareDatetime | None = None   # свой срок сдачи лиги; пусто — срок тура
    opens_at: AwareDatetime | None = None   # своё открытие задания для лиги; пусто — открытие тура

    @field_validator('title')
    @classmethod
    def trim(cls, value):
        return clean_text(value)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    form: FormIn
    variants: list[VariantIn] = Field(min_length=1, max_length=4)

    @field_validator('title')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)

    @model_validator(mode='after')
    def shape(self):
        leagues = [v.league for v in self.variants]
        if leagues.count(None) != 1:
            raise ValueError('one_general_text')
        if len(set(leagues)) != len(leagues):
            raise ValueError('duplicate_league')
        return self


def schema_dict(form):
    out = {'photo': form.photo, 'link': form.link, 'photo_max': form.photo_max if form.photo != 'none' else 1}
    return out


@router.put('/rounds/{round_id}/task', dependencies=WRITE)
def put_task(round_id: UUID, body: TaskIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        r = load_round(conn, round_id, lock=True)
        e = load_event(conn, r['event_id'], lock=True)
        if e['status'] in ('finished', 'archived'):
            raise problem('game_finished', 409)
        a = main_task(conn, r)
        if a is None:
            a = conn.execute('''INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work',%s) RETURNING *''',
                             (e['id'], round_id, body.title)).fetchone()
        a = conn.execute('SELECT * FROM assignments WHERE id=%s FOR UPDATE', (a['id'],)).fetchone()
        current = conn.execute('SELECT * FROM assignment_variants WHERE assignment_id=%s FOR UPDATE', (a['id'],)).fetchall()
        active = {variant_league(v): v for v in current if v['active']}
        schema = schema_dict(body.form)
        wanted = {v.league: v for v in body.variants}
        is_open = opened(conn, r, now)
        if is_open:
            if set(wanted) != set(active):
                raise problem('leagues_locked', 409)
            if any(form_of(v) != schema for v in active.values()):
                raise problem('form_locked', 409)
        conn.execute('UPDATE assignments SET title=%s WHERE id=%s', (body.title, a['id']))
        changed = []
        general_text = wanted[None].instructions.strip()
        deadline_moved = []
        published = r['status'] != 'draft'
        for league, v in wanted.items():
            code = league or 'all'
            own_title = v.title if league else None
            own_deadline = v.deadline if league else None
            own_open = v.opens_at if league else None
            if league:
                found = league_problems(own_open, own_deadline, r['opens_at'], r['deadline'], e['ends_at'])
                if found:
                    raise problem(found[0])
                # Лиге задание уже открылось — её дату открытия не поменять (участницы уже работают).
                before = active.get(league)
                was_open = (R.variant_opens_at(before) if before else None) or r['opens_at']
                if published and before is not None and was_open is not None and was_open <= now \
                        and (own_open or r['opens_at']) != was_open:
                    raise problem('league_opens_locked', 409)
                old_deadline = (R.variant_deadline(before) if before else None) or r['deadline']
                if is_open and (own_deadline or r['deadline']) != old_deadline:
                    if own_deadline is not None and own_deadline <= now:
                        raise problem('deadline_in_past')
                    deadline_moved.append(league)
            same = bool(league) and not v.instructions.strip()
            text = general_text if same else v.instructions.strip()
            rules = {}
            if own_deadline:
                rules['deadline'] = own_deadline.isoformat()
            if own_open:
                rules['opens_at'] = own_open.isoformat()
            if same:
                rules['same_text'] = True
            release = Jsonb(rules)
            title_i18n, text_i18n = Jsonb({'ru': own_title or body.title}), Jsonb({'ru': text})
            existing = active.get(league) or next((x for x in current if x['code'] == code), None)
            if existing is None:
                conn.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n,audience_rules,
submission_schema,release_rules) VALUES (%s,%s,%s,%s,%s,%s,%s)''', (a['id'], code, title_i18n, text_i18n,
                                                     Jsonb({'leagues': [league]} if league else {}), Jsonb(schema), release))
                continue
            text_changed = localized(existing['instructions_i18n']) != text \
                or localized(existing['title_i18n']) != (own_title or body.title)
            conn.execute('''UPDATE assignment_variants SET title_i18n=%s, instructions_i18n=%s, submission_schema=%s, active=true,
audience_rules=%s, release_rules=%s WHERE id=%s''', (title_i18n, text_i18n, Jsonb(schema),
                                                      Jsonb({'leagues': [league]} if league else {}), release, existing['id']))
            if text_changed:
                changed.append(existing['id'])
        for league, v in active.items():
            if league not in wanted:
                # Ещё никому не выдан — убрать; выдан (например, при личном продлении срока) — только выключить.
                used = conn.execute('SELECT 1 FROM participant_assignments WHERE assignment_variant_id=%s LIMIT 1',
                                    (v['id'],)).fetchone()
                if used:
                    conn.execute('UPDATE assignment_variants SET active=false WHERE id=%s', (v['id'],))
                else:
                    conn.execute('DELETE FROM assignment_variants WHERE id=%s', (v['id'],))
        # Уже выданное задание показывается по снимку — обновить снимки, чтобы все видели исправленный текст
        # (и форму сдачи, если задание выдали до открытия тура — например, при личном продлении срока).
        conn.execute('''UPDATE participant_assignments pa SET payload_snapshot = pa.payload_snapshot
  || jsonb_build_object('title_i18n', v.title_i18n, 'instructions_i18n', v.instructions_i18n,
                        'submission_schema', v.submission_schema)
FROM assignment_variants v WHERE v.id=pa.assignment_variant_id AND pa.assignment_id=%s AND pa.active AND v.active''', (a['id'],))
        notified = 0
        if changed and is_open:
            stamp = uuid4().hex[:12]
            rows = conn.execute('''SELECT event_participant_id FROM participant_assignments
WHERE assignment_variant_id = ANY(%s) AND active''', (changed,)).fetchall()
            if rows:
                users = conn.execute('SELECT id, user_id FROM event_participants WHERE id = ANY(%s)',
                                     ([x['event_participant_id'] for x in rows],)).fetchall()
                for u in users:
                    notify(conn, u['user_id'], 'task', f"task:{a['id']}:{stamp}:{u['id']}",
                           {'title': f"Задание тура {r['round_no']} уточнено",
                            'text': 'Организатор обновил текст задания. Посмотрите его ещё раз.',
                            'route': 'task', 'event_id': str(e['id']), 'assignment_id': str(a['id'])}, e['id'], r['id'])
                notified = len(users)
        for league in deadline_moved:
            notified += notify_deadline(conn, e, r, league=league)
        audit(conn, user['id'], 'assignment', a['id'], 'task_changed',
              {'leagues': [k for k in wanted if k], 'form': schema, 'texts_changed': len(changed), 'notified': notified,
               'league_deadlines': {k: iso(v.deadline) for k, v in wanted.items() if k and v.deadline},
               'league_opens': {k: iso(v.opens_at) for k, v in wanted.items() if k and v.opens_at}})
        return round_detail(conn, r, now) | {'notified': notified}
