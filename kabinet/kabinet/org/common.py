"""Общее для кабинета организатора: доступ, время, журнал, уведомления, проверка дат.

Доступ — только администратору (роль admin) по сессии браузера. Каждая запись идёт в одной транзакции
с повторной проверкой роли под блокировкой (require_admin): снятая роль или приостановленный аккаунт
перестают действовать сразу, даже если страница была открыта раньше.
"""
from datetime import datetime

from fastapi import Depends, HTTPException, Request

from kabinet.auth.service import require_admin
from kabinet.participation import game as G
from kabinet.participation.views import iso
from kabinet.web.routes import browser_user, same_origin

LEAGUES = ('bronze', 'silver', 'gold')
audit = G.audit
notify = G.notify
Jsonb = G.Jsonb
__all__ = ['LEAGUES', 'audit', 'notify', 'Jsonb', 'iso', 'org_user', 'WRITE', 'db', 'now_of', 'locked_admin',
           'problem', 'aware', 'later', 'person_name']


def org_user(user=Depends(browser_user)):
    if 'admin' not in user['roles']:
        raise HTTPException(403, 'organizer_only')
    return user


# Изменения — только со страницы самого кабинета (проверка Origin), как у участника.
WRITE = [Depends(same_origin)]


def db(request: Request):
    return request.app.state.db


def now_of(request: Request):
    return request.app.state.clock()


def locked_admin(conn, actor):
    """Роль администратора ещё действует (под блокировкой аккаунта на время транзакции)."""
    require_admin(conn, actor)


def problem(code, status=422):
    """Понятная ошибка для страницы: код, который она переводит в текст."""
    return HTTPException(status, code)


def aware(value, field):
    """Время только с часовым поясом: «12:00» без пояса — непонятно чьё."""
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
        raise problem(f'{field}_timezone')
    return value


def later(a, b):
    """a позже b (пустые значения не сравниваются)."""
    return a is None or b is None or a > b


def person_name(row):
    # Организатору важнее ФИО; публичное имя — если ФИО нет.
    return row.get('full_name') or row.get('display_name') or row.get('email') or 'Без имени'
