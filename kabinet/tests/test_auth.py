from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from kabinet.auth.security import token_hash
from conftest import PASSWORD


def login(client, email='person@example.com', password=PASSWORD):
    return client.post('/auth/login', json={'email':email, 'password':password})


def headers(response):
    return {'Authorization':'Bearer ' + response.json()['access_token']}


def imported(client, admin_headers):
    response = client.post('/users/import', headers=admin_headers,
                           json={'telegram_id':12345,'full_name':'Legacy user'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def activation(client, app, admin_headers, user_id, email='legacy@example.com'):
    response = client.post(f'/users/{user_id}/activation', headers=admin_headers, json={'email':email})
    assert response.status_code == 202, response.text
    assert 'token' not in response.text
    return app.state.mailer.messages[-1].token


def test_ready_and_openapi(client):
    assert client.get('/ready').json() == {'status':'ready','schema':'012'}
    assert client.get('/health').status_code == 200
    assert client.get('/openapi.json').status_code == 200


def test_import_nullable_idempotent(client, app, admin_headers):
    uid = imported(client, admin_headers)
    again = imported(client, admin_headers)
    assert uid == again
    with app.state.db.transaction() as conn:
        row = conn.execute('SELECT * FROM users WHERE id=%s',(uid,)).fetchone()
        assert row['email'] is None and row['password_hash'] is None and row['account_status']=='imported'
    assert client.get('/auth/me', headers={'Authorization':'Bearer imported-user'}).status_code == 401


def test_activation_login_hash_and_roles(client, app, admin_headers):
    uid = imported(client, admin_headers)
    token = activation(client, app, admin_headers, uid)
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT token_hash FROM auth_tokens WHERE user_id=%s',(uid,)).fetchone()['token_hash'] == token_hash(token)
        assert conn.execute('SELECT email FROM users WHERE id=%s',(uid,)).fetchone()['email'] is None
    response = client.post('/auth/password/set', json={'token':token,'password':PASSWORD})
    assert response.status_code == 204, response.text
    session = login(client,'LEGACY@EXAMPLE.COM')
    assert session.status_code == 200
    user = client.get('/auth/me',headers=headers(session)).json()
    assert user['id']==uid and user['roles']==['participant']
    with app.state.db.transaction() as conn:
        row = conn.execute('SELECT * FROM users WHERE id=%s',(uid,)).fetchone()
        assert row['password_hash'].startswith('$argon2id$') and row['password_hash'] != PASSWORD
        assert row['email_verified_at'] is not None
        saved = conn.execute('SELECT token_hash FROM auth_sessions WHERE user_id=%s',(uid,)).fetchone()['token_hash']
        assert saved == token_hash(session.json()['access_token'])
    assert client.post('/auth/password/set',json={'token':token,'password':PASSWORD}).status_code == 400


def test_wrong_missing_and_imported_credentials(client,seed):
    seed()
    seed('legacy@example.com',status='imported')
    results = [login(client,password='wrong'),login(client,'missing@example.com'),login(client,'legacy@example.com')]
    assert all(x.status_code==401 and x.json()=={'detail':'Invalid credentials'} for x in results)


def test_reset_generic_and_revoke_sessions(client,app,seed):
    uid=seed()
    s1,s2=login(client),login(client)
    known=client.post('/auth/password/reset-request',json={'email':'person@example.com'})
    unknown=client.post('/auth/password/reset-request',json={'email':'missing@example.com'})
    assert known.status_code == unknown.status_code == 202 and known.json()==unknown.json()
    assert len(app.state.mailer.messages)==1
    token=app.state.mailer.messages[-1].token
    new='New-password-123456!'
    assert client.post('/auth/password/reset',json={'token':token,'password':new}).status_code==204
    assert login(client).status_code==401
    assert login(client,password=new).status_code==200
    assert all(client.get('/auth/me',headers=headers(s)).status_code==401 for s in (s1,s2))
    assert client.post('/auth/password/reset',json={'token':token,'password':new}).status_code==400


def test_logout_and_expired_session(client,app,seed):
    seed()
    s=login(client)
    assert client.post('/auth/logout',headers=headers(s)).status_code==204
    assert client.get('/auth/me',headers=headers(s)).status_code==401
    s=login(client)
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second'")
    assert client.get('/auth/me',headers=headers(s)).status_code==401


def test_expired_token(client,app,seed):
    uid=seed()
    app.state.auth.issue_token(uid,'reset_password')
    token=app.state.mailer.messages[-1].token
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE auth_tokens SET expires_at=now()-interval '1 second'")
    assert client.post('/auth/password/reset',json={'token':token,'password':PASSWORD}).status_code==400
    assert login(client).status_code==200


def test_reissue_invalidates_old_token(client,app,seed):
    uid=seed()
    app.state.auth.issue_token(uid,'reset_password')
    first=app.state.mailer.messages[-1].token
    app.state.auth.issue_token(uid,'reset_password')
    second=app.state.mailer.messages[-1].token
    assert client.post('/auth/password/reset',json={'token':first,'password':PASSWORD}).status_code==400
    assert client.post('/auth/password/reset',json={'token':second,'password':PASSWORD}).status_code==204


def test_wrong_token_purpose(client,app,admin_headers):
    uid=imported(client,admin_headers)
    token=activation(client,app,admin_headers,uid)
    assert client.post('/auth/password/reset',json={'token':token,'password':PASSWORD}).status_code==400
    assert client.post('/auth/password/set',json={'token':token,'password':PASSWORD}).status_code==204


def test_email_collision_rolls_back_activation(client,app,seed,admin_headers):
    uid=imported(client,admin_headers)
    token=activation(client,app,admin_headers,uid)
    seed('legacy@example.com')
    assert client.post('/auth/password/set',json={'token':token,'password':PASSWORD}).status_code==409
    with app.state.db.transaction() as conn:
        user=conn.execute('SELECT * FROM users WHERE id=%s',(uid,)).fetchone()
        assert user['account_status']=='imported' and user['password_hash'] is None and user['email'] is None
        assert conn.execute('SELECT used_at FROM auth_tokens WHERE user_id=%s',(uid,)).fetchone()['used_at'] is None


def test_prelinked_email_cannot_be_changed(client,app,seed,admin_headers):
    uid=seed('bound@example.com',status='imported')
    assert client.post(f'/users/{uid}/activation',headers=admin_headers,json={'email':'other@example.com'}).status_code==409
    assert not app.state.mailer.messages


def test_concurrent_token_consumption_once(client,app,seed):
    uid=seed()
    app.state.auth.issue_token(uid,'reset_password')
    token=app.state.mailer.messages[-1].token
    def consume(_):
        with TestClient(app) as c:
            return c.post('/auth/password/reset',json={'token':token,'password':PASSWORD}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume,range(2)))==[204,400]


def test_role_protection_and_live_revocation(client,app,seed,admin_headers):
    uid=seed()
    s=login(client)
    assert client.post('/users/import',json={'telegram_id':123456}).status_code==401
    assert client.post('/users/import',headers=headers(s),json={'telegram_id':123456}).status_code==403
    assert client.post(f'/users/{uid}/roles',headers=admin_headers,json={'role':'judge','enabled':True}).status_code==200
    assert client.get('/auth/me',headers=headers(s)).json()['roles']==['judge','participant']
    assert client.post(f'/users/{uid}/roles',headers=admin_headers,json={'role':'owner','enabled':True}).status_code==422
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE users SET account_status='suspended' WHERE id=%s",(uid,))
    assert client.get('/auth/me',headers=headers(s)).status_code==401
    assert login(client).status_code==401


def test_last_admin_protection(client,admin_headers):
    uid=client.get('/auth/me',headers=admin_headers).json()['id']
    assert client.post(f'/users/{uid}/roles',headers=admin_headers,json={'role':'admin','enabled':False}).status_code==409


def test_role_revoke_applies_to_old_session(client,seed,admin_headers):
    uid=seed('second-admin@example.com',roles=('admin',))
    s=login(client,'second-admin@example.com')
    assert client.post(f'/users/{uid}/roles',headers=admin_headers,json={'role':'admin','enabled':False}).status_code==200
    assert client.post('/users/import',headers=headers(s),json={'telegram_id':123456}).status_code==403


def test_validation_never_echoes_password(client):
    secret='tiny-s'
    response=client.post('/auth/password/set',json={'token':'token-value-that-is-long-enough','password':secret})
    assert response.status_code==422 and secret not in response.text
    assert client.post('/auth/login',json={'email':'bad-email','password':PASSWORD}).status_code==422


def test_rate_limit_persisted_on_failed_login(client,app):
    app.state.auth.settings.login_limit=2
    assert login(client).status_code==401
    assert login(client).status_code==401
    third=login(client)
    assert third.status_code==429 and 'Retry-After' in third.headers
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT max(attempts) AS n FROM auth_rate_limits').fetchone()['n']==3


def test_delivery_failure_invalidates_token(client,app,seed):
    seed()
    class BrokenMailer:
        def send(self,mail):
            raise OSError('TEST failure')
    app.state.auth.mailer=BrokenMailer()
    assert client.post('/auth/password/reset-request',json={'email':'person@example.com'}).status_code==202
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT used_at FROM auth_tokens').fetchone()['used_at'] is not None


def test_deleted_user_and_email_unverified_block_login(client,app,seed):
    uid=seed()
    s=login(client)
    with app.state.db.transaction() as conn:
        conn.execute('UPDATE users SET deleted_at=now() WHERE id=%s',(uid,))
    assert client.get('/auth/me',headers=headers(s)).status_code==401
    assert login(client).status_code==401
    with app.state.db.transaction() as conn:
        conn.execute('UPDATE users SET deleted_at=NULL,email_verified_at=NULL WHERE id=%s',(uid,))
    assert login(client).status_code==401


def test_malformed_stored_hash_does_not_authorize(client,app,seed):
    uid=seed()
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE users SET password_hash='legacy-invalid' WHERE id=%s",(uid,))
    assert login(client).status_code==401


def test_cache_headers(client):
    response=client.get('/auth/me')
    assert response.headers['Cache-Control']=='no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'


def test_reset_inactive_is_generic_and_sends_no_mail(client,app,seed):
    seed('legacy@example.com',status='imported')
    response=client.post('/auth/password/reset-request',json={'email':'legacy@example.com'})
    assert response.status_code==202 and not app.state.mailer.messages


def test_activation_cannot_claim_existing_email(client,app,seed,admin_headers):
    seed('existing@example.com')
    uid=imported(client,admin_headers)
    response=client.post(f'/users/{uid}/activation',headers=admin_headers,json={'email':'existing@example.com'})
    assert response.status_code==409 and not app.state.mailer.messages


def test_expired_rate_window_resets(client,app):
    app.state.auth.settings.login_limit=1
    assert login(client).status_code==401
    assert login(client).status_code==429
    with app.state.db.transaction() as conn:
        conn.execute("UPDATE auth_rate_limits SET window_start=now()-interval '1 hour'")
    assert login(client).status_code==401


def test_invalid_reset_token_does_not_change_password(client,seed):
    seed()
    assert client.post('/auth/password/reset',json={'token':'invalid-token-with-at-least-20-chars','password':'Changed-password-123!'}).status_code==400
    assert login(client).status_code==200


def test_readiness_missing_revision(client,app):
    with app.state.db.transaction() as conn:
        old=conn.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
        conn.execute("UPDATE alembic_version SET version_num='003'")
    try:
        assert client.get('/ready').status_code==503
    finally:
        with app.state.db.transaction() as conn:
            conn.execute('UPDATE alembic_version SET version_num=%s',(old,))


def test_import_huge_telegram_id_is_422(client, admin_headers):
    """Telegram ID больше bigint — понятная ошибка, не сбой сервера (Codex, 13.10)."""
    r = client.post('/users/import', headers=admin_headers, json={'telegram_id': 10 ** 100, 'full_name': 'Тест'})
    assert r.status_code == 422
