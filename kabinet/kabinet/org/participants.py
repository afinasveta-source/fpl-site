"""Кабинет организатора: участницы Игры — список, карточка участия и действия организатора.

Действия (каждое — с записью в журнале и уведомлением участнице в кабинете):
- лига участницы (Bronze / Silver / Gold) — по ней выдаётся текст задания; уже выданное задание не меняется;
- личный срок сдачи тура (продление) — с причиной; срок тура для остальных не меняется;
- вне конкурса по решению организатора; вернуть в конкурс (исправление ошибки) — только если нет пропущенного срока,
  иначе сверка снова переведёт её вне конкурса: сначала продлите срок;
- вывести из Игры и вернуть; дисквалифицировать и отменить дисквалификацию.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from kabinet.participation import game as G
from kabinet.participation import rules as R
from kabinet.participation import views as V
from .common import WRITE, audit, db, iso, locked_admin, notify, now_of, org_user, person_name, problem
from .games import clean_text, load_event

router = APIRouter(prefix='/api/org', tags=['organizer'])
MODES = ('in', 'outside', 'out_pending', 'eliminated', 'withdrawn', 'disqualified', 'pending', 'completed')


def work_state(rnd, a, pa, sub, has_draft, now):
    """Как у участницы: none / draft / sent / sent_late / missed / plan (тур ещё не открыт)."""
    if sub and sub['latest_version_id']:
        return 'sent' if sub['is_on_time'] else 'sent_late'
    if rnd['status'] == 'draft' or not R.round_opened(rnd, now):
        return 'plan'
    if R.competition_deadline_passed(rnd, a, pa, now) and a['required_for_competition']:
        return 'missed'
    return 'draft' if has_draft else 'none'


def event_structure(conn, event_id):
    rounds = conn.execute("SELECT * FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no", (event_id,)).fetchall()
    mains = {}
    for r in rounds:
        a = conn.execute('''SELECT * FROM assignments WHERE round_id=%s
ORDER BY (assignment_type='competition_work') DESC, code LIMIT 1''', (r['id'],)).fetchone()
        if a:
            mains[r['id']] = a
    return rounds, mains


def variants_of(conn, task_ids):
    out = {t: [] for t in task_ids}
    for v in conn.execute('SELECT * FROM assignment_variants WHERE assignment_id = ANY(%s) ORDER BY code', (task_ids,)):
        out[v['assignment_id']].append(v)
    return out


def effective(r, a, variants, pa, ep):
    """Тур и задание с датами лиги участницы — так же, как их видит она сама (participation/game.apply_league_deadlines)."""
    if pa:
        variant = next((v for v in variants.get(a['id'], []) if v['id'] == pa['assignment_variant_id']), None)
    else:
        variant = R.pick_variant(variants.get(a['id'], []), ep)
    return R.effective_round(r, variant), R.effective_assignment(a, variant)


def works_of(conn, ep_ids, task_ids):
    pas = {(p['event_participant_id'], p['assignment_id']): p for p in conn.execute(
        'SELECT * FROM participant_assignments WHERE event_participant_id = ANY(%s) AND assignment_id = ANY(%s) AND active',
        (ep_ids, task_ids))}
    subs = {s['participant_assignment_id']: s for s in conn.execute(
        'SELECT * FROM submissions WHERE participant_assignment_id = ANY(%s) AND deleted_at IS NULL',
        ([p['id'] for p in pas.values()],))}
    drafts = {r['submission_id'] for r in conn.execute(
        'SELECT submission_id FROM submission_versions WHERE submission_id = ANY(%s) AND submitted_at IS NULL',
        ([s['id'] for s in subs.values()],))}
    return pas, subs, drafts


@router.get('/events/{event_id}/participants')
def participants(event_id: UUID, request: Request, q: str = Query('', max_length=100),
                 mode: str = Query('', pattern='^(|' + '|'.join(MODES) + ')$'),
                 league: str = Query('', pattern='^(|bronze|silver|gold|none)$'), user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        e = load_event(conn, event_id)
        if e['status'] in ('active', 'registration'):
            G.sync_event(conn, event_id, now)   # опоздавшие — вне конкурса, как увидит сама участница
        rows = conn.execute('''SELECT p.*, u.full_name, u.display_name, u.email, u.city, u.country_code, u.account_status,
ps.current_rating, ps.rating_status FROM event_participants p JOIN users u ON u.id=p.user_id
LEFT JOIN participant_stats ps ON ps.user_id=p.user_id AND ps.rating_status<>'unrated'
WHERE p.event_id=%s ORDER BY p.joined_at NULLS LAST, p.created_at''', (event_id,)).fetchall()
        rounds, mains = event_structure(conn, event_id)
        pas, subs, drafts = works_of(conn, [r['id'] for r in rows], [a['id'] for a in mains.values()])
        variants = variants_of(conn, [a['id'] for a in mains.values()])
        rules_doc = G.rules_document(conn, now)
        accepted = set()
        if rules_doc:
            accepted = {r['user_id'] for r in conn.execute('''SELECT DISTINCT ON (user_id) user_id, status FROM consents
WHERE legal_document_id=%s ORDER BY user_id, recorded_at DESC, id DESC''', (rules_doc['id'],)) if r['status'] == 'accepted'}
    current = next((r for r in reversed(rounds) if R.round_opened_any(r, variants.get(mains[r['id']]['id']) if r['id'] in mains else [], now)), None)
    term = q.strip().lower()
    out, counts, leagues = [], {}, {}
    for p in rows:
        m = R.participation_mode(p)
        counts[m] = counts.get(m, 0) + 1
        leagues[p['entry_league'] or 'none'] = leagues.get(p['entry_league'] or 'none', 0) + 1
        hay = ' '.join(str(p[k] or '') for k in ('full_name', 'display_name', 'email', 'city')).lower()
        if (term and term not in hay) or (mode and m != mode) or (league and (p['entry_league'] or 'none') != league):
            continue
        cells = []
        for r in rounds:
            a = mains.get(r['id'])
            if not a:
                cells.append({'round_no': r['round_no'], 'work': None})
                continue
            pa = pas.get((p['id'], a['id']))
            sub = subs.get(pa['id']) if pa else None
            er, a = effective(r, a, variants, pa, p)
            cells.append({'round_no': r['round_no'], 'work': work_state(er, a, pa, sub, bool(sub and sub['id'] in drafts), now),
                          'personal_deadline': iso(pa['deadline_override']) if pa and pa['deadline_override'] else None})
        out.append({'id': str(p['id']), 'user_id': str(p['user_id']), 'name': person_name(p), 'email': p['email'],
                    'city': p['city'], 'country_code': p['country_code'], 'mode': m, 'league': p['entry_league'],
                    'joined_at': iso(p['joined_at']), 'account_status': p['account_status'],
                    'rating': round(float(p['current_rating'])) if p['current_rating'] is not None else None,
                    'rules_ok': rules_doc is None or p['user_id'] in accepted, 'rounds': cells})
    return {'event': {'id': str(e['id']), 'title': e['title'], 'status': e['status']},
            'current_round': current['round_no'] if current else None,
            'rounds': [{'id': str(r['id']), 'round_no': r['round_no'], 'title': r['title']} for r in rounds],
            'participants': out, 'counts': counts, 'leagues': leagues, 'total': len(rows)}


def load_ep(conn, ep_id, lock=False):
    ep = conn.execute('SELECT * FROM event_participants WHERE id=%s' + (' FOR UPDATE' if lock else ''), (ep_id,)).fetchone()
    if not ep:
        raise HTTPException(404, 'Participant not found')
    return ep


def participant_detail(conn, ep, request, now):
    e = load_event(conn, ep['event_id'])
    u = conn.execute('SELECT * FROM users WHERE id=%s', (ep['user_id'],)).fetchone()
    game = G.load(conn, ep['event_id'], ep['user_id'])
    root = request.app.state.settings.root_path
    rounds_out = []
    for r in game.rounds:
        items = game.assignments.get(r['id'], [])
        a = items[0] if items else None
        if a is None:
            continue
        pa = game.pas.get(a['id'])
        sub = game.subs.get(a['id'])
        versions = game.versions.get(sub['id'], {}) if sub else {}
        latest = versions.get('latest')
        deadline, source = R.competition_deadline(r, a, pa)
        rounds_out.append({
            'round_id': str(r['id']), 'round_no': r['round_no'], 'title': r['title'], 'assignment_id': str(a['id']),
            'opened': R.round_opened(r, now), 'deadline': iso(deadline), 'deadline_source': source,
            'round_deadline': iso(r['deadline']),
            'personal': {'deadline': iso(pa['deadline_override']), 'reason': pa['deadline_override_reason']}
            if pa and pa['deadline_override'] else None,
            'work': work_state(r, a, pa, sub, bool(versions.get('draft')), now),
            'submitted': V.version_view(game, latest, root) | {'is_on_time': sub['is_on_time'],
                                                               'first_submitted_at': iso(sub['first_submitted_at'])}
            if latest else None})
    log = conn.execute('''SELECT a.action, a.after_data, a.reason, a.created_at, u.full_name, u.display_name, u.email
FROM audit_log a LEFT JOIN users u ON u.id=a.actor_user_id
WHERE a.entity_type='event_participant' AND a.entity_id=%s ORDER BY a.created_at DESC, a.id DESC LIMIT 30''', (ep['id'],)).fetchall()
    missed = R.missed_round(game.event, game.rounds, game.assignments, game.on_time_ids(), game.pas, now)
    return {'id': str(ep['id']), 'event': {'id': str(e['id']), 'title': e['title'], 'status': e['status']},
            'person': {'id': str(u['id']), 'name': person_name(u), 'email': u['email'], 'city': u['city'],
                       'country_code': u['country_code'], 'account_status': u['account_status']},
            'mode': R.participation_mode(ep), 'league': ep['entry_league'], 'registration_status': ep['registration_status'],
            'competition_status': ep['competition_status'], 'elimination_reason': ep['elimination_reason'],
            'out_of_competition_at': iso(ep['out_of_competition_at']), 'out_source': ep['out_of_competition_source'],
            'joined_at': iso(ep['joined_at']), 'rules_ok': G.rules_ok(conn, ep['user_id'], now),
            'missed_round': missed['round_no'] if missed else None, 'rounds': rounds_out,
            'log': [{'action': x['action'], 'data': x['after_data'], 'reason': x['reason'], 'at': iso(x['created_at']),
                     'by': person_name(x) if (x['full_name'] or x['display_name'] or x['email']) else 'Система'} for x in log]}


@router.get('/participants/{ep_id}')
def participant(ep_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        ep = load_ep(conn, ep_id)
        e = load_event(conn, ep['event_id'])
        if e['status'] in ('active', 'registration'):
            game = G.load(conn, ep['event_id'], ep['user_id'], lock=True)
            G.sync_late(conn, game, now)
            ep = load_ep(conn, ep_id)
        return participant_detail(conn, ep, request, now)


def reason_text(value):
    value = clean_text(value)
    if value is None:
        raise ValueError('Reason is required')
    return value


class LeagueIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    league: Literal['bronze', 'silver', 'gold'] | None = None


class DeadlineIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    round_id: UUID
    deadline: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim(cls, value):
        return clean_text(value)


class ActionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['outside', 'return', 'withdraw', 'restore', 'disqualify', 'undisqualify']
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim(cls, value):
        return reason_text(value)


LEAGUE_NAME = {'bronze': 'Bronze', 'silver': 'Silver', 'gold': 'Gold'}


def guard_event(e):
    if e['status'] in ('finished', 'archived'):
        raise problem('game_finished', 409)
    if e['status'] == 'draft':
        raise problem('game_draft', 409)


def league_event(conn, event_id):
    """Игра для смены лиги. Сначала Игра, потом участницы — как у публикации итогов. FOR NO KEY UPDATE: публикацию
    (FOR UPDATE) ждём, а записям участниц со ссылкой на Игру (они берут KEY SHARE) не мешаем — без взаимной блокировки.
    Лигу можно указать и после завершения Игры, пока итоги не опубликованы: без лиги диплому не дать номер, а публикация
    итогов останавливается (симуляция 13.10: выбывшая в 1 туре без лиги продолжила вне конкурса)."""
    e = conn.execute('SELECT * FROM events WHERE id=%s FOR NO KEY UPDATE', (event_id,)).fetchone()
    if not e:
        raise HTTPException(404, 'Game not found')
    results_out = bool(((e['settings'] or {}).get('results') or {}).get('published_at'))
    if not (e['status'] == 'finished' and not results_out):
        guard_event(e)
    return e


def apply_league(conn, e, ep, league, actor_id, now):
    if ep['entry_league'] == league:
        return ep, False
    ep = conn.execute('UPDATE event_participants SET entry_league=%s WHERE id=%s RETURNING *', (league, ep['id'])).fetchone()
    if e['season_id']:
        # лига в сезоне — для рейтинга на сайте (последняя назначенная; лигу сняли — и в сезоне пусто)
        conn.execute('''INSERT INTO season_participants(season_id,user_id,league_at_start,current_league) VALUES (%s,%s,%s,%s)
ON CONFLICT (season_id,user_id) DO UPDATE SET current_league=EXCLUDED.current_league,
league_at_start=coalesce(season_participants.league_at_start, EXCLUDED.league_at_start)''', (e['season_id'], ep['user_id'], league, league))
    audit(conn, actor_id, 'event_participant', ep['id'], 'league_set', {'league': league})
    notify(conn, ep['user_id'], 'league', f"league:{ep['id']}:{league or 'none'}:{now.timestamp():.0f}",
           {'title': f"Ваша лига в {e['title']} — {LEAGUE_NAME[league]}" if league
            else f"Лига в {e['title']} снята",
            'text': 'Задания туров будут для вашей лиги.' if league else 'Задания туров будут общими для всех.',
            'route': 'game', 'event_id': str(e['id'])}, e['id'])
    return ep, True


@router.post('/participants/{ep_id}/league', dependencies=WRITE)
def set_league(ep_id: UUID, body: LeagueIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = league_event(conn, load_ep(conn, ep_id)['event_id'])
        ep, _ = apply_league(conn, e, load_ep(conn, ep_id, lock=True), body.league, user['id'], now)
        return participant_detail(conn, ep, request, now)


class LeagueItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    league: Literal['bronze', 'silver', 'gold'] | None = None


class LeaguesIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[LeagueItem] = Field(min_length=1, max_length=2000)


@router.post('/events/{event_id}/leagues', dependencies=WRITE)
def set_leagues(event_id: UUID, body: LeaguesIn, request: Request, user=Depends(org_user)):
    """Лиги списком (200 участниц — одним сохранением, а не 200 переходами)."""
    now = now_of(request)
    wanted = {str(x.id): x.league for x in body.items}
    if len(wanted) != len(body.items):
        raise problem('duplicate_participant')
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = league_event(conn, event_id)
        rows = conn.execute('SELECT * FROM event_participants WHERE event_id=%s AND id = ANY(%s) ORDER BY id FOR UPDATE',
                            (event_id, list(wanted))).fetchall()     # один порядок блокировок — по id
        if len(rows) != len(wanted):
            raise problem('participant_not_in_game', 404)
        changed = sum(apply_league(conn, e, ep, wanted[str(ep['id'])], user['id'], now)[1] for ep in rows)
        return {'changed': changed}


@router.post('/participants/{ep_id}/deadline', dependencies=WRITE)
def personal_deadline(ep_id: UUID, body: DeadlineIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        ep = load_ep(conn, ep_id, lock=True)
        e = load_event(conn, ep['event_id'])
        guard_event(e)
        game = G.load(conn, ep['event_id'], ep['user_id'], lock=True)
        rnd = next((r for r in game.rounds if str(r['id']) == str(body.round_id)), None)
        if rnd is None or not game.assignments.get(rnd['id']):
            raise problem('round_not_found', 404)
        a = game.assignments[rnd['id']][0]
        if body.deadline is not None:
            if body.reason is None:
                raise problem('reason_required')
            if body.deadline <= now:
                raise problem('deadline_in_past')
            usual, _ = R.competition_deadline(rnd, a, None)   # срок тура или лиги участницы
            if usual and body.deadline <= usual:
                raise problem('not_an_extension')
            end = R.game_deadline(e)
            if end and body.deadline > end:
                raise problem('deadline_after_game_end')
            if game.mode not in (R.IN, R.OUTSIDE, R.OUT_PENDING):
                raise problem('not_participating', 409)
            pa = G.materialize(conn, game, a)   # личный срок хранится в выданном задании — выдать, если ещё не выдано
            conn.execute('''UPDATE participant_assignments SET deadline_override=%s, deadline_override_reason=%s,
deadline_override_by=%s WHERE id=%s''', (body.deadline, body.reason, user['id'], pa['id']))
            audit(conn, user['id'], 'event_participant', ep_id, 'deadline_extended',
                  {'round_no': rnd['round_no'], 'deadline': iso(body.deadline), 'reason': body.reason})
            notify(conn, ep['user_id'], 'deadline', f"deadline:{pa['id']}:{body.deadline.timestamp():.0f}",
                   {'title': f"Срок сдачи тура {rnd['round_no']} продлён для вас",
                    'text': 'Новый срок — в задании тура.', 'route': 'task', 'event_id': str(e['id']),
                    'assignment_id': str(a['id'])}, e['id'], rnd['id'])
        else:
            pa = game.pas.get(a['id'])
            if pa and pa['deadline_override']:
                if body.reason is None:
                    raise problem('reason_required')
                conn.execute('''UPDATE participant_assignments SET deadline_override=NULL, deadline_override_reason=NULL,
deadline_override_by=NULL WHERE id=%s''', (pa['id'],))
                audit(conn, user['id'], 'event_participant', ep_id, 'deadline_reset', {'round_no': rnd['round_no'], 'reason': body.reason})
                usual, _ = R.competition_deadline(rnd, a, None)
                notify(conn, ep['user_id'], 'deadline', f"deadline-reset:{pa['id']}:{now.timestamp():.0f}",
                       {'title': f"Личный срок сдачи тура {rnd['round_no']} отменён",
                        'text': 'Действует обычный срок — он в задании тура.' if usual is None or usual > now
                        else 'Обычный срок сдачи уже прошёл. Вопросы — организатору в «Поддержке».',
                        'route': 'task', 'event_id': str(e['id']), 'assignment_id': str(a['id'])}, e['id'], rnd['id'])
        return participant_detail(conn, load_ep(conn, ep_id), request, now)


TEXTS = {
    'outside': ('Вы продолжаете вне конкурса', 'Решение организатора. Работы — до конца Игры, тогда будет диплом.'),
    'return': ('Вы снова в конкурсе', 'Организатор вернул вас в конкурс.'),
    'withdraw': ('Вы выведены из Игры', 'Сдача работ закрыта. Вопросы — организатору в «Поддержке».'),
    'restore': ('Вы снова участвуете в Игре', 'Организатор вернул ваше участие.'),
    'disqualify': ('Участие в Игре прекращено', 'Решение организатора. Подробности — в «Поддержке».'),
    'undisqualify': ('Дисквалификация отменена', 'Организатор отменил решение. Участие продолжается.'),
}


def previous_state(conn, ep_id, action):
    """Состояние участницы до последнего такого действия организатора (из журнала) — для отмены этого действия."""
    row = conn.execute('''SELECT before_data FROM audit_log WHERE entity_type='event_participant' AND entity_id=%s AND action=%s
ORDER BY created_at DESC, id DESC LIMIT 1''', (ep_id, action)).fetchone()
    return (row and row['before_data']) or {}


@router.post('/participants/{ep_id}/action', dependencies=WRITE)
def action(ep_id: UUID, body: ActionIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        ep = load_ep(conn, ep_id, lock=True)
        e = load_event(conn, ep['event_id'])
        guard_event(e)
        mode = R.participation_mode(ep)
        before = {k: ep[k] for k in ('registration_status', 'competition_status', 'elimination_reason')}
        if body.action == 'outside':
            if mode != R.IN:
                raise problem('not_in_competition', 409)
            sql = '''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='admin',
out_of_competition_at=%s, out_of_competition_source='admin' WHERE id=%s RETURNING *'''
            args = (now, ep_id)
        elif body.action == 'return':
            if mode not in (R.OUTSIDE, R.OUT_PENDING, R.ELIMINATED):
                raise problem('wrong_state', 409)
            game = G.load(conn, ep['event_id'], ep['user_id'], lock=True)
            if R.missed_round(game.event, game.rounds, game.assignments, game.on_time_ids(), game.pas, now):
                raise problem('still_missed', 409)
            sql = '''UPDATE event_participants SET competition_status='active', elimination_reason=NULL,
eliminated_round_id=NULL, out_of_competition_at=NULL, out_of_competition_source=NULL WHERE id=%s RETURNING *'''
            args = (ep_id,)
        elif body.action == 'undisqualify':
            # Вернуть то состояние, что было до дисквалификации (вне конкурса, отбор жюри…), а не «в конкурсе» для всех.
            if mode != R.DISQUALIFIED:
                raise problem('wrong_state', 409)
            prev = previous_state(conn, ep_id, 'org_disqualify')
            status, reason = prev.get('competition_status') or 'active', prev.get('elimination_reason')
            if status == 'disqualified':
                status, reason = 'active', None
            if status == 'active':
                game = G.load(conn, ep['event_id'], ep['user_id'], lock=True)
                if R.missed_round(game.event, game.rounds, game.assignments, game.on_time_ids(), game.pas, now):
                    raise problem('still_missed', 409)
            sql = 'UPDATE event_participants SET competition_status=%s, elimination_reason=%s WHERE id=%s RETURNING *'
            args = (status, reason, ep_id)
        elif body.action == 'withdraw':
            if ep['registration_status'] in ('withdrawn', 'cancelled'):
                raise problem('wrong_state', 409)
            sql = "UPDATE event_participants SET registration_status='withdrawn' WHERE id=%s RETURNING *"
            args = (ep_id,)
        elif body.action == 'restore':
            if ep['registration_status'] != 'withdrawn':
                raise problem('wrong_state', 409)
            prev = previous_state(conn, ep_id, 'org_withdraw').get('registration_status')
            back = prev if prev in ('participating', 'pre_registered', 'payment_pending') else 'participating'
            sql = '''UPDATE event_participants SET registration_status=%s,
competition_status=coalesce(competition_status,'active') WHERE id=%s RETURNING *'''
            args = (back, ep_id)
        else:  # disqualify
            if mode in (R.DISQUALIFIED, R.WITHDRAWN) or ep['registration_status'] != 'participating':
                raise problem('wrong_state', 409)
            sql = "UPDATE event_participants SET competition_status='disqualified', elimination_reason='disqualified' WHERE id=%s RETURNING *"
            args = (ep_id,)
        ep = conn.execute(sql, args).fetchone()
        conn.execute('''INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,before_data,after_data,reason)
VALUES (%s,'event_participant',%s,%s,%s,%s,%s)''', (user['id'], ep_id, 'org_' + body.action, G.Jsonb(before),
                                                    G.Jsonb({k: ep[k] for k in before}), body.reason))
        title, text = TEXTS[body.action]
        notify(conn, ep['user_id'], 'status', f"org:{body.action}:{ep_id}:{now.timestamp():.0f}",
               {'title': title, 'text': text, 'route': 'game', 'event_id': str(e['id'])}, e['id'])
        return participant_detail(conn, ep, request, now)
