"""Перенос Игры 01 из бота в кабинет по таблице туров 1–2 (решения Светланы 13.10, вечер).

SaleBot недоступен с 11.10, Игра 01 продолжается в кабинете с 3 тура. Организатор загружает таблицу (CSV, «;»), которую
собрали из сохранённых расчётов: ID участника SaleBot, ФИО, лига, балл тура 1 (40–100), рейтинг после тура 1, балл тура 2,
прошла ли в тур 3, рейтинг после тура 2, TOP WORK тура 2. Сначала — предпросмотр (что будет записано и что не так),
потом — перенос. Личные данные в репозиторий и пакеты сервера не попадают: файл загружается только в кабинет.

Что записывается (числа — как их видели участницы, без пересчёта):
- сезон 1, Игра 01 (если её ещё нет), туры 1–2 — опубликованы, туры 3, 4 и финал — черновики для организатора
  (тур 3 — эстафета Gold → Silver, тур 4 — Silver → Gold, как в боте; поменять можно в туре);
- участница без входа (account_status imported) и её ID SaleBot; лига: А → Gold, Б → Silver (решение 11.10);
- в конкурсе — кто прошёл в тур 3; остальные — вне конкурса: с баллом тура 2 — «не прошла отбор», без него — «срок»;
- итоги туров 1–2 (балл, лига, проход, TOP WORK тура 2), FPL Rating: тур 1 — стартовое распределение, тур 2 — изменение;
  текущий рейтинг и калибровка (2 тура).
Повторный перенос той же или исправленной таблицы ничего не дублирует: соответствие строк — в import_row_map
(те же ключи, что у переноса из SaleBot: salebot_client, salebot_participant, salebot_marathon). Игра помечается
settings.moved_to_kabinet — перенос из SaleBot (если бот вернётся) её туры, итоги и рейтинг больше не трогает.
Подробностей судейства туров 1–2 (кто с кем сравнивался) в кабинете нет — публичная статистика судейства с 3 тура.
"""
import csv
import hashlib
import io
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from .common import WRITE, Jsonb, audit, db, locked_admin, now_of, org_user, problem

router = APIRouter(prefix='/api/org/import', tags=['organizer'])

MSK = timezone(timedelta(hours=3))
PROJECT = '874007'
MARATHON = 'fpl_game1_2026'
GAME = dict(season_no=1, season_name='Сезон 1', game_no=1, title='Игра 01', title_en='Game 01',
            starts=datetime(2026, 9, 30, 0, 0, tzinfo=MSK), ends=datetime(2026, 11, 10, 23, 59, tzinfo=MSK))
# Даты туров 1–2 в боте (для истории; итоги уже опубликованы участницам).
BOT_ROUNDS = {
    1: dict(title='Тур 1', opens=datetime(2026, 9, 30, 17, 0, tzinfo=MSK), deadline=datetime(2026, 10, 4, 2, 0, tzinfo=MSK),
            published=datetime(2026, 10, 6, 12, 0, tzinfo=MSK)),
    2: dict(title='Тур 2', opens=datetime(2026, 10, 5, 12, 0, tzinfo=MSK), deadline=datetime(2026, 10, 8, 2, 0, tzinfo=MSK),
            published=datetime(2026, 10, 9, 22, 0, tzinfo=MSK)),
}
NEXT_ROUNDS = {3: ('Тур 3', {'from': 'gold', 'to': 'silver'}), 4: ('Тур 4', {'from': 'silver', 'to': 'gold'}), 5: ('Финал', None)}
LEAGUE = {'а': 'gold', 'a': 'gold', 'лига а': 'gold', 'gold': 'gold', 'б': 'silver', 'b': 'silver', 'лига б': 'silver',
          'silver': 'silver'}
YES = {'да', 'yes', '1', 'true', '+'}
NO = {'нет', 'no', '0', 'false', '-', ''}
DEFAULT_FORM = {'photo': 'required', 'link': 'required', 'photo_max': 1}

# Колонка таблицы → поле. Ищется по началу заголовка (без регистра), порядок колонок не важен.
COLUMNS = [
    ('cid', ('id участника', 'id')),
    ('name', ('имя', 'фио')),
    ('league', ('лига',)),
    ('s1', ('оценка тура 1',)),
    ('r1_first', ('рейтинг после тура 1 (первоначальный',)),
    ('r1', ('рейтинг после тура 1 (пересчитанный', 'рейтинг после тура 1')),
    ('tw1', ('top work тура 1',)),
    ('s2', ('оценка работы тура 2', 'оценка тура 2')),
    ('adv', ('прошёл в тур 3', 'прошла в тур 3', 'прошел в тур 3')),
    ('r2', ('рейтинг после тура 2',)),
    ('d2', ('изменение за тур 2',)),
    ('tw2', ('top work тура 2',)),
    ('note', ('примечание',)),
]
REQUIRED = ('cid', 'name', 'league', 's1', 'r1', 's2', 'adv', 'r2', 'tw2')


def _num(raw):
    v = (raw or '').strip().replace(',', '.').replace('−', '-')
    if v.endswith('.'):
        v = v[:-1]
    if v in ('', '-', '—'):
        return None
    try:
        return float(v)
    except ValueError:
        raise ValueError('not_a_number') from None


def parse(text):
    """Таблица → (строки, ошибки, предупреждения). Ошибка в строке — строка не переносится (и перенос не начнётся)."""
    text = text.lstrip('﻿')
    sample = text[:2000]
    delimiter = ';' if sample.count(';') >= sample.count(',') else ','
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return [], [{'line': 1, 'problem': 'empty_file'}], []
    norm = [h.strip().lower().replace('ё', 'е') for h in header]
    index = {}
    for key, prefixes in COLUMNS:
        for i, h in enumerate(norm):
            if i in index.values():
                continue
            if any(h.startswith(p.replace('ё', 'е')) for p in prefixes):
                # «Рейтинг после тура 1» без уточнения не должен съесть «первоначальный»
                if key == 'r1' and 'первоначальн' in h:
                    continue
                index[key] = i
                break
    missing = [k for k in REQUIRED if k not in index]
    if missing:
        return [], [{'line': 1, 'problem': 'missing_columns', 'columns': missing}], []
    rows, errors, warnings, seen = [], [], [], set()
    for no, raw in enumerate(reader, 2):
        if not any(x.strip() for x in raw):
            continue
        get = lambda k: raw[index[k]].strip() if k in index and index[k] < len(raw) else ''
        try:
            cid = get('cid')
            if not re.fullmatch(r'\d{3,20}', cid):
                raise ValueError('bad_id')
            if cid in seen:
                raise ValueError('duplicate_id')
            name = ' '.join(get('name').split())
            if len(name) < 2:
                raise ValueError('bad_name')
            league = LEAGUE.get(get('league').lower())
            if not league:
                raise ValueError('bad_league')
            adv = get('adv').lower()
            if adv not in YES | NO:
                raise ValueError('bad_advanced')
            row = dict(line=no, cid=cid, name=name[:200], league=league, s1=_num(get('s1')), r1_first=_num(get('r1_first')),
                       r1=_num(get('r1')), s2=_num(get('s2')), advanced=adv in YES, r2=_num(get('r2')), d2=_num(get('d2')),
                       tw1=get('tw1').lower() in YES, tw2=get('tw2').lower() in YES, note=get('note')[:300] or None)
            if row['r1'] is None and row['r1_first'] is not None:
                row['r1'] = row['r1_first']      # без тура 2 пересчёта не было — действует первоначальный рейтинг
                row['r1_from_first'] = True
            if row['s1'] is None or not 0 <= row['s1'] <= 100:
                raise ValueError('bad_score_1')
            if row['r1'] is None or not 0 < row['r1'] < 5000:
                raise ValueError('bad_rating_1')
            if row['s2'] is not None and not 0 <= row['s2'] <= 100:
                raise ValueError('bad_score_2')
            if row['advanced'] and (row['s2'] is None or row['r2'] is None):
                raise ValueError('advanced_without_round_2')
            if (row['s2'] is None) != (row['r2'] is None):
                raise ValueError('round_2_incomplete')
            if row['r2'] is not None and not 0 < row['r2'] < 5000:
                raise ValueError('bad_rating_2')
            if row['tw2'] and row['s2'] is None:
                raise ValueError('top_work_without_score')
        except ValueError as exc:
            errors.append({'line': no, 'problem': str(exc), 'id': raw[index['cid']].strip()[:20] if index['cid'] < len(raw) else None})
            continue
        seen.add(cid)
        if row['r2'] is not None and row['d2'] is not None and abs(round(row['r2']) - round(row['r1']) - round(row['d2'])) > 1:
            warnings.append({'line': no, 'problem': 'delta_mismatch'})
        if row.get('r1_from_first'):
            warnings.append({'line': no, 'problem': 'rating_1_first'})
        rows.append(row)
    if not rows and not errors:
        errors.append({'line': 1, 'problem': 'no_rows'})
    if rows and 'tw1' not in index:
        warnings.append({'line': 1, 'problem': 'no_top_work_1'})
    return rows, errors, warnings


def summary(rows):
    out = {}
    for r in rows:
        lg = out.setdefault(r['league'], {'total': 0, 'in_competition': 0, 'judged_out': 0, 'no_round_2': 0, 'top_work_2': 0})
        lg['total'] += 1
        if r['advanced']:
            lg['in_competition'] += 1
        elif r['s2'] is not None:
            lg['judged_out'] += 1
        else:
            lg['no_round_2'] += 1
        lg['top_work_2'] += r['tw2']
    return out


class ImportIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csv: str = Field(min_length=10, max_length=2_000_000)
    sha256: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')   # из предпросмотра: переносится ровно то, что видели


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def existing_event(conn):
    ev = conn.execute('''SELECT e.* FROM events e JOIN seasons s ON s.id=e.season_id
WHERE s.season_no=%s AND e.game_no=%s''', (GAME['season_no'], GAME['game_no'])).fetchone()
    return ev


@router.post('/game01/preview', dependencies=WRITE)
def preview(body: ImportIn, request: Request, user=Depends(org_user)):
    rows, errors, warnings = parse(body.csv)
    with db(request).transaction() as conn:
        ev = existing_event(conn)
        known = 0
        if rows:
            known = conn.execute('''SELECT count(*) AS n FROM import_row_map WHERE source_table='salebot_client'
AND target_table='users' AND source_key = ANY(%s)''', ([r['cid'] for r in rows],)).fetchone()['n']
        moved = bool(ev and (ev['settings'] or {}).get('moved_to_kabinet'))
        locked = cabinet_rating(conn)
        not_in_table = 0
        if ev and rows:
            not_in_table = conn.execute('''SELECT count(*) AS n FROM event_participants p WHERE p.event_id=%s
AND p.registration_status='participating' AND (p.competition_status IS NULL OR p.competition_status='active')
AND NOT EXISTS (SELECT 1 FROM external_identities x WHERE x.user_id=p.user_id AND x.provider='salebot_client' AND x.external_id = ANY(%s))
AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id=p.user_id AND u.account_status='active')''', (ev['id'], [r['cid'] for r in rows])).fetchone()['n']
        no_rules = conn.execute("SELECT 1 FROM legal_documents WHERE doc_type='rules' AND published_at <= now() LIMIT 1").fetchone() is None
    if not_in_table:
        warnings = warnings + [{'line': 1, 'problem': 'not_in_table', 'count': not_in_table}]
    if no_rules:
        warnings = warnings + [{'line': 1, 'problem': 'no_rules'}]
    return {'sha256': digest(body.csv), 'rows': len(rows), 'errors': errors[:200], 'error_count': len(errors),
            'warnings': warnings[:200], 'leagues': summary(rows), 'already_known': known,
            'event': {'exists': ev is not None, 'title': ev['title'] if ev else GAME['title'], 'moved': moved,
                      'id': str(ev['id']) if ev else None, 'locked': locked}}


@router.post('/game01/apply', dependencies=WRITE)
def apply(body: ImportIn, request: Request, user=Depends(org_user)):
    if body.sha256 is None or body.sha256 != digest(body.csv):
        raise problem('preview_first', 409)
    rows, errors, _ = parse(body.csv)
    if errors:
        raise problem('table_has_errors')
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('bot-import-game01', 0))")
        if cabinet_rating(conn):
            raise problem('cabinet_rating_started', 409)
        return Importer(conn, user['id'], now, body.sha256).run(rows)


def cabinet_rating(conn):
    """Кабинет уже начислил рейтинг за туры Игры 01 — перенос туров 1–2 больше нельзя повторить (рейтинг разошёлся бы)."""
    ev = existing_event(conn)
    return bool(ev and conn.execute('''SELECT 1 FROM rating_transactions WHERE event_id=%s AND status='active'
AND idempotency_key LIKE 'elo:%%' LIMIT 1''', (ev['id'],)).fetchone())


class Importer:
    def __init__(self, conn, actor, now, sha):
        self.conn, self.actor, self.now, self.sha = conn, actor, now, sha
        self.counts = {}

    def one(self, q, args=()):
        return self.conn.execute(q, args).fetchone()

    def count(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def mapped(self, st, sk, tt):
        r = self.one('SELECT target_id FROM import_row_map WHERE source_table=%s AND source_key=%s AND target_table=%s', (st, sk, tt))
        return r['target_id'] if r else None

    def remember(self, st, sk, tt, tid, row=None):
        self.conn.execute('''INSERT INTO import_row_map(first_batch_id,last_batch_id,source_table,source_key,target_table,target_id,row_sha256)
VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_table, source_key, target_table) DO UPDATE
SET last_batch_id=EXCLUDED.last_batch_id, target_id=EXCLUDED.target_id, row_sha256=EXCLUDED.row_sha256, updated_at=now()''',
                          (self.batch, self.batch, st, sk, tt, tid,
                           hashlib.sha256(repr(sorted((row or {}).items())).encode()).hexdigest() if row else None))

    # --- Игра и туры
    def game(self):
        season = self.one('SELECT * FROM seasons WHERE season_no=%s', (GAME['season_no'],))
        if season is None:
            season = self.one("INSERT INTO seasons(name,status,season_no) VALUES (%s,'active',%s) RETURNING *",
                              (GAME['season_name'], GAME['season_no']))
        ev = existing_event(self.conn) or (self.one('SELECT * FROM events WHERE id=%s', (self.mapped('salebot_marathon', MARATHON, 'events'),))
                                           if self.mapped('salebot_marathon', MARATHON, 'events') else None)
        rules = self.one('''SELECT id FROM legal_documents WHERE doc_type='rules' AND published_at <= %s
AND (superseded_at IS NULL OR superseded_at > %s) ORDER BY published_at DESC LIMIT 1''', (self.now, self.now))
        mark = {'at': self.now.isoformat(), 'from_round': 3, 'source': 'csv', 'sha256': self.sha}
        if ev is None:
            ev = self.one('''INSERT INTO events(season_id,event_type,status,title,title_i18n,starts_at,ends_at,completion_deadline,
registration_opens_at,registration_closes_at,official_timezone,affects_rating,has_diploma,awards_points,game_no,rules_document_id,settings)
VALUES (%s,'ranked_game','active',%s,%s,%s,%s,%s,%s,%s,'Europe/Moscow',true,true,true,%s,%s,%s) RETURNING *''',
                          (season['id'], GAME['title'], Jsonb({'ru': GAME['title'], 'en': GAME['title_en']}), GAME['starts'], GAME['ends'],
                           GAME['ends'], GAME['starts'] - timedelta(days=4), GAME['starts'] + timedelta(days=3), GAME['game_no'],
                           rules['id'] if rules else None, Jsonb({'moved_to_kabinet': mark})))
            self.count('event_created')
        else:
            settings = dict(ev['settings'] or {})
            settings['moved_to_kabinet'] = {**(settings.get('moved_to_kabinet') or {}), **mark}
            # редакцию Правил после старта Игры менять нельзя (триггер lr_events_rules_frozen) — ставится только до старта
            started = ev['status'] in ('active', 'finished', 'archived')
            ev = self.one('''UPDATE events SET settings=%s,
rules_document_id=CASE WHEN %s THEN rules_document_id ELSE coalesce(rules_document_id, %s) END,
status=CASE WHEN status IN ('draft','registration') THEN 'active' ELSE status END WHERE id=%s RETURNING *''',
                          (Jsonb(settings), started, rules['id'] if rules else None, ev['id']))
        self.event, self.season = ev, season
        self.remember('salebot_marathon', MARATHON, 'events', ev['id'])
        self.rounds = {}
        for no, cfg in BOT_ROUNDS.items():
            r = self.one('SELECT * FROM rounds WHERE event_id=%s AND round_no=%s', (ev['id'], no))
            settings = {'source': 'bot', 'judging_details': False}
            if r is None:
                r = self.one('''INSERT INTO rounds(event_id,round_no,title,title_i18n,status,opens_at,deadline,judging_deadline,settings)
VALUES (%s,%s,%s,%s,'published',%s,%s,%s,%s) RETURNING *''', (ev['id'], no, cfg['title'], Jsonb({'ru': cfg['title'], 'en': f'Round {no}'}),
                                                       cfg['opens'], cfg['deadline'], cfg['published'], Jsonb(settings)))
            else:
                r = self.one('''UPDATE rounds SET status='published', settings=settings || %s,
opens_at=coalesce(opens_at,%s), deadline=coalesce(deadline,%s) WHERE id=%s RETURNING *''',
                             (Jsonb(settings), cfg['opens'], cfg['deadline'], r['id']))
            self.rounds[no] = r
        for no, (title, relay) in NEXT_ROUNDS.items():
            r = self.one('SELECT * FROM rounds WHERE event_id=%s AND round_no=%s', (ev['id'], no))
            if r is not None:
                has_task = self.one('SELECT 1 FROM assignments WHERE round_id=%s', (r['id'],))
                # тур, созданный переносом из SaleBot (без задания и дат), — в черновик кабинета; заполненный — не трогать
                if has_task or r['status'] not in ('draft', 'scheduled') or r['opens_at'] is not None:
                    continue
                settings = dict(r['settings'] or {})
                if relay:
                    settings['relay'] = relay
                r = self.one("UPDATE rounds SET status='draft', title=%s, settings=%s WHERE id=%s RETURNING *", (title, Jsonb(settings), r['id']))
            else:
                r = self.one('''INSERT INTO rounds(event_id,round_no,title,status,settings) VALUES (%s,%s,%s,'draft',%s) RETURNING *''',
                             (ev['id'], no, title, Jsonb({'relay': relay} if relay else {})))
            a = self.one('''INSERT INTO assignments(event_id,round_id,code,title) VALUES (%s,%s,'work',%s) RETURNING *''',
                         (ev['id'], r['id'], f'Задание тура {no}' if no < 5 else 'Задание финала'))
            self.conn.execute('''INSERT INTO assignment_variants(assignment_id,code,title_i18n,instructions_i18n,submission_schema)
VALUES (%s,'all',%s,%s,%s)''', (a['id'], Jsonb({'ru': a['title']}), Jsonb({'ru': ''}), Jsonb(DEFAULT_FORM)))
            self.count('rounds_created')

    # --- люди
    def person(self, row):
        uid = self.mapped('salebot_client', row['cid'], 'users')
        if uid is None:
            ident = self.one('''SELECT user_id FROM external_identities WHERE provider='salebot_client' AND project_ref=%s AND external_id=%s''',
                             (PROJECT, row['cid']))
            uid = ident['user_id'] if ident else None
        if uid is None:
            uid = self.one("INSERT INTO users(account_status,full_name) VALUES ('imported',%s) RETURNING id", (row['name'],))['id']
            self.count('people_created')
        else:
            # имя из таблицы — только тем, кто ещё не вошёл в кабинет (вошедшая правит профиль сама)
            self.conn.execute("UPDATE users SET full_name=%s WHERE id=%s AND account_status='imported'", (row['name'], uid))
            self.count('people_known')
        self.conn.execute('''INSERT INTO external_identities(user_id,provider,project_ref,external_id,linked_at,metadata)
VALUES (%s,'salebot_client',%s,%s,now(),%s) ON CONFLICT (provider, project_ref, external_id) DO NOTHING''',
                          (uid, PROJECT, row['cid'], Jsonb({'project': PROJECT})))
        self.conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (uid,))
        self.remember('salebot_client', row['cid'], 'users', uid, {'name': row['name']})
        return uid

    def participant(self, row, uid):
        r1, r2 = self.rounds[1], self.rounds[2]
        if row['advanced']:
            status = dict(competition_status='active', elimination_reason=None, eliminated_round_id=None,
                          out_of_competition_at=None, out_of_competition_source=None)
        else:
            status = dict(competition_status='diploma_only', elimination_reason='judged_out' if row['s2'] is not None else 'late',
                          eliminated_round_id=r2['id'], out_of_competition_at=BOT_ROUNDS[2]['published'],
                          out_of_competition_source='import_auto')
        ep = self.one('SELECT * FROM event_participants WHERE event_id=%s AND user_id=%s FOR UPDATE', (self.event['id'], uid))
        if ep is None:
            ep = self.one('''INSERT INTO event_participants(event_id,user_id,registration_status,eligibility_status,payment_status,
entry_league,entry_league_round_id,joined_at,competition_status,elimination_reason,eliminated_round_id,out_of_competition_at,
out_of_competition_source) VALUES (%(e)s,%(u)s,'participating','eligible','not_required',%(lg)s,%(r1)s,%(j)s,%(competition_status)s,
%(elimination_reason)s,%(eliminated_round_id)s,%(out_of_competition_at)s,%(out_of_competition_source)s) RETURNING *''',
                          {'e': self.event['id'], 'u': uid, 'lg': row['league'], 'r1': r1['id'], 'j': GAME['starts'], **status})
            self.count('participants_created')
        else:
            # уже в кабинете: лигу и состояние после тура 2 — из таблицы, но решения, принятые в кабинете позже
            # (вышла, дисквалифицирована, выбыла в туре 3+), не затираются
            later = ep['competition_status'] in ('disqualified',) or ep['registration_status'] in ('withdrawn', 'cancelled') or \
                (ep['eliminated_round_id'] is not None and ep['eliminated_round_id'] not in (r1['id'], r2['id'])) or \
                self.one('''SELECT 1 FROM audit_log WHERE entity_type='event_participant' AND entity_id=%s
AND (action='league_set' OR action LIKE 'org!_%%' ESCAPE '!') LIMIT 1''', (ep['id'],)) is not None
            if later:
                self.count('participants_kept')
            else:
                ep = self.one('''UPDATE event_participants SET entry_league=%(lg)s, entry_league_round_id=%(r1)s,
competition_status=%(competition_status)s, elimination_reason=%(elimination_reason)s, eliminated_round_id=%(eliminated_round_id)s,
out_of_competition_at=%(out_of_competition_at)s, out_of_competition_source=%(out_of_competition_source)s WHERE id=%(id)s RETURNING *''',
                              {'lg': row['league'], 'r1': r1['id'], 'id': ep['id'], **status})
                self.count('participants_updated')
        self.remember('salebot_participant', f"{MARATHON}:{row['cid']}", 'event_participants', ep['id'])
        self.conn.execute('''INSERT INTO season_participants(season_id,user_id,league_at_start,current_league) VALUES (%s,%s,%s,%s)
ON CONFLICT (season_id,user_id) DO UPDATE SET league_at_start=coalesce(season_participants.league_at_start, EXCLUDED.league_at_start),
current_league=EXCLUDED.current_league''', (self.season['id'], uid, row['league'], row['league']))
        return ep

    def result(self, row, ep, no):
        rnd = self.rounds[no]
        score = row['s1'] if no == 1 else row['s2']
        if score is None:
            return
        snap = {'source': 'bot_csv', 'sha256': self.sha, 'scale': '40-100' if no == 1 else '1-100',
                'method': 'bot_v1' if no == 1 else 'bt_bot_v1', 'note': row['note']}
        advanced = True if no == 1 else row['advanced']
        top = row['tw1'] if no == 1 else row['tw2']
        after = 'active' if advanced else ('diploma_only' if no == 2 else 'active')
        out = self.one('''INSERT INTO round_results(event_id,round_id,event_participant_id,version_no,is_current,status,display_score,
advanced,competition_status_after,league,top_work,top_work_rule_version,calculation_snapshot,published_at)
VALUES (%s,%s,%s,1,true,'published',%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (round_id, event_participant_id, version_no) DO UPDATE SET display_score=EXCLUDED.display_score, advanced=EXCLUDED.advanced,
competition_status_after=EXCLUDED.competition_status_after, league=EXCLUDED.league, top_work=EXCLUDED.top_work,
top_work_rule_version=EXCLUDED.top_work_rule_version, calculation_snapshot=EXCLUDED.calculation_snapshot RETURNING id''',
                       (self.event['id'], rnd['id'], ep['id'], round(score, 2), advanced, after, row['league'], top,
                        'FPL_TOPWORK_V1' if top else None, Jsonb(snap), BOT_ROUNDS[no]['published']))
        self.remember('bot_csv_round_result', f"{MARATHON}:{no}:{row['cid']}", 'round_results', out['id'])
        self.count(f'round_{no}_results')

    def rating(self, row, uid):
        r1, r2 = round(row['r1']), round(row['r2']) if row['r2'] is not None else None
        tx = [(1, 'initial_seeding', None, r1, 0, 1, {'first_shown': row['r1_first']})]
        if r2 is not None:
            tx.append((2, 'pairwise_elo', r1, r2, 1, 2, {}))
        for no, method, before, after, cb, ca, extra in tx:
            key = f'bot-csv:{MARATHON}:r{no}:{row["cid"]}'
            if method == 'initial_seeding':
                # одно стартовое распределение на человека (уникальный индекс): прежнее из переноса SaleBot — гасится
                self.conn.execute('''UPDATE rating_transactions SET status='void' WHERE user_id=%s AND method='initial_seeding'
AND status='active' AND idempotency_key<>%s''', (uid, key))
            self.conn.execute('''INSERT INTO rating_transactions(user_id,event_id,round_id,method,formula_version,rating_before,
delta_after_cap,rating_after,calibration_round_no,calibration_rounds_completed_before,calibration_rounds_completed_after,
calculation_snapshot,status,idempotency_key,applied_at) VALUES (%s,%s,%s,%s,'bot_csv_v1',%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)
ON CONFLICT (idempotency_key) DO UPDATE SET rating_before=EXCLUDED.rating_before, delta_after_cap=EXCLUDED.delta_after_cap,
rating_after=EXCLUDED.rating_after, calculation_snapshot=EXCLUDED.calculation_snapshot, status='active' ''',
                              (uid, self.event['id'], self.rounds[no]['id'], method, before,
                               (after - before) if before is not None else None, after, ca, cb, ca,
                               Jsonb({'source': 'bot_csv', 'sha256': self.sha, **extra}), key, BOT_ROUNDS[no]['published']))
            # старые записи переноса SaleBot за тот же тур — гасятся (одна действующая на тур)
            self.conn.execute('''UPDATE rating_transactions SET status='void' WHERE user_id=%s AND round_id=%s AND status='active'
AND idempotency_key<>%s AND idempotency_key LIKE 'salebot:%%' ''', (uid, self.rounds[no]['id'], key))
            self.count('rating_transactions')
        # кабинет уже начислял рейтинг за туры 3+ — текущий рейтинг не трогаем
        cabinet = self.one('''SELECT 1 FROM rating_transactions WHERE user_id=%s AND status='active' AND idempotency_key LIKE 'elo:%%' LIMIT 1''', (uid,))
        if cabinet:
            return
        current, cal = (r2, 2) if r2 is not None else (r1, 1)
        self.conn.execute('''INSERT INTO participant_stats(user_id,current_rating,calibration_rounds_completed,rating_status)
VALUES (%s,%s,%s,'calibrating') ON CONFLICT (user_id) DO UPDATE SET current_rating=EXCLUDED.current_rating,
calibration_rounds_completed=EXCLUDED.calibration_rounds_completed, rating_status=EXCLUDED.rating_status''', (uid, current, cal))

    def others(self, rows):
        """Участницы Игры, которых нет в таблице (были в переносе из SaleBot): в конкурсе их оставлять нельзя —
        они попали бы в эстафету и судейство. Переводятся вне конкурса с пометкой; вернуть может организатор."""
        cids = [r['cid'] for r in rows]
        extra = self.conn.execute('''SELECT p.* FROM event_participants p WHERE p.event_id=%s AND p.registration_status='participating'
AND (p.competition_status IS NULL OR p.competition_status='active')
AND NOT EXISTS (SELECT 1 FROM external_identities x WHERE x.user_id=p.user_id AND x.provider='salebot_client' AND x.external_id = ANY(%s))
AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id=p.user_id AND u.account_status='active')''', (self.event['id'], cids)).fetchall()
        for ep in extra:
            self.conn.execute('''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='admin',
out_of_competition_at=%s, out_of_competition_source='import_auto' WHERE id=%s''', (self.now, ep['id']))
            audit(self.conn, self.actor, 'event_participant', ep['id'], 'bot_import_not_in_table', {})
        self.count('not_in_table_outside', len(extra))

    def run(self, rows):
        # журнал переноса — общий с переносом SaleBot (данные оттуда же); вид переноса — в notes
        self.batch = self.one('''INSERT INTO import_batches(source,source_project,snapshot_sha256,status,started_by,started_at,notes)
VALUES ('salebot',%s,%s,'started',%s,%s,%s) RETURNING id''', (PROJECT, self.sha, self.actor, self.now, f'bot_csv game01: {len(rows)} rows'))['id']
        self.game()
        for row in rows:
            uid = self.person(row)
            ep = self.participant(row, uid)
            self.result(row, ep, 1)
            self.result(row, ep, 2)
            self.rating(row, uid)
        self.others(rows)
        self.conn.execute("UPDATE import_batches SET status='completed', finished_at=%s, notes=%s WHERE id=%s",
                          (self.now, f'bot_csv game01: {len(rows)} rows; ' + ', '.join(f'{k}={v}' for k, v in sorted(self.counts.items())), self.batch))
        audit(self.conn, self.actor, 'event', self.event['id'], 'bot_import_game01', {'rows': len(rows), 'counts': self.counts, 'sha256': self.sha})
        return {'event_id': str(self.event['id']), 'rows': len(rows), 'counts': self.counts, 'leagues': summary(rows)}


def _uuid(v):
    return v if isinstance(v, UUID) else UUID(str(v))
