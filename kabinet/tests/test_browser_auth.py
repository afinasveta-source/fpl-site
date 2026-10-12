from conftest import PASSWORD

ORIGIN={'Origin':'http://testserver'}

def browser_login(client):
    return client.post('/web-auth/login',headers=ORIGIN,json={'email':'person@example.com','password':PASSWORD})


def test_cookie_login_profile_reload_logout(client,seed):
    seed()
    response=browser_login(client)
    assert response.status_code==200 and 'access_token' not in response.text
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
    assert client.get('/web-auth/me').json()['email']=='person@example.com'
    assert client.get('/web-auth/me').status_code==200  # cookie survives another request
    assert client.post('/web-auth/logout',headers=ORIGIN).status_code==204
    assert client.get('/web-auth/me').status_code==401


def test_cookie_not_authorized_as_bearer(client,seed):
    seed(); browser_login(client)
    assert client.get('/auth/me').status_code==401


def test_browser_login_requires_exact_origin(client,seed):
    seed()
    for origin in (None,'https://attacker.example','http://testserver.evil.example'):
        headers={} if origin is None else {'Origin':origin}
        response=client.post('/web-auth/login',headers=headers,json={'email':'person@example.com','password':PASSWORD})
        assert response.status_code==403 and not response.cookies


def test_csrf_cannot_modify_profile_or_logout(client,seed):
    seed();browser_login(client)
    bad={'Origin':'https://attacker.example'}
    assert client.patch('/web-auth/profile',headers=bad,json={'display_name':'Changed'}).status_code==403
    assert client.post('/web-auth/logout',headers=bad).status_code==403
    assert client.get('/web-auth/me').status_code==200


def test_profile_change_persisted_and_only_self(client,app,seed):
    mine=seed();other=seed('other@example.com');browser_login(client)
    response=client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'  Новое имя  ','full_name':'  Анна Тестовая  ','city':'  Москва  '})
    assert response.status_code==200 and response.json()['display_name']=='Новое имя'
    assert client.get('/web-auth/me').json()['display_name']=='Новое имя'
    assert response.json()['full_name']=='Анна Тестовая'
    assert response.json()['city']=='Москва'
    client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Второе имя'})
    assert client.get('/web-auth/me').json()['city']=='Москва'
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT display_name FROM users WHERE id=%s',(other,)).fetchone()['display_name'] is None
        assert conn.execute('SELECT role FROM user_roles WHERE user_id=%s',(mine,)).fetchone()['role']=='participant'


def test_public_name_can_be_cleared_and_stays_cleared(client,seed):
    seed();browser_login(client)
    assert client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Nickname','full_name':'Full name'}).status_code==200
    response=client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'   '})
    assert response.status_code==200 and response.json()['display_name'] is None
    saved=client.get('/web-auth/me').json()
    assert saved['display_name'] is None and saved['full_name']=='Full name'


def test_partial_profile_and_empty_update(client,seed):
    seed();browser_login(client)
    assert client.patch('/web-auth/profile',headers=ORIGIN,json={'city':'City'}).status_code==200
    assert client.patch('/web-auth/profile',headers=ORIGIN,json={}).status_code==422


def test_cookie_session_revoked_after_password_reset(client,app,seed):
    uid=seed();browser_login(client)
    app.state.auth.issue_token(uid,'reset_password')
    token=app.state.mailer.messages[-1].token
    assert client.post('/auth/password/reset',json={'token':token,'password':'Changed-password-123!'}).status_code==204
    assert client.get('/web-auth/me').status_code==401


def test_relogin_revokes_previous_browser_session(client,app,seed):
    seed();browser_login(client)
    first=client.cookies.get('fpl_session')
    browser_login(client)
    second=client.cookies.get('fpl_session')
    assert first!=second
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException):app.state.auth.current_user(first)
    assert app.state.auth.current_user(second)['email']=='person@example.com'


def test_prod_cookie_security_attributes(client,app,seed):
    seed()
    # Attribute-only test on TEST DB. No connection to production is made.
    app.state.settings.environment='PROD'
    response=browser_login(client)
    cookie=response.headers['set-cookie']
    assert '__Host-fpl_session=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie and 'Domain=' not in cookie


def test_frontend_pages_and_local_assets(client):
    for url in ('/','/setup','/auth/set-password','/auth/reset-password'):
        response=client.get(url)
        assert response.status_code==200 and '<html lang="ru">' in response.text
        assert 'noindex,nofollow' in response.text and 'frame-ancestors' in response.headers['Content-Security-Policy']
        assert '{{ROOT}}' not in response.text and 'src="/assets/app.js"' in response.text
    for url in ('/assets/app.js','/assets/cabinet.css','/assets/kabinet.css','/assets/fonts.css'):
        assert client.get(url).status_code==200, url
    # шрифты — с сайта (тот же домен), а не из кабинета
    assert "url('/assets/fonts/manrope-cyrillic-400-normal.woff2')" in client.get('/assets/fonts.css').text
    config=client.get('/web-auth/config').json()
    assert config=={'is_test':True,'mail_delivery':False,'password_min_length':12,'setup_needed':True}


def test_browser_profile_requires_session(client):
    assert client.get('/web-auth/me').status_code==401
    assert client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Name'}).status_code==401


def test_profile_rejects_privilege_and_identity_changes(client,seed):
    seed(); browser_login(client)
    for extra in ({'roles':['admin']},{'email':'other@example.com'},{'public_profile':True},{'id':'123'}):
        assert client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Name',**extra}).status_code==422
    assert client.get('/web-auth/me').json()['display_name'] is None


def test_profile_optional_clear_and_limits(client,seed):
    seed(); browser_login(client)
    assert client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Имя','city':'Город'}).status_code==200
    response=client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Имя','city':'   ','full_name':''})
    assert response.status_code==200 and response.json()['city'] is None and response.json()['full_name'] is None
    for field, length in [('display_name',101),('full_name',201),('city',121)]:
        assert client.patch('/web-auth/profile',headers=ORIGIN,json={'display_name':'Имя',field:'x'*length}).status_code==422
