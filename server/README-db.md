# База сайта на сервере (с 11.10.2026)

PostgreSQL на сервере сайта (`fpl-site-2`), доступна только с самого сервера (127.0.0.1).
Устанавливается и обновляется пакетом `fpl-ops.tgz` (`server/ops/pack.sh`).

- Схема — та же, что у backend кабинета (репозиторий face-painting-league): `server/db/schema/001…004`,
  номер версии в `alembic_version` (004). Новые миграции backend добавлять сюда же по порядку.
- 004 (12.10.2026): скидки по итогам Игры и связь с InSales (`reward_rules`, `reward_codes`, `events.reward_multi_mode`),
  пары и группы в задании (`task_groups`, `task_group_members`, до 6 человек), набор автоматических уведомлений
  (`notification_rules`, 28 правил), призы Игры (`event_prizes`), материал от организатора (`exchange_items.provided_by`),
  «судья не участник этой Игры» в обе стороны. Проверка: `python3 server/db/tests/test_004.py`.
  Ту же миграцию нужно добавить в backend (alembic 004), когда будет доступ к его репозиторию.
- Пароль генерируется на сервере: `/etc/fpl-db.env` (только root). В репозитории и хранилище его нет.
- `site_views.sql` — публичный слой: человек виден, только если последнее согласие нужного типа «accepted»
  (`publication` — рейтинг и работы, `public_profile` — анкета, `public_contacts` — контакты),
  включён флаг в профиле и профиль не удалён. Места в рейтинге считаются по всем, скрытые не сдвигают места.
- `fpl-db-export` (cron, 10 мин) → `/data/rating.json`, `games.json`, `certificates.json`, `masters.json`.
- `fpl-db-backup` (03:17 ночью) → `/var/backups/fpl`, 14 копий. Дальше — копия в закрытый бакет S3.
- `fpl-status` (10 мин) → `/data/server-status.json`: версия сайта и схемы, число таблиц и пользователей,
  размер базы, последняя копия, результат последнего fpl-ops, свободный диск и память.
- Если `apply.sh` упал: в статусе `ops: error … line N`, пакет применится заново через 5 минут.
- Backend Codex в режиме PROD требует отдельный сервер базы с `sslmode=verify-full` — при запуске кабинета
  на этом сервере эту проверку нужно ослабить для локального подключения.

## Перенос из SaleBot (fpl-db-import, с 11.10.2026)
- Блок бота «Сайт: выгрузка в базу» (текст генерирует `server/salebot/make_blocks.py export`, сохраняет Светлана)
  шлёт таблицы `mg_*` частями в закрытые наборы `private-sb-<таблица>` и последним — `private-sb-manifest`
  (число строк каждой таблицы).
- `fpl-db-import` (cron, каждые 5 минут) переносит снимок, только когда пришли все таблицы и число строк совпало,
  и только новый снимок (sha256). Одна транзакция: всё или ничего; пакет и замечания — `import_batches`, `import_issues`.
  Повтор не дублирует (`import_row_map`). После переноса сразу запускается `fpl-db-export`.
- Правила переноса: лига Игры 01 А → gold, Б → silver; тур публикуется на сайте при состоянии
  `confirmed / published / locked` в `mg_rating_rounds`; жюри не участник; согласие на публикацию —
  последнее решение по `publication_consent`; батч рейтинга, удалённый в боте, гасится (`void`).
- Сводка без имён: `/data/import-status.json`; в `server-status.json` — `import_status`, `last_import`.
- На сайт по турам идут только размеры лиг и TOP WORK (имя — при согласии). Баллы и места других — нет (Правила 7.3).
- Проверки: `python3 server/db/tests/test_import.py`, `python3 server/db/tests/test_e2e_salebot.py`
  (нужны локальный PostgreSQL и `/etc/fpl-db.env`).
- Перед первым запуском сверить колонки в `make_blocks.py` с живой схемой SaleBot (особенно `mg_client_channels`,
  `mg_public_names`) и значения лиг в `mg_round_snapshot`.
