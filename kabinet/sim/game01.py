"""Игра 01 с 3 тура в кабинете (13.10, вечер) — сквозной прогон на выдуманных данных:

перенос таблицы туров 1–2 (100 участниц: Gold 51 = 40 в конкурсе + 11 вне, Silver 49 = 40 + 9) → заявки по общей ссылке
(90 из 100, ФИО в разном порядке и с опечатками) → организатор подтверждает → тур 3 — эстафета Gold → Silver
(исходники всем Silver, и вне конкурса) → судейство парами по лигам, проход 27 → тур 4 — эстафета Silver → Gold, проход 13
→ финал по критериям → итоги Игры (путь — туры 1–4 с перенесёнными баллами, финал) → сайт.

    FPL_SIM_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m sim.game01 [--keep]
"""
import json
import random
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

from sim.harness import (ORIGIN, PASSWORD, Clock, Http, Problems, create_app, db_conn, drop_db, jpeg, make_db, MemoryMailer,
                         pw_hash, settings_for)

MSK = timezone(timedelta(hours=3))
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=MSK)
iso = lambda d: d.isoformat()
P = Problems()
AREA = 'Игра 01 с 3 тура'
SURN = ['Иванова', 'Петрова', 'Сидорова', 'Кузнецова', 'Смирнова', 'Попова', 'Васильева', 'Соколова', 'Михайлова', 'Новикова',
        'Фёдорова', 'Морозова', 'Волкова', 'Алексеева', 'Лебедева', 'Семёнова', 'Егорова', 'Павлова', 'Козлова', 'Степанова']
NAMES = ['Анна', 'Мария', 'Елена', 'Ольга', 'Дарья', 'Софья', 'Юлия', 'Татьяна', 'Наталья', 'Ирина']
PATR = ['Петровна', 'Ивановна', 'Сергеевна', 'Андреевна', '']


def table(rnd):
    head = ('ID участника;Имя;Лига;Оценка тура 1 (исходная 40–100);Рейтинг после тура 1 (первоначальный);'
            'Рейтинг после тура 1 (пересчитанный, использован в туре 2);Оценка работы тура 2 (объявленная);Прошёл в тур 3;'
            'Рейтинг после тура 2;Изменение за тур 2;TOP WORK тура 2;Примечание')
    rows, people = [], []
    plan = [('А', 40, 8, 3), ('Б', 40, 5, 4)]
    n = 0
    for lg, adv, cut, none in plan:
        for k in range(adv + cut + none):
            n += 1
            cid = str(1035000000 + n)
            name = f'{SURN[n % 20]} {NAMES[(n // 20) % 10]} {PATR[n % 5]}'.strip()
            s1 = rnd.choice([40, 50, 60, 70, 75, 80, 90, 100])
            r1 = 350 + (s1 - 40) * 5 + rnd.randint(-10, 10)
            if k < adv + cut:
                s2 = round(rnd.uniform(30, 99) if k < adv else rnd.uniform(5, 30), 2)
                r2 = r1 + rnd.randint(-60, 110)
                row = f"{cid};{name};{lg};{s1};{r1};{r1}.;{s2:.2f};{'Да' if k < adv else 'Нет'};{r2}.;{r2 - r1:+d}.;{'Да' if k < 4 else 'Нет'};"
            else:
                row = f'{cid};{name};{lg};{s1};{r1};{r1}.;;Нет;;;Нет;Нет результата тура 2'
                r2 = None
            rows.append(row)
            people.append({'cid': cid, 'name': name, 'league': 'gold' if lg == 'А' else 'silver', 'in': k < adv, 'r2': r2, 'r1': r1})
    return '﻿' + head + '\n' + '\n'.join(rows) + '\n', people


def claim_name(p, i):
    sur, first = p['name'].split()[:2]
    variant = i % 4
    if variant == 0:
        return p['name']
    if variant == 1:
        return f'{first} {sur}'                       # «Имя Фамилия» — как в кабинете
    if variant == 2:
        return f'{sur} {first}'.replace('ё', 'е')     # без отчества, «е» вместо «ё»
    return f'{sur.upper()} {first.lower()}'           # регистр


class W:
    pass


def setup():
    import os
    source = os.environ['FPL_SIM_DSN']
    name, dsn = make_db(source)
    w = W()
    w.source, w.name = source, name
    w.clock = Clock(T0)
    w.media = tempfile.mkdtemp(prefix='fpl-g01-')
    w.app = create_app(settings_for(dsn, w.media, claim_limit=10000), MemoryMailer(), clock=w.clock)
    w.db = db_conn(dsn)
    from sim.harness import ROOT
    with w.db.transaction():
        w.db.execute((ROOT / 'server' / 'db' / 'site_views.sql').read_text(encoding='utf-8'))
    w.q = lambda s, a=(): w.db.execute(s, a).fetchall()
    w.q1 = lambda s, a=(): w.db.execute(s, a).fetchone()
    w.n = 0
    w.org, w.org_id = person(w, 'admin')
    for kind in ('rules', 'publication', 'personal_data'):
        w.org.post('/api/org/documents', {'doc_type': kind, 'version': '1.8' if kind == 'rules' else '1', 'title': kind,
                                          'body': 'Текст документа для прогона.'}, expect=201)
    w.judges = [person(w, 'judge') for _ in range(3)]
    return w


def person(w, role):
    w.n += 1
    email = f'{role}{w.n}@example.com'
    with w.db.transaction():
        uid = w.q1('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,city,country_code)
VALUES (%s,%s,now(),'active',%s,'Казань','RU') RETURNING id''', (email, pw_hash(), f'{role} {w.n}'))['id']
        w.db.execute('INSERT INTO user_roles VALUES (%s,%s)', (uid, role))
    h = Http(w.app, P, f'{role}{w.n}')
    h.post('/web-auth/login', {'email': email, 'password': PASSWORD})
    h.email = email
    return h, str(uid)


def send(w, h, eid, aid, seed):
    ph = h.call('POST', '/api/uploads', expect=201, content=jpeg(seed), headers={'Content-Type': 'image/jpeg', **ORIGIN})
    if not ph:
        return None
    d = h.put(f'/api/games/{eid}/tasks/{aid}/draft', {'photos': [ph['id']], 'link': 'https://vk.com/wall-1_' + str(seed)}, expect=(200, 409))
    if not d or 'draft' not in d:
        return d
    return h.post(f'/api/games/{eid}/tasks/{aid}/submit', {'draft_id': d['draft']['id']}, expect=(200, 409))


def setup_round(w, eid, no, first, second, opens, first_hours, gap_hours, second_hours, text):
    """Тур-эстафета: первая лига — opens…+first_hours, вторая — открытие через gap_hours после срока первой."""
    o = w.org
    rid = str(w.q1('SELECT id FROM rounds WHERE event_id=%s AND round_no=%s', (eid, no))['id'])
    f_dl = opens + timedelta(hours=first_hours)
    s_open = f_dl + timedelta(hours=gap_hours)
    s_dl = s_open + timedelta(hours=second_hours)
    o.patch(f'/api/org/rounds/{rid}', {'opens_at': iso(opens), 'deadline': iso(s_dl), 'judging_deadline': iso(s_dl + timedelta(days=2))})
    o.put(f'/api/org/rounds/{rid}/task', {'title': text, 'form': {'photo': 'required', 'link': 'required', 'photo_max': 1}, 'variants': [
        {'league': None, 'instructions': text},
        {'league': first, 'instructions': f'{text}: своя работа.', 'deadline': iso(f_dl)},
        {'league': second, 'instructions': f'{text}: повторите выданную работу.', 'opens_at': iso(s_open), 'deadline': iso(s_dl)}]})
    v = o.post(f'/api/org/rounds/{rid}/status', {'action': 'publish'})
    P.check(v and v['status'] == 'scheduled', 'critical', AREA, f'тур {no} не опубликован: {v and v["checks"]}')
    aid = str(w.q1('SELECT id FROM assignments WHERE round_id=%s', (rid,))['id'])
    return {'id': rid, 'aid': aid, 'first_dl': f_dl, 'second_open': s_open, 'deadline': s_dl}


def judge_pairs(w, rnd, quota, strength):
    o = w.org
    jids = [j[1] for j in w.judges]
    o.put(f"/api/org/rounds/{rnd['id']}/judging", {'method': 'pairwise', 'pools': 'leagues', 'per_target': 4,
                                                   'judges': {'gold': jids, 'silver': jids}, 'quota': {'gold': quota, 'silver': quota}})
    v = o.post(f"/api/org/rounds/{rnd['id']}/judging/start", expect=(200, 409))
    if not P.check(v and v.get('started'), 'critical', AREA, f"судейство тура не стартовало: {v}"):
        return None
    tm = {str(r['t']): str(r['u']) for r in w.q('''SELECT t.id AS t, p.user_id AS u FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id JOIN event_participants p ON p.id=m.event_participant_id
JOIN evaluation_streams s ON s.id=t.evaluation_stream_id WHERE s.round_id=%s''', (rnd['id'],))}
    seen_source = 0
    for jc, _ in w.judges:
        for st in jc.get('/api/judging')['streams']:
            if st['round_no'] != rnd['no']:
                continue
            while True:
                s = jc.get(f"/api/judging/streams/{st['id']}")
                if not s or not s['next']:
                    break
                c = w.q1('SELECT target_a_id, target_b_id FROM pairwise_comparisons WHERE id=%s', (s['next']['id'],))
                if s['next']['a'].get('source'):
                    seen_source += 1
                a, b = strength.get(tm[str(c['target_a_id'])], 0), strength.get(tm[str(c['target_b_id'])], 0)
                jc.post(f"/api/judging/comparisons/{s['next']['id']}", {'winner': 'a' if a >= b else 'b'})
    pre = o.get(f"/api/org/rounds/{rnd['id']}/judging")
    # граница прохода: равные — решает организатор
    for st in pre['streams']:
        b = st.get('border') or {}
        tied = list(b.get('tied') or []) + list(b.get('unjudged') or [])
        if tied:
            n_in = sum(1 for r in st['rows'] if r.get('advanced') and r['target'] not in tied)
            o.post(f"/api/org/judging/streams/{st['id']}/decision", {'targets': tied, 'advance': tied[: max(0, quota - n_in)],
                                                                      'reason': 'прогон: равные на границе'}, expect=(200,))
    pub = o.post(f"/api/org/rounds/{rnd['id']}/judging/publish", expect=(200, 409))
    P.check(pub and pub.get('published'), 'critical', AREA, f"итоги тура {rnd['no']} не публикуются: {pub and pub.get('publish_problems')}")
    return seen_source


STOP = '--stop3' in sys.argv     # для проверки экранов: остановиться в туре 3 (судейство запущено, голосов нет; 5 заявок ждут)


class Stop(Exception):
    pass


def main():
    w = setup()
    rnd = random.Random(13)
    try:
        csv_text, people = table(rnd)
        o = w.org
        p = o.post('/api/org/import/game01/preview', {'csv': csv_text})
        P.check(p and p['error_count'] == 0 and p['rows'] == 100, 'critical', AREA, f'предпросмотр: {p and (p["error_count"], p["errors"][:3])}')
        res = o.post('/api/org/import/game01/apply', {'csv': csv_text, 'sha256': p['sha256']})
        eid = res['event_id']
        P.check(res['leagues']['gold']['in_competition'] == 40 and res['leagues']['silver']['total'] == 49, 'critical', AREA, f'перенос: {res}')

        # --- заявки: 90 из 100
        by_cid = {x['cid']: x for x in people}
        hs = {}
        anon = Http(w.app, P, 'anon')
        for i, x in enumerate(people[:90]):
            r = anon.post('/api/public/claims', {'full_name': claim_name(x, i), 'email': f"p{x['cid']}@example.com", 'password': PASSWORD,
                                                 'country_code': 'RU', 'city': 'Москва', 'accept_rules': True, 'accept_publication': True,
                                                 'accept_personal_data': True, 'confirm_adult': True}, expect=201)
            x['claim'] = r and r['claim_no']
        lst = o.get('/api/org/claims')
        wrong, manual = 0, 0
        for c in lst['items'][5 if STOP else 0:]:
            x = next(v for v in people if v.get('claim') == c['no'])
            sug = c['suggestions']
            pick = next((s for s in sug if s['bot_id'] == x['cid']), None)
            if pick is None or sug[0]['bot_id'] != x['cid']:
                manual += 1                                       # организатор ищет по ID / фамилии
                found = o.get('/api/org/claims/people?q=' + x['cid'])['items']
                pick = found[0] if found else None
            if pick is None:
                wrong += 1
                continue
            o.post(f"/api/org/claims/{c['no']}/approve", {'user_id': pick['user_id']})
        P.check(wrong == 0, 'critical', AREA, f'не нашлись в списке: {wrong}')
        P.check(manual <= 5, 'major', AREA, f'подсказка не на первом месте у {manual} из 90 (одинаковые ФИО в выдуманных данных — норма)')
        print(f'  заявки: 90, подсказка не первая у {manual}')
        for x in people[:90]:
            h = Http(w.app, P, x['cid'])
            me = h.post('/web-auth/login', {'email': f"p{x['cid']}@example.com", 'password': PASSWORD}, expect=(200, 401) if STOP else 200)
            me = me if me and me.get('email') else None
            if me:
                hs[x['cid']] = h
                g = h.get(f'/api/games/{eid}')
                P.check(g and g['me']['league'] == x['league'] and (g['me']['mode'] == 'in') == x['in'], 'critical', AREA,
                        f"после входа не та лига/состояние: {x['cid']} {g and g['me']}")
        P.check(len(hs) == (85 if STOP else 90), 'critical', AREA, f'вошли {len(hs)} из 90')
        # итоги туров 1–2 видны в Игре
        g = next(iter(hs.values())).get(f'/api/games/{eid}')
        res12 = [r for r in (g or {}).get('rounds', []) if r.get('round_no') in (1, 2) and r.get('result')]
        P.check(len(res12) == 2, 'major', AREA, f"итоги туров 1–2 в Игре у участницы: {[(r.get('round_no'), bool(r.get('result'))) for r in (g or {}).get('rounds', [])]}")

        # --- тур 3: Gold → Silver
        r3 = setup_round(w, eid, 3, 'gold', 'silver', T0 + timedelta(hours=1), 72, 1, 72, 'Цветы Пандоры')
        r3['no'] = 3
        w.clock.set(T0 + timedelta(hours=2))
        gold_in = [x for x in people if x['league'] == 'gold' and x['cid'] in hs]
        for i, x in enumerate(gold_in):
            if i % 13 == 5:
                continue                                          # не сдала
            send(w, hs[x['cid']], eid, r3['aid'], seed=1000 + i)
        # Silver до своей даты — исходника нет, задание закрыто
        sil = [x for x in people if x['league'] == 'silver' and x['cid'] in hs]
        t = hs[sil[0]['cid']].get(f"/api/games/{eid}/tasks/{r3['aid']}")
        P.check(t and t['window']['reason'] == 'not_open' and not t.get('source'), 'critical', AREA, f"Silver видит задание раньше: {t and t['window']}")
        w.clock.set(r3['second_open'] + timedelta(minutes=10))
        # организатор проверяет раздачу и отправляет исходники
        d = o.get(f"/api/org/rounds/{r3['id']}/relay")
        P.check(d and d['overview']['ready'] and not d['overview']['released'], 'critical', AREA, f"раздача не готова к проверке: {d and d['overview']}")
        o.post(f"/api/org/rounds/{r3['id']}/relay/prepare")
        if '--stop-check' in sys.argv:
            print('STOP', json.dumps({'round3': r3['id'], 'org': w.org.email, 'at': w.clock().isoformat(), 'db': w.name, 'media': w.media,
                                      'silver': next(f"p{x['cid']}@example.com" for x in sil), 'event': eid, 'aid': r3['aid']}))
            raise Stop()
        d = o.post(f"/api/org/rounds/{r3['id']}/relay/release")
        P.check(d and d['overview']['released'], 'critical', AREA, 'исходники не отправлены')
        opened = 0
        for i, x in enumerate(sil):
            if i % 3 == 0:
                continue                                          # часть откроет позже — им раздаст сверка
            t = hs[x['cid']].get(f"/api/games/{eid}/tasks/{r3['aid']}")
            P.check(t and t.get('source') and t['source']['photos'], 'critical', AREA, f"Silver без исходника: {x['cid']} {t and t['window']}")
            opened += 1
        from kabinet import relay
        with w.db.transaction():
            rrow = w.q1('SELECT * FROM rounds WHERE id=%s', (r3['id'],))
            given = relay.distribute(w.db, rrow, w.clock())
        cnt = Counter(r['item'] for r in w.q('''SELECT exchange_item_id AS item FROM exchange_assignments WHERE round_id=%s AND active''', (r3['id'],)))
        recipients = w.q1('''SELECT count(*) AS n FROM event_participants WHERE event_id=%s AND entry_league='silver'
AND registration_status='participating' AND (competition_status IS NULL OR competition_status IN ('active','diploma_only'))''', (eid,))['n']
        P.check(sum(cnt.values()) == recipients, 'critical', AREA, f'исходники выданы {sum(cnt.values())} из {recipients} (сверка добавила {given})')
        P.check(max(cnt.values()) - min(cnt.values()) <= 1, 'major', AREA, f'исходники неравномерно: {sorted(cnt.values())}')
        out_sil = w.q1('''SELECT count(*) AS n FROM event_participants p JOIN exchange_assignments ea ON ea.recipient_event_participant_id=p.id
AND ea.round_id=%s WHERE p.event_id=%s AND p.entry_league='silver' AND p.competition_status='diploma_only' ''', (r3['id'], eid))['n']
        P.check(out_sil == 9, 'critical', AREA, f'Silver вне конкурса с исходником: {out_sil} из 9')
        print(f'  тур 3: открыли {opened}, сверка выдала {given}, исходников {len(cnt)}, на работу {min(cnt.values())}–{max(cnt.values())}')
        for i, x in enumerate(sil):
            if i % 11 == 7:
                continue
            send(w, hs[x['cid']], eid, r3['aid'], seed=2000 + i)
        w.clock.set(r3['deadline'] + timedelta(minutes=10))
        strength = {}
        for x in people:
            u = w.q1("SELECT user_id FROM external_identities WHERE provider='salebot_client' AND external_id=%s", (x['cid'],))
            x['uid'] = str(u['user_id'])
            strength[x['uid']] = rnd.random()
        if STOP:
            jids = [j[1] for j in w.judges]
            o.put(f"/api/org/rounds/{r3['id']}/judging", {'method': 'pairwise', 'pools': 'leagues', 'per_target': 4,
                                                          'judges': {'gold': jids, 'silver': jids}, 'quota': {'gold': 27, 'silver': 27}})
            o.post(f"/api/org/rounds/{r3['id']}/judging/start")
            sx = next(x for x in sil if x['cid'] in hs)
            print('STOP', json.dumps({'event': eid, 'round3': r3['id'], 'aid': r3['aid'], 'silver': f"p{sx['cid']}@example.com",
                                      'judge': w.judges[0][0].email, 'org': w.org.email, 'at': w.clock().isoformat(),
                                      'db': w.name, 'media': w.media}))
            raise Stop()
        seen = judge_pairs(w, r3, 27, strength)
        P.check(seen and seen > 0, 'critical', AREA, 'судьи не видели исходник рядом с работой Silver')
        # снимок рейтинга = рейтинг после тура 2 из таблицы
        bad = 0
        for x in people:
            s = w.q1('SELECT rating_snapshot FROM round_rating_snapshots WHERE round_id=%s AND user_id=%s', (r3['id'], x['uid']))
            if s and x['r2'] is not None and abs(float(s['rating_snapshot']) - x['r2']) > 0.01:
                bad += 1
        P.check(bad == 0, 'critical', AREA, f'снимок рейтинга тура 3 ≠ рейтингу после тура 2 у {bad}')

        # --- тур 4: Silver → Gold (Gold усложняет работу Silver)
        r4 = setup_round(w, eid, 4, 'silver', 'gold', w.clock() + timedelta(hours=1), 48, 1, 48, 'Усложнение')
        r4['no'] = 4
        w.clock.set(r4['first_dl'] - timedelta(hours=1))
        for i, x in enumerate(sil):
            send(w, hs[x['cid']], eid, r4['aid'], seed=3000 + i)
        w.clock.set(r4['second_open'] + timedelta(minutes=5))
        o.post(f"/api/org/rounds/{r4['id']}/relay/release")
        for i, x in enumerate(gold_in):
            t = hs[x['cid']].get(f"/api/games/{eid}/tasks/{r4['aid']}")
            if t and t['me']['mode'] in ('in', 'outside'):
                P.check(t.get('source'), 'critical', AREA, f"Gold без исходника в туре 4: {t['window']}")
                send(w, hs[x['cid']], eid, r4['aid'], seed=4000 + i)
        w.clock.set(r4['deadline'] + timedelta(minutes=10))
        judge_pairs(w, r4, 13, strength)

        # --- финал: критерии, общий пул
        rid5 = str(w.q1('SELECT id FROM rounds WHERE event_id=%s AND round_no=5', (eid,))['id'])
        op = w.clock() + timedelta(hours=1)
        o.patch(f'/api/org/rounds/{rid5}', {'opens_at': iso(op), 'deadline': iso(op + timedelta(hours=48)), 'judging_deadline': iso(op + timedelta(hours=96))})
        o.put(f'/api/org/rounds/{rid5}/task', {'title': 'Финал', 'form': {'photo': 'required', 'link': 'required', 'photo_max': 2},
                                               'variants': [{'league': None, 'instructions': 'Финальная работа.'}]})
        o.post(f'/api/org/rounds/{rid5}/status', {'action': 'publish'})
        aid5 = str(w.q1('SELECT id FROM assignments WHERE round_id=%s', (rid5,))['id'])
        w.clock.set(op + timedelta(hours=1))
        for i, x in enumerate(people):
            if x['cid'] in hs:
                g = hs[x['cid']].get(f'/api/games/{eid}')
                if g and g['me']['mode'] in ('in', 'outside'):
                    send(w, hs[x['cid']], eid, aid5, seed=5000 + i)
        w.clock.set(op + timedelta(hours=49))
        jids = [j[1] for j in w.judges]
        o.put(f'/api/org/rounds/{rid5}/judging', {'method': 'criteria', 'pools': 'leagues', 'criteria': [{'label': 'Образ', 'weight': 1}],
                                                  'judges': {'gold': jids, 'silver': jids}, 'quota': {}})
        v = o.post(f'/api/org/rounds/{rid5}/judging/start', expect=(200, 409))
        if P.check(v and v.get('started'), 'critical', AREA, f'финал не стартовал: {v}'):
            for jc, _ in w.judges:
                for st in jc.get('/api/judging')['streams']:
                    if st['round_no'] != 5:
                        continue
                    s = jc.get(f"/api/judging/streams/{st['id']}")
                    for wk in s['works']:
                        jc.post(f"/api/judging/streams/{st['id']}/works/{wk['id']}", {'scores': {s['criteria'][0]['code']: rnd.randint(40, 99)}})
            pub = o.post(f'/api/org/rounds/{rid5}/judging/publish', expect=(200, 409))
            P.check(pub and pub.get('published'), 'critical', AREA, f'финал не публикуется: {pub and pub.get("publish_problems")}')

        # --- итоги Игры
        w.clock.set(datetime(2026, 11, 11, 0, 30, tzinfo=MSK))
        o.post(f'/api/org/events/{eid}/status', {'action': 'finish'})
        rv = o.get(f'/api/org/events/{eid}/results')
        P.check(rv and not rv['checks']['problems'], 'critical', AREA, f"итоги Игры: {rv and rv['checks']}")
        pub = o.post(f'/api/org/events/{eid}/results/publish', expect=(200, 409))
        P.check(pub is not None, 'critical', AREA, 'итоги Игры не публикуются')
        rows = (o.get(f'/api/org/events/{eid}/results') or {}).get('rows') or []
        with_path = [r for r in rows if r.get('scores') and '1' in {str(k) for k in r['scores']}]
        P.check(with_path, 'critical', AREA, 'в итогах Игры нет перенесённых баллов тура 1')
        places = Counter((r['league'], r.get('award_place')) for r in rows if r.get('award_place'))
        P.check(places.get(('gold', 1)) == 1 and places.get(('silver', 1)) == 1, 'major', AREA, f'призёры: {places}')
        print(f"  итоги: строк {len(rows)}, призёры {dict(places)}")
        # сайт
        with w.db.transaction():
            games = w.q1('SELECT site_export_games() AS j')['j']
            rating = w.q1('SELECT site_export_rating() AS j')['j']
        g01 = next((g for g in games['games'] if g.get('title') == 'Игра 01'), None)
        P.check(g01 and all(r['published'] for r in g01['rounds']), 'major', AREA, f'сайт: туры Игры 01 {g01 and [r["published"] for r in g01["rounds"]]}')
        P.check(rating['seasons'] and rating['seasons'][0]['players'], 'major', AREA, 'сайт: рейтинг сезона пуст после Игры')
        # участница: итоги и достижения
        h = hs[people[0]['cid']]
        P.check(h.get(f'/api/games/{eid}') is not None and h.get('/api/achievements') is not None, 'major', AREA, 'страницы участницы после итогов')
    except Stop:
        pass
    finally:
        json.dump(P.items, open('game01-report.json', 'w'), ensure_ascii=False, indent=1)
        print('PROBLEMS', len(P.items))
        if '--keep' not in sys.argv:
            drop_db(w.source, w.name)
        else:
            print('kept', w.name)


if __name__ == '__main__':
    main()
