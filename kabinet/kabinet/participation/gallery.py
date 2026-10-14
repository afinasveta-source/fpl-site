"""Галерея работ тура в кабинете участницы (решение 15.10).

Правила (по умолчанию; организатор может поменять):
- тур виден в галерее только после публикации итогов (status='published'; туры 1–2 Игры 01 из бота — опубликованы);
  пока идёт сдача или судейство — работ не видно никому, кроме организатора в его кабинете;
- работа показывается, если автор сейчас разрешает публикацию — то же условие, что у сайта (server/db/site_views.sql,
  site_public_people.show_works): последнее решение по согласию publication — «accepted» и включено «Показывать работы»
  (users.public_works), профиль не удалён и не обезличен; работы дисквалифицированных не показываются;
  свою работу участница видит всегда;
- подпись — публичное имя (как на сайте: публичное имя, иначе из ФИО) и лига; баллов, мест и рейтинга других нет
  (Правила, п. 7.3); TOP WORK — отметкой и отдельным блоком;
- фото — версия, которая шла в конкурс, иначе последняя сданная (в том числе фото из бота и загруженные в архив);
- открыть галерею Игры может её участница (в любом состоянии участия), организатор / модератор — любую, судья — Игр,
  в которых он судит (чужие работы другим судьям не открываются: так же устроен доступ судьи разборов).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from kabinet.web.routes import browser_user
from . import rules as R
from . import views as V

router = APIRouter(prefix='/api/gallery', tags=['participant'])
STAFF = ('admin', 'moderator')
# Игры, где человек судья (назначен в судейство хоть одного тура), — как в проверке «судья не участвует в своей Игре» (схема 004)
JUDGED = '''SELECT 1 FROM evaluation_judge_assignments a JOIN evaluation_streams st ON st.id=a.evaluation_stream_id
WHERE st.event_id={event} AND a.user_id=%(viewer)s AND a.status<>'void' '''
LEAGUE_ORDER = {'gold': 0, 'silver': 1, 'bronze': 2}


def db(request):
    return request.app.state.db


def is_staff(user):
    return any(r in STAFF for r in user['roles'])


def can_open(conn, user, event_id):
    if is_staff(user):
        return True
    if conn.execute('SELECT 1 FROM event_participants WHERE event_id=%s AND user_id=%s', (event_id, user['id'])).fetchone():
        return True
    return 'judge' in user['roles'] and conn.execute(JUDGED.format(event='%(event)s') + ' LIMIT 1',
                                                     {'event': event_id, 'viewer': user['id']}).fetchone() is not None


# Работы опубликованного тура, которые может видеть viewer. Условие показа — как у сайта (site_public_people.show_works).
WORKS_SQL = '''SELECT s.id AS submission_id, p.user_id, u.display_name, u.full_name, p.entry_league, rr.league AS round_league,
  coalesce(rr.top_work, false) AS top_work, m.id, m.metadata, r.id AS round_id, r.event_id,
  (u.public_works AND pub.status = 'accepted' AND u.deleted_at IS NULL AND u.anonymized_at IS NULL
   AND p.competition_status IS DISTINCT FROM 'disqualified') AS public
FROM rounds r
JOIN assignments a ON a.id = (SELECT x.id FROM assignments x WHERE x.round_id=r.id
                              ORDER BY (x.assignment_type='competition_work') DESC, x.code LIMIT 1)
JOIN participant_assignments pa ON pa.assignment_id=a.id AND pa.active
JOIN event_participants p ON p.id=pa.event_participant_id
JOIN users u ON u.id=p.user_id
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
JOIN submission_versions v ON v.id=coalesce(s.competition_version_id, s.latest_version_id) AND v.submitted_at IS NOT NULL
JOIN LATERAL (SELECT mf.id, mf.metadata FROM submission_version_media x JOIN media_files mf ON mf.id=x.media_file_id
              WHERE x.submission_version_id=v.id AND x.field_key='photo' AND mf.deleted_at IS NULL AND mf.storage_key IS NOT NULL
              ORDER BY x.sort_order LIMIT 1) m ON true
LEFT JOIN round_results rr ON rr.round_id=r.id AND rr.event_participant_id=p.id AND rr.is_current AND rr.status='published'
LEFT JOIN LATERAL (SELECT c.status FROM consents c WHERE c.user_id=u.id AND c.consent_type='publication'
                   ORDER BY c.recorded_at DESC, c.id DESC LIMIT 1) pub ON true
WHERE r.status='published' AND {where}'''
VISIBLE = '''(p.user_id=%(viewer)s OR (u.public_works AND pub.status = 'accepted' AND u.deleted_at IS NULL AND u.anonymized_at IS NULL
  AND p.competition_status IS DISTINCT FROM 'disqualified'))'''


def works(conn, viewer_id, round_id):
    return conn.execute(WORKS_SQL.format(where='r.id=%(round)s AND ' + VISIBLE), {'round': round_id, 'viewer': viewer_id}).fetchall()


def media_allowed(conn, user, media_id):
    """Фото работы из галереи: тур опубликован, автор разрешает показ (или это своя), зритель — участница Игры или staff.
    Отдаются только копии для показа (view / thumb) — оригинал наружу не отдаётся никому."""
    rows = conn.execute(WORKS_SQL.format(where='m.id=%(media)s AND ' + VISIBLE), {'media': media_id, 'viewer': user['id']}).fetchall()
    return any(can_open(conn, user, r['event_id']) for r in rows)


def author_name(row):
    return (row['display_name'] or '').strip() or R.name_for_site(row['full_name']) or 'Участница'


def item_view(row, viewer_id, root):
    own = row['user_id'] == viewer_id
    return {'id': str(row['submission_id']), 'author': author_name(row), 'league': row['round_league'] or row['entry_league'],
            'top_work': row['top_work'], 'own': own, 'only_you': own and not row['public'],
            'photo': V.photo_view(row, root)}


def sort_key(it):
    return (LEAGUE_ORDER.get(it['league'], 9), it['author'].lower())


@router.get('')
def overview(request: Request, user=Depends(browser_user)):
    """Игры, которые можно открыть, их туры (опубликован ли итог) и что показать по умолчанию."""
    with db(request).transaction() as conn:
        if is_staff(user):
            events = conn.execute('''SELECT e.* FROM events e WHERE e.status<>'draft'
ORDER BY coalesce(e.starts_at, e.created_at) DESC''').fetchall()
        else:
            events = conn.execute('''SELECT e.* FROM events e WHERE e.status<>'draft' AND (
  EXISTS (SELECT 1 FROM event_participants p WHERE p.event_id=e.id AND p.user_id=%(viewer)s)
  OR EXISTS (''' + JUDGED.format(event='e.id') + '''))
ORDER BY coalesce(e.starts_at, e.created_at) DESC''', {'viewer': user['id']}).fetchall()
        rounds = {}
        for r in conn.execute('''SELECT id, event_id, round_no, title, status, settings FROM rounds WHERE event_id = ANY(%s)
AND status<>'draft' ORDER BY round_no''', ([e['id'] for e in events],)):
            rounds.setdefault(r['event_id'], []).append(r)
    games = [{'id': str(e['id']), 'title': e['title'], 'status': e['status'],
              'rounds': [{'id': str(r['id']), 'round_no': r['round_no'], 'title': r['title'], 'published': r['status'] == 'published',
                          'from_bot': R.bot_round(r)} for r in rounds.get(e['id'], [])]} for e in events]
    # по умолчанию — текущая Игра (идущая, иначе последняя) и её последний тур с опубликованными итогами
    current = next((g for g in games if g['status'] in ('active', 'registration')), games[0] if games else None)
    default = None
    if current:
        pub = [r for r in current['rounds'] if r['published']]
        pick = pub[-1] if pub else (current['rounds'][-1] if current['rounds'] else None)
        default = {'event_id': current['id'], 'round_id': pick['id'] if pick else None}
    return {'games': games, 'default': default}


@router.get('/{event_id}/rounds/{round_id}')
def round_gallery(event_id: UUID, round_id: UUID, request: Request, user=Depends(browser_user)):
    root = request.app.state.settings.root_path
    with db(request).transaction() as conn:
        rnd = conn.execute('''SELECT r.*, e.title AS event_title FROM rounds r JOIN events e ON e.id=r.event_id
WHERE r.id=%s AND r.event_id=%s AND r.status<>'draft' AND e.status<>'draft' ''', (round_id, event_id)).fetchone()
        if not rnd or not can_open(conn, user, event_id):
            raise HTTPException(404, 'Not found')       # чужая Игра — как будто её нет
        published = rnd['status'] == 'published'
        rows = works(conn, user['id'], round_id) if published else []
    items = sorted((item_view(r, user['id'], root) for r in rows), key=sort_key)
    leagues = {}
    for it in items:
        leagues[it['league'] or 'none'] = leagues.get(it['league'] or 'none', 0) + 1
    return {'event': {'id': str(event_id), 'title': rnd['event_title']},
            'round': {'id': str(rnd['id']), 'round_no': rnd['round_no'], 'title': rnd['title'], 'published': published,
                      'from_bot': R.bot_round(rnd)},
            'top': [it for it in items if it['top_work']], 'items': items, 'leagues': leagues, 'total': len(items)}
