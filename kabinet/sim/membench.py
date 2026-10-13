"""Память службы при одновременной загрузке фото: пик и остаток RSS при разных настройках malloc.

    FPL_SIM_DSN=... python -m sim.membench [workers] [uploads] [ENV=VAL ...]
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psutil

from sim.harness import PASSWORD, db_conn, drop_db, make_db, pw_hash
from sim.load import Mem, photo_bytes

PORT = 8792
B = f'http://127.0.0.1:{PORT}'


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    extra = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
    source = os.environ['FPL_SIM_DSN']
    name, dsn = make_db(source)
    media = tempfile.mkdtemp(prefix='fpl-mem-')
    env = dict(os.environ, FPL_ENVIRONMENT='TEST', FPL_DATABASE_DSN=dsn, FPL_MEDIA_DIR=media, FPL_MEDIA_MIN_FREE_MB='1',
               FPL_UPLOAD_LIMIT='10000', FPL_LOGIN_LIMIT='1000', FPL_FRONTEND_URL=B, **extra)
    srv = subprocess.Popen(['taskset', '-c', '0', sys.executable, '-m', 'uvicorn', 'kabinet.main:create_app', '--factory',
                            '--host', '127.0.0.1', '--port', str(PORT), '--no-access-log', '--workers', '1'],
                           env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if httpx.get(B + '/health').status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        db = db_conn(dsn)
        with db.transaction():
            uid = db.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES ('m@example.com',%s,now(),'active','M') RETURNING id''', (pw_hash(),)).fetchone()['id']
            db.execute("INSERT INTO user_roles VALUES (%s,'participant')", (uid,))
        c = httpx.Client(base_url=B, headers={'Origin': B}, timeout=300)
        c.post('/web-auth/login', json={'email': 'm@example.com', 'password': PASSWORD})
        base = [photo_bytes(s) for s in range(4)]
        idle = psutil.Process(srv.pid).memory_info().rss / 2 ** 20
        mem = Mem(srv.pid)
        t0 = time.perf_counter()
        codes = []

        def one(k):
            r = c.post('/api/uploads', content=base[k % 4] + os.urandom(16), headers={'Content-Type': 'image/jpeg'})
            codes.append(r.status_code)
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, range(n)))
        wall = time.perf_counter() - t0
        time.sleep(2)
        after = psutil.Process(srv.pid).memory_info().rss / 2 ** 20
        print(f'{extra or "default"} workers={workers} n={n}: idle {idle:.0f} MB, peak {mem.peak / 2 ** 20:.0f} MB, '
              f'after {after:.0f} MB, {wall:.1f}s, codes {sorted(set(codes))}', flush=True)
    finally:
        srv.send_signal(signal.SIGINT)
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        drop_db(source, name)


if __name__ == '__main__':
    main()
