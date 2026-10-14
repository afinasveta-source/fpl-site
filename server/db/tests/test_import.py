#!/usr/bin/env python3
"""Проверка fpl-db-import на отдельной базе fpl_import_test (локальный PostgreSQL, роль из /etc/fpl-db.env).

Запуск: python3 server/db/tests/test_import.py
Данные — выдуманные (клиенты c1…c12), по колонкам таблиц SaleBot из документов проекта.
"""
import copy, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.dirname(HERE)
IMPORT = os.path.join(DB_DIR, 'fpl-db-import')
TEST_DB = 'fpl_import_test'
M = 'fpl_game1_2026'

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
    for f in ('001_initial_mvp_schema.sql', '002_auth.sql', '003_league_rules.sql', '004_rewards_groups.sql',
              '005_participant_cabinet.sql', '006_organizer_cabinet.sql', '007_judging_results.sql'):
        body = ''.join(l for l in open(os.path.join(DB_DIR, 'schema', f)) if l.strip() not in ('BEGIN;', 'COMMIT;'))
        with psycopg.connect(DSN) as c:
            c.execute(body)
    with psycopg.connect(DSN) as c:
        c.execute(open(os.path.join(DB_DIR, 'site_views.sql')).read())


def q(sql, args=()):
    with psycopg.connect(DSN) as c:
        return c.execute(sql, args).fetchall()


def q1(sql, args=()):
    r = q(sql, args)
    return r[0][0] if r else None


# ------------------------------------------------------------------ данные
def fixture():
    clients = ['c%d' % i for i in range(1, 13)]
    t = {}
    t['mg_person_names'] = [{'client_id': c, 'last_name': 'Фамилия%s' % c, 'first_name': 'Имя', 'middle_name': None,
                             'no_middle_name': 1, 'full_name': 'Фамилия%s Имя' % c} for c in clients]
    t['mg_public_names'] = [{'client_id': c, 'public_name': 'Мастер %s' % c.upper(), 'updated_at': '2026-09-25 10:00:00'}
                            for c in clients if c != 'c3']
    # c5 сменил публичное имя — берётся последнее
    t['mg_public_names'].append({'client_id': 'c5', 'public_name': 'Новое имя C5', 'updated_at': '2026-10-01 10:00:00'})
    t['mg_client_channels'] = [{'client_id': 'c1', 'channel': 'telegram', 'external_id': '111'},
                               {'client_id': 'c2', 'channel': 'vk', 'external_id': '222'}]
    t['mg_legal_documents'] = [
        {'doc_type': 'rules', 'version': '1.7', 'title': 'Правила', 'published_on': '2026-09-22', 'part_no': 2, 'body': 'вторая часть', 'is_current': 1},
        {'doc_type': 'rules', 'version': '1.7', 'title': 'Правила', 'published_on': '2026-09-22', 'part_no': 1, 'body': 'первая часть', 'is_current': 1},
        {'doc_type': 'pd_consent', 'version': '1.1', 'title': 'Согласие ПД', 'published_on': '2026-09-22', 'part_no': 1, 'body': 'пд', 'is_current': 1},
        {'doc_type': 'publication_consent', 'version': '1.2', 'title': 'Распространение', 'published_on': '2026-09-22', 'part_no': 1, 'body': 'ред 1.2', 'is_current': 0},
        {'doc_type': 'publication_consent', 'version': '1.3', 'title': 'Распространение', 'published_on': '2026-09-24', 'part_no': 1, 'body': 'ред 1.3', 'is_current': 1},
        {'doc_type': 'model_confirmation', 'version': '1.1', 'title': 'Модель', 'published_on': '2026-09-22', 'part_no': 1, 'body': 'модель', 'is_current': 1},
    ]
    acc, n = [], 0
    for c in clients:
        types = [('pd_consent', '1.1')] if c == 'c12' else [('rules', '1.7'), ('pd_consent', '1.1'), ('publication_consent', '1.3'), ('model_confirmation', '1.1')]
        for dt, ver in types:
            n += 1
            acc.append({'id': n, 'client_id': c, 'doc_type': dt, 'version': ver, 'status': 'accepted',
                        'accepted_at_utc': '2026-09-26 12:%02d:00' % (n % 60), 'accepted_unix': 1790424000 + n,
                        'channel': 'telegram', 'button_text': 'Принимаю', 'marathon': M, 'context': 'ФИО и контакт %s' % c})
    t['mg_legal_acceptances'] = acc
    # тур 1: общий пул из 10, лиги А (c1–c5, часть кириллицей) и Б; c11 — жюри, c12 — без работы
    snap = []
    for i, c in enumerate(clients[:10]):
        snap.append({'marathon': M, 'round_no': 1, 'client_id': c, 'season': 1, 'league': ('А' if i % 2 else 'A') if i < 5 else 'Б',
                     'metric_type': 'win_share', 'metric_raw': 1 - i / 10, 'metric_max': 1, 'display_score': 100 - i * 6,
                     'display_formula_version': 'DISPLAY_V1', 'place': i + 1, 'average_place': i + 1, 'tie_group_size': 1,
                     'pool_size': 10, 'top_work': 1 if i < 2 else 0, 'participant_status': 'valid', 'rules_version': '1.7'})
    snap.append({'marathon': M, 'round_no': 1, 'client_id': 'c11', 'participant_status': 'jury', 'top_work': 0})
    snap.append({'marathon': M, 'round_no': 1, 'client_id': 'c12', 'participant_status': 'no_work', 'top_work': 0})
    for i, c in enumerate(clients[:10]):
        snap.append({'marathon': M, 'round_no': 2, 'client_id': c, 'league': 'A' if i < 5 else 'B', 'display_score': 90 - (i % 5) * 10,
                     'place': i % 5 + 1, 'average_place': i % 5 + 1, 'tie_group_size': 1, 'pool_size': 5,
                     'top_work': 1 if i % 5 == 0 else 0, 'participant_status': 'valid'})
    snap.append({'marathon': 'fpl_rating_test', 'round_no': 1, 'client_id': 'c1', 'participant_status': 'valid'})
    t['mg_round_snapshot'] = snap
    t['mg_rating_rounds'] = [{'marathon': M, 'round_no': 1, 'league': 'all', 'state': 'published'},
                             {'marathon': M, 'round_no': 2, 'league': 'gold', 'state': 'calculated'},
                             {'marathon': M, 'round_no': 2, 'league': 'silver', 'state': 'calculated'}]
    ev, n = [], 0
    for i, c in enumerate(clients[:10]):
        n += 1
        ev.append({'event_id': n, 'marathon': M, 'season': 1, 'round_no': 1, 'client_id': c, 'event_type': 'initial',
                   'rating_before': None, 'rating_after': round(650 - 300 * i / 9), 'delta': None, 'calibration_before': 0,
                   'calibration_after': 1, 'league': 'A' if i < 5 else 'B', 'batch_id': 'GAME01_R01_INIT_V1',
                   'formula_version': 'FPL_RATING_V1', 'created_at': '2026-10-06 12:00:00'})
    for i, c in enumerate(clients[:10]):
        n += 1
        before = round(650 - 300 * i / 9)
        ev.append({'event_id': n, 'marathon': M, 'season': 1, 'round_no': 2, 'client_id': c, 'event_type': 'round',
                   'rating_before': before, 'rating_after': before + (10 - i), 'delta': 10 - i, 'k_factor': 300, 'cap': 140,
                   'expected': 0.5, 'scored': 0.6, 'comparisons': 8, 'calibration_before': 1, 'calibration_after': 2,
                   'league': 'A' if i < 5 else 'B', 'batch_id': 'GAME01_R02_V1', 'formula_version': 'FPL_RATING_V1',
                   'created_at': '2026-10-09 12:00:00'})
    t['mg_rating_events'] = ev
    t['mg_rating_players'] = [{'client_id': c, 'rating_current': round(650 - 300 * i / 9) + (10 - i), 'calibration_count': 2,
                               'rating_status': 'provisional', 'league_current': 'A' if i < 5 else 'B', 'last_marathon': M}
                              for i, c in enumerate(clients[:10])]
    return t


def write_input(d, tables, export_id, manifest_counts=None):
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for name, rows in tables.items():
        json.dump(rows, open(os.path.join(d, 'private-sb-%s.json' % name), 'w'), ensure_ascii=False)
    counts = manifest_counts or {k: len(v) for k, v in tables.items()}
    json.dump({'export_id': export_id, 'project': '874007', 'tables': counts},
              open(os.path.join(d, 'private-sb-manifest.json'), 'w'))


def run(priv, data, *args):
    e = dict(os.environ, FPL_PRIVATE=priv, FPL_DATA=data, FPL_DATABASE_DSN=DSN, FPL_DB_EXPORT='/nonexistent')
    p = subprocess.run([sys.executable, '-I', IMPORT] + list(args), env=e, capture_output=True, text=True)
    status = json.load(open(os.path.join(data, 'import-status.json'))) if os.path.exists(os.path.join(data, 'import-status.json')) else {}
    return p, status


def rating_after_game():
    """Рейтинг на сайте после конца Игры (во время Игры — рейтинг на начало, решение 13.10)."""
    live = q1("SELECT site_export_rating()")
    q1("UPDATE events SET status='finished' WHERE status='active' RETURNING 1")
    try:
        return live, q1('SELECT site_export_rating()')
    finally:
        q1("UPDATE events SET status='active' WHERE status='finished' RETURNING 1")


def main():
    fresh_db()
    priv, data = tempfile.mkdtemp(), tempfile.mkdtemp()
    try:
        t = fixture()

        print('1. неполный набор — ждём')
        write_input(priv, t, 'e1', manifest_counts=dict({k: len(v) for k, v in t.items()}, mg_round_snapshot=999))
        p, st = run(priv, data)
        check(p.returncode == 0 and 'mg_round_snapshot' in st.get('waiting', ''), 'не совпало число строк → импорт не начат')
        check(q1('SELECT count(*) FROM import_batches') == 0, 'пакетов нет')

        print('2. первый перенос')
        write_input(priv, t, 'e1')
        p, st = run(priv, data)
        check(p.returncode == 0 and st.get('status') == 'completed', 'пакет completed (%s)' % (p.stderr.strip()[-300:]))
        check(q1('SELECT count(*) FROM users') == 12, 'людей 12')
        check(q1("SELECT count(*) FROM external_identities WHERE provider='salebot_client'") == 12, 'идентичностей SaleBot 12')
        check(q1("SELECT telegram_id FROM users u JOIN external_identities e ON e.user_id=u.id AND e.external_id='c1' AND e.provider='salebot_client'") == 111,
              'telegram_id из mg_client_channels')
        check(q1("SELECT count(*) FROM external_identities WHERE provider='vk' AND external_id='222'") == 1, 'ВК-идентичность')
        check(q1("SELECT display_name FROM users u JOIN external_identities e ON e.user_id=u.id AND e.external_id='c5'") == 'Новое имя C5',
              'публичное имя — последнее')
        check(q1('SELECT count(*) FROM consents') == 45, 'согласий 45 (11×4 + 1)')
        check(q1("SELECT body FROM legal_documents WHERE doc_type='rules'") == 'первая часть\nвторая часть', 'части Правил склеены по порядку')
        check(q1("SELECT superseded_at IS NOT NULL FROM legal_documents WHERE doc_type='publication' AND version='1.2'") is True,
              'ред. 1.2 отмечена устаревшей')
        check(q1("SELECT count(*) FROM consents WHERE legal_document_id IS NULL") == 0, 'каждое согласие привязано к редакции')
        check(q1('SELECT count(*) FROM event_participants') == 11, 'участниц Игры 11 (без жюри)')
        check(q1("SELECT string_agg(DISTINCT entry_league, ',' ORDER BY entry_league) FROM event_participants") == 'gold,silver',
              'лиги А/Б → gold/silver (и кириллица)')
        check(q1("SELECT count(*) FROM round_results") == 20, 'итогов 20 (только valid)')
        check(q1("SELECT count(*) FROM round_results rr JOIN rounds r ON r.id=rr.round_id WHERE r.round_no=1 AND rr.status='published'") == 10,
              'тур 1 опубликован')
        check(q1("SELECT count(*) FROM round_results rr JOIN rounds r ON r.id=rr.round_id WHERE r.round_no=2 AND rr.status='draft'") == 10,
              'тур 2 (calculated) — не опубликован')
        check(q1("SELECT count(*) FROM round_results rr JOIN rounds r ON r.id=rr.round_id WHERE r.round_no=1 AND league_rank IS NOT NULL") == 0,
              'в туре 1 место в лиге не записывается (пул общий)')
        check(q1("SELECT count(*) FROM rating_transactions WHERE status='active'") == 20, 'рейтинговых записей 20')
        check(q1("SELECT count(*) FROM participant_stats WHERE rating_status='calibrating'") == 10, 'профили рейтинга 10 (calibrating)')
        check(q1("SELECT count(*) FROM season_participants WHERE current_league='gold'") == 5, 'в Gold 5')
        check(q1("SELECT count(*) FROM import_issues WHERE severity='error'") == 0, 'ошибок импорта нет')
        check(q1("SELECT count(*) FROM import_row_map") > 0, 'карта строк заполнена')

        live, rating = rating_after_game()
        check(all(not x['players'] for x in live['seasons']), 'во время Игры 01 рейтинга на сайте нет (на начало Игры его ни у кого не было)')
        players = rating['seasons'][0]['players']
        names = [p['name'] for p in players]
        check(len(players) == 10, 'в рейтинге на сайте 10 (без публичного имени — имя из ФИО, решение 13.10): %d' % len(players))
        check('Мастер C3' not in names and all(n for n in names) and any(n.startswith('Фамилия') for n in names),
              'без публичного имени — имя из ФИО')
        check([p['place'] for p in players][:3] == [1, 2, 3], 'места по порядку')
        games = q1('SELECT site_export_games()')
        r1 = games['games'][0]['rounds'][0]
        check(r1['published'] and r1['top_work_count'] == 2 and sorted(x['name'] for x in r1['top_work']) == ['Мастер C1', 'Мастер C2'],
              'TOP WORK тура 1: 2 работы с именами')
        dumped = json.dumps(games, ensure_ascii=False)
        check('score' not in dumped and 'league_rank' not in dumped, 'баллы и места других в games.json не публикуются')
        check(games['games'][0]['rounds'][1]['top_work'] == [], 'TOP WORK неопубликованного тура 2 не виден')
        check(games['games'][0]['participants'] == 11, 'участниц Игры 11')
        check(sum(r1['top_work_leagues'].values()) == 2 and set(r1['top_work_leagues']) <= {'gold', 'silver'},
              'TOP WORK тура 1 посчитан по лигам (для «TOP WORK Gold»)')
        check(games['games'][0]['rating_live'] is False, 'по умолчанию рейтинг во время Игры — на её начало')
        tw_players = [p for p in rating['seasons'][0]['players'] if p['top_work']]
        check(tw_players and all(sum(p['top_work_leagues'].values()) == p['top_work'] for p in tw_players),
              'TOP WORK в рейтинге — по лигам')

        print('2a. организатор разрешил текущий рейтинг во время Игры (17.10)')
        q1("""UPDATE events SET settings = settings || '{"site_rating_live": true}' WHERE status='active' RETURNING 1""")
        try:
            lv = q1('SELECT site_export_rating()')
            check(lv['frozen'] is None and lv['live'] and lv['live']['after_round'] == 1, 'вместо «на начало Игры» — «после тура 1»')
            lp = lv['seasons'][0]['players']
            check(len(lp) == 10 and [p['place'] for p in lp][:3] == [1, 2, 3], 'таблица во время Игры: 10 мастеров, места по порядку')
            check(q1('SELECT site_export_games()')['games'][0]['rating_live'] is True, 'games.json знает, что рейтинг текущий')
        finally:
            q1("""UPDATE events SET settings = settings - 'site_rating_live' WHERE status='active' RETURNING 1""")
        check(all(not x['players'] for x in q1('SELECT site_export_rating()')['seasons']), 'флаг снят — снова на начало Игры')

        print('3. тот же снимок ещё раз — пропускается')
        p, st = run(priv, data)
        check(q1('SELECT count(*) FROM import_batches') == 1, 'новый пакет не создан')

        print('4. --force: повтор без дублей')
        p, st = run(priv, data, '--force')
        check(st.get('status') == 'completed', 'повтор completed')
        for tbl, n in (('users', 12), ('consents', 45), ('round_results', 20), ('rating_transactions', 20), ('event_participants', 11),
                       ('legal_documents', 5), ('external_identities', 14)):
            check(q1('SELECT count(*) FROM %s' % tbl) == n, '%s: %d без дублей' % (tbl, n))

        print('5. отзыв согласия, тур 2 опубликован, пересчёт стартового батча')
        t2 = copy.deepcopy(t)
        t2['mg_legal_acceptances'].append({'id': 999, 'client_id': 'c4', 'doc_type': 'publication_consent', 'version': '1.3',
                                           'status': 'revoked', 'accepted_at_utc': '2026-10-10 09:00:00', 'accepted_unix': 1791622800,
                                           'channel': 'telegram', 'button_text': 'Отозвать', 'marathon': M})
        for r in t2['mg_rating_rounds']:
            if r['round_no'] == 2:
                r['state'] = 'published'
        for r in t2['mg_rating_events']:
            if r['batch_id'] == 'GAME01_R01_INIT_V1':
                r['batch_id'] = 'GAME01_R01_INIT_V2'
        write_input(priv, t2, 'e2')
        p, st = run(priv, data)
        check(st.get('status') == 'completed', 'пакет completed (%s)' % p.stderr.strip()[-300:])
        check(q1('SELECT count(*) FROM consents') == 46, 'отзыв добавлен новой записью')
        names = [x['name'] for x in rating_after_game()[1]['seasons'][0]['players']]
        check('Мастер C4' not in names and len(names) == 9, 'отозвавшая скрыта с сайта: %d' % len(names))
        check(q1("SELECT public_rating FROM users u JOIN external_identities e ON e.user_id=u.id AND e.external_id='c4'") is False,
              'флаг публичности снят')
        check(q1("SELECT count(*) FROM rating_transactions WHERE status='void'") == 10 and
              q1("SELECT count(*) FROM rating_transactions WHERE status='active' AND method='initial_seeding'") == 10,
              'старый стартовый батч погашен, новый активен')
        g = q1('SELECT site_export_games()')['games'][0]['rounds'][1]
        check(g['published'] and g['top_work_count'] == 2, 'тур 2 опубликован, TOP WORK 2')
        check(sorted(x['league'] for x in g['top_work']) == ['gold', 'silver'], 'TOP WORK тура 2 по лигам')

        print('6. сбой — ничего не записано')
        before = q1('SELECT count(*) FROM rating_transactions')
        t3 = copy.deepcopy(t2)
        t3['mg_rating_events'].append(dict(t3['mg_rating_events'][0], event_id=500, batch_id='SECOND_INIT'))
        t3['mg_person_names'].append({'client_id': 'c13', 'full_name': 'Новая Участница'})
        write_input(priv, t3, 'e3')
        p, st = run(priv, data)
        check(p.returncode == 1 and st.get('status') == 'failed', 'второе стартовое распределение → failed')
        check('lr_rt_one_initial_seeding' in st.get('error', ''), 'в статусе названо ограничение, без данных строк')
        check(q1('SELECT count(*) FROM users') == 12 and q1('SELECT count(*) FROM rating_transactions') == before,
              'транзакция откатилась целиком')
        check(q1("SELECT count(*) FROM import_batches WHERE status='failed'") == 1, 'пакет failed записан')

        print('7. лига с неизвестным значением — ошибка в журнале, не падение')
        t4 = copy.deepcopy(t2)
        t4['mg_round_snapshot'][0]['league'] = 'Z'
        write_input(priv, t4, 'e4')
        p, st = run(priv, data)
        check(st.get('status') == 'completed' and st['issues'].get('error') == 1, 'пакет completed, 1 ошибка в журнале')

        print('8. Игра перенесена в кабинет (13.10) — перенос из SaleBot её не трогает')
        q1('''UPDATE events SET settings = settings || '{"moved_to_kabinet": {"from_round": 3}}'::jsonb RETURNING 1''')
        q1("UPDATE rounds SET status='scheduled', settings='{\"relay\": {\"from\": \"gold\", \"to\": \"silver\"}}' WHERE round_no=3 RETURNING 1")
        uid = q1("SELECT user_id FROM external_identities WHERE external_id='c1' AND provider='salebot_client'")
        q1("UPDATE users SET email='c1@example.com', password_hash='x', account_status='active', display_name='Сама поменяла' WHERE id=%s RETURNING 1", (uid,))
        q1("UPDATE participant_stats SET current_rating=777 WHERE user_id=%s RETURNING 1", (uid,))
        rr = q1("SELECT count(*) FROM round_results")
        rt = q1("SELECT count(*) FROM rating_transactions WHERE status='active'")
        t5 = copy.deepcopy(t2)
        for r in t5['mg_round_snapshot']:
            r['display_score'] = 41
        write_input(priv, t5, 'e5')
        p, st = run(priv, data)
        check(st.get('status') == 'completed', 'пакет completed (%s)' % p.stderr.strip()[-300:])
        check(q1("SELECT status FROM rounds WHERE round_no=3") == 'scheduled' and
              q1("SELECT settings->'relay'->>'to' FROM rounds WHERE round_no=3") == 'silver', 'туры кабинета не тронуты')
        check(q1("SELECT count(*) FROM round_results WHERE display_score=41") == 0 and q1("SELECT count(*) FROM round_results") == rr,
              'итоги не перезаписаны')
        check(float(q1("SELECT current_rating FROM participant_stats WHERE user_id=%s", (uid,))) == 777 and
              q1("SELECT count(*) FROM rating_transactions WHERE status='active'") == rt, 'рейтинг кабинета не тронут')
        check(q1("SELECT display_name FROM users WHERE id=%s", (uid,)) == 'Сама поменяла', 'имя вошедшей не перезаписано')
    finally:
        shutil.rmtree(priv)
        shutil.rmtree(data)
        su('DROP DATABASE IF EXISTS %s' % TEST_DB)
    print('\nИТОГ: %s' % ('всё прошло' if not failures else '%d проверок не прошли' % len(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
