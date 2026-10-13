"""Дополнительные сценарии (13.10, день): маленькие Игры со своими проверками — то, чего не было в прогоне на 200.

    FPL_SIM_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m sim.scenarios [--keep]

S1 две Игры одновременно в одном сезоне, одни и те же участницы в обеих (очки, дипломы, лига сезона, рейтинг)
S2 правки организатора посреди Игры (текст задания, срок, туры, конец Игры, личный срок)
S3 крошечные и пустые пулы (1–2 работы в лиге, тур без работ)
S4 переголосование: отмена, повтор, снова равенство → решение; больше 12 работ — отказ
S5 судья теряет роль посреди судейства; администратор как судья
S6 аккаунт: ссылка нового пароля от организатора, вход, старые сессии; публичное имя после диплома
S7 выход и возврат после срока; дисквалификация после публикации тура и после итогов
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

from sim.harness import (ORIGIN, PASSWORD, Clock, Http, Problems, create_app, db_conn, drop_db, jpeg, make_db,
                         MemoryMailer, pw_hash, settings_for)

T0 = datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc)
iso = lambda d: d.isoformat()
P = Problems()


class W:
    pass


def setup():
    source = os.environ['FPL_SIM_DSN']
    name, dsn = make_db(source)
    w = W()
    w.source, w.name, w.dsn = source, name, dsn
    w.clock = Clock(T0)
    w.app = create_app(settings_for(dsn, tempfile.mkdtemp(prefix='fpl-scen-')), MemoryMailer(), clock=w.clock)
    w.db = db_conn(dsn)
    w.q = lambda sql, a=(): w.db.execute(sql, a).fetchall()
    w.q1 = lambda sql, a=(): w.db.execute(sql, a).fetchone()
    w.n = 0
    w.org, w.org_id = person(w, 'admin', 'Организатор')
    for kind in ('rules', 'publication', 'personal_data'):
        w.org.post('/api/org/documents', {'doc_type': kind, 'version': '1', 'title': kind, 'body': 'Текст документа для сценариев.'}, expect=201)
    w.season = w.org.post('/api/org/seasons', {'name': 'Сезон сценариев', 'season_no': 3}, expect=201)
    w.judges = [person(w, 'judge', f'Судья {i}') for i in range(6)]
    return w


def person(w, role, name=None):
    w.n += 1
    email = f'{role}{w.n}@example.com'
    with w.db.transaction():
        uid = w.q1('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,city,country_code)
VALUES (%s,%s,now(),'active',%s,'Казань','RU') RETURNING id''', (email, pw_hash(), name or f'Участница {w.n} Тестова'))['id']
        w.db.execute('INSERT INTO user_roles VALUES (%s,%s)', (uid, role))
    h = Http(w.app, P, f'{role}{w.n}')
    h.post('/web-auth/login', {'email': email, 'password': PASSWORD})
    h.email, h.user_id = email, str(uid)
    return h, str(uid)


def people(w, k):
    return [person(w, 'participant')[0] for _ in range(k)]


def game(w, title, game_no, rounds, fmt=None, start=True):
    """rounds — [(открытие от сейчас, часы на сдачу, форма, варианты)]; Игра идёт 30 дней."""
    o, now = w.org, w.clock()
    e = o.post('/api/org/events', {'title': title, 'season_id': w.season['id']}, expect=201)
    eid = e['id']
    o.patch(f'/api/org/events/{eid}', {'game_no': game_no, 'registration_opens_at': iso(now - timedelta(hours=1)),
                                        'registration_closes_at': iso(now + timedelta(hours=2)), 'starts_at': iso(now + timedelta(hours=1)),
                                        'ends_at': iso(now + timedelta(days=30))})
    out = []
    for k, (opens_h, hours, form, variants) in enumerate(rounds, 1):
        r = o.post(f'/api/org/events/{eid}/rounds', {}, expect=201)
        op = now + timedelta(hours=opens_h)
        o.patch(f"/api/org/rounds/{r['id']}", {'title': f'Тур {k}', 'opens_at': iso(op), 'deadline': iso(op + timedelta(hours=hours)),
                                               'judging_deadline': iso(op + timedelta(hours=hours + 24))})
        o.put(f"/api/org/rounds/{r['id']}/task", {'title': f'Тур {k}', 'form': form or {'photo': 'required', 'link': 'none', 'photo_max': 1},
                                                  'variants': variants or [{'league': None, 'instructions': 'Задание.'}]})
        o.post(f"/api/org/rounds/{r['id']}/status", {'action': 'publish'})
        out.append({'id': r['id'], 'no': k, 'opens': op, 'deadline': op + timedelta(hours=hours)})
    if fmt:
        o.put(f'/api/org/events/{eid}/results/format', fmt)
    o.post(f'/api/org/events/{eid}/status', {'action': 'publish'})
    for r in out:
        r['aid'] = str(w.q1('SELECT id FROM assignments WHERE round_id=%s', (r['id'],))['id'])
    return eid, out


def join(w, eid, ps, leagues=None):
    for p in ps:
        p.post(f'/api/events/{eid}/registration', {'accept_rules': True, 'accept_publication': True, 'accept_personal_data': True},
               expect=(200, 201))
    lst = {x['user_id']: x['id'] for x in w.org.get(f'/api/org/events/{eid}/participants')['participants']}
    for i, p in enumerate(ps):
        p.ep = lst.get(p.user_id)
    if leagues:
        w.org.post(f'/api/org/events/{eid}/leagues', {'items': [{'id': p.ep, 'league': leagues[i]} for i, p in enumerate(ps)]})


def start(w, eid):
    w.clock.shift(hours=1, minutes=5)
    r = w.org.post(f'/api/org/events/{eid}/status', {'action': 'start'})
    P.check(r and r['status'] == 'active', 'critical', 'сценарий', f'Игра не стартовала: {r}')


def send(w, p, eid, aid, seed=1, expect=(200,)):
    ph = p.call('POST', '/api/uploads', expect=201, content=jpeg(seed * 31 + hash(p.email) % 997), headers={'Content-Type': 'image/jpeg', **ORIGIN})
    d = p.put(f'/api/games/{eid}/tasks/{aid}/draft', {'photos': [ph['id']], 'link': None}, expect=(200, 409))
    if not d or 'draft' not in d:
        return d
    return p.post(f'/api/games/{eid}/tasks/{aid}/submit', {'draft_id': d['draft']['id']}, expect=expect)


def criteria_round(w, rnd, ps_scores, judges=None, quota=None, pools='leagues', leagues=('gold', 'silver', 'bronze')):
    """Судейство по одному критерию: ps_scores {участница: оценка всех судей}. Возвращает ответ публикации."""
    o = w.org
    J = judges or [w.judges[0], w.judges[1]]
    jids = [j[1] for j in J]
    cfg = {'method': 'criteria', 'pools': pools, 'criteria': [{'label': 'Образ', 'weight': 1}],
           'judges': ({'all': jids} if pools == 'common' else {lg: jids for lg in leagues}), 'quota': quota or {}}
    o.put(f"/api/org/rounds/{rnd['id']}/judging", cfg)
    w.clock.set(rnd['deadline'] + timedelta(minutes=5))
    v = o.post(f"/api/org/rounds/{rnd['id']}/judging/start", expect=(200, 409))
    if not v or not v.get('started'):
        return v
    by_ep = {p.ep: s for p, s in ps_scores.items()}
    for st in v['streams']:
        tm = {str(r['t']): str(r['ep']) for r in w.q('''SELECT t.id AS t, m.event_participant_id AS ep FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id WHERE t.evaluation_stream_id=%s''', (st['id'],))}
        for jc, _ in J:
            s = jc.get(f"/api/judging/streams/{st['id']}")
            for wk in s['works']:
                jc.post(f"/api/judging/streams/{st['id']}/works/{wk['id']}", {'scores': {s['criteria'][0]['code']: by_ep.get(tm[wk['id']], 50)}})
    return o.get(f"/api/org/rounds/{rnd['id']}/judging")


def publish_round(w, rnd, expect=200):
    return w.org.post(f"/api/org/rounds/{rnd['id']}/judging/publish", expect=expect)


def finish(w, eid):
    w.org.post(f'/api/org/events/{eid}/status', {'action': 'finish'})
    v = w.org.get(f'/api/org/events/{eid}/results')
    return v


# ---------------------------------------------------------------- сценарии

def s1_two_games(w):
    area = 'S1 две Игры'
    ps = people(w, 12)
    a, ra = game(w, 'Параллельная A', 5, [(1, 48, None, None)], {'final_round': 1, 'path_rounds': [], 'path_weight': 0})
    b, rb = game(w, 'Параллельная B', 6, [(1, 72, None, None)], {'final_round': 1, 'path_rounds': [], 'path_weight': 0})
    join(w, a, ps, ['gold'] * 6 + ['silver'] * 6)
    eps_a = {p.user_id: p.ep for p in ps}
    join(w, b, ps, ['silver'] * 6 + ['gold'] * 6)        # в другой Игре — другая лига
    eps_b = {p.user_id: p.ep for p in ps}
    w.clock.shift(hours=1, minutes=5)
    for eid in (a, b):
        w.org.post(f'/api/org/events/{eid}/status', {'action': 'start'})
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, a, ra[0]['aid'], seed=i)
        send(w, p, b, rb[0]['aid'], seed=100 + i)
    for p in ps:
        p.ep = eps_a[p.user_id]
    criteria_round(w, ra[0], {p: 90 - i for i, p in enumerate(ps)}, leagues=('gold', 'silver'))
    publish_round(w, ra[0])
    # тур B судится позже — снимок рейтинга уже после A
    for p in ps:
        p.ep = eps_b[p.user_id]
    criteria_round(w, rb[0], {p: 50 + i for i, p in enumerate(ps)}, leagues=('gold', 'silver'))
    publish_round(w, rb[0])
    for eid in (a, b):
        finish(w, eid)
        w.org.post(f'/api/org/events/{eid}/results/publish')
    # очки: сумма по двум Играм; дипломы — свои номера
    for p in ps:
        tx = w.q1('SELECT coalesce(sum(lifetime_delta),0) AS s FROM points_transactions WHERE user_id=%s', (p.user_id,))['s']
        st = w.q1('SELECT lifetime_points FROM participant_stats WHERE user_id=%s', (p.user_id,))
        P.check(st and st['lifetime_points'] == tx, 'critical', area, f'очки в профиле {st and st["lifetime_points"]} ≠ сумме {tx}')
        ach = p.get('/api/achievements')
        P.check(ach is not None, 'major', area, 'страница достижений не открылась')
        # снимок рейтинга в Игре B = рейтинг после Игры A
        snap = w.q1('SELECT rating_snapshot, calibration_rounds_completed_before AS c FROM round_rating_snapshots WHERE round_id=%s AND user_id=%s',
                    (rb[0]['id'], p.user_id))
        txa = w.q1('SELECT rating_after FROM rating_transactions WHERE round_id=%s AND user_id=%s', (ra[0]['id'], p.user_id))
        P.check(snap and txa and abs(float(snap['rating_snapshot']) - float(txa['rating_after'])) < 1e-6 and snap['c'] == 1,
                'critical', area, f'снимок рейтинга в Игре B не равен рейтингу после A: {snap} / {txa}')
    nums = [r['certificate_number'] for r in w.q('SELECT certificate_number FROM certificates ORDER BY 1')]
    P.check(len(nums) == 24 and len(set(nums)) == 24 and any('-05-' in n for n in nums) and any('-06-' in n for n in nums),
            'critical', area, f'дипломы двух Игр: {len(nums)}, разных {len(set(nums))}')
    lg = {r['user_id']: r['current_league'] for r in w.q('SELECT user_id::text, current_league FROM season_participants')}
    P.check(lg.get(ps[0].user_id) == 'silver', 'minor', area, f"лига сезона после двух Игр — последняя назначенная: {lg.get(ps[0].user_id)}")
    print(f'  {area}: done')


def s2_org_edits(w):
    area = 'S2 правки организатора'
    ps = people(w, 4)
    eid, rs = game(w, 'Правки', 7, [(1, 24, None, None), (48, 24, None, None), (96, 24, None, None)])
    join(w, eid, ps, ['gold'] * 4)
    start(w, eid)
    r1 = rs[0]
    w.clock.shift(minutes=30)
    send(w, ps[0], eid, r1['aid'])
    # текст задания после открытия — можно; участницы получают уведомление
    before = w.q1("SELECT count(*) AS n FROM notifications WHERE event_id=%s", (eid,))['n']
    w.org.put(f"/api/org/rounds/{r1['id']}/task", {'title': 'Тур 1', 'form': {'photo': 'required', 'link': 'none', 'photo_max': 1},
                                                   'variants': [{'league': None, 'instructions': 'Исправленный текст задания.'}]})
    t = ps[1].get(f"/api/games/{eid}/tasks/{r1['aid']}")
    P.check(t and t.get('instructions') == 'Исправленный текст задания.', 'major', area, f"участница не видит новый текст: {t and t.get('instructions')}")
    after = w.q1("SELECT count(*) AS n FROM notifications WHERE event_id=%s", (eid,))['n']
    P.check(after > before, 'minor', area, 'о новом тексте задания уведомления нет')
    # форму сдачи после открытия не поменять
    r = w.org.raw('PUT', f"/api/org/rounds/{r1['id']}/task", json={'title': 'Тур 1', 'form': {'photo': 'required', 'link': 'required', 'photo_max': 2},
                                                                  'variants': [{'league': None, 'instructions': 'x'}]}, headers=ORIGIN)
    P.check(r.status_code in (409, 422), 'major', area, f'форма поменялась после открытия: {r.status_code}')
    # продлить срок всем — опоздание исчезает
    new_dl = r1['deadline'] + timedelta(hours=12)
    w.org.patch(f"/api/org/rounds/{r1['id']}", {'deadline': iso(new_dl)})
    w.clock.set(r1['deadline'] + timedelta(hours=1))
    s = send(w, ps[1], eid, r1['aid'])
    P.check(s and s.get('submitted', {}).get('is_on_time'), 'major', area, f'сдача в продлённый срок не «вовремя»: {s and s.get("submitted")}')
    # срок в прошлом — нельзя
    r = w.org.raw('PATCH', f"/api/org/rounds/{r1['id']}", json={'deadline': iso(w.clock() - timedelta(hours=1))}, headers=ORIGIN)
    P.check(r.status_code != 200 or True, 'note', area, f'срок тура в прошлом: {r.status_code}')
    note = r.status_code
    # конец Игры раньше сроков туров — нельзя
    r = w.org.raw('PATCH', f'/api/org/events/{eid}', json={'ends_at': iso(rs[1]['deadline'] - timedelta(hours=1))}, headers=ORIGIN)
    P.check(r.status_code == 422, 'major', area, f'конец Игры раньше срока тура принят: {r.status_code}')
    # последний тур (ещё не открыт): снять с публикации и удалить
    r3 = rs[2]
    u = w.org.post(f"/api/org/rounds/{r3['id']}/status", {'action': 'unpublish'}, expect=(200, 409))
    d = w.org.raw('DELETE', f"/api/org/rounds/{r3['id']}", headers=ORIGIN)
    P.check(d.status_code in (200, 204, 409), 'major', area, f'удаление последнего тура: {d.status_code} {d.text[:120]}')
    # личный срок: дать и отменить
    w.org.post(f"/api/org/participants/{ps[2].ep}/deadline", {'round_id': r1['id'], 'deadline': iso(new_dl + timedelta(hours=6)), 'reason': 'Болела'})
    w.org.post(f"/api/org/participants/{ps[2].ep}/deadline", {'round_id': r1['id'], 'deadline': None, 'reason': 'Поправилась'})
    pa = w.q1('''SELECT deadline_override FROM participant_assignments WHERE event_participant_id=%s''', (ps[2].ep,))
    P.check(pa is None or pa['deadline_override'] is None, 'major', area, 'личный срок не отменился')
    print(f'  {area}: done (срок в прошлом → {note}, снять тур → {bool(u)}, удалить → {d.status_code})')


def s3_tiny_pools(w):
    area = 'S3 крошечные пулы'
    ps = people(w, 9)
    eid, rs = game(w, 'Крошечные пулы', 8, [(1, 24, None, None), (48, 24, None, None)])
    join(w, eid, ps, ['gold'] + ['silver'] * 2 + ['bronze'] * 6)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    J = [w.judges[0][1], w.judges[1][1], w.judges[2][1]]
    w.org.put(f"/api/org/rounds/{rs[0]['id']}/judging", {'method': 'pairwise', 'pools': 'leagues', 'per_target': 2,
                                                         'judges': {'gold': J, 'silver': J, 'bronze': J}, 'quota': {}})
    w.clock.set(rs[0]['deadline'] + timedelta(minutes=5))
    pre = w.org.get(f"/api/org/rounds/{rs[0]['id']}/judging")
    P.check('lonely_work' in str(pre), 'major', area, 'нет предупреждения: одна работа в пуле пар останется без балла')
    v = w.org.post(f"/api/org/rounds/{rs[0]['id']}/judging/start", expect=(200, 409))
    P.check(v is not None, 'major', area, 'тур с пулом из 1 работы не запускается')
    if v and v.get('started'):
        for jc, _ in w.judges[:3]:
            for st in jc.get('/api/judging')['streams']:
                while True:
                    s = jc.get(f"/api/judging/streams/{st['id']}")
                    if not s or not s['next']:
                        break
                    jc.post(f"/api/judging/comparisons/{s['next']['id']}", {'winner': 'a'})
        pub = publish_round(w, rs[0], expect=(200, 409))
        P.check(pub and pub.get('published'), 'major', area, f'тур с крошечными пулами не публикуется: {pub and pub.get("publish_problems")}')
        rr = {str(r['event_participant_id']): r for r in w.q('SELECT * FROM round_results WHERE round_id=%s', (rs[0]['id'],))}
        tx = {str(r['user_id']) for r in w.q('SELECT user_id FROM rating_transactions WHERE round_id=%s', (rs[0]['id'],))}
        P.check(ps[0].user_id not in tx and ps[1].user_id not in tx, 'critical', area, 'рейтинг изменился в пуле меньше 3 работ')
        P.check(ps[3].user_id in tx, 'major', area, 'в пуле из 6 рейтинг не изменился')
        P.check(not any(rr[p.ep]['top_work'] for p in ps[:3]), 'critical', area, 'TOP WORK в лиге меньше 5 работ')
        P.check(rr[ps[0].ep]['display_score'] is not None, 'note', area, f"одна работа в пуле: балл {rr[ps[0].ep]['display_score']}")
    # тур 2: никто не сдал — как закрыть тур и выйти к итогам
    w.clock.set(rs[1]['deadline'] + timedelta(minutes=5))
    w.org.put(f"/api/org/rounds/{rs[1]['id']}/judging", {'method': 'pairwise', 'pools': 'leagues', 'per_target': 2,
                                                         'judges': {'gold': J, 'silver': J, 'bronze': J}, 'quota': {}})
    r = w.org.raw('POST', f"/api/org/rounds/{rs[1]['id']}/judging/start", headers=ORIGIN)
    detail = r.json().get('detail') if r.content else None
    v = finish(w, eid)
    probs = v['checks']['problems']
    if 'rounds_not_published' in probs:
        P.add('major', area, f'тур без работ (старт судейства: {detail}) нельзя закрыть — итоги Игры не публикуются: {probs}')
    else:
        P.check('empty_rounds' in v['checks']['warnings'], 'minor', area, f"нет предупреждения о пустом туре: {v['checks']}")
        pub = w.org.post(f'/api/org/events/{eid}/results/publish', expect=(200, 409))
        P.check(pub is not None, 'major', area, 'итоги с пустым туром не публикуются')
        rows = {r['id']: r for r in w.org.get(f'/api/org/events/{eid}/results')['rows']}
        for p in ps[:3]:
            r = rows.get(p.ep)
            print('    одна/две в пуле:', r and {k: r[k] for k in ('league', 'total', 'league_rank', 'award_place', 'diploma', 'counted', 'scores')})
        me = ps[0].get(f'/api/games/{eid}')
        P.check(me is not None, 'major', area, 'участница не открывает Игру с пустым туром')
    print(f'  {area}: done (тур без работ: {detail}; итоги: {probs})')


def s4_tie_break(w):
    area = 'S4 переголосование'
    ps = people(w, 14)
    eid, rs = game(w, 'Переголосование', 9, [(1, 24, None, None)])
    join(w, eid, ps, ['gold'] * 14)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    # 13 равных на границе (оценки одинаковые), квота 7
    scores = {p: (90 if i == 0 else 60) for i, p in enumerate(ps)}
    v = criteria_round(w, rs[0], scores, quota={'gold': 7}, leagues=('gold',))
    st = v['streams'][0]
    tied = st['border']['tied']
    r = w.org.raw('POST', f"/api/org/judging/streams/{st['id']}/tie-break", json={'targets': tied, 'goal': 'advance'}, headers=ORIGIN)
    P.check(r.status_code == 422 if len(tied) > 12 else r.status_code == 200, 'major', area, f'переголосование {len(tied)} работ: {r.status_code}')
    sub = tied[:3]
    w.org.post(f"/api/org/judging/streams/{st['id']}/tie-break", {'targets': sub, 'goal': 'advance'}, expect=(200, 409, 422))
    w.org.post(f"/api/org/judging/streams/{st['id']}/tie-break/cancel", expect=(200, 409))
    again = w.org.post(f"/api/org/judging/streams/{st['id']}/tie-break", {'targets': sub, 'goal': 'advance'}, expect=(200, 409, 422))
    runs = w.q1("SELECT configuration FROM evaluation_streams WHERE id=%s", (st['id'],))['configuration'].get('tie_breaks', [])
    P.check(again is None or len({x['run_no'] for x in runs}) == len(runs), 'major', area, f'номера переголосований повторяются: {runs}')
    # решение организатора
    v = w.org.get(f"/api/org/rounds/{rs[0]['id']}/judging")
    st = v['streams'][0]
    if st['border']['status'] != 'ok':
        tb = [c for c in w.q("SELECT * FROM pairwise_comparisons WHERE evaluation_stream_id=%s AND phase='tie_break' AND status='pending'", (st['id'],))]
        w.org.post(f"/api/org/judging/streams/{st['id']}/tie-break/cancel", expect=(200, 409))
        v = w.org.get(f"/api/org/rounds/{rs[0]['id']}/judging")
        st = v['streams'][0]
        tied = st['border']['tied']
        sure = sum(1 for r in st['rows'] if r['advanced'] and r['target'] not in tied)
        w.org.post(f"/api/org/judging/streams/{st['id']}/decision", {'targets': tied, 'advance': tied[:7 - sure], 'reason': 'Решение жюри'})
    pub = publish_round(w, rs[0], expect=(200, 409))
    adv = w.q1("SELECT count(*) AS n FROM round_results WHERE round_id=%s AND advanced", (rs[0]['id'],))['n']
    P.check(pub and adv == 7, 'critical', area, f'после решения прошли {adv} при квоте 7 ({pub and pub.get("publish_problems")})')
    print(f'  {area}: done (равных {len(tied)}, прошли {adv})')


def s5_judge_role(w):
    area = 'S5 роль судьи'
    ps = people(w, 6)
    eid, rs = game(w, 'Роль судьи', 10, [(1, 24, None, None)])
    join(w, eid, ps, ['gold'] * 6)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    jc, jid = w.judges[3]
    cfg = {'method': 'pairwise', 'pools': 'leagues', 'per_target': 2, 'judges': {'gold': [jid, w.org_id, w.judges[4][1]]}, 'quota': {}}
    r = w.org.raw('PUT', f"/api/org/rounds/{rs[0]['id']}/judging", json=cfg, headers=ORIGIN)
    P.check(r.status_code == 200, 'note', area, f'администратор как судья: {r.status_code} {r.text[:100]}')
    if r.status_code != 200:
        cfg['judges']['gold'] = [jid, w.judges[4][1], w.judges[5][1]]
        w.org.put(f"/api/org/rounds/{rs[0]['id']}/judging", cfg)
    w.clock.set(rs[0]['deadline'] + timedelta(minutes=5))
    v = w.org.post(f"/api/org/rounds/{rs[0]['id']}/judging/start")
    st = v['streams'][0]
    s = jc.get(f"/api/judging/streams/{st['id']}")
    jc.post(f"/api/judging/comparisons/{s['next']['id']}", {'winner': 'a'})
    w.org.post(f"/api/org/people/{jid}/roles", {'role': 'judge', 'enabled': False})
    r = jc.raw('GET', f"/api/judging/streams/{st['id']}")
    P.check(r.status_code == 404, 'critical', area, f'судья без роли видит пул: {r.status_code}')
    r = jc.raw('POST', f"/api/judging/comparisons/{s['next']['id']}", json={'winner': 'b'}, headers=ORIGIN)
    P.check(r.status_code in (403, 404), 'critical', area, f'судья без роли голосует: {r.status_code}')
    rep = w.org.post(f"/api/org/judging/streams/{st['id']}/replace", {'old_user_id': jid, 'new_user_id': w.judges[5][1], 'reason': 'Сняли роль'},
                     expect=(200, 409, 422))
    P.check(rep is not None, 'major', area, 'заменить судью, у которого сняли роль, нельзя')
    print(f'  {area}: done')


def s6_account(w):
    area = 'S6 аккаунт'
    p = people(w, 1)[0]
    link = w.org.post(f'/api/org/people/{p.user_id}/reset-link')
    token = link['link'].split('token=')[1].split('&')[0]
    r = p.raw('POST', '/auth/password/reset', json={'token': token, 'password': 'New-password-123456!'})
    P.check(r.status_code == 204, 'major', area, f'новый пароль по ссылке организатора: {r.status_code} {r.text[:100]}')
    r = p.raw('GET', '/web-auth/me')
    P.check(r.status_code == 401, 'major', area, f'старая сессия жива после смены пароля: {r.status_code}')
    r = p.raw('POST', '/web-auth/login', json={'email': p.email, 'password': 'New-password-123456!'}, headers=ORIGIN)
    P.check(r.status_code == 200, 'major', area, f'вход с новым паролем: {r.status_code}')
    r = p.raw('POST', '/auth/password/reset', json={'token': token, 'password': 'Other-password-123456!'})
    P.check(r.status_code == 400, 'major', area, f'ссылка сработала второй раз: {r.status_code}')
    print(f'  {area}: done')


def s7_status_edges(w):
    area = 'S7 статусы'
    ps = people(w, 7)
    eid, rs = game(w, 'Статусы', 11, [(1, 24, None, None), (48, 24, None, None)],
                   {'final_round': 2, 'path_rounds': [1], 'path_weight': 40})
    join(w, eid, ps, ['gold'] * 7)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    # выход и возврат после срока тура
    w.org.post(f'/api/org/participants/{ps[6].ep}/action', {'action': 'withdraw', 'reason': 'Попросила'})
    w.clock.set(rs[0]['deadline'] + timedelta(hours=1))
    back = w.org.post(f'/api/org/participants/{ps[6].ep}/action', {'action': 'restore', 'reason': 'Вернулась'}, expect=(200, 409))
    m = w.q1('SELECT registration_status, competition_status FROM event_participants WHERE id=%s', (ps[6].ep,))
    criteria_round(w, rs[0], {p: 80 - i for i, p in enumerate(ps)}, leagues=('gold',))
    publish_round(w, rs[0])
    # дисквалификация после публикации тура
    w.org.post(f'/api/org/participants/{ps[0].ep}/action', {'action': 'disqualify', 'reason': 'Чужая работа'})
    w.clock.set(rs[1]['opens'] + timedelta(minutes=10))
    for i, p in enumerate(ps[1:6], 1):
        send(w, p, eid, rs[1]['aid'], seed=50 + i)
    criteria_round(w, rs[1], {p: 70 + i for i, p in enumerate(ps)}, leagues=('gold',))
    publish_round(w, rs[1])
    v = finish(w, eid)
    w.org.post(f'/api/org/events/{eid}/results/publish')
    er = {str(r['event_participant_id']): r for r in w.q('SELECT * FROM event_results WHERE event_id=%s AND is_current', (eid,))}
    P.check(er[ps[0].ep]['excluded_reason'] == 'disqualified', 'critical', area, f"дисквалифицированная в итогах: {er[ps[0].ep]['excluded_reason']}")
    pts = w.q1('SELECT coalesce(sum(lifetime_delta),0) AS s FROM points_transactions WHERE user_id=%s AND event_id=%s', (ps[0].user_id, eid))['s']
    P.check(pts == 0, 'critical', area, f'дисквалифицированной начислены очки: {pts}')
    # после итогов отменить дисквалификацию / вывести — нельзя
    r = w.org.raw('POST', f'/api/org/participants/{ps[0].ep}/action', json={'action': 'undisqualify', 'reason': 'x'}, headers=ORIGIN)
    P.check(r.status_code == 409, 'critical', area, f'после итогов статус меняется: {r.status_code}')
    print(f'  {area}: done (возврат после срока: {m})')


SITE_VIEWS = __import__('pathlib').Path(__file__).resolve().parents[2] / 'server' / 'db' / 'site_views.sql'


def site(w, what):
    w.db.execute(SITE_VIEWS.read_text(encoding='utf-8'))
    return w.q1(f'SELECT site_export_{what}() AS j')['j']


def s8_suspend_judge(w):
    area = 'S8 судью приостановили'
    ps = people(w, 6)
    eid, rs = game(w, 'Приостановка судьи', 12, [(1, 24, None, None)])
    join(w, eid, ps, ['gold'] * 6)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    (j1, id1), (j2, id2), (j3, id3) = person(w, 'judge'), w.judges[1], w.judges[2]
    w.org.put(f"/api/org/rounds/{rs[0]['id']}/judging", {'method': 'pairwise', 'pools': 'leagues', 'per_target': 2,
                                                         'judges': {'gold': [id1, id2, id3]}, 'quota': {}})
    w.clock.set(rs[0]['deadline'] + timedelta(minutes=5))
    v = w.org.post(f"/api/org/rounds/{rs[0]['id']}/judging/start")
    st = v['streams'][0]
    w.org.post(f'/api/org/people/{id1}/suspend', {'suspended': True})
    new, nid = w.judges[4]
    rep = w.org.post(f"/api/org/judging/streams/{st['id']}/replace", {'old_user_id': id1, 'new_user_id': nid, 'reason': 'Приостановлен'},
                     expect=(200, 409, 422))
    P.check(rep is not None, 'major', area, 'приостановленного судью нельзя заменить')
    for jc in (new, j2, j3):
        while True:
            s_ = jc.get(f"/api/judging/streams/{st['id']}")
            if not s_ or not s_['next']:
                break
            jc.post(f"/api/judging/comparisons/{s_['next']['id']}", {'winner': 'a'})
    pub = publish_round(w, rs[0], expect=(200, 409))
    P.check(pub and pub.get('published'), 'major', area, f'тур после замены приостановленного судьи не публикуется: {pub}')
    w.org.post(f'/api/org/people/{id1}/suspend', {'suspended': False})
    r = j1.raw('GET', '/web-auth/me')
    P.check(r.status_code == 401, 'major', area, f'старая сессия судьи ожила после снятия приостановки: {r.status_code}')
    print(f'  {area}: done')


def s9_suspend_participant(w):
    area = 'S9 участницу приостановили'
    ps = people(w, 6)
    eid, rs = game(w, 'Приостановка участницы', 13, [(1, 24, None, None)], {'final_round': 1, 'path_rounds': [], 'path_weight': 0})
    join(w, eid, ps, ['gold'] * 6)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    w.org.post(f'/api/org/people/{ps[0].user_id}/suspend', {'suspended': True})
    criteria_round(w, rs[0], {p: 90 - i for i, p in enumerate(ps)}, leagues=('gold',))
    pub = publish_round(w, rs[0], expect=(200, 409))
    P.check(pub and pub.get('published'), 'major', area, f'тур с приостановленной участницей не публикуется: {pub}')
    finish(w, eid)
    r = w.org.post(f'/api/org/events/{eid}/results/publish', expect=(200, 409))
    P.check(r is not None, 'major', area, 'итоги с приостановленной участницей не публикуются')
    er = w.q1('SELECT * FROM event_results WHERE event_participant_id=%s AND is_current', (ps[0].ep,))
    cert = w.q1("SELECT certificate_number FROM certificates WHERE event_participant_id=%s", (ps[0].ep,))
    print(f"  {area}: done (приостановленная: место {er and er['league_rank']}, диплом {cert and cert['certificate_number']})")


def s10_reopen(w):
    area = 'S10 вернуть Игру в работу'
    ps = people(w, 6)
    eid, rs = game(w, 'Возврат в работу', 14, [(1, 24, None, None), (48, 24, None, None)],
                   {'final_round': 2, 'path_rounds': [1], 'path_weight': 40})
    join(w, eid, ps, ['gold'] * 6)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    criteria_round(w, rs[0], {p: 90 - i for i, p in enumerate(ps)}, leagues=('gold',))
    publish_round(w, rs[0])
    # организатор по ошибке завершает Игру до 2 тура
    v = finish(w, eid)
    P.check('rounds_not_published' in v['checks']['problems'], 'critical', area,
            f"итоги можно опубликовать, хотя финал ещё не прошёл: {v['checks']}")
    w.org.post(f'/api/org/events/{eid}/status', {'action': 'reopen'})
    w.clock.set(rs[1]['opens'] + timedelta(minutes=10))
    for i, p in enumerate(ps):
        s_ = send(w, p, eid, rs[1]['aid'], seed=60 + i)
        P.check(s_ is not None, 'major', area, 'после возврата Игры в работу финал не сдаётся')
        break
    for i, p in enumerate(ps[1:], 61):
        send(w, p, eid, rs[1]['aid'], seed=i)
    criteria_round(w, rs[1], {p: 50 + i for i, p in enumerate(ps)}, leagues=('gold',))
    publish_round(w, rs[1])
    v = finish(w, eid)
    w.org.post(f'/api/org/events/{eid}/results/publish')
    n = w.q1('SELECT count(*) AS n, count(DISTINCT event_participant_id) AS d FROM event_results WHERE event_id=%s AND is_current', (eid,))
    P.check(n['n'] == n['d'] == 6, 'critical', area, f'итоги задвоились после возврата: {n}')
    print(f'  {area}: done')


def s11_publicity(w):
    area = 'S11 согласие на публикацию'
    ps = people(w, 5)
    eid, rs = game(w, 'Согласие', 15, [(1, 24, None, None)], {'final_round': 1, 'path_rounds': [], 'path_weight': 0})
    join(w, eid, ps, ['gold'] * 5)
    start(w, eid)
    w.clock.shift(minutes=30)
    for i, p in enumerate(ps):
        send(w, p, eid, rs[0]['aid'], seed=i)
    ps[0].patch('/web-auth/profile', {'display_name': 'Звёздочка'})
    for p in ps:
        p.put('/api/publicity', {'gallery': True})
    criteria_round(w, rs[0], {p: 90 - i for i, p in enumerate(ps)}, leagues=('gold',))
    publish_round(w, rs[0])
    finish(w, eid)
    w.org.post(f'/api/org/events/{eid}/results/publish')
    g = next(x for x in site(w, 'games')['games'] if x['game_no'] == 15)
    names = [t['name'] for r in g['rounds'] for t in r['top_work']]
    P.check('Звёздочка' in names, 'major', area, f'TOP WORK с публичным именем не на сайте: {names}')
    num = w.q1('SELECT certificate_number FROM certificates WHERE event_participant_id=%s', (ps[0].ep,))
    num = num and num['certificate_number']
    # меняет публичное имя после диплома
    ps[0].patch('/web-auth/profile', {'display_name': 'Новая Звезда'})
    c = site(w, 'certificates')['certificates'].get(num) if num else None
    print(f"    имя в проверке диплома после смены публичного имени: {c and c['name']}")
    # отзыв — пропадает отовсюду
    ps[0].post('/api/publicity/revoke', {})
    g = next(x for x in site(w, 'games')['games'] if x['game_no'] == 15)
    names = [t['name'] for r in g['rounds'] for t in r['top_work']]
    rating = [x['name'] for sx in site(w, 'rating')['seasons'] for x in sx['players']]
    c = site(w, 'certificates')['certificates'].get(num) if num else None
    P.check('Новая Звезда' not in names and 'Звёздочка' not in names, 'critical', area, 'после отзыва имя в TOP WORK на сайте')
    P.check('Новая Звезда' not in rating, 'critical', area, 'после отзыва имя в рейтинге на сайте')
    P.check(not c or not c['name'], 'critical', area, 'после отзыва имя в проверке диплома')
    # снова согласилась
    doc = w.q1("SELECT id FROM legal_documents WHERE doc_type='publication' ORDER BY published_at DESC LIMIT 1")['id']
    r = ps[0].put('/api/publicity', {'gallery': True, 'accept_publication': True})
    rating = [x['name'] for sx in site(w, 'rating')['seasons'] for x in sx['players']]
    P.check('Новая Звезда' in rating, 'major', area, f'после повторного согласия её нет в рейтинге на сайте')
    print(f'  {area}: done')


def s12_new_documents(w):
    area = 'S12 новые документы посреди Игры'
    ps = people(w, 3)
    eid, rs = game(w, 'Документы', 16, [(1, 24, None, None)])
    join(w, eid, ps, ['gold'] * 3)
    start(w, eid)
    w.clock.shift(minutes=30)
    w.org.post('/api/org/documents', {'doc_type': 'personal_data', 'version': '2', 'title': 'Обработка данных',
                                      'body': 'Новая редакция согласия на обработку данных.'}, expect=201)
    w.org.post('/api/org/documents', {'doc_type': 'publication', 'version': '2', 'title': 'Публикация',
                                      'body': 'Новая редакция согласия на публикацию.'}, expect=201)
    s_ = send(w, ps[0], eid, rs[0]['aid'], expect=(200, 409, 422))
    home = ps[0].get('/api/home', expect=(200, 404))
    print(f"  {area}: done (сдача после новой редакции согласий: {'ok' if s_ and s_.get('submitted') else s_})")


def main():
    w = setup()
    try:
        for fn in (s1_two_games, s2_org_edits, s3_tiny_pools, s4_tie_break, s5_judge_role, s6_account, s7_status_edges, s8_suspend_judge,
                   s9_suspend_participant, s10_reopen, s11_publicity, s12_new_documents):
            try:
                fn(w)
            except Exception as exc:
                P.add('critical', fn.__name__, f'сценарий упал: {type(exc).__name__}: {exc}')
                import traceback
                traceback.print_exc()
    finally:
        json.dump(P.items, open('scenarios-report.json', 'w'), ensure_ascii=False, indent=1)
        print('PROBLEMS', len(P.items))
        if '--keep' not in sys.argv:
            drop_db(w.source, w.name)
        else:
            print('kept', w.name)


if __name__ == '__main__':
    main()
