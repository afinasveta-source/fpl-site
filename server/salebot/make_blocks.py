#!/usr/bin/env python3
"""Текст калькулятора для двух служебных блоков SaleBot (проект 874007).

  python3 server/salebot/make_blocks.py export   → блок «Сайт: выгрузка в базу» (команда «Сайт: выгрузить базу»)
  python3 server/salebot/make_blocks.py photos   → блок «Сайт: архив фото»     (команда «Сайт: архив фото»)

Блоки сохраняет Светлана (Claude не сохраняет блоки с запросами к таблицам с личными данными).
Перед генерацией: сверить колонки ниже с живой схемой (SQL-консоль: SELECT sql FROM sqlite_master WHERE name=…)
и число частей PARTS с текущим числом строк (части с запасом; пустые части допустимы).

Как работает выгрузка: каждая таблица уходит частями в закрытый набор private-sb-<таблица>
(POST /api/ingest?name=…&part=i&parts=n, ключ — константа проекта site_ingest_key), последним —
private-sb-manifest с числом строк. Сервер переносит снимок в базу, когда пришло всё (fpl-db-import).
Ответ блока — список «таблица: строк / ответ сервера», чтобы молчаливый сбой был виден.
"""
import sys

URL = 'https://facepaintingleague.com/api/ingest?name='
PART_ROWS = 250

# таблица → (колонки, частей). Колонки — по документам проекта; сверить перед сохранением блока.
EXPORT = {
    'mg_person_names': (['client_id', 'last_name', 'first_name', 'middle_name', 'no_middle_name', 'full_name'], 1),
    'mg_public_names': (['client_id', 'public_name'], 1),
    'mg_client_channels': (None, 1),  # колонки неизвестны — заполнить по схеме
    'mg_legal_documents': (['doc_type', 'version', 'title', 'published_on', 'part_no', 'body', 'is_current'], 1),
    'mg_legal_acceptances': (['id', 'client_id', 'doc_type', 'version', 'status', 'accepted_at_utc', 'accepted_unix',
                              'channel', 'button_text', 'marathon', 'context'], 4),
    'mg_round_snapshot': (['marathon', 'round_no', 'client_id', 'season', 'league', 'metric_type', 'metric_raw', 'metric_max',
                           'display_score', 'display_formula_version', 'place', 'average_place', 'tie_group_size',
                           'pool_size', 'top_work', 'participant_status', 'rating_before', 'calibration_before',
                           'rules_version', 'created_at'], 3),
    'mg_rating_rounds': (['marathon', 'round_no', 'league', 'state', 'batch_id', 'pool_size', 'calculated_at',
                          'confirmed_at', 'published_at'], 1),
    'mg_rating_events': (['event_id', 'marathon', 'season', 'round_no', 'client_id', 'event_type', 'rating_before',
                          'rating_after', 'delta', 'k_factor', 'cap', 'expected', 'scored', 'comparisons',
                          'calibration_before', 'calibration_after', 'league', 'batch_id', 'formula_version', 'reason',
                          'created_at'], 4),
    'mg_rating_players': (['client_id', 'rating_current', 'rating_official', 'peak_rating', 'calibration_count',
                           'rating_status', 'league_current', 'league_next', 'global_rank', 'active_status',
                           'last_marathon', 'last_played_at', 'formula_version', 'updated_at'], 1),
}

# фото: набор → SQL, возвращающий key (постоянный идентификатор работы) и url (ссылка на фото сейчас).
# Колонки и условия — сверить по схеме перед сохранением.
PHOTOS = {
    'private-photos-r1': ("SELECT 'fpl_game1_2026/r1/' || w.owner_id AS key, w.image AS url FROM mg_works w "
                          "JOIN mg_runs r ON r.id = w.run_id WHERE r.marathon = 'fpl_game1_2026' AND r.round_no = 1 "
                          "AND r.stage = 'main' AND w.image LIKE 'http%'", 1),
    'private-photos-r2': ("SELECT 'fpl_game1_2026/r2/' || owner_id AS key, image AS url FROM mg_round2_submissions "
                          "WHERE image LIKE 'http%'", 1),
    'private-photos-r3': ("SELECT 'fpl_game1_2026/r3/' || owner_id AS key, image AS url FROM mg_round3_submissions "
                          "WHERE image LIKE 'http%'", 1),
    'private-photos-r4': ("SELECT 'fpl_game1_2026/r4/' || owner_id AS key, image AS url FROM mg_round4_submissions "
                          "WHERE image LIKE 'http%'", 1),
    'private-photos-free': ("SELECT 'fpl_game1_2026/free/' || client_id || '/' || round_no AS key, image AS url "
                            "FROM mg_free_submissions WHERE image LIKE 'http%'", 1),
    'private-photos-cards': ("SELECT 'cards/' || client_id AS key, image AS url FROM mg_league_cards WHERE image LIKE 'http%'", 1),
}


def q(sql):
    return sql.replace('\\', '\\\\').replace('"', '\\"')


def obj(cols):
    return 'json_object(%s)' % ', '.join("'%s', %s" % (c, c) for c in cols)


def export_block():
    out = ['sb_h = {"X-FPL-Key": site_ingest_key}',
           'sb_id = sql_value("SELECT strftime(\'%Y%m%d%H%M%S\',\'now\')", [])',
           'sb_rep = "Выгрузка в базу " + sb_id']
    counts = []
    for i, (t, (cols, parts)) in enumerate(EXPORT.items(), 1):
        if not cols:
            out.append('# %s: колонки не заданы — таблица пропущена' % t)
            continue
        out.append('sb_n%d = sql_value("SELECT count(*) FROM %s", [])' % (i, t))
        for p in range(1, parts + 1):
            sel = ('SELECT json_group_array(%s) FROM (SELECT * FROM %s ORDER BY rowid LIMIT %d OFFSET %d)'
                   % (obj(cols), t, PART_ROWS, (p - 1) * PART_ROWS))
            v = 'sb_%d_%d' % (i, p)
            out.append('%s = sql_value("%s", [])' % (v, q(sel)))
            out.append('%s_r = requests_post("%sprivate-sb-%s&part=%d&parts=%d", "ok", sb_h, "", {"data": %s})'
                       % (v, URL, t, p, parts, v))
        out.append('sb_rep = sb_rep + "\\n%s: " + str(sb_n%d) + " / " + %s + if(sb_n%d > %d, " НЕ ПОМЕСТИЛОСЬ — нужно больше частей", "")' % (
            t, i, ' + " " + '.join('str(sb_%d_%d_r)' % (i, p) for p in range(1, parts + 1)), i, parts * PART_ROWS))
        counts.append('"%s": sb_n%d' % (t, i))
    out.append('sb_m = {"export_id": sb_id, "project": "874007", "tables": {%s}}' % ', '.join(counts))
    out.append('sb_m_r = requests_post("%sprivate-sb-manifest", "ok", sb_h, "", {"data": sb_m})' % URL)
    out.append('sb_rep = sb_rep + "\\nманифест: " + str(sb_m_r)')
    return '\n'.join(out)


def photos_block():
    out = ['ph_h = {"X-FPL-Key": site_ingest_key}', 'ph_rep = "Архив фото"']
    for i, (name, (sql, parts)) in enumerate(PHOTOS.items(), 1):
        for p in range(1, parts + 1):
            sel = ("SELECT json_group_array(json_object('key', key, 'url', url)) FROM (%s ORDER BY key LIMIT %d OFFSET %d)"
                   % (sql, 400, (p - 1) * 400))
            v = 'ph_%d_%d' % (i, p)
            out.append('%s = sql_value("%s", [])' % (v, q(sel)))
            suffix = '&part=%d&parts=%d' % (p, parts) if parts > 1 else ''
            out.append('%s_r = requests_post("%s%s%s", "rows", ph_h, "", {"data": %s})' % (v, URL, name, suffix, v))
            out.append('ph_rep = ph_rep + "\\n%s: " + str(%s_r)' % (name, v))
    return '\n'.join(out)


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'export'
    print(export_block() if which == 'export' else photos_block())
