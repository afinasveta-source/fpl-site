from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from kabinet.auth.routes import admin, service, client_ip
from kabinet.auth.schemas import EmailInput, ImportUser, RoleChange, UserView
from kabinet.auth.service import user_view, require_admin

router = APIRouter(prefix='/users', tags=['users'])


@router.post('/import', response_model=UserView, status_code=201)
def import_user(body: ImportUser, actor=Depends(admin), auth=Depends(service)):
    with auth.db.transaction() as conn:
        require_admin(conn, actor)
        user = conn.execute('''INSERT INTO users(telegram_id,full_name,display_name)
VALUES (%s,%s,%s) ON CONFLICT (telegram_id) WHERE telegram_id IS NOT NULL DO NOTHING
RETURNING *''', (body.telegram_id, body.full_name, body.display_name)).fetchone()
        if not user:
            user = conn.execute('SELECT * FROM users WHERE telegram_id=%s', (body.telegram_id,)).fetchone()
        else:
            conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant')", (user['id'],))
            conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'import')", (actor['id'], user['id']))
        return user_view(conn, user)


@router.post('/{user_id}/activation', status_code=202)
def activate(user_id: UUID, body: EmailInput, request: Request, actor=Depends(admin), auth=Depends(service)):
    auth.throttle('activation', client_ip(request), body.email)
    auth.issue_token(user_id, 'set_password', body.email, actor=actor)
    with auth.db.transaction() as conn:
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'activation_requested')", (actor['id'], user_id))
    return {'message': 'Activation email requested'}


@router.post('/{user_id}/roles', response_model=UserView)
def change_role(user_id: UUID, body: RoleChange, actor=Depends(admin), auth=Depends(service)):
    with auth.db.transaction() as conn:
        # Serializes admin removals so two concurrent requests cannot remove the last two admins.
        conn.execute('SELECT pg_advisory_xact_lock(712436902)')
        require_admin(conn, actor)
        user = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
        if not user or user['account_status'] == 'deleted' or user['deleted_at']:
            raise HTTPException(404, 'User not found')
        if body.role.value == 'admin' and not body.enabled:
            active_admins = conn.execute("SELECT count(*) AS n FROM user_roles r JOIN users u ON u.id=r.user_id WHERE r.role='admin' AND u.account_status='active' AND u.deleted_at IS NULL").fetchone()['n']
            is_admin = conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role='admin'", (user_id,)).fetchone()
            if is_admin and user['account_status'] == 'active' and active_admins <= 1:
                raise HTTPException(409, 'Cannot remove the last active administrator')
        if body.enabled:
            conn.execute('INSERT INTO user_roles(user_id,role) VALUES (%s,%s) ON CONFLICT DO NOTHING', (user_id, body.role.value))
        else:
            conn.execute('DELETE FROM user_roles WHERE user_id=%s AND role=%s', (user_id, body.role.value))
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,after_data) VALUES (%s,'user',%s,'role_changed',jsonb_build_object('role',%s::text,'enabled',%s::boolean))", (actor['id'], user_id, body.role.value, body.enabled))
        return user_view(conn, user)
