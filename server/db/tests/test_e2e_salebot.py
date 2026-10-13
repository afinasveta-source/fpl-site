#!/usr/bin/env python3
"""Сквозная проверка: SQL из блока «Сайт: выгрузка в базу» (make_blocks.py) на копии схемы SaleBot в SQLite
→ приёмник fpl-ingest.py (части, закрытые наборы) → fpl-db-import → публичные файлы.

Запуск: python3 server/db/tests/test_e2e_salebot.py   (нужны локальный PostgreSQL и /etc/fpl-db.env)
"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'server', 'salebot'))
import test_import as T          # фикстура, база и проверки
import make_blocks as B

failures = T.failures


def sqlite_copy(tables):
    db = sqlite3.connect(':memory:')
    for name, rows in tables.items():
        cols = B.EXPORT.get(name, (None, 0))[0] or sorted({k for r in rows for k in r})
        db.execute('CREATE TABLE %s (%s)' % (name, ', '.join(cols)))
        for r in rows:
            db.execute('INSERT INTO %s (%s) VALUES (%s)' % (name, ', '.join(cols), ', '.join('?' * len(cols))),
                       [r.get(c) for c in cols])
    return db


def post(port, key, url_tail, payload):
    req = urllib.request.Request('http://127.0.0.1:%d/api/ingest?name=%s' % (port, url_tail),
                                 data=json.dumps({'data': payload}, ensure_ascii=False).encode(),
                                 headers={'X-FPL-Key': key, 'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    T.fresh_db()
    priv, data, parts = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    port, key = 18471, 'test-key-' + str(os.getpid())
    env = dict(os.environ, FPL_DATA=data, FPL_PRIVATE=priv, FPL_PARTS=parts, FPL_INGEST_KEY=key, FPL_PORT=str(port))
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, 'server', 'fpl-ingest.py')], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        B.PART_ROWS = 7                      # мелкие части, чтобы проверить склейку
        fx = T.fixture()
        fx.pop('mg_client_channels')         # в блоке колонки не заданы — таблица не уходит
        db = sqlite_copy(fx)
        # 1) частей не хватает: строки теряются → блок пишет «НЕ ПОМЕСТИЛОСЬ», сервер не переносит неполный снимок
        short = B.export_block()
        T.check('НЕ ПОМЕСТИЛОСЬ' in short and 'if(sb_n5 > 28' in short, 'блок предупреждает о нехватке частей')
        for t, (cols, _) in list(B.EXPORT.items()):
            if cols:
                n = db.execute('SELECT count(*) FROM %s' % t).fetchone()[0]
                B.EXPORT[t] = (cols, n // B.PART_ROWS + 1)
        text = B.export_block()
        sent = {}
        for m in re.finditer(r'^(sb_\d+_\d+) = sql_value\("(.*)", \[\]\)$', text, re.M):
            sql = m.group(2).replace('\\"', '"').replace('\\\\', '\\')
            payload = json.loads(db.execute(sql).fetchone()[0])
            url = re.search(r'^%s_r = requests_post\("[^"]*name=([^"]+)"' % m.group(1), text, re.M).group(1)
            r = post(port, key, url, payload)
            t = url.split('&')[0].replace('private-sb-', '')
            sent.setdefault(t, 0)
            sent[t] += len(payload)
            if not r.get('ok'):
                failures.append('приёмник отклонил %s: %s' % (url, r))
        counts = {t: db.execute('SELECT count(*) FROM %s' % t).fetchone()[0] for t in sent}
        T.check(counts == sent, 'все строки ушли частями (%d таблиц)' % len(sent))
        T.check(all(os.stat(os.path.join(priv, f)).st_mode & 0o077 == 0 for f in os.listdir(priv)), 'закрытые файлы — только владельцу')
        T.check(not any(f.startswith('private') for f in os.listdir(data)), 'в публичной папке закрытых наборов нет')
        bad = dict(counts, mg_legal_acceptances=counts['mg_legal_acceptances'] + 5)
        post(port, key, 'private-sb-manifest', {'export_id': 'e2e-short', 'project': '874007', 'tables': bad})
        p, st = T.run(priv, data)
        T.check('waiting' in st and 'mg_legal_acceptances' in st['waiting'] and T.q1('SELECT count(*) FROM users') == 0,
                'неполный снимок не переносится, в статусе видно какая таблица')
        r = post(port, key, 'private-sb-manifest', {'export_id': 'e2e', 'project': '874007', 'tables': counts})
        p, st = T.run(priv, data)
        T.check(st.get('status') == 'completed', 'импорт снимка из приёмника: %s %s' % (st.get('status'), p.stderr[-300:]))
        T.check(T.q1('SELECT count(*) FROM users') == 12 and T.q1('SELECT count(*) FROM round_results') == 20,
                'люди 12, итоги 20')
        T.check(len(T.rating_after_game()[1]['seasons'][0]['players']) == 10, 'рейтинг на сайт: 10 (без публичного имени — имя из ФИО)')
        photos = B.photos_block()
        T.check(photos.count('requests_post') == len(B.PHOTOS) and 'private-photos' in photos, 'блок архива фото собран')
    finally:
        srv.terminate()
        for d in (priv, data, parts):
            shutil.rmtree(d)
        T.su('DROP DATABASE IF EXISTS %s' % T.TEST_DB)
    print('\nИТОГ: %s' % ('всё прошло' if not failures else '%d проверок не прошли: %s' % (len(failures), failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
