"""Тур-эстафета: вторая лига работает по работам первой (решения Светланы 13.10; механика 3 и 4 тура Игры 01 из бота).

3 тур: Gold (Лига А) делает свою работу, после её срока каждой участнице Silver (Лига Б) выдаётся работа Gold как исходник —
повторить. 4 тур — зеркально: Silver делает, Gold усложняет. Настройка тура: rounds.settings.relay = {'from': лига, 'to': лига}.

Правила раздачи:
- раздача начинается, когда второй лиге открылось задание (своя дата открытия лиги не раньше срока первой лиги — проверяет
  организатор при настройке); набор исходников закрепляется при первой раздаче и дальше не меняется;
- исходники — работы первой лиги, сданные в конкурс в срок (версия, которая идёт судьям); если таких нет — любые сданные
  работы первой лиги (вне конкурса тоже);
- исходник получают все участницы второй лиги — и в конкурсе, и вне конкурса (в боте вне конкурса оставались без исходника —
  дыра, найденная 03.10); поздно пришедшие получают его при первом открытии задания;
- раздача равномерная: каждой — исходник, у которого сейчас меньше всего получателей (при равенстве — случайный);
  работ меньше, чем получателей, — одна работа достаётся нескольким;
- выданный исходник не меняется; автор не узнаёт, кому досталась её работа, получательница — чья она (без имён и ссылок).
"""
import random

from kabinet.participation import rules as R

GROUP = 'relay'
LEAGUES = ('bronze', 'silver', 'gold')


def relay_of(rnd):
    cfg = ((rnd or {}).get('settings') or {}).get('relay') or {}
    if cfg.get('from') in LEAGUES and cfg.get('to') in LEAGUES and cfg['from'] != cfg['to']:
        return {'from': cfg['from'], 'to': cfg['to']}
    return None


def main_task(conn, round_id):
    return conn.execute('''SELECT * FROM assignments WHERE round_id=%s
ORDER BY (assignment_type='competition_work') DESC, code LIMIT 1''', (round_id,)).fetchone()


def _variants(conn, assignment_id):
    return conn.execute('SELECT * FROM assignment_variants WHERE assignment_id=%s', (assignment_id,)).fetchall()


def league_dates(conn, rnd, league):
    """Открытие и срок задания для лиги: своя дата лиги → дата задания → дата тура."""
    a = main_task(conn, rnd['id'])
    if a is None:
        return None, None
    v = R.pick_variant(_variants(conn, a['id']), {'entry_league': league})
    opens = R.variant_opens_at(v) or rnd['opens_at']
    deadline = R.variant_deadline(v) or a['deadline'] or rnd['deadline']
    return opens, deadline


def second_open(conn, rnd, now):
    cfg = relay_of(rnd)
    if not cfg or rnd['status'] == 'draft':
        return False
    a = main_task(conn, rnd['id'])
    if a is None:
        return False
    v = R.pick_variant(_variants(conn, a['id']), {'entry_league': cfg['to']})
    return R.round_opened(R.effective_round(rnd, v) if v else rnd, now)


def problems(conn, rnd):
    """Что не так с настройкой эстафеты (для проверок тура): вторая лига открывается раньше срока первой."""
    cfg = relay_of(rnd)
    if not cfg:
        return []
    _, first_deadline = league_dates(conn, rnd, cfg['from'])
    second_opens, _ = league_dates(conn, rnd, cfg['to'])
    if first_deadline is None or second_opens is None:
        return ['relay_dates_missing']
    if second_opens < first_deadline:
        return ['relay_opens_before_source_deadline']
    return []


def _lock(conn, round_id):
    # Отдельная блокировка раздачи (не строка тура). Участница приходит с занятой своей записью и ждёт эту блокировку;
    # сверка, держа её, занятые записи участниц пропускает (SKIP LOCKED в _recipients) — ожидания по кругу нет.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ('relay:' + str(round_id),))


def _pool(conn, rnd, cfg, assignment_id):
    rows = conn.execute('''SELECT p.id AS ep_id, s.competition_version_id AS version_id, v.submitted_at
FROM event_participants p
JOIN participant_assignments pa ON pa.event_participant_id=p.id AND pa.assignment_id=%s AND pa.active
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
JOIN submission_versions v ON v.id=s.competition_version_id
WHERE p.event_id=%s AND p.entry_league=%s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status <> 'disqualified')
AND EXISTS (SELECT 1 FROM submission_version_media m WHERE m.submission_version_id=v.id AND m.field_key='photo')''',
                        (assignment_id, rnd['event_id'], cfg['from'])).fetchall()
    if rows:
        return rows
    return conn.execute('''SELECT p.id AS ep_id, s.latest_version_id AS version_id, v.submitted_at
FROM event_participants p
JOIN participant_assignments pa ON pa.event_participant_id=p.id AND pa.assignment_id=%s AND pa.active
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
JOIN submission_versions v ON v.id=s.latest_version_id
WHERE p.event_id=%s AND p.entry_league=%s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status <> 'disqualified')
AND EXISTS (SELECT 1 FROM submission_version_media m WHERE m.submission_version_id=v.id AND m.field_key='photo')''',
                        (assignment_id, rnd['event_id'], cfg['from'])).fetchall()


def _recipients(conn, rnd, cfg, only_ep=None, lock=False):
    """Получательницы. lock — для общей раздачи (сверка): строки берутся FOR KEY SHARE SKIP LOCKED — участницу, чья запись
    сейчас занята (она как раз открывает задание), сверка пропускает: исходник ей выдаст её же запрос. Так ожидание
    по кругу «запись участницы ↔ блокировка раздачи» невозможно."""
    q = '''SELECT id, user_id FROM event_participants WHERE event_id=%s AND entry_league=%s AND registration_status='participating'
AND (competition_status IS NULL OR competition_status IN ('active','diploma_only'))'''
    args = [rnd['event_id'], cfg['to']]
    if only_ep is not None:
        q += ' AND id=%s'
        args.append(only_ep)
    if lock:
        q += ' FOR KEY SHARE SKIP LOCKED'
    return conn.execute(q, args).fetchall()


def source_deadline(conn, rnd, cfg):
    """Когда первая лига закончила сдавать: её срок, а если у кого-то из неё личное продление — самое позднее."""
    _, deadline = league_dates(conn, rnd, cfg['from'])
    a = main_task(conn, rnd['id'])
    if a is None or deadline is None:
        return deadline
    row = conn.execute('''SELECT max(pa.deadline_override) AS d FROM participant_assignments pa
JOIN event_participants p ON p.id=pa.event_participant_id
WHERE pa.assignment_id=%s AND pa.active AND p.entry_league=%s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status='active')''', (a['id'], cfg['from'])).fetchone()
    return max(deadline, row['d']) if row and row['d'] else deadline


def distribute(conn, rnd, now, only_ep=None, rng=None):
    """Выдать исходники тем участницам второй лиги, у кого их ещё нет. Возвращает число выданных.
    only_ep — только этой участнице (при открытии задания). Безопасно вызывать сколько угодно раз."""
    rnd = conn.execute('SELECT * FROM rounds WHERE id=%s', (rnd['id'],)).fetchone()   # тур из базы, а не «глазами лиги»
    cfg = relay_of(rnd)
    if not cfg:
        return 0
    if only_ep is not None and has_source(conn, rnd['id'], only_ep):
        return 0            # уже выдан — без общей блокировки раздачи
    if not second_open(conn, rnd, now):
        return 0
    a = main_task(conn, rnd['id'])
    if a is None:
        return 0
    first_deadline = source_deadline(conn, rnd, cfg)
    if first_deadline is None or now <= first_deadline:
        return 0            # первая лига ещё сдаёт (в том числе по личному продлению) — исходники не раздаются
    rng = rng or random.SystemRandom()
    _lock(conn, rnd['id'])
    items = conn.execute('SELECT id FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s', (rnd['id'], GROUP)).fetchall()
    if not items:
        for w in _pool(conn, rnd, cfg, a['id']):
            conn.execute('''INSERT INTO exchange_items(round_id,event_participant_id,assignment_id,exchange_group_key,item_type,
source_submission_version_id,submitted_at) VALUES (%s,%s,%s,%s,'media',%s,%s)
ON CONFLICT (round_id, exchange_group_key, source_submission_version_id) WHERE source_submission_version_id IS NOT NULL DO NOTHING''',
                         (rnd['id'], w['ep_id'], a['id'], GROUP, w['version_id'], w['submitted_at']))
        items = conn.execute('SELECT id FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s', (rnd['id'], GROUP)).fetchall()
        if items:
            conn.execute('''INSERT INTO audit_log(entity_type,entity_id,action,after_data) VALUES ('round',%s,'relay_pool_fixed',%s)''',
                         (rnd['id'], _json({'from': cfg['from'], 'to': cfg['to'], 'works': len(items)})))
    if not items:
        return 0
    items = conn.execute('SELECT id, event_participant_id AS author FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s',
                         (rnd['id'], GROUP)).fetchall()
    author = {i['id']: i['author'] for i in items}
    counts = {i['id']: 0 for i in items}
    for r in conn.execute('''SELECT exchange_item_id, count(*) AS n FROM exchange_assignments
WHERE round_id=%s AND exchange_group_key=%s AND active GROUP BY exchange_item_id''', (rnd['id'], GROUP)):
        counts[r['exchange_item_id']] = r['n']
    have = {r['recipient_event_participant_id'] for r in conn.execute('''SELECT recipient_event_participant_id FROM exchange_assignments
WHERE round_id=%s AND exchange_group_key=%s AND active''', (rnd['id'], GROUP))}
    todo = [p for p in _recipients(conn, rnd, cfg, only_ep, lock=only_ep is None) if p['id'] not in have]
    rng.shuffle(todo)
    order = sorted(counts)          # стабильный порядок, случайность — только в выборе среди равных
    from kabinet.participation.game import notify
    given = 0
    for p in todo:
        options = [i for i in order if author[i] != p['id']]     # свою работу (если сменила лигу) не получает
        if not options:
            continue
        low = min(counts[i] for i in options)
        pick = rng.choice([i for i in options if counts[i] == low])
        conn.execute('''INSERT INTO exchange_assignments(round_id,exchange_group_key,exchange_item_id,recipient_event_participant_id,source,assigned_at)
VALUES (%s,%s,%s,%s,'automatic',%s)''', (rnd['id'], GROUP, pick, p['id'], now))
        counts[pick] += 1
        given += 1
        notify(conn, p['user_id'], 'task', f"relay:{rnd['id']}:{p['id']}",
               {'title': f"Тур {rnd['round_no']}: ваш исходник готов", 'text': 'Задание и работа-исходник — в кабинете.',
                'route': 'task', 'event_id': str(rnd['event_id']), 'assignment_id': str(a['id'])}, rnd['event_id'], rnd['id'])
    return given


def league_changed(conn, ep_id, league):
    """Организатор сменил лигу участнице: выдачи туров-эстафет, где она больше не получательница, снимаются
    (после смены ей выдастся исходник по новой лиге, если положен)."""
    for r in conn.execute('''SELECT ea.id, r.settings FROM exchange_assignments ea JOIN rounds r ON r.id=ea.round_id
WHERE ea.recipient_event_participant_id=%s AND ea.active AND ea.exchange_group_key=%s''', (ep_id, GROUP)).fetchall():
        cfg = relay_of({'settings': r['settings']})
        if not cfg or cfg['to'] != league:
            conn.execute('''UPDATE exchange_assignments SET active=false, replaced_at=now(), replacement_reason='league_changed'
WHERE id=%s''', (r['id'],))


def _json(value):
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def source_rows(conn, round_id, ep_ids):
    """Фото исходников: {event_participant_id получательницы: [строки media_files]} (по порядку фото)."""
    if not ep_ids:
        return {}
    out = {}
    for r in conn.execute('''SELECT ea.recipient_event_participant_id AS ep_id, mf.*
FROM exchange_assignments ea JOIN exchange_items ei ON ei.id=ea.exchange_item_id
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id AND svm.field_key='photo'
JOIN media_files mf ON mf.id=svm.media_file_id
WHERE ea.round_id=%s AND ea.exchange_group_key=%s AND ea.active AND ea.recipient_event_participant_id = ANY(%s)
ORDER BY svm.sort_order''', (round_id, GROUP, list(ep_ids))):
        out.setdefault(r['ep_id'], []).append(r)
    return out


def has_source(conn, round_id, ep_id):
    return conn.execute('''SELECT 1 FROM exchange_assignments WHERE round_id=%s AND exchange_group_key=%s AND active
AND recipient_event_participant_id=%s''', (round_id, GROUP, ep_id)).fetchone() is not None


def media_allowed(conn, user_id, media_id):
    """Получательница видит фото своего исходника."""
    return conn.execute('''SELECT 1 FROM exchange_assignments ea
JOIN event_participants p ON p.id=ea.recipient_event_participant_id AND p.user_id=%s AND p.registration_status='participating'
JOIN exchange_items ei ON ei.id=ea.exchange_item_id
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id
WHERE ea.active AND ea.exchange_group_key=%s AND svm.media_file_id=%s LIMIT 1''', (user_id, GROUP, media_id)).fetchone() is not None


def media_allowed_judge(conn, user_id, media_id):
    """Судья видит исходник рядом с работой своего пула."""
    return conn.execute('''SELECT 1 FROM exchange_items ei
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id AND svm.media_file_id=%s
JOIN exchange_assignments ea ON ea.exchange_item_id=ei.id AND ea.active
JOIN evaluation_target_members m ON m.event_participant_id=ea.recipient_event_participant_id
JOIN evaluation_targets t ON t.id=m.evaluation_target_id
JOIN evaluation_streams st ON st.id=t.evaluation_stream_id AND st.round_id=ea.round_id
JOIN evaluation_judge_assignments a ON a.evaluation_stream_id=st.id AND a.user_id=%s AND a.status='active'
WHERE ei.exchange_group_key=%s LIMIT 1''', (media_id, user_id, GROUP)).fetchone() is not None


def overview(conn, rnd, now):
    """Для организатора: настройка, сколько исходников и выдано, сколько ждут."""
    cfg = relay_of(rnd)
    if not cfg:
        return None
    items = conn.execute('SELECT count(*) AS n FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s',
                         (rnd['id'], GROUP)).fetchone()['n']
    given = conn.execute('''SELECT count(*) AS n FROM exchange_assignments WHERE round_id=%s AND exchange_group_key=%s AND active''',
                         (rnd['id'], GROUP)).fetchone()['n']
    waiting = len(_recipients(conn, rnd, cfg)) - given
    first_deadline = source_deadline(conn, rnd, cfg)
    second_opens, _ = league_dates(conn, rnd, cfg['to'])
    return {'from': cfg['from'], 'to': cfg['to'], 'sources': items, 'given': given, 'waiting': max(0, waiting),
            'started': bool(items), 'second_open': second_open(conn, rnd, now),
            'source_deadline': first_deadline.isoformat() if first_deadline else None,
            'second_opens_at': second_opens.isoformat() if second_opens else None}
