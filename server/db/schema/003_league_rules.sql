-- 003 League rules (11.10.2026). Решения Светланы и находки проверки схемы
-- (claude/fpl-audit-skhemy-bd-codex-2026-10-11.md в проекте «Чат бот»).
-- Все новые ограничения, индексы, триггеры и функции имеют префикс lr_ —
-- откат удаляет ровно их. Не пересекается с экспериментальной 003 (context integrity):
-- её ck_pf_voted_evidence и ck_pf_valid_score_author дублируют проверки раздела 9,
-- при слиянии оставить одну пару.

------------------------------------------------------------------------
-- 1. Публичность только по согласию: по умолчанию ничего не публично,
--    удалённый пользователь не может оставаться публичным.
------------------------------------------------------------------------
ALTER TABLE users ALTER COLUMN public_city SET DEFAULT false;
ALTER TABLE users ALTER COLUMN public_works SET DEFAULT false;
ALTER TABLE users ALTER COLUMN public_rating SET DEFAULT false;
ALTER TABLE users ADD CONSTRAINT lr_users_deleted_not_public CHECK (
  deleted_at IS NULL
  OR NOT (public_profile OR public_city OR public_contacts OR public_works OR public_rating)
);

------------------------------------------------------------------------
-- 2. Лиги. Решение 11.10: лиги Игры 01 записываются как лиги сезона
--    (А → gold, Б → silver), отдельной сущности «лига Игры» нет.
--    entry_league = лига, в которой человек играет эту Игру;
--    entry_league_round_id — после какого тура она назначена (Игра 01: тур 1),
--    NULL — назначена при входе по рейтингу.
------------------------------------------------------------------------
ALTER TABLE event_participants ADD COLUMN entry_league_round_id uuid;
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_league_round
  FOREIGN KEY (entry_league_round_id, event_id) REFERENCES rounds(id, event_id) ON DELETE RESTRICT;
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_league_round_needs_league
  CHECK (entry_league_round_id IS NULL OR entry_league IS NOT NULL);

-- Поток судейства — пул одной лиги (NULL = общий пул, как тур 1 Игры 01),
-- со своим сроком судейства (в турах 3–4 лиги судятся по очереди).
ALTER TABLE evaluation_streams ADD COLUMN league text;
ALTER TABLE evaluation_streams ADD CONSTRAINT lr_stream_league
  CHECK (league IS NULL OR league IN ('bronze','silver','gold'));
ALTER TABLE evaluation_streams ADD COLUMN judging_deadline timestamptz;
-- Как считается балл 40–100: Игра 01 — доля побед по всем сравнениям,
-- включая переголосование (решение 06.10); bt_v1 — вариант брифа Codex.
ALTER TABLE evaluation_streams ADD COLUMN scoring_method text;
ALTER TABLE evaluation_streams ADD CONSTRAINT lr_stream_scoring_method
  CHECK (scoring_method IS NULL OR scoring_method IN ('win_share_v1','bt_v1','criteria_mean_v1'));

------------------------------------------------------------------------
-- 3. Итог тура: лига, место в лиге, TOP WORK.
--    TOP WORK выбирается по правилу (≈20% пула, не больше 10, равные на границе
--    входят все, при пуле < 5 не присваивается), но результат правила хранится:
--    от него зависят очки (+1), публикация и сайт, и опубликованный факт
--    не должен меняться, если правило потом поправят.
------------------------------------------------------------------------
ALTER TABLE round_results ADD COLUMN league text;
ALTER TABLE round_results ADD CONSTRAINT lr_rr_league
  CHECK (league IS NULL OR league IN ('bronze','silver','gold'));
ALTER TABLE round_results ADD COLUMN pool_size integer;
ALTER TABLE round_results ADD COLUMN league_rank integer;
ALTER TABLE round_results ADD COLUMN average_place numeric(8,3);
ALTER TABLE round_results ADD COLUMN tie_group_size integer;
ALTER TABLE round_results ADD COLUMN top_work boolean NOT NULL DEFAULT false;
ALTER TABLE round_results ADD COLUMN top_work_rule_version text;
ALTER TABLE round_results ADD CONSTRAINT lr_rr_ranks CHECK (
  (pool_size IS NULL OR pool_size > 0)
  AND (league_rank IS NULL OR league_rank > 0)
  AND (tie_group_size IS NULL OR tie_group_size > 0)
  AND (average_place IS NULL OR average_place > 0)
  AND (league_rank IS NULL OR pool_size IS NULL OR league_rank <= pool_size)
);
ALTER TABLE round_results ADD CONSTRAINT lr_rr_top_work_rule
  CHECK (NOT top_work OR top_work_rule_version IS NOT NULL);
-- Сайт и кабинет читают только один опубликованный текущий итог.
CREATE UNIQUE INDEX lr_rr_one_current ON round_results (round_id, event_participant_id) WHERE is_current;

------------------------------------------------------------------------
-- 4. Итог Игры: лига, место в лиге, место в сквозном зачёте (TOP-10/25),
--    основание места, версия формулы. Решение 11.10: личный итог финала
--    = 40% среднего балла туров 2–4 + 60% финальной работы (FINAL_40_60_V1).
------------------------------------------------------------------------
ALTER TABLE event_results ADD COLUMN league text;
ALTER TABLE event_results ADD CONSTRAINT lr_er_league
  CHECK (league IS NULL OR league IN ('bronze','silver','gold'));
ALTER TABLE event_results ADD COLUMN league_rank integer;
ALTER TABLE event_results ADD COLUMN overall_rank integer;
ALTER TABLE event_results ADD COLUMN standing_basis text;
ALTER TABLE event_results ADD COLUMN standing_round_no integer;
ALTER TABLE event_results ADD COLUMN excluded_reason text;
ALTER TABLE event_results ADD COLUMN formula_version text;
ALTER TABLE event_results ADD CONSTRAINT lr_er_ranks CHECK (
  (league_rank IS NULL OR league_rank > 0) AND (overall_rank IS NULL OR overall_rank > 0)
);
ALTER TABLE event_results ADD CONSTRAINT lr_er_standing CHECK (
  (standing_basis IS NULL AND standing_round_no IS NULL)
  OR (standing_basis = 'final' AND standing_round_no IS NULL)
  OR (standing_basis = 'round' AND standing_round_no IS NOT NULL AND standing_round_no > 0)
);
-- В сквозной зачёт не входят опоздавшие и не прошедшие отбор 1 тура.
ALTER TABLE event_results ADD CONSTRAINT lr_er_excluded CHECK (
  excluded_reason IS NULL
  OR (excluded_reason IN ('late','not_qualified_round1','withdrawn','disqualified') AND overall_rank IS NULL)
);
ALTER TABLE event_results ADD CONSTRAINT lr_er_formula
  CHECK (status <> 'published' OR final_score IS NULL OR formula_version IS NOT NULL);
CREATE UNIQUE INDEX lr_er_one_current_personal ON event_results (event_id, event_participant_id)
  WHERE is_current AND event_participant_id IS NOT NULL;

------------------------------------------------------------------------
-- 5. «Вне конкурса». Решение 04–05.10: автоматических переводов нет.
--    Выбывший (по судейству или опозданию) остаётся 'eliminated' с причиной,
--    пока сам не нажмёт «Вне конкурса» → 'diploma_only' с отметкой, кто и когда.
--    Вернуться в конкурс нельзя (кроме исправления ошибки — через audit_log).
------------------------------------------------------------------------
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_elimination_reason CHECK (
  elimination_reason IS NULL
  OR elimination_reason IN ('judged_out','late','withdrawn','disqualified','admin')
);
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_eliminated_round
  FOREIGN KEY (eliminated_round_id, event_id) REFERENCES rounds(id, event_id) ON DELETE RESTRICT;
ALTER TABLE event_participants ADD COLUMN out_of_competition_at timestamptz;
ALTER TABLE event_participants ADD COLUMN out_of_competition_source text;
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_out_source CHECK (
  out_of_competition_source IS NULL
  OR out_of_competition_source IN ('participant','admin','import_auto')
);
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_out_state CHECK (
  (competition_status IS DISTINCT FROM 'diploma_only')
  OR (out_of_competition_at IS NOT NULL AND out_of_competition_source IS NOT NULL)
);
ALTER TABLE event_participants ADD CONSTRAINT lr_ep_eliminated_reason_required CHECK (
  competition_status IS DISTINCT FROM 'eliminated' OR elimination_reason IS NOT NULL
);

------------------------------------------------------------------------
-- 6. Юридические документы и согласия. Текст принятой редакции неизменяем,
--    согласие — журнал (отзыв = новая запись), за Игрой закреплена редакция Правил.
------------------------------------------------------------------------
CREATE TABLE legal_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_type text NOT NULL CHECK (doc_type IN (
    'rules','personal_data','publication','model_confirmation',
    'privacy_policy','guardian_consent','offer','other')),
  version text NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  body_sha256 text NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  superseded_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (doc_type, version),
  UNIQUE (id, doc_type),
  CHECK (superseded_at IS NULL OR superseded_at >= published_at)
);
CREATE FUNCTION lr_legal_documents_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'legal_documents are append-only';
  END IF;
  IF (NEW.doc_type, NEW.version, NEW.title, NEW.body, NEW.body_sha256, NEW.published_at)
     IS DISTINCT FROM (OLD.doc_type, OLD.version, OLD.title, OLD.body, OLD.body_sha256, OLD.published_at) THEN
    RAISE EXCEPTION 'published legal document text cannot change; publish a new version';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_legal_documents_frozen BEFORE UPDATE OR DELETE ON legal_documents
  FOR EACH ROW EXECUTE FUNCTION lr_legal_documents_frozen();

-- Внешние идентичности: Telegram, ВКонтакте, client_id SaleBot. Один человек
-- может иметь несколько; запись может существовать до активации аккаунта.
CREATE TABLE external_identities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE RESTRICT,
  provider text NOT NULL CHECK (provider IN ('telegram','vk','salebot_client')),
  project_ref text NOT NULL DEFAULT '',
  external_id text NOT NULL CHECK (external_id <> ''),
  verified_at timestamptz,
  linked_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, project_ref, external_id),
  CHECK (user_id IS NULL OR linked_at IS NOT NULL)
);
CREATE INDEX lr_external_identities_user ON external_identities (user_id) WHERE user_id IS NOT NULL;

ALTER TABLE consents ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE consents ADD COLUMN external_identity_id uuid REFERENCES external_identities(id) ON DELETE RESTRICT;
ALTER TABLE consents ADD COLUMN legal_document_id uuid REFERENCES legal_documents(id) ON DELETE RESTRICT;
ALTER TABLE consents ADD COLUMN status text NOT NULL DEFAULT 'accepted';
ALTER TABLE consents ADD COLUMN channel text;
ALTER TABLE consents ADD COLUMN button_text text;
ALTER TABLE consents ADD COLUMN idempotency_key text;
ALTER TABLE consents ADD CONSTRAINT lr_consents_subject
  CHECK (num_nonnulls(user_id, external_identity_id) >= 1);
ALTER TABLE consents ADD CONSTRAINT lr_consents_status
  CHECK (status IN ('accepted','declined','revoked'));
ALTER TABLE consents ADD CONSTRAINT lr_consents_status_matches
  CHECK (accepted = (status = 'accepted'));
ALTER TABLE consents ADD CONSTRAINT lr_consents_channel
  CHECK (channel IS NULL OR channel IN ('telegram','vk','web','admin','import'));
ALTER TABLE consents ADD CONSTRAINT lr_consents_type CHECK (consent_type IN (
  'rules','personal_data','publication','model_confirmation','privacy_policy',
  'guardian_consent','offer','marketing','public_profile','public_contacts'));
ALTER TABLE consents ADD CONSTRAINT lr_consents_idempotency UNIQUE (idempotency_key);
CREATE INDEX lr_consents_identity ON consents (external_identity_id, consent_type, recorded_at DESC)
  WHERE external_identity_id IS NOT NULL;
CREATE FUNCTION lr_consents_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'consents are append-only; record a revocation instead';
  END IF;
  -- Разрешено только связать запись с аккаунтом при активации.
  IF (NEW.id, NEW.event_id, NEW.consent_type, NEW.accepted, NEW.document_version, NEW.recorded_at,
      NEW.external_identity_id, NEW.legal_document_id, NEW.status, NEW.channel, NEW.button_text,
      NEW.idempotency_key, NEW.metadata)
     IS DISTINCT FROM
     (OLD.id, OLD.event_id, OLD.consent_type, OLD.accepted, OLD.document_version, OLD.recorded_at,
      OLD.external_identity_id, OLD.legal_document_id, OLD.status, OLD.channel, OLD.button_text,
      OLD.idempotency_key, OLD.metadata)
     OR (OLD.user_id IS NOT NULL AND NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
    RAISE EXCEPTION 'consents are append-only; record a revocation instead';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_consents_append_only BEFORE UPDATE OR DELETE ON consents
  FOR EACH ROW EXECUTE FUNCTION lr_consents_append_only();

-- Редакция Правил закреплена за Игрой и не меняется после старта.
ALTER TABLE events ADD COLUMN rules_document_id uuid;
ALTER TABLE events ADD COLUMN rules_doc_type text GENERATED ALWAYS AS ('rules') STORED;
ALTER TABLE events ADD CONSTRAINT lr_events_rules_document
  FOREIGN KEY (rules_document_id, rules_doc_type) REFERENCES legal_documents(id, doc_type) ON DELETE RESTRICT;
CREATE FUNCTION lr_events_rules_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('active','finished','archived')
     AND NEW.rules_document_id IS DISTINCT FROM OLD.rules_document_id THEN
    RAISE EXCEPTION 'rules edition cannot change after the Game has started';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_events_rules_frozen BEFORE UPDATE OF rules_document_id ON events
  FOR EACH ROW EXECUTE FUNCTION lr_events_rules_frozen();

------------------------------------------------------------------------
-- 7. Импорт из SaleBot: пакеты, карта «старая строка → новая запись», проблемы.
--    Повторный импорт обновляет записи по карте, а не дублирует их.
------------------------------------------------------------------------
CREATE TABLE import_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source text NOT NULL CHECK (source IN ('salebot')),
  source_project text NOT NULL,
  snapshot_sha256 text CHECK (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'started'
    CHECK (status IN ('started','completed','failed','rolled_back')),
  started_by uuid REFERENCES users(id) ON DELETE SET NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  notes text,
  CHECK (status = 'started' OR finished_at IS NOT NULL)
);
CREATE TABLE import_row_map (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  first_batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
  last_batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
  source_table text NOT NULL,
  source_key text NOT NULL,
  target_table text NOT NULL,
  target_id uuid NOT NULL,
  row_sha256 text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_table, source_key, target_table)
);
CREATE INDEX lr_import_row_map_target ON import_row_map (target_table, target_id);
CREATE TABLE import_issues (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
  source_table text NOT NULL,
  source_key text,
  severity text NOT NULL CHECK (severity IN ('info','warning','error')),
  message text NOT NULL,
  resolved_at timestamptz,
  resolution text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (resolved_at IS NULL OR resolution IS NOT NULL)
);

------------------------------------------------------------------------
-- 8. Дипломы: номер FPL-S<сезон>-<Игра>-<номер>, неизменный снимок реквизитов.
------------------------------------------------------------------------
ALTER TABLE seasons ADD COLUMN season_no integer;
ALTER TABLE seasons ADD CONSTRAINT lr_seasons_no CHECK (season_no IS NULL OR season_no BETWEEN 1 AND 99);
ALTER TABLE seasons ADD CONSTRAINT lr_seasons_no_unique UNIQUE (season_no);
ALTER TABLE events ADD COLUMN game_no integer;
ALTER TABLE events ADD CONSTRAINT lr_events_game_no CHECK (game_no IS NULL OR game_no BETWEEN 1 AND 99);
ALTER TABLE events ADD CONSTRAINT lr_events_game_no_unique UNIQUE (season_id, game_no);

ALTER TABLE certificates ADD COLUMN certificate_number text;
ALTER TABLE certificates ADD COLUMN issue_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE certificates ADD COLUMN revoked_at timestamptz;
ALTER TABLE certificates ADD COLUMN revoke_reason text;
ALTER TABLE certificates ADD CONSTRAINT lr_cert_number_format
  CHECK (certificate_number IS NULL OR certificate_number ~ '^FPL-S[0-9]{1,2}-[0-9]{2}-[0-9]{4}$');
ALTER TABLE certificates ADD CONSTRAINT lr_cert_number_unique UNIQUE (certificate_number);
ALTER TABLE certificates ADD CONSTRAINT lr_cert_issued_complete CHECK (
  status <> 'issued' OR (certificate_number IS NOT NULL AND issued_at IS NOT NULL AND issue_snapshot <> '{}'::jsonb)
);
ALTER TABLE certificates ADD CONSTRAINT lr_cert_revoked CHECK (
  (revoked_at IS NULL AND revoke_reason IS NULL) OR (revoked_at IS NOT NULL AND revoke_reason IS NOT NULL AND status = 'void')
);
CREATE UNIQUE INDEX lr_cert_one_per_type ON certificates (event_participant_id, certificate_type)
  WHERE status <> 'void';
CREATE FUNCTION lr_certificates_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'issued' AND (
       NEW.certificate_number IS DISTINCT FROM OLD.certificate_number
       OR NEW.issue_snapshot IS DISTINCT FROM OLD.issue_snapshot
       OR NEW.event_participant_id IS DISTINCT FROM OLD.event_participant_id
       OR NEW.certificate_type IS DISTINCT FROM OLD.certificate_type
       OR NEW.issued_at IS DISTINCT FROM OLD.issued_at) THEN
    RAISE EXCEPTION 'issued certificate cannot change; revoke and issue a new one';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_certificates_frozen BEFORE UPDATE ON certificates
  FOR EACH ROW EXECUTE FUNCTION lr_certificates_frozen();

------------------------------------------------------------------------
-- 9. Судейство.
------------------------------------------------------------------------
-- Голос и балл всегда с автором; голос — с победителем и временем.
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_voted_evidence CHECK (
  status <> 'voted' OR (winner_target_id IS NOT NULL AND judge_assignment_id IS NOT NULL AND voted_at IS NOT NULL)
);
ALTER TABLE criterion_scores ADD CONSTRAINT lr_cs_valid_author
  CHECK (status <> 'valid' OR judge_assignment_id IS NOT NULL);

-- Один человек — одно активное место судьи в потоке; судья не участник этой Игры.
ALTER TABLE evaluation_judge_assignments ADD COLUMN evaluation_stream_id uuid;
UPDATE evaluation_judge_assignments a SET evaluation_stream_id = s.evaluation_stream_id
  FROM evaluation_judge_slots s WHERE s.id = a.judge_slot_id;
CREATE FUNCTION lr_judge_assignment_fill() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE ev uuid;
BEGIN
  IF NEW.evaluation_stream_id IS NULL THEN
    SELECT evaluation_stream_id INTO NEW.evaluation_stream_id FROM evaluation_judge_slots WHERE id = NEW.judge_slot_id;
  END IF;
  IF NEW.status = 'active' THEN
    SELECT event_id INTO ev FROM evaluation_streams WHERE id = NEW.evaluation_stream_id;
    IF EXISTS (SELECT 1 FROM event_participants p WHERE p.event_id = ev AND p.user_id = NEW.user_id
               AND p.registration_status NOT IN ('cancelled')) THEN
      RAISE EXCEPTION 'a participant of this Game cannot judge it';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_judge_assignment_fill BEFORE INSERT OR UPDATE ON evaluation_judge_assignments
  FOR EACH ROW EXECUTE FUNCTION lr_judge_assignment_fill();
ALTER TABLE evaluation_judge_assignments ALTER COLUMN evaluation_stream_id SET NOT NULL;
ALTER TABLE evaluation_judge_assignments ADD CONSTRAINT lr_eja_slot_stream
  FOREIGN KEY (judge_slot_id, evaluation_stream_id) REFERENCES evaluation_judge_slots(id, evaluation_stream_id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX lr_eja_one_slot_per_judge ON evaluation_judge_assignments (evaluation_stream_id, user_id)
  WHERE status = 'active';

-- Повторные прогоны (переголосование 2–4 побед), правка голоса с историей,
-- досудейство, засчитанное одной стороне (случай 1 тура Игры 01).
ALTER TABLE pairwise_comparisons ADD COLUMN run_no integer NOT NULL DEFAULT 1;
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_run_no CHECK (run_no > 0);
ALTER TABLE pairwise_comparisons ADD COLUMN supersedes_id uuid;
ALTER TABLE pairwise_comparisons ADD COLUMN counts_for text NOT NULL DEFAULT 'both';
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_counts_for
  CHECK (counts_for IN ('both','target_a','target_b'));
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_id_stream UNIQUE (id, evaluation_stream_id);
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_supersedes
  FOREIGN KEY (supersedes_id, evaluation_stream_id) REFERENCES pairwise_comparisons(id, evaluation_stream_id) ON DELETE RESTRICT;
ALTER TABLE pairwise_comparisons ADD CONSTRAINT lr_pc_supersedes_self
  CHECK (supersedes_id IS NULL OR supersedes_id <> id);
DROP INDEX ux_pairwise_no_duplicate_pair_per_slot_phase;
CREATE UNIQUE INDEX lr_pc_no_duplicate_pair ON pairwise_comparisons (
  evaluation_stream_id, judge_slot_id,
  LEAST(target_a_id, target_b_id), GREATEST(target_a_id, target_b_id),
  phase, run_no
) WHERE status NOT IN ('cancelled','void');

-- Решение о проходе: по правилу, после переголосования или решением администратора
-- («Решение администратора: 90,34,52,78,99,11», квота 25 → 26).
CREATE TABLE advancement_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL,
  round_id uuid NOT NULL,
  method text NOT NULL CHECK (method IN ('rule','tie_break','admin')),
  quota_before integer CHECK (quota_before IS NULL OR quota_before >= 0),
  quota_after integer CHECK (quota_after IS NULL OR quota_after >= 0),
  band_low numeric(10,4),
  band_high numeric(10,4),
  decided_by uuid REFERENCES users(id) ON DELETE RESTRICT,
  reason text,
  decided_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','void')),
  UNIQUE (id, evaluation_stream_id),
  FOREIGN KEY (evaluation_stream_id, round_id) REFERENCES evaluation_streams(id, round_id) ON DELETE RESTRICT,
  CHECK (method <> 'admin' OR (decided_by IS NOT NULL AND reason IS NOT NULL)),
  CHECK (band_low IS NULL OR band_high IS NULL OR band_low <= band_high)
);
CREATE TABLE advancement_decision_members (
  decision_id uuid NOT NULL,
  evaluation_stream_id uuid NOT NULL,
  evaluation_target_id uuid NOT NULL,
  advanced boolean NOT NULL,
  PRIMARY KEY (decision_id, evaluation_target_id),
  FOREIGN KEY (decision_id, evaluation_stream_id) REFERENCES advancement_decisions(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (evaluation_target_id, evaluation_stream_id) REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT
);

------------------------------------------------------------------------
-- 10. Сроки: персональные продления и срок, от которого считалось «в срок»
--     (1 тур Игры 01: 24 участницам продлено до 04.10 23:59).
------------------------------------------------------------------------
ALTER TABLE participant_assignments ADD COLUMN deadline_override timestamptz;
ALTER TABLE participant_assignments ADD COLUMN deadline_override_reason text;
ALTER TABLE participant_assignments ADD COLUMN deadline_override_by uuid REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE participant_assignments ADD CONSTRAINT lr_pa_override_reason
  CHECK (deadline_override IS NULL OR deadline_override_reason IS NOT NULL);
ALTER TABLE submissions ADD COLUMN deadline_applied_at timestamptz;
ALTER TABLE submissions ADD COLUMN deadline_source text;
ALTER TABLE submissions ADD COLUMN publication_url text;
ALTER TABLE submissions ADD CONSTRAINT lr_sub_deadline_source CHECK (
  deadline_source IS NULL OR deadline_source IN ('round','assignment','personal','completion','import')
);
ALTER TABLE submissions ADD CONSTRAINT lr_sub_on_time_basis
  CHECK (is_on_time IS NULL OR deadline_applied_at IS NOT NULL);

------------------------------------------------------------------------
-- 11. Фото: исходный адрес (ссылки ВК протухают), отпечаток, пакет импорта;
--     запись об утраченном исходнике без файла.
------------------------------------------------------------------------
ALTER TABLE media_files ADD COLUMN source_url text;
ALTER TABLE media_files ADD COLUMN sha256 text;
ALTER TABLE media_files ADD COLUMN import_batch_id uuid REFERENCES import_batches(id) ON DELETE RESTRICT;
ALTER TABLE media_files ADD COLUMN source_lost_at timestamptz;
ALTER TABLE media_files ALTER COLUMN storage_key DROP NOT NULL;
ALTER TABLE media_files ADD CONSTRAINT lr_media_sha256 CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE media_files ADD CONSTRAINT lr_media_file_or_lost
  CHECK (storage_key IS NOT NULL OR source_lost_at IS NOT NULL);
CREATE INDEX lr_media_sha256_idx ON media_files (sha256) WHERE sha256 IS NOT NULL;

------------------------------------------------------------------------
-- 12. Рейтинг и очки: защита от двойного начисления; очки FPL не уменьшаются.
------------------------------------------------------------------------
CREATE UNIQUE INDEX lr_rt_one_active_per_stream ON rating_transactions (user_id, evaluation_stream_id)
  WHERE status = 'active' AND method IN ('pairwise_elo','criteria_virtual_elo');
CREATE UNIQUE INDEX lr_rt_one_initial_seeding ON rating_transactions (user_id)
  WHERE status = 'active' AND method = 'initial_seeding';
ALTER TABLE points_transactions ADD COLUMN source_type text;
ALTER TABLE points_transactions ADD COLUMN source_id uuid;
ALTER TABLE points_transactions ADD COLUMN reversal_of_id uuid REFERENCES points_transactions(id) ON DELETE RESTRICT;
ALTER TABLE points_transactions ADD CONSTRAINT lr_pt_source CHECK (
  (source_type IS NULL AND source_id IS NULL)
  OR (source_type IN ('round_result','event_result','manual','import') AND (source_id IS NOT NULL OR source_type IN ('manual','import')))
);
ALTER TABLE points_transactions ADD CONSTRAINT lr_pt_lifetime_never_decreases
  CHECK (lifetime_delta >= 0 OR reversal_of_id IS NOT NULL);
ALTER TABLE points_transactions ADD CONSTRAINT lr_pt_reversal_self
  CHECK (reversal_of_id IS NULL OR reversal_of_id <> id);
