"""Первый администратор по ключу сервера, адрес кабинета в подпапке, письма выключены."""
import hashlib

from fastapi.testclient import TestClient

from conftest import PASSWORD, SETUP_KEY, make_settings
from kabinet.auth.mail import DisabledMailer
from kabinet.main import create_app

ORIGIN = {'Origin': 'http://testserver'}
BODY = {'key': SETUP_KEY, 'email': 'Owner@Example.com', 'password': PASSWORD, 'full_name': '  Светлана  '}


def test_first_admin_once(client, app):
    assert client.get('/web-auth/config').json()['setup_needed'] is True
    r = client.post('/web-auth/setup', headers=ORIGIN, json=BODY)
    assert r.status_code == 201, r.text
    assert r.json()['roles'] == ['admin'] and r.json()['email'] == 'owner@example.com' and r.json()['full_name'] == 'Светлана'
    assert 'HttpOnly' in r.headers['set-cookie'] and PASSWORD not in r.text and SETUP_KEY not in r.text
    assert client.get('/web-auth/me').json()['roles'] == ['admin']   # сразу вошёл
    assert client.get('/web-auth/config').json()['setup_needed'] is False
    again = client.post('/web-auth/setup', headers=ORIGIN, json=dict(BODY, email='second@example.com'))
    assert again.status_code == 409
    with app.state.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM user_roles WHERE role='admin'").fetchone()['n'] == 1
        assert conn.execute("SELECT password_hash FROM users").fetchone()['password_hash'].startswith('$argon2id$')
        assert conn.execute("SELECT action FROM audit_log").fetchone()['action'] == 'admin_setup'


def test_wrong_key_and_existing_admin(client, seed):
    assert client.post('/web-auth/setup', headers=ORIGIN, json=dict(BODY, key='wrong-key-1234')).status_code == 403
    seed('admin@example.com', ('admin',))
    assert client.get('/web-auth/config').json()['setup_needed'] is False
    assert client.post('/web-auth/setup', headers=ORIGIN, json=BODY).status_code == 409


def test_setup_requires_same_origin_and_strong_password(client):
    assert client.post('/web-auth/setup', json=BODY).status_code == 403
    assert client.post('/web-auth/setup', headers={'Origin': 'https://attacker.example'}, json=BODY).status_code == 403
    weak = client.post('/web-auth/setup', headers=ORIGIN, json=dict(BODY, password='Qz7#x'))
    assert weak.status_code == 422 and 'Qz7#x' not in weak.text


def test_setup_is_throttled(client, app):
    app.state.auth.settings.reset_limit = 2
    codes = [client.post('/web-auth/setup', headers=ORIGIN, json=dict(BODY, key='wrong-key-%d' % i)).status_code for i in range(3)]
    assert codes == [403, 403, 429]


def test_setup_disabled_without_key(database_dsn):
    app = create_app(make_settings(database_dsn, setup_key_sha256=None))
    with TestClient(app) as c:
        assert c.get('/web-auth/config').json()['setup_needed'] is False
        assert c.post('/web-auth/setup', headers=ORIGIN, json=BODY).status_code == 404


def test_root_path_and_disabled_mail(database_dsn, app):
    """Как на сервере: адрес /kabinet, письма не настроены — сброс отвечает одинаково и пишет ошибку в журнал."""
    app2 = create_app(make_settings(database_dsn, root_path='/kabinet', mail_mode='disabled'))
    with TestClient(app2) as c:   # как за nginx: /kabinet/... приходит без /kabinet
        for asset in ('/assets/core.js', '/assets/pages.js', '/assets/org.js', '/assets/org-people.js', '/assets/org-judging.js', '/assets/judge.js', '/assets/account.js', '/assets/cabinet.css', '/assets/fonts.css'):
            assert c.get(asset).status_code == 200, asset
        page = c.get('/')
        assert 'src="/kabinet/assets/core.js?v=' in page.text and 'data-root="/kabinet"' in page.text
        assert c.get('/web-auth/config').json()['mail_delivery'] is False
        with app2.state.db.transaction() as conn:
            conn.execute("""INSERT INTO users(email,password_hash,email_verified_at,account_status)
VALUES ('person@example.com','x',now(),'active')""")
        r = c.post('/auth/password/reset-request', json={'email': 'person@example.com'})
        assert r.status_code == 202
        with app2.state.db.transaction() as conn:
            assert conn.execute("SELECT 1 FROM system_errors WHERE error_code='MAIL_DELIVERY_FAILED'").fetchone()
            assert conn.execute("SELECT used_at FROM auth_tokens").fetchone()['used_at'] is not None
        # Origin без подпапки — тот же сайт
        assert c.post('/web-auth/login', headers=ORIGIN, json={'email': 'x@example.com', 'password': 'y'}).status_code == 401
    assert isinstance(app2.state.mailer, DisabledMailer)


def test_ready_accepts_newer_schema(client, app):
    with app.state.db.transaction() as conn:
        old = conn.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
        conn.execute("UPDATE alembic_version SET version_num='015'")
    try:
        assert client.get('/ready').json() == {'status': 'ready', 'schema': '015'}
    finally:
        with app.state.db.transaction() as conn:
            conn.execute('UPDATE alembic_version SET version_num=%s', (old,))


def test_setup_key_hash_matches_server_rule():
    # На сервере в настройки пишется sha256 ключа приёмника — так же, как здесь.
    assert len(hashlib.sha256(SETUP_KEY.encode()).hexdigest()) == 64


def test_cabinet_pages_open_from_any_address(client):
    for url in ('/games', '/games/6f1c2a5e-0000-4000-8000-000000000001/tasks/6f1c2a5e-0000-4000-8000-000000000002',
                '/events/abc', '/notifications', '/support/12', '/profile/publicity', '/achievements', '/documents/x'):
        r = client.get(url)
        assert r.status_code == 200 and 'core.js' in r.text, url
    assert client.get('/api/nothing').status_code == 404       # адреса API не подменяются страницей
    assert client.get('/unknown-page').status_code == 404
