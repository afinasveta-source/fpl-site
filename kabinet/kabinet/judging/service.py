"""Судейство тура в базе: настройка, запуск, голоса, расчёт итогов, переголосование, решение о проходе, публикация.

Порядок тура: настройка судейства (способ, пулы, судьи, критерии, проход) → «Начать судейство» после срока сдачи
(жеребьёвка, работы и рейтинги «замораживаются») → судьи голосуют → организатор видит итоги на проверке, границу
прохода, при необходимости проводит переголосование или решает сам → «Опубликовать итоги»: результаты тура,
выбывшие по судейству, изменение FPL Rating, уведомления. После публикации итоги не пересчитываются.

Пул (поток оценки) — одна лига или общий пул. Работа в пуле — работа участницы в конкурсе, сданная в срок;
судья видит только фото работы (без имени и ссылки). Расчёты — judging/compute.py.
"""
from collections import defaultdict

from fastapi import HTTPException

from kabinet.participation import game as G
from kabinet.participation import rules as R
from kabinet.participation.views import iso
from . import compute as C

LEAGUE_NAME = {'bronze': 'Bronze', 'silver': 'Silver', 'gold': 'Gold', None: 'Общий пул'}
ORDER = {'bronze': 1, 'silver': 2, 'gold': 3, None: 0}
DEFAULT_CONFIG = {'method': 'pairwise', 'pools': 'leagues', 'per_target': 2, 'criteria': [], 'judges': {}, 'quota': {}}


def problem(code, status=422):
    return HTTPException(status, code)


# ---------- настройка (до запуска) ----------

def config_of(rnd):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(((rnd['settings'] or {}).get('judging') or {}))
    return cfg


def main_task(conn, rnd):
    return conn.execute('''SELECT * FROM assignments WHERE round_id=%s
ORDER BY (assignment_type='competition_work') DESC, code LIMIT 1''', (rnd['id'],)).fetchone()


def pool_key(ep, cfg):
    return ep['entry_league'] if cfg['pools'] == 'leagues' else None


def candidates(conn, event, rnd, now):
    """Работы, которые пойдут в судейство: участница в конкурсе, работа сдана в срок (по первой отправке)."""
    a = main_task(conn, rnd)
    if a is None:
        return [], []
    # Судьям — версия, которая идёт в конкурс (сданная в срок), а не поздняя замена.
    rows = conn.execute('''SELECT p.*, s.id AS submission_id, coalesce(s.competition_version_id, s.latest_version_id) AS latest_version_id, s.is_on_time
FROM event_participants p
JOIN participant_assignments pa ON pa.event_participant_id=p.id AND pa.assignment_id=%s AND pa.active
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
WHERE p.event_id=%s AND s.latest_version_id IS NOT NULL AND s.is_on_time''', (a['id'], event['id'])).fetchall()
    works = [r for r in rows if R.participation_mode(r) == R.IN]
    # В конкурсе, а личный срок ещё не прошёл — она ещё может сдать или заменить работу; судейство это отрезало бы.
    pending = conn.execute('''SELECT p.id FROM event_participants p
JOIN participant_assignments pa ON pa.event_participant_id=p.id AND pa.assignment_id=%s AND pa.active
WHERE p.event_id=%s AND pa.deadline_override > %s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status='active')''', (a['id'], event['id'], now)).fetchall()
    return works, pending


def acceptance_end(conn, rnd):
    """Когда закончился приём работ в конкурсе: самый поздний из общего срока и сроков лиг."""
    from kabinet.org.rounds import league_dates
    ends = [d for d in [rnd['deadline']] + league_dates(conn, rnd['id'])['deadlines'] if d is not None]
    return max(ends) if ends else None


def eligible_judges(conn, event_id):
    """Кого можно назначить судьёй: роль «судья» или «администратор», аккаунт активен, не участник этой Игры."""
    return conn.execute('''SELECT u.id, u.full_name, u.display_name, u.email,
  EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role='judge') AS is_judge
FROM users u WHERE u.deleted_at IS NULL AND u.account_status='active'
AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role IN ('judge','admin'))
AND NOT EXISTS (SELECT 1 FROM event_participants p WHERE p.event_id=%s AND p.user_id=u.id AND p.registration_status<>'cancelled')
ORDER BY coalesce(u.full_name, u.display_name, u.email)''', (event_id,)).fetchall()


def start_checks(conn, event, rnd, cfg, now):
    """Что мешает начать судейство (problems) и на что обратить внимание (warnings); плюс пулы с числом работ."""
    problems, warnings = [], []
    if event['status'] != 'active':
        problems.append('game_not_active')
    if rnd['status'] not in ('scheduled', 'open', 'closed'):
        problems.append('judging_started' if rnd['status'] in ('judging', 'tie_break', 'results_review', 'published') else 'round_not_published')
    end = acceptance_end(conn, rnd)
    if end is None or end > now:
        problems.append('acceptance_not_over')
    works, pending = candidates(conn, event, rnd, now)
    if pending:
        problems.append('personal_deadlines_pending')
    pools = defaultdict(int)
    for w in works:
        pools[pool_key(w, cfg)] += 1
    if cfg['pools'] == 'leagues' and None in pools:
        problems.append('participants_without_league')
    if not works:
        problems.append('no_works')
    if cfg['method'] == 'criteria' and not cfg['criteria']:
        problems.append('no_criteria')
    eligible = {str(j['id']) for j in eligible_judges(conn, event['id'])}
    for key in pools:
        judges = cfg['judges'].get(key or 'all') or []
        if not judges:
            problems.append('no_judges')
        elif any(j not in eligible for j in judges):
            problems.append('judge_not_eligible')
        elif cfg['method'] == 'pairwise' and len(judges) % 2 == 0:
            warnings.append('even_judges')
    for key, n in pools.items():
        if cfg['method'] == 'pairwise' and n < 3:
            warnings.append('small_pool')
        q = cfg['quota'].get(key or 'all')
        if q is not None and q >= n:
            warnings.append('quota_covers_all')
    if rnd['judging_deadline'] is None:
        warnings.append('no_judging_deadline')
    return {'problems': sorted(set(problems), key=problems.index), 'warnings': sorted(set(warnings), key=warnings.index),
            'pools': [{'league': k, 'works': n, 'judges': len(cfg['judges'].get(k or 'all') or []),
                       'quota': cfg['quota'].get(k or 'all')} for k, n in sorted(pools.items(), key=lambda x: ORDER[x[0]])]}


def start(conn, event, rnd, actor_id, now, seed=None):
    """Запуск: пулы, судьи, работы (замороженная версия), снимок рейтингов, жеребьёвка пар. Тур → «судейство»."""
    cfg = config_of(rnd)
    G.sync_event(conn, event['id'], now)   # опоздавшие — вне конкурса до жеребьёвки
    checks = start_checks(conn, event, rnd, cfg, now)
    if checks['problems']:
        raise problem(checks['problems'][0], 409)
    works, _ = candidates(conn, event, rnd, now)
    by_pool = defaultdict(list)
    for w in works:
        by_pool[pool_key(w, cfg)].append(w)
    method = cfg['method']
    for key, items in sorted(by_pool.items(), key=lambda x: ORDER[x[0]]):
        st = conn.execute('''INSERT INTO evaluation_streams(event_id,round_id,code,target_type,judging_method,affects_rating,
comparisons_per_target_per_judge,configuration,league,judging_deadline,scoring_method)
VALUES (%s,%s,%s,'individual',%s,%s,%s,%s,%s,%s,%s) RETURNING *''', (
            event['id'], rnd['id'], key or 'all', method, event['affects_rating'],
            cfg['per_target'] if method == 'pairwise' else None,
            G.Jsonb({'quota': cfg['quota'].get(key or 'all'), 'tie_breaks': [], 'admin_decisions': []}),
            key, rnd['judging_deadline'], 'win_share_v1' if method == 'pairwise' else 'criteria_mean_v1')).fetchone()
        for i, c in enumerate(cfg['criteria'] if method == 'criteria' else []):
            conn.execute('''INSERT INTO evaluation_criteria(evaluation_stream_id,code,label_i18n,weight,min_score,max_score,sort_order)
VALUES (%s,%s,%s,%s,1,10,%s)''', (st['id'], c['code'], G.Jsonb({'ru': c['label']}), c['weight'], i))
        slots = []
        for no, user_id in enumerate(cfg['judges'].get(key or 'all') or [], 1):
            slot = conn.execute('INSERT INTO evaluation_judge_slots(evaluation_stream_id,slot_no) VALUES (%s,%s) RETURNING id',
                                (st['id'], no)).fetchone()['id']
            conn.execute('''INSERT INTO evaluation_judge_assignments(judge_slot_id,user_id,evaluation_stream_id,active_from)
VALUES (%s,%s,%s,%s)''', (slot, user_id, st['id'], now))
            slots.append(slot)
        targets = []
        for w in items:
            t = conn.execute('''INSERT INTO evaluation_targets(event_id,evaluation_stream_id,metadata) VALUES (%s,%s,%s) RETURNING id''',
                             (event['id'], st['id'], G.Jsonb({'event_participant_id': str(w['id'])}))).fetchone()['id']
            conn.execute('''INSERT INTO evaluation_target_members(event_id,evaluation_target_id,event_participant_id,submission_id,
submission_version_id) VALUES (%s,%s,%s,%s,%s)''', (event['id'], t, w['id'], w['submission_id'], w['latest_version_id']))
            targets.append(t)
            if event['affects_rating']:
                snapshot_rating(conn, event, rnd, w)
        if method == 'pairwise':
            for slot, pairs in C.draw_pairs(targets, slots, cfg['per_target'], seed=seed).items():
                for a, b in pairs:
                    conn.execute('''INSERT INTO pairwise_comparisons(evaluation_stream_id,judge_slot_id,target_a_id,target_b_id)
VALUES (%s,%s,%s,%s)''', (st['id'], slot, a, b))
        notify_judges(conn, event, rnd, st, cfg['judges'].get(key or 'all') or [], 'start')
    conn.execute("UPDATE rounds SET status='judging' WHERE id=%s", (rnd['id'],))
    G.audit(conn, actor_id, 'round', rnd['id'], 'judging_started',
            {'pools': {(k or 'all'): len(v) for k, v in by_pool.items()}, 'method': method})


def snapshot_rating(conn, event, rnd, ep):
    stats = conn.execute('SELECT * FROM participant_stats WHERE user_id=%s', (ep['user_id'],)).fetchone()
    rating = float(stats['current_rating']) if stats and stats['current_rating'] is not None else C.NEWCOMER_RATING
    cal = stats['calibration_rounds_completed'] if stats else 0
    conn.execute('''INSERT INTO round_rating_snapshots(event_id,round_id,event_participant_id,user_id,rating_snapshot,
calibration_rounds_completed_before,rating_status_before) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (round_id, event_participant_id) DO NOTHING''',
                 (event['id'], rnd['id'], ep['id'], ep['user_id'], rating, cal, 'established' if cal >= 3 else 'calibrating'))


def notify_judges(conn, event, rnd, st, user_ids, kind, extra=''):
    texts = {'start': (f"Судейство тура {rnd['round_no']} открыто", 'Работы ждут оценки в разделе «Судейство».'),
             'tie_break': (f"Переголосование: тур {rnd['round_no']}", 'Несколько работ нужно сравнить ещё раз — в разделе «Судейство».')}
    title, text = texts[kind]
    for uid in user_ids:
        G.notify(conn, uid, 'judging', f"judging:{kind}:{st['id']}:{uid}{extra}",
                 {'title': title, 'text': text, 'route': 'judging', 'stream_id': str(st['id'])}, event['id'], rnd['id'])


# ---------- состояние пула ----------

def streams_of(conn, round_id):
    return conn.execute("SELECT * FROM evaluation_streams WHERE round_id=%s AND active ORDER BY code", (round_id,)).fetchall()


def load(conn, st):
    """Всё о пуле: работы, судьи, сравнения, оценки — для расчёта и страниц."""
    targets = conn.execute('''SELECT t.id, t.status, m.event_participant_id, m.submission_id, m.submission_version_id,
p.user_id, p.entry_league, p.registration_status, p.competition_status, p.elimination_reason, u.full_name, u.display_name, u.email
FROM evaluation_targets t JOIN evaluation_target_members m ON m.evaluation_target_id=t.id
JOIN event_participants p ON p.id=m.event_participant_id JOIN users u ON u.id=p.user_id
WHERE t.evaluation_stream_id=%s ORDER BY t.created_at, t.id''', (st['id'],)).fetchall()
    slots = conn.execute('''SELECT s.id, s.slot_no, a.id AS assignment_id, a.user_id, u.full_name, u.display_name, u.email
FROM evaluation_judge_slots s LEFT JOIN evaluation_judge_assignments a ON a.judge_slot_id=s.id AND a.status='active'
LEFT JOIN users u ON u.id=a.user_id WHERE s.evaluation_stream_id=%s ORDER BY s.slot_no''', (st['id'],)).fetchall()
    comps = conn.execute('''SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND status NOT IN ('cancelled','void')
ORDER BY run_no, md5(id::text)''', (st['id'],)).fetchall()
    criteria = conn.execute('SELECT * FROM evaluation_criteria WHERE evaluation_stream_id=%s ORDER BY sort_order', (st['id'],)).fetchall()
    scores = conn.execute("SELECT * FROM criterion_scores WHERE evaluation_stream_id=%s AND status='valid'", (st['id'],)).fetchall()
    return {'targets': targets, 'slots': slots, 'comps': comps, 'criteria': criteria, 'scores': scores}


def tally(comps, phases=('regular', 'tie_break'), run=None):
    wins, total = defaultdict(int), defaultdict(int)
    for c in comps:
        if c['status'] != 'voted' or c['phase'] not in phases or (run is not None and c['run_no'] != run):
            continue
        sides = {'both': (c['target_a_id'], c['target_b_id']), 'target_a': (c['target_a_id'],),
                 'target_b': (c['target_b_id'],)}[c['counts_for']]
        for t in sides:
            total[t] += 1
            if c['winner_target_id'] == t:
                wins[t] += 1
    return wins, total


def criteria_values(data):
    weights = {c['id']: float(c['weight']) for c in data['criteria']}
    by_target = defaultdict(lambda: defaultdict(dict))
    for s in data['scores']:
        by_target[s['evaluation_target_id']][s['judge_slot_id']][s['criterion_id']] = float(s['score'])
    return {t['id']: C.criteria_value(by_target.get(t['id'], {}), weights) for t in data['targets']}


def tie_groups(st, data):
    """Проведённые переголосования: [(члены, победы, завершено)]."""
    out = []
    for tb in (st['configuration'] or {}).get('tie_breaks', []):
        run = tb['run_no']
        comps = [c for c in data['comps'] if c['phase'] == 'tie_break' and c['run_no'] == run]
        wins, _ = tally(comps, phases=('tie_break',), run=run)
        members = {m for m in tb['targets']}
        out.append((members, {str(k): v for k, v in wins.items()}, all(c['status'] == 'voted' for c in comps), tb))
    return out


def evaluate(conn, st, data=None):
    """Итоги пула на сейчас: балл, места, позиции после переголосований, TOP WORK, граница прохода."""
    data = data or load(conn, st)
    cfg = st['configuration'] or {}
    rows = []
    if st['judging_method'] == 'pairwise':
        reg_w, reg_t = tally(data['comps'], phases=('regular',))
        all_w, all_t = tally(data['comps'])
        for t in data['targets']:
            key = reg_w[t['id']] / reg_t[t['id']] if reg_t[t['id']] else None
            rows.append(C.Row(str(t['id']), key, C.win_share_score(all_w[t['id']], all_t[t['id']]),
                              extra={'wins': all_w[t['id']], 'comparisons': all_t[t['id']]}))
    else:
        values = criteria_values(data)
        for t in data['targets']:
            v = values[t['id']]
            rows.append(C.Row(str(t['id']), v, C.criteria_score(v), extra={'value': round(v, 3) if v is not None else None}))
    ordered = C.rank_rows(rows)
    n = sum(1 for r in ordered if r.key is not None)
    # Вышла, дисквалифицирована или перешла вне конкурса во время судейства — за проход и TOP WORK не борется,
    # рейтинг не меняется (её работа остаётся в голосах соперниц).
    state = {str(t['id']): R.participation_mode(t) for t in data['targets']}
    for r in ordered:
        r.extra['left'] = state[r.target] != R.IN
    staying = [r for r in ordered if not r.extra['left']]
    C.top_work(staying, sum(1 for r in staying if r.key is not None))   # по баллу тура, переголосование его не меняет
    groups = tie_groups(st, data)
    done = [(m, w) for m, w, finished, _ in groups if finished]
    order = C.apply_tie_breaks(ordered, done)
    # места — среди тех, кто в конкурсе: равные делят место, переголосование разводит своих
    prev, pos = None, 0
    for r in order:
        if r.key is None or r.extra['left']:
            r.place = None
            continue
        pos += 1
        r.place = prev.place if prev is not None and C.tie_unresolved(order, prev, r, done) else pos
        prev = r
    admin = {}
    for d in cfg.get('admin_decisions', []):
        for t in d['targets']:
            admin[t] = t in d['advance']
    border = C.boundary([r for r in order if not r.extra['left']], cfg.get('quota'), done, admin)
    # После публикации — как опубликовано: публикация сама переводит не прошедших в «выбыла по судейству»,
    # а участница может потом уйти; итог тура от этого не меняется.
    published = {str(x['evaluation_target_id']): x for x in conn.execute(
        '''SELECT evaluation_target_id, internal_rank, qualified FROM evaluation_results
WHERE evaluation_stream_id=%s AND status='published' ''', (st['id'],)).fetchall()}
    if published:
        for r in order:
            p = published.get(r.target)
            if p:
                r.extra['left'] = p['qualified'] is None
                r.place, r.advanced = p['internal_rank'], p['qualified']
    pending_regular = 0 if cfg.get('regular_closed') else sum(
        1 for c in data['comps'] if c['phase'] == 'regular' and c['status'] == 'pending')
    pending_tb = sum(1 for c in data['comps'] if c['phase'] == 'tie_break' and c['status'] == 'pending')
    if st['judging_method'] == 'criteria' and not cfg.get('regular_closed'):
        need = len(data['targets']) * len(data['criteria'])
        have = defaultdict(int)
        for s in data['scores']:
            have[s['judge_slot_id']] += 1
        pending_regular = sum(max(0, need - have[s['id']]) for s in data['slots'])
    return {'order': order, 'pool_size': n, 'border': border, 'groups': groups,
            'pending_regular': pending_regular, 'pending_tie_break': pending_tb}


def progress(st, data):
    """Сколько сделал каждый судья."""
    out = []
    for s in data['slots']:
        if st['judging_method'] == 'pairwise':
            mine = [c for c in data['comps'] if c['judge_slot_id'] == s['id']]
            done = sum(1 for c in mine if c['status'] == 'voted')
            total = len(mine)
        else:
            total = len(data['targets']) * len(data['criteria'])
            done = sum(1 for x in data['scores'] if x['judge_slot_id'] == s['id'])
        out.append({'slot_id': str(s['id']), 'slot_no': s['slot_no'], 'user_id': str(s['user_id']) if s['user_id'] else None,
                    'name': s['full_name'] or s['display_name'] or s['email'], 'done': done, 'total': total})
    return out


def stream_view(conn, st, now):
    data = load(conn, st)
    ev = evaluate(conn, st, data)
    cfg = st['configuration'] or {}
    names = {str(t['id']): (t['full_name'] or t['display_name'] or t['email'] or 'Без имени') for t in data['targets']}
    ep_of = {str(t['id']): str(t['event_participant_id']) for t in data['targets']}
    return {'id': str(st['id']), 'league': st['league'], 'league_name': LEAGUE_NAME[st['league']], 'method': st['judging_method'],
            'per_target': st['comparisons_per_target_per_judge'], 'quota': cfg.get('quota'),
            'judging_deadline': iso(st['judging_deadline']), 'pool_size': ev['pool_size'], 'works': len(data['targets']),
            'judges': progress(st, data), 'pending': ev['pending_regular'], 'pending_tie_break': ev['pending_tie_break'],
            'criteria': [{'code': c['code'], 'label': (c['label_i18n'] or {}).get('ru'), 'weight': float(c['weight'])} for c in data['criteria']],
            'border': {'status': ev['border']['status'], 'tied': ev['border']['tied'], 'close': ev['border']['close'],
                       'unjudged': ev['border'].get('unjudged', []), 'cut_score': ev['border'].get('cut_score')},
            'regular_closed': bool(cfg.get('regular_closed')),
            'rows': [{'target': r.target, 'participant_id': ep_of[r.target], 'name': names[r.target], 'score': r.score,
                      'rank': r.rank, 'position': r.position, 'place': r.place, 'tie_group_size': r.tie_group_size,
                      'top_work': r.top_work, 'left': r.extra.get('left'),
                      'advanced': r.advanced, 'wins': r.extra.get('wins'), 'comparisons': r.extra.get('comparisons'),
                      'value': r.extra.get('value'), 'tie_break_wins': r.extra.get('tie_break_wins')} for r in ev['order']],
            'tie_breaks': [{'run_no': tb['run_no'], 'goal': tb['goal'], 'targets': tb['targets'], 'finished': finished,
                            'wins': wins, 'created_at': tb['created_at']} for _, wins, finished, tb in ev['groups']],
            'admin_decisions': cfg.get('admin_decisions', [])}


# ---------- голоса ----------
# Порядок блокировок везде один: тур → пул → сравнение (публикация блокирует тур первой — голос и публикация не пересекаются).

def judge_slot(conn, user_id, stream_id):
    row = conn.execute("""SELECT a.*, s.slot_no FROM evaluation_judge_assignments a JOIN evaluation_judge_slots s ON s.id=a.judge_slot_id
WHERE a.evaluation_stream_id=%s AND a.user_id=%s AND a.status='active'
AND EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=a.user_id AND ur.role IN ('judge','admin'))""", (stream_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Not found')
    return row


def lock_stream(conn, stream_id, round_mode='SHARE'):
    """Тур (FOR SHARE для голоса, FOR UPDATE для действий организатора), потом пул (FOR UPDATE)."""
    st = conn.execute('SELECT round_id FROM evaluation_streams WHERE id=%s', (stream_id,)).fetchone()
    if not st:
        raise HTTPException(404, 'Not found')
    rnd = conn.execute(f"SELECT * FROM rounds WHERE id=%s FOR {round_mode}", (st['round_id'],)).fetchone()
    st = conn.execute('SELECT * FROM evaluation_streams WHERE id=%s FOR UPDATE', (stream_id,)).fetchone()
    return st, rnd


def check_open(st, rnd, phase):
    cfg = st['configuration'] or {}
    if rnd['status'] == 'published':
        raise problem('judging_closed', 409)
    if phase == 'regular' and (cfg.get('regular_closed') or cfg.get('tie_breaks')):
        # основное голосование закрыто организатором или уже идёт/прошло переголосование — основные голоса не меняются
        raise problem('regular_locked', 409)


def vote(conn, user_id, comparison_id, winner_side, now):
    c = conn.execute('SELECT evaluation_stream_id FROM pairwise_comparisons WHERE id=%s', (comparison_id,)).fetchone()
    if not c:
        raise HTTPException(404, 'Not found')
    st, rnd = lock_stream(conn, c['evaluation_stream_id'])
    c = conn.execute('SELECT * FROM pairwise_comparisons WHERE id=%s FOR UPDATE', (comparison_id,)).fetchone()
    if c['status'] in ('cancelled', 'void'):
        raise HTTPException(404, 'Not found')
    a = judge_slot(conn, user_id, st['id'])
    # своё место судьи; голос прежнего судьи (до замены) новый судья не видит и не меняет
    if a['judge_slot_id'] != c['judge_slot_id'] or (c['status'] == 'voted' and c['judge_assignment_id'] != a['id']):
        raise HTTPException(404, 'Not found')
    check_open(st, rnd, c['phase'])
    winner = c['target_a_id'] if winner_side == 'a' else c['target_b_id']
    if c['status'] == 'voted' and c['winner_target_id'] != winner:
        G.audit(conn, user_id, 'pairwise_comparison', c['id'], 'vote_changed',
                {'from': str(c['winner_target_id']), 'to': str(winner)})
    conn.execute('''UPDATE pairwise_comparisons SET winner_target_id=%s, judge_assignment_id=%s, status='voted', voted_at=%s
WHERE id=%s''', (winner, a['id'], now, c['id']))
    return st


def score(conn, user_id, stream_id, target_id, values, now):
    st, rnd = lock_stream(conn, stream_id)
    if st['judging_method'] != 'criteria':
        raise HTTPException(404, 'Not found')
    a = judge_slot(conn, user_id, st['id'])
    check_open(st, rnd, 'regular')
    if not conn.execute('SELECT 1 FROM evaluation_targets WHERE id=%s AND evaluation_stream_id=%s', (target_id, st['id'])).fetchone():
        raise HTTPException(404, 'Not found')
    criteria = conn.execute('SELECT * FROM evaluation_criteria WHERE evaluation_stream_id=%s', (st['id'],)).fetchall()
    codes = {c['code']: c for c in criteria}
    if set(values) != set(codes):
        raise problem('all_criteria_required')
    # оценки, выставленные прежним судьёй этого места, остаются за ним — новый судья их не меняет
    if conn.execute('''SELECT 1 FROM criterion_scores WHERE judge_slot_id=%s AND evaluation_target_id=%s AND status='valid'
AND judge_assignment_id<>%s LIMIT 1''', (a['judge_slot_id'], target_id, a['id'])).fetchone():
        raise HTTPException(404, 'Not found')
    for code, v in values.items():
        c = codes[code]
        if not (float(c['min_score']) <= v <= float(c['max_score'])):
            raise problem('score_out_of_range')
        conn.execute('''UPDATE criterion_scores SET status='void' WHERE judge_slot_id=%s AND evaluation_target_id=%s
AND criterion_id=%s AND status='valid' ''', (a['judge_slot_id'], target_id, c['id']))
        conn.execute('''INSERT INTO criterion_scores(evaluation_stream_id,judge_slot_id,judge_assignment_id,evaluation_target_id,
criterion_id,score,submitted_at) VALUES (%s,%s,%s,%s,%s,%s,%s)''', (st['id'], a['judge_slot_id'], a['id'], target_id, c['id'], v, now))
    return st


# ---------- организатор: судьи, переголосование, решение, закрытие ----------

def save_cfg(conn, st, cfg):
    conn.execute('UPDATE evaluation_streams SET configuration=%s WHERE id=%s', (G.Jsonb(cfg), st['id']))


def replace_judge(conn, st, old_user, new_user, reason, now):
    old = conn.execute('''SELECT * FROM evaluation_judge_assignments WHERE evaluation_stream_id=%s AND user_id=%s AND status='active'
FOR UPDATE''', (st['id'], old_user)).fetchone()
    if not old:
        raise problem('judge_not_found', 404)
    if conn.execute('''SELECT 1 FROM evaluation_judge_assignments WHERE evaluation_stream_id=%s AND user_id=%s AND status='active' ''',
                    (st['id'], new_user)).fetchone():
        raise problem('judge_already_in_pool', 409)
    if str(new_user) not in {str(j['id']) for j in eligible_judges(conn, st['event_id'])}:
        raise problem('judge_not_eligible')
    conn.execute('''UPDATE evaluation_judge_assignments SET status='replaced', active_to=%s, replacement_reason=%s WHERE id=%s''',
                 (now, reason, old['id']))
    # Неоценённое переходит новому судье (место судьи то же), выставленные голоса остаются за прежним.
    conn.execute('''INSERT INTO evaluation_judge_assignments(judge_slot_id,user_id,evaluation_stream_id,active_from)
VALUES (%s,%s,%s,%s)''', (old['judge_slot_id'], new_user, st['id'], now))


def start_tie_break(conn, st, targets, goal, actor_id, now):
    cfg = dict(st['configuration'] or {})
    data = load(conn, st)
    ev = evaluate(conn, st, data)
    rows = {r.target: r for r in ev['order']}
    targets = list(dict.fromkeys(str(t) for t in targets))
    # только оценённые работы тех, кто борется за проход
    if len(targets) < 2 or any(t not in rows or rows[t].key is None or rows[t].extra.get('left') for t in targets):
        raise problem('tie_break_targets')
    if ev['pending_tie_break']:
        raise problem('tie_break_running', 409)
    if ev['pending_regular']:
        raise problem('votes_pending', 409)   # сначала основное голосование (или закрыть недоделанное)
    # только равные между собой (одинаковая доля побед или оценка, не разведённые прежним переголосованием):
    # иначе переголосование подняло бы слабую работу над сильной
    done = [(m, w) for m, w, finished, _ in ev['groups'] if finished]
    first = rows[targets[0]]
    if any(not C.tie_unresolved(ev['order'], first, rows[t], done) for t in targets[1:]):
        raise problem('tie_break_not_tied')
    slots = [s for s in data['slots'] if s['assignment_id']]
    if not slots:
        raise problem('no_judges', 409)
    # номер — после всех прежних, включая отменённые (иначе уведомление судьям совпало бы с прежним и не пришло)
    run = max(1, conn.execute('''SELECT coalesce(max(run_no),1) AS m FROM pairwise_comparisons WHERE evaluation_stream_id=%s
AND phase='tie_break' ''', (st['id'],)).fetchone()['m']) + 1
    for s in slots:
        for a, b in C.tie_break_pairs(targets):
            conn.execute('''INSERT INTO pairwise_comparisons(evaluation_stream_id,judge_slot_id,target_a_id,target_b_id,phase,run_no)
VALUES (%s,%s,%s,%s,'tie_break',%s)''', (st['id'], s['id'], a, b, run))
    cfg['tie_breaks'] = cfg.get('tie_breaks', []) + [{'run_no': run, 'goal': goal, 'targets': targets, 'created_at': iso(now),
                                                      'by': str(actor_id)}]
    # решения организатора по этим работам заменяет переголосование
    cfg['admin_decisions'] = [d for d in cfg.get('admin_decisions', []) if not set(d['targets']) & set(targets)]
    save_cfg(conn, st, cfg)
    rnd = conn.execute('SELECT * FROM rounds WHERE id=%s', (st['round_id'],)).fetchone()
    event = conn.execute('SELECT * FROM events WHERE id=%s', (st['event_id'],)).fetchone()
    notify_judges(conn, event, rnd, st, [s['user_id'] for s in slots], 'tie_break', f':{run}')
    return run


def cancel_tie_break(conn, st, actor_id):
    """Отменить идущее переголосование (например, судья недоступен): его голоса не идут в счёт."""
    cfg = dict(st['configuration'] or {})
    pending = conn.execute('''SELECT DISTINCT run_no FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND phase='tie_break'
AND status='pending' ''', (st['id'],)).fetchall()
    if not pending:
        raise problem('no_tie_break', 409)
    runs = [r['run_no'] for r in pending]
    conn.execute('''UPDATE pairwise_comparisons SET status='cancelled' WHERE evaluation_stream_id=%s AND phase='tie_break'
AND run_no = ANY(%s) AND status IN ('pending','voted')''', (st['id'], runs))
    cfg['tie_breaks'] = [tb for tb in cfg.get('tie_breaks', []) if tb['run_no'] not in runs]
    cfg.setdefault('cancelled_tie_breaks', []).append({'runs': runs, 'by': str(actor_id)})
    save_cfg(conn, st, cfg)
    return runs


def admin_decision(conn, st, targets, advance, reason, actor_id, now):
    cfg = dict(st['configuration'] or {})
    ev = evaluate(conn, st)
    targets = list(dict.fromkeys(str(t) for t in targets))
    advance = list(dict.fromkeys(str(t) for t in advance))
    if ev['pending_regular'] or ev['pending_tie_break']:
        raise problem('votes_pending', 409)
    # решать можно только то, что правило не решило: равные на границе и работы без оценки
    open_ = set(ev['border']['tied']) | set(ev['border'].get('unjudged', [])) | {
        t for d in cfg.get('admin_decisions', []) for t in d['targets']}
    if not targets or any(t not in open_ for t in targets) or any(t not in targets for t in advance):
        raise problem('decision_targets')
    cfg['admin_decisions'] = [d for d in cfg.get('admin_decisions', []) if not set(d['targets']) & set(targets)] + [
        {'targets': targets, 'advance': advance, 'reason': reason, 'by': str(actor_id), 'at': iso(now)}]
    cfg['regular_closed'] = True        # итоги проверены — основные голоса больше не меняются
    save_cfg(conn, st, cfg)


def set_stream(conn, st, values):
    cfg = dict(st['configuration'] or {})
    if 'quota' in values and values['quota'] != cfg.get('quota'):
        cfg['quota'] = values['quota']
        cfg['admin_decisions'] = []     # граница сдвинулась — прежние решения о ней не действуют
    save_cfg(conn, st, cfg)
    if 'judging_deadline' in values:
        conn.execute('UPDATE evaluation_streams SET judging_deadline=%s WHERE id=%s', (values['judging_deadline'], st['id']))


def close_pending(conn, st, reason, actor_id):
    """Закрыть основное голосование: что не оценено, не идёт в счёт (судья не успевает); дальше голоса не меняются."""
    n = conn.execute('''UPDATE pairwise_comparisons SET status='cancelled' WHERE evaluation_stream_id=%s AND status='pending'
AND phase='regular' ''', (st['id'],)).rowcount
    cfg = dict(st['configuration'] or {})
    cfg['regular_closed'] = True
    cfg['closed_pending'] = {'reason': reason, 'by': str(actor_id), 'count': n}
    save_cfg(conn, st, cfg)
    return n


# ---------- публикация ----------

def publish_checks(conn, rnd):
    problems = []
    if rnd['status'] not in ('judging', 'tie_break', 'results_review'):
        problems.append('judging_not_started' if rnd['status'] != 'published' else 'already_published')
        return problems
    for st in streams_of(conn, rnd['id']):
        ev = evaluate(conn, st)
        if ev['pending_regular']:
            problems.append('votes_pending')
        if ev['pending_tie_break']:
            problems.append('tie_break_running')
        if ev['border']['status'] == 'tie':
            problems.append('border_tie')
        if ev['border']['status'] == 'unjudged':
            problems.append('unjudged_works')
    return sorted(set(problems), key=problems.index)


def publish(conn, event, rnd, actor_id, now):
    problems = publish_checks(conn, rnd)
    if problems:
        raise problem(problems[0], 409)
    next_round = conn.execute('''SELECT round_no FROM rounds WHERE event_id=%s AND round_no>%s ORDER BY round_no LIMIT 1''',
                              (event['id'], rnd['round_no'])).fetchone()
    summary = {}
    for st in streams_of(conn, rnd['id']):
        data = load(conn, st)
        ev = evaluate(conn, st, data)
        by_target = {str(t['id']): t for t in data['targets']}
        cfg = st['configuration'] or {}
        quota = cfg.get('quota')
        # решение о проходе: по правилу (+ переголосования и решения организатора — отдельными записями)
        dec = conn.execute('''INSERT INTO advancement_decisions(evaluation_stream_id,round_id,method,quota_before,quota_after,decided_by,reason,decided_at)
VALUES (%s,%s,'rule',%s,%s,%s,%s,%s) RETURNING id''', (st['id'], rnd['id'], quota, quota, actor_id, None, now)).fetchone()['id']
        for d in cfg.get('admin_decisions', []):
            ad = conn.execute('''INSERT INTO advancement_decisions(evaluation_stream_id,round_id,method,quota_before,quota_after,decided_by,reason,decided_at)
VALUES (%s,%s,'admin',%s,%s,%s,%s,%s) RETURNING id''', (st['id'], rnd['id'], quota, quota, d['by'], d['reason'], now)).fetchone()['id']
            for t in d['targets']:
                conn.execute('''INSERT INTO advancement_decision_members(decision_id,evaluation_stream_id,evaluation_target_id,advanced)
VALUES (%s,%s,%s,%s)''', (ad, st['id'], t, t in d['advance']))
        snapshot = {str(s['event_participant_id']): s for s in conn.execute(
            'SELECT * FROM round_rating_snapshots WHERE round_id=%s', (rnd['id'],))}
        rating_on = event['affects_rating'] and st['affects_rating'] and ev['pool_size'] >= 3
        outcomes = elo_outcomes(st, data, ev, snapshot) if rating_on else {}
        for r in ev['order']:
            t = by_target[r.target]
            judged = r.key is not None
            ep = conn.execute('SELECT * FROM event_participants WHERE id=%s FOR UPDATE', (t['event_participant_id'],)).fetchone()
            # за время судейства могла выйти, получить дисквалификацию или перейти вне конкурса — тогда без прохода и рейтинга
            in_comp = R.participation_mode(ep) == R.IN and not r.extra.get('left')
            advanced = bool(r.advanced) if in_comp else None
            place = r.place if judged and in_comp else None
            conn.execute('''INSERT INTO evaluation_results(evaluation_stream_id,evaluation_target_id,version_no,status,raw_score,
display_score,internal_rank,qualified,calculation_snapshot,published_at) VALUES (%s,%s,1,'published',%s,%s,%s,%s,%s,%s)''',
                         (st['id'], t['id'], r.key, r.score, place, advanced,
                          G.Jsonb({'method': st['scoring_method'], 'position': r.position, **r.extra}), now))
            if in_comp:
                conn.execute('''INSERT INTO advancement_decision_members(decision_id,evaluation_stream_id,evaluation_target_id,advanced)
VALUES (%s,%s,%s,%s)''', (dec, st['id'], t['id'], advanced))
            if in_comp and advanced is False:
                ep = conn.execute('''UPDATE event_participants SET competition_status='eliminated', elimination_reason='judged_out',
eliminated_round_id=%s WHERE id=%s RETURNING *''', (rnd['id'], ep['id'])).fetchone()
            after = ep['competition_status'] or 'active'
            conn.execute('''UPDATE round_results SET is_current=false, status='superseded' WHERE round_id=%s AND event_participant_id=%s
AND is_current''', (rnd['id'], ep['id']))
            ver = conn.execute('SELECT coalesce(max(version_no),0)+1 AS v FROM round_results WHERE round_id=%s AND event_participant_id=%s',
                               (rnd['id'], ep['id'])).fetchone()['v']
            conn.execute('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,status,display_score,advanced,
competition_status_after,calculation_snapshot,published_at,league,pool_size,league_rank,average_place,tie_group_size,top_work,top_work_rule_version)
VALUES (%s,%s,%s,%s,'published',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (
                event['id'], rnd['id'], ep['id'], ver, r.score, advanced, after,
                G.Jsonb({'stream_id': str(st['id']), 'position': r.position, **r.extra}), now,
                st['league'], ev['pool_size'] if judged else None, place,
                r.average_place, r.tie_group_size, r.top_work, C.TOPWORK_RULE if r.top_work else None))
            change = None
            if rating_on and in_comp and judged and str(ep['id']) in snapshot and outcomes.get(r.target):
                change = apply_rating(conn, event, rnd, st, ep, snapshot[str(ep['id'])], outcomes[r.target], now)
            notify_result(conn, event, rnd, ep, r, advanced, change, next_round)
            summary[st['league'] or 'all'] = summary.get(st['league'] or 'all', 0) + 1
    conn.execute("UPDATE rounds SET status='published' WHERE id=%s", (rnd['id'],))
    G.audit(conn, actor_id, 'round', rnd['id'], 'results_published', {'results': summary})
    return summary


def elo_outcomes(st, data, ev, snapshot):
    """{цель: [(рейтинг соперника, S)]} — по голосам (и переголосованию) или виртуальным исходам по оценкам."""
    rating_of = {}
    for t in data['targets']:
        s = snapshot.get(str(t['event_participant_id']))
        if s:
            rating_of[str(t['id'])] = float(s['rating_snapshot'])
    if st['judging_method'] == 'pairwise':
        out = defaultdict(list)
        for c in data['comps']:
            if c['status'] != 'voted':
                continue
            a, b = str(c['target_a_id']), str(c['target_b_id'])
            if a not in rating_of or b not in rating_of:
                continue
            win_a = 1.0 if str(c['winner_target_id']) == a else 0.0
            if c['counts_for'] in ('both', 'target_a'):
                out[a].append((rating_of[b], win_a))
            if c['counts_for'] in ('both', 'target_b'):
                out[b].append((rating_of[a], 1.0 - win_a))
        return out
    values = {r.target: r.key for r in ev['order'] if r.key is not None and r.target in rating_of}
    return C.virtual_outcomes(values, rating_of)


def apply_rating(conn, event, rnd, st, ep, snap, outcomes, now):
    before_snap = float(snap['rating_snapshot'])
    cal_before = snap['calibration_rounds_completed_before']
    raw, delta, k, cap = C.elo_delta(before_snap, outcomes, cal_before)
    stats = conn.execute('SELECT * FROM participant_stats WHERE user_id=%s FOR UPDATE', (ep['user_id'],)).fetchone()
    current = float(stats['current_rating']) if stats and stats['current_rating'] is not None else before_snap
    cal_now = stats['calibration_rounds_completed'] if stats else 0
    after = current + delta
    cal_after = min(3, cal_now + 1)
    status = 'established' if cal_after >= 3 else 'calibrating'
    if stats:
        conn.execute('''UPDATE participant_stats SET current_rating=%s, calibration_rounds_completed=%s, rating_status=%s WHERE user_id=%s''',
                     (after, cal_after, status, ep['user_id']))
    else:
        conn.execute('''INSERT INTO participant_stats(user_id,current_rating,calibration_rounds_completed,rating_status) VALUES (%s,%s,%s,%s)''',
                     (ep['user_id'], after, cal_after, status))
    conn.execute('''INSERT INTO rating_transactions(user_id,event_id,round_id,evaluation_stream_id,round_rating_snapshot_id,method,
formula_version,rating_before,delta_before_cap,delta_after_cap,rating_after,k_used,cap_used,calibration_round_no,
calibration_rounds_completed_before,calibration_rounds_completed_after,calculation_snapshot,idempotency_key,applied_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (
        ep['user_id'], event['id'], rnd['id'], st['id'], snap['id'],
        'pairwise_elo' if st['judging_method'] == 'pairwise' else 'criteria_virtual_elo', C.ELO_FORMULA,
        current, raw, delta, after, k, cap, cal_now + 1 if cal_now < 3 else None, min(3, cal_now), cal_after,
        G.Jsonb({'snapshot_rating': before_snap, 'games': len(outcomes)}), f"elo:{st['id']}:{ep['user_id']}", now))
    return {'before': round(current), 'after': round(after), 'delta': round(after) - round(current), 'calibration': cal_after}


def notify_result(conn, event, rnd, ep, row, advanced, change, next_round):
    if advanced is None:
        text = 'Итоги тура — в кабинете.'
    elif advanced:
        text = f"Вы проходите в тур {next_round['round_no']}." if next_round else 'Итоги тура — в кабинете.'
    else:
        text = 'В следующий тур вы не прошли. Можно продолжить вне конкурса — работы до конца Игры, тогда будет диплом.'
    G.notify(conn, ep['user_id'], 'results', f"results:{rnd['id']}:{ep['id']}",
             {'title': f"Итоги тура {rnd['round_no']}", 'text': text, 'route': 'game', 'event_id': str(event['id'])},
             event['id'], rnd['id'])


def round_rating_change(conn, round_id, user_id):
    """Изменение рейтинга участницы за тур (для страницы итога): до, после, изменение, калибровка."""
    t = conn.execute('''SELECT * FROM rating_transactions WHERE round_id=%s AND user_id=%s AND status='active'
ORDER BY ledger_seq DESC LIMIT 1''', (round_id, user_id)).fetchone()
    if not t:
        return None
    before, after = float(t['rating_before']), float(t['rating_after'])
    return {'before': round(before), 'after': round(after), 'delta': round(after) - round(before),
            'calibration': t['calibration_rounds_completed_after'], 'established': (t['calibration_rounds_completed_after'] or 0) >= 3}


__all__ = ['config_of', 'start_checks', 'start', 'streams_of', 'stream_view', 'vote', 'score', 'replace_judge', 'start_tie_break',
           'admin_decision', 'cancel_tie_break', 'set_stream', 'close_pending', 'publish_checks', 'publish', 'eligible_judges', 'round_rating_change']
