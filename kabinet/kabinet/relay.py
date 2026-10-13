"""Тур-эстафета: вторая лига работает по работам первой (решения Светланы 13.10; механика 3 и 4 тура Игры 01 из бота).

3 тур: Gold (Лига А) делает свою работу, после её срока каждой участнице Silver (Лига Б) выдаётся работа Gold как исходник —
повторить. 4 тур — зеркально: Silver делает, Gold усложняет. Настройка тура: rounds.settings.relay = {'from': лига, 'to': лига}.

Как раздаются исходники (решение 13.10, вечер: «не автоматически, а по ручной проверке»):
1. После срока первой лиги (с учётом личных продлений) кабинет готовит раздачу — черновик: каждой участнице второй лиги
   (и в конкурсе, и вне конкурса) — работа первой лиги. Участницы черновик не видят.
2. Организатор проверяет работы: неподходящую убирает из исходников (с причиной) — раздача пересобирается; может перераздать.
3. «Отправить исходники» — участницы получают исходники и уведомление; задание открывается им в их дату.
4. После отправки: кому исходника не хватило (пришла позже, перевели в эту лигу) — выдаётся одна из уже отправленных работ.
Исходники — только работы участниц в конкурсе, сданные в срок (версия, которая идёт судьям). Работ меньше, чем получательниц, —
одна работа достаётся нескольким, поровну; свою работу участница не получает. Отправленный исходник не меняется.
Автор не узнаёт, кому досталась её работа; получательница — чья она (без имён и ссылок).
"""
import random
from datetime import timedelta, timezone

from kabinet.participation import rules as R

GROUP = 'relay'
MSK = timezone(timedelta(hours=3))
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
    """Работы первой лиги для исходников: только участницы в конкурсе, работа сдана в конкурс в срок, есть фото."""
    return conn.execute('''SELECT p.id AS ep_id, s.competition_version_id AS version_id, v.submitted_at
FROM event_participants p
JOIN participant_assignments pa ON pa.event_participant_id=p.id AND pa.assignment_id=%s AND pa.active
JOIN submissions s ON s.participant_assignment_id=pa.id AND s.deleted_at IS NULL
JOIN submission_versions v ON v.id=s.competition_version_id
WHERE p.event_id=%s AND p.entry_league=%s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status='active') AND s.counts_for_competition
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


def released(rnd):
    return bool((((rnd or {}).get('settings') or {}).get('relay') or {}).get('released_at'))


def _round(conn, rnd):
    return conn.execute('SELECT * FROM rounds WHERE id=%s', (rnd['id'],)).fetchone()   # тур из базы, а не «глазами лиги»


def _items(conn, round_id):
    return conn.execute('''SELECT id, event_participant_id AS author FROM exchange_items
WHERE round_id=%s AND exchange_group_key=%s AND excluded_at IS NULL ORDER BY id''', (round_id, GROUP)).fetchall()


def ready(conn, rnd, now):
    """Первая лига закончила сдавать (с учётом личных продлений) — можно готовить раздачу."""
    cfg = relay_of(rnd)
    if not cfg or rnd['status'] == 'draft' or main_task(conn, rnd['id']) is None:
        return False
    deadline = source_deadline(conn, rnd, cfg)
    return deadline is not None and now > deadline


def _fill_pool(conn, rnd, cfg):
    """Набор исходников закрепляется при первой подготовке раздачи."""
    if conn.execute('SELECT 1 FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s LIMIT 1', (rnd['id'], GROUP)).fetchone():
        return
    a = main_task(conn, rnd['id'])
    works = _pool(conn, rnd, cfg, a['id'])
    for w in works:
        conn.execute('''INSERT INTO exchange_items(round_id,event_participant_id,assignment_id,exchange_group_key,item_type,
source_submission_version_id,submitted_at) VALUES (%s,%s,%s,%s,'media',%s,%s)
ON CONFLICT (round_id, exchange_group_key, source_submission_version_id) WHERE source_submission_version_id IS NOT NULL DO NOTHING''',
                     (rnd['id'], w['ep_id'], a['id'], GROUP, w['version_id'], w['submitted_at']))
    conn.execute("INSERT INTO audit_log(entity_type,entity_id,action,after_data) VALUES ('round',%s,'relay_pool_fixed',%s)",
                 (rnd['id'], _json({'from': cfg['from'], 'to': cfg['to'], 'works': len(works)})))


def _assign(conn, rnd, cfg, now, rng, only_ep=None):
    """Каждой получательнице без исходника — работа с наименьшим числом получательниц (при равенстве — случайная), не своя."""
    items = _items(conn, rnd['id'])
    if not items:
        return []
    author = {i['id']: i['author'] for i in items}
    counts = {i['id']: 0 for i in items}
    for r in conn.execute('''SELECT exchange_item_id, count(*) AS n FROM exchange_assignments
WHERE round_id=%s AND exchange_group_key=%s AND active GROUP BY exchange_item_id''', (rnd['id'], GROUP)):
        if r['exchange_item_id'] in counts:
            counts[r['exchange_item_id']] = r['n']
    have = {r['recipient_event_participant_id'] for r in conn.execute('''SELECT recipient_event_participant_id FROM exchange_assignments
WHERE round_id=%s AND exchange_group_key=%s AND active''', (rnd['id'], GROUP))}
    todo = [p for p in _recipients(conn, rnd, cfg, only_ep, lock=only_ep is None) if p['id'] not in have]
    rng.shuffle(todo)
    order = sorted(counts)
    out = []
    for p in todo:
        options = [i for i in order if author[i] != p['id']]
        if not options:
            continue
        low = min(counts[i] for i in options)
        pick = rng.choice([i for i in options if counts[i] == low])
        conn.execute('''INSERT INTO exchange_assignments(round_id,exchange_group_key,exchange_item_id,recipient_event_participant_id,source,assigned_at)
VALUES (%s,%s,%s,%s,'automatic',%s)''', (rnd['id'], GROUP, pick, p['id'], now))
        counts[pick] += 1
        out.append(p)
    return out


def _notify(conn, rnd, people):
    from kabinet.participation.game import notify
    a = main_task(conn, rnd['id'])
    cfg = relay_of(rnd)
    opens, _ = league_dates(conn, rnd, cfg['to'])
    for p in people:
        notify(conn, p['user_id'], 'task', f"relay:{rnd['id']}:{p['id']}",
               {'title': f"Тур {rnd['round_no']}: ваш исходник готов",
                'text': 'Задание и работа-исходник — в кабинете.' + (f" Задание откроется {opens.astimezone(MSK):%d.%m в %H:%M} МСК." if opens else ''),
                'route': 'task', 'event_id': str(rnd['event_id']), 'assignment_id': str(a['id'])}, rnd['event_id'], rnd['id'])


def prepare(conn, rnd, now, rng=None):
    """Черновик раздачи (до отправки): набор исходников и выдача всем получательницам. Возвращает число выданных."""
    rnd = _round(conn, rnd)
    cfg = relay_of(rnd)
    if not cfg or released(rnd) or not ready(conn, rnd, now):
        return 0
    _lock(conn, rnd['id'])
    _fill_pool(conn, rnd, cfg)
    return len(_assign(conn, rnd, cfg, now, rng or random.SystemRandom()))


def reshuffle(conn, rnd, now, rng=None):
    """Перераздать черновик заново (до отправки)."""
    rnd = _round(conn, rnd)
    cfg = relay_of(rnd)
    if not cfg or released(rnd):
        return 0
    _lock(conn, rnd['id'])
    conn.execute('DELETE FROM exchange_assignments WHERE round_id=%s AND exchange_group_key=%s', (rnd['id'], GROUP))
    if not ready(conn, rnd, now):
        return 0
    _fill_pool(conn, rnd, cfg)
    return len(_assign(conn, rnd, cfg, now, rng or random.SystemRandom()))


def exclude(conn, rnd, item_id, excluded, reason, actor_id, now, rng=None):
    """Убрать работу из исходников (или вернуть) до отправки — раздача пересобирается."""
    conn.execute('''UPDATE exchange_items SET excluded_at=%s, excluded_by=%s, excluded_reason=%s
WHERE id=%s AND round_id=%s AND exchange_group_key=%s''', (now if excluded else None, actor_id if excluded else None,
                                                          reason if excluded else None, item_id, rnd['id'], GROUP))
    return reshuffle(conn, rnd, now, rng)


def release(conn, rnd, actor_id, now, rng=None):
    """«Отправить исходники»: черновик становится раздачей, участницы получают уведомление."""
    rnd = _round(conn, rnd)
    cfg = relay_of(rnd)
    _lock(conn, rnd['id'])
    _fill_pool(conn, rnd, cfg)
    _assign(conn, rnd, cfg, now, rng or random.SystemRandom())
    settings = dict(rnd['settings'] or {})
    settings['relay'] = {**settings['relay'], 'released_at': now.isoformat(), 'released_by': str(actor_id)}
    conn.execute('UPDATE rounds SET settings=%s WHERE id=%s', (_json(settings), rnd['id']))
    people = conn.execute('''SELECT p.id, p.user_id FROM exchange_assignments ea JOIN event_participants p ON p.id=ea.recipient_event_participant_id
WHERE ea.round_id=%s AND ea.exchange_group_key=%s AND ea.active''', (rnd['id'], GROUP)).fetchall()
    rnd = _round(conn, rnd)
    _notify(conn, rnd, people)
    conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,after_data) VALUES (%s,'round',%s,'relay_released',%s)",
                 (actor_id, rnd['id'], _json({'given': len(people)})))
    return len(people)


def distribute(conn, rnd, now, only_ep=None, rng=None):
    """Сверка и открытие задания. До отправки: сверка готовит черновик (участница ничего не получает).
    После отправки: кому исходника не хватило — одна из уже отправленных работ, с уведомлением. Возвращает число выданных."""
    rnd = _round(conn, rnd)
    cfg = relay_of(rnd)
    if not cfg:
        return 0
    if not released(rnd):
        return prepare(conn, rnd, now, rng) if only_ep is None else 0
    if only_ep is not None and has_source(conn, rnd['id'], only_ep):
        return 0
    _lock(conn, rnd['id'])
    given = _assign(conn, rnd, cfg, now, rng or random.SystemRandom(), only_ep)
    _notify(conn, rnd, given)
    return len(given)


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
JOIN rounds r ON r.id=ea.round_id AND r.settings->'relay' ? 'released_at'
WHERE ea.round_id=%s AND ea.exchange_group_key=%s AND ea.active AND ea.recipient_event_participant_id = ANY(%s)
ORDER BY svm.sort_order''', (round_id, GROUP, list(ep_ids))):
        out.setdefault(r['ep_id'], []).append(r)
    return out


def has_source(conn, round_id, ep_id):
    """Отправленный исходник есть (черновик до отправки не считается)."""
    return conn.execute('''SELECT 1 FROM exchange_assignments ea JOIN rounds r ON r.id=ea.round_id AND r.settings->'relay' ? 'released_at'
WHERE ea.round_id=%s AND ea.exchange_group_key=%s AND ea.active AND ea.recipient_event_participant_id=%s''',
                        (round_id, GROUP, ep_id)).fetchone() is not None


def media_allowed(conn, user_id, media_id):
    """Получательница видит фото своего исходника."""
    return conn.execute('''SELECT 1 FROM exchange_assignments ea
JOIN event_participants p ON p.id=ea.recipient_event_participant_id AND p.user_id=%s AND p.registration_status='participating'
JOIN exchange_items ei ON ei.id=ea.exchange_item_id
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id
JOIN rounds r ON r.id=ea.round_id AND r.settings->'relay' ? 'released_at'
WHERE ea.active AND ea.exchange_group_key=%s AND svm.media_file_id=%s LIMIT 1''', (user_id, GROUP, media_id)).fetchone() is not None


def media_allowed_judge(conn, user_id, media_id):
    """Судья видит исходник рядом с работой своего пула."""
    return conn.execute('''SELECT 1 FROM exchange_items ei
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id AND svm.media_file_id=%s
JOIN exchange_assignments ea ON ea.exchange_item_id=ei.id AND ea.active
JOIN rounds r ON r.id=ea.round_id AND r.settings->'relay' ? 'released_at'
JOIN evaluation_target_members m ON m.event_participant_id=ea.recipient_event_participant_id
JOIN evaluation_targets t ON t.id=m.evaluation_target_id
JOIN evaluation_streams st ON st.id=t.evaluation_stream_id AND st.round_id=ea.round_id
JOIN evaluation_judge_assignments a ON a.evaluation_stream_id=st.id AND a.user_id=%s AND a.status='active'
WHERE ei.exchange_group_key=%s LIMIT 1''', (media_id, user_id, GROUP)).fetchone() is not None


def overview(conn, rnd, now):
    """Для организатора: настройка, состояние раздачи (черновик / отправлено), сколько выдано и ждут."""
    cfg = relay_of(rnd)
    if not cfg:
        return None
    items = conn.execute('''SELECT count(*) FILTER (WHERE excluded_at IS NULL) AS n, count(*) FILTER (WHERE excluded_at IS NOT NULL) AS x
FROM exchange_items WHERE round_id=%s AND exchange_group_key=%s''', (rnd['id'], GROUP)).fetchone()
    given = conn.execute('''SELECT count(*) AS n FROM exchange_assignments WHERE round_id=%s AND exchange_group_key=%s AND active''',
                         (rnd['id'], GROUP)).fetchone()['n']
    waiting = len(_recipients(conn, rnd, cfg)) - given
    first_deadline = source_deadline(conn, rnd, cfg)
    second_opens, _ = league_dates(conn, rnd, cfg['to'])
    rel = (((rnd.get('settings') or {}).get('relay')) or {}).get('released_at')
    return {'from': cfg['from'], 'to': cfg['to'], 'sources': items['n'], 'excluded': items['x'], 'given': given,
            'waiting': max(0, waiting), 'started': bool(items['n'] or items['x']), 'released': bool(rel), 'released_at': rel,
            'ready': ready(conn, rnd, now), 'second_open': second_open(conn, rnd, now),
            'source_deadline': first_deadline.isoformat() if first_deadline else None,
            'second_opens_at': second_opens.isoformat() if second_opens else None}


def detail(conn, rnd, root):
    """Раздача для проверки организатором: работы-исходники (фото, автор, сколько получательниц), кому что досталось."""
    from kabinet.participation.views import photo_view
    rows = conn.execute('''SELECT ei.id, ei.excluded_at, ei.excluded_reason, u.full_name, u.display_name,
  (SELECT count(*) FROM exchange_assignments ea WHERE ea.exchange_item_id=ei.id AND ea.active) AS n
FROM exchange_items ei JOIN event_participants p ON p.id=ei.event_participant_id JOIN users u ON u.id=p.user_id
WHERE ei.round_id=%s AND ei.exchange_group_key=%s ORDER BY u.full_name''', (rnd['id'], GROUP)).fetchall()
    photos = {}
    for m in conn.execute('''SELECT ei.id AS item, mf.* FROM exchange_items ei
JOIN submission_version_media svm ON svm.submission_version_id=ei.source_submission_version_id AND svm.field_key='photo'
JOIN media_files mf ON mf.id=svm.media_file_id WHERE ei.round_id=%s AND ei.exchange_group_key=%s ORDER BY svm.sort_order''',
                          (rnd['id'], GROUP)):
        photos.setdefault(m['item'], []).append(photo_view(m, root))
    given = conn.execute('''SELECT ea.exchange_item_id AS item, u.full_name, p.competition_status FROM exchange_assignments ea
JOIN event_participants p ON p.id=ea.recipient_event_participant_id JOIN users u ON u.id=p.user_id
WHERE ea.round_id=%s AND ea.exchange_group_key=%s AND ea.active ORDER BY u.full_name''', (rnd['id'], GROUP)).fetchall()
    to = {}
    for g in given:
        to.setdefault(g['item'], []).append({'name': g['full_name'], 'outside': g['competition_status'] == 'diploma_only'})
    return [{'id': str(r['id']), 'author': r['full_name'] or r['display_name'], 'photos': photos.get(r['id'], []),
             'recipients': to.get(r['id'], []), 'excluded': r['excluded_at'] is not None, 'excluded_reason': r['excluded_reason']}
            for r in rows]
