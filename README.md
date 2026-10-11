# fpl-site — сайт Face Painting League (facepaintingleague.com)

- `src/` — исходные страницы (RU) и `assets/` (общий CSS, consent.js, шрифты, файлы подтверждения поисковиков).
- `build/` — сборка: `build_site.py` → `i18n/build_en.py` (английская версия) → `seo.py` (EN в корне, RU в /ru/, мета, sitemap) → `links.py` (настоящие ссылки: бот, Instagram, соцсети; архив). В скриптах зашиты пути старой среды (`/mnt/user-data/outputs`, scratchpad) — при первом запуске заменить на пути репозитория.
- `dist/` — готовый сайт, как он должен лежать на сервере (сборка 11.10.2026).
- `server/` — приёмник данных из бота и шаблон cloud-init сервера (ключ скрыт; настоящий ключ только у Светланы).
- `tests/site-check.js` — автоматическая проверка (Playwright): `node tests/site-check.js <базовый URL>`.
- `prototypes/` — прототип кабинета участника.

Секретов в репозитории нет и быть не должно.
Подробности: документы проекта «Чат бот» — claude/fpl-server-selectel-status-2026-10-05.md, claude/fpl-sitecheck/README.md, Claude Doc «План тестирования сайта FPL».
