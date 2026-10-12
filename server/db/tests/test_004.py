#!/usr/bin/env python3
"""Проверка миграции 004 (скидки, группы, уведомления, призы, материал от организатора, «судья не участник»).

Отдельная база fpl_004_test на локальном PostgreSQL (роль из /etc/fpl-db.env), данные выдуманные.
Запуск: python3 server/db/tests/test_004.py
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.dirname(HERE)
TEST_DB = 'fpl_004_test'
env = dict(l.rstrip('\n').split('=', 1) for l in open('/etc/fpl-db.env') if '=' in l)
DSN = 'postgresql://%s:%s@127.0.0.1:5432/%s' % (env['FPL_DB_USER'], env['FPL_DB_PASSWORD'], TEST_DB)

import psycopg

failures = []


def check(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        failures.append(msg)


def su(sql):
    subprocess.run(['su', 'postgres', '-c', 'psql -v ON_ERROR_STOP=1 -qc "%s"' % sql], check=True)


def fresh_db():
    su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    su("CREATE DATABASE %s OWNER %s ENCODING 'UTF8' TEMPLATE template0" % (TEST_DB, env['FPL_DB_USER']))
    for f in ('001_initial_mvp_schema.sql', '002_auth.sql', '003_league_rules.sql', '004_rewards_groups.sql'):
        body = ''.join(l for l in open(os.path.join(DB_DIR, 'schema', f)) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        with psycopg.connect(DSN) as c:
            c.execute(body)


def fails(c, sql, args=(), contains=''):
    """True, если запрос отклонён базой (и текст ошибки содержит contains)."""
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
    fresh_db()
    with psycopg.connect(DSN) as c:
        print('Набор уведомлений')
        check(one(c, 'SELECT count(*) FROM notification_rules WHERE event_id IS NULL') == 28, '28 правил в общем наборе')
        check(one(c, "SELECT template_text FROM notification_rules WHERE rule_key='discount'").startswith('Спасибо за {Игра}'),
              'правило скидки с текстом')
        check(one(c, "SELECT channels FROM notification_rules WHERE rule_key='mateSent'") == ['in_app'],
              '«партнёр сдал» — только кабинет')

        season = one(c, "INSERT INTO seasons (name) VALUES ('Сезон 1') RETURNING id")
        ev = one(c, "INSERT INTO events (season_id, event_type, title) VALUES (%s,'ranked_game','Игра 01') RETURNING id", (season,))
        ev2 = one(c, "INSERT INTO events (season_id, event_type, title) VALUES (%s,'ranked_game','Игра 02') RETURNING id", (season,))
        users = [one(c, "INSERT INTO users (full_name, display_name) VALUES (%s,%s) RETURNING id", ('Участник %d' % i, 'У%d' % i))
                 for i in range(9)]
        parts = [one(c, "INSERT INTO event_participants (event_id, user_id) VALUES (%s,%s) RETURNING id", (ev, u))
                 for u in users[:7]]
        other_part = one(c, "INSERT INTO event_participants (event_id, user_id) VALUES (%s,%s) RETURNING id", (ev2, users[7]))
        rnd = one(c, "INSERT INTO rounds (event_id, round_no, title) VALUES (%s,5,'Финал') RETURNING id", (ev,))

        print('Призы')
        c.execute("INSERT INTO event_prizes (event_id, sort_order, criterion, prize) VALUES (%s,1,'1 место в каждой лиге','Главный приз')", (ev,))
        check(fails(c, "INSERT INTO event_prizes (event_id, criterion, prize) VALUES (%s,' ','x')", (ev,)), 'пустая строка приза не принимается')

        print('Скидки')
        check(one(c, 'SELECT reward_multi_mode FROM events WHERE id=%s', (ev,)) == 'all', 'по умолчанию — все подходящие скидки')
        r_all = one(c, """INSERT INTO reward_rules (event_id, sort_order, audience, discount_type, discount_value, code_source)
                          VALUES (%s,1,'finished','percent',10,'generate_push') RETURNING id""", (ev,))
        r_top = one(c, """INSERT INTO reward_rules (event_id, sort_order, audience, discount_type, discount_value, code_source)
                          VALUES (%s,2,'place_1_3','percent',20,'uploaded') RETURNING id""", (ev,))
        check(fails(c, """INSERT INTO reward_rules (event_id, audience, discount_type, discount_value, code_source)
                          VALUES (%s,'league','percent',15,'uploaded')""", (ev,)), 'правило «лига» без лиги — нельзя')
        check(fails(c, """INSERT INTO reward_rules (event_id, audience, league, discount_type, discount_value, code_source)
                          VALUES (%s,'finished','gold','percent',15,'uploaded')""", (ev,)), 'лига у правила «все» — нельзя')
        check(fails(c, """INSERT INTO reward_rules (event_id, audience, discount_type, discount_value, code_source)
                          VALUES (%s,'finished','percent',120,'uploaded')""", (ev,)), 'скидка больше 100% — нельзя')
        check(not fails(c, """INSERT INTO reward_rules (event_id, audience, league, discount_type, discount_value, code_source)
                          VALUES (%s,'league','gold','fixed',500,'uploaded')""", (ev,)), 'скидка 500 ₽ лиге Gold — можно')

        gen = one(c, "INSERT INTO reward_codes (reward_rule_id, code, origin, shop_sync_status) VALUES (%s,'FPL01-K7Q2','generated','pending') RETURNING id", (r_all,))
        check(fails(c, "INSERT INTO reward_codes (reward_rule_id, code, origin) VALUES (%s,'FPL01-X1','generated')", (r_all,)),
              'созданный кабинетом код без загрузки в магазин — нельзя')
        check(fails(c, "UPDATE reward_codes SET status='issued', event_participant_id=%s, issued_at=now() WHERE id=%s", (parts[0], gen)),
              'выдать код до загрузки в InSales — нельзя')
        c.execute("UPDATE reward_codes SET shop_sync_status='synced', shop_synced_at=now(), shop_code_id='9001' WHERE id=%s", (gen,))
        check(not fails(c, "UPDATE reward_codes SET status='issued', event_participant_id=%s, issued_at=now() WHERE id=%s", (parts[0], gen)),
              'после загрузки в InSales код выдаётся')
        check(fails(c, "UPDATE reward_codes SET event_participant_id=%s WHERE id=%s", (parts[1], gen), 'cannot be moved'),
              'выданный код не переходит к другому человеку')
        check(fails(c, "UPDATE reward_codes SET status='available', event_participant_id=NULL, issued_at=NULL WHERE id=%s", (gen,)),
              'выданный код нельзя вернуть в запас')
        up = [one(c, "INSERT INTO reward_codes (reward_rule_id, code, origin) VALUES (%s,%s,'uploaded') RETURNING id", (r_top, 'PRIZE-%d' % i))
              for i in range(3)]
        check(fails(c, "INSERT INTO reward_codes (reward_rule_id, code, origin) VALUES (%s,'prize-0','uploaded')", (r_top,)),
              'один и тот же код дважды (без учёта регистра) — нельзя')
        c.execute("UPDATE reward_codes SET status='issued', event_participant_id=%s, issued_at=now() WHERE id=%s", (parts[0], up[0]))
        check(fails(c, "UPDATE reward_codes SET status='issued', event_participant_id=%s, issued_at=now() WHERE id=%s", (parts[0], up[1])),
              'два кода одного правила одному человеку — нельзя')
        check(fails(c, "UPDATE reward_codes SET status='issued', event_participant_id=%s, issued_at=now() WHERE id=%s", (other_part, up[1]), 'same Game'),
              'код Игры 01 участнику Игры 02 — нельзя')
        check(fails(c, "UPDATE reward_codes SET status='void' WHERE id=%s", (up[2],)), 'аннулировать без причины — нельзя')
        check(not fails(c, "UPDATE reward_codes SET status='redeemed', redeemed_at=now() WHERE id=%s", (up[0],)),
              'отметка «использован в магазине»')

        print('Группы')
        g1 = one(c, "INSERT INTO task_groups (round_id, group_no, formation, submission_mode) VALUES (%s,1,'cross_league','each') RETURNING id", (rnd,))
        g2 = one(c, "INSERT INTO task_groups (round_id, group_no, formation, submission_mode) VALUES (%s,2,'manual','one_per_group') RETURNING id", (rnd,))
        contact = one(c, "INSERT INTO user_contacts (user_id, contact_type, contact_value) VALUES (%s,'telegram','@u0') RETURNING id", (users[0],))
        foreign_contact = one(c, "INSERT INTO user_contacts (user_id, contact_type, contact_value) VALUES (%s,'telegram','@u5') RETURNING id", (users[5],))
        c.execute("INSERT INTO task_group_members (task_group_id, round_id, event_participant_id, shared_contact_id) VALUES (%s,%s,%s,%s)",
                  (g1, rnd, parts[0], contact))
        check(fails(c, "INSERT INTO task_group_members (task_group_id, round_id, event_participant_id) VALUES (%s,%s,%s)", (g2, rnd, parts[0])),
              'один человек в двух группах одного тура — нельзя')
        check(fails(c, "INSERT INTO task_group_members (task_group_id, round_id, event_participant_id, shared_contact_id) VALUES (%s,%s,%s,%s)",
                    (g1, rnd, parts[1], foreign_contact), 'belong'), 'показывать партнёрам чужой контакт — нельзя')
        check(fails(c, "INSERT INTO task_group_members (task_group_id, round_id, event_participant_id) VALUES (%s,%s,%s)", (g1, rnd, other_part), 'same Game'),
              'участник другой Игры в группе — нельзя')
        for p in parts[1:6]:
            c.execute("INSERT INTO task_group_members (task_group_id, round_id, event_participant_id) VALUES (%s,%s,%s)", (g1, rnd, p))
        check(one(c, 'SELECT count(*) FROM task_group_members WHERE task_group_id=%s AND active', (g1,)) == 6, 'группа из 6 человек')
        check(fails(c, "INSERT INTO task_group_members (task_group_id, round_id, event_participant_id) VALUES (%s,%s,%s)", (g1, rnd, parts[6]), 'at most 6'),
              'седьмой в группе — нельзя')
        c.execute("UPDATE task_group_members SET active=false, left_at=now(), left_reason='выбыла' WHERE task_group_id=%s AND event_participant_id=%s", (g1, parts[5]))
        check(not fails(c, "INSERT INTO task_group_members (task_group_id, round_id, event_participant_id) VALUES (%s,%s,%s)", (g2, rnd, parts[5])),
              'выбывший из группы может попасть в другую')
        check(fails(c, "UPDATE task_groups SET status='sent' WHERE id=%s", (g1,)), '«разослано» без даты — нельзя')

        print('Материал от организатора')
        org = users[8]
        check(not fails(c, "INSERT INTO exchange_items (round_id, provided_by, item_type, text_value) VALUES (%s,%s,'text','Тема: зима')", (rnd, org)),
              'материал от организатора без участника-автора')
        check(fails(c, "INSERT INTO exchange_items (round_id, item_type, text_value) VALUES (%s,'text','ничей')", (rnd,)),
              'материал без автора — нельзя')

        print('Судья не участник')
        judge = users[8]
        c.execute("INSERT INTO event_staff (event_id, user_id, role) VALUES (%s,%s,'judge')", (ev, judge))
        check(fails(c, "INSERT INTO event_participants (event_id, user_id) VALUES (%s,%s)", (ev, judge), 'cannot take part'),
              'судья Игры не записывается в неё участником')
        check(not fails(c, "INSERT INTO event_participants (event_id, user_id) VALUES (%s,%s)", (ev2, judge)),
              'судья Игры 01 может играть в Игре 02')
        check(fails(c, "INSERT INTO event_staff (event_id, user_id, role) VALUES (%s,%s,'judge')", (ev, users[1]), 'cannot judge'),
              'участник Игры не назначается её судьёй')
        c.execute('ROLLBACK')

    print()
    if failures:
        print('НЕ ПРОШЛО: %d' % len(failures))
        sys.exit(1)
    print('Все проверки прошли')
    su('DROP DATABASE IF EXISTS %s' % TEST_DB)


if __name__ == '__main__':
    main()
