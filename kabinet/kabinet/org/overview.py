"""Кабинет организатора: «Игры и туры» одним запросом (17.10).

Сверху — текущая Игра (games.current_event) с турами по порядку и цифрами: сколько участниц в Игре (в конкурсе / вне
конкурса / выбыли, по лигам), сколько сдали работу тура, сколько сдали после срока и сколько в конкурсе ещё не сдали,
итоги тура из бота и фото в архиве, ход судейства. Ниже — сезоны и их Игры с короткими цифрами.

Все цифры — несколькими общими запросами на Игру (а не запросом на каждую участницу или тур): при 1000 участниц
страница открывается так же быстро, как при 100.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, Request

from kabinet.participation import rules as R
from .common import db, iso, now_of, org_user
from .games import current_event, event_view, season_view
from .participants import GROUP_OF, LEAGUE_KEYS
from .rounds import round_state, variant_league

router = APIRouter(prefix='/api/org', tags=['organizer'])
JUDGING = ('judging', 'tie_break', 'results_review')


def blank_people():
    return {'total': 0, 'in': 0, 'outside': 0, 'out': 0, 'other': 0}


def people_by_event(conn, event_ids=None):
    """{event_id: {'total', 'in', 'outside', 'out', 'other', 'leagues': {лига: {...}}}} — без отменённых записей."""
    out = {}
    for r in conn.execute('''SELECT event_id, entry_league, registration_status, competition_status, elimination_reason, count(*) AS n
FROM event_participants WHERE registration_status<>'cancelled' AND (%(ids)s::uuid[] IS NULL OR event_id = ANY(%(ids)s::uuid[]))
GROUP BY 1, 2, 3, 4, 5''', {'ids': event_ids}):
        e = out.setdefault(r['event_id'], blank_people() | {'leagues': {}})
        lg = e['leagues'].setdefault(r['entry_league'] or 'none', blank_people())
        group = GROUP_OF.get(R.participation_mode(r), 'other')
        for box in (e, lg):
            box['total'] += r['n']
            box[group] += r['n']
    return out


def phase_of(r, state):
    """Что сейчас с туром — одним словом для организатора."""
    if r['status'] == 'draft':
        return 'draft'
    if R.bot_round(r):
        return 'bot'
    if r['status'] == 'published':
        return 'published'
    if r['status'] in JUDGING:
        return 'judging'
    return state   # plan / open / closed


def rounds_of(conn, e, people, now):
    """Туры Игры с датами лиг, работами, итогами и ходом судейства — по запросу на вид данных, не на тур."""
    rounds = conn.execute('SELECT * FROM rounds WHERE event_id=%s ORDER BY round_no', (e['id'],)).fetchall()
    if not rounds:
        return []
    ids = [r['id'] for r in rounds]
    mains = {a['round_id']: a for a in conn.execute('''SELECT DISTINCT ON (round_id) id, round_id, title FROM assignments
WHERE round_id = ANY(%s) ORDER BY round_id, (assignment_type='competition_work') DESC, code''', (ids,))}
    variants = defaultdict(list)
    for v in conn.execute('''SELECT v.*, a.round_id FROM assignment_variants v JOIN assignments a ON a.id=v.assignment_id
WHERE a.id = ANY(%s) AND v.active''', ([a['id'] for a in mains.values()],)):
        variants[v['round_id']].append(v)
    # Работы: выданное задание (главное задание тура) → работа со сданной версией. Лига и «в конкурсе» — по участию сейчас.
    works = defaultdict(lambda: defaultdict(lambda: {'sent': 0, 'sent_in': 0, 'late': 0}))
    for w in conn.execute('''SELECT a.round_id, ep.entry_league, ep.registration_status, ep.competition_status, ep.elimination_reason,
  count(*) AS sent, count(*) FILTER (WHERE NOT coalesce(s.is_on_time, true)) AS late
FROM event_participants ep
JOIN participant_assignments pa ON pa.event_participant_id=ep.id AND pa.active AND pa.assignment_id = ANY(%(tasks)s)
JOIN assignments a ON a.id=pa.assignment_id
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL AND s.latest_version_id IS NOT NULL
WHERE ep.event_id=%(e)s AND ep.registration_status<>'cancelled'
GROUP BY 1, 2, 3, 4, 5''', {'tasks': [a['id'] for a in mains.values()], 'e': e['id']}):
        box = works[w['round_id']][w['entry_league'] or 'none']
        box['sent'] += w['sent']
        box['late'] += w['late']
        if GROUP_OF.get(R.participation_mode(w)) == 'in':
            box['sent_in'] += w['sent']
    results = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'advanced': 0}))
    for x in conn.execute('''SELECT rr.round_id, ep.entry_league, count(*) AS n, count(*) FILTER (WHERE rr.advanced) AS advanced
FROM round_results rr JOIN event_participants ep ON ep.id=rr.event_participant_id
WHERE rr.round_id = ANY(%s) AND rr.is_current AND rr.status='published' GROUP BY 1, 2''', (ids,)):
        results[x['round_id']][x['entry_league'] or 'none'] = {'n': x['n'], 'advanced': x['advanced']}
    judging = defaultdict(list)
    for st in conn.execute('''SELECT st.round_id, st.league, st.judging_method,
  (SELECT count(*) FROM evaluation_targets t WHERE t.evaluation_stream_id=st.id) AS works,
  (SELECT count(*) FROM evaluation_judge_slots j WHERE j.evaluation_stream_id=st.id) AS judges,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.evaluation_stream_id=st.id AND c.status NOT IN ('cancelled','void')) AS comps,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.evaluation_stream_id=st.id AND c.status='voted') AS voted,
  (SELECT count(*) FROM evaluation_criteria k WHERE k.evaluation_stream_id=st.id) AS criteria,
  (SELECT count(*) FROM criterion_scores x WHERE x.evaluation_stream_id=st.id AND x.status='valid') AS scored
FROM evaluation_streams st WHERE st.round_id = ANY(%s) AND st.active ORDER BY st.code''', (ids,)):
        if st['judging_method'] == 'pairwise':
            done, total = st['voted'], st['comps']
        else:
            done, total = st['scored'], st['works'] * st['criteria'] * st['judges']
        judging[st['round_id']].append({'league': st['league'], 'works': st['works'], 'judges': st['judges'],
                                        'done': done, 'total': total})
    in_now = {lg: v['in'] for lg, v in people.get('leagues', {}).items()}
    out = []
    for r in rounds:
        own = [v for v in variants.get(r['id'], []) if variant_league(v)]
        dates = {'opens': [d for d in (R.variant_opens_at(v) for v in own) if d], 'deadlines': [d for d in (R.variant_deadline(v) for v in own) if d]}
        state = round_state(r, now, dates)
        phase = phase_of(r, state)
        leagues = sorted(({'league': variant_league(v), 'opens_at': iso(R.variant_opens_at(v) or r['opens_at']),
                           'deadline': iso(R.variant_deadline(v) or r['deadline'])} for v in own
                          if (R.variant_opens_at(v) and R.variant_opens_at(v) != r['opens_at'])
                          or (R.variant_deadline(v) and R.variant_deadline(v) != r['deadline'])),
                         key=lambda x: LEAGUE_KEYS.index(x['league']))
        by_league = {}
        for lg in LEAGUE_KEYS:
            w = works[r['id']].get(lg, {'sent': 0, 'sent_in': 0, 'late': 0})
            res = results[r['id']].get(lg, {'n': 0, 'advanced': 0})
            row = {'sent': w['sent'], 'late': w['late'], 'in_now': in_now.get(lg, 0), 'results': res['n'], 'advanced': res['advanced']}
            # «в конкурсе не сдали» имеет смысл, пока тур не отсужен: потом статусы уже сдвинулись по итогам тура
            if phase in ('open', 'closed') and not R.bot_round(r):
                row['missing_in'] = max(0, in_now.get(lg, 0) - w['sent_in'])
            if any(row.values()):
                by_league[lg] = row
        total = {k: sum(x.get(k, 0) for x in by_league.values()) for k in ('sent', 'late', 'results', 'advanced', 'missing_in')}
        streams = judging.get(r['id'], [])
        a = mains.get(r['id'])
        out.append({'id': str(r['id']), 'round_no': r['round_no'], 'title': r['title'], 'status': r['status'], 'state': state,
                    'phase': phase, 'from_bot': R.bot_round(r), 'task_title': a['title'] if a else None,
                    'opens_at': iso(r['opens_at']), 'deadline': iso(r['deadline']), 'judging_deadline': iso(r['judging_deadline']),
                    'league_dates': leagues, 'works': total, 'by_league': by_league,
                    'judging': {'done': sum(s['done'] for s in streams), 'total': sum(s['total'] for s in streams),
                                'works': sum(s['works'] for s in streams), 'streams': streams} if streams else None})
    # «Сейчас» — последний тур, где что-то происходит (идёт сдача, ждёт судейства или судится); иначе ближайший впереди
    live = [x for x in out if x['phase'] in ('open', 'closed', 'judging')]
    ahead = [x for x in out if x['phase'] == 'plan']
    now_round = live[-1] if live else (ahead[0] if ahead else None)
    if now_round:
        now_round['current'] = True
    return out


@router.get('/games/overview')
def overview(request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        seasons = conn.execute('SELECT * FROM seasons ORDER BY season_no NULLS LAST, created_at').fetchall()
        events = conn.execute('''SELECT e.*, (SELECT count(*) FROM rounds r WHERE r.event_id=e.id) AS rounds_count,
  (SELECT count(*) FROM rounds r WHERE r.event_id=e.id AND r.status='published') AS rounds_done
FROM events e ORDER BY e.game_no NULLS LAST, coalesce(e.starts_at, e.created_at), e.created_at''').fetchall()
        people = people_by_event(conn)
        cur = current_event(conn)
        current = None
        if cur:
            season = next((s for s in seasons if s['id'] == cur['season_id']), None)
            p = people.get(cur['id'], blank_people() | {'leagues': {}})
            current = event_view(cur, season) | {'people': p, 'rounds': rounds_of(conn, cur, p, now),
                                                 'results_published': bool(((cur['settings'] or {}).get('results') or {}).get('published_at'))}
    by_season = defaultdict(list)
    for e in events:
        p = people.get(e['id'], blank_people() | {'leagues': {}})
        by_season[e['season_id']].append({'id': str(e['id']), 'title': e['title'], 'status': e['status'], 'type': e['event_type'],
                                          'game_no': e['game_no'], 'starts_at': iso(e['starts_at']), 'ends_at': iso(e['ends_at']),
                                          'rounds_count': e['rounds_count'], 'rounds_done': e['rounds_done'],
                                          'people': {k: p[k] for k in ('total', 'in', 'outside', 'out')},
                                          'current': bool(cur and e['id'] == cur['id'])})
    return {'current': current,
            'seasons': [season_view(s, len(by_season.get(s['id'], []))) | {'events': by_season.get(s['id'], []),
                                                                            'current': bool(cur and cur['season_id'] == s['id'])}
                        for s in seasons],
            'no_season': by_season.get(None, [])}
