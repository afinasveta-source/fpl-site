"""A dependency snapshot must not authorize a write after access changes."""
import pytest
from fastapi import HTTPException
from kabinet.auth.schemas import ImportUser, RoleChange
from kabinet.users.routes import import_user, change_role


@pytest.mark.parametrize('change', ['suspended', 'role_removed'])
def test_stale_administrator_cannot_import_activate_or_change_roles(app, seed, change):
    actor={'id':seed('admin@example.com',('admin',)), 'roles':['admin']}
    target=seed('legacy@example.com', status='imported')
    with app.state.db.transaction() as c:
        if change=='suspended':
            c.execute("UPDATE users SET account_status='suspended' WHERE id=%s",(actor['id'],))
        else:
            c.execute("DELETE FROM user_roles WHERE user_id=%s AND role='admin'",(actor['id'],))
    calls=[
        lambda:import_user(ImportUser(telegram_id=222),actor,app.state.auth),
        lambda:app.state.auth.issue_token(target,'set_password','target@example.com',actor=actor),
        lambda:change_role(target,RoleChange(role='judge',enabled=True),actor,app.state.auth),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc: call()
        assert exc.value.status_code==403
    with app.state.db.transaction() as c:
        assert c.execute('SELECT 1 FROM users WHERE telegram_id=222').fetchone() is None
        assert c.execute('SELECT count(*) AS n FROM auth_tokens').fetchone()['n']==0
        assert c.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role='judge'",(target,)).fetchone() is None
