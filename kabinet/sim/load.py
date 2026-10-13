"""Нагрузка и одновременность на настоящем uvicorn (как на сервере: 1 процесс, прокси-заголовки), своя база *_test.

Что меряем: вход 200 человек, сдача 200 работ у срока (фото 3–5 МБ), 25 судей сразу, страницы организатора с 200 строками,
двойные нажатия и одновременные публикации. Память службы (на сервере предел 350 МБ) — пик RSS процесса.

    FPL_SIM_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m sim.load [--cpu 0]
"""
import io
import json
import os
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import psutil
from PIL import Image

from sim.harness import PASSWORD, db_conn, drop_db, make_db, pw_hash

PORT = 8791
B = f'http://127.0.0.1:{PORT}'
H = {'Origin': B}
OUT = {}
rng = random.Random(7)


def photo_bytes(seed, mp=12):
    """Похоже на фото с телефона: 4000×3000, шум + градиент, JPEG q90 ≈ 3–5 МБ."""
    w, h = (4000, 3000) if mp == 12 else (2000, 1500)
    noise = Image.effect_noise((w // 4, h // 4), 60).resize((w, h)).convert('RGB')
    grad = Image.linear_gradient('L').resize((w, h)).convert('RGB')
    img = Image.blend(noise, grad, 0.4)
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=90)
    return out.getvalue()


class Mem:
    def __init__(self, pid):
        self.proc = psutil.Process(pid)
        self.peak = 0
        self.stop = False
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while not self.stop:
            try:
                rss = self.proc.memory_info().rss + sum(c.memory_info().rss for c in self.proc.children(recursive=True))
                self.peak = max(self.peak, rss)
            except psutil.Error:
                pass
            time.sleep(0.05)

    def reset(self):
        p = self.peak
        self.peak = 0
        return p / 2 ** 20


def stats(times):
    if not times:
        return {}
    t = sorted(times)
    return {'n': len(t), 'p50_ms': round(statistics.median(t) * 1000), 'p95_ms': round(t[int(len(t) * .95) - 1] * 1000),
            'max_ms': round(t[-1] * 1000)}


def run_parallel(fn, items, workers):
    times, errors = [], defaultdict(int)
    lock = threading.Lock()

    def one(x):
        t = time.perf_counter()
        try:
            code = fn(x)
        except Exception as exc:     # сеть, таймаут
            code = type(exc).__name__
        dt = time.perf_counter() - t
        with lock:
            times.append(dt)
            if code not in (200, 201, True):
                errors[str(code)] += 1
    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, items))
    return {**stats(times), 'wall_s': round(time.perf_counter() - t0, 1), 'errors': dict(errors)}


def client(email):
    c = httpx.Client(base_url=B, headers=H, timeout=120)
    r = c.post('/web-auth/login', json={'email': email, 'password': PASSWORD})
    assert r.status_code == 200, r.text
    return c


def main():
    source = os.environ['FPL_SIM_DSN']
    name, dsn = make_db(source)
    media = tempfile.mkdtemp(prefix='fpl-load-media-')
    env = dict(os.environ, FPL_ENVIRONMENT='TEST', FPL_DATABASE_DSN=dsn, FPL_MEDIA_DIR=media, FPL_MEDIA_MIN_FREE_MB='1',
               FPL_LOGIN_LIMIT='20', FPL_UPLOAD_LIMIT='60', FPL_FRONTEND_URL=B, FPL_MAIL_MODE='disabled')
    cmd = [sys.executable, '-m', 'uvicorn', 'kabinet.main:create_app', '--factory', '--host', '127.0.0.1', '--port', str(PORT),
           '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1', '--no-access-log', '--workers', '1']
    if '--cpu' in sys.argv:
        cmd = ['taskset', '-c', sys.argv[sys.argv.index('--cpu') + 1]] + cmd
    srv = subprocess.Popen(cmd, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get(B + '/health').status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        mem = Mem(srv.pid)
        db = db_conn(dsn)
        OUT['idle_rss_mb'] = round(psutil.Process(srv.pid).memory_info().rss / 2 ** 20)
        # люди и Игра — напрямую в базу (подготовка, не измерение)
        h = pw_hash()
        with db.transaction():
            org = db.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES ('org@example.com',%s,now(),'active','Организатор') RETURNING id''', (h,)).fetchone()['id']
            db.execute("INSERT INTO user_roles VALUES (%s,'admin')", (org,))
            people, judges = [], []
            for i in range(200):
                u = db.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,city,country_code)
VALUES (%s,%s,now(),'active',%s,'Казань','RU') RETURNING id''', (f'l{i:03d}@example.com', h, f'Участница {i:03d}')).fetchone()['id']
                db.execute("INSERT INTO user_roles VALUES (%s,'participant')", (u,))
                people.append((str(u), f'l{i:03d}@example.com'))
            for j in range(25):
                u = db.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES (%s,%s,now(),'active',%s) RETURNING id''', (f'lj{j:02d}@example.com', h, f'Судья {j}')).fetchone()['id']
                db.execute("INSERT INTO user_roles VALUES (%s,'judge')", (u,))
                judges.append((str(u), f'lj{j:02d}@example.com'))
        adm = client('org@example.com')
        for kind in ('rules', 'publication', 'personal_data'):
            adm.post('/api/org/documents', json={'doc_type': kind, 'version': '1', 'title': kind, 'body': 'Текст документа для нагрузки.'})
        now = datetime.now(timezone.utc)
        season = adm.post('/api/org/seasons', json={'name': 'Нагрузка', 'season_no': 9}).json()
        e = adm.post('/api/org/events', json={'title': 'Нагрузка', 'season_id': season['id']}).json()
        eid = e['id']
        adm.patch(f'/api/org/events/{eid}', json={'game_no': 1, 'registration_opens_at': (now - timedelta(days=1)).isoformat(),
                                                   'registration_closes_at': (now + timedelta(hours=2)).isoformat(),
                                                   'starts_at': (now - timedelta(hours=1)).isoformat(), 'ends_at': (now + timedelta(days=10)).isoformat()})
        deadline = now + timedelta(minutes=12)
        r = adm.post(f'/api/org/events/{eid}/rounds', json={}).json()
        rid = r['id']
        adm.patch(f'/api/org/rounds/{rid}', json={'title': 'Тур', 'opens_at': (now - timedelta(minutes=30)).isoformat(),
                                                  'deadline': deadline.isoformat(), 'judging_deadline': (now + timedelta(days=1)).isoformat()})
        adm.put(f'/api/org/rounds/{rid}/task', json={'title': 'Тур', 'form': {'photo': 'required', 'link': 'optional', 'photo_max': 3},
                                                     'variants': [{'league': None, 'instructions': 'Задание.'}]})
        adm.post(f'/api/org/rounds/{rid}/status', json={'action': 'publish'})
        adm.post(f'/api/org/events/{eid}/status', json={'action': 'publish'})

        # 1. вход 200 человек: сначала все с одного адреса (как за одним мобильным NAT), потом — с разных
        def login_one(email, ip=None):
            c = httpx.Client(base_url=B, headers=H | ({'X-Forwarded-For': ip} if ip else {}), timeout=60)
            r = c.post('/web-auth/login', json={'email': email, 'password': PASSWORD})
            return r.status_code
        mem.reset()
        OUT['login_200_same_ip_w20'] = run_parallel(lambda p: login_one(p[1]), people, 20)
        OUT['login_200_same_ip_w20']['rss_peak_mb'] = round(mem.reset())
        db.execute('DELETE FROM auth_rate_limits')
        clients = {}
        lock = threading.Lock()

        busy = [0]

        def login_keep(p):
            c = httpx.Client(base_url=B, headers=H, timeout=120)
            for _ in range(30):      # «занято» — человек нажимает ещё раз через пару секунд
                r = c.post('/web-auth/login', json={'email': p[1], 'password': PASSWORD})
                if r.status_code != 503:
                    break
                with lock:
                    busy[0] += 1
                time.sleep(2)
            with lock:
                clients[p[0]] = c
            return r.status_code
        db.execute('ALTER TABLE auth_rate_limits DISABLE TRIGGER ALL') if False else None
        # (адрес клиента — 127.0.0.1: у сервера свой лимит на адрес; чтобы дальше мерить не лимит, а скорость — чистим)
        db.execute('DELETE FROM auth_rate_limits')
        mem.reset()
        OUT['login_200_w20_with_retry'] = run_parallel(login_keep, people, 20)
        OUT['login_200_w20_with_retry'].update({'busy_answers': busy[0], 'rss_peak_mb': round(mem.reset())})
        # заявки
        mem.reset()
        OUT['register_200_w20'] = run_parallel(lambda p: clients[p[0]].post(
            f'/api/events/{eid}/registration', json={'accept_rules': True, 'confirm_adult': True, 'accept_publication': True, 'accept_personal_data': True}).status_code,
            people, 20)
        OUT['register_200_w20']['rss_peak_mb'] = round(mem.reset())
        adm.post(f'/api/org/events/{eid}/status', json={'action': 'start'})
        lst = adm.get(f'/api/org/events/{eid}/participants').json()['participants']
        ep_of = {x['user_id']: x['id'] for x in lst}
        for k, (uid, _) in enumerate(people):
            adm.post(f'/api/org/participants/{ep_of[uid]}/league', json={'league': ('gold', 'silver', 'bronze')[k % 3]})
        g = clients[people[0][0]].get(f'/api/games/{eid}').json()
        aid = g['rounds'][0]['assignment_id']
        # 2. сдача 200 работ у срока: фото как с телефона (3–5 МБ), у части — по 2–3 фото
        base = [photo_bytes(s) for s in range(4)]
        OUT['photo_sizes_mb'] = [round(len(b) / 2 ** 20, 2) for b in base]

        def submit_one(p):
            c = clients[p[0]]
            k = 1 + (int(p[0][-2:], 16) % 3 == 0) + (int(p[0][-2:], 16) % 7 == 0)
            ids = []
            for j in range(k):
                data = base[(int(p[0][-1], 16) + j) % 4] + os.urandom(16)     # другие байты — другой файл на диске
                r = c.post('/api/uploads', content=data, headers={'Content-Type': 'image/jpeg'})
                if r.status_code != 201:
                    return f'upload {r.status_code} {r.text[:80]}'
                ids.append(r.json()['id'])
            d = c.put(f'/api/games/{eid}/tasks/{aid}/draft', json={'photos': ids, 'link': None})
            if d.status_code != 200:
                return f'draft {d.status_code}'
            s = c.post(f'/api/games/{eid}/tasks/{aid}/submit', json={'draft_id': d.json()['draft']['id']})
            return s.status_code
        for workers, chunk in ((5, people[:50]), (10, people[50:100]), (20, people[100:200])):
            mem.reset()
            res = run_parallel(submit_one, chunk, workers)
            res['rss_peak_mb'] = round(mem.reset())
            OUT[f'submit_{len(chunk)}_w{workers}'] = res
            print('submit', workers, res, flush=True)
        du = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(media) for f in fs)
        orig = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(os.path.join(media, 'orig')) for f in fs)
        n_photos = db.execute('SELECT count(*) AS n FROM media_files').fetchone()['n']
        OUT['disk'] = {'photos': n_photos, 'total_mb': round(du / 2 ** 20), 'orig_mb': round(orig / 2 ** 20),
                       'per_photo_mb': round(du / 2 ** 20 / max(1, n_photos), 2)}
        # 3. одновременно: одна работа отправлена дважды (двойной клик) — одна версия
        c = clients[people[0][0]]
        ph = c.post('/api/uploads', content=base[0] + b'dbl', headers={'Content-Type': 'image/jpeg'}).json()['id']
        d = c.put(f'/api/games/{eid}/tasks/{aid}/draft', json={'photos': [ph], 'link': None}).json()['draft']['id']
        with ThreadPoolExecutor(2) as ex:
            codes = list(ex.map(lambda _: c.post(f'/api/games/{eid}/tasks/{aid}/submit', json={'draft_id': d}).status_code, range(2)))
        OUT['double_submit_codes'] = codes
        # 4. страницы организатора с 200 строками
        for url in (f'/api/org/events/{eid}/participants', f'/api/org/events/{eid}', '/api/org/home', '/api/org/people'):
            t = time.perf_counter()
            r = adm.get(url)
            OUT['org ' + url.split(eid)[-1] if eid in url else 'org ' + url] = {'ms': round((time.perf_counter() - t) * 1000), 'kb': len(r.content) // 1024, 'code': r.status_code}
        # 5. судейство: срок прошёл → 3 пула по лигам, по 3 судьи, 6 сравнений
        wait = (deadline - datetime.now(timezone.utc)).total_seconds() + 2
        print(f'waiting {wait:.0f}s for deadline', flush=True)
        time.sleep(max(0, wait))
        J = [u for u, _ in judges]
        cfg = {'method': 'pairwise', 'pools': 'leagues', 'per_target': 6,
               'judges': {'gold': J[0:3], 'silver': J[3:6], 'bronze': J[6:9]}, 'quota': {'gold': 30, 'silver': 30, 'bronze': 30}}
        adm.put(f'/api/org/rounds/{rid}/judging', json=cfg)
        t = time.perf_counter()
        v = adm.post(f'/api/org/rounds/{rid}/judging/start')
        OUT['judging_start_ms'] = round((time.perf_counter() - t) * 1000)
        v = v.json()
        db.execute('DELETE FROM auth_rate_limits')     # все запросы теста идут с одного адреса
        jc = {u: client(e) for u, e in judges[:9]}
        stream_of = {}
        for u in J[:9]:
            stream_of[u] = jc[u].get('/api/judging').json()['streams'][0]['id']
        vote_times, view_kb = [], []
        vlock = threading.Lock()

        def judge_run(u):
            c = jc[u]
            sid = stream_of[u]
            n = 0
            while True:
                t = time.perf_counter()
                s = c.get(f'/api/judging/streams/{sid}')
                if s.status_code != 200:
                    return s.status_code
                s = s.json()
                if not s['next']:
                    return True
                r = c.post(f"/api/judging/comparisons/{s['next']['id']}", json={'winner': rng.choice('ab')})
                dt = time.perf_counter() - t
                with vlock:
                    vote_times.append(dt)
                    view_kb.append(len(r.content) / 1024)
                if r.status_code != 200:
                    return r.status_code
                n += 1
        mem.reset()
        t0 = time.perf_counter()
        with ThreadPoolExecutor(9) as ex:
            res = list(ex.map(judge_run, J[:9]))
        OUT['judging_9_judges'] = {**stats(vote_times), 'votes': len(vote_times), 'wall_s': round(time.perf_counter() - t0),
                                   'last_response_kb': round(max(view_kb)), 'results': res, 'rss_peak_mb': round(mem.reset())}
        # повторный голос по одной паре одновременно
        u = J[0]
        cid = db.execute('''SELECT c.id FROM pairwise_comparisons c JOIN evaluation_judge_assignments a ON a.judge_slot_id=c.judge_slot_id
WHERE a.user_id=%s LIMIT 1''', (u,)).fetchone()['id']
        with ThreadPoolExecutor(2) as ex:
            OUT['double_vote_codes'] = list(ex.map(lambda w: jc[u].post(f'/api/judging/comparisons/{cid}', json={'winner': w}).status_code, 'ab'))
        t = time.perf_counter()
        r = adm.get(f'/api/org/rounds/{rid}/judging')
        OUT['org_judging_view'] = {'ms': round((time.perf_counter() - t) * 1000), 'kb': len(r.content) // 1024}
        jv = r.json()
        for st in jv['streams']:
            if st['border']['status'] != 'ok':
                tied = st['border']['tied'] or st['border']['unjudged']
                adm.post(f"/api/org/judging/streams/{st['id']}/decision", json={'targets': tied, 'advance': tied[:max(0, st['quota'] - sum(1 for x in st['rows'] if x['advanced'] and x['target'] not in tied))], 'reason': 'нагрузка'})
        # две публикации тура одновременно
        mem.reset()
        with ThreadPoolExecutor(2) as ex:
            t = time.perf_counter()
            OUT['double_publish_codes'] = list(ex.map(lambda _: adm.post(f'/api/org/rounds/{rid}/judging/publish').status_code, range(2)))
            OUT['publish_ms'] = round((time.perf_counter() - t) * 1000)
        OUT['publish_rss_mb'] = round(mem.reset())
        OUT['round_results_rows'] = db.execute('SELECT count(*) AS n FROM round_results WHERE round_id=%s', (rid,)).fetchone()['n']
        # 6. 200 участниц открывают кабинет после рассылки итогов
        mem.reset()
        OUT['open_game_200_w20'] = run_parallel(lambda p: clients[p[0]].get(f'/api/games/{eid}').status_code, people, 20)
        OUT['open_game_200_w20']['rss_peak_mb'] = round(mem.reset())
        OUT['open_home_200_w20'] = run_parallel(lambda p: clients[p[0]].get('/api/home').status_code, people, 20)
        # 7. итоги Игры: завершить, черновик, две публикации сразу
        adm.post(f'/api/org/events/{eid}/status', json={'action': 'finish', 'early': True})
        t = time.perf_counter()
        r = adm.get(f'/api/org/events/{eid}/results')
        OUT['results_view'] = {'ms': round((time.perf_counter() - t) * 1000), 'kb': len(r.content) // 1024, 'code': r.status_code}
        with ThreadPoolExecutor(2) as ex:
            t = time.perf_counter()
            OUT['double_results_publish'] = list(ex.map(lambda _: adm.post(f'/api/org/events/{eid}/results/publish').status_code, range(2)))
            OUT['results_publish_ms'] = round((time.perf_counter() - t) * 1000)
        OUT['points_rows'] = db.execute("SELECT count(*) AS n, count(DISTINCT user_id) AS u FROM points_transactions WHERE reason_code='game_result'").fetchone()
        OUT['cert_rows'] = db.execute('SELECT count(*) AS n, count(DISTINCT event_participant_id) AS u FROM certificates').fetchone()
        OUT['peak_overall_rss_mb'] = round(psutil.Process(srv.pid).memory_info().rss / 2 ** 20)
    finally:
        srv.send_signal(signal.SIGINT)
        try:
            out, _ = srv.communicate(timeout=10)
            tail = out.decode(errors='replace').splitlines()[-30:]
            OUT['server_log_tail'] = [l for l in tail if 'Traceback' in l or 'Error' in l or 'error' in l][:10]
        except subprocess.TimeoutExpired:
            srv.kill()
        json.dump(OUT, open('load-report.json', 'w'), ensure_ascii=False, indent=1, default=str)
        print(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
        shutil.rmtree(media, ignore_errors=True)
        drop_db(source, name)


if __name__ == '__main__':
    main()
