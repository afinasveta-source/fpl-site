"""Команды сервера кабинета.

bootstrap-admin --email … — первый администратор (запасной путь к /web-auth/setup). Публичной регистрации администраторов нет.
sync-late — сверка идущих Игр: опоздавших в конкурсе — вне конкурса (таймер fpl-kabinet-sync, каждые 10 минут).
"""
import argparse
from getpass import getpass
from pydantic import TypeAdapter, EmailStr
from kabinet.config import Settings
from kabinet.db import Database
from kabinet.auth.security import password_hasher


def sync_late(settings):
    from datetime import datetime, timezone
    from kabinet.participation.game import sync_event
    db = Database(settings)
    with db.transaction() as conn:
        events = [r['id'] for r in conn.execute("SELECT id FROM events WHERE status='active'")]
    moved = 0
    for event_id in events:
        with db.transaction() as conn:   # по Игре — своя транзакция: сбой одной не откатывает другие
            moved += sync_event(conn, event_id, datetime.now(timezone.utc))
    print(f'sync-late: games {len(events)}, moved outside {moved}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['bootstrap-admin', 'sync-late'])
    parser.add_argument('--email')
    args = parser.parse_args()
    settings = Settings()
    if args.command == 'sync-late':
        sync_late(settings)
        return
    if not args.email:
        parser.error('--email is required for bootstrap-admin')
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    password = getpass('Admin password (at least 12 characters): ')
    if not 12 <= len(password) <= 128 or password != getpass('Repeat password: '):
        raise SystemExit('Password length/confirmation invalid')
    with Database(settings).transaction() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(712436902)')
        if conn.execute("SELECT 1 FROM user_roles WHERE role='admin'").fetchone():
            raise SystemExit('An administrator already exists. Use the protected role API.')
        user = conn.execute("INSERT INTO users(email,password_hash,email_verified_at,account_status) VALUES (%s,%s,now(),'active') RETURNING id", (email, password_hasher.hash(password))).fetchone()
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'admin')", (user['id'],))
        conn.execute("INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action) VALUES (%s,'user',%s,'admin_bootstrap')", (user['id'], user['id']))
    print('Administrator created. Operator is responsible for verifying this mailbox before bootstrap.')


if __name__ == '__main__':
    main()
