"""Ход Игры: пять туров со сдачей, судейством, границей прохода и публикацией; итоги Игры. Проверки — по ходу."""
import math
import random
import time
from collections import Counter, defaultdict
from datetime import timedelta

from sim import oracle as O
from sim.game200 import ORIGIN, VARIANT, game_me, iso, rng, submit

LEAGUES = ('gold', 'silver', 'bronze')


def pick(pool, k, tag, exclude=()):
    cand = [p for p in pool if not (p['scen'] & set(exclude)) and p.get('ep_id')]
    rng.shuffle(cand)
    for p in cand[:k]:
        p['scen'].add(tag)
    return cand[:k]


def assign_scenarios(w):
    base = [p for p in w.part if 'no_league' not in p['scen']]
    busy = ('late1', 'miss1', 'ext2', 'self_out', 'org_out_ret', 'withdraw', 'dq', 'league_change', 'left_in_judging',
            'replace_late')
    pick(base, 4, 'late1', busy)
    miss = pick(base, 4, 'miss1', busy)
    for p in miss[:2]:
        p['scen'].add('miss1_continue')
    pick(base, 15, 'replace', busy)
    pick(base, 2, 'replace_late', busy)
    pick(base, 3, 'ext2', busy)
    pick(base, 1, 'ext2_late', busy + ('ext2',))
    pick(base, 2, 'org_out_ret', busy)
    pick(base, 2, 'withdraw', busy)
    pick(base, 10, 'hidden', ())
    pick(base, 5, 'support', ())
    lc = [p for p in base if p['league'] in ('silver', 'bronze') and not (p['scen'] & set(busy))]
    rng.shuffle(lc)
    for p in lc[:2]:
        p['scen'].add('league_change')
    w.trace = defaultdict(list)


def note(w, p, text):
    w.trace[p['i']].append(text)


# ---------------------------------------------------------------- тур: сдача

def mode_of(w, p):
    row = w.q1('SELECT registration_status, competition_status, elimination_reason FROM event_participants WHERE id=%s', (p['ep_id'],))
    from kabinet.participation.rules import participation_mode
    return participation_mode(row)


def league_deadline(rnd, league):
    for v in rnd['variants']:
        if v.get('league') == league and v.get('deadline'):
            from datetime import datetime
            return datetime.fromisoformat(v['deadline'])
    return rnd['deadline']


def league_opens(rnd, league):
    for v in rnd['variants']:
        if v.get('league') == league and v.get('opens_at'):
            from datetime import datetime
            return datetime.fromisoformat(v['opens_at'])
    return rnd['opens']


def wants_to_submit(w, p, rnd):
    """Кто пытается сдать работу этого тура."""
    if not p.get('ep_id'):
        return False
    m = mode_of(w, p)
    if m in ('withdrawn', 'disqualified', 'eliminated', 'out_pending'):
        return False
    if 'miss1' in p['scen'] and (rnd['no'] == 1 or 'miss1_continue' not in p['scen']):
        return False
    return True


def phase_submit(w, rnd):
    no = rnd['no']
    org, eid = w.org, w.event
    # окно сдачи: разные лиги — разные даты; двигаем часы по событиям
    opens = {lg: league_opens(rnd, lg) for lg in LEAGUES}
    dls = {lg: league_deadline(rnd, lg) for lg in LEAGUES}
    first_open = min(opens.values())
    if VARIANT == 'B' and no == 4:
        # организатор открывает тур на день раньше даты
        w.clock.set(first_open - timedelta(days=1))
        r = org.post(f"/api/org/rounds/{rnd['id']}/status", {'action': 'open_now'})
        p0 = next(p for p in w.part if wants_to_submit(w, p, rnd))
        early = submit(w, p0, rnd, label='open_now')
        w.p.check(early is not None and 'detail' not in early, 'major', 'туры', f'после «Открыть сейчас» сдать нельзя: {early}')
        opens = {lg: first_open - timedelta(days=1) for lg in LEAGUES}
        first_open = first_open - timedelta(days=1)
    w.clock.set(first_open + timedelta(minutes=1))
    if VARIANT == 'B' and no == 3:
        # срок тура продлён всем после открытия: сдавшие в добавленные сутки — вовремя
        new_dl = rnd['deadline'] + timedelta(days=1)
        org.patch(f"/api/org/rounds/{rnd['id']}", {'deadline': iso(new_dl)})
        rnd['old_deadline'], rnd['deadline'] = rnd['deadline'], new_dl
        dls = {lg: league_deadline(rnd, lg) for lg in LEAGUES}
        ext = [p for p in w.part if wants_to_submit(w, p, rnd)][10:15]
        for p in ext:
            p['scen'].add('ext_all3')
    # до открытия своей лиги задание не видно / сдать нельзя
    if no == 2:
        bronze = next(p for p in w.part if p.get('league') == 'bronze' and wants_to_submit(w, p, rnd))
        r = submit(w, bronze, rnd, label='early')
        w.p.check(r is None or r.get('status') != 'sent', 'major', 'leagues',
                  f'Bronze сдала работу тура 2 до открытия задания своей лиги: {r}')
        t = bronze['client'].get(f"/api/games/{eid}/tasks/{rnd['assignment_id']}", expect=(200, 404, 409))
        note(w, bronze, f'тур 2 до открытия Bronze: {t and t.get("state")}')
    # новая редакция Правил посреди Игры (как будет с 1.8): сдать работу можно, только приняв её
    if no == 3:
        w.org.post('/api/org/documents', {'doc_type': 'rules', 'version': '1.9', 'title': 'Правила Игры',
                                          'body': 'Правила Игры. Новая редакция 1.9 для проверки.'}, expect=(200, 201))
    # организаторские сценарии в начале тура
    if no == 1:
        for p in [x for x in w.part if 'org_out_ret' in x['scen']]:
            org.post(f"/api/org/participants/{p['ep_id']}/action", {'action': 'outside', 'reason': 'Проверка: нарушение формы'})
            org.post(f"/api/org/participants/{p['ep_id']}/action", {'action': 'return', 'reason': 'Ошибка организатора'})
            w.p.check(mode_of(w, p) == 'in', 'major', 'org', f"после «вернуть» участница не в конкурсе: {mode_of(w, p)}")
    if no == 2:
        for p in [x for x in w.part if 'ext2' in x['scen'] or 'ext2_late' in x['scen']]:
            new = dls[p['league']] + timedelta(days=1)
            org.post(f"/api/org/participants/{p['ep_id']}/deadline", {'round_id': rnd['id'], 'deadline': iso(new), 'reason': 'Болела'})
            p['personal_dl'] = new
        wd = [x for x in w.part if 'withdraw' in x['scen']]
        for p in wd:
            org.post(f"/api/org/participants/{p['ep_id']}/action", {'action': 'withdraw', 'reason': 'Попросила выйти'})
        if wd:
            org.post(f"/api/org/participants/{wd[0]['ep_id']}/action", {'action': 'restore', 'reason': 'Передумала'})
            wd[0]['scen'].add('withdraw_restored')
    # опоздавшие: пропущенную работу можно сдать (для диплома), когда откроется следующий тур
    if no >= 2:
        prev = w.rounds[no - 2]
        for p in [x for x in w.part if ('late1' in x['scen'] and no == 2) or ('ext2_late' in x['scen'] and no == 3)]:
            w.clock.set(max(opens.values()) + timedelta(hours=1))
            m = mode_of(w, p)
            r = submit(w, p, prev, label='late_prev')
            ok = r is not None and (r.get('state') == 'sent_late' or r.get('work') or r.get('status'))
            note(w, p, f"тур {prev['no']} сдан после открытия тура {no} (режим {m}): {r and (r.get('state') or str(r)[:80])}")
            w.p.check(r is not None and 'detail' not in r, 'major', 'submit',
                      f"опоздавшая не смогла сдать пропущенную работу тура {prev['no']} после открытия тура {no}: {r}")
    # сдача: каждая лига в своё окно
    who = [p for p in w.part if wants_to_submit(w, p, rnd)]
    sent = 0
    for lg in sorted(LEAGUES, key=lambda x: opens[x]):
        w.clock.set(opens[lg] + timedelta(hours=2))
        group = [p for p in who if p.get('league', None) == lg or (p.get('league') is None and lg == 'bronze')]
        for p in group:
            if p.get('league') is None and no > 1:
                pass
            if 'late1' in p['scen'] and no == 1:
                continue
            if ('ext2' in p['scen'] or 'ext2_late' in p['scen']) and no == 2:
                continue
            if 'ext_all3' in p['scen'] and no == 3:
                continue
            r = submit(w, p, rnd)
            if r is None:
                note(w, p, f'тур {no}: сдача не прошла')
                continue
            sent += 1
            if 'replace' in p['scen'] and (p['i'] % 5) + 1 == no:
                r2 = submit(w, p, rnd, label='replace')
                w.p.check(r2 is not None, 'major', 'submit', f"замена работы не прошла: {p['email']}")
    # после сроков: опоздавшие
    last_dl = max(dls.values())
    for p in who:
        if 'late1' in p['scen'] and no == 1:
            w.clock.set(rnd['deadline'] + timedelta(hours=3))
            r = submit(w, p, rnd, label='late')
            w.p.check(r is not None and 'detail' in r, 'major', 'submit', f"до открытия следующего тура опоздавшая сдала работу: {r}")
            note(w, p, f'тур 1 после срока, до тура 2: {r and (r.get("state") or r.get("detail"))}')
        if 'ext2' in p['scen'] and no == 2:
            w.clock.set(dls[p['league']] + timedelta(hours=6))   # после срока лиги, до личного
            r = submit(w, p, rnd, label='ext')
            note(w, p, f'тур 2 сдан в личный срок: {r and r.get("state")}')
        if 'ext2_late' in p['scen'] and no == 2:
            w.clock.set(p['personal_dl'] + timedelta(hours=1))
            r = submit(w, p, rnd, label='ext_late')
            note(w, p, f'тур 2 сдан после личного срока: {r and r.get("state")}')
    for p in who:
        if 'ext_all3' in p['scen'] and no == 3:
            w.clock.set(rnd['old_deadline'] + timedelta(hours=6))
            r = submit(w, p, rnd, label='ext_all')
            w.p.check(r is not None and 'detail' not in r, 'major', 'сроки', f'сдача в продлённый всем срок не прошла: {r}')
    # замена после срока (сдала вовремя): какая версия пойдёт в конкурс
    for p in who:
        if 'replace_late' in p['scen'] and no == 3:
            w.clock.set(dls[p['league']] + timedelta(hours=2))
            r = submit(w, p, rnd, label='replace_after_deadline')
            p['replace_late_result'] = r
            note(w, p, f'тур 3: замена после срока → {r and (r.get("state") or r.get("detail"))}')
    end = max([last_dl] + [p['personal_dl'] for p in who if p.get('personal_dl') and no == 2])
    w.clock.set(end + timedelta(hours=2))
    return sent


# ---------------------------------------------------------------- тур: судейство

def frac_quota(n, frac):
    return max(1, min(n - 1, round(n * frac))) if n > 1 else None


def configure(w, rnd):
    no = rnd['no']
    J = [j['user_id'] for j in w.judges]
    counts = Counter()
    for p in w.part:
        if p.get('ep_id') and mode_of(w, p) == 'in':
            counts[p.get('league') or 'none'] += 1
    rows = w.q('''SELECT p.entry_league AS league, count(*) AS n FROM submissions s JOIN event_participants p ON p.id=s.event_participant_id
JOIN participant_assignments pa ON pa.id=s.participant_assignment_id WHERE pa.assignment_id=%s AND s.latest_version_id IS NOT NULL
AND p.competition_status='active' GROUP BY 1''', (rnd['assignment_id'],))
    works = {r['league']: r['n'] for r in rows}
    total = sum(works.values())
    if VARIANT == 'B':
        crit2 = [{'label': 'Образ', 'weight': 1}, {'label': 'Техника', 'weight': 2}]
        cfg = {1: {'method': 'criteria', 'pools': 'common', 'criteria': crit2, 'judges': {'all': J[:5]},
                   'quota': {'all': frac_quota(total, 0.85)}},
               2: {'method': 'pairwise', 'pools': 'common', 'per_target': 2, 'judges': {'all': J[5:9]},     # чётное число судей
                   'quota': {'all': frac_quota(total, 0.8)}},
               3: {'method': 'pairwise', 'pools': 'leagues', 'per_target': 4,
                   'judges': {'gold': J[9:12], 'silver': J[12:15], 'bronze': J[15:18]},
                   'quota': {lg: frac_quota(works.get(lg, 0), .75) for lg in LEAGUES}},
               4: {'method': 'criteria', 'pools': 'leagues', 'criteria': crit2,
                   'judges': {'gold': J[18:20], 'silver': J[20:22], 'bronze': J[22:25]},
                   'quota': {lg: frac_quota(works.get(lg, 0), .75) for lg in LEAGUES}},
               5: {'method': 'pairwise', 'pools': 'leagues', 'per_target': 6,
                   'judges': {'gold': J[0:3], 'silver': J[3:6], 'bronze': J[6:9]}, 'quota': {}}}[no]
    elif no == 1:
        cfg = {'method': 'pairwise', 'pools': 'common', 'per_target': 2, 'judges': {'all': J[:9]},
               'quota': {'all': frac_quota(total, 0.85)}}
    elif no == 2:
        cfg = {'method': 'pairwise', 'pools': 'leagues', 'per_target': 4,
               'judges': {'gold': J[0:3], 'silver': J[3:6], 'bronze': J[6:9]},
               'quota': {lg: frac_quota(works.get(lg, 0), f) for lg, f in (('gold', .8), ('silver', .75), ('bronze', .7))}}
    elif no == 3:
        cfg = {'method': 'criteria', 'pools': 'leagues',
               'criteria': [{'label': 'Идея', 'weight': 2}, {'label': 'Техника', 'weight': 3}, {'label': 'Чистота', 'weight': 1}],
               'judges': {'gold': J[9:11], 'silver': J[11:13], 'bronze': J[13:16]},
               'quota': {lg: frac_quota(works.get(lg, 0), .75) for lg in LEAGUES}}
    elif no == 4:
        cfg = {'method': 'pairwise', 'pools': 'leagues', 'per_target': 6,
               'judges': {'gold': J[16:19], 'silver': J[19:22], 'bronze': J[22:25]},
               'quota': {lg: min(works.get(lg, 0) - 1, 12) for lg in LEAGUES}}
    else:
        cfg = {'method': 'criteria', 'pools': 'leagues', 'criteria': [{'label': 'Образ', 'weight': 1}, {'label': 'Техника', 'weight': 1}],
               'judges': {'gold': J[0:3], 'silver': J[3:6], 'bronze': J[6:9]}, 'quota': {}}
    cfg['quota'] = {k: v for k, v in cfg['quota'].items() if v}
    rnd['cfg'] = cfg
    v = w.org.put(f"/api/org/rounds/{rnd['id']}/judging", cfg)
    return v


def target_people(w, stream_id):
    rows = w.q('''SELECT t.id AS target, m.event_participant_id AS ep FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id WHERE t.evaluation_stream_id=%s''', (stream_id,))
    by_ep = {p['ep_id']: p for p in w.part if p.get('ep_id')}
    return {str(r['target']): by_ep[str(r['ep'])] for r in rows}


def judge_client(w, user_id):
    return next(j for j in w.judges if j['user_id'] == str(user_id))


def vote_pairs(w, jd, stream_id, tmap, limit=None, phase=None):
    c = jd['client']
    n = 0
    while limit is None or n < limit:
        s = c.get(f'/api/judging/streams/{stream_id}')
        if not s or not s['next']:
            break
        nx = s['next']
        if phase and nx['phase'] != phase:
            break
        row = w.q1('SELECT target_a_id, target_b_id FROM pairwise_comparisons WHERE id=%s', (nx['id'],))
        a, b = tmap[str(row['target_a_id'])], tmap[str(row['target_b_id'])]
        pa = 1 / (1 + math.exp(-(a['skill'] - b['skill']) * 1.6 + jd['bias']))
        c.post(f"/api/judging/comparisons/{nx['id']}", {'winner': 'a' if rng.random() < pa else 'b'})
        n += 1
    return n


def criteria_score(p, jd, value=None):
    if value is not None:
        return value
    return int(max(1, min(100, round(60 + 14 * p['skill'] + rng.gauss(0, 6) + jd['bias'] * 10))))


def score_works(w, jd, stream_id, tmap, limit=None, forced=None):
    c = jd['client']
    s = c.get(f'/api/judging/streams/{stream_id}')
    n = 0
    for wk in s['works']:
        if wk['done']:
            continue
        if limit is not None and n >= limit:
            break
        p = tmap[wk['id']]
        val = (forced or {}).get(p['i'])
        c.post(f"/api/judging/streams/{stream_id}/works/{wk['id']}",
               {'scores': {cr['code']: criteria_score(p, jd, val) for cr in s['criteria']}})
        n += 1
    return n


def phase_judging(w, rnd, forced=None):
    no = rnd['no']
    org = w.org
    v = configure(w, rnd)
    if v and v.get('checks', {}).get('problems'):
        print('   start problems:', v['checks']['problems'])
    # 2 участницы без лиги: тур по лигам не стартует, пока организатор не назначит лигу
    if rnd['cfg']['pools'] == 'leagues' and not getattr(w, 'nolg_done', False):
        w.nolg_done = True
        r = org.post(f"/api/org/rounds/{rnd['id']}/judging/start", expect=(200, 409))
        nolg = [p for p in w.part if 'no_league' in p['scen'] and mode_of(w, p) == 'in']
        if nolg:
            w.p.check(r is None or not r.get('started'), 'major', 'judging', 'судейство по лигам стартовало с участницами без лиги')
            for p in nolg:
                p['league'] = 'bronze'
                org.post(f"/api/org/participants/{p['ep_id']}/league", {'league': 'bronze'})
            v = org.post(f"/api/org/rounds/{rnd['id']}/judging/start")
        else:
            v = r
    else:
        v = org.post(f"/api/org/rounds/{rnd['id']}/judging/start")
    if not v or not v.get('started'):
        w.p.add('critical', 'judging', f'судейство тура {no} не стартовало: {v and v.get("checks")}')
        return None
    streams = v['streams']
    print(f"   tour {no}: streams " + ', '.join(f"{s['league'] or 'all'}={s['works']}" for s in streams))
    # участница не может судить и не видит пулы
    anyp = next(p for p in w.part if p.get('client'))
    for st in streams:
        anyp['client'].get(f"/api/judging/streams/{st['id']}", expect=404, level='critical')
    # судья чужого пула
    for st in streams:
        tmap = target_people(w, st['id'])
        ids = (rnd['cfg']['judges'].get(st['league'] or 'all') or [])
        others = [j for j in w.judges if j['user_id'] not in ids]
        if others:
            others[0]['client'].get(f"/api/judging/streams/{st['id']}", expect=404, level='critical')
        # анонимность: в ответе судье нет имён и email
        jd = judge_client(w, ids[0])
        s = jd['client'].get(f"/api/judging/streams/{st['id']}")
        blob = str(s)
        leaked = [p['name'] for p in tmap.values() if p['name'] in blob or p['email'] in blob]
        w.p.check(not leaked, 'critical', 'judging', f'судья видит имена участниц: {leaked[:3]}')
        st['tmap'] = tmap
        st['judge_ids'] = ids
    # дисквалификация во время судейства 3 тура (одну потом отменяют)
    if no == 3:
        plan = {x for v in getattr(w, 'border_plan', {}).values() for x in v}
        cand = [p for p in w.part if p.get('ep_id') and mode_of(w, p) == 'in' and not (p['scen'] & {'replace_late', 'league_change'})
                and p['ep_id'] not in plan]
        rng.shuffle(cand)
        for k, p in enumerate(cand[:2]):
            p['scen'].add('dq')
            org.post(f"/api/org/participants/{p['ep_id']}/action", {'action': 'disqualify', 'reason': 'Работа не своя'})
        org.post(f"/api/org/participants/{cand[0]['ep_id']}/action", {'action': 'undisqualify', 'reason': 'Проверили — своя'})
        cand[0]['scen'].add('dq_undone')
    if no == 4:
        cand = [p for p in w.part if p.get('ep_id') and mode_of(w, p) == 'in' and p['league'] == 'gold']
        p = cand[0]
        p['scen'].add('left_in_judging')
        org.post(f"/api/org/participants/{p['ep_id']}/action", {'action': 'withdraw', 'reason': 'Ушла во время судейства'})
    # голосование
    for st in streams:
        tmap, ids = st['tmap'], st['judge_ids']
        for k, uid in enumerate(ids):
            jd = judge_client(w, uid)
            if st['method'] if 'method' in st else rnd['cfg']['method'] == 'pairwise':
                pass
            if rnd['cfg']['method'] == 'pairwise':
                limit = None
                if no == 4 and st['league'] == 'silver' and k == 2:
                    limit = 25            # судья не доделал — организатор закроет недосуженное
                if no == 2 and st['league'] == 'gold' and k == 0:
                    vote_pairs(w, jd, st['id'], tmap, limit=10)
                    # замена судьи посреди судейства
                    new = w.judges[24 - 0]
                    org.post(f"/api/org/judging/streams/{st['id']}/replace",
                             {'old_user_id': uid, 'new_user_id': new['user_id'], 'reason': 'Заболела'}, expect=(200, 409, 422))
                    st['replaced'] = (uid, new['user_id'])
                    jd['client'].get(f"/api/judging/streams/{st['id']}", expect=404, level='critical')
                    jd = new
                vote_pairs(w, jd, st['id'], tmap, limit=limit)
            else:
                if no == 3 and k == 0:
                    # неверные оценки
                    s = jd['client'].get(f"/api/judging/streams/{st['id']}")
                    wk = s['works'][0]
                    for bad in (0, 101, 55.5, -1):
                        jd['client'].post(f"/api/judging/streams/{st['id']}/works/{wk['id']}",
                                          {'scores': {cr['code']: bad for cr in s['criteria']}}, expect=422, level='major')
                    jd['client'].post(f"/api/judging/streams/{st['id']}/works/{wk['id']}",
                                      {'scores': {s['criteria'][0]['code']: 50}}, expect=(200, 422), level='minor')
                if VARIANT == 'B' and no == 4 and st['league'] == 'gold' and k == 0:
                    score_works(w, jd, st['id'], tmap, limit=5, forced=forced)
                    new = w.judges[10]
                    org.post(f"/api/org/judging/streams/{st['id']}/replace",
                             {'old_user_id': uid, 'new_user_id': new['user_id'], 'reason': 'Уехала'}, expect=(200, 409, 422))
                    st['replaced'] = (uid, new['user_id'])
                    jd = new
                score_works(w, jd, st['id'], tmap, forced=forced)
    # двойное нажатие: повторный голос по уже проголосованной паре
    st0 = next((s for s in streams if rnd['cfg']['method'] == 'pairwise'), None)
    if st0:
        row = w.q1("SELECT c.id, a.user_id FROM pairwise_comparisons c JOIN evaluation_judge_assignments a ON a.id=c.judge_assignment_id WHERE c.evaluation_stream_id=%s AND c.status='voted' LIMIT 1", (st0['id'],))
        if row:
            jd = judge_client(w, row['user_id'])
            r = jd['client'].raw('POST', f"/api/judging/comparisons/{row['id']}", json={'winner': 'a'}, headers=ORIGIN)
            w.p.check(r.status_code in (200, 409), 'major', 'judging', f'повторный голос: {r.status_code} {r.text[:200]}')
            after = w.q1('SELECT count(*) AS n FROM pairwise_comparisons WHERE id=%s', (row['id'],))
    if no == 4:
        st = next(s for s in streams if s['league'] == 'silver')
        org.post(f"/api/org/judging/streams/{st['id']}/close", {'reason': 'Судья не успела'})
    # граница прохода
    for attempt in range(4):
        v = org.get(f"/api/org/rounds/{rnd['id']}/judging")
        bad = [s for s in v['streams'] if s['border']['status'] != 'ok']
        if not bad:
            break
        for s in bad:
            b = s['border']
            tied = b['tied'] or b['unjudged']
            print(f"   border {s['league'] or 'all'}: {b['status']} tied={len(b['tied'])} unjudged={len(b.get('unjudged', []))} close={len(b.get('close') or [])}")
            tmap = next(x for x in streams if x['id'] == s['id'])['tmap']
            use_tb = attempt == 0 and 2 <= len(b['tied']) <= 12 and (no in (1, 4) or s['league'] in ('silver', 'bronze'))
            if use_tb:
                r = org.post(f"/api/org/judging/streams/{s['id']}/tie-break", {'targets': b['tied'], 'goal': 'advance'}, expect=(200, 409))
                if r:
                    ids = next(x for x in streams if x['id'] == s['id'])['judge_ids']
                    rep = next((x.get('replaced') for x in streams if x['id'] == s['id'] and x.get('replaced')), None)
                    for uid in ids:
                        if rep and uid == rep[0]:
                            uid = rep[1]
                        vote_pairs(w, judge_client(w, uid), s['id'], tmap, phase='tie_break')
                    continue
            # решение организатора: проходят сильнейшие по «настоящей силе» (как решило бы жюри)
            need = len([r for r in s['rows'] if r['advanced']]) if False else None
            stay = sorted(tied, key=lambda t: -tmap[t]['skill'])
            quota = s['quota']
            sure = sum(1 for r in s['rows'] if r.get('advanced') and r['target'] not in tied)
            k = max(0, (quota or 0) - sure)
            org.post(f"/api/org/judging/streams/{s['id']}/decision", {'targets': tied, 'advance': stay[:k],
                                                                      'reason': 'Решение жюри по границе'}, expect=(200, 409, 422))
    v = org.get(f"/api/org/rounds/{rnd['id']}/judging")
    if v.get('publish_problems'):
        print('   publish problems:', v['publish_problems'])
    rnd['streams'] = streams
    return v


def phase_publish(w, rnd):
    org = w.org
    pub = org.post(f"/api/org/rounds/{rnd['id']}/judging/publish", expect=(200, 409))
    if not pub or not pub.get('published'):
        w.p.add('critical', 'judging', f"тур {rnd['no']} не опубликован: {pub}")
        return False
    again = org.post(f"/api/org/rounds/{rnd['id']}/judging/publish", expect=(200, 409), level='minor')
    n = w.q1('SELECT count(*) AS n FROM round_results WHERE round_id=%s AND is_current', (rnd['id'],))['n']
    n2 = w.q1('SELECT count(DISTINCT event_participant_id) AS n FROM round_results WHERE round_id=%s AND is_current', (rnd['id'],))['n']
    w.p.check(n == n2, 'critical', 'judging', f'тур {rnd["no"]}: задвоились итоги после повторной публикации ({n} vs {n2})')
    # голос после публикации
    st = rnd['streams'][0]
    row = w.q1("SELECT c.id, a.user_id FROM pairwise_comparisons c JOIN evaluation_judge_assignments a ON a.judge_slot_id=c.judge_slot_id WHERE c.evaluation_stream_id=%s LIMIT 1", (st['id'],))
    if row:
        jd = judge_client(w, row['user_id'])
        r = jd['client'].raw('POST', f"/api/judging/comparisons/{row['id']}", json={'winner': 'b'}, headers=ORIGIN)
        w.p.check(r.status_code in (404, 409), 'critical', 'judging', f'голос после публикации принят: {r.status_code}')
    return True


def after_round(w, rnd):
    """Участницы смотрят итог тура; выбывшие решают — продолжать вне конкурса или нет."""
    eid = w.event
    for p in w.part:
        if not p.get('ep_id'):
            continue
        g = p['client'].get(f'/api/games/{eid}')
        if not g:
            continue
        r = next((x for x in g['rounds'] if x['round_no'] == rnd['no']), None)
        blob = str(r)
        w.p.check("'place'" not in blob or "'place': None" in blob, 'major', 'privacy', f"место в туре видно участнице: {r}")
        if g['me']['mode'] == 'out_pending':
            if p['i'] % 5 < 3:
                p['client'].post(f'/api/games/{eid}/outside')
                p['scen'].add(f'out_continue_{rnd["no"]}')
            else:
                p['scen'].add(f'out_stop_{rnd["no"]}')


def border_ties(w, rnd):
    """Тур 3 (критерии): оценки без шума — по силе, разные; на границе прохода — равные: Gold — двое (решает
    организатор), Silver — трое (переголосование), Bronze — двое (переголосование)."""
    forced = {}
    rows = w.q('''SELECT p.id AS ep, p.entry_league AS league FROM submissions s JOIN event_participants p ON p.id=s.event_participant_id
JOIN participant_assignments pa ON pa.id=s.participant_assignment_id WHERE pa.assignment_id=%s AND s.latest_version_id IS NOT NULL
AND p.competition_status='active' AND s.is_on_time''', (rnd['assignment_id'],))
    by_ep = {p['ep_id']: p for p in w.part if p.get('ep_id')}
    w.border_plan = {}
    for lg, size in (('gold', 2), ('silver', 3), ('bronze', 2)):
        mem = sorted([by_ep[str(r['ep'])] for r in rows if r['league'] == lg], key=lambda p: -p['skill'])
        q = frac_quota(len(mem), .75)
        for k, p in enumerate(mem):
            forced[p['i']] = 95 - k
        tied = mem[q - 1:q - 1 + size]
        for p in tied:
            forced[p['i']] = 95 - (q - 1)
        w.border_plan[lg] = [p['ep_id'] for p in tied]
    return forced


def run(w):
    from sim import extra as X
    assign_scenarios(w)
    X.before_game(w)
    for p in w.part:
        if 'hidden' in p['scen']:
            p['client'].post('/api/publicity/revoke', {}, expect=(200, 204, 422))
        if 'support' in p['scen']:
            p['client'].post('/api/support', {'subject': 'Не грузится фото', 'text': 'Помогите, пожалуйста, фото не грузится.'},
                             expect=(200, 201, 422))
    sup = w.org.get('/api/org/support')
    forced = None
    for rnd in w.rounds:
        t = time.perf_counter()
        if rnd['no'] == 2:
            for p in [x for x in w.part if 'league_change' in x['scen']]:
                new = {'silver': 'gold', 'bronze': 'silver'}[p['league']]
                w.org.post(f"/api/org/participants/{p['ep_id']}/league", {'league': new})
                note(w, p, f"лига {p['league']} → {new}")
                p['league'] = new
        sent = phase_submit(w, rnd)
        forced = None
        if rnd['no'] == (3 if VARIANT == 'A' else 4):
            forced = border_ties(w, rnd)
        if rnd['no'] == 5 and VARIANT == 'A':
            forced = O.engineer_final(w, rnd)
        v = phase_judging(w, rnd, forced=forced)
        if v is None:
            return
        ok = phase_publish(w, rnd)
        if not ok:
            return
        O.check_round(w, rnd)
        O.check_rating(w, rnd)
        after_round(w, rnd)
        print(f"tour {rnd['no']}: sent {sent}, {time.perf_counter() - t:.0f}s, problems so far {len(w.p.items)}"
              + (f", приняли новые Правила: {getattr(w, 'rules_accepted', 0)}" if rnd['no'] == 3 else ''), flush=True)
    finish(w)


def finish(w):
    org, eid = w.org, w.event
    w.clock.set(w.rounds[-1]['jdl'] + timedelta(days=1))
    pre = org.get(f'/api/org/events/{eid}/results')
    org.post(f'/api/org/events/{eid}/status', {'action': 'finish', 'early': True})
    v = org.get(f'/api/org/events/{eid}/results')
    w.results_view = v
    # равные на призовых — решение организатора
    for lg in LEAGUES:
        ties = {tuple(sorted(r['tie'])) for r in v.get('rows', []) if r.get('tie') and r.get('league') == lg}
        for t in ties:
            order = sorted(t, key=lambda x: -next(p['skill'] for p in w.part if p.get('ep_id') == x))
            org.post(f'/api/org/events/{eid}/results/tie', {'league': lg, 'order': order, 'reason': 'Жюри: лучше раскрыта тема'})
            w.tie_decided = getattr(w, 'tie_decided', []) + [(lg, order)]
    v = org.get(f'/api/org/events/{eid}/results')
    if 'diploma_without_league' in v['checks']['problems']:
        # организатор видит, у кого нет лиги, и указывает её (после завершения — можно, пока итоги не опубликованы)
        for r in v['rows']:
            if r.get('diploma') and not r.get('league'):
                org.post(f"/api/org/participants/{r['id']}/league", {'league': 'bronze'})
                next(p for p in w.part if p.get('ep_id') == r['id'])['league'] = 'bronze'
        v = org.get(f'/api/org/events/{eid}/results')
    w.p.check(not v['checks']['problems'], 'major', 'итоги', f"публикация итогов остановлена: {v['checks']['problems']}")
    pub = org.post(f'/api/org/events/{eid}/results/publish')
    again = org.post(f'/api/org/events/{eid}/results/publish', expect=(200, 409), level='minor')
    O.check_game(w)
    # что видит каждая участница на странице Игры — то же, что посчитано
    by_ep = {x['ep']: x for x in getattr(w, 'game_people', [])}
    seen_bad = []
    for p in w.part:
        x = by_ep.get(p.get('ep_id'))
        if not x or not p.get('client'):
            continue
        g = p['client'].get(f'/api/games/{eid}', expect=(200, 401))
        r = (g or {}).get('result')
        if r is None:
            seen_bad.append(f"{p['email']}: итога нет")
            continue
        if (r['award_place'], r['total'], bool(r['diploma']), r['points']) != (x['award'], x['total'], x['diploma'], x['pts']):
            seen_bad.append(f"{p['email']}: {r['award_place'], r['total'], bool(r['diploma']), r['points']} ≠ {x['award'], x['total'], x['diploma'], x['pts']}")
    w.p.check(not seen_bad, 'critical', 'итоги у участницы', f'{len(seen_bad)} расхождений: ' + '; '.join(seen_bad[:3]))
    # после итогов Игру не открыть
    org.post(f'/api/org/events/{eid}/status', {'action': 'reopen'}, expect=409, level='critical')
    for p in w.part[:30]:
        p['client'].get('/api/achievements')
        p['client'].get(f'/api/games/{eid}')
    from sim import extra as X
    X.security(w)
    X.site_export(w)
    X.mini_games(w)
