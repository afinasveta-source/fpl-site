# Кабинет FPL (backend + страницы)

Личные кабинеты участника, организатора, судьи и модератора. Пишется заново по прототипу 12.10.2026
(`prototypes/kabinet-2026-10-12/`, ветка `kabinet-prototip`) на базе сервера (`server/db/schema/001…`).
Вход и пароли перенесены из backend Codex вместе с его тестами.

## Этап 1 (12.10.2026)
- Вход по email и паролю (Argon2id), сессия в cookie (HttpOnly, SameSite=Strict, `__Host-` на сервере), выход.
- Первый администратор — один раз, на странице `/kabinet/setup`, по ключу сервера (ключ приёмника данных).
  На сервере хранится только sha256 этого ключа. Запасной путь — `python -m kabinet.cli bootstrap-admin`.
- Установка и сброс пароля по ссылке (письма пока выключены: `FPL_MAIL_MODE=disabled`), профиль (публичное имя, полное имя, город), роли.
- Ограничение попыток входа, журнал действий (`audit_log`), запрет записи с чужого сайта (проверка Origin).

## Сервер
`server/kabinet/fpl-kabinet-setup` (запускается из `fpl-ops`): пользователь `fplkab`, служба `fpl-kabinet` на 127.0.0.1:8100,
роль базы `fpl_kabinet` — только данные (без права менять таблицы), nginx `/kabinet/`. Итог — поле `kabinet`
в `/data/server-status.json`.

## Проверка
```sh
pip install -r kabinet/requirements-dev.txt
cd kabinet && FPL_TEST_DSN=postgresql://USER:PASS@127.0.0.1:5432/ANY_test python -m pytest -q
```
Тесты создают отдельную базу из `server/db/schema/*.sql` — той же схемы, что на сервере — и удаляют её после.
Есть проверка, что в репозитории нет ключей и паролей (он открытый).
