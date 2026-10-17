"""Вход в кабинет участниц Игры 01 из бота (решения Светланы 13.10, вечер).

Бот недоступен, написать каждой участнице лично нельзя. Поэтому: общая ссылка (пост в соцсетях) → страница «Я играю
в Игре 01» → участница оставляет ФИО, email, пароль, страну, город, контакт в Telegram/VK (по желанию) и согласия →
заявка. Организатор видит заявку и подсказку — похожие ФИО из перенесённого списка Игры 01 — и нажимает «Это она»:
у записи из бота появляется вход (email и пароль из заявки), участница входит и продолжает Игру с 3 тура.
До подтверждения аккаунта нет. Пароль хранится только хешем. Чужую запись занять нельзя: подтверждает человек.
"""
import re
from typing import Literal
from uuid import UUID

import psycopg

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from kabinet.auth.routes import client_ip, service
from kabinet.auth.security import password_hasher
from kabinet.org.common import WRITE, Jsonb, audit, db, iso, locked_admin, notify, now_of, org_user, problem
from kabinet.participation import rules as R
from kabinet.web.routes import PASSWORD_MIN, same_origin

public = APIRouter(prefix='/api/public/claims', tags=['public'])
org = APIRouter(prefix='/api/org/claims', tags=['organizer'])
KINDS = ('rules', 'publication', 'personal_data')


def moved_event(conn):
    """Игра, перенесённая из бота и идущая сейчас (заявки принимаются только тогда)."""
    return conn.execute('''SELECT * FROM events WHERE settings ? 'moved_to_kabinet' AND status='active'
ORDER BY starts_at DESC NULLS LAST LIMIT 1''').fetchone()


def documents(conn, now):
    out = {}
    for kind in KINDS:
        d = conn.execute('''SELECT id, version, title, body FROM legal_documents WHERE doc_type=%s AND published_at <= %s
AND (superseded_at IS NULL OR superseded_at > %s) ORDER BY published_at DESC LIMIT 1''', (kind, now, now)).fetchone()
        if d:
            out[kind] = d
    return out


@public.get('/config')
def config(request: Request):
    with db(request).transaction() as conn:
        ev = moved_event(conn)
        docs = documents(conn, now_of(request))
    return {'open': ev is not None, 'game': ev['title'] if ev else None, 'password_min_length': PASSWORD_MIN,
            'documents': {k: {'version': d['version'], 'title': d['title'], 'body': d['body']} for k, d in docs.items()}}


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    country_code: str = Field(pattern='^[A-Za-z]{2}$')
    city: str = Field(min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    accept_rules: bool = False
    accept_publication: bool = False
    accept_personal_data: bool = False
    confirm_adult: bool = False
    website: str | None = Field(default=None, max_length=200)   # ловушка для ботов

    @field_validator('full_name', 'city', 'contact')
    @classmethod
    def trim(cls, value):
        return ' '.join(value.split()) if value is not None else None

    @field_validator('email')
    @classmethod
    def lower(cls, value):
        return value.lower()


@public.post('', status_code=201, dependencies=[Depends(same_origin)])
def create(body: ClaimIn, request: Request, auth=Depends(service)):
    auth.throttle('claim', client_ip(request), limit=request.app.state.settings.claim_limit, window=3600)
    if body.website:
        return {'claim_no': 0}
    if len(body.full_name) < 2 or not body.city:
        raise HTTPException(422, 'name_required')
    if not (body.accept_rules and body.accept_publication and body.accept_personal_data):
        raise HTTPException(422, 'consents_required')
    if not body.confirm_adult:
        raise HTTPException(422, 'adult_required')
    now = now_of(request)
    encoded = password_hasher.hash(body.password)
    with db(request).transaction() as conn:
        ev = moved_event(conn)
        if ev is None:
            raise HTTPException(409, 'claims_closed')
        if conn.execute('SELECT 1 FROM users WHERE lower(email)=%s', (body.email,)).fetchone():
            raise HTTPException(409, 'email_taken')
        if conn.execute("SELECT 1 FROM account_claims WHERE lower(email)=%s AND status='pending'", (body.email,)).fetchone():
            raise HTTPException(409, 'claim_pending')
        docs = documents(conn, now)
        conn.execute('SAVEPOINT claim')
        try:
            row = conn.execute('''INSERT INTO account_claims(event_id,full_name,email,password_hash,country_code,city,contact,consents,created_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING claim_no''', (
            ev['id'], body.full_name, body.email, encoded, body.country_code.upper(), body.city, body.contact,
            Jsonb({'adult_confirmed': True, 'at': now.isoformat(),
                   'documents': {k: {'id': str(d['id']), 'version': d['version']} for k, d in docs.items()}}), now)).fetchone()
        except psycopg.errors.UniqueViolation:
            conn.execute('ROLLBACK TO SAVEPOINT claim')   # вторая заявка с тем же email в ту же секунду
            raise HTTPException(409, 'claim_pending') from None
        conn.execute("INSERT INTO audit_log(entity_type,action,after_data) VALUES ('account_claim','claim_created',%s)",
                     (Jsonb({'claim_no': row['claim_no']}),))
    return {'claim_no': row['claim_no']}


# ---------- организатор ----------

def words(name):
    return {w for w in re.split(r'[^a-zа-я0-9]+', (name or '').lower().replace('ё', 'е')) if len(w) > 1}


def similarity(a, b):
    """Похожесть ФИО по словам (порядок не важен: «Анна Смирнова» = «Смирнова Анна Михайловна»)."""
    return word_similarity(words(a), words(b))


def word_similarity(wa, wb):
    if not wa or not wb:
        return 0.0
    common = len(wa & wb)
    return common / min(len(wa), len(wb)) * (0.85 + 0.15 * common / max(len(wa), len(wb)))


def free_people(conn, event_id):
    """Перенесённые участницы Игры без входа (ещё никто не подтвердил за них заявку)."""
    return conn.execute('''SELECT u.id, u.full_name, p.entry_league, p.competition_status, p.elimination_reason,
  (SELECT external_id FROM external_identities x WHERE x.user_id=u.id AND x.provider='salebot_client' LIMIT 1) AS bot_id
FROM event_participants p JOIN users u ON u.id=p.user_id
WHERE p.event_id=%s AND u.account_status='imported' AND u.email IS NULL AND u.deleted_at IS NULL
AND p.registration_status='participating' ORDER BY u.full_name''', (event_id,)).fetchall()


def person_view(p, score=None):
    return {'user_id': str(p['id']), 'full_name': p['full_name'], 'league': p['entry_league'], 'bot_id': p['bot_id'],
            'in_competition': p['competition_status'] in (None, 'active'), 'score': round(score, 2) if score is not None else None}


def claim_view(c, people=None):
    out = {'no': c['claim_no'], 'status': c['status'], 'full_name': c['full_name'], 'email': c['email'], 'country_code': c['country_code'],
           'city': c['city'], 'contact': c['contact'], 'created_at': iso(c['created_at']), 'decided_at': iso(c['decided_at']),
           'decision_note': c['decision_note'], 'matched_user_id': str(c['matched_user_id']) if c['matched_user_id'] else None}
    if people is not None:
        ranked = sorted(((similarity(c['full_name'], p['full_name']), p) for p in people), key=lambda x: -x[0])
        out['suggestions'] = [person_view(p, s) for s, p in ranked[:3] if s >= 0.5]
    return out


@org.get('')
def claims(request: Request, status: str = Query('pending', pattern='^(pending|all)$'), user=Depends(org_user)):
    with db(request).transaction() as conn:
        ev = moved_event(conn)
        people = free_people(conn, ev['id']) if ev else []
        q = 'SELECT * FROM account_claims' + (" WHERE status='pending'" if status == 'pending' else '') + ' ORDER BY created_at DESC LIMIT 500'
        items = conn.execute(q).fetchall()
        decided = conn.execute("SELECT claim_no, full_name, email, decision_note FROM account_claims WHERE status='approved'").fetchall()
        out = []
        for c in items:
            v = claim_view(c, people if c['status'] == 'pending' else None)
            if c['status'] == 'pending':
                # тот же человек уже получил вход по другой заявке (14.10: Антонова с двумя email)
                v['same_name'] = [{'no': d['claim_no'], 'email': d['email'], 'note': d['decision_note']} for d in decided
                                  if similarity(c['full_name'], d['full_name']) >= 0.9][:3]
            out.append(v)
        return {'game': ev['title'] if ev else None, 'free': len(people), 'items': out}


@org.get('/people')
def candidates(request: Request, q: str = Query('', max_length=100), user=Depends(org_user)):
    """Поиск по перенесённым участницам без входа — если подсказка не нашла (другая фамилия, опечатка)."""
    with db(request).transaction() as conn:
        ev = moved_event(conn)
        people = free_people(conn, ev['id']) if ev else []
    if q.strip():
        needle = q.strip().lower().replace('ё', 'е')
        people = [p for p in people if needle in (p['full_name'] or '').lower().replace('ё', 'е') or needle == (p['bot_id'] or '')]
    return {'items': [person_view(p) for p in people[:50]]}


class Approve(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID


@org.post('/{claim_no}/approve', dependencies=WRITE)
def approve(claim_no: int, body: Approve, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        c = conn.execute('SELECT * FROM account_claims WHERE claim_no=%s FOR UPDATE', (claim_no,)).fetchone()
        if not c:
            raise HTTPException(404, 'Not found')
        if c['status'] != 'pending':
            raise problem('claim_decided', 409)
        person = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (body.user_id,)).fetchone()
        if not person or person['account_status'] != 'imported' or person['email'] is not None or person['deleted_at'] is not None:
            raise problem('person_has_login', 409)
        ep = conn.execute('''SELECT * FROM event_participants WHERE user_id=%s AND event_id=%s''', (person['id'], c['event_id'])).fetchone()
        if not ep:
            raise problem('person_not_in_game', 409)
        if conn.execute('SELECT 1 FROM users WHERE lower(email)=%s', (c['email'].lower(),)).fetchone():
            raise problem('email_taken', 409)
        display = person['display_name'] if (person['display_name'] or '').strip() else R.name_for_site(person['full_name'])
        conn.execute('SAVEPOINT approve')
        try:
            conn.execute('''UPDATE users SET email=%s, password_hash=%s, email_verified_at=%s, account_status='active', country_code=%s, city=%s,
display_name=%s, public_works=true, public_social=true, public_rating=true WHERE id=%s''',
                         (c['email'], c['password_hash'], now, c['country_code'], c['city'], display, person['id']))
        except psycopg.errors.UniqueViolation:
            conn.execute('ROLLBACK TO SAVEPOINT approve')
            raise problem('email_taken', 409) from None
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (person['id'],))
        docs = (c['consents'] or {}).get('documents') or {}
        for kind in KINDS:
            d = docs.get(kind)
            if not d:
                continue
            conn.execute('''INSERT INTO consents(user_id,event_id,consent_type,accepted,status,document_version,legal_document_id,channel,
button_text,idempotency_key,recorded_at,metadata) VALUES (%s,%s,%s,true,'accepted',%s,%s,'web',%s,%s,%s,%s)
ON CONFLICT (idempotency_key) DO NOTHING''', (person['id'], c['event_id'], kind, d['version'], d['id'], 'Войти в кабинет — Игра 01',
                                                f"claim:{c['claim_no']}:{kind}", c['created_at'],
                                                Jsonb({'claim_no': c['claim_no'], 'adult_confirmed': True})))
        conn.execute('''UPDATE account_claims SET status='approved', matched_user_id=%s, decided_by=%s, decided_at=%s,
password_hash='-' WHERE id=%s''', (person['id'], user['id'], now, c['id']))
        audit(conn, user['id'], 'user', person['id'], 'claim_approved', {'claim_no': c['claim_no'], 'bot_name': person['full_name'],
                                                                         'claim_name': c['full_name']})
        notify(conn, person['id'], 'reg', f"claim:{c['claim_no']}",
               {'title': 'Добро пожаловать в кабинет лиги', 'text': 'Ваши итоги туров 1–2 перенесены. Задания следующих туров — здесь.',
                'route': 'game', 'event_id': str(c['event_id'])}, c['event_id'])
        return claim_view(conn.execute('SELECT * FROM account_claims WHERE id=%s', (c['id'],)).fetchone())


class Reject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    note: str = Field(min_length=2, max_length=500)


@org.post('/{claim_no}/reject', dependencies=WRITE)
def reject(claim_no: int, body: Reject, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        c = conn.execute('SELECT * FROM account_claims WHERE claim_no=%s FOR UPDATE', (claim_no,)).fetchone()
        if not c:
            raise HTTPException(404, 'Not found')
        if c['status'] != 'pending':
            raise problem('claim_decided', 409)
        c = conn.execute('''UPDATE account_claims SET status='rejected', decided_by=%s, decided_at=%s, decision_note=%s, password_hash='-'
WHERE id=%s RETURNING *''', (user['id'], now, body.note.strip(), c['id'])).fetchone()
        audit(conn, user['id'], 'account_claim', c['id'], 'claim_rejected', {'claim_no': c['claim_no']})
        return claim_view(c)


class AddOutside(BaseModel):
    model_config = ConfigDict(extra='forbid')
    league: Literal['gold', 'silver'] | None = None


@org.post('/{claim_no}/add-outside', dependencies=WRITE)
def add_outside(claim_no: int, body: AddOutside, request: Request, user=Depends(org_user)):
    """Человека нет в таблице бота (рисовала вне конкурса, тура 1 в судействе не было): новый вход и запись в Игру 01
    вне конкурса (решение 14.10). Туры 1–2 она может сдать в кабинете вне конкурса; диплом решается потом."""
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        c = conn.execute('SELECT * FROM account_claims WHERE claim_no=%s FOR UPDATE', (claim_no,)).fetchone()
        if not c:
            raise HTTPException(404, 'Not found')
        if c['status'] != 'pending':
            raise problem('claim_decided', 409)
        ev = conn.execute('SELECT * FROM events WHERE id=%s', (c['event_id'],)).fetchone()
        if not ev or not (ev['settings'] or {}).get('moved_to_kabinet'):
            raise problem('not_moved', 409)
        if conn.execute('SELECT 1 FROM users WHERE lower(email)=%s', (c['email'].lower(),)).fetchone():
            raise problem('email_taken', 409)
        conn.execute('SAVEPOINT outside')
        try:
            person = conn.execute('''INSERT INTO users(email,password_hash,email_verified_at,account_status,full_name,display_name,
country_code,city,public_works,public_social,public_rating) VALUES (%s,%s,%s,'active',%s,%s,%s,%s,true,true,true) RETURNING *''',
                                  (c['email'], c['password_hash'], now, c['full_name'], R.name_for_site(c['full_name']),
                                   c['country_code'], c['city'])).fetchone()
        except psycopg.errors.UniqueViolation:
            conn.execute('ROLLBACK TO SAVEPOINT outside')
            raise problem('email_taken', 409) from None
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (person['id'],))
        ep = conn.execute('''INSERT INTO event_participants(event_id,user_id,registration_status,eligibility_status,payment_status,
competition_status,elimination_reason,out_of_competition_at,out_of_competition_source,entry_league,joined_at)
VALUES (%s,%s,'participating','eligible','not_required','diploma_only','admin',%s,'admin',%s,%s) RETURNING *''',
                          (ev['id'], person['id'], now, body.league, now)).fetchone()
        docs = (c['consents'] or {}).get('documents') or {}
        for kind in KINDS:
            d = docs.get(kind)
            if not d:
                continue
            conn.execute('''INSERT INTO consents(user_id,event_id,consent_type,accepted,status,document_version,legal_document_id,channel,
button_text,idempotency_key,recorded_at,metadata) VALUES (%s,%s,%s,true,'accepted',%s,%s,'web',%s,%s,%s,%s)
ON CONFLICT (idempotency_key) DO NOTHING''', (person['id'], c['event_id'], kind, d['version'], d['id'], 'Войти в кабинет — Игра 01',
                                                f"claim:{c['claim_no']}:{kind}", c['created_at'],
                                                Jsonb({'claim_no': c['claim_no'], 'adult_confirmed': True})))
        conn.execute('''UPDATE account_claims SET status='approved', matched_user_id=%s, decided_by=%s, decided_at=%s,
password_hash='-', decision_note=%s WHERE id=%s''', (person['id'], user['id'], now, 'Добавлена вне конкурса', c['id']))
        audit(conn, user['id'], 'event_participant', ep['id'], 'claim_added_outside',
              {'claim_no': c['claim_no'], 'claim_name': c['full_name'], 'league': body.league})
        notify(conn, person['id'], 'reg', f"claim:{c['claim_no']}",
               {'title': 'Добро пожаловать в кабинет лиги',
                'text': 'Вы в Игре 01 вне конкурса. Работы всех туров, включая 1 и 2, можно сдать до конца Игры.',
                'route': 'game', 'event_id': str(c['event_id'])}, c['event_id'])
        return claim_view(conn.execute('SELECT * FROM account_claims WHERE id=%s', (c['id'],)).fetchone())


# ---------- Зарегистрировались сами, а не по заявке Игры 01 (14.10) ----------
# Участница из бота нашла на входе «Впервые в лиге? Заведите кабинет» и завела пустой аккаунт: её итоги туров 1–2
# остались на записи из бота, а вход — на новой. Организатор привязывает вход к записи из бота: email и пароль
# переезжают на неё, пустой аккаунт закрывается. Согласия копируются (их нельзя переносить — только дописывать).

def self_registered(conn, account_id=None):
    """Активные аккаунты, заведённые самой участницей, без единой Игры и без ролей кроме участницы."""
    return conn.execute('''SELECT u.* FROM users u
WHERE u.account_status='active' AND u.deleted_at IS NULL AND (%(id)s::uuid IS NULL OR u.id=%(id)s::uuid)
AND EXISTS (SELECT 1 FROM audit_log a WHERE a.entity_type='user' AND a.entity_id=u.id AND a.action='self_registered')
AND NOT EXISTS (SELECT 1 FROM event_participants p WHERE p.user_id=u.id)
AND NOT EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id=u.id AND r.role<>'participant')
ORDER BY u.created_at DESC LIMIT 200''', {'id': account_id}).fetchall()


def accounts_to_link(conn):
    """Сколько зарегистрировавшихся самих похожи на участницу Игры 01 без входа (есть подсказка «Это она»):
    их организатору нужно соединить. Новички без похожих ФИО внимания не требуют — в счётчик не входят."""
    ev = moved_event(conn)
    if not ev:
        return 0
    accs = self_registered(conn)
    if not accs:
        return 0
    people = [words(p['full_name']) for p in free_people(conn, ev['id'])]
    n = 0
    for a in accs:
        wa = words(a['full_name'])
        if wa and any(wb and word_similarity(wa, wb) >= 0.5 for wb in people):
            n += 1
    return n


@org.get('/accounts')
def accounts(request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        ev = moved_event(conn)
        people = free_people(conn, ev['id']) if ev else []
        out = []
        for a in self_registered(conn):
            ranked = sorted(((similarity(a['full_name'], p['full_name']), p) for p in people), key=lambda x: -x[0])
            out.append({'user_id': str(a['id']), 'full_name': a['full_name'], 'email': a['email'], 'created_at': iso(a['created_at']),
                        'suggestions': [person_view(p, s) for s, p in ranked[:3] if s >= 0.5]})
        # сначала те, кого похоже узнали в списке Игры
        out.sort(key=lambda x: -(x['suggestions'][0]['score'] if x['suggestions'] else 0))
        return {'items': out}


class LinkAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID


@org.post('/accounts/{account_id}/link', dependencies=WRITE)
def link_account(account_id: UUID, body: LinkAccount, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        ev = moved_event(conn)
        if not ev:
            raise problem('not_moved', 409)
        acc = self_registered(conn, account_id)
        if not acc:
            raise problem('account_not_linkable', 409)
        acc = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (account_id,)).fetchone()
        person = conn.execute('SELECT * FROM users WHERE id=%s FOR UPDATE', (body.user_id,)).fetchone()
        if not person or person['account_status'] != 'imported' or person['email'] is not None or person['deleted_at'] is not None:
            raise problem('person_has_login', 409)
        if not conn.execute('SELECT 1 FROM event_participants WHERE user_id=%s AND event_id=%s', (person['id'], ev['id'])).fetchone():
            raise problem('person_not_in_game', 409)
        moved_support = move_support(conn, acc['id'], person['id'])
        # пустой аккаунт закрыть: вход (email, пароль, Telegram) освобождается для записи из бота
        conn.execute('UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL', (now, acc['id']))
        # закрытый аккаунт не может быть публичным (проверка базы lr_users_deleted_not_public)
        conn.execute('''UPDATE users SET email=NULL, password_hash=NULL, telegram_id=NULL, account_status='deleted', deleted_at=%s,
public_profile=false, public_city=false, public_contacts=false, public_works=false, public_rating=false, public_social=false
WHERE id=%s''', (now, acc['id']))
        conn.execute("DELETE FROM user_roles WHERE user_id=%s", (acc['id'],))
        display = (acc['display_name'] or '').strip() or (person['display_name'] or '').strip() or R.name_for_site(person['full_name'])
        conn.execute('''UPDATE users SET email=%s, password_hash=%s, email_verified_at=coalesce(%s, %s), account_status='active',
telegram_id=coalesce(telegram_id, %s), country_code=coalesce(country_code, %s), city=coalesce(city, %s), display_name=%s,
public_works=true, public_social=true, public_rating=true WHERE id=%s''',
                     (acc['email'], acc['password_hash'], acc['email_verified_at'], now, acc['telegram_id'], acc['country_code'],
                      acc['city'], display, person['id']))
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (person['id'],))
        conn.execute('''INSERT INTO consents(user_id,event_id,consent_type,accepted,status,document_version,legal_document_id,channel,
button_text,idempotency_key,recorded_at,metadata)
SELECT %s, event_id, consent_type, accepted, status, document_version, legal_document_id, channel, button_text,
  'link:' || id::text, recorded_at, metadata || jsonb_build_object('linked_from', %s::text)
FROM consents WHERE user_id=%s ON CONFLICT (idempotency_key) DO NOTHING''', (person['id'], str(acc['id']), acc['id']))
        audit(conn, user['id'], 'user', person['id'], 'account_linked',
              {'from_account': str(acc['id']), 'account_name': acc['full_name'], 'bot_name': person['full_name'],
               'support_threads_moved': moved_support})
        notify(conn, person['id'], 'reg', f"link:{acc['id']}",
               {'title': 'Ваш кабинет соединён с Игрой 01', 'text': 'Итоги туров 1–2 перенесены. Задания следующих туров — здесь.',
                'route': 'game', 'event_id': str(ev['id'])}, ev['id'])
        return {'user_id': str(person['id']), 'full_name': person['full_name']}


# ---------- Две записи одного человека (14.10, Антонова) ----------
# Две заявки с разными email: одна «Это она» (запись из бота с итогами), другая — «вне конкурса» (новый вход).
# Человек входит во вторую. Организатор переносит вход (email, пароль) на запись из бота; лишняя запись закрывается,
# её участие в Игре удаляется. Только если в лишней записи нет работ и итогов, а в основную ещё никто не входил.

class MergeIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    from_user_id: UUID
    into_user_id: UUID
    # 17.10: в основную запись уже входили (например, с опечаткой в email), а человек завёл новый аккаунт с верным email.
    # Организатор явно подтверждает замену входа основной записи — старый email и пароль перестают работать.
    replace_login: bool = False
    reason: str | None = Field(default=None, max_length=500)


def move_support(conn, from_id, to_id):
    """Обращения в поддержку закрываемого аккаунта переходят на основную запись вместе с входом (14.10: Дина написала
    в поддержку до соединения — соединить было нельзя). Обращения о работах закрываемого аккаунта сюда не попадают:
    у него нет работ (проверяется до вызова)."""
    conn.execute('''UPDATE support_messages SET author_user_id=%s WHERE author_user_id=%s
AND support_thread_id IN (SELECT id FROM support_threads WHERE user_id=%s)''', (to_id, from_id, from_id))
    return conn.execute('UPDATE support_threads SET user_id=%s WHERE user_id=%s', (to_id, from_id)).rowcount


def has_works(conn, user_id):
    return conn.execute('''SELECT 1 FROM event_participants p WHERE p.user_id=%s AND (
  EXISTS (SELECT 1 FROM submissions s WHERE s.event_participant_id=p.id)
  OR EXISTS (SELECT 1 FROM round_results r WHERE r.event_participant_id=p.id)) LIMIT 1''', (user_id,)).fetchone() is not None


@org.post('/merge', dependencies=WRITE)
def merge(body: MergeIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    if body.from_user_id == body.into_user_id:
        raise problem('same_person', 409)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        a = conn.execute('SELECT * FROM users WHERE id=%s AND deleted_at IS NULL FOR UPDATE', (body.from_user_id,)).fetchone()
        b = conn.execute('SELECT * FROM users WHERE id=%s AND deleted_at IS NULL FOR UPDATE', (body.into_user_id,)).fetchone()
        if not a or not b:
            raise HTTPException(404, 'Not found')
        if a['account_status'] != 'active' or not a['email']:
            raise problem('merge_from_no_login', 409)
        if conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role<>'participant'", (a['id'],)).fetchone():
            raise problem('account_not_linkable', 409)
        if has_works(conn, a['id']):
            raise problem('merge_from_has_works', 409)
        logged_in = conn.execute('SELECT 1 FROM auth_sessions WHERE user_id=%s LIMIT 1', (b['id'],)).fetchone() is not None
        reason = (body.reason or '').strip() or None
        if logged_in and not body.replace_login:
            raise problem('merge_into_logged_in', 409)    # в основную уже входили — без явного подтверждения её вход не трогаем
        if logged_in and not reason:
            raise problem('reason_required')
        if conn.execute("SELECT 1 FROM user_roles WHERE user_id=%s AND role<>'participant'", (b['id'],)).fetchone():
            raise problem('account_not_linkable', 409)    # вход судьи или организатора так не заменить
        moved_support = move_support(conn, a['id'], b['id'])
        if logged_in:                                     # старый вход основной записи закрывается везде
            conn.execute('UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL', (now, b['id']))
            conn.execute('UPDATE auth_tokens SET used_at=%s WHERE user_id=%s AND used_at IS NULL', (now, b['id']))
        # участие лишней записи: убрать (заданий без работ — тоже); не выходит — снять с Игры
        removed, cancelled = [], []
        for ep in conn.execute('SELECT * FROM event_participants WHERE user_id=%s', (a['id'],)).fetchall():
            conn.execute('SAVEPOINT merge_ep')
            try:
                conn.execute('DELETE FROM participant_assignments WHERE event_participant_id=%s', (ep['id'],))
                conn.execute('DELETE FROM event_participants WHERE id=%s', (ep['id'],))
                conn.execute('RELEASE SAVEPOINT merge_ep')
                removed.append(str(ep['event_id']))
            except psycopg.errors.IntegrityError:
                conn.execute('ROLLBACK TO SAVEPOINT merge_ep')
                conn.execute("UPDATE event_participants SET registration_status='cancelled' WHERE id=%s", (ep['id'],))
                cancelled.append(str(ep['event_id']))
        conn.execute('UPDATE auth_sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL', (now, a['id']))
        conn.execute('''UPDATE users SET email=NULL, password_hash=NULL, telegram_id=NULL, account_status='deleted', deleted_at=%s,
public_profile=false, public_city=false, public_contacts=false, public_works=false, public_rating=false, public_social=false
WHERE id=%s''', (now, a['id']))
        conn.execute('DELETE FROM user_roles WHERE user_id=%s', (a['id'],))
        conn.execute('''UPDATE users SET email=%s, password_hash=%s, email_verified_at=coalesce(%s, %s), account_status='active',
telegram_id=coalesce(telegram_id, %s), country_code=coalesce(%s, country_code), city=coalesce(%s, city) WHERE id=%s''',
                     (a['email'], a['password_hash'], a['email_verified_at'], now, a['telegram_id'], a['country_code'], a['city'], b['id']))
        conn.execute("INSERT INTO user_roles(user_id,role) VALUES (%s,'participant') ON CONFLICT DO NOTHING", (b['id'],))
        conn.execute('''INSERT INTO consents(user_id,event_id,consent_type,accepted,status,document_version,legal_document_id,channel,
button_text,idempotency_key,recorded_at,metadata)
SELECT %s, event_id, consent_type, accepted, status, document_version, legal_document_id, channel, button_text,
  'merge:' || id::text, recorded_at, metadata || jsonb_build_object('merged_from', %s::text)
FROM consents WHERE user_id=%s ON CONFLICT (idempotency_key) DO NOTHING''', (b['id'], str(a['id']), a['id']))
        audit(conn, user['id'], 'user', b['id'], 'accounts_merged',
              {'from_user': str(a['id']), 'from_name': a['full_name'], 'old_email_dropped': b['email'],
               'removed_from_games': removed, 'cancelled_in_games': cancelled, 'support_threads_moved': moved_support,
               'replaced_login': logged_in, 'reason': reason})
        return {'user_id': str(b['id']), 'full_name': b['full_name'], 'removed': removed, 'cancelled': cancelled}
