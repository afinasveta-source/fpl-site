"""Итоги Игры: страница организатора (формат, черновик, равные, публикация)."""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from kabinet.org.common import WRITE, audit, db, locked_admin, now_of, org_user, problem
from kabinet.org.games import load_event
from . import service as S

router = APIRouter(prefix='/api/org', tags=['organizer'])


class Places(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gold: list[int] | None = None
    silver: list[int] | None = None
    bronze: list[int] | None = None

    @field_validator('gold', 'silver', 'bronze')
    @classmethod
    def three(cls, v):
        if v is not None and (len(v) != 3 or any(x < 0 or x > 1000 for x in v)):
            raise ValueError('three values 0..1000')
        return v


class Points(BaseModel):
    model_config = ConfigDict(extra='forbid')
    places: Places | None = None
    top10: int | None = Field(default=None, ge=0, le=1000)
    top25: int | None = Field(default=None, ge=0, le=1000)
    completion: int | None = Field(default=None, ge=0, le=1000)
    top_work: int | None = Field(default=None, ge=0, le=1000)


class FormatIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    final_round: int | None = Field(default=None, ge=1, le=99)
    no_final: bool = False
    path_rounds: list[int] = Field(default_factory=list, max_length=50)
    path_weight: int = Field(default=40, ge=0, le=100)
    points: Points | None = None


@router.get('/events/{event_id}/results')
def results(event_id: UUID, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        return S.view(conn, load_event(conn, event_id), now_of(request))


@router.put('/events/{event_id}/results/format', dependencies=WRITE)
def put_format(event_id: UUID, body: FormatIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        # формат итогов объявляется до Игры (Правила, 24.09) — после старта не меняется
        if e['status'] not in ('draft', 'registration'):
            raise problem('locked_after_start', 409)
        nos = S.round_nos(conn, e['id'])
        final = None if body.no_final else body.final_round
        if final is not None and final not in nos:
            raise problem('unknown_round')
        if any(n not in nos for n in body.path_rounds):
            raise problem('unknown_round')
        path = sorted({n for n in body.path_rounds if n != final})
        if final is None and not path:
            raise problem('no_rounds')
        values = {'final_round': final, 'path_rounds': path, 'path_weight': body.path_weight}
        if body.points is not None:
            pts = body.points.model_dump(exclude_none=True)
            if 'places' in pts:
                pts['places'] = {k: v for k, v in pts['places'].items() if v is not None}
            values['points'] = pts
        e = S.save(conn, e, values)
        audit(conn, user['id'], 'event', e['id'], 'results_format_changed', values)
        return S.view(conn, e, now_of(request))


class TieIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    league: Literal['bronze', 'silver', 'gold']
    order: list[UUID] = Field(min_length=2, max_length=20)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def trim(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('reason')
        return v


@router.post('/events/{event_id}/results/tie', dependencies=WRITE)
def tie(event_id: UUID, body: TieIn, request: Request, user=Depends(org_user)):
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        e = S.save_tie_order(conn, e, body.league, body.order, body.reason, user['id'], now_of(request))
        return S.view(conn, e, now_of(request))


@router.post('/events/{event_id}/results/publish', dependencies=WRITE)
def publish(event_id: UUID, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        e = load_event(conn, event_id, lock=True)
        try:
            with conn.transaction():
                summary = S.publish(conn, e, user['id'], now)
        except psycopg.errors.UniqueViolation:
            raise problem('diploma_number_taken', 409) from None
        out = S.view(conn, load_event(conn, event_id), now)
        out['summary'] = summary
        return out
