# Лента данных FPL для инструмента контента

Только чтение. Данные лиги для постов в соцсетях: Игры и туры, итоги опубликованных туров и Игр, FPL Rating, очки FPL,
статистика судейства. Изменить что-либо через ленту нельзя.

- Адрес: `https://facepaintingleague.com/kabinet/api/feed/...`
- Ключ выдаёт организатор: кабинет организатора → «Ключи для данных». Ключ показывается один раз; храните его
  в переменной окружения `FPL_FEED_KEY`, не в коде и не в постах.
- Каждый запрос: заголовок `Authorization: Bearer $FPL_FEED_KEY`. Без ключа, с неверным или отозванным ключом — `401`.
- Не больше **120 запросов в минуту** на ключ, иначе `429` (подождите минуту, заголовок `Retry-After`).
- Данные на сервере обновляются сразу; кешировать ответы дольше 10 минут не нужно.

```sh
export FPL_FEED_KEY=fplf_…        # ключ из кабинета
F=https://facepaintingleague.com/kabinet/api/feed
curl -sS -H "Authorization: Bearer $FPL_FEED_KEY" "$F/games"
```

## Главное правило публикации (Правила лиги, п. 7.3)

Пока Игра идёт (`running: true`), **нельзя публиковать баллы и места других участниц и общий рейтинговый список**.
Можно: TOP WORK с названием лиги («TOP WORK Gold»), общие цифры (сколько участниц, сколько работ сдано), анонсы туров.
После завершения Игры (`finished: true`, итоги — `results_published: true`) — итоги по опубликованным данным.

Человека (имя, работу, рейтинг) в пост — **только если `can_post_social: true`**. Фото работы — только из `photos`
(они есть, только если автор разрешил показ работ). У кого нет согласия на публикацию, `name: null` — такую участницу
не упоминать вовсе. Очки FPL — не рейтинг: они копятся за итог Игры и TOP WORK и на рейтинг не влияют.

Этот текст приходит и в самих данных — поле `rules_note`.

## Участница в ленте

```json
{"id": "p_3f2a9c0d1e4b5a6f7c8d", "name": "Анна Иванова", "city": null, "country": null}
```

- `id` — постоянный непрозрачный id (одна и та же участница — один id во всех ответах).
- `name` — публичное имя (или «Имя Фамилия»), только при согласии на публикацию; иначе `null`.
- `city`, `country` — только если участница открыла их для анкеты мастера.
- В ленте никогда нет: email, телефона, ФИО, контактов, обращений, судей, отдельных голосов, адресов.

Флаги рядом с участницей:
- `can_show_work` — работу можно показывать (есть `photos`);
- `can_post_social` — участницу можно упоминать в соцсетях лиги;
- `can_publish` (в рейтинге) — рейтинг участницы можно публиковать.

## Запросы

### `GET /games` — сезоны, Игры, туры

```json
{"schema": "fpl.feed.games.v1", "rules_note": "…",
 "seasons": [{"no": 1, "name": "Сезон 1", "status": "active"}],
 "games": [{"id": "…", "title": "Игра 01", "season_no": 1, "game_no": 1, "status": "active",
   "running": true, "finished": false, "results_published": false, "site_rating_live": false,
   "starts_at": "…", "ends_at": "…",
   "participants": {"total": 100, "in_competition": 80, "outside": 20, "out": 0,
                    "by_league": {"gold": {"total": 51, "in_competition": 40, "outside": 11, "out": 0}}},
   "rounds": [{"no": 3, "title": "Тур 3", "phase": "judging", "from_bot": false, "results_published": false,
               "opens_at": "…", "deadline": "…", "judging_deadline": "…",
               "league_dates": [{"league": "silver", "opens_at": "…", "deadline": "…"}],
               "submitted": {"total": 77, "late": 2, "by_league": {"gold": 37, "silver": 40}},
               "results": {"total": 0, "advanced": 0}, "top_work": {},
               "judging": {"works": 37, "done": 120, "total": 222}}]}]}
```

`phase`: `plan` (впереди), `open` (идёт сдача), `closed` (приём закрыт, ждёт судейства), `judging`, `published`
(итоги опубликованы), `bot` (тур прошёл в боте). `top_work` — сколько TOP WORK в каждой лиге.

### `GET /games/{id}/rounds/{no}/results` — итоги опубликованного тура

Только для туров с опубликованными итогами (и туров из бота), иначе `404`.

```json
{"game": {"id": "…", "running": true, "…": "…"}, "round": {"no": 2, "title": "Бабочка", "from_bot": true},
 "results": [{"participant": {"id": "p_…", "name": "Анна Иванова", "city": null, "country": null},
   "league": "gold", "score": 88.65, "place": 1, "pool_size": 48, "top_work": true, "advanced": true,
   "can_show_work": true, "can_post_social": true,
   "photos": [{"id": "…", "url": "https://…/kabinet/api/feed/media/…?size=view", "thumb_url": "…?size=thumb",
               "width": 1600, "height": 2000}]}]}
```

`place` — место в своей лиге. Пока Игра идёт, `score` и `place` — только для расчётов и общих цифр, не для постов.

### `GET /games/{id}/standings` — итоги Игры

Пока итоги не опубликованы — `rows: []` и `game.results_published: false`.

```json
{"game": {"finished": true, "results_published": true},
 "rows": [{"participant": {"…": "…"}, "can_show_work": true, "can_post_social": true, "league": "gold",
   "league_rank": 1, "award_place": 1, "overall_rank": 1, "top10": true, "top25": false, "excluded": null,
   "finalist": true, "path": 88.16, "final": 83, "total": 85.07, "top_works": 3, "counted": true, "diploma": true,
   "points": {"total": 23, "items": [{"reason_code": "game_result", "reason": "1 место…", "amount": 20}]}}]}
```

`award_place` — 1–3 место в лиге; `path` — средний балл туров, `final` — финал, `total` — итог.

### `GET /rating` — FPL Rating сейчас

```json
{"games_running": ["Игра 01"], "rated": 100,
 "players": [{"participant": {"…": "…"}, "can_publish": true, "can_post_social": true,
   "rank": 1, "rating": 736, "status": "calibrating", "calibration": 2, "league": "silver"}]}
```

Место (`rank`) — среди всех, у кого есть рейтинг. `status`: `calibrating` (калибровка, `calibration` из 3) или
`established`. Пока в `games_running` есть Игра, общий список рейтинга не публикуется (п. 7.3).

### `GET /rating/history?game={id}` — изменения рейтинга по турам Игры

```json
{"participants": [{"participant": {"…": "…"}, "can_publish": true,
   "rounds": [{"round_no": 1, "method": "initial_seeding", "before": null, "after": 526, "delta": null},
              {"round_no": 2, "method": "pairwise_elo", "before": 526, "after": 590, "delta": 64}]}]}
```

### `GET /points` — очки FPL

```json
{"participants": [{"participant": {"…": "…"}, "can_post_social": true, "total": 23,
   "games": [{"game_id": "…", "title": "Игра 01",
              "items": [{"reason_code": "top_work", "reason": "TOP WORK Gold · Игра 01", "amount": 1, "at": "…"}]}]}]}
```

### `GET /stats?game={id}` — судейство (без судей)

```json
{"games": [{"game_id": "…", "title": "Игра 01", "rounds": [{"no": 3, "results_published": true,
   "pools": [{"league": "gold", "method": "pairwise", "works": 37, "judges": 3, "comparisons": 222, "votes": 222,
              "tie_break_votes": 0, "criteria": 0, "criteria_scores": 0}],
   "totals": {"works": 37, "votes": 222, "criteria_scores": 0}}]}]}
```

`game` можно не указывать — тогда все Игры.

### `GET /media/{id}?size=view|thumb` — фото работы

Адрес берите из `photos[].url` (с тем же ключом). Оригинал не отдаётся. Фото работы без разрешения автора — `404`.

```sh
curl -sS -H "Authorization: Bearer $FPL_FEED_KEY" -o work.jpg "<photos[0].url>"
```

## Пример: кого можно упомянуть в посте про TOP WORK тура

```sh
curl -sS -H "Authorization: Bearer $FPL_FEED_KEY" "$F/games/$GAME/rounds/3/results" |
  jq '.results[] | select(.top_work and .can_post_social) | {name: .participant.name, league, photo: .photos[0].url}'
```

Подпись — с лигой: «TOP WORK Gold», «TOP WORK Silver», «TOP WORK Bronze».
