#!/usr/bin/env python3
"""Проверка миграции 006 (кабинет организатора): ссылка-приглашение 'invite' без email.

Отдельная база fpl_006_test на локальном PostgreSQL (роль из /etc/fpl-db.env), данные выдуманные.
Запуск: python3 server/db/tests/test_006.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.dirname(HERE)
TEST_DB = 'fpl_006_test'
env = dict(l.rstrip('\n').split('=', 1) for l in open('/etc/fpl-db.env') if '=' in l)
DSN = 'postgresql://%s:%s@127.0.0.1:5432/%s' % (env['FPL_DB_USER'], env['FPL_DB_PASSWORD'], TEST_DB)

import psycopg

failures = []
FILES = ('001_initial_mvp_schema.sql', '002_auth.sql', '003_league_rules.sql', '004_rewards_groups.sql',
         '005_participant_cabinet.sql', '006_organizer_cabinet.sql', '007_judging_scale.sql')


def check(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        failures.append(msg)


def su(sql):
    subprocess.run(['su', 'postgres', '-c', 'psql -v ON_ERROR_STOP=1 -qc "%s"' % sql], check=True)


def apply(c, f):
    c.execute(''.join(l for l in open(os.path.join(DB_DIR, 'schema', f)) if l.strip() not in ('BEGIN;', 'COMMIT;')))


def fresh_db(files=FILES):
    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    su("CREATE DATABASE %s OWNER %s ENCODING 'UTF8' TEMPLATE template0" % (TEST_DB, env['FPL_DB_USER']))
    for f in files:
        with psycopg.connect(DSN) as c:
            apply(c, f)


def fails(c, sql, args=(), contains=''):
    c.execute('SAVEPOINT sp')
    try:
        c.execute(sql, args)
    except psycopg.Error as e:
        c.execute('ROLLBACK TO SAVEPOINT sp')
        return contains.lower() in str(e).lower()
    c.execute('RELEASE SAVEPOINT sp')
    return False


def one(c, sql, args=()):
    return c.execute(sql, args).fetchone()[0]


def main():
    # Миграция ложится на базу 005 с данными (код установки пароля уже выдан).
    fresh_db(FILES[:5])
    with psycopg.connect(DSN) as c:
        u = one(c, "INSERT INTO users(full_name) VALUES ('До миграции') RETURNING id")
        c.execute("""INSERT INTO auth_tokens(user_id,token_hash,token_type,target_email,expires_at)
VALUES (%s,'h-old','set_password','old@example.com',now()+interval '1 hour')""", (u,))
        apply(c, FILES[5])
        check(one(c, "SELECT count(*) FROM auth_tokens") == 1, 'выданный код установки пароля сохранился')

    fresh_db()
    with psycopg.connect(DSN) as c:
        u = one(c, "INSERT INTO users(full_name) VALUES ('Участница из бота') RETURNING id")
        print('Ссылка-приглашение')
        check(not fails(c, """INSERT INTO auth_tokens(user_id,token_hash,token_type,expires_at)
VALUES (%s,'h2','invite',now()+interval '7 days')""", (u,)), "код 'invite' без email принимается")
        check(fails(c, """INSERT INTO auth_tokens(user_id,token_hash,token_type,expires_at)
VALUES (%s,'h3','set_password',now()+interval '1 hour')""", (u,), 'ck_auth_set_password_email'),
              'код установки пароля без email по-прежнему отклоняется')
        check(fails(c, """INSERT INTO auth_tokens(user_id,token_hash,token_type,expires_at)
VALUES (%s,'h4','magic',now()+interval '1 hour')""", (u,), 'auth_tokens_token_type_check'), 'неизвестный вид кода отклонён')
        check(not fails(c, """INSERT INTO auth_tokens(user_id,token_hash,token_type,target_email,expires_at)
VALUES (%s,'h5','reset_password','a@example.com',now()+interval '1 hour')""", (u,)), 'код сброса пароля работает как раньше')

        print('Пожелания с сайта')
        check(not fails(c, "INSERT INTO feedback_messages(body) VALUES ('Сделайте тур про зиму')"), 'анонимное пожелание сохраняется')
        check(fails(c, "INSERT INTO feedback_messages(body) VALUES ('   ')", (), 'check'), 'пустое пожелание отклонено')
        check(fails(c, "INSERT INTO feedback_messages(body) VALUES (repeat('a', 2001))", (), 'check'), 'больше 2000 символов — отклонено')
        check(fails(c, "INSERT INTO feedback_messages(body,status) VALUES ('x','read')", (), 'check'), 'прочитано — только с временем прочтения')
        cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='feedback_messages'")}
        check(not any(k in cols for k in ('ip', 'ip_address', 'user_agent', 'user_id')), 'адреса и браузера в таблице нет')

    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    print('Итог: %s' % ('ошибок нет' if not failures else '%d ошибок' % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
