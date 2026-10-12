#!/usr/bin/env python3
"""Проверка миграции 005 (кабинет участника): черновик и сданные версии работы, переход опоздавшего,
публичность «соцсети», номер обращения.

Отдельная база fpl_005_test на локальном PostgreSQL (роль из /etc/fpl-db.env), данные выдуманные.
Запуск: python3 server/db/tests/test_005.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.dirname(HERE)
TEST_DB = 'fpl_005_test'
env = dict(l.rstrip('\n').split('=', 1) for l in open('/etc/fpl-db.env') if '=' in l)
DSN = 'postgresql://%s:%s@127.0.0.1:5432/%s' % (env['FPL_DB_USER'], env['FPL_DB_PASSWORD'], TEST_DB)

import psycopg

failures = []
FILES = ('001_initial_mvp_schema.sql', '002_auth.sql', '003_league_rules.sql', '004_rewards_groups.sql',
         '005_participant_cabinet.sql')


def check(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        failures.append(msg)


def su(sql):
    subprocess.run(['su', 'postgres', '-c', 'psql -v ON_ERROR_STOP=1 -qc "%s"' % sql], check=True)


def fresh_db(files=FILES):
    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    su("CREATE DATABASE %s OWNER %s ENCODING 'UTF8' TEMPLATE template0" % (TEST_DB, env['FPL_DB_USER']))
    for f in files:
        body = ''.join(l for l in open(os.path.join(DB_DIR, 'schema', f)) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        with psycopg.connect(DSN) as c:
            c.execute(body)


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


def work(c):
    """Игра, участник, тур, задание, вариант, выданное задание и работа."""
    u = one(c, "INSERT INTO users(full_name) VALUES ('Тест') RETURNING id")
    e = one(c, "INSERT INTO events(event_type,status,title) VALUES ('ranked_game','active','Игра 99') RETURNING id")
    p = one(c, "INSERT INTO event_participants(event_id,user_id,registration_status) VALUES (%s,%s,'participating') RETURNING id", (e, u))
    r = one(c, "INSERT INTO rounds(event_id,round_no,title,status) VALUES (%s,1,'Тур','open') RETURNING id", (e,))
    a = one(c, "INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work','Работа') RETURNING id", (e, r))
    v = one(c, "INSERT INTO assignment_variants(assignment_id,code) VALUES (%s,'all') RETURNING id", (a,))
    pa = one(c, """INSERT INTO participant_assignments(event_id,event_participant_id,assignment_id,assignment_variant_id)
VALUES (%s,%s,%s,%s) RETURNING id""", (e, p, a, v))
    s = one(c, "INSERT INTO submissions(event_participant_id,participant_assignment_id) VALUES (%s,%s) RETURNING id", (p, pa))
    m = one(c, "INSERT INTO media_files(uploaded_by,storage_key) VALUES (%s,'orig/x.jpg') RETURNING id", (u,))
    return dict(user=u, event=e, part=p, sub=s, media=m)


def main():
    # Миграция ложится на базу с данными 004 (а не только на пустую).
    fresh_db(FILES[:4])
    with psycopg.connect(DSN) as c:
        c.execute("INSERT INTO users(full_name) VALUES ('До миграции')")
        u = one(c, "SELECT id FROM users LIMIT 1")
        c.execute("INSERT INTO support_threads(user_id,subject) VALUES (%s,'старое')", (u,))
        body = ''.join(l for l in open(os.path.join(DB_DIR, 'schema', FILES[4])) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        c.execute(body)
        check(one(c, "SELECT thread_no FROM support_threads") == 1, 'старое обращение получило номер 1')

    fresh_db()
    with psycopg.connect(DSN) as c:
        w = work(c)
        print('Опоздавший — вне конкурса автоматически')
        check(not fails(c, """UPDATE event_participants SET competition_status='diploma_only', elimination_reason='late',
out_of_competition_at=now(), out_of_competition_source='auto' WHERE id=%s""", (w['part'],)), "источник 'auto' разрешён")
        check(fails(c, "UPDATE event_participants SET out_of_competition_source='robot' WHERE id=%s", (w['part'],), 'lr_ep_out_source'),
              'неизвестный источник отклонён')

        print('Публичность')
        check(fails(c, "UPDATE users SET public_social=true, deleted_at=now() WHERE id=%s", (w['user'],), 'lr_users_deleted_not_public'),
              'удалённый не может остаться в соцсетях')
        check(not fails(c, "UPDATE users SET public_social=true WHERE id=%s", (w['user'],)), 'соцсети можно включить')

        print('Обращения')
        n1 = one(c, "INSERT INTO support_threads(user_id,subject) VALUES (%s,'a') RETURNING thread_no", (w['user'],))
        n2 = one(c, "INSERT INTO support_threads(user_id,subject) VALUES (%s,'b') RETURNING thread_no", (w['user'],))
        check(n2 == n1 + 1, 'номера обращений идут подряд')

        print('Черновик и версии')
        d1 = one(c, "INSERT INTO submission_versions(submission_id,version_no,payload) VALUES (%s,1,'{}') RETURNING id", (w['sub'],))
        check(fails(c, "INSERT INTO submission_versions(submission_id,version_no) VALUES (%s,2)", (w['sub'],), 'lr_sv_one_draft'),
              'второй черновик не создаётся')
        check(fails(c, "UPDATE submissions SET latest_version_id=%s WHERE id=%s", (d1, w['sub']), 'only to submitted'),
              'работа не указывает на черновик')
        c.execute("INSERT INTO submission_version_media VALUES (%s,%s,'photo',0)", (d1, w['media']))
        check(not fails(c, "DELETE FROM submission_version_media WHERE submission_version_id=%s", (d1,)), 'фото черновика можно убрать')
        c.execute("INSERT INTO submission_version_media VALUES (%s,%s,'photo',0)", (d1, w['media']))
        check(fails(c, "UPDATE submission_versions SET submitted_at=now() WHERE id=%s", (d1,), 'lr_sv_final_matches'),
              'сдача без отметки is_final_submit отклонена')
        c.execute("UPDATE submission_versions SET submitted_at=now(), is_final_submit=true WHERE id=%s", (d1,))
        check(not fails(c, "UPDATE submissions SET latest_version_id=%s, diploma_version_id=%s WHERE id=%s", (d1, d1, w['sub'])),
              'работа указывает на сданную версию')
        check(fails(c, "UPDATE submission_versions SET payload='{\"link\":\"x\"}' WHERE id=%s", (d1,), 'cannot change'),
              'сданная версия не меняется')
        check(fails(c, "UPDATE submission_versions SET submitted_at=now()-interval '1 day' WHERE id=%s", (d1,), 'cannot change'),
              'время сдачи не переписывается')
        check(fails(c, "DELETE FROM submission_version_media WHERE submission_version_id=%s", (d1,), 'cannot change'),
              'фото сданной версии не удаляются')
        m2 = one(c, "INSERT INTO media_files(uploaded_by,storage_key) VALUES (%s,'orig/y.jpg') RETURNING id", (w['user'],))
        check(fails(c, "INSERT INTO submission_version_media VALUES (%s,%s,'photo',1)", (d1, m2), 'cannot change'),
              'к сданной версии не добавить фото')
        check(fails(c, "DELETE FROM submission_versions WHERE id=%s", (d1,), 'cannot be deleted'), 'сданная версия не удаляется')
        d2 = one(c, "INSERT INTO submission_versions(submission_id,version_no) VALUES (%s,2) RETURNING id", (w['sub'],))
        check(not fails(c, "DELETE FROM submission_versions WHERE id=%s", (d2,)), 'черновик удаляется')

    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    print('Итог: %s' % ('ошибок нет' if not failures else '%d ошибок' % len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
