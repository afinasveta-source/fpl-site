"""Симуляция целой Игры на 200 участниц через HTTP, как браузер (управляемые часы, без ожидания).

Сценарии участниц, судей и организатора — см. out/claude-test-plan.md. После каждого тура и итогов Игры —
независимая сверка (sim/oracle.py). Находки печатаются и пишутся в sim-report.json.

    FPL_SIM_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m sim.game200 [--keep]
"""
import json
import math
import os
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sim.harness import (ORIGIN, PASSWORD, Clock, Http, Problems, create_app, db_conn, drop_db, jpeg, make_db,
                         MemoryMailer, pw_hash, settings_for)

SEED = int(os.environ.get('SIM_SEED', '20261013'))
VARIANT = os.environ.get('SIM_VARIANT', 'A')     # A — финал 40/60; B — без финала, другие способы судейства, поздняя запись
N = int(os.environ.get('SIM_N', '200'))
rng = random.Random(SEED)
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
S = T0 + timedelta(days=2)          # старт Игры
iso = lambda d: d.isoformat()
LEAGUES = ('gold', 'silver', 'bronze')

FIRST = ['Анна', 'Вера', 'Дина', 'Зоя', 'Кира', 'Мира', 'Ника', 'Ольга', 'Полина', 'Рита', 'Софья', 'Таисия', 'Ульяна',
         'Фаина', 'Юлия', 'Яна', 'Алиса', 'Белла', 'Галина', 'Дарья', 'Елена', 'Жанна', 'Инна', 'Лада', 'Марина']
LAST = ['Белова', 'Глебова', 'Ершова', 'Ильина', 'Лосева', 'Носова', 'Орлова', 'Петрова', 'Росова', 'Седова', 'Титова',
        'Уткина', 'Фомина', 'Хохлова', 'Цветкова', 'Чернова', 'Шилова', 'Щукина', 'Юдина', 'Яковлева']


class World:
    def __init__(self, app, dsn, problems, clock):
        self.app, self.dsn, self.p, self.clock = app, dsn, problems, clock
        self.people = []          # dict: email, name, client, user_id, ep_id, skill, league, scen
        self.judges = []          # dict: email, client, user_id
        self.org = None
        self.event = None
        self.rounds = []          # dict: id, no, assignment_id
        self.db = db_conn(dsn)

    def deadline_for(self, no, league):
        rnd = self.rounds[no - 1]
        for v in rnd['variants']:
            if v.get('league') == league and v.get('deadline'):
                return datetime.fromisoformat(v['deadline'])
        return rnd['deadline']

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def q1(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()


def login(w, email, label):
    h = Http(w.app, w.p, label)
    if h.post('/web-auth/login', {'email': email, 'password': PASSWORD}) is None:
        return None
    return h


# ---------------------------------------------------------------- подготовка

def setup_org(w):
    with w.db.transaction():
        uid = w.q1('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES ('org@example.com',%s,now(),'active','Организатор') RETURNING id''', (pw_hash(),))['id']
        w.db.execute("INSERT INTO user_roles VALUES (%s,'admin')", (uid,))
    w.org = login(w, 'org@example.com', 'организатор')
    w.org_id = str(uid)
    for kind, title in (('rules', 'Правила Игры'), ('publication', 'Согласие на публикацию'),
                        ('personal_data', 'Согласие на обработку ПД')):
        w.org.post('/api/org/documents', {'doc_type': kind, 'version': '1.8', 'title': title,
                                         'body': f'{title}. Текст документа для симуляции, редакция 1.8.'}, expect=(200, 201))


def make_people(w):
    """200 участниц: 30 регистрируются сами, остальные — из бота по приглашению организатора. Ещё 5 приглашённых
    не приходят, 3 зарегистрированные не записываются в Игру."""
    names = set()
    total = N + 8
    for i in range(total):
        while True:
            name = f'{rng.choice(FIRST)} {rng.choice(LAST)}'
            if name not in names:
                break
            name = f'{name} {i}'
            break
        names.add(name)
        email = f'p{i:03d}@example.com'
        person = {'i': i, 'email': email, 'name': name, 'skill': rng.gauss(0, 1), 'scen': set()}
        if i % 7 == 0:   # сама
            h = Http(w.app, w.p, f'p{i}')
            if h.post('/web-auth/register', {'email': email, 'password': PASSWORD, 'full_name': name}, expect=201) is None:
                continue
            person['client'] = h
            person['scen'].add('self_signup')
        else:
            u = w.org.post('/api/org/people', {'full_name': name, 'email': email, 'city': 'Казань', 'country_code': 'RU',
                                              'telegram_id': 900000000 + i}, expect=201)
            if u is None:
                continue
            if i >= N + 3:   # приглашены, но не пришли
                person['scen'].add('never_came')
                w.people.append(person | {'user_id': u['id'], 'client': None})
                continue
            link = w.org.post(f"/api/org/people/{u['id']}/invite")
            token = link['link'].split('token=')[1]
            h = Http(w.app, w.p, f'p{i}')
            h.post('/web-auth/invite/check', {'token': token})
            if h.post('/web-auth/invite', {'token': token, 'email': email, 'password': PASSWORD}) is None:
                continue
            person['client'] = h
            person['scen'].add('invited')
        me = person['client'].get('/web-auth/me')
        person['user_id'] = me['id'] if me else None
        w.people.append(person)
    print(f'accounts: {sum(1 for p in w.people if p.get("client"))} active, {sum(1 for p in w.people if "never_came" in p["scen"])} not came')


def make_judges(w, n=25):
    with w.db.transaction():
        for j in range(n):
            email = f'j{j:02d}@example.com'
            uid = w.q1('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name)
VALUES (%s,%s,now(),'active',%s) RETURNING id''', (email, pw_hash(), f'Судья {j + 1}'))['id']
            w.db.execute("INSERT INTO user_roles VALUES (%s,'judge')", (uid,))
            w.judges.append({'j': j, 'email': email, 'user_id': str(uid), 'bias': rng.gauss(0, 0.25)})
    for jd in w.judges:
        jd['client'] = login(w, jd['email'], f"судья {jd['j'] + 1}")


def make_game(w):
    org = w.org
    season = org.post('/api/org/seasons', {'name': 'Сезон 2 (симуляция)', 'season_no': 2}, expect=201)
    e = org.post('/api/org/events', {'title': 'Игра 02 — симуляция 200', 'season_id': season['id']}, expect=201)
    eid = e['id']
    org.patch(f'/api/org/events/{eid}', {'game_no': 2, 'registration_opens_at': iso(T0 - timedelta(hours=1)),
                                         'registration_closes_at': iso(S - timedelta(hours=1) if VARIANT == 'A' else S + timedelta(days=1)), 'starts_at': iso(S),
                                         'ends_at': iso(S + timedelta(days=36)), 'description': 'Пять туров, финал — 5 тур.'})
    plan = [
        # (название, открытие, срок, срок судейства, форма, варианты)
        ('Бабочка', S, S + timedelta(days=3), S + timedelta(days=5),
         {'photo': 'required', 'link': 'none', 'photo_max': 1},
         [{'league': None, 'instructions': 'Общее задание: бабочка на щеке.'}]),
        ('Сказка', S + timedelta(days=6), S + timedelta(days=10), S + timedelta(days=12),
         {'photo': 'required', 'link': 'optional', 'photo_max': 2},
         [{'league': None, 'instructions': 'Общий текст (на случай без лиги).'},
          {'league': 'gold', 'title': 'Сказка: сложный персонаж', 'instructions': 'Gold: полный образ.',
           'opens_at': iso(S + timedelta(days=6)), 'deadline': iso(S + timedelta(days=9))},
          {'league': 'silver', 'title': 'Сказка: герой', 'instructions': 'Silver: образ героя.',
           'opens_at': iso(S + timedelta(days=6, hours=12)), 'deadline': iso(S + timedelta(days=9, hours=12))},
          {'league': 'bronze', 'instructions': 'Bronze: простой персонаж.',
           'opens_at': iso(S + timedelta(days=7)), 'deadline': iso(S + timedelta(days=10))}]),
        ('Стихии', S + timedelta(days=13), S + timedelta(days=16), S + timedelta(days=18),
         {'photo': 'required', 'link': 'optional', 'photo_max': 3},
         [{'league': None, 'instructions': 'Стихии: одна из четырёх.'},
          {'league': 'gold', 'instructions': 'Gold: две стихии в одном образе.'}]),
        ('Маска', S + timedelta(days=19), S + timedelta(days=22), S + timedelta(days=24),
         {'photo': 'required', 'link': 'required', 'photo_max': 1},
         [{'league': None, 'instructions': 'Маска: фото и ссылка на пост.'}]),
        ('Финал', S + timedelta(days=25), S + timedelta(days=28), S + timedelta(days=30),
         {'photo': 'required', 'link': 'none', 'photo_max': 2},
         [{'league': None, 'instructions': 'Финал: свободная тема.'}]),
    ]
    for no, (title, opens, deadline, jdl, form, variants) in enumerate(plan, 1):
        r = org.post(f'/api/org/events/{eid}/rounds', {}, expect=201)
        org.patch(f"/api/org/rounds/{r['id']}", {'title': title, 'opens_at': iso(opens), 'deadline': iso(deadline),
                                                 'judging_deadline': iso(jdl)})
        org.put(f"/api/org/rounds/{r['id']}/task", {'title': title, 'form': form, 'variants': variants})
        org.post(f"/api/org/rounds/{r['id']}/status", {'action': 'publish'})
        w.rounds.append({'id': r['id'], 'no': no, 'title': title, 'opens': opens, 'deadline': deadline, 'jdl': jdl,
                         'form': form, 'variants': variants})
    # формат итогов: по умолчанию 40/60; TOP-25 — с 60 человек в лиге, чтобы проверить и его (по умолчанию — от 100)
    if VARIANT == 'A':
        fmt = {'final_round': 5, 'path_rounds': [1, 2, 3, 4], 'path_weight': 40, 'points': {'top25_min': 60}}
        w.fmt = {'final': 5, 'path': [1, 2, 3, 4], 'weight': 40}
    else:   # без финала: итог — средний балл всех пяти туров
        fmt = {'no_final': True, 'path_rounds': [1, 2, 3, 4, 5], 'path_weight': 100, 'points': {'top25_min': 60}}
        w.fmt = {'final': None, 'path': [1, 2, 3, 4, 5], 'weight': 100}
    res = org.put(f'/api/org/events/{eid}/results/format', fmt)
    w.p.check(res is not None and res['config']['final_round'] == w.fmt['final'], 'major', 'org', f"формат итогов не сохранился: {res and res.get('config')}")
    pub = org.post(f'/api/org/events/{eid}/status', {'action': 'publish'})
    w.event = eid
    w.season = season
    detail = org.get(f'/api/org/events/{eid}')
    w.p.check(detail and detail.get('status') == 'registration', 'major', 'org', f'Игра не опубликовалась: {detail and detail.get("status")}')
    for r in w.rounds:
        w.assignment_of = getattr(w, 'assignment_of', {})
    rows = w.q('SELECT r.id, r.round_no, a.id AS aid FROM rounds r JOIN assignments a ON a.round_id=r.id WHERE r.event_id=%s', (eid,))
    for row in rows:
        w.rounds[row['round_no'] - 1]['assignment_id'] = str(row['aid'])


def register_all(w):
    eid = w.event
    active = [p for p in w.people if p.get('client') and 'never_came' not in p['scen']]
    # 3 активных аккаунта в Игру не записываются
    for p in active[-3:]:
        p['scen'].add('no_registration')
    if VARIANT == 'B':      # шесть человек записываются уже после старта Игры (запись открыта до S + 1 день)
        for p in active[-9:-3]:
            p['scen'].add('late_reg')
    for p in active[:-3]:
        if 'late_reg' in p['scen']:
            continue
        c = p['client']
        cat = c.get('/api/events')
        ev = c.get(f'/api/events/{eid}')
        body = {'accept_rules': True, 'confirm_adult': True, 'accept_publication': True, 'accept_personal_data': True}
        if 'self_signup' in p['scen']:
            body |= {'country_code': 'RU', 'city': rng.choice(['Москва', 'Самара', 'Пермь'])}
        # двойное нажатие «Записаться» — второй ответ без новой записи
        r1 = c.post(f'/api/events/{eid}/registration', body, expect=201)
        if p['i'] % 25 == 1:
            r2 = c.post(f'/api/events/{eid}/registration', body, expect=(200, 201))
            w.p.check(r2 is not None and r2.get('created') is False, 'major', 'registration', f'повторная запись: {r2}')
        p['registered'] = r1 is not None
    # без согласий — отказ
    bad = active[-1]['client']
    bad.post(f'/api/events/{eid}/registration', {'accept_rules': False, 'accept_publication': True,
                                                 'accept_personal_data': True}, expect=422, level='minor')
    n = w.q1('SELECT count(*) AS n FROM event_participants WHERE event_id=%s', (eid,))['n']
    print(f'registered: {n}')
    w.part = [p for p in w.people if p.get('registered')]
    # судья не может записаться участницей в Игру, где он судья — это проверим после назначения судей
    return n


def assign_leagues(w):
    """Лиги по «силе» (как по рейтингу): ~20% Gold, ~35% Silver, остальные Bronze; двое — без лиги (ошибка организатора)."""
    lst = w.org.get(f'/api/org/events/{w.event}/participants')
    by_user = {x['user_id']: x for x in lst['participants']} if lst and lst['participants'] and 'user_id' in lst['participants'][0] else None
    if by_user is None:
        by_email = {x.get('email'): x for x in lst['participants']}
    ranked = sorted(w.part, key=lambda p: -p['skill'])
    n = len(ranked)
    for k, p in enumerate(ranked):
        row = by_user.get(p['user_id']) if by_user else by_email.get(p['email'])
        if row is None:
            w.p.add('major', 'org', f"нет в списке участниц: {p['email']}")
            continue
        p['ep_id'] = row['id']
        p['league'] = 'gold' if k < n * 0.2 else 'silver' if k < n * 0.55 else 'bronze'
    for p in w.part[5:7]:
        p['scen'].add('no_league')
    t = time.perf_counter()
    items = [{'id': p['ep_id'], 'league': p['league']} for p in w.part if 'no_league' not in p['scen'] and 'ep_id' in p]
    r = w.org.post(f'/api/org/events/{w.event}/leagues', {'items': items})    # лиги списком — одним сохранением
    w.p.check(r is not None and r['changed'] == len(items), 'major', 'org', f'лиги списком: {r}')
    print(f'leagues set: {Counter(p.get("league") for p in w.part)} in {time.perf_counter() - t:.1f}s (bulk)')


def start_game(w):
    w.clock.set(S + timedelta(minutes=5))
    r = w.org.post(f'/api/org/events/{w.event}/status', {'action': 'start'})
    w.p.check(r is not None and r['status'] == 'active', 'critical', 'org', 'Игра не стартовала')
    late = [p for p in w.people if 'late_reg' in p['scen']]
    if late:
        w.clock.set(S + timedelta(hours=12))
        for p in late:
            r = p['client'].post(f'/api/events/{w.event}/registration',
                                 {'accept_rules': True, 'confirm_adult': True, 'accept_publication': True, 'accept_personal_data': True,
                                  'country_code': 'RU', 'city': 'Тула'}, expect=201)
            p['registered'] = r is not None
            me = game_me(w, p)
            p['late_reg_mode'] = me and me['mode']
        lst = {x['user_id']: x['id'] for x in w.org.get(f'/api/org/events/{w.event}/participants')['participants']}
        items = []
        for p in late:
            p['ep_id'] = lst.get(p['user_id'])
            p['league'] = 'bronze'
            items.append({'id': p['ep_id'], 'league': 'bronze'})
            w.part.append(p)
        w.org.post(f'/api/org/events/{w.event}/leagues', {'items': items})
        print('late registrations after start, modes:', Counter(p['late_reg_mode'] for p in late))


# ---------------------------------------------------------------- сдача

def upload_photos(c, k, seed):
    ids = []
    for j in range(k):
        r = c.call('POST', '/api/uploads', expect=201, content=jpeg(seed * 10 + j), headers={'Content-Type': 'image/jpeg', **ORIGIN})
        if r:
            ids.append(r['id'])
    return ids


def submit(w, p, rnd, late=False, link=True, photos=None, label=''):
    """Сдать работу тура. Возвращает ответ submit или None."""
    c, eid, aid = p['client'], w.event, rnd['assignment_id']
    t = c.get(f'/api/games/{eid}/tasks/{aid}', expect=(200, 404))
    if t is None:
        return None
    k = photos or rng.randint(1, rnd['form']['photo_max'])
    ids = upload_photos(c, k, hash((p['i'], rnd['no'], label)) % 100000)
    body = {'photos': ids, 'link': f"https://vk.com/wall-1_{p['i']}{rnd['no']}" if rnd['form']['link'] != 'none' and (link or rnd['form']['link'] == 'required') else None}
    d = c.put(f'/api/games/{eid}/tasks/{aid}/draft', body, expect=(200, 409, 422))
    if d and d.get('detail') == 'rules':
        # вышла новая редакция Правил — участница принимает её и сдаёт работу
        doc = w.q1("SELECT id FROM legal_documents WHERE doc_type='rules' ORDER BY published_at DESC LIMIT 1")['id']
        c.post('/api/consents', {'document_id': str(doc)})
        w.rules_accepted = getattr(w, 'rules_accepted', 0) + 1
        d = c.put(f'/api/games/{eid}/tasks/{aid}/draft', body, expect=(200, 409, 422))
    if not d or 'draft' not in d:
        return d
    return c.post(f'/api/games/{eid}/tasks/{aid}/submit', {'draft_id': d['draft']['id']}, expect=(200, 409, 422))


def game_me(w, p):
    g = p['client'].get(f'/api/games/{w.event}')
    return g['me'] if g else None


def main():
    source = os.environ['FPL_SIM_DSN']
    name, dsn = make_db(source)
    media = tempfile.mkdtemp(prefix='fpl-sim-media-')
    clock = Clock(T0)
    problems = Problems()
    app = create_app(settings_for(dsn, media), MemoryMailer(), clock=clock)
    w = World(app, dsn, problems, clock)
    w.media = media
    try:
        setup_org(w); make_people(w); make_judges(w); make_game(w)
        register_all(w); assign_leagues(w); start_game(w)
        import sim.phases as PH
        PH.run(w)
    finally:
        json.dump({'problems': problems.items}, open('sim-report.json', 'w'), ensure_ascii=False, indent=1)
        print('PROBLEMS', len(problems.items))
        if '--keep' not in sys.argv:
            drop_db(source, name)
        else:
            print('kept db', name)


if __name__ == '__main__':
    main()
