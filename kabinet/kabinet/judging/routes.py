"""Судейство: страницы организатора (/api/org/…) и судьи (/api/judging/…).

Судья видит только назначенные ему пулы, только фото работ (без имён и ссылок), голосует до публикации итогов.
Организатор настраивает судейство тура, запускает его после срока сдачи, следит за ходом, решает границу прохода
(переголосование или своё решение с причиной) и публикует итоги — с изменением FPL Rating.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from kabinet import relay
from kabinet.org.common import WRITE, audit, db, iso, locked_admin, now_of, org_user, person_name, problem
from kabinet.org.games import clean_text, load_event
from kabinet.org.rounds import load_round
from kabinet.participation import rules as R
from kabinet.participation.views import localized, photo_view
from kabinet.web.routes import browser_user
from . import service as S

org = APIRouter(prefix='/api/org', tags=['organizer'])
judge = APIRouter(prefix='/api/judging', tags=['judging'])
POOL_KEYS = ('all', 'bronze', 'silver', 'gold')


# ---------- организатор ----------

def stream_photos(conn, stream_id, root):
    rows = conn.execute('''SELECT m.evaluation_target_id, mf.* FROM evaluation_target_members m
JOIN evaluation_targets t ON t.id=m.evaluation_target_id
JOIN submission_version_media svm ON svm.submission_version_id=m.submission_version_id
JOIN media_files mf ON mf.id=svm.media_file_id
WHERE t.evaluation_stream_id=%s ORDER BY svm.sort_order''', (stream_id,)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(str(r['evaluation_target_id']), []).append(photo_view(r, root))
    return out


def judging_view(conn, event, rnd, now, root):
    cfg = S.config_of(rnd)
    streams = S.streams_of(conn, rnd['id'])
    judges = S.eligible_judges(conn, event['id'])
    out = {'round': {'id': str(rnd['id']), 'round_no': rnd['round_no'], 'title': rnd['title'], 'status': rnd['status'],
                     'deadline': iso(rnd['deadline']), 'judging_deadline': iso(rnd['judging_deadline'])},
           'event': {'id': str(event['id']), 'title': event['title'], 'status': event['status'],
                     'affects_rating': event['affects_rating']},
           'config': cfg, 'started': bool(streams), 'published': rnd['status'] == 'published',
           'judges': [{'id': str(j['id']), 'name': person_name(j), 'is_judge': j['is_judge']} for j in judges]}
    if not streams:
        out['checks'] = S.start_checks(conn, event, rnd, cfg, now)
        out['acceptance_end'] = iso(S.acceptance_end(conn, rnd))
        return out
    views = []
    for st in streams:
        v = S.stream_view(conn, st, now)
        photos = stream_photos(conn, st['id'], root)
        sources = {str(k): x for k, x in target_sources(conn, rnd['id'], [row['target'] for row in v['rows']], root).items()}
        for row in v['rows']:
            row['photos'] = photos.get(row['target'], [])
            row['source'] = sources.get(row['target'])
        views.append(v)
    out['streams'] = views
    out['publish_problems'] = S.publish_checks(conn, rnd) if rnd['status'] != 'published' else []
    return out


@org.get('/rounds/{round_id}/judging')
def round_judging(round_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        rnd = load_round(conn, round_id)
        return judging_view(conn, load_event(conn, rnd['event_id']), rnd, now_of(request), request.app.state.settings.root_path)


class CriterionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1, max_length=60)
    weight: float = Field(default=1, gt=0, le=100)

    @field_validator('label')
    @classmethod
    def trim(cls, value):
        return clean_text(value, required=True)


class JudgingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    method: Literal['pairwise', 'criteria'] = 'pairwise'
    pools: Literal['leagues', 'common'] = 'leagues'
    per_target: Literal[2, 4, 6] = 2
    criteria: list[CriterionIn] = Field(default_factory=list, max_length=6)
    judges: dict[Literal['all', 'bronze', 'silver', 'gold'], list[UUID]] = Field(default_factory=dict)
    quota: dict[Literal['all', 'bronze', 'silver', 'gold'], int | None] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check(self):
        for v in self.quota.values():
            if v is not None and not 1 <= v <= 10000:
                raise ValueError('quota_range')
        for v in self.judges.values():
            if len(set(v)) != len(v) or len(v) > 15:
                raise ValueError('judges_list')
        if self.method == 'criteria' and not self.criteria:
            raise ValueError('no_criteria')
        return self


@org.put('/rounds/{round_id}/judging', dependencies=WRITE)
def set_judging(round_id: UUID, body: JudgingConfig, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        rnd = load_round(conn, round_id, lock=True)
        event = load_event(conn, rnd['event_id'])
        if S.streams_of(conn, rnd['id']):
            raise problem('judging_started', 409)
        eligible = {str(j['id']) for j in S.eligible_judges(conn, event['id'])}
        if any(str(u) not in eligible for v in body.judges.values() for u in v):
            raise problem('judge_not_eligible')
        cfg = {'method': body.method, 'pools': body.pools, 'per_target': body.per_target,
               'criteria': [{'code': f'c{i + 1}', 'label': c.label, 'weight': c.weight} for i, c in enumerate(body.criteria)],
               'judges': {k: [str(u) for u in v] for k, v in body.judges.items() if v},
               'quota': {k: v for k, v in body.quota.items() if v is not None}}
        settings = dict(rnd['settings'] or {})
        settings['judging'] = cfg
        rnd = conn.execute('UPDATE rounds SET settings=%s WHERE id=%s RETURNING *', (S.G.Jsonb(settings), rnd['id'])).fetchone()
        audit(conn, user['id'], 'round', rnd['id'], 'judging_configured', {'method': body.method, 'pools': body.pools})
        return judging_view(conn, event, rnd, now, request.app.state.settings.root_path)


@org.post('/rounds/{round_id}/judging/start', dependencies=WRITE)
def start_judging(round_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        rnd = load_round(conn, round_id, lock=True)
        event = load_event(conn, rnd['event_id'], lock=True)
        S.start(conn, event, rnd, user['id'], now)
        rnd = load_round(conn, round_id)
        return judging_view(conn, event, rnd, now, request.app.state.settings.root_path)


def locked_stream(conn, stream_id):
    st, rnd = S.lock_stream(conn, stream_id, 'UPDATE')    # тур, потом пул — как у голоса и публикации
    if rnd['status'] == 'published':
        raise problem('already_published', 409)
    return st, rnd


def after_change(conn, request, rnd):
    return judging_view(conn, load_event(conn, rnd['event_id']), load_round(conn, rnd['id']), now_of(request),
                        request.app.state.settings.root_path)


class StreamChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quota: int | None = Field(default=None, ge=1, le=10000)
    judging_deadline: AwareDatetime | None = None


@org.patch('/judging/streams/{stream_id}', dependencies=WRITE)
def change_stream(stream_id: UUID, body: StreamChange, request: Request, user=Depends(org_user)):
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise problem('nothing_to_change')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        S.set_stream(conn, st, values)
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'stream_changed',
              {k: (iso(v) if hasattr(v, 'isoformat') else v) for k, v in values.items()})
        return after_change(conn, request, rnd)


class Replace(BaseModel):
    model_config = ConfigDict(extra='forbid')
    old_user_id: UUID
    new_user_id: UUID
    reason: str = Field(min_length=1, max_length=500)


@org.post('/judging/streams/{stream_id}/replace', dependencies=WRITE)
def replace(stream_id: UUID, body: Replace, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        S.replace_judge(conn, st, body.old_user_id, body.new_user_id, body.reason.strip(), now)
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'judge_replaced',
              {'old': str(body.old_user_id), 'new': str(body.new_user_id), 'reason': body.reason.strip()})
        event = load_event(conn, rnd['event_id'])
        S.notify_judges(conn, event, rnd, st, [body.new_user_id], 'start', f':{now.timestamp():.0f}')
        return after_change(conn, request, rnd)


class TieBreak(BaseModel):
    model_config = ConfigDict(extra='forbid')
    targets: list[UUID] = Field(min_length=2, max_length=12)
    goal: Literal['advance', 'places'] = 'advance'


@org.post('/judging/streams/{stream_id}/tie-break', dependencies=WRITE)
def tie_break(stream_id: UUID, body: TieBreak, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        run = S.start_tie_break(conn, st, body.targets, body.goal, user['id'], now)
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'tie_break_started',
              {'run_no': run, 'goal': body.goal, 'targets': [str(t) for t in body.targets]})
        return after_change(conn, request, rnd)


@org.post('/judging/streams/{stream_id}/tie-break/cancel', dependencies=WRITE)
def cancel_tie_break(stream_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        runs = S.cancel_tie_break(conn, st, user['id'])
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'tie_break_cancelled', {'runs': runs})
        return after_change(conn, request, rnd)


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    targets: list[UUID] = Field(min_length=1, max_length=50)
    advance: list[UUID] = Field(default_factory=list, max_length=50)
    reason: str = Field(min_length=1, max_length=500)


@org.post('/judging/streams/{stream_id}/decision', dependencies=WRITE)
def decision(stream_id: UUID, body: Decision, request: Request, user=Depends(org_user)):
    now = now_of(request)
    reason = body.reason.strip()
    if not reason:
        raise problem('reason_required')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        S.admin_decision(conn, st, body.targets, body.advance, reason, user['id'], now)
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'advancement_decided',
              {'targets': [str(t) for t in body.targets], 'advance': [str(t) for t in body.advance], 'reason': reason})
        return after_change(conn, request, rnd)


class Close(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=500)


@org.post('/judging/streams/{stream_id}/close', dependencies=WRITE)
def close(stream_id: UUID, body: Close, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        st, rnd = locked_stream(conn, stream_id)
        n = S.close_pending(conn, st, body.reason.strip(), user['id'])
        audit(conn, user['id'], 'evaluation_stream', st['id'], 'pending_closed', {'count': n, 'reason': body.reason.strip()})
        return after_change(conn, request, rnd)


@org.post('/rounds/{round_id}/judging/publish', dependencies=WRITE)
def publish(round_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        rnd = load_round(conn, round_id, lock=True)
        event = load_event(conn, rnd['event_id'], lock=True)
        S.publish(conn, event, rnd, user['id'], now)
        return judging_view(conn, event, load_round(conn, round_id), now, request.app.state.settings.root_path)


# ---------- судья ----------

def my_streams(conn, user_id):
    return conn.execute('''SELECT st.*, a.judge_slot_id, r.round_no, r.title AS round_title, r.status AS round_status, e.title AS event_title
FROM evaluation_judge_assignments a JOIN evaluation_streams st ON st.id=a.evaluation_stream_id
JOIN rounds r ON r.id=st.round_id JOIN events e ON e.id=st.event_id
WHERE a.user_id=%s AND a.status='active' AND st.active
AND EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=a.user_id AND ur.role IN ('judge','admin')) ORDER BY a.active_from DESC''', (user_id,)).fetchall()


def judge_progress(conn, st, slot_id):
    if st['judging_method'] == 'pairwise':
        row = conn.execute('''SELECT count(*) FILTER (WHERE status='voted') AS done, count(*) AS total,
count(*) FILTER (WHERE status='pending' AND phase='tie_break') AS tb FROM pairwise_comparisons
WHERE judge_slot_id=%s AND status NOT IN ('cancelled','void')''', (slot_id,)).fetchone()
        return {'done': row['done'], 'total': row['total'], 'tie_break_pending': row['tb']}
    tb = conn.execute('''SELECT count(*) AS n FROM pairwise_comparisons WHERE judge_slot_id=%s AND status='pending' AND phase='tie_break' ''',
                      (slot_id,)).fetchone()['n']
    targets = conn.execute('SELECT count(*) AS n FROM evaluation_targets WHERE evaluation_stream_id=%s', (st['id'],)).fetchone()['n']
    crit = conn.execute('SELECT count(*) AS n FROM evaluation_criteria WHERE evaluation_stream_id=%s', (st['id'],)).fetchone()['n']
    done = conn.execute('''SELECT count(DISTINCT evaluation_target_id) AS n FROM (SELECT evaluation_target_id, count(*) c FROM criterion_scores
WHERE judge_slot_id=%s AND status='valid' GROUP BY evaluation_target_id) x WHERE c=%s''', (slot_id, crit)).fetchone()['n']
    return {'done': done, 'total': targets, 'tie_break_pending': tb}


def is_open(st):
    return st['round_status'] != 'published'


@judge.get('')
def judging_home(request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        out = []
        for st in my_streams(conn, user['id']):
            out.append({'id': str(st['id']), 'event': st['event_title'], 'round_no': st['round_no'], 'round_title': st['round_title'],
                        'league': st['league'], 'league_name': S.LEAGUE_NAME[st['league']], 'method': st['judging_method'],
                        'deadline': iso(st['judging_deadline']), 'open': is_open(st), **judge_progress(conn, st, st['judge_slot_id'])})
        return {'streams': out}


def task_text(conn, st):
    a = S.main_task(conn, {'id': st['round_id']})
    if a is None:
        return None
    variants = conn.execute('SELECT * FROM assignment_variants WHERE assignment_id=%s', (a['id'],)).fetchall()
    v = R.pick_variant(variants, {'entry_league': st['league']}) or next((x for x in variants if x['code'] == 'all'), None)
    return {'title': (localized(v['title_i18n']) if v else None) or a['title'],
            'instructions': localized(v['instructions_i18n']) if v else ''}


def target_sources(conn, round_id, target_ids, root):
    """Тур-эстафета: исходник рядом с работой второй лиги — {цель: [фото исходника]} (без имён)."""
    if not target_ids:
        return {}
    members = {r['event_participant_id']: r['evaluation_target_id'] for r in conn.execute(
        'SELECT evaluation_target_id, event_participant_id FROM evaluation_target_members WHERE evaluation_target_id = ANY(%s::uuid[])',
        ([str(x) for x in target_ids],))}
    rows = relay.source_rows(conn, round_id, list(members))
    return {members[ep]: [photo_view(m, root) for m in ms] for ep, ms in rows.items()}


def target_photos(conn, target_ids, root):
    if not target_ids:
        return {}
    rows = conn.execute('''SELECT m.evaluation_target_id, mf.* FROM evaluation_target_members m
JOIN submission_version_media svm ON svm.submission_version_id=m.submission_version_id
JOIN media_files mf ON mf.id=svm.media_file_id
WHERE m.evaluation_target_id = ANY(%s) ORDER BY svm.sort_order''', (list(target_ids),)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r['evaluation_target_id'], []).append(photo_view(r, root))
    return out


def my_stream(conn, user_id, stream_id):
    st = next((s for s in my_streams(conn, user_id) if str(s['id']) == str(stream_id)), None)
    if not st:
        raise HTTPException(404, 'Not found')
    return st


def work_no(conn, st):
    """Номер работы для судьи — порядковый в пуле (без имени)."""
    return {t['id']: i for i, t in enumerate(conn.execute(
        'SELECT id FROM evaluation_targets WHERE evaluation_stream_id=%s ORDER BY md5(id::text)', (st['id'],)).fetchall(), 1)}


@judge.get('/streams/{stream_id}')
def judging_stream(stream_id: UUID, request: Request, user=Depends(browser_user)):
    root = request.app.state.settings.root_path
    with db(request).transaction() as conn:
        st = my_stream(conn, user['id'], stream_id)
        nos = work_no(conn, st)
        out = {'id': str(st['id']), 'event': st['event_title'], 'round_no': st['round_no'], 'round_title': st['round_title'],
               'league': st['league'], 'league_name': S.LEAGUE_NAME[st['league']], 'method': st['judging_method'],
               'deadline': iso(st['judging_deadline']), 'open': is_open(st), 'task': task_text(conn, st),
               **judge_progress(conn, st, st['judge_slot_id'])}
        me = conn.execute('''SELECT id FROM evaluation_judge_assignments WHERE judge_slot_id=%s AND user_id=%s AND status='active' ''',
                          (st['judge_slot_id'], user['id'])).fetchone()['id']
        # пары: основное голосование (сравнение пар) и переголосование (любой способ оценки);
        # голоса прежнего судьи этого места (до замены) не показываются
        comps = [c for c in conn.execute('''SELECT * FROM pairwise_comparisons WHERE judge_slot_id=%s AND status NOT IN ('cancelled','void')
ORDER BY (phase='tie_break') DESC, run_no DESC, md5(id::text)''', (st['judge_slot_id'],)).fetchall()
                 if c['status'] == 'pending' or c['judge_assignment_id'] == me]
        cfg = st['configuration'] or {}
        out['locked_regular'] = bool(cfg.get('regular_closed') or cfg.get('tie_breaks'))
        pending = [c for c in comps if c['status'] == 'pending' and not (c['phase'] == 'regular' and out['locked_regular'])]
        ids = {x for c in comps for x in (c['target_a_id'], c['target_b_id'])}
        photos = target_photos(conn, ids, root)
        sources = target_sources(conn, st['round_id'], ids, root)

        def pair(c):
            return {'id': str(c['id']), 'phase': c['phase'], 'status': c['status'],
                    'winner': None if c['winner_target_id'] is None else ('a' if c['winner_target_id'] == c['target_a_id'] else 'b'),
                    'a': {'no': nos.get(c['target_a_id']), 'photos': photos.get(c['target_a_id'], []),
                          'source': sources.get(c['target_a_id'])},
                    'b': {'no': nos.get(c['target_b_id']), 'photos': photos.get(c['target_b_id'], []),
                          'source': sources.get(c['target_b_id'])},
                    'voted_at': iso(c['voted_at'])}
        out['next'] = pair(pending[0]) if pending else None
        out['voted'] = [pair(c) for c in comps if c['status'] == 'voted']
        if st['judging_method'] == 'criteria':
            criteria = conn.execute('SELECT * FROM evaluation_criteria WHERE evaluation_stream_id=%s ORDER BY sort_order', (st['id'],)).fetchall()
            targets = conn.execute('SELECT id FROM evaluation_targets WHERE evaluation_stream_id=%s', (st['id'],)).fetchall()
            scored, own = {}, {}
            for x in conn.execute("SELECT * FROM criterion_scores WHERE judge_slot_id=%s AND status='valid'", (st['judge_slot_id'],)):
                scored.setdefault(x['evaluation_target_id'], set()).add(x['criterion_id'])
                if x['judge_assignment_id'] == me:        # оценки прежнего судьи этого места не показываются
                    own.setdefault(x['evaluation_target_id'], {})[x['criterion_id']] = float(x['score'])
            photos = target_photos(conn, [t['id'] for t in targets], root)
            sources = target_sources(conn, st['round_id'], [t['id'] for t in targets], root)
            code = {c['id']: c['code'] for c in criteria}
            out['criteria'] = [{'code': c['code'], 'label': localized(c['label_i18n']), 'min': float(c['min_score']),
                                'max': float(c['max_score'])} for c in criteria]
            out['works'] = sorted([{'id': str(t['id']), 'no': nos.get(t['id']), 'photos': photos.get(t['id'], []),
                                    'source': sources.get(t['id']),
                                    'scores': {code[k]: v for k, v in own.get(t['id'], {}).items()},
                                    'done': len(scored.get(t['id'], set())) == len(criteria)} for t in targets], key=lambda w: w['no'])
        return out


class Vote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    winner: Literal['a', 'b']


@judge.post('/comparisons/{comparison_id}', dependencies=WRITE)
def vote(comparison_id: UUID, body: Vote, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        st = S.vote(conn, user['id'], comparison_id, body.winner, now_of(request))
    return judging_stream(st['id'], request, user)


class Scores(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scores: dict[str, int] = Field(min_length=1, max_length=6)   # целые 1–100 (дробные и бесконечность — 422)


@judge.post('/streams/{stream_id}/works/{target_id}', dependencies=WRITE)
def score(stream_id: UUID, target_id: UUID, body: Scores, request: Request, user=Depends(browser_user)):
    with db(request).transaction() as conn:
        S.score(conn, user['id'], stream_id, target_id, body.scores, now_of(request))
    return judging_stream(stream_id, request, user)
