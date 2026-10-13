"""Общая обвязка симуляции: своя база *_test из схемы сервера, приложение с управляемыми часами, клиенты-люди.

Запуск: FPL_SIM_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m sim.game200
"""
import hashlib
import io
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from PIL import Image

from kabinet.config import Settings
from kabinet.main import create_app
from kabinet.auth.mail import MemoryMailer
from kabinet.auth.security import password_hasher

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / 'server' / 'db' / 'schema'
PASSWORD = 'Sim-test-password-123!'
ORIGIN = {'Origin': 'http://testserver'}
_HASH = None


def pw_hash():
    global _HASH
    if _HASH is None:
        _HASH = password_hasher.hash(PASSWORD)
    return _HASH


def make_db(source):
    if not conninfo_to_dict(source).get('dbname', '').endswith('_test'):
        sys.exit('FPL_SIM_DSN must point to a *_test database')
    name = 'fpl_sim_' + uuid4().hex[:10] + '_test'
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = make_conninfo(source, dbname=name)
    last = None
    for f in sorted(SCHEMA.glob('[0-9][0-9][0-9]_*.sql')):
        body = ''.join(l for l in f.read_text(encoding='utf-8').splitlines(True) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        with psycopg.connect(dsn) as conn:
            conn.execute(body)
        last = re.match(r'(\d{3})_', f.name).group(1)
    with psycopg.connect(dsn) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY)')
        conn.execute('DELETE FROM alembic_version')
        conn.execute('INSERT INTO alembic_version VALUES (%s)', (last,))
    return name, dsn


def drop_db(source, name):
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def set(self, value):
        self.now = value

    def shift(self, **delta):
        self.now = self.now + timedelta(**delta)


def settings_for(dsn, media_dir, **extra):
    values = dict(environment='TEST', database_dsn=dsn, login_limit=1000, reset_limit=10000, signup_limit=100,
                  upload_limit=1000, setup_key_sha256=hashlib.sha256(b'sim-setup-key').hexdigest(), _env_file=None,
                  media_dir=media_dir, media_min_free_mb=1)
    values.update(extra)
    return Settings(**values)


class Problems:
    """Найденные проблемы: (важность, область, текст). Важность: critical / major / minor / note."""
    def __init__(self):
        self.items = []

    def add(self, level, area, text):
        self.items.append((level, area, text))
        print(f'  !! [{level}] {area}: {text}', flush=True)

    def check(self, cond, level, area, text):
        if not cond:
            self.add(level, area, text)
        return cond


class Http:
    """Обёртка клиента: ok() требует ожидаемый код, иначе пишет проблему и возвращает None."""
    def __init__(self, app, problems, label):
        self.c = TestClient(app, headers=ORIGIN)
        self.p, self.label = problems, label
        self.timings = []

    def call(self, method, url, expect=200, level='major', **kw):
        t = time.perf_counter()
        r = self.c.request(method, url, **kw)
        self.timings.append((method, re.sub(r'[0-9a-f-]{36}', '{id}', url), time.perf_counter() - t))
        codes = expect if isinstance(expect, (tuple, list, set)) else (expect,)
        if r.status_code not in codes:
            self.p.add(level, 'api', f'{self.label}: {method} {url} → {r.status_code} (ожидалось {expect}): {r.text[:300]}')
            return None
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {'_raw': r.text}

    def get(self, url, **kw):
        return self.call('GET', url, **kw)

    def post(self, url, json=None, **kw):
        return self.call('POST', url, json=json, **kw)

    def put(self, url, json=None, **kw):
        return self.call('PUT', url, json=json, **kw)

    def patch(self, url, json=None, **kw):
        return self.call('PATCH', url, json=json, **kw)

    def raw(self, method, url, **kw):
        return self.c.request(method, url, **kw)


def jpeg(seed, size=(480, 640), noise=False):
    rnd = random.Random(seed)
    img = Image.new('RGB', size, (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    if noise:
        img = Image.effect_noise(size, 80).convert('RGB')
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=92)
    return out.getvalue()


def db_conn(dsn):
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
