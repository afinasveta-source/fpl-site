"""Команды сервера кабинета.

bootstrap-admin --email … — первый администратор (запасной путь к /web-auth/setup). Публичной регистрации администраторов нет.
sync-late — сверка идущих Игр: опоздавших в конкурсе — вне конкурса (таймер fpl-kabinet-sync, каждые 10 минут).
rebuild-media — после восстановления из копии: пересоздать копии для показа (view/, thumb/) из оригиналов (orig/),
  убрать недописанные временные файлы. В бакете хранятся только оригиналы.
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
    moved, failed = 0, 0
    for event_id in events:
        try:
            with db.transaction() as conn:   # по Игре — своя транзакция: сбой одной не мешает остальным
                moved += sync_event(conn, event_id, datetime.now(timezone.utc))
        except Exception as exc:  # noqa: BLE001 — сверка остальных Игр продолжается, ошибка видна в журнале
            failed += 1
            print(f'sync-late: game {event_id} failed: {type(exc).__name__}: {exc}'[:300])
    try:
        from kabinet.org.documents import notify_due_rules
        with db.transaction() as conn:
            notified = notify_due_rules(conn, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        failed += 1
        notified = 0
        print(f'sync-late: rules notice failed: {type(exc).__name__}: {exc}'[:300])
    print(f'sync-late: games {len(events)}, moved outside {moved}, rules notices {notified}, failed {failed}')
    if failed:
        raise SystemExit(1)


def rebuild_media(settings):
    import time
    from pathlib import Path
    from kabinet.participation.media import MediaError, MediaStore
    store = MediaStore(settings.media_dir, 0)
    root = Path(settings.media_dir)
    stale = 0
    for tmp in root.glob('*/*/tmp*'):
        if tmp.is_file() and time.time() - tmp.stat().st_mtime > 3600:
            tmp.unlink()
            stale += 1
    with Database(settings).transaction() as conn:
        rows = conn.execute('''SELECT DISTINCT storage_key, optimized_storage_key, thumbnail_storage_key FROM media_files
WHERE storage_key IS NOT NULL''').fetchall()
    made = missing = failed = 0
    for r in rows:
        orig = store.path(r['storage_key'])
        need = [k for k in (r['optimized_storage_key'], r['thumbnail_storage_key']) if k and not store.path(k).exists()]
        if not need:
            continue
        if not orig.exists():
            missing += 1
            continue
        try:
            store.save_image(orig.read_bytes())
            made += 1
        except MediaError as exc:
            failed += 1
            print(f'rebuild-media: {r["storage_key"]}: {exc.code}')
    print(f'rebuild-media: photos {len(rows)}, rebuilt {made}, original missing {missing}, failed {failed}, stale tmp removed {stale}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['bootstrap-admin', 'sync-late', 'rebuild-media'])
    parser.add_argument('--email')
    args = parser.parse_args()
    settings = Settings()
    if args.command == 'sync-late':
        sync_late(settings)
        return
    if args.command == 'rebuild-media':
        rebuild_media(settings)
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
