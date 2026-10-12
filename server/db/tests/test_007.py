#!/usr/bin/env python3
"""Проверка миграции 007 (судейство в кабинете): названия способов расчёта для шкалы 1–100.

Отдельная база fpl_007_test на локальном PostgreSQL (роль из /etc/fpl-db.env), данные выдуманные.
Запуск: python3 server/db/tests/test_007.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.dirname(HERE)
TEST_DB = 'fpl_007_test'
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


def rule(c):
    return one(c, """SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='lr_stream_scoring_method'""")


def main():
    # Миграция ложится на базу 006.
    fresh_db(FILES[:6])
    with psycopg.connect(DSN) as c:
        before = rule(c)
        check('win_share_100_v1' not in before, 'до миграции нового названия нет')
        apply(c, FILES[6])
        after = rule(c)
        for name in ('win_share_v1', 'bt_v1', 'criteria_mean_v1', 'win_share_100_v1', 'criteria_mean_100_v1'):
            check(name in after, 'способ %s разрешён' % name)
        check('scoring_method IS NULL' in after, 'пустой способ по-прежнему разрешён')
        check(one(c, "SELECT count(*) FROM pg_constraint WHERE conname='lr_stream_scoring_method'") == 1, 'правило одно')
    fresh_db()
    with psycopg.connect(DSN) as c:
        check('criteria_mean_100_v1' in rule(c), 'с нуля 001→007 — новое правило на месте')
    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    print('Итог: %s' % ('ошибок нет' if not failures else '%d ошибок' % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
