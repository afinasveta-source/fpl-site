"""Кабинет организатора: ключи для данных (16.10) — доступ внешнего инструмента контента к ленте /api/feed (только чтение).

Ключ показывается один раз при создании; в базе — только sha256 и начало ключа (чтобы узнать его в списке).
Отозвать — сразу перестаёт действовать. Создание и отзыв — в журнале.
"""
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.feed import key_hash
from .common import WRITE, audit, db, iso, locked_admin, org_user, person_name
from .games import clean_text

router = APIRouter(prefix='/api/org/feed-keys', tags=['organizer'])
PREFIX = 'fplf_'


def key_view(k):
    return {'id': str(k['id']), 'name': k['name'], 'comment': k['comment'], 'hint': k['key_hint'] + '…',
            'created_at': iso(k['created_at']), 'created_by': person_name(k) if k.get('full_name') or k.get('email') else None,
            'last_used_at': iso(k['last_used_at']), 'use_count': k['use_count'],
            'revoked_at': iso(k['revoked_at']), 'active': k['revoked_at'] is None}


def all_keys(conn):
    return [key_view(k) for k in conn.execute('''SELECT k.*, u.full_name, u.display_name, u.email FROM feed_keys k
LEFT JOIN users u ON u.id=k.created_by ORDER BY (k.revoked_at IS NULL) DESC, k.created_at DESC''')]


@router.get('')
def keys(request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return {'keys': all_keys(conn)}


class KeyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator('name')
    @classmethod
    def trim_name(cls, value):
        return clean_text(value, required=True)

    @field_validator('comment')
    @classmethod
    def trim_comment(cls, value):
        return clean_text(value)


@router.post('', status_code=201, dependencies=WRITE)
def create(body: KeyIn, request: Request, user=Depends(org_user)):
    raw = PREFIX + secrets.token_urlsafe(32)          # 32 случайных байта
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        k = conn.execute('''INSERT INTO feed_keys(name,comment,key_hash,key_hint,created_by) VALUES (%s,%s,%s,%s,%s) RETURNING *''',
                         (body.name, body.comment, key_hash(raw), raw[:9], user['id'])).fetchone()
        audit(conn, user['id'], 'feed_key', k['id'], 'feed_key_created', {'name': body.name})
        return {'key': raw, 'item': key_view(k), 'keys': all_keys(conn)}


@router.post('/{key_id}/revoke', dependencies=WRITE)
def revoke(key_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        k = conn.execute('''UPDATE feed_keys SET revoked_at=coalesce(revoked_at, now()), revoked_by=coalesce(revoked_by, %s)
WHERE id=%s RETURNING *''', (user['id'], key_id)).fetchone()
        if not k:
            raise HTTPException(404, 'Not found')
        audit(conn, user['id'], 'feed_key', key_id, 'feed_key_revoked', {'name': k['name']})
        return {'keys': all_keys(conn)}
