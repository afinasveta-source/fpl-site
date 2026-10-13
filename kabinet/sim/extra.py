"""Права, приватность, выгрузка на сайт и маленькие Игры с полностью заданными оценками (равенства, номера)."""
import json
from datetime import timedelta
from pathlib import Path

from sim.harness import ORIGIN, Http
from sim.game200 import iso
from sim import oracle as O

SITE_VIEWS = Path(__file__).resolve().parents[2] / 'server' / 'db' / 'site_views.sql'


def before_game(w):
    """Публичные имена у 40 участниц (у остальных — пусто, как по умолчанию)."""
    for p in w.part[:40]:
        first, last = p['name'].split(' ')[:2]
        p['client'].patch('/web-auth/profile', {'display_name': f'{first} {last[0]}.'})
        p['public'] = f'{first} {last[0]}.'


def security(w):
    P = w.p
    eid = w.event
    a, b = [p for p in w.part if p.get('ep_id')][:2]
    # участница → кабинет организатора
    for url in ('/api/org/home', f'/api/org/events/{eid}/participants', f'/api/org/events/{eid}/results', '/api/org/people'):
        r = a['client'].raw('GET', url)
        P.check(r.status_code in (401, 403, 404), 'critical', 'права', f'участница открыла {url}: {r.status_code}')
    # чужое фото
    mid = w.q1('SELECT id FROM media_files WHERE uploaded_by=%s LIMIT 1', (b['user_id'],))['id']
    r = a['client'].raw('GET', f'/api/media/{mid}?size=view')
    P.check(r.status_code == 404, 'critical', 'права', f'участница видит чужое фото: {r.status_code}')
    r = w.org.raw('GET', f'/api/media/{mid}?size=view')
    P.check(r.status_code == 200, 'major', 'права', f'организатор не видит фото работы: {r.status_code}')
    # судья не из пула работы — не видит
    stranger = w.judges[-1]
    rows = w.q('''SELECT svm.media_file_id FROM submission_version_media svm JOIN evaluation_target_members m ON m.submission_version_id=svm.submission_version_id
JOIN evaluation_targets t ON t.id=m.evaluation_target_id JOIN evaluation_judge_assignments ja ON ja.evaluation_stream_id=t.evaluation_stream_id
GROUP BY 1 HAVING bool_and(ja.user_id<>%s) LIMIT 1''', (stranger['user_id'],))
    if rows:
        r = stranger['client'].raw('GET', f"/api/media/{rows[0]['media_file_id']}?size=view")
        P.check(r.status_code == 404, 'critical', 'права', f'судья видит фото чужого пула: {r.status_code}')
    # запрос без Origin (с чужого сайта)
    r = a['client'].c.post('/api/support', json={'subject': 'x', 'text': 'Подделка запроса с чужого сайта'},
                           headers={'Origin': 'https://evil.example'})
    P.check(r.status_code in (403, 400), 'critical', 'права', f'запись с чужого сайта принята: {r.status_code}')
    # участница не видит баллы и итоги других
    g = a['client'].get(f'/api/games/{eid}')
    blob = json.dumps(g, ensure_ascii=False)
    P.check(b['name'] not in blob and b['email'] not in blob, 'critical', 'приватность', 'на странице Игры видно другую участницу')
    # приостановленный аккаунт
    c = [p for p in w.part if p.get('ep_id')][5]
    w.org.post(f"/api/org/people/{c['user_id']}/suspend", {'suspended': True})
    r = c['client'].raw('GET', f'/api/games/{eid}')
    P.check(r.status_code in (401, 403), 'critical', 'права', f'приостановленная участница работает: {r.status_code}')
    r = c['client'].raw('POST', '/web-auth/login', json={'email': c['email'], 'password': 'Sim-test-password-123!'}, headers=ORIGIN)
    P.check(r.status_code in (401, 403), 'critical', 'права', f'приостановленная входит: {r.status_code}')
    w.org.post(f"/api/org/people/{c['user_id']}/suspend", {'suspended': False})
    c['client'].post('/web-auth/login', {'email': c['email'], 'password': 'Sim-test-password-123!'})   # сессии закрыты — войти снова
    # уведомления: у каждой участницы Игры есть уведомление об итогах
    no_note = w.q('''SELECT count(*) AS n FROM event_participants p WHERE p.event_id=%s AND NOT EXISTS (
SELECT 1 FROM notifications n WHERE n.user_id=p.user_id AND n.event_id=%s AND n.notification_type ILIKE '%%result%%')''', (eid, eid))[0]['n']
    types = w.q('SELECT notification_type, count(*) AS n FROM notifications GROUP BY 1 ORDER BY 2 DESC')
    print('   notifications:', {t['notification_type']: t['n'] for t in types})
    P.check(no_note == 0, 'major', 'уведомления', f'{no_note} участниц без уведомления об итогах Игры')


def site_export(w):
    """Выгрузка на сайт: те же функции, что на сервере (site_views.sql)."""
    P = w.p
    w.db.execute(SITE_VIEWS.read_text(encoding='utf-8'))
    games = w.q1('SELECT site_export_games() AS j')['j']
    certs = w.q1('SELECT site_export_certificates() AS j')['j']['certificates']
    rating = w.q1('SELECT site_export_rating() AS j')['j']
    blob = json.dumps(games, ensure_ascii=False) + json.dumps(certs, ensure_ascii=False)
    for p in w.part:
        P.check(p['email'] not in blob, 'critical', 'сайт', f"email участницы в выгрузке: {p['email']}")
        if 'hidden' in p['scen'] and p.get('public'):
            P.check(p['public'] not in blob, 'critical', 'сайт', f"имя скрывшей себя участницы на сайте: {p['public']}")
        full = p['name']
        P.check(full not in blob, 'major', 'сайт', f'полное имя в выгрузке: {full}')
    g = next(x for x in games['games'] if x['game_no'] == 2)
    named = sum(len(r['top_work']) for r in g['rounds'])
    total = sum(r['top_work_count'] for r in g['rounds'])
    print(f'   site: TOP WORK {total}, с именем {named}; дипломов {len(certs)}, с именем {sum(1 for c in certs.values() if c["name"])}; '
          f'рейтинг: сезонов {len(rating["seasons"])}, участниц {sum(len(s["players"]) for s in rating["seasons"])}')
    w.site = {'top_work': total, 'top_work_named': named, 'certs': len(certs),
              'certs_named': sum(1 for c in certs.values() if c['name']),
              'rating_players': sum(len(s['players']) for s in rating['seasons'])}
    # отзыв согласия после выдачи диплома: имя должно уйти и из проверки диплома
    with_cert = w.q('''SELECT p.user_id, c.certificate_number FROM certificates c JOIN event_participants p ON p.id=c.event_participant_id
JOIN users u ON u.id=p.user_id WHERE u.display_name IS NOT NULL LIMIT 1''')
    if with_cert:
        uid, num = str(with_cert[0]['user_id']), with_cert[0]['certificate_number']
        person = next(p for p in w.part if p.get('user_id') == uid)
        person['client'].post('/api/publicity/revoke', {}, expect=(200, 204))
        after = w.q1('SELECT site_export_certificates() AS j')['j']['certificates'].get(num)
        P.check(after is None or not after['name'], 'major', 'сайт',
                f'после отзыва согласия на публикацию имя осталось в проверке диплома {num}: {after and after["name"]}')


# ---------------------------------------------------------------- маленькие Игры: оценки заданы полностью

def mini_game(w, title, game_no, rounds, fmt, people, scores, tie_league=None, set_game_no_late=False):
    """rounds — число туров (все по критериям, проход — все); scores[i участницы][номер тура] — оценка всех судей."""
    org = w.org
    base = w.clock()
    e = org.post('/api/org/events', {'title': title, 'season_id': w.season['id']}, expect=201)
    eid = e['id']
    patch = {'registration_opens_at': iso(base - timedelta(hours=1)), 'registration_closes_at': iso(base + timedelta(hours=10)),
             'starts_at': iso(base + timedelta(hours=11)), 'ends_at': iso(base + timedelta(days=10 * rounds + 5))}
    if not set_game_no_late:
        patch['game_no'] = game_no
    org.patch(f'/api/org/events/{eid}', patch)
    rids = []
    for k in range(rounds):
        r = org.post(f'/api/org/events/{eid}/rounds', {}, expect=201)
        op = base + timedelta(hours=12, days=10 * k)
        org.patch(f"/api/org/rounds/{r['id']}", {'opens_at': iso(op), 'deadline': iso(op + timedelta(days=3)),
                                                 'judging_deadline': iso(op + timedelta(days=5))})
        org.put(f"/api/org/rounds/{r['id']}/task", {'title': f'Тур {k + 1}', 'form': {'photo': 'required', 'link': 'none', 'photo_max': 1},
                                                    'variants': [{'league': None, 'instructions': 'Задание.'}]})
        org.post(f"/api/org/rounds/{r['id']}/status", {'action': 'publish'})
        rids.append((r['id'], op))
    org.put(f'/api/org/events/{eid}/results/format', fmt)
    org.post(f'/api/org/events/{eid}/status', {'action': 'publish'})
    eps = {}
    for p in people:
        p['client'].post(f'/api/events/{eid}/registration', {'accept_rules': True, 'confirm_adult': True, 'accept_publication': True,
                                                            'accept_personal_data': True}, expect=(200, 201))
    lst = org.get(f'/api/org/events/{eid}/participants')['participants']
    by_user = {x['user_id']: x['id'] for x in lst}
    for p in people:
        eps[p['i']] = by_user[p['user_id']]
        org.post(f"/api/org/participants/{eps[p['i']]}/league", {'league': p['mini_league']})
    w.clock.set(base + timedelta(hours=11, minutes=5))
    org.post(f'/api/org/events/{eid}/status', {'action': 'start'})
    from sim.game200 import upload_photos
    J = w.judges[:3]
    for k, (rid, op) in enumerate(rids):
        w.clock.set(op + timedelta(hours=1))
        aid = w.q1('SELECT id FROM assignments WHERE round_id=%s', (rid,))['id']
        for p in people:
            ids = upload_photos(p['client'], 1, p['i'] * 7 + k + game_no * 1000)
            d = p['client'].put(f'/api/games/{eid}/tasks/{aid}/draft', {'photos': ids, 'link': None})
            p['client'].post(f'/api/games/{eid}/tasks/{aid}/submit', {'draft_id': d['draft']['id']})
        w.clock.set(op + timedelta(days=3, hours=1))
        leagues = sorted({p['mini_league'] for p in people})
        cfg = {'method': 'criteria', 'pools': 'leagues', 'criteria': [{'label': 'Образ', 'weight': 1}],
               'judges': {lg: [j['user_id'] for j in J] for lg in leagues}, 'quota': {}}
        org.put(f'/api/org/rounds/{rid}/judging', cfg)
        v = org.post(f'/api/org/rounds/{rid}/judging/start')
        by_ep = {eps[p['i']]: p for p in people}
        for st in v['streams']:
            tm = {str(r['t']): by_ep[str(r['ep'])] for r in w.q('''SELECT t.id AS t, m.event_participant_id AS ep FROM evaluation_targets t
JOIN evaluation_target_members m ON m.evaluation_target_id=t.id WHERE t.evaluation_stream_id=%s''', (st['id'],))}
            for jd in J:
                s = jd['client'].get(f"/api/judging/streams/{st['id']}")
                for wk in s['works']:
                    val = scores[tm[wk['id']]['i']][k + 1]
                    jd['client'].post(f"/api/judging/streams/{st['id']}/works/{wk['id']}", {'scores': {s['criteria'][0]['code']: val}})
        org.post(f'/api/org/rounds/{rid}/judging/publish')
    w.clock.set(rids[-1][1] + timedelta(days=6))
    org.post(f'/api/org/events/{eid}/status', {'action': 'finish', 'early': True})
    v = org.get(f'/api/org/events/{eid}/results')
    return eid, eps, v


def mini_games(w):
    P = w.p
    # Игра 03: 32 человека в Gold (TOP-10 есть: 32 ≥ 30, 20% = 6), 2 тура (путь 50 / финал 50);
    # тройное равенство на 1 месте (решает организатор), номер Игры заполняется после старта.
    pool = [p for p in w.part if p.get('ep_id')][:32]
    scores = {}
    for k, p in enumerate(pool):
        p['mini_league'] = 'gold'
        scores[p['i']] = {1: 90 - k, 2: 90 - k}
    for p in pool[:3]:
        scores[p['i']] = {1: 95, 2: 95}
    eid, eps, v = mini_game(w, 'Игра 03 — равенства', 3, 2,
                            {'final_round': 2, 'path_rounds': [1], 'path_weight': 50, 'points': {}}, pool, scores, set_game_no_late=True)
    probs = (v.get('checks') or {}).get('problems') or v.get('problems') or []
    print('   mini 03 problems before decisions:', probs)
    P.check('place_tie' in json.dumps(v), 'major', 'итоги', 'тройное равенство на 1 месте не требует решения организатора')
    P.check('no_game_number' in json.dumps(v), 'major', 'итоги', 'нет номера Игры — публикация не остановлена')
    r = w.org.post(f'/api/org/events/{eid}/results/publish', expect=(409, 422))
    w.org.patch(f'/api/org/events/{eid}', {'game_no': 3})
    order = [eps[p['i']] for p in pool[:3]][::-1]
    w.org.post(f'/api/org/events/{eid}/results/tie', {'league': 'gold', 'order': order, 'reason': 'Голосование жюри'})
    pub = w.org.post(f'/api/org/events/{eid}/results/publish')
    er = {str(r['event_participant_id']): r for r in w.q('SELECT * FROM event_results WHERE event_id=%s AND is_current', (eid,))}
    got = [er[x]['award_place'] for x in order]
    P.check(got == [1, 2, 3], 'critical', 'итоги', f'решение о порядке равных не применилось: {got}')
    tops = sum(1 for r in er.values() if (r['calculation_snapshot'] or {}).get('top10'))
    print(f'   mini 03: awards {got}, top10 {tops}')
    P.check(tops == 6, 'critical', 'итоги', f'TOP-10 при 32 участницах: {tops} (ожидалось 6 = 20%)')
    certs = w.q('''SELECT c.certificate_number, c.issue_snapshot FROM certificates c JOIN event_participants p ON p.id=c.event_participant_id
WHERE p.event_id=%s ORDER BY c.certificate_number''', (eid,))
    P.check(len(certs) == 32 and certs[0]['certificate_number'] == 'FPL-S2-03-G-0001', 'critical', 'дипломы',
            f'дипломы Игры 03: {len(certs)}, первый {certs and certs[0]["certificate_number"]}')
    first = next(c for c in certs if c['certificate_number'].endswith('0001'))
    P.check(first['issue_snapshot'].get('title') == 'Победитель' or 'Победит' in json.dumps(first['issue_snapshot'], ensure_ascii=False),
            'major', 'дипломы', f'диплом №1: {first["issue_snapshot"]}')
    # Игра 04: один тур (он и финал), Silver 29 человек — TOP-10 нет (меньше 30); последний не выбывает «в 1 туре»
    pool = [p for p in w.part if p.get('ep_id')][40:69]
    scores = {}
    for k, p in enumerate(pool):
        p['mini_league'] = 'silver'
        scores[p['i']] = {1: 99 - 3 * k}
    eid, eps, v = mini_game(w, 'Игра 04 — один тур', 4, 1, {'final_round': 1, 'path_rounds': [], 'path_weight': 0, 'points': {}}, pool, scores)
    w.org.post(f'/api/org/events/{eid}/results/publish')
    er = {str(r['event_participant_id']): r for r in w.q('SELECT * FROM event_results WHERE event_id=%s AND is_current', (eid,))}
    P.check(sum(1 for r in er.values() if r['excluded_reason']) == 0, 'critical', 'итоги', 'в Игре из одного тура кто-то вне списка')
    P.check(sum(1 for r in er.values() if (r['calculation_snapshot'] or {}).get('top10')) == 0, 'critical', 'итоги', 'TOP-10 при 29 участницах')
    pts = {str(r['user_id']): r['s'] for r in w.q("SELECT user_id, sum(lifetime_delta) AS s FROM points_transactions WHERE event_id=%s GROUP BY 1", (eid,))}
    best = min(pool, key=lambda p: -scores[p['i']][1])
    P.check(pts.get(best['user_id']) == 13, 'major', 'итоги', f"1 место Silver в Игре 04: очков {pts.get(best['user_id'])} (ожидалось 12 + 1 TOP WORK)")
    print(f"   mini 04: 1st silver points {pts.get(best['user_id'])}")
