"""Локальный кабинет с выдуманными данными — для проверки экранов в браузере (не для сервера).

Запуск: FPL_TEST_DSN=... python3 tests/demo_server.py [порт]
Создаёт отдельную базу <имя>_demo_test, заполняет её и поднимает кабинет на 127.0.0.1:порт.
Вход: anna@example.com / Correct-test-password-123! (участница), admin@example.com — администратор.
"""
import hashlib
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import psycopg
import uvicorn
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import PASSWORD, apply_schema  # noqa: E402
from kabinet.auth.security import password_hasher  # noqa: E402
from kabinet.config import Settings  # noqa: E402
from kabinet.main import create_app  # noqa: E402
from kabinet.auth.mail import MemoryMailer  # noqa: E402


def main(port):
    source = os.environ['FPL_TEST_DSN']
    name = 'fpl_kabinet_demo_test'
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = make_conninfo(source, dbname=name)
    apply_schema(dsn)
    now = datetime.now(timezone.utc)
    h = lambda **kw: now + timedelta(**kw)
    with psycopg.connect(dsn) as c:
        def user(email, role, **kw):
            u = c.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,display_name)
VALUES (%s,%s,now(),'active',%s,%s) RETURNING id''', (email, password_hasher.hash(PASSWORD), kw.get('full'), kw.get('disp'))).fetchone()[0]
            c.execute('INSERT INTO user_roles VALUES (%s,%s)', (u, role))
            return u
        user('anna@example.com', 'participant', full='Анна Петрова', disp='Анна П.')
        user('admin@example.com', 'admin', full='Светлана')
        for kind, ver, title in (('rules', '1.9', 'Правила лиги'), ('publication', '1', 'Согласие на публикацию работ'),
                                 ('personal_data', '1', 'Согласие на обработку персональных данных')):
            body = f'{title}, редакция {ver}.\n\n1. Пример текста документа для проверки экранов.\n2. Настоящий текст публикует организатор.'
            c.execute('''INSERT INTO legal_documents(doc_type,version,title,body,body_sha256,published_at) VALUES (%s,%s,%s,%s,%s,%s)''',
                      (kind, ver, title, body, hashlib.sha256(body.encode()).hexdigest(), h(days=-30)))

        def game(title, status, starts, reg_closes, rounds, no):
            e = c.execute('''INSERT INTO events(event_type,status,title,starts_at,ends_at,completion_deadline,registration_opens_at,
registration_closes_at,affects_rating,game_no,description) VALUES ('ranked_game',%s,%s,%s,%s,%s,%s,%s,true,%s,%s) RETURNING id''',
                          (status, title, starts, starts + timedelta(days=21), starts + timedelta(days=21), h(days=-10), reg_closes, no,
                           'Пять туров аквагрима: от общего задания до финала в паре.')).fetchone()[0]
            for i, (crit, prize) in enumerate((('1 место в каждой лиге', 'Главный приз лиги'), ('2–3 место в каждой лиге', 'Приз призёра'),
                                               ('Все, кто прошёл Игру', 'Диплом участника'))):
                c.execute('INSERT INTO event_prizes(event_id,sort_order,criterion,prize) VALUES (%s,%s,%s,%s)', (e, i, crit, prize))
            for n, (rt, opens, deadline) in enumerate(rounds, 1):
                r = c.execute('''INSERT INTO rounds(event_id,round_no,title,status,opens_at,deadline,judging_deadline)
VALUES (%s,%s,%s,'scheduled',%s,%s,%s) RETURNING id''', (e, n, rt, opens, deadline, deadline + timedelta(days=1, hours=14))).fetchone()[0]
                a = c.execute("INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work',%s) RETURNING id", (e, r, rt)).fetchone()[0]
                c.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n,submission_schema)
VALUES (%s,'all',%s,%s,%s)''', (a, '{"ru":"%s"}' % rt,
                                '{"ru":"Превратите лицо модели в персонажа из сказки вашей страны. Персонаж должен узнаваться без подписи.\\n\\nНужно 1 фото анфас при дневном свете, лицо целиком, без фильтров."}',
                                '{"photo":"required","link":"optional"}'))
            return e
        game('Игра 02', 'active', h(days=-1), h(days=3), [('Бабочка', h(days=-1), h(days=2)), ('Обмен темами', h(days=3), h(days=6)),
                                                          ('Портрет-персонаж', h(days=7), h(days=10))], 2)
        game('Игра 03', 'registration', h(days=25), h(days=20), [('Первый тур', h(days=25), h(days=28))], 3)
    media = tempfile.mkdtemp(prefix='fpl-demo-media-')
    settings = Settings(environment='TEST', database_dsn=dsn, mail_mode='memory', media_dir=media, media_min_free_mb=1,
                        login_limit=500, reset_limit=500, _env_file=None)
    uvicorn.run(create_app(settings, MemoryMailer()), host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8200)
