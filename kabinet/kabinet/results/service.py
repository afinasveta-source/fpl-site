"""Итоги Игры в базе: настройки формата, черновик итогов, решения о равных, публикация (итоги, очки, дипломы).

Опубликованные итоги не пересчитываются: после публикации Игру нельзя вернуть в работу, а итоги, очки и дипломы
читаются из записанных строк (event_results, points_transactions, certificates).
"""
from fastapi import HTTPException

from kabinet.participation import game as G
from kabinet.participation import rules as R
from kabinet.participation.views import iso
from . import compute as C

LEAGUE_NAME = {'gold': 'Gold', 'silver': 'Silver', 'bronze': 'Bronze'}


def problem(code, status=422):
    return HTTPException(status, code)


def round_nos(conn, event_id):
    return [r['round_no'] for r in conn.execute(
        "SELECT round_no FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no", (event_id,))]


def stored(e):
    return (e['settings'] or {}).get('results') or {}


def config(conn, e):
    return C.config_defaults(stored(e), round_nos(conn, e['id']))


def published(e):
    return bool(stored(e).get('published_at'))


def save(conn, e, values):
    settings = dict(e['settings'] or {})
    settings['results'] = {**stored(e), **values}
    return conn.execute('UPDATE events SET settings=%s WHERE id=%s RETURNING *', (G.Jsonb(settings), e['id'])).fetchone()


def people(conn, e, now):
    """Участницы Игры для итогов (записанные; черновые заявки и отменённые — нет)."""
    rows = conn.execute('''SELECT p.*, u.full_name, u.display_name, u.email, u.city FROM event_participants p
JOIN users u ON u.id=p.user_id WHERE p.event_id=%s AND p.registration_status NOT IN ('cancelled','pre_registered','payment_pending')
ORDER BY p.created_at, p.id''', (e['id'],)).fetchall()
    results = {}
    for r in conn.execute('''SELECT rr.*, r.round_no FROM round_results rr JOIN rounds r ON r.id=rr.round_id
WHERE rr.event_id=%s AND rr.is_current AND rr.status='published' ''', (e['id'],)):
        results.setdefault(r['event_participant_id'], []).append(r)
    out, extra = [], {}
    for ep in rows:
        mode = R.participation_mode(ep)
        excluded = {R.WITHDRAWN: 'withdrawn', R.DISQUALIFIED: 'disqualified'}.get(mode)
        if excluded is None and ep['elimination_reason'] == 'late':
            excluded = 'late'
        if excluded is None and ep['elimination_reason'] == 'admin':
            excluded = 'admin'      # организатор перевёл вне конкурса — в общий список не входит (причина в журнале)
        mine = results.get(ep['id'], [])
        # туры, где работу судили в конкурсе (у вышедших во время судейства проход не записан — не в счёт)
        scores = {r['round_no']: (float(r['display_score']) if r['display_score'] is not None else None)
                  for r in mine if r['advanced'] is not None}
        game = G.load(conn, e['id'], ep['user_id'])
        flags = R.game_flags(game.event, game.mode, game.rounds, game.assignments, game.on_time_ids(), game.by_end_ids(),
                             game.pas, now)
        p = C.Person(id=str(ep['id']), user_id=str(ep['user_id']), name=G_name(ep), league=ep['entry_league'], scores=scores,
                     excluded=excluded, counted=flags['counted'] == 'ok' and mode not in (R.WITHDRAWN, R.DISQUALIFIED),
                     diploma=bool(e['has_diploma']) and flags['diploma'] == 'all_sent' and mode != R.DISQUALIFIED,
                     top_works=[str(r['id']) for r in mine if r['top_work']])
        out.append(p)
        extra[p.id] = {'ep': ep, 'mode': mode, 'diploma_name': ep['display_name'] or ep['full_name'] or 'Участница FPL',
                       'public_name': ep['display_name']}
    return out, extra


def G_name(row):
    return row['full_name'] or row['display_name'] or row['email'] or 'Без имени'


def evaluate(conn, e, now):
    cfg = config(conn, e)
    ps, extra = people(conn, e, now)
    order = C.compute(ps, cfg, awards_points=bool(e['awards_points']))
    return cfg, order, extra


def imported(conn, event_id):
    return conn.execute('''SELECT 1 FROM round_results WHERE event_id=%s AND calculation_snapshot->>'source'='salebot' LIMIT 1''',
                        (event_id,)).fetchone() is not None


def checks(conn, e, cfg, order):
    problems, warnings = [], []
    if published(e):
        problems.append('already_published')
    if e['status'] != 'finished':
        problems.append('game_not_finished')
    if imported(conn, e['id']):
        problems.append('imported_game')    # итоги перенесённой из бота Игры переносятся готовыми (решение 12.10)
    if conn.execute("SELECT 1 FROM rounds WHERE event_id=%s AND status NOT IN ('draft','published') LIMIT 1", (e['id'],)).fetchone():
        problems.append('rounds_not_published')
    if any(p.tie for p in order):
        problems.append('place_tie')
    if cfg['final_round'] is None and not cfg['path_rounds']:
        problems.append('no_rounds')
    diplomas = [p for p in order if p.diploma]
    if diplomas:
        season = conn.execute('SELECT season_no FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
        if not season or season['season_no'] is None:
            problems.append('no_season_number')
        if e['game_no'] is None:
            problems.append('no_game_number')
        if any(p.league is None for p in diplomas):
            problems.append('diploma_without_league')
    if any(p.finalist and p.total is None for p in order):
        warnings.append('final_unjudged')
    return {'problems': problems, 'warnings': warnings}


def row_view(p, extra):
    return {'id': p.id, 'name': p.name, 'league': p.league, 'excluded': p.excluded, 'stage': p.stage, 'finalist': p.finalist,
            'path': round(p.path, 2) if p.path is not None else None, 'final': p.final, 'total': p.total,
            'league_rank': p.league_rank, 'award_place': p.award_place, 'overall_rank': p.overall_rank, 'tie': p.tie,
            'counted': p.counted, 'diploma': p.diploma, 'top_works': len(p.top_works), 'points': p.points,
            'scores': {str(k): v for k, v in sorted(p.scores.items())}}


def view(conn, e, now):
    cfg, order, extra = evaluate(conn, e, now)
    st = stored(e)
    rounds = conn.execute("SELECT round_no, title, status FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no",
                          (e['id'],)).fetchall()
    out = {'event': {'id': str(e['id']), 'title': e['title'], 'status': e['status'], 'awards_points': e['awards_points'],
                     'has_diploma': e['has_diploma']},
           'config': cfg, 'config_editable': e['status'] in ('draft', 'registration'),
           'rounds': [dict(r) for r in rounds], 'published_at': st.get('published_at')}
    if published(e):
        out['rows'] = published_rows(conn, e)
        out['checks'] = {'problems': ['already_published'], 'warnings': []}
        return out
    out['rows'] = [row_view(p, extra) for p in order]
    out['checks'] = checks(conn, e, cfg, order)
    return out


def published_rows(conn, e):
    rows = conn.execute('''SELECT er.*, u.full_name, u.display_name, u.email, c.certificate_number,
(SELECT coalesce(sum(lifetime_delta),0) FROM points_transactions pt WHERE pt.event_id=er.event_id AND pt.user_id=p.user_id) AS points
FROM event_results er JOIN event_participants p ON p.id=er.event_participant_id JOIN users u ON u.id=p.user_id
LEFT JOIN certificates c ON c.event_participant_id=p.id AND c.certificate_type='diploma' AND c.status='issued'
WHERE er.event_id=%s AND er.is_current AND er.status='published' AND er.result_kind='personal'
ORDER BY er.overall_rank NULLS LAST, er.league, er.league_rank NULLS LAST, u.full_name''', (e['id'],)).fetchall()
    out = []
    for r in rows:
        snap = r['calculation_snapshot'] or {}
        out.append({'id': str(r['event_participant_id']), 'name': G_name(r), 'league': r['league'], 'excluded': r['excluded_reason'],
                    'finalist': r['standing_basis'] == 'final', 'stage': snap.get('stage'), 'path': snap.get('path'),
                    'final': snap.get('final'), 'total': float(r['final_score']) if r['final_score'] is not None else None,
                    'league_rank': r['league_rank'], 'award_place': r['award_place'], 'overall_rank': r['overall_rank'], 'tie': [],
                    'counted': r['game_counted'], 'diploma': r['diploma_eligible'], 'top_works': snap.get('top_works', 0),
                    'points': {'total': r['points']}, 'certificate': r['certificate_number'],
                    'scores': snap.get('scores', {})})
    return out


# ---------- решения организатора ----------

def save_tie_order(conn, e, league, order_ids, reason, actor_id, now):
    if published(e):
        raise problem('already_published', 409)
    cfg, order, _ = evaluate(conn, e, now)
    tied = {tuple(sorted(p.tie)) for p in order if p.tie and p.league == league}
    ids = [str(x) for x in order_ids]
    if tuple(sorted(ids)) not in tied:
        raise problem('tie_targets')
    st = stored(e)
    orders = [o for o in st.get('tie_orders', []) if not (o.get('league') == league and set(o['order']) & set(ids))]
    orders.append({'league': league, 'order': ids, 'reason': reason, 'by': str(actor_id), 'at': iso(now)})
    e = save(conn, e, {'tie_orders': orders})
    G.audit(conn, actor_id, 'event', e['id'], 'results_tie_order', {'league': league, 'order': ids, 'reason': reason})
    return e


# ---------- публикация ----------

def publish(conn, e, actor_id, now):
    # опоздавшие, которых таймер ещё не перевёл вне конкурса, — перевести сейчас, чтобы общий список был верным
    G.sync_event(conn, e['id'], now)
    cfg, order, extra = evaluate(conn, e, now)
    ch = checks(conn, e, cfg, order)
    if ch['problems']:
        raise problem(ch['problems'][0], 409)
    season = conn.execute('SELECT * FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
    taken = {}
    for c in conn.execute('''SELECT c.certificate_number FROM certificates c JOIN event_participants p ON p.id=c.event_participant_id
WHERE p.event_id=%s AND c.certificate_number IS NOT NULL''', (e['id'],)):
        letter, n = c['certificate_number'].split('-')[3], int(c['certificate_number'].split('-')[4])
        league = {v: k for k, v in C.LEAGUE_LETTER.items()}[letter]
        taken[league] = max(taken.get(league, 0), n)
    numbers = C.diploma_numbers(order, season['season_no'], e['game_no'], taken) if any(p.diploma for p in order) else {}
    summary = {'results': 0, 'diplomas': 0, 'points': 0}
    for p in order:
        ep = extra[p.id]['ep']
        snap = {'formula': C.FORMULA, 'path_rounds': cfg['path_rounds'], 'final_round': cfg['final_round'],
                'path_weight': cfg['path_weight'], 'stage': p.stage, 'path': round(p.path, 2) if p.path is not None else None,
                'final': p.final, 'scores': {str(k): v for k, v in sorted(p.scores.items())}, 'top_works': len(p.top_works),
                'points': p.points, 'tie': None}
        basis, basis_round = (('final', None) if p.finalist and p.total is not None else
                              ('round', p.stage) if p.overall_rank is not None else (None, None))
        er = conn.execute('''INSERT INTO event_results(event_id,event_participant_id,result_kind,version_no,is_current,status,final_score,
internal_rank,award_place,game_counted,diploma_eligible,calculation_snapshot,published_at,league,league_rank,overall_rank,
standing_basis,standing_round_no,excluded_reason,formula_version) VALUES (%s,%s,'personal',1,true,'published',%s,%s,%s,%s,%s,%s,%s,
%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (
            e['id'], ep['id'], p.total, p.overall_rank, p.award_place, p.counted, p.diploma, G.Jsonb(snap), now,
            p.league, p.league_rank, p.overall_rank, basis, basis_round, p.excluded if p.excluded != 'admin' else None,
            C.FORMULA)).fetchone()
        conn.execute('UPDATE event_participants SET game_counted=%s, diploma_eligible=%s WHERE id=%s', (p.counted, p.diploma, ep['id']))
        summary['results'] += 1
        if e['awards_points']:
            summary['points'] += award_points(conn, e, ep, p, er['id'], cfg, actor_id)
        number = numbers.get(p.id)
        if number:
            issue_diploma(conn, e, season, ep, p, extra[p.id], number, now)
            summary['diplomas'] += 1
        notify_result(conn, e, ep, p, number)
    save(conn, e, {'published_at': iso(now), 'published_by': str(actor_id)})
    G.audit(conn, actor_id, 'event', e['id'], 'results_published', summary)
    return summary


def award_points(conn, e, ep, p, result_id, cfg, actor_id):
    total = 0
    pts = p.points or {}
    if pts.get('result'):
        conn.execute('''INSERT INTO points_transactions(user_id,event_id,lifetime_delta,available_delta,reason_code,reason_text,
points_rule_snapshot,created_by,idempotency_key,source_type,source_id) VALUES (%s,%s,%s,0,'game_result',%s,%s,%s,%s,'event_result',%s)''',
                     (ep['user_id'], e['id'], pts['result'], reason_text(e, p, pts['best']), G.Jsonb({**cfg['points'], 'best': pts['best']}), actor_id,
                      f"game_result:{e['id']}:{ep['user_id']}", result_id))
        total += pts['result']
    per = cfg['points']['top_work']
    if per and p.excluded != 'disqualified':
        for rr in p.top_works:
            conn.execute('''INSERT INTO points_transactions(user_id,event_id,lifetime_delta,available_delta,reason_code,reason_text,
points_rule_snapshot,created_by,idempotency_key,source_type,source_id) VALUES (%s,%s,%s,0,'top_work',%s,%s,%s,%s,'round_result',%s)''',
                         (ep['user_id'], e['id'], per, f"TOP WORK · {e['title']}", G.Jsonb({'top_work': per}), actor_id, f'top_work:{rr}', rr))
            total += per
    if total:
        conn.execute('''INSERT INTO participant_stats(user_id,lifetime_points) VALUES (%s,%s)
ON CONFLICT (user_id) DO UPDATE SET lifetime_points=participant_stats.lifetime_points + EXCLUDED.lifetime_points, updated_at=now()''',
                     (ep['user_id'], total))
    return total


def reason_text(e, p, best):
    what = {'top10': 'TOP-10 Игры', 'top25': 'TOP-25 Игры', 'completion': 'завершение Игры'}.get(best)
    if best and best.startswith('place_'):
        what = f"{best[-1]} место, лига {LEAGUE_NAME.get(p.league, '')}".strip()
    return f"Итог Игры «{e['title']}»: {what}"


def issue_diploma(conn, e, season, ep, p, extra, number, now):
    title = C.diploma_title(p)
    snap = {'name': extra['diploma_name'], 'public_name': extra['public_name'], 'city': ep['city'], 'game': e['title'], 'game_no': e['game_no'],
            'season': season['name'], 'season_no': season['season_no'], 'league': LEAGUE_NAME.get(p.league),
            'title': title, 'place': p.award_place if title else None,
            'result': (f"{title}, {p.award_place} место" if title else 'За прохождение Игры'),
            'result_en': ({1: 'Winner, 1st place', 2: 'Prize-winner, 2nd place', 3: 'Prize-winner, 3rd place'}[p.award_place]
                          if title else 'Game completed'),
            'season_en': f"Season {season['season_no']}",
            'game_counted': p.counted}
    conn.execute('''INSERT INTO certificates(event_participant_id,certificate_type,template_key,status,certificate_number,
issue_snapshot,issued_at) VALUES (%s,'diploma','game_diploma_v1','issued',%s,%s,%s)''', (ep['id'], number, G.Jsonb(snap), now))


def notify_result(conn, e, ep, p, number):
    parts = []
    if p.award_place:
        parts.append(f"{p.award_place} место в лиге {LEAGUE_NAME.get(p.league, '')}".strip())
    if number:
        parts.append(f'диплом № {number}')
    if p.points and p.points.get('total'):
        parts.append(f"+{p.points['total']} очков FPL")
    G.notify(conn, ep['user_id'], 'game_result', f"game_result:{e['id']}:{ep['id']}",
             {'title': f"Итоги Игры «{e['title']}»", 'text': ('; '.join(parts) + '.') if parts else 'Итоги опубликованы.',
              'route': 'game', 'event_id': str(e['id'])}, e['id'])


# ---------- для участницы ----------

def my_result(conn, event_id, ep_id):
    r = conn.execute('''SELECT er.*, (SELECT coalesce(sum(pt.lifetime_delta),0) FROM points_transactions pt JOIN event_participants p
  ON p.user_id=pt.user_id WHERE p.id=er.event_participant_id AND pt.event_id=er.event_id) AS points
FROM event_results er WHERE er.event_id=%s AND er.event_participant_id=%s AND er.is_current AND er.status='published'
AND er.result_kind='personal' ''', (event_id, ep_id)).fetchone()
    if not r:
        return None
    cert = conn.execute('''SELECT certificate_number, issue_snapshot FROM certificates WHERE event_participant_id=%s
AND certificate_type='diploma' AND status='issued' ''', (ep_id,)).fetchone()
    top = conn.execute('''SELECT count(*) AS n FROM round_results WHERE event_participant_id=%s AND is_current AND status='published'
AND top_work''', (ep_id,)).fetchone()['n']
    return {'total': float(r['final_score']) if r['final_score'] is not None else None, 'league': r['league'],
            'league_rank': r['league_rank'] if r['standing_basis'] == 'final' else None, 'award_place': r['award_place'],
            'top10': r['overall_rank'] is not None and r['overall_rank'] <= 10,
            'top25': r['overall_rank'] is not None and r['overall_rank'] <= 25, 'overall_rank': r['overall_rank'],
            'game_counted': r['game_counted'], 'diploma': cert['certificate_number'] if cert else None,
            'diploma_title': cert['issue_snapshot'].get('result') if cert else None,
            'points': r['points'], 'top_works': top, 'published_at': iso(r['published_at'])}
