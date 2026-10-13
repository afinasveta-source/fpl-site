"""Кабинет организатора: обзор лиги — что идёт сейчас и что требует внимания."""
from fastapi import APIRouter, Depends, Request

from kabinet.participation import game as G
from kabinet.participation import rules as R
from .common import db, iso, now_of, org_user
from .games import round_brief

router = APIRouter(prefix='/api/org', tags=['organizer'])


@router.get('/home')
def home(request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        live = conn.execute('''SELECT * FROM events WHERE status IN ('registration','active')
ORDER BY coalesce(starts_at, created_at)''').fetchall()
        games, alerts = [], []
        for e in live:
            rounds = conn.execute("SELECT * FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no", (e['id'],)).fetchall()
            people = conn.execute('''SELECT count(*) AS n FROM event_participants WHERE event_id=%s
AND registration_status='participating' ''', (e['id'],)).fetchone()['n']
            briefs = [round_brief(conn, r, now) for r in rounds]
            current = next((b for b in reversed(briefs) if b['state'] in ('open', 'closed')), None)
            upcoming = next((b for b in briefs if b['state'] == 'plan'), None)
            # подсказки организатору: шаги, которые кабинет сам не сделает (репетиция-проверка 13.10)
            gid, title = str(e['id']), e['title']
            if e['status'] == 'registration' and e['starts_at'] and e['starts_at'] <= now:
                alerts.append({'title': f'Пора начать «{title}»', 'href': f'/org/games/{gid}',
                               'text': 'Время старта прошло. Нажмите «Начать Игру» — без этого не запустится судейство, а опоздавшие не перейдут вне конкурса.'})
            if e['status'] == 'active':
                for b in briefs:
                    if b['state'] == 'closed' and b['status'] == 'scheduled':
                        alerts.append({'title': f'«{title}», тур {b["round_no"]}: приём закрыт', 'href': f'/org/rounds/{b["id"]}/judging',
                                       'text': 'Можно настраивать и начинать судейство.'})
                end = R.game_deadline(e)
                if end and end <= now:
                    alerts.append({'title': f'«{title}»: конец Игры прошёл', 'href': f'/org/games/{gid}',
                                   'text': 'Когда все туры отсужены — «Завершить Игру», затем «Подвести итоги».'})
            games.append({'id': str(e['id']), 'title': e['title'], 'status': e['status'], 'people': people,
                          'starts_at': iso(e['starts_at']), 'ends_at': iso(e['ends_at']),
                          'registration_closes_at': iso(e['registration_closes_at']),
                          'current': current, 'next': upcoming})
        docs = {k: G.current_document(conn, k, now) is not None for k in ('rules', 'publication', 'personal_data')}
        counts = conn.execute('''SELECT
  (SELECT count(*) FROM support_threads WHERE status IN ('open','waiting_admin')) AS support,
  (SELECT count(*) FROM feedback_messages WHERE status='new') AS feedback,
  (SELECT count(*) FROM review_orders WHERE status IN ('new','paid')) AS reviews,
  (SELECT count(*) FROM users WHERE account_status='imported' AND deleted_at IS NULL
     AND EXISTS (SELECT 1 FROM event_participants p WHERE p.user_id=users.id)) AS not_activated,
  (SELECT count(*) FROM events WHERE status='draft') AS drafts,
  (SELECT count(*) FROM users WHERE deleted_at IS NULL) AS people''').fetchone()
    return {'games': games, 'documents': docs, 'counts': dict(counts), 'alerts': alerts}
