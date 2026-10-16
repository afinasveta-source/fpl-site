"""Лента данных для инструмента контента (решение Светланы 16.10): только чтение, по ключу организатора.

Внешний инструмент (Codex) делает посты для соцсетей лиги из данных кабинета. Доступа к серверу у него нет: только
GET /api/feed/... с заголовком «Authorization: Bearer <ключ>». Ключ выдаёт организатор в «Ключах для данных»
(org/feed_keys.py), в базе хранится только sha256 ключа; отозванный или неизвестный ключ — 401. Куки не действуют.

Что отдаётся: Игры и туры с общими цифрами, итоги опубликованных туров, итоги Игр, FPL Rating и его изменения, очки FPL,
статистика судейства (без судей). Участница в ленте — непрозрачный постоянный id, публичное имя (только при согласии на
публикацию), город и страна — только если она их открыла. НИКОГДА: email, телефон, ФИО, контакты, обращения, судьи,
голоса, адреса. Фото работы — копия для показа, только если автор разрешил показ работ (как на сайте и в галерее),
по адресу /api/feed/media/{id} с тем же ключом. Подробно для инструмента — kabinet/FEED.md.

Частота: не больше feed_rate_limit запросов в минуту на ключ (429). «Последнее использование» и счётчик пишутся в базу
не чаще раза в feed_flush_seconds на ключ (служба одна — счёт в памяти).
"""
import hashlib
import threading
import time
from collections import deque
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from kabinet.participation import rules as R
from kabinet.participation.views import iso

router = APIRouter(prefix='/api/feed', tags=['feed'])
LEAGUES = ('gold', 'silver', 'bronze')
RULES_NOTE = ('Правила лиги, п. 7.3: пока Игра идёт (running=true), нельзя публиковать баллы и места других участниц '
              'и общий рейтинговый список (FPL Rating). Можно: TOP WORK с названием лиги («TOP WORK Gold»), общие цифры '
              '(сколько участниц, сколько работ сдано), анонсы туров. После завершения Игры — итоги по опубликованным данным. '
              'Человека (имя, работу) — только если can_post_social=true; фото работы — только из photos '
              '(они есть, только если автор разрешил показ работ). Очки FPL — не рейтинг: копятся отдельно и на рейтинг не влияют.')


def key_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def pid(user_id):
    """Непрозрачный постоянный id участницы в ленте (по нему не узнать запись в базе)."""
    return 'p_' + hashlib.sha256(f'fpl-feed:{user_id}'.encode()).hexdigest()[:20]


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------- ключ, частота, учёт использования ----------

class Gate:
    """Окно частоты на ключ и отложенная запись «последнего использования» (служба работает одним процессом)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits, self.pending, self.flushed = {}, {}, {}

    def hit(self, key_id, now, limit, window=60):
        with self.lock:
            q = self.hits.setdefault(key_id, deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            self.pending[key_id] = self.pending.get(key_id, 0) + 1
            return True

    def take(self, key_id, now, every):
        with self.lock:
            if key_id in self.flushed and now - self.flushed[key_id] < every:
                return 0
            self.flushed[key_id] = now
            return self.pending.pop(key_id, 0)


def gate_of(app):
    g = getattr(app.state, 'feed_gate', None)
    if g is None:
        g = app.state.feed_gate = Gate()
    return g


def unauthorized():
    return HTTPException(401, 'Feed key required', headers={'WWW-Authenticate': 'Bearer'})


def feed_key(request: Request):
    scheme, _, raw = request.headers.get('authorization', '').partition(' ')
    raw = raw.strip()
    if scheme.lower() != 'bearer' or not raw or len(raw) > 200:
        raise unauthorized()
    s = request.app.state.settings
    with request.app.state.db.transaction() as conn:
        row = conn.execute('SELECT id, name FROM feed_keys WHERE key_hash=%s AND revoked_at IS NULL', (key_hash(raw),)).fetchone()
        if not row:
            raise unauthorized()
        gate, t = gate_of(request.app), time.monotonic()
        if not gate.hit(row['id'], t, s.feed_rate_limit):
            raise HTTPException(429, 'Too many requests', headers={'Retry-After': '60'})
        n = gate.take(row['id'], t, s.feed_flush_seconds)
        if n:
            conn.execute('UPDATE feed_keys SET last_used_at=now(), use_count=use_count+%s WHERE id=%s', (n, row['id']))
    return row


def db(request):
    return request.app.state.db


def root(request):
    return request.app.state.settings.root_path


# ---------- кто участница и что о ней можно ----------

# Последние решения по согласиям и флаги публичности — те же правила, что у сайта (server/db/site_views.sql):
# публикация (имя, результаты, рейтинг, работы) — согласие publication; город — согласие public_profile + public_city.
PERSON = '''LEFT JOIN LATERAL (SELECT c.status FROM consents c WHERE c.user_id=u.id AND c.consent_type='publication'
                   ORDER BY c.recorded_at DESC, c.id DESC LIMIT 1) pub ON true
LEFT JOIN LATERAL (SELECT c.status FROM consents c WHERE c.user_id=u.id AND c.consent_type='public_profile'
                   ORDER BY c.recorded_at DESC, c.id DESC LIMIT 1) prof ON true'''
PERSON_COLS = '''u.id AS user_id, u.display_name, u.full_name, u.city, u.country_code,
  (pub.status = 'accepted' AND u.deleted_at IS NULL AND u.anonymized_at IS NULL) AS pub_ok,
  (prof.status = 'accepted' AND u.public_city AND u.deleted_at IS NULL AND u.anonymized_at IS NULL) AS city_ok,
  u.public_works, u.public_social, u.public_rating'''


def public_name(row):
    return (row['display_name'] or '').strip() or R.name_for_site(row['full_name']) or None


def person(row, name_ok=None):
    """Участница в ленте: id, имя (только при согласии), город/страна (только если открыты)."""
    ok = row['pub_ok'] if name_ok is None else name_ok
    return {'id': pid(row['user_id']), 'name': public_name(row) if ok else None,
            'city': row['city'] if row['city_ok'] else None, 'country': row['country_code'] if row['city_ok'] else None}


def flags(row, disqualified=False):
    show = bool(row['pub_ok'] and row['public_works'] and not disqualified)
    return {'can_show_work': show, 'can_post_social': bool(row['pub_ok'] and row['public_social'] and not disqualified)}


# Фото работы тура, которые можно отдать: тур опубликован (в том числе туры из бота), автор разрешает показ работ,
# не дисквалифицирована. Одно условие для итогов тура и для /media — чтобы адрес из ленты всегда открывался.
WORK_PHOTOS = '''SELECT p.id AS ep_id, mf.id, mf.metadata, x.sort_order FROM rounds r
JOIN assignments a ON a.id = (SELECT y.id FROM assignments y WHERE y.round_id=r.id
                              ORDER BY (y.assignment_type='competition_work') DESC, y.code LIMIT 1)
JOIN participant_assignments pa ON pa.assignment_id=a.id AND pa.active
JOIN event_participants p ON p.id=pa.event_participant_id
JOIN users u ON u.id=p.user_id
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
JOIN submission_versions v ON v.id=coalesce(s.competition_version_id, s.latest_version_id) AND v.submitted_at IS NOT NULL
JOIN submission_version_media x ON x.submission_version_id=v.id AND x.field_key='photo'
JOIN media_files mf ON mf.id=x.media_file_id AND mf.deleted_at IS NULL AND mf.optimized_storage_key IS NOT NULL
LEFT JOIN LATERAL (SELECT c.status FROM consents c WHERE c.user_id=u.id AND c.consent_type='publication'
                   ORDER BY c.recorded_at DESC, c.id DESC LIMIT 1) pub ON true
WHERE r.status='published' AND u.public_works AND pub.status='accepted' AND u.deleted_at IS NULL AND u.anonymized_at IS NULL
  AND p.competition_status IS DISTINCT FROM 'disqualified' AND {where}'''


def photo(request, m):
    meta = m['metadata'] or {}
    base = f"{root(request)}/api/feed/media/{m['id']}"
    return {'id': str(m['id']), 'url': base + '?size=view', 'thumb_url': base + '?size=thumb',
            'width': meta.get('width'), 'height': meta.get('height')}


def load_game(conn, game_id):
    e = conn.execute("SELECT * FROM events WHERE id=%s AND status<>'draft'", (game_id,)).fetchone()
    if not e:
        raise HTTPException(404, 'Game not found')
    return e


def results_published(e):
    return bool(((e['settings'] or {}).get('results') or {}).get('published_at'))


def game_head(e, season=None):
    return {'id': str(e['id']), 'title': e['title'], 'season_no': season['season_no'] if season else None,
            'game_no': e['game_no'], 'status': e['status'], 'running': e['status'] == 'active',
            'finished': e['status'] in ('finished', 'archived'), 'results_published': results_published(e)}


# ---------- Игры и туры ----------

@router.get('/games')
def games(request: Request, key=Depends(feed_key)):
    from kabinet.org.overview import people_by_event, rounds_of
    now = request.app.state.clock()
    with db(request).transaction() as conn:
        seasons = conn.execute('SELECT * FROM seasons ORDER BY season_no NULLS LAST, created_at').fetchall()
        events = conn.execute('''SELECT * FROM events WHERE status<>'draft'
ORDER BY coalesce(starts_at, created_at), game_no NULLS LAST''').fetchall()
        people = people_by_event(conn, [e['id'] for e in events])
        tw = {}
        for x in conn.execute('''SELECT rr.round_id, coalesce(rr.league, ep.entry_league) AS league, count(*) AS n FROM round_results rr
JOIN event_participants ep ON ep.id=rr.event_participant_id JOIN rounds r ON r.id=rr.round_id
WHERE rr.is_current AND rr.status='published' AND rr.top_work AND r.status='published' GROUP BY 1, 2'''):
            tw.setdefault(x['round_id'], {})[x['league'] or 'none'] = x['n']
        out = []
        for e in events:
            season = next((s for s in seasons if s['id'] == e['season_id']), None)
            p = people.get(e['id'], {'total': 0, 'in': 0, 'outside': 0, 'out': 0, 'other': 0, 'leagues': {}})
            rounds = []
            for r in rounds_of(conn, e, p, now):
                if r['phase'] == 'draft':
                    continue
                rid = UUID(r['id'])
                rounds.append({
                    'no': r['round_no'], 'title': r['title'], 'task_title': r['task_title'], 'phase': r['phase'],
                    'from_bot': r['from_bot'], 'results_published': r['status'] == 'published',
                    'opens_at': r['opens_at'], 'deadline': r['deadline'], 'judging_deadline': r['judging_deadline'],
                    'league_dates': r['league_dates'],
                    'submitted': {'total': r['works']['sent'], 'late': r['works']['late'],
                                  'by_league': {lg: x['sent'] for lg, x in r['by_league'].items() if x['sent']}},
                    'results': {'total': r['works']['results'], 'advanced': r['works']['advanced']},
                    'top_work': tw.get(rid, {}),
                    'judging': {'works': r['judging']['works'], 'done': r['judging']['done'], 'total': r['judging']['total']}
                    if r['judging'] else None})
            out.append(game_head(e, season) | {
                'type': e['event_type'], 'starts_at': iso(e['starts_at']), 'ends_at': iso(e['ends_at']),
                'registration_closes_at': iso(e['registration_closes_at']),
                'site_rating_live': bool((e['settings'] or {}).get('site_rating_live')),
                'participants': {'total': p['total'], 'in_competition': p['in'], 'outside': p['outside'], 'out': p['out'],
                                 'by_league': {lg: {'total': x['total'], 'in_competition': x['in'], 'outside': x['outside'], 'out': x['out']}
                                               for lg, x in p['leagues'].items()}},
                'rounds': rounds})
    return {'schema': 'fpl.feed.games.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE,
            'seasons': [{'no': s['season_no'], 'name': s['name'], 'status': s['status'], 'starts_at': iso(s['starts_at']),
                         'ends_at': iso(s['ends_at'])} for s in seasons],
            'games': out}


@router.get('/games/{game_id}/rounds/{round_no}/results')
def round_results(game_id: UUID, round_no: int, request: Request, key=Depends(feed_key)):
    with db(request).transaction() as conn:
        e = load_game(conn, game_id)
        season = conn.execute('SELECT season_no FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
        r = conn.execute('SELECT * FROM rounds WHERE event_id=%s AND round_no=%s', (game_id, round_no)).fetchone()
        if not r or r['status'] != 'published':
            raise HTTPException(404, 'Round results are not published')
        rows = conn.execute(f'''SELECT rr.display_score, rr.league_rank, rr.pool_size, rr.top_work, rr.advanced,
  coalesce(rr.league, p.entry_league) AS league, p.id AS ep_id, p.competition_status, {PERSON_COLS}
FROM round_results rr JOIN event_participants p ON p.id=rr.event_participant_id JOIN users u ON u.id=p.user_id
{PERSON}
WHERE rr.round_id=%s AND rr.is_current AND rr.status='published'
ORDER BY coalesce(rr.league, p.entry_league) NULLS LAST, rr.league_rank NULLS LAST, rr.display_score DESC NULLS LAST''',
                            (r['id'],)).fetchall()
        photos = {}
        for m in conn.execute(WORK_PHOTOS.format(where='r.id=%s') + ' ORDER BY x.sort_order', (r['id'],)):
            photos.setdefault(m['ep_id'], []).append(photo(request, m))
    items = []
    for x in rows:
        f = flags(x, x['competition_status'] == 'disqualified')
        items.append({'participant': person(x), 'league': x['league'],
                      'score': float(x['display_score']) if x['display_score'] is not None else None,
                      'place': x['league_rank'], 'pool_size': x['pool_size'], 'top_work': bool(x['top_work']),
                      'advanced': x['advanced'], **f, 'photos': photos.get(x['ep_id'], []) if f['can_show_work'] else []})
    return {'schema': 'fpl.feed.round_results.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE,
            'game': game_head(e, season), 'round': {'no': r['round_no'], 'title': r['title'], 'from_bot': R.bot_round(r),
                                                    'deadline': iso(r['deadline'])},
            'results': items}


@router.get('/games/{game_id}/standings')
def standings(game_id: UUID, request: Request, key=Depends(feed_key)):
    with db(request).transaction() as conn:
        e = load_game(conn, game_id)
        season = conn.execute('SELECT season_no FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
        head = game_head(e, season)
        if not head['results_published']:
            return {'schema': 'fpl.feed.standings.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE, 'game': head, 'rows': []}
        rows = conn.execute(f'''SELECT er.*, p.competition_status, {PERSON_COLS},
  EXISTS (SELECT 1 FROM certificates c WHERE c.event_participant_id=p.id AND c.certificate_type='diploma' AND c.status='issued'
          AND c.revoked_at IS NULL) AS has_diploma
FROM event_results er JOIN event_participants p ON p.id=er.event_participant_id JOIN users u ON u.id=p.user_id
{PERSON}
WHERE er.event_id=%s AND er.is_current AND er.status='published' AND er.result_kind='personal'
ORDER BY er.overall_rank NULLS LAST, er.league, er.league_rank NULLS LAST''', (game_id,)).fetchall()
        points = {}
        for t in conn.execute('''SELECT user_id, reason_code, reason_text, lifetime_delta FROM points_transactions
WHERE event_id=%s AND lifetime_delta<>0 ORDER BY created_at, id''', (game_id,)):
            points.setdefault(t['user_id'], []).append({'reason_code': t['reason_code'], 'reason': t['reason_text'],
                                                        'amount': t['lifetime_delta']})
    out = []
    for x in rows:
        snap = x['calculation_snapshot'] or {}
        pts = points.get(x['user_id'], [])
        out.append({'participant': person(x), **flags(x, x['competition_status'] == 'disqualified'), 'league': x['league'],
                    'league_rank': x['league_rank'], 'award_place': x['award_place'], 'overall_rank': x['overall_rank'],
                    'top10': bool(snap.get('top10')), 'top25': bool(snap.get('top25')), 'excluded': x['excluded_reason'],
                    'finalist': x['standing_basis'] == 'final', 'path': snap.get('path'), 'final': snap.get('final'),
                    'total': float(x['final_score']) if x['final_score'] is not None else None,
                    'top_works': snap.get('top_works', 0), 'counted': x['game_counted'], 'diploma': x['has_diploma'],
                    'points': {'total': sum(p['amount'] for p in pts), 'items': pts}})
    return {'schema': 'fpl.feed.standings.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE, 'game': head, 'rows': out}


# ---------- FPL Rating и очки FPL ----------

@router.get('/rating')
def rating(request: Request, key=Depends(feed_key)):
    """Текущий FPL Rating всех, у кого он есть. Место — среди всех (скрытые не сдвигают места, как на сайте);
    имя — только у тех, кто разрешил публиковать рейтинг (can_publish)."""
    with db(request).transaction() as conn:
        rows = conn.execute(f'''SELECT ps.current_rating, ps.rating_status, ps.calibration_rounds_completed,
  rank() OVER (ORDER BY round(ps.current_rating) DESC) AS rank,
  (SELECT sp.current_league FROM season_participants sp JOIN seasons s ON s.id=sp.season_id WHERE sp.user_id=u.id
   ORDER BY s.season_no DESC NULLS LAST LIMIT 1) AS league, {PERSON_COLS}
FROM participant_stats ps JOIN users u ON u.id=ps.user_id
{PERSON}
WHERE ps.current_rating IS NOT NULL AND ps.rating_status<>'unrated'
ORDER BY rank, u.id''').fetchall()
        running = [x['title'] for x in conn.execute("SELECT title FROM events WHERE status='active' AND event_type='ranked_game' ORDER BY starts_at")]
    out = []
    for x in rows:
        ok = bool(x['pub_ok'] and x['public_rating'])
        out.append({'participant': person(x, ok), 'can_publish': ok, 'can_post_social': bool(ok and x['public_social']),
                    'rank': x['rank'], 'rating': round(float(x['current_rating'])), 'status': x['rating_status'],
                    'calibration': x['calibration_rounds_completed'], 'league': x['league']})
    return {'schema': 'fpl.feed.rating.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE,
            'games_running': running, 'rated': len(out), 'players': out}


@router.get('/rating/history')
def rating_history(request: Request, game: UUID = Query(...), key=Depends(feed_key)):
    with db(request).transaction() as conn:
        e = load_game(conn, game)
        season = conn.execute('SELECT season_no FROM seasons WHERE id=%s', (e['season_id'],)).fetchone() if e['season_id'] else None
        rows = conn.execute(f'''SELECT t.rating_before, t.rating_after, t.delta_after_cap, t.method,
  t.calibration_rounds_completed_after, r.round_no, {PERSON_COLS}
FROM rating_transactions t LEFT JOIN rounds r ON r.id=t.round_id JOIN users u ON u.id=t.user_id
{PERSON}
WHERE t.event_id=%s AND t.status='active' ORDER BY u.id, t.ledger_seq''', (game,)).fetchall()
    num = lambda v: round(float(v)) if v is not None else None
    people = {}
    for x in rows:
        ok = bool(x['pub_ok'] and x['public_rating'])
        p = people.setdefault(x['user_id'], {'participant': person(x, ok), 'can_publish': ok, 'rounds': []})
        before, after = num(x['rating_before']), num(x['rating_after'])
        p['rounds'].append({'round_no': x['round_no'], 'method': x['method'], 'before': before, 'after': after,
                            'delta': num(x['delta_after_cap']) if x['delta_after_cap'] is not None
                            else (after - before if before is not None and after is not None else None),
                            'calibration': x['calibration_rounds_completed_after']})
    return {'schema': 'fpl.feed.rating_history.v1', 'generated_at': now_iso(), 'rules_note': RULES_NOTE,
            'game': game_head(e, season), 'participants': list(people.values())}


@router.get('/points')
def points(request: Request, key=Depends(feed_key)):
    with db(request).transaction() as conn:
        rows = conn.execute(f'''SELECT t.event_id, e.title, t.reason_code, t.reason_text, t.lifetime_delta, t.created_at, {PERSON_COLS}
FROM points_transactions t JOIN users u ON u.id=t.user_id LEFT JOIN events e ON e.id=t.event_id
{PERSON}
WHERE t.lifetime_delta<>0 ORDER BY u.id, t.created_at, t.id''').fetchall()
    people = {}
    for x in rows:
        p = people.setdefault(x['user_id'], {'participant': person(x), 'can_post_social': bool(x['pub_ok'] and x['public_social']),
                                             'total': 0, 'games': {}})
        p['total'] += x['lifetime_delta']
        g = p['games'].setdefault(x['event_id'], {'game_id': str(x['event_id']) if x['event_id'] else None, 'title': x['title'], 'items': []})
        g['items'].append({'reason_code': x['reason_code'], 'reason': x['reason_text'], 'amount': x['lifetime_delta'], 'at': iso(x['created_at'])})
    out = sorted(({**p, 'games': list(p['games'].values())} for p in people.values()), key=lambda p: -p['total'])
    return {'schema': 'fpl.feed.points.v1', 'generated_at': now_iso(),
            'note': 'Очки FPL копятся за итог Игры и TOP WORK и не сгорают. Это не FPL Rating.', 'participants': out}


# ---------- статистика судейства (без судей) ----------

@router.get('/stats')
def stats(request: Request, game: UUID | None = Query(None), key=Depends(feed_key)):
    with db(request).transaction() as conn:
        rows = conn.execute('''SELECT e.id AS event_id, e.title, r.round_no, r.title AS round_title, r.status AS round_status,
  st.league, st.judging_method,
  (SELECT count(*) FROM evaluation_targets t WHERE t.evaluation_stream_id=st.id) AS works,
  (SELECT count(*) FROM evaluation_judge_slots j WHERE j.evaluation_stream_id=st.id) AS judges,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.evaluation_stream_id=st.id AND c.status NOT IN ('cancelled','void')) AS comparisons,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.evaluation_stream_id=st.id AND c.status='voted') AS voted,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.evaluation_stream_id=st.id AND c.status='voted' AND c.phase='tie_break') AS tie_break_votes,
  (SELECT count(*) FROM evaluation_criteria k WHERE k.evaluation_stream_id=st.id) AS criteria,
  (SELECT count(*) FROM criterion_scores x WHERE x.evaluation_stream_id=st.id AND x.status='valid') AS scores
FROM evaluation_streams st JOIN rounds r ON r.id=st.round_id JOIN events e ON e.id=st.event_id
WHERE st.active AND e.status<>'draft' AND (%(g)s::uuid IS NULL OR e.id=%(g)s::uuid)
ORDER BY e.starts_at NULLS LAST, r.round_no, st.code''', {'g': game}).fetchall()
    games_out = {}
    for x in rows:
        g = games_out.setdefault(x['event_id'], {'game_id': str(x['event_id']), 'title': x['title'], 'rounds': {}})
        rd = g['rounds'].setdefault(x['round_no'], {'no': x['round_no'], 'title': x['round_title'],
                                                    'results_published': x['round_status'] == 'published', 'pools': []})
        rd['pools'].append({'league': x['league'], 'method': x['judging_method'], 'works': x['works'], 'judges': x['judges'],
                            'comparisons': x['comparisons'], 'votes': x['voted'], 'tie_break_votes': x['tie_break_votes'],
                            'criteria': x['criteria'], 'criteria_scores': x['scores']})
    out = []
    for g in games_out.values():
        rounds = list(g['rounds'].values())
        for rd in rounds:
            rd['totals'] = {k: sum(p[k] for p in rd['pools']) for k in ('works', 'votes', 'criteria_scores')}
        out.append({**g, 'rounds': rounds})
    return {'schema': 'fpl.feed.stats.v1', 'generated_at': now_iso(),
            'note': 'Без судей и без отдельных голосов: только сколько работ, судей, сравнений и оценок в каждом пуле.',
            'games': out}


# ---------- фото работ ----------

@router.get('/media/{media_id}')
def media(media_id: UUID, request: Request, size: str = Query('view', pattern='^(view|thumb)$'), key=Depends(feed_key)):
    """Копия для показа (или миниатюра) — только фото работы опубликованного тура, автор которой разрешил показ работ.
    Оригинал не отдаётся. Остальное — как будто его нет (404)."""
    with db(request).transaction() as conn:
        ok = conn.execute(WORK_PHOTOS.format(where='mf.id=%s') + ' LIMIT 1', (media_id,)).fetchone()
        row = conn.execute('SELECT * FROM media_files WHERE id=%s AND deleted_at IS NULL', (media_id,)).fetchone() if ok else None
    if not row:
        raise HTTPException(404, 'Not found')
    store_key = row['optimized_storage_key'] if size == 'view' else row['thumbnail_storage_key']
    path = request.app.state.media.path(store_key) if store_key else None
    if path is None or not path.is_file():
        raise HTTPException(404, 'Not found')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})
