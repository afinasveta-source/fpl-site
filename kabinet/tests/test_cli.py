import sys
import pytest
from kabinet import cli


def test_bootstrap_admin_and_refuse_second(app,client,monkeypatch):
    monkeypatch.setenv('FPL_ENVIRONMENT','TEST')
    monkeypatch.setenv('FPL_DATABASE_DSN',app.state.db.dsn)
    monkeypatch.setattr(sys,'argv',['fpl','bootstrap-admin','--email','owner@example.com'])
    monkeypatch.setattr(cli,'getpass',lambda prompt:'Operator-password-123!')
    cli.main()
    session=client.post('/auth/login',json={'email':'owner@example.com','password':'Operator-password-123!'})
    assert session.status_code==200
    profile=client.get('/auth/me',headers={'Authorization':'Bearer '+session.json()['access_token']})
    assert profile.json()['roles']==['admin']
    with pytest.raises(SystemExit,match='already exists'):
        cli.main()
    with app.state.db.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM users').fetchone()['n']==1


def test_sync_late_command(app, monkeypatch, capsys):
    monkeypatch.setenv('FPL_ENVIRONMENT', 'TEST')
    monkeypatch.setenv('FPL_DATABASE_DSN', app.state.db.dsn)
    monkeypatch.setattr(sys, 'argv', ['fpl', 'sync-late'])
    cli.main()
    assert 'sync-late: games' in capsys.readouterr().out
