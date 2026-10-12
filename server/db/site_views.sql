-- Публичный слой для сайта facepaintingleague.com (без кабинета).
-- Применяется при каждой установке (CREATE OR REPLACE). Схема таблиц — миграции 001→003 backend.
-- Правило: человек виден на сайте, только если его ПОСЛЕДНЕЕ решение по согласию нужного типа —
-- «accepted», флаг публичности в профиле включён и профиль не удалён.

CREATE OR REPLACE VIEW site_consent_latest AS
SELECT DISTINCT ON (c.user_id, c.consent_type)
       c.user_id, c.consent_type, c.status, c.recorded_at
FROM consents c
WHERE c.user_id IS NOT NULL
ORDER BY c.user_id, c.consent_type, c.recorded_at DESC, c.id DESC;

-- Кто может быть показан: работы/результаты/рейтинг — согласие publication (1.3);
-- анкета мастера — public_profile; контакты — public_contacts.
CREATE OR REPLACE VIEW site_public_people AS
SELECT u.id AS user_id,
       u.display_name,
       (pub.status = 'accepted' AND u.public_rating) AS show_rating,
       (pub.status = 'accepted' AND u.public_works)  AS show_works,
       (prof.status = 'accepted' AND u.public_profile) AS show_profile,
       (cont.status = 'accepted' AND u.public_contacts AND prof.status = 'accepted') AS show_contacts,
       (prof.status = 'accepted' AND u.public_city) AS show_city
FROM users u
LEFT JOIN site_consent_latest pub  ON pub.user_id = u.id  AND pub.consent_type = 'publication'
LEFT JOIN site_consent_latest prof ON prof.user_id = u.id AND prof.consent_type = 'public_profile'
LEFT JOIN site_consent_latest cont ON cont.user_id = u.id AND cont.consent_type = 'public_contacts'
WHERE u.deleted_at IS NULL AND u.anonymized_at IS NULL
  AND coalesce(nullif(trim(u.display_name), ''), NULL) IS NOT NULL;

-- Рейтинг текущего сезона. Место считается среди ВСЕХ с рейтингом (скрытые не сдвигают места),
-- в выгрузку попадают только показываемые.
CREATE OR REPLACE VIEW site_rating_all AS
SELECT s.id AS season_id, s.season_no, s.name AS season_name,
       ps.user_id,
       round(ps.current_rating)::int AS rating,
       ps.rating_status, ps.calibration_rounds_completed AS calibration,
       sp.current_league AS league,
       rank() OVER (PARTITION BY s.id ORDER BY round(ps.current_rating) DESC) AS place,
       (SELECT count(*) FROM round_results rr
          JOIN event_participants ep ON ep.id = rr.event_participant_id
          JOIN events e ON e.id = rr.event_id
        WHERE ep.user_id = ps.user_id AND e.season_id = s.id
          AND rr.top_work AND rr.is_current AND rr.status = 'published')::int AS top_work
FROM participant_stats ps
JOIN season_participants sp ON sp.user_id = ps.user_id
JOIN seasons s ON s.id = sp.season_id AND s.status IN ('active','finished')
WHERE ps.current_rating IS NOT NULL AND ps.rating_status <> 'unrated';

CREATE OR REPLACE FUNCTION site_export_rating() RETURNS json LANGUAGE sql STABLE AS $$
  SELECT json_build_object(
    'schema', 'fpl.public.rating.v1',
    'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'seasons', coalesce((
      SELECT json_agg(json_build_object(
        'no', x.season_no, 'name', x.season_name,
        'rated', x.rated,
        'players', x.players) ORDER BY x.season_no DESC)
      FROM (
        SELECT r.season_id, r.season_no, r.season_name, count(*) AS rated,
               coalesce(json_agg(json_build_object(
                 'place', r.place, 'name', p.display_name, 'league', r.league,
                 'rating', r.rating, 'status', r.rating_status,
                 'calibration', r.calibration, 'top_work', r.top_work)
                 ORDER BY r.place, p.display_name) FILTER (WHERE p.show_rating), '[]'::json) AS players
        FROM site_rating_all r
        LEFT JOIN site_public_people p ON p.user_id = r.user_id
        GROUP BY r.season_id, r.season_no, r.season_name
      ) x), '[]'::json));
$$;

-- Игры и опубликованные итоги туров. По Правилам (п. 7.3) баллы и места других участников
-- не публикуются: наружу идут только размеры лиг и TOP WORK (имя — при согласии на публикацию).
CREATE OR REPLACE FUNCTION site_export_games() RETURNS json LANGUAGE sql STABLE AS $$
  SELECT json_build_object(
    'schema', 'fpl.public.games.v1',
    'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'games', coalesce((
      SELECT json_agg(json_build_object(
        'season_no', s.season_no, 'game_no', e.game_no,
        'title', e.title, 'title_i18n', e.title_i18n,
        'status', e.status, 'starts_at', e.starts_at, 'ends_at', coalesce(e.completion_deadline, e.ends_at),
        'participants', (SELECT count(*) FROM event_participants ep WHERE ep.event_id = e.id
                           AND ep.registration_status IN ('participating','completed')),
        'rounds', coalesce((
          SELECT json_agg(json_build_object(
            'no', r.round_no, 'title', r.title, 'title_i18n', r.title_i18n,
            'status', r.status, 'deadline', r.deadline,
            'leagues', (SELECT coalesce(json_object_agg(l.league, l.n), '{}'::json) FROM (
                          SELECT rr.league, count(*) AS n FROM round_results rr
                          WHERE rr.round_id = r.id AND rr.is_current AND rr.status = 'published' AND rr.league IS NOT NULL
                          GROUP BY rr.league) l),
            'published', (r.status = 'published'),
            'top_work_count', (SELECT count(*) FROM round_results rr
                               WHERE rr.round_id = r.id AND rr.is_current AND rr.status = 'published' AND rr.top_work),
            'top_work', coalesce((
              SELECT json_agg(json_build_object('name', p.display_name, 'league', rr.league)
                ORDER BY p.display_name)
              FROM round_results rr
              JOIN event_participants ep ON ep.id = rr.event_participant_id
              JOIN site_public_people p ON p.user_id = ep.user_id AND p.show_works
              WHERE rr.round_id = r.id AND rr.is_current AND rr.status = 'published' AND rr.top_work), '[]'::json))
            ORDER BY r.round_no)
          FROM rounds r WHERE r.event_id = e.id AND r.status <> 'draft'), '[]'::json))
        ORDER BY s.season_no, e.game_no)
      FROM events e LEFT JOIN seasons s ON s.id = e.season_id
      WHERE e.status <> 'draft' AND e.event_type = 'ranked_game'), '[]'::json));
$$;

-- Проверка диплома по номеру: только выданные и неотозванные, без лишних личных данных
-- (Политика 4.3: публичное имя, Игра, сезон, лига, вид диплома, дата выдачи — город не выгружается).
CREATE OR REPLACE FUNCTION site_export_certificates() RETURNS json LANGUAGE sql STABLE AS $$
  SELECT json_build_object(
    'schema', 'fpl.public.certificates.v1',
    'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'certificates', coalesce((
      SELECT json_object_agg(c.certificate_number, json_build_object(
        'type', c.certificate_type,
        'name', c.issue_snapshot->>'public_name',
        'game', c.issue_snapshot->>'game',
        'season', c.issue_snapshot->>'season',
        'season_en', c.issue_snapshot->>'season_en',
        'league', c.issue_snapshot->>'league',
        'result', c.issue_snapshot->>'result',
        'result_en', c.issue_snapshot->>'result_en',
        'issued_at', c.issued_at))
      FROM certificates c
      WHERE c.status = 'issued' AND c.revoked_at IS NULL AND c.certificate_number IS NOT NULL), '{}'::json));
$$;

-- Каталог «Найти мастера»: заполнится, когда появятся согласия public_profile (после финала Игры 01).
CREATE OR REPLACE FUNCTION site_export_masters() RETURNS json LANGUAGE sql STABLE AS $$
  SELECT json_build_object(
    'schema', 'fpl.public.masters.v1',
    'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'masters', coalesce((
      SELECT json_agg(json_build_object(
        'name', p.display_name,
        'city', CASE WHEN p.show_city THEN u.city END,
        'country', CASE WHEN p.show_city THEN u.country_code END,
        'rating', CASE WHEN p.show_rating THEN round(ps.current_rating)::int END,
        'league', CASE WHEN p.show_rating THEN sp.current_league END,
        'contacts', CASE WHEN p.show_contacts THEN (
            SELECT coalesce(json_agg(json_build_object('type', uc.contact_type, 'value', uc.contact_value)
                            ORDER BY uc.sort_order), '[]'::json)
            FROM user_contacts uc WHERE uc.user_id = u.id AND uc.is_public) END)
        ORDER BY p.display_name)
      FROM site_public_people p
      JOIN users u ON u.id = p.user_id
      LEFT JOIN participant_stats ps ON ps.user_id = u.id
      LEFT JOIN LATERAL (SELECT sp.current_league FROM season_participants sp
                         JOIN seasons s ON s.id = sp.season_id
                         WHERE sp.user_id = u.id ORDER BY s.season_no DESC NULLS LAST LIMIT 1) sp ON true
      WHERE p.show_profile), '[]'::json));
$$;
