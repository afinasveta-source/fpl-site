"""Тесты кабинета — только на настоящей PostgreSQL.

База создаётся заново из тех же файлов схемы, что ставятся на сервер (server/db/schema/*.sql),
поэтому схема кабинета и сервера не может разойтись. Нужна переменная FPL_TEST_DSN — подключение
к служебной базе с именем *_test (тесты создают и удаляют свою отдельную базу).
"""
import os
import re
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from fastapi.testclient import TestClient

from kabinet.config import Settings
from kabinet.main import create_app
from kabinet.auth.mail import MemoryMailer
from kabinet.auth.security import password_hasher

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / 'server' / 'db' / 'schema'
PASSWORD = 'Correct-test-password-123!'
SETUP_KEY = 'server-ingest-key-for-tests'


def schema_files():
    files = sorted(SCHEMA.glob('[0-9][0-9][0-9]_*.sql'))
    assert files, 'server/db/schema is empty'
    return files


def apply_schema(dsn):
    last = None
    for f in schema_files():
        body = ''.join(l for l in f.read_text(encoding='utf-8').splitlines(True) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        with psycopg.connect(dsn) as conn:
            conn.execute(body)
        last = re.match(r'(\d{3})_', f.name).group(1)
    with psycopg.connect(dsn) as conn:  # как fpl-db-setup на сервере
        conn.execute('CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY)')
        conn.execute('DELETE FROM alembic_version')
        conn.execute('INSERT INTO alembic_version VALUES (%s)', (last,))
    return last


@pytest.fixture(scope='session')
def database_dsn():
    source = os.environ.get('FPL_TEST_DSN')
    if not source:
        pytest.fail('FPL_TEST_DSN is required; integration tests never substitute SQLite')
    if not conninfo_to_dict(source).get('dbname', '').endswith('_test'):
        pytest.fail('Only a dedicated TEST connection is permitted')
    name = 'fpl_kabinet_' + uuid4().hex[:12] + '_test'
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = make_conninfo(source, dbname=name)
    try:
        apply_schema(dsn)
        yield dsn
    finally:
        with psycopg.connect(source, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def make_settings(dsn, **extra):
    import hashlib
    values = dict(environment='TEST', database_dsn=dsn, login_limit=50, reset_limit=50,
                  setup_key_sha256=hashlib.sha256(SETUP_KEY.encode()).hexdigest(), _env_file=None)
    values.update(extra)
    return Settings(**values)


@pytest.fixture
def app(database_dsn):
    with psycopg.connect(database_dsn) as conn:
        conn.execute('TRUNCATE users CASCADE')
        conn.execute('TRUNCATE auth_rate_limits')
    return create_app(make_settings(database_dsn), MemoryMailer())


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed(app):
    def create(email='person@example.com', roles=('participant',), status='active'):
        with app.state.db.transaction() as conn:
            user = conn.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status)
VALUES (%s,%s,CASE WHEN %s='active' THEN now() ELSE NULL END,%s) RETURNING id''',
                                (email, password_hasher.hash(PASSWORD) if status == 'active' else None, status, status)).fetchone()
            for role in roles:
                conn.execute('INSERT INTO user_roles(user_id,role) VALUES (%s,%s)', (user['id'], role))
            return user['id']
    return create


@pytest.fixture
def admin_headers(client, seed):
    seed('admin@example.com', ('admin',))
    response = client.post('/auth/login', json={'email': 'admin@example.com', 'password': PASSWORD})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}
