"""Робот-репетиция на сервере: Игра на N участниц в ТЕСТОВОМ кабинете (/kabinet-test/) в реальном времени.

Робот-организатор, роботы-участницы и роботы-судьи работают через тот же адрес, что и браузер (nginx → служба
fpl-kabinet-test), с настоящими сроками в минутах. Проверки — независимый пересчёт (sim/oracle.py), время ответов,
память службы (cgroup systemd). Итог — JSON в /var/lib/fpl/data/robot-report.json (на сайте: /data/robot-report.json;
там только числа, данные выдуманные).

Только тестовая база: запускается, лишь если FPL_ENVIRONMENT=TEST и имя базы оканчивается на _test.
Зависимости — из окружения кабинета (psycopg, Pillow, pwdlib); httpx не нужен.

    /opt/fpl/kabinet/venv/bin/python robot.py [--base https://домен/kabinet-test] [--n 200] [--minutes 12]
"""
import http.cookiejar
import io
import json
import math
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oracle as O  # noqa: E402

PASSWORD = 'Robot-rehearsal-password-1!'
OUT = os.environ.get('ROBOT_REPORT', '/var/lib/fpl/data/robot-report.json')
rng = random.Random(int(os.environ.get('ROBOT_SEED', '7')))
REPORT = {'started_at': None, 'stage': 'start', 'problems': [], 'timings': {}, 'memory_mb': {}, 'counts': {}}
LOCK = threading.Lock()


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def now():
    return datetime.now(timezone.utc)


def save(stage=None):
    if stage:
        REPORT['stage'] = stage
        print(f'[{now():%H:%M:%S}] {stage}', flush=True)
    REPORT['updated_at'] = now().isoformat()
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1, default=str)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)


class Problems:
    def __init__(self):
        self.items = REPORT['problems']

    def add(self, level, area, text):
        with LOCK:
            if len(self.items) < 300:
                self.items.append([level, area, text[:500]])
        print(f'  !! [{level}] {area}: {text[:300]}', flush=True)

    def check(self, cond, level, area, text):
        if not cond:
            self.add(level, area, text)
        return cond


P = Problems()


class Client:
    """Браузер без браузера: cookie, Origin, JSON."""
    def __init__(self, base, label):
        self.base, self.label = base.rstrip('/'), label
        parts = urlsplit(self.base)
        self.origin = f'{parts.scheme}://{parts.netloc}'
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, raw=None, ctype='application/json', expect=(200, 201), level='major', timing=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Origin': self.origin, 'Content-Type': ctype, 'Accept': 'application/json'})
        t = time.perf_counter()
        try:
            with self.op.open(req, timeout=120) as r:
                code, text = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, text = e.code, e.read()
        except Exception as e:      # сеть, таймаут
            code, text = type(e).__name__, b''
        dt = time.perf_counter() - t
        if timing:
            with LOCK:
                REPORT['timings'].setdefault(timing, []).append(round(dt, 3))
        try:
            out = json.loads(text) if text else {}
        except ValueError:
            out = {'_raw': text[:200].decode(errors='replace')}
        if code not in expect:
            P.add(level, 'api', f'{self.label}: {method} {path.split("?")[0]} → {code}: {str(out)[:200]}')
            return None
        return out


class World:
    pass


def stats(xs):
    if not xs:
        return None
    s = sorted(xs)
    return {'n': len(s), 'p50': s[len(s) // 2], 'p95': s[min(len(s) - 1, math.ceil(len(s) * .95) - 1)], 'max': s[-1]}


def memory_watch(stop):
    """Пик памяти служб по cgroup systemd (тестовый и рабочий кабинет)."""
    units = {'kabinet_test': 'fpl-kabinet-test.service', 'kabinet_prod': 'fpl-kabinet.service', 'all_services': 'system.slice'}
    peak = defaultdict(int)
    while not stop.is_set():
        for k, u in units.items():
            path = f'/sys/fs/cgroup/system.slice/{u}/memory.current' if u.endswith('.service') else '/sys/fs/cgroup/system.slice/memory.current'
            try:
                peak[k] = max(peak[k], int(open(path).read()))
            except (OSError, ValueError):
                pass
        try:
            avail = [int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith('MemAvailable')][0] // 1024
            REPORT['memory_mb']['min_available'] = min(REPORT['memory_mb'].get('min_available', 10 ** 9), avail)
        except (OSError, IndexError):
            pass
        REPORT['memory_mb'].update({k: v // 2 ** 20 for k, v in peak.items()})
        stop.wait(0.5)


def photo(seed, size=(3000, 2000)):
    r = random.Random(seed)
    noise = Image.effect_noise((size[0] // 4, size[1] // 4), 50).resize(size).convert('RGB')
    tint = Image.new('RGB', size, (r.randrange(256), r.randrange(256), r.randrange(256)))
    out = io.BytesIO()
    Image.blend(noise, tint, 0.5).save(out, 'JPEG', quality=85)
    return out.getvalue()


def parallel(fn, items, workers):
    t = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(fn, items))
    return res, round(time.perf_counter() - t, 1)


def wait_until(t, why):
    s = (t - now()).total_seconds()
    if s > 0:
        save(f'жду {why}: {int(s)} с')
        time.sleep(s)


def main():
    env_dsn = os.environ.get('FPL_DATABASE_DSN', '')
    if os.environ.get('FPL_ENVIRONMENT') != 'TEST' or not conninfo_to_dict(env_dsn).get('dbname', '').endswith('_test'):
        sys.exit('robot: только тестовый кабинет (FPL_ENVIRONMENT=TEST и база *_test)')
    base = arg('--base', 'http://127.0.0.1:8101')
    n = int(arg('--n', '200'))
    minutes = int(arg('--minutes', '12'))
    REPORT.update({'started_at': now().isoformat(), 'base': base, 'participants': n, 'minutes_per_round': minutes})
    save('подготовка')
    db = psycopg.connect(env_dsn, row_factory=dict_row, autocommit=True, options='-c TimeZone=UTC')
    stop = threading.Event()
    threading.Thread(target=memory_watch, args=(stop,), daemon=True).start()
    w = World()
    w.p, w.trace, w.tie_decided, w.engineered = P, defaultdict(list), [], []
    w.q = lambda sql, a=(): db.execute(sql, a).fetchall()
    w.q1 = lambda sql, a=(): db.execute(sql, a).fetchone()
    try:
        run(w, db, base, n, minutes)
    except Exception as exc:   # итог сохраняется в любом случае
        P.add('critical', 'робот', f'остановился: {type(exc).__name__}: {exc}')
        raise
    finally:
        stop.set()
        time.sleep(0.6)
        REPORT['timings_summary'] = {k: stats(v) for k, v in REPORT['timings'].items()}
        REPORT['timings'] = {}
        REPORT['finished_at'] = now().isoformat()
        REPORT['verdict'] = 'ok' if not any(p[0] in ('critical', 'major') for p in REPORT['problems']) else 'problems'
        save('готово')


def run(w, db, base, n, minutes):
    from pwdlib import PasswordHash
    tag = now().strftime('%m%d%H%M')
    h = PasswordHash.recommended().hash(PASSWORD)
    # 1. люди — сразу в тестовую базу (как перенос из бота); роли
    with db.transaction():
        def user(email, name, role):
            u = db.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,city,country_code)
VALUES (%s,%s,now(),'active',%s,'Казань','RU') RETURNING id''', (email, h, name)).fetchone()['id']
            db.execute('INSERT INTO user_roles VALUES (%s,%s)', (u, role))
            return str(u)
        org_id = user(f'robot-org-{tag}@example.com', 'Робот Организатор', 'admin')
        people = [{'i': i, 'email': f'robot-{tag}-{i:03d}@example.com', 'name': f'Робот{i:03d} Участница', 'skill': rng.gauss(0, 1),
                   'scen': set()} for i in range(n)]
        for p in people:
            p['user_id'] = user(p['email'], p['name'], 'participant')
        judges = [{'j': j, 'email': f'robot-{tag}-j{j}@example.com', 'bias': rng.gauss(0, .25)} for j in range(9)]
        for jd in judges:
            jd['user_id'] = user(jd['email'], f"Робот Судья {jd['j'] + 1}", 'judge')
    db.execute('DELETE FROM auth_rate_limits')
    org = Client(base, 'организатор')
    org.call('POST', '/web-auth/login', {'email': f'robot-org-{tag}@example.com', 'password': PASSWORD}, level='critical')
    # документы — только если в тестовой базе их ещё нет (не сбивать людям принятые Правила)
    have = {r['doc_type'] for r in w.q("SELECT DISTINCT doc_type FROM legal_documents WHERE published_at <= now()")}
    for kind in ('rules', 'publication', 'personal_data'):
        if kind not in have:
            org.call('POST', '/api/org/documents', {'doc_type': kind, 'version': 'R1', 'title': f'Тест: {kind}',
                                                    'body': 'Тестовый документ репетиции, не настоящий текст.'})
    season = org.call('POST', '/api/org/seasons', {'name': f'Робот {tag}', 'season_no': 98})
    if season is None:   # номер занят прошлым прогоном — без номера сезона, номер ставим свободный
        season = org.call('POST', '/api/org/seasons', {'name': f'Робот {tag}', 'season_no': 97 - int(tag[-2:]) % 50})
    e = org.call('POST', '/api/org/events', {'title': f'Робот-репетиция {tag}', 'season_id': season['id']}, level='critical')
    eid = e['id']
    t0 = now()
    D = timedelta(minutes=minutes)
    r1_open, r1_dl = t0 + timedelta(minutes=2), t0 + timedelta(minutes=2) + D
    r2_open = r1_dl + D            # время на судейство тура 1
    r2_dl = r2_open + D
    org.call('PATCH', f'/api/org/events/{eid}', {'game_no': 1, 'registration_opens_at': (t0 - timedelta(hours=1)).isoformat(),
                                                  'registration_closes_at': (t0 + timedelta(minutes=1)).isoformat(),
                                                  'starts_at': (t0 + timedelta(minutes=1)).isoformat(),
                                                  'ends_at': (r2_dl + 4 * D).isoformat()})
    w.rounds = []
    for no, (op, dl, form) in enumerate([(r1_open, r1_dl, {'photo': 'required', 'link': 'none', 'photo_max': 2}),
                                         (r2_open, r2_dl, {'photo': 'required', 'link': 'optional', 'photo_max': 2})], 1):
        r = org.call('POST', f'/api/org/events/{eid}/rounds', {})
        org.call('PATCH', f"/api/org/rounds/{r['id']}", {'title': f'Робот-тур {no}', 'opens_at': op.isoformat(), 'deadline': dl.isoformat(),
                                                         'judging_deadline': (dl + 2 * D).isoformat()})
        org.call('PUT', f"/api/org/rounds/{r['id']}/task", {'title': f'Робот-тур {no}', 'form': form,
                                                            'variants': [{'league': None, 'instructions': 'Задание робот-репетиции.'}]})
        org.call('POST', f"/api/org/rounds/{r['id']}/status", {'action': 'publish'})
        w.rounds.append({'id': r['id'], 'no': no, 'deadline': dl, 'opens': op, 'variants': [], 'form': form})
    org.call('PUT', f'/api/org/events/{eid}/results/format', {'final_round': 2, 'path_rounds': [1], 'path_weight': 40})
    org.call('POST', f'/api/org/events/{eid}/status', {'action': 'publish'}, level='critical')
    for r in w.q('SELECT a.id, r.round_no FROM assignments a JOIN rounds r ON r.id=a.round_id WHERE r.event_id=%s', (eid,)):
        w.rounds[r['round_no'] - 1]['assignment_id'] = str(r['id'])
    w.event, w.season, w.game_no, w.top25_min = eid, {'season_no': season.get('season_no')}, 1, 100
    w.fmt = {'final': 2, 'path': [1], 'weight': 40}
    w.deadline_for = lambda no, league: w.rounds[no - 1]['deadline']

    # 2. вход и запись: 20 одновременно (как после рассылки)
    save('вход и запись участниц')

    def join(p):
        c = Client(base, f"участница {p['i']}")
        for _ in range(20):        # «занято» — нажать ещё раз через пару секунд
            r = c.call('POST', '/web-auth/login', {'email': p['email'], 'password': PASSWORD}, expect=(200, 503), timing='вход')
            if r is not None and r.get('detail') != 'busy':
                break
            time.sleep(2)
        p['client'] = c
        r = c.call('POST', f'/api/events/{eid}/registration', {'accept_rules': True, 'accept_publication': True,
                                                              'accept_personal_data': True}, timing='запись')
        if r is None:   # документы приняты раньше или нужна новая редакция — принять и повторить
            return False
        return True
    res, wall = parallel(join, people, 20)
    REPORT['counts']['записались'] = sum(res)
    REPORT['counts']['вход_и_запись_сек'] = wall
    lst = {x['user_id']: x for x in org.call('GET', f'/api/org/events/{eid}/participants')['participants']}
    ranked = sorted(people, key=lambda p: -p['skill'])
    items = []
    for k, p in enumerate(ranked):
        x = lst.get(p['user_id'])
        if not x:
            continue
        p['ep_id'] = x['id']
        p['league'] = 'gold' if k < n * .2 else 'silver' if k < n * .55 else 'bronze'
        items.append({'id': p['ep_id'], 'league': p['league']})
    org.call('POST', f'/api/org/events/{eid}/leagues', {'items': items}, level='critical')
    w.part = [p for p in people if p.get('ep_id')]
    wait_until(t0 + timedelta(minutes=1, seconds=5), 'старта Игры')
    org.call('POST', f'/api/org/events/{eid}/status', {'action': 'start'}, level='critical')

    # 3. тур 1: сдача у срока, 20 одновременно; 5 опоздают, 10 заменят работу
    base_photos = [photo(s) for s in range(4)]
    REPORT['counts']['размер_фото_мб'] = round(sum(map(len, base_photos)) / 4 / 2 ** 20, 2)
    for p in w.part[:5]:
        p['scen'].add('late')
    for p in w.part[5:15]:
        p['scen'].add('replace')

    def send(p, rnd, label=''):
        c, aid = p['client'], rnd['assignment_id']
        ids = []
        for j in range(1 + (p['i'] % 4 == 0)):
            data = base_photos[(p['i'] + j) % 4] + os.urandom(8)
            r = c.call('POST', '/api/uploads', raw=data, ctype='image/jpeg', timing='загрузка фото')
            if r is None:
                return False
            ids.append(r['id'])
        d = c.call('PUT', f'/api/games/{eid}/tasks/{aid}/draft', {'photos': ids, 'link': None}, timing='черновик', expect=(200, 409))
        if not d or 'draft' not in d:
            return d
        s = c.call('POST', f'/api/games/{eid}/tasks/{aid}/submit', {'draft_id': d['draft']['id']}, timing='отправка', expect=(200, 409))
        return s

    def submit_round(rnd, who):
        def one(p):
            r = send(p, rnd)
            if r and 'replace' in p['scen'] and rnd['no'] == 1:
                r = send(p, rnd)
            return bool(r and 'detail' not in r)
        res, wall = parallel(one, who, 20)
        REPORT['counts'][f'тур{rnd["no"]}_сдали'] = sum(res)
        REPORT['counts'][f'тур{rnd["no"]}_сдача_сек'] = wall

    wait_until(r1_open + timedelta(seconds=5), 'открытия тура 1')
    save('тур 1: сдача')
    submit_round(w.rounds[0], [p for p in w.part if 'late' not in p['scen']])
    judge(w, org, db, base, judges, w.rounds[0], 'pairwise', r1_dl)
    # участницы смотрят итог тура; выбывшие — половина продолжает вне конкурса
    def look(p):
        g = p['client'].call('GET', f'/api/games/{eid}', timing='страница Игры')
        if g and g['me']['mode'] == 'out_pending' and p['i'] % 2 == 0:
            p['client'].call('POST', f'/api/games/{eid}/outside')
        return g is not None
    res, wall = parallel(look, w.part, 20)
    REPORT['counts']['итог_тура1_открыли'] = sum(res)

    # 4. тур 2: опоздавшие сдают работу тура 1 (для диплома), все — работу тура 2
    wait_until(r2_open + timedelta(seconds=5), 'открытия тура 2')
    db.execute('DELETE FROM auth_rate_limits')
    save('тур 2: сдача')
    for p in [x for x in w.part if 'late' in x['scen']]:
        r = send(p, w.rounds[0], 'late')
        P.check(r and 'detail' not in r, 'major', 'сдача', f'опоздавшая не сдала работу тура 1 после открытия тура 2: {r}')
    modes = {str(r['id']): r for r in w.q('SELECT id, competition_status FROM event_participants WHERE event_id=%s', (eid,))}
    submit_round(w.rounds[1], [p for p in w.part if modes[p['ep_id']]['competition_status'] in ('active', 'diploma_only')])
    judge(w, org, db, base, judges, w.rounds[1], 'criteria', r2_dl)

    # 5. итоги Игры
    save('итоги Игры')
    org.call('POST', f'/api/org/events/{eid}/status', {'action': 'finish'}, level='critical')
    t = time.perf_counter()
    v = org.call('GET', f'/api/org/events/{eid}/results', timing='итоги: черновик')
    for lg in ('gold', 'silver', 'bronze'):
        for tie in {tuple(sorted(r['tie'])) for r in v['rows'] if r.get('tie') and r['league'] == lg}:
            order = sorted(tie, key=lambda x: -next(p['skill'] for p in w.part if p['ep_id'] == x))
            org.call('POST', f'/api/org/events/{eid}/results/tie', {'league': lg, 'order': order, 'reason': 'Робот: решение жюри'})
            w.tie_decided.append((lg, order))
    org.call('POST', f'/api/org/events/{eid}/results/publish', timing='итоги: публикация', level='critical')
    O.check_game(w)
    res, wall = parallel(lambda p: p['client'].call('GET', f'/api/games/{eid}', timing='итоги у участницы') is not None, w.part, 20)
    REPORT['counts']['итоги_Игры_открыли'] = sum(res)
    REPORT['counts']['дипломов'] = w.q1('''SELECT count(*) AS n FROM certificates c JOIN event_participants p ON p.id=c.event_participant_id
WHERE p.event_id=%s''', (eid,))['n']


def judge(w, org, db, base, judges, rnd, method, deadline):
    no = rnd['no']
    wait_until(deadline + timedelta(seconds=20), f'срока тура {no}')
    save(f'тур {no}: судейство')
    J = [j['user_id'] for j in judges]
    cfg = {'method': method, 'pools': 'leagues', 'judges': {'gold': J[0:3], 'silver': J[3:6], 'bronze': J[6:9]}}
    if method == 'pairwise':
        works = Counter(r['league'] for r in w.q('''SELECT p.entry_league AS league FROM submissions s JOIN event_participants p
ON p.id=s.event_participant_id JOIN participant_assignments pa ON pa.id=s.participant_assignment_id
WHERE pa.assignment_id=%s AND s.latest_version_id IS NOT NULL AND s.is_on_time AND p.competition_status='active' ''', (rnd['assignment_id'],)))
        cfg.update({'per_target': 4, 'quota': {lg: max(1, round(k * .75)) for lg, k in works.items() if k > 1}})
    else:
        cfg.update({'criteria': [{'label': 'Образ', 'weight': 2}, {'label': 'Техника', 'weight': 1}], 'quota': {}})
    org.call('PUT', f"/api/org/rounds/{rnd['id']}/judging", cfg, level='critical')
    v = org.call('POST', f"/api/org/rounds/{rnd['id']}/judging/start", timing='судейство: запуск', level='critical')
    if not v or not v.get('started'):
        P.add('critical', f'тур {no}', f'судейство не стартовало: {v and v.get("checks")}')
        raise RuntimeError('judging not started')
    tmap = {}
    for st in v['streams']:
        by_ep = {p['ep_id']: p for p in w.part}
        for r in w.q('''SELECT t.id, m.event_participant_id AS ep FROM evaluation_targets t JOIN evaluation_target_members m
ON m.evaluation_target_id=t.id WHERE t.evaluation_stream_id=%s''', (st['id'],)):
            tmap[str(r['id'])] = by_ep[str(r['ep'])]
    db.execute('DELETE FROM auth_rate_limits')

    def work(jd):
        c = Client(base, f"судья {jd['j'] + 1}")
        c.call('POST', '/web-auth/login', {'email': jd['email'], 'password': PASSWORD})
        home = c.call('GET', '/api/judging') or {'streams': []}
        for st in [s for s in home['streams'] if s['open']]:
            while True:
                s = c.call('GET', f"/api/judging/streams/{st['id']}", timing='судья: страница пула')
                if not s:
                    break
                if method == 'pairwise' or s.get('next'):
                    nx = s.get('next')
                    if not nx:
                        break
                    row = w.q1('SELECT target_a_id, target_b_id FROM pairwise_comparisons WHERE id=%s', (nx['id'],))
                    a, b = tmap[str(row['target_a_id'])], tmap[str(row['target_b_id'])]
                    pa = 1 / (1 + math.exp(-(a['skill'] - b['skill']) * 1.6 + jd['bias']))
                    c.call('POST', f"/api/judging/comparisons/{nx['id']}", {'winner': 'a' if rng.random() < pa else 'b'}, timing='судья: голос')
                    continue
                todo = [x for x in s['works'] if not x['done']]
                if not todo:
                    break
                for wk in todo:
                    p = tmap[wk['id']]
                    val = int(max(1, min(100, round(60 + 14 * p['skill'] + rng.gauss(0, 6) + jd['bias'] * 10))))
                    c.call('POST', f"/api/judging/streams/{st['id']}/works/{wk['id']}",
                           {'scores': {cr['code']: val for cr in s['criteria']}}, timing='судья: оценка')
                break
        return True
    _, wall = parallel(work, judges, 9)
    REPORT['counts'][f'тур{no}_судейство_сек'] = wall
    for _ in range(3):
        view = org.call('GET', f"/api/org/rounds/{rnd['id']}/judging", timing='судейство: страница организатора')
        bad = [s for s in view['streams'] if s['border']['status'] != 'ok']
        if not bad:
            break
        for s in bad:
            tied = s['border']['tied'] or s['border'].get('unjudged') or []
            sure = sum(1 for r in s['rows'] if r.get('advanced') and r['target'] not in tied)
            stay = sorted(tied, key=lambda t: -tmap[t]['skill'])[:max(0, (s['quota'] or 0) - sure)]
            org.call('POST', f"/api/org/judging/streams/{s['id']}/decision", {'targets': tied, 'advance': stay, 'reason': 'Робот: решение жюри'},
                     expect=(200, 409, 422))
    org.call('POST', f"/api/org/rounds/{rnd['id']}/judging/publish", timing='судейство: публикация', level='critical')
    O.check_round(w, rnd)
    O.check_rating(w, rnd)
    save(f'тур {no}: опубликован')


if __name__ == '__main__':
    main()
