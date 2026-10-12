# fpl-site — сайт Face Painting League (facepaintingleague.com)

- `src/` — исходные страницы (RU) и `assets/` (общий CSS, consent.js, шрифты, файлы подтверждения поисковиков).
- `build/` — сборка, запуск одной командой `bash build/build.sh` (нужен python3 + beautifulsoup4): `build_site.py` → `i18n/build_en.py` (английская версия) → `seo.py` (EN в корне, RU в /ru/, мета, sitemap) → `links.py` (настоящие ссылки: бот, Instagram, соцсети). Пути — в `build/paths.py`; `FPL_DIST=<папка>` собирает в другую папку.
- `build/privacy/`, `build/feedback/` — политика и «Пожелания лиге»: текст и стили страниц на оболочке «О лиге». RU: `python3 build/<папка>/assemble.py` → `src/fpl-<папка>.html` (политика в `src/` правлена вручную и разошлась с `build/privacy/ru.html` — её не пересобирать без сверки); EN собирается в `i18n/build_en.py`. Форма пожеланий шлёт `POST /kabinet/api/public/feedback` (кабинет на том же домене).
- `dist/` — готовый сайт, как он должен лежать на сервере (сборка 11.10.2026).
- `server/` — приёмник данных из бота и шаблон cloud-init сервера (ключ скрыт; настоящий ключ только у Светланы). `server/ops/` — канал обновлений сервера (`apply.sh`, `fpl-sync`, `pack.sh` → `out/fpl-ops.tgz`).
- `tests/site-check.js` — автоматическая проверка (Playwright): `node tests/site-check.js <базовый URL>`. `bash tests/check-build.sh` — та же проверка по локальной сборке перед push (код выхода 1 — есть поломки; заглушки контента выкладку не блокируют).
- `prototypes/` — прототип кабинета участника.

## Выкладка
Сервер раз в 5 минут спрашивает у GitHub номер последнего коммита в `main`; если он новый — скачивает архив репозитория и выкладывает папку `dist/`. Репозиторий публичный, токен не нужен.

1. Правки — в `src/` (или в `build/`).
2. `bash build/build.sh` — собрать `dist/`.
3. `bash tests/check-build.sh` — должно быть «Поломки: 0».
4. Коммит и push в `main` (вместе с `dist/` — сервер берёт готовую сборку, сам ничего не собирает).
5. Через ~5 минут: `https://facepaintingleague.com/version.txt` = номер коммита; затем `node tests/site-check.js` по живому сайту (из облака сайт недоступен — проверка через браузер Светланы).

Откат: `git revert` и push — или в `/etc/fpl.env` на сервере `ZIP_URL=$ZIP_URL_STORAGE`, убрать `SHA_URL` и `SITE_DIR` (вернётся забор архива из хранилища).

Секретов в репозитории нет и быть не должно.
Подробности: документы проекта «Чат бот» — claude/fpl-server-selectel-status-2026-10-05.md, claude/fpl-sitecheck/README.md, Claude Doc «План тестирования сайта FPL».
