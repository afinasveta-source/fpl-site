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


# ---------- Пульс лиги на Обзоре (17.10): цифры за сутки и неделю, судьи, лента последних событий ----------

def _name(r):
    return r.get('full_name') or r.get('display_name') or r.get('email') or 'Без имени'


@router.get('/pulse')
def pulse(request: Request, user=Depends(org_user)):
    """Для Обзора: что произошло за последние дни. Только чтение; имена — потому что это кабинет организатора."""
    from datetime import timedelta
    now = now_of(request)
    day, week, since = now - timedelta(hours=24), now - timedelta(days=7), now - timedelta(days=3)
    with db(request).transaction() as conn:
        live = [r['id'] for r in conn.execute("SELECT id FROM events WHERE status IN ('registration','active')")]
        n = dict(conn.execute('''SELECT
  (SELECT count(DISTINCT s.id) FROM submission_versions v JOIN submissions s ON s.id=v.submission_id
     WHERE v.submitted_at > %(day)s AND v.submitted_at <= %(now)s) AS works_24h,
  (SELECT count(DISTINCT s.id) FROM submission_versions v JOIN submissions s ON s.id=v.submission_id
     WHERE v.submitted_at > %(week)s AND v.submitted_at <= %(now)s) AS works_7d,
  (SELECT count(*) FROM event_participants WHERE joined_at > %(week)s AND joined_at <= %(now)s) AS joined_7d,
  (SELECT count(*) FROM users WHERE created_at > %(week)s AND deleted_at IS NULL AND account_status<>'imported') AS accounts_7d,
  (SELECT count(DISTINCT user_id) FROM auth_sessions WHERE created_at > %(day)s) AS logins_24h,
  (SELECT count(*) FROM support_messages WHERE author_role='participant' AND created_at > %(day)s) AS support_24h''',
                          {'day': day, 'week': week, 'now': now}).fetchone())
        people = [r['user_id'] for r in conn.execute('''SELECT DISTINCT user_id FROM event_participants WHERE event_id = ANY(%s)
AND registration_status IN ('participating','completed')''', (live,))]
        from kabinet import messengers as MS
        n['messengers'] = MS.counts(conn, people) | {'people': len(people), 'channels': MS.enabled(request.app.state.settings)}
        # судьи идущего судейства: кто сколько сделал
        judges = []
        for st in conn.execute('''SELECT st.id, st.league, st.judging_method, st.judging_deadline, r.round_no, r.id AS round_id, e.title
FROM evaluation_streams st JOIN rounds r ON r.id=st.round_id JOIN events e ON e.id=r.event_id
WHERE st.active AND e.id = ANY(%s) AND r.status IN ('judging','tie_break','results_review') ORDER BY r.round_no, st.code''', (live,)):
            rows = conn.execute('''SELECT sl.id, u.full_name, u.display_name, u.email,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.judge_slot_id=sl.id AND c.status NOT IN ('cancelled','void')) AS total,
  (SELECT count(*) FROM pairwise_comparisons c WHERE c.judge_slot_id=sl.id AND c.status='voted') AS done,
  (SELECT max(c.voted_at) FROM pairwise_comparisons c WHERE c.judge_slot_id=sl.id) AS last_at
FROM evaluation_judge_slots sl
LEFT JOIN evaluation_judge_assignments a ON a.judge_slot_id=sl.id AND a.status='active'
LEFT JOIN users u ON u.id=a.user_id WHERE sl.evaluation_stream_id=%s ORDER BY sl.slot_no''', (st['id'],)).fetchall()
            if st['judging_method'] != 'pairwise':
                crit = conn.execute('''SELECT (SELECT count(*) FROM evaluation_targets WHERE evaluation_stream_id=%(s)s)
  * (SELECT count(*) FROM evaluation_criteria WHERE evaluation_stream_id=%(s)s) AS t''', {'s': st['id']}).fetchone()['t']
                rows = [dict(r) | {'total': crit, 'done': conn.execute('''SELECT count(*) AS n FROM criterion_scores
WHERE judge_slot_id=%s AND status='valid' ''', (r['id'],)).fetchone()['n'], 'last_at': None} for r in rows]
            judges.append({'round_id': str(st['round_id']), 'round_no': st['round_no'], 'league': st['league'], 'game': st['title'],
                           'deadline': iso(st['judging_deadline']),
                           'judges': [{'name': _name(r), 'done': r['done'], 'total': r['total'], 'last_at': iso(r['last_at'])} for r in rows]})
        feed = []
        for r in conn.execute('''SELECT v.submitted_at AS at, v.source, s.is_on_time, s.event_participant_id AS ep, rd.round_no,
  ep.entry_league, u.full_name, u.display_name, u.email, v.version_no
FROM submission_versions v JOIN submissions s ON s.id=v.submission_id
JOIN event_participants ep ON ep.id=s.event_participant_id JOIN users u ON u.id=ep.user_id
JOIN participant_assignments pa ON pa.id=s.participant_assignment_id JOIN assignments a ON a.id=pa.assignment_id
JOIN rounds rd ON rd.id=a.round_id
WHERE v.submitted_at > %s AND v.submitted_at <= %s ORDER BY v.submitted_at DESC LIMIT 40''', (since, now)):
            feed.append({'kind': 'work', 'at': iso(r['at']), 'name': _name(r), 'href': f"/org/participants/{r['ep']}",
                         'text': f"тур {r['round_no']}" + (' · заменила работу' if r['version_no'] > 1 and r['source'] != 'admin' else '') +
                                 (' · загрузил организатор' if r['source'] == 'admin' else '') +
                                 (' · после срока' if r['is_on_time'] is False else ''), 'league': r['entry_league']})
        for r in conn.execute('''SELECT ep.joined_at AS at, ep.id AS ep, e.title, u.full_name, u.display_name, u.email
FROM event_participants ep JOIN users u ON u.id=ep.user_id JOIN events e ON e.id=ep.event_id
WHERE ep.joined_at > %s AND ep.joined_at <= %s ORDER BY ep.joined_at DESC LIMIT 20''', (since, now)):
            feed.append({'kind': 'join', 'at': iso(r['at']), 'name': _name(r), 'text': f"записалась в «{r['title']}»",
                         'href': f"/org/participants/{r['ep']}"})
        for r in conn.execute('''SELECT m.created_at AS at, t.thread_no, t.subject, u.full_name, u.display_name, u.email
FROM support_messages m JOIN support_threads t ON t.id=m.support_thread_id LEFT JOIN users u ON u.id=t.user_id
WHERE m.author_role='participant' AND m.created_at > %s ORDER BY m.created_at DESC LIMIT 20''', (since,)):
            feed.append({'kind': 'support', 'at': iso(r['at']), 'name': _name(r), 'text': 'поддержка' + (f": {r['subject']}" if r['subject'] else ''),
                         'href': f"/org/support/{r['thread_no']}"})
        for r in conn.execute('''SELECT created_at AS at, claim_no, full_name FROM account_claims WHERE created_at > %s
ORDER BY created_at DESC LIMIT 10''', (since,)):
            feed.append({'kind': 'claim', 'at': iso(r['at']), 'name': r['full_name'], 'text': 'заявка на вход', 'href': '/org/claims'})
        for r in conn.execute('''SELECT created_at AS at FROM feedback_messages WHERE created_at > %s ORDER BY created_at DESC LIMIT 10''', (since,)):
            feed.append({'kind': 'feedback', 'at': iso(r['at']), 'name': 'Анонимно', 'text': 'пожелание с сайта', 'href': '/org/feedback'})
        feed.sort(key=lambda x: x['at'], reverse=True)
    return {'now': iso(now), 'numbers': n, 'judges': judges, 'feed': feed[:40]}
