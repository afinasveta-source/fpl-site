"""Общие заготовки проверок кабинета участника: Игра с турами, документы, вход, фото."""
import hashlib
import io
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image

from conftest import PASSWORD

ORIGIN = {'Origin': 'http://testserver'}
T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def h(**kw):
    return T0 + timedelta(**kw)


def add_doc(conn, kind, version, published=None):
    body = f'{kind} {version}: текст документа'
    return conn.execute('''INSERT INTO legal_documents(doc_type,version,title,body,body_sha256,published_at)
VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''', (kind, version, f'{kind} {version}', body,
                                            hashlib.sha256(body.encode()).hexdigest(), published or h(days=-30))).fetchone()['id']


def add_docs(conn):
    return {k: add_doc(conn, k, v) for k, v in (('rules', '1.9'), ('publication', '1'), ('personal_data', '1'))}


def build_game(conn, status='active', reg_closes=None, payment=False, rounds=3, title='Игра 02', leagues=None):
    """Игра: тур 1 открыт (срок через 1 день), тур 2 откроется через 2 дня (срок +4), тур 3 — через 5 (срок +7).
    Конец Игры через 20 дней."""
    event = conn.execute('''INSERT INTO events(event_type,status,title,starts_at,ends_at,completion_deadline,
registration_opens_at,registration_closes_at,payment_required,price,currency,game_no)
VALUES ('ranked_game',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,2) RETURNING *''',
                         (status, title, h(days=-1), h(days=20), h(days=20), h(days=-5),
                          reg_closes if reg_closes is not None else h(days=1), payment,
                          1500 if payment else None, 'RUB' if payment else None)).fetchone()
    out = {'event': event['id'], 'rounds': [], 'tasks': []}
    plan = [(h(days=-1), h(days=1)), (h(days=2), h(days=4)), (h(days=5), h(days=7))][:rounds]
    for no, (opens, deadline) in enumerate(plan, 1):
        r = conn.execute('''INSERT INTO rounds(event_id,round_no,title,status,opens_at,deadline,judging_deadline)
VALUES (%s,%s,%s,'scheduled',%s,%s,%s) RETURNING id''', (event['id'], no, f'Тур {no}', opens, deadline,
                                                     deadline + timedelta(days=1))).fetchone()['id']
        a = conn.execute('''INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work',%s) RETURNING id''',
                         (event['id'], r, f'Работа {no}')).fetchone()['id']
        if leagues:
            for league in leagues:
                conn.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n,audience_rules)
VALUES (%s,%s,%s,%s,%s)''', (a, league, f'{{"ru":"Задание {no} {league}"}}', f'{{"ru":"Текст {no} для {league}"}}',
                             f'{{"leagues":["{league}"]}}'))
        else:
            conn.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n)
VALUES (%s,'all',%s,%s)''', (a, f'{{"ru":"Задание {no}"}}', f'{{"ru":"Нарисуйте персонажа {no}"}}'))
        out['rounds'].append(r)
        out['tasks'].append(a)
    return out


def login(app, seed, email, roles=('participant',)):
    seed(email, roles)
    c = TestClient(app)
    r = c.post('/web-auth/login', headers=ORIGIN, json={'email': email, 'password': PASSWORD})
    assert r.status_code == 200, r.text
    return c


def register(c, event_id, **extra):
    body = {'accept_rules': True, 'accept_publication': True, 'accept_personal_data': True,
            'country_code': 'RU', 'city': 'Москва'} | extra
    return c.post(f'/api/events/{event_id}/registration', headers=ORIGIN, json=body)


def jpeg(color=(200, 50, 50), size=(64, 48), gps=True):
    img = Image.new('RGB', size, color)
    exif = Image.Exif()
    exif[0x010F] = 'PhoneMaker'
    if gps:
        exif[0x8825] = {1: 'N', 2: (55.0, 45.0, 0.0), 3: 'E', 4: (37.0, 37.0, 0.0)}
    out = io.BytesIO()
    img.save(out, 'JPEG', exif=exif)
    return out.getvalue()


def upload(c, data=None, ctype='image/jpeg'):
    return c.post('/api/uploads', content=data if data is not None else jpeg(), headers={'Content-Type': ctype, **ORIGIN})


def task_url(game, i):
    return f"/api/games/{game['event']}/tasks/{game['tasks'][i]}"


def send_work(c, game, i, link=None, color=(10, 20, 30)):
    photo = upload(c, jpeg(color)).json()
    draft = c.put(task_url(game, i) + '/draft', headers=ORIGIN, json={'photos': [photo['id']], 'link': link})
    assert draft.status_code == 200, draft.text
    r = c.post(task_url(game, i) + '/submit', headers=ORIGIN, json={'draft_id': draft.json()['draft']['id']})
    assert r.status_code == 200, r.text
    return r.json()
