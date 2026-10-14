"""Кабинет организатора: обзор лиги — что идёт сейчас и что требует внимания."""
from fastapi import APIRouter, Depends, Request

from kabinet.participation import game as G
from kabinet.participation import rules as R
from .common import db, iso, now_of, org_user
from .games import round_brief

router = APIRouter(prefix='/api/org', tags=['organizer'])


def attention(conn):
    """Что ждёт организатора (счётчики в меню, в заголовке вкладки и «Требует внимания» на Обзоре):
    support — обращения, где последней написала участница (статус «ждёт организатора»: новое или её ответ после нашего);
    feedback — новые пожелания с сайта (не открытые: статус new); reviews — заказы разборов «новый» и «оплачен»;
    claims — заявки на вход из бота + зарегистрировавшиеся сами, похожие на участницу Игры 01 без входа.
    Простые счёты по небольшим таблицам — страница спрашивает раз в минуту."""
    from kabinet.claims import accounts_to_link
    c = dict(conn.execute('''SELECT
  (SELECT count(*) FROM support_threads WHERE status IN ('open','waiting_admin')) AS support,
  (SELECT count(*) FROM feedback_messages WHERE status='new') AS feedback,
  (SELECT count(*) FROM review_orders WHERE status IN ('new','paid')) AS reviews,
  (SELECT count(*) FROM account_claims WHERE status='pending') AS claims_pending''').fetchone())
    c['accounts'] = accounts_to_link(conn)
    c['claims'] = c['claims_pending'] + c['accounts']
    c['total'] = c['support'] + c['feedback'] + c['reviews'] + c['claims']
    return c


@router.get('/attention')
def attention_counts(request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return attention(conn)


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
            # туры, прошедшие в боте (Игра 01, туры 1–2), — не «текущие»: их работы были в боте, в кабинете «0 сдали»
            briefs = [round_brief(conn, r, now) for r in rounds if (r['settings'] or {}).get('source') != 'bot']
            current = next((b for b in reversed(briefs) if b['state'] in ('open', 'closed')), None)
            upcoming = next((b for b in briefs if b['state'] == 'plan'), None)
            # подсказки организатору: шаги, которые кабинет сам не сделает (репетиция-проверка 13.10)
            gid, title = str(e['id']), e['title']
            if e['status'] == 'registration' and e['starts_at'] and e['starts_at'] <= now:
                alerts.append({'title': f'Пора начать «{title}»', 'href': f'/org/games/{gid}',
                               'text': 'Время старта прошло. Нажмите «Начать Игру» — без этого не запустится судейство, а опоздавшие не перейдут вне конкурса.'})
            if e['status'] == 'active':
                from kabinet import relay
                for r in rounds:
                    rc = relay.relay_of(r)
                    if rc and rc['sources'] == 'top' and r['status'] in ('scheduled', 'open', 'closed') \
                            and relay.early_stream(conn, r, rc) is None:
                        dl = relay.source_deadline(conn, r, rc)
                        from kabinet.judging import service as JS
                        blocked = {'no_works', 'early_needs_leagues'} & set(JS.early_checks(conn, e, r, JS.config_of(r), now)['problems'])
                        if blocked and dl and dl < now:
                            alerts.append({'title': f'«{title}», тур {r["round_no"]}: эстафета без исходников', 'href': f'/org/rounds/{r["id"]}',
                                           'text': 'В первой лиге нет работ для судейства (или пулы не по лигам). Вторая лига ждёт исходник — выключите эстафету или поменяйте настройку.'})
                        elif dl and dl < now:
                            alerts.append({'title': f'«{title}», тур {r["round_no"]}: начните судейство первой лиги', 'href': f'/org/rounds/{r["id"]}/judging',
                                           'text': 'Срок первой лиги прошёл. Её судят раньше, чтобы раздать второй лиге лучшие работы.'})
                    if rc and not relay.released(r) and relay.ready(conn, r, now):
                        alerts.append({'title': f'«{title}», тур {r["round_no"]}: проверьте исходники', 'href': f'/org/rounds/{r["id"]}',
                                       'text': 'Первая лига сдала работы. Проверьте раздачу и нажмите «Отправить исходники» — до этого вторая лига работать не может.'})
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
        counts = attention(conn) | dict(conn.execute('''SELECT
  (SELECT count(*) FROM events WHERE settings ? 'moved_to_kabinet') AS moved_games,
  (SELECT count(*) FROM users WHERE account_status='imported' AND deleted_at IS NULL
     AND EXISTS (SELECT 1 FROM event_participants p WHERE p.user_id=users.id)) AS not_activated,
  (SELECT count(*) FROM events WHERE status='draft') AS drafts,
  (SELECT count(*) FROM users WHERE deleted_at IS NULL) AS people''').fetchone())
    return {'games': games, 'documents': docs, 'counts': counts, 'alerts': alerts}
