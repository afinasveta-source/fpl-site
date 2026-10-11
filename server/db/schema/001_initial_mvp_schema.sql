-- Face Painting League
-- PostgreSQL MVP schema — migration 001
-- Generated from Architecture Spec decisions agreed in conversation.
-- Target: PostgreSQL 15+ (uses gen_random_uuid(), JSONB, partial indexes, num_nonnulls()).

BEGIN;

-- gen_random_uuid() is built into PostgreSQL 15+; no extension is required.

-- =========================================================
-- Utility
-- =========================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- =========================================================
-- 1. Users / roles / participant state
-- =========================================================

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text,
  password_hash text,
  email_verified_at timestamptz,
  account_status text NOT NULL DEFAULT 'imported'
    CHECK (account_status IN ('imported','active','suspended','deleted')),
  telegram_id bigint,
  full_name text,
  display_name text,
  city text,
  country_code text,
  locale text NOT NULL DEFAULT 'ru',
  timezone text,
  avatar_media_id uuid,
  public_profile boolean NOT NULL DEFAULT false,
  public_city boolean NOT NULL DEFAULT true,
  public_contacts boolean NOT NULL DEFAULT false,
  public_works boolean NOT NULL DEFAULT true,
  public_rating boolean NOT NULL DEFAULT true,
  deleted_at timestamptz,
  anonymized_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (account_status <> 'active' OR (email IS NOT NULL AND password_hash IS NOT NULL))
);

CREATE UNIQUE INDEX ux_users_email_lower
  ON users (lower(email))
  WHERE email IS NOT NULL;
CREATE UNIQUE INDEX ux_users_telegram_id ON users (telegram_id) WHERE telegram_id IS NOT NULL;

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE user_roles (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('participant','judge','moderator','admin')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role)
);


CREATE TABLE user_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  contact_type text NOT NULL,
  contact_value text NOT NULL,
  is_public boolean NOT NULL DEFAULT false,
  is_verified boolean NOT NULL DEFAULT false,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_user_contacts_user ON user_contacts (user_id, sort_order);

CREATE TRIGGER trg_user_contacts_updated_at
BEFORE UPDATE ON user_contacts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE communication_preferences (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  marketing_opt_in boolean NOT NULL DEFAULT false,
  telegram_service_enabled boolean NOT NULL DEFAULT true,
  email_service_enabled boolean NOT NULL DEFAULT true,
  in_app_enabled boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_communication_preferences_updated_at
BEFORE UPDATE ON communication_preferences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE participant_stats (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
  current_rating numeric(10,4),
  calibration_rounds_completed smallint NOT NULL DEFAULT 0
    CHECK (calibration_rounds_completed BETWEEN 0 AND 3),
  rating_status text NOT NULL DEFAULT 'unrated'
    CHECK (rating_status IN ('unrated','calibrating','established')),
  lifetime_points integer NOT NULL DEFAULT 0 CHECK (lifetime_points >= 0),
  available_points integer NOT NULL DEFAULT 0 CHECK (available_points >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (rating_status = 'unrated' OR current_rating IS NOT NULL),
  CHECK (rating_status <> 'established' OR calibration_rounds_completed = 3),
  CHECK (available_points <= lifetime_points)
);

CREATE TRIGGER trg_participant_stats_updated_at
BEFORE UPDATE ON participant_stats
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =========================================================
-- 2. Seasons / league state
-- =========================================================

CREATE TABLE seasons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  starts_at timestamptz,
  ends_at timestamptz,
  official_timezone text NOT NULL DEFAULT 'Europe/Moscow',
  silver_threshold numeric(10,4),
  gold_threshold numeric(10,4),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','active','finished','archived')),
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    silver_threshold IS NULL
    OR gold_threshold IS NULL
    OR silver_threshold < gold_threshold
  )
);

CREATE TRIGGER trg_seasons_updated_at
BEFORE UPDATE ON seasons
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE season_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  season_id uuid NOT NULL REFERENCES seasons(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  league_at_start text CHECK (league_at_start IN ('bronze','silver','gold')),
  current_league text CHECK (current_league IN ('bronze','silver','gold')),
  last_league_recalculation_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (season_id, user_id)
);

CREATE INDEX ix_season_participants_season_league
  ON season_participants (season_id, current_league);

CREATE TRIGGER trg_season_participants_updated_at
BEFORE UPDATE ON season_participants
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =========================================================
-- 3. Events / participation / staff / payments
-- =========================================================

CREATE TABLE events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  season_id uuid REFERENCES seasons(id) ON DELETE RESTRICT,
  event_type text NOT NULL
    CHECK (event_type IN ('ranked_game','challenge','final','team','special')),
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','registration','active','finished','archived')),
  title text NOT NULL,
  title_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  description text,
  description_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  registration_opens_at timestamptz,
  registration_closes_at timestamptz,
  payment_opens_at timestamptz,
  payment_deadline timestamptz,
  starts_at timestamptz,
  ends_at timestamptz,
  completion_deadline timestamptz,
  official_timezone text,
  affects_rating boolean NOT NULL DEFAULT false,
  counts_for_final boolean NOT NULL DEFAULT false,
  awards_points boolean NOT NULL DEFAULT false,
  has_diploma boolean NOT NULL DEFAULT false,
  payment_required boolean NOT NULL DEFAULT false,
  price numeric(12,2),
  currency char(3),
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (price IS NULL OR price >= 0),
  CHECK (
    payment_required = false
    OR (price IS NOT NULL AND currency IS NOT NULL)
  ),
  CHECK (
    completion_deadline IS NULL
    OR starts_at IS NULL
    OR completion_deadline >= starts_at
  ),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at),
  CHECK (
    registration_closes_at IS NULL
    OR registration_opens_at IS NULL
    OR registration_closes_at >= registration_opens_at
  ),
  CHECK (
    payment_deadline IS NULL
    OR payment_opens_at IS NULL
    OR payment_deadline >= payment_opens_at
  ),
  CHECK (counts_for_final = false OR event_type = 'ranked_game'),
  CHECK (event_type <> 'team' OR affects_rating = false),
  UNIQUE (id, season_id)
);

CREATE INDEX ix_events_season_status ON events (season_id, status);
CREATE INDEX ix_events_affects_rating ON events (affects_rating) WHERE affects_rating = true;

CREATE TRIGGER trg_events_updated_at
BEFORE UPDATE ON events
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE event_participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

  registration_status text NOT NULL DEFAULT 'pre_registered'
    CHECK (registration_status IN (
      'pre_registered','payment_pending','participating',
      'completed','withdrawn','cancelled'
    )),
  eligibility_status text NOT NULL DEFAULT 'pending'
    CHECK (eligibility_status IN ('pending','eligible','ineligible','locked')),
  payment_status text NOT NULL DEFAULT 'not_required'
    CHECK (payment_status IN ('not_required','pending','paid','failed','refunded')),
  competition_status text
    CHECK (competition_status IN (
      'active','eliminated','diploma_only','disqualified','completed'
    )),
  elimination_reason text,
  eliminated_round_id uuid,

  entry_rating numeric(10,4),
  entry_league text CHECK (entry_league IN ('bronze','silver','gold')),
  eligibility_checked_at timestamptz,
  eligibility_locked_at timestamptz,
  eligibility_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- Derived/cached state. Source of truth is submissions/results/rules.
  game_counted boolean,
  diploma_eligible boolean,
  status_calculated_at timestamptz,

  joined_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (event_id, user_id),
  UNIQUE (id, event_id),
  UNIQUE (id, user_id)
);

CREATE INDEX ix_event_participants_event_status
  ON event_participants (event_id, registration_status, competition_status);
CREATE INDEX ix_event_participants_user
  ON event_participants (user_id, event_id);

CREATE TRIGGER trg_event_participants_updated_at
BEFORE UPDATE ON event_participants
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE event_staff (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('judge','moderator')),
  active_from timestamptz NOT NULL DEFAULT now(),
  active_to timestamptz,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_id, user_id, role, active_from)
);

CREATE INDEX ix_event_staff_active
  ON event_staff (event_id, role)
  WHERE active = true;

CREATE UNIQUE INDEX ux_event_staff_one_active_role
  ON event_staff (event_id, user_id, role)
  WHERE active = true;

CREATE TABLE payments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  provider text NOT NULL,
  provider_payment_id text,
  amount numeric(12,2) NOT NULL CHECK (amount >= 0),
  currency char(3) NOT NULL,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','paid','failed','refunded','cancelled')),
  idempotency_key text NOT NULL,
  provider_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  paid_at timestamptz,
  refunded_at timestamptz,
  UNIQUE (idempotency_key)
);

CREATE UNIQUE INDEX ux_payments_provider_payment
  ON payments (provider, provider_payment_id)
  WHERE provider_payment_id IS NOT NULL;

-- =========================================================
-- 4. Promotions / one-time benefits
-- =========================================================

CREATE TABLE promotions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text,
  name text NOT NULL,
  discount_type text NOT NULL
    CHECK (discount_type IN ('percent','fixed','free')),
  discount_value numeric(12,2),
  conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
  starts_at timestamptz,
  ends_at timestamptz,
  max_uses integer CHECK (max_uses IS NULL OR max_uses > 0),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at),
  CHECK (
    (discount_type = 'free' AND discount_value IS NULL)
    OR (discount_type = 'percent' AND discount_value > 0 AND discount_value <= 100)
    OR (discount_type = 'fixed' AND discount_value > 0)
  )
);

CREATE UNIQUE INDEX ux_promotions_code_lower
  ON promotions (lower(code))
  WHERE code IS NOT NULL;

CREATE TABLE promotion_redemptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  promotion_id uuid NOT NULL REFERENCES promotions(id) ON DELETE RESTRICT,
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'reserved'
    CHECK (status IN ('reserved','consumed','restored','cancelled')),
  reserved_at timestamptz NOT NULL DEFAULT now(),
  consumed_at timestamptz,
  restored_at timestamptz,
  reason text,
  UNIQUE (promotion_id, event_participant_id)
);

-- =========================================================
-- 5. Rounds / assignments / participant materialization
-- =========================================================

CREATE TABLE rounds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  round_no integer NOT NULL CHECK (round_no > 0),
  title text NOT NULL,
  title_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN (
      'draft','scheduled','open','closed','judging',
      'tie_break','results_review','published'
    )),
  opens_at timestamptz,
  deadline timestamptz,
  judging_deadline timestamptz,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_id, round_no),
  UNIQUE (id, event_id),
  CHECK (deadline IS NULL OR opens_at IS NULL OR deadline >= opens_at),
  CHECK (judging_deadline IS NULL OR deadline IS NULL OR judging_deadline >= deadline)
);

CREATE INDEX ix_rounds_event_status ON rounds (event_id, status);

ALTER TABLE event_participants
  ADD CONSTRAINT fk_event_participants_eliminated_round
  FOREIGN KEY (eliminated_round_id, event_id)
  REFERENCES rounds(id, event_id) ON DELETE RESTRICT;


CREATE TRIGGER trg_rounds_updated_at
BEFORE UPDATE ON rounds
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid NOT NULL,
  code text NOT NULL,
  title text NOT NULL,
  assignment_type text NOT NULL DEFAULT 'competition_work'
    CHECK (assignment_type IN ('competition_work','mechanic_task','reference_task','other')),
  required boolean NOT NULL DEFAULT true,
  required_for_competition boolean NOT NULL DEFAULT true,
  required_for_game_count boolean NOT NULL DEFAULT true,
  required_for_diploma boolean NOT NULL DEFAULT true,
  deadline timestamptz,
  lock_after_submit boolean NOT NULL DEFAULT true,
  on_missed_deadline text NOT NULL DEFAULT 'diploma_track'
    CHECK (on_missed_deadline IN (
      'eliminate','diploma_track','fallback','admin_decision','none'
    )),
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, code),
  UNIQUE (id, event_id),
  FOREIGN KEY (round_id, event_id)
    REFERENCES rounds(id, event_id) ON DELETE RESTRICT
);

CREATE TABLE assignment_variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid NOT NULL REFERENCES assignments(id) ON DELETE RESTRICT,
  code text NOT NULL,
  title_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  instructions_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  audience_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  submission_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  release_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, code),
  UNIQUE (id, assignment_id)
);

CREATE TABLE participant_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  event_participant_id uuid NOT NULL,
  assignment_id uuid NOT NULL,
  assignment_variant_id uuid NOT NULL,
  source text NOT NULL DEFAULT 'automatic'
    CHECK (source IN ('automatic','manual','fallback','migration')),
  payload_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  active boolean NOT NULL DEFAULT true,
  previous_assignment_id uuid REFERENCES participant_assignments(id) ON DELETE RESTRICT,
  replacement_reason text,
  replaced_at timestamptz,
  UNIQUE (id, event_participant_id),
  FOREIGN KEY (event_participant_id, event_id)
    REFERENCES event_participants(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (assignment_id, event_id)
    REFERENCES assignments(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (assignment_variant_id, assignment_id)
    REFERENCES assignment_variants(id, assignment_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_participant_assignments_active
  ON participant_assignments (event_participant_id, assignment_id)
  WHERE active = true;

-- =========================================================
-- 6. Submissions / versions / media
-- =========================================================

CREATE TABLE submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  participant_assignment_id uuid NOT NULL REFERENCES participant_assignments(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','submitted','locked','late','completed','void')),
  latest_version_id uuid,
  competition_version_id uuid,
  diploma_version_id uuid,
  first_submitted_at timestamptz,
  last_submitted_at timestamptz,
  locked_at timestamptz,
  is_on_time boolean,
  counts_for_competition boolean,
  counts_for_diploma boolean,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (participant_assignment_id)
);

CREATE TRIGGER trg_submissions_updated_at
BEFORE UPDATE ON submissions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE submission_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK (version_no > 0),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  source text NOT NULL DEFAULT 'web'
    CHECK (source IN ('web','telegram','admin','migration')),
  is_final_submit boolean NOT NULL DEFAULT false,
  submitted_at timestamptz,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, version_no),
  UNIQUE (id, submission_id)
);

ALTER TABLE submissions
  ADD CONSTRAINT uq_submissions_id_event_participant UNIQUE (id, event_participant_id);

ALTER TABLE submissions
  ADD CONSTRAINT fk_submissions_participant_assignment_owner
  FOREIGN KEY (participant_assignment_id, event_participant_id)
  REFERENCES participant_assignments(id, event_participant_id) ON DELETE RESTRICT;

ALTER TABLE submissions
  ADD CONSTRAINT fk_submissions_latest_version
  FOREIGN KEY (latest_version_id, id)
  REFERENCES submission_versions(id, submission_id) ON DELETE RESTRICT;

ALTER TABLE submissions
  ADD CONSTRAINT fk_submissions_competition_version
  FOREIGN KEY (competition_version_id, id)
  REFERENCES submission_versions(id, submission_id) ON DELETE RESTRICT;

ALTER TABLE submissions
  ADD CONSTRAINT fk_submissions_diploma_version
  FOREIGN KEY (diploma_version_id, id)
  REFERENCES submission_versions(id, submission_id) ON DELETE RESTRICT;

CREATE TABLE media_files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uploaded_by uuid REFERENCES users(id) ON DELETE SET NULL,
  storage_key text NOT NULL UNIQUE,
  original_filename text,
  mime_type text,
  size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
  optimized_storage_key text,
  thumbnail_storage_key text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE users
  ADD CONSTRAINT fk_users_avatar_media
  FOREIGN KEY (avatar_media_id) REFERENCES media_files(id) ON DELETE SET NULL;

CREATE TABLE submission_version_media (
  submission_version_id uuid NOT NULL REFERENCES submission_versions(id) ON DELETE RESTRICT,
  media_file_id uuid NOT NULL REFERENCES media_files(id) ON DELETE RESTRICT,
  field_key text NOT NULL,
  sort_order integer NOT NULL DEFAULT 0,
  PRIMARY KEY (submission_version_id, media_file_id, field_key)
);


CREATE TABLE certificates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  certificate_type text NOT NULL
    CHECK (certificate_type IN ('diploma','placement','nomination','other')),
  template_key text NOT NULL,
  media_file_id uuid REFERENCES media_files(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','generated','issued','void')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  issued_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_certificates_participant
  ON certificates (event_participant_id, created_at DESC);

-- =========================================================
-- 7. Theme/reference exchange
-- =========================================================

CREATE TABLE exchange_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id uuid NOT NULL REFERENCES rounds(id) ON DELETE RESTRICT,
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  assignment_id uuid REFERENCES assignments(id) ON DELETE RESTRICT,
  exchange_group_key text NOT NULL DEFAULT 'default',
  item_type text NOT NULL DEFAULT 'text'
    CHECK (item_type IN ('text','media','mixed')),
  text_value text,
  media_file_id uuid REFERENCES media_files(id) ON DELETE RESTRICT,
  source_submission_version_id uuid REFERENCES submission_versions(id) ON DELETE RESTRICT,
  submitted_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE exchange_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id uuid NOT NULL REFERENCES rounds(id) ON DELETE RESTRICT,
  exchange_group_key text NOT NULL DEFAULT 'default',
  exchange_item_id uuid NOT NULL REFERENCES exchange_items(id) ON DELETE RESTRICT,
  recipient_event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  self_assignment boolean NOT NULL DEFAULT false,
  source text NOT NULL DEFAULT 'automatic'
    CHECK (source IN ('automatic','manual','fallback')),
  active boolean NOT NULL DEFAULT true,
  previous_assignment_id uuid REFERENCES exchange_assignments(id) ON DELETE RESTRICT,
  replacement_reason text,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  replaced_at timestamptz
);

CREATE UNIQUE INDEX ux_exchange_assignments_active_recipient
  ON exchange_assignments (round_id, exchange_group_key, recipient_event_participant_id)
  WHERE active = true;

-- =========================================================
-- 8. Judging streams / judge slots / targets
-- =========================================================

CREATE TABLE evaluation_streams (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid NOT NULL,
  code text NOT NULL,
  target_type text NOT NULL
    CHECK (target_type IN ('individual','pair','team','group')),
  judging_method text NOT NULL
    CHECK (judging_method IN ('pairwise','criteria')),
  affects_rating boolean NOT NULL DEFAULT false,
  comparisons_per_target_per_judge integer
    CHECK (comparisons_per_target_per_judge IS NULL OR comparisons_per_target_per_judge > 0),
  result_scale_min numeric(6,2) NOT NULL DEFAULT 40,
  result_scale_max numeric(6,2) NOT NULL DEFAULT 100,
  configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, code),
  UNIQUE (id, round_id),
  UNIQUE (id, event_id),
  CHECK (result_scale_min < result_scale_max),
  FOREIGN KEY (round_id, event_id)
    REFERENCES rounds(id, event_id) ON DELETE RESTRICT
);

CREATE TABLE evaluation_judge_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  slot_no integer NOT NULL CHECK (slot_no > 0),
  required boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evaluation_stream_id, slot_no),
  UNIQUE (id, evaluation_stream_id)
);

CREATE TABLE evaluation_judge_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  judge_slot_id uuid NOT NULL REFERENCES evaluation_judge_slots(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','replaced','ended','void')),
  active_from timestamptz NOT NULL DEFAULT now(),
  active_to timestamptz,
  replacement_reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE evaluation_judge_assignments
  ADD CONSTRAINT uq_judge_assignment_id_slot UNIQUE (id, judge_slot_id);

CREATE UNIQUE INDEX ux_judge_slot_one_active_assignment
  ON evaluation_judge_assignments (judge_slot_id)
  WHERE status = 'active';

CREATE TABLE evaluation_targets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  evaluation_stream_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','incomplete','withdrawn','void')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, evaluation_stream_id),
  UNIQUE (id, event_id),
  FOREIGN KEY (evaluation_stream_id, event_id)
    REFERENCES evaluation_streams(id, event_id) ON DELETE RESTRICT
);

CREATE TABLE evaluation_target_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  evaluation_target_id uuid NOT NULL,
  event_participant_id uuid NOT NULL,
  submission_id uuid,
  submission_version_id uuid,
  member_role text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evaluation_target_id, event_participant_id),
  FOREIGN KEY (evaluation_target_id, event_id)
    REFERENCES evaluation_targets(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (event_participant_id, event_id)
    REFERENCES event_participants(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (submission_id, event_participant_id)
    REFERENCES submissions(id, event_participant_id) ON DELETE RESTRICT,
  FOREIGN KEY (submission_version_id, submission_id)
    REFERENCES submission_versions(id, submission_id) ON DELETE RESTRICT,
  CHECK (submission_version_id IS NULL OR submission_id IS NOT NULL)
);

-- =========================================================
-- 9. Pairwise judging
-- =========================================================

CREATE TABLE pairwise_comparisons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  judge_slot_id uuid NOT NULL,
  judge_assignment_id uuid,
  target_a_id uuid NOT NULL,
  target_b_id uuid NOT NULL,
  winner_target_id uuid,
  phase text NOT NULL DEFAULT 'regular'
    CHECK (phase IN ('regular','tie_break')),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','voted','cancelled','void')),
  voted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (judge_slot_id, evaluation_stream_id)
    REFERENCES evaluation_judge_slots(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (judge_assignment_id, judge_slot_id)
    REFERENCES evaluation_judge_assignments(id, judge_slot_id) ON DELETE RESTRICT,
  FOREIGN KEY (target_a_id, evaluation_stream_id)
    REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (target_b_id, evaluation_stream_id)
    REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (winner_target_id, evaluation_stream_id)
    REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT,
  CHECK (target_a_id <> target_b_id),
  CHECK (
    winner_target_id IS NULL
    OR winner_target_id = target_a_id
    OR winner_target_id = target_b_id
  )
);

CREATE INDEX ix_pairwise_pending_by_slot
  ON pairwise_comparisons (judge_slot_id, status);

CREATE UNIQUE INDEX ux_pairwise_no_duplicate_pair_per_slot_phase
  ON pairwise_comparisons (
    evaluation_stream_id,
    judge_slot_id,
    LEAST(target_a_id, target_b_id),
    GREATEST(target_a_id, target_b_id),
    phase
  )
  WHERE status <> 'cancelled';

-- =========================================================
-- 10. Criteria judging
-- =========================================================

CREATE TABLE evaluation_criteria (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  code text NOT NULL,
  label_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
  weight numeric(8,4) NOT NULL DEFAULT 1 CHECK (weight > 0),
  min_score numeric(6,2) NOT NULL DEFAULT 1,
  max_score numeric(6,2) NOT NULL DEFAULT 10,
  sort_order integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evaluation_stream_id, code),
  UNIQUE (id, evaluation_stream_id),
  CHECK (min_score < max_score)
);

CREATE TABLE criterion_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  judge_slot_id uuid NOT NULL,
  judge_assignment_id uuid,
  evaluation_target_id uuid NOT NULL,
  criterion_id uuid NOT NULL,
  score numeric(6,2) NOT NULL,
  status text NOT NULL DEFAULT 'valid'
    CHECK (status IN ('valid','void')),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (judge_slot_id, evaluation_stream_id)
    REFERENCES evaluation_judge_slots(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (judge_assignment_id, judge_slot_id)
    REFERENCES evaluation_judge_assignments(id, judge_slot_id) ON DELETE RESTRICT,
  FOREIGN KEY (evaluation_target_id, evaluation_stream_id)
    REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT,
  FOREIGN KEY (criterion_id, evaluation_stream_id)
    REFERENCES evaluation_criteria(id, evaluation_stream_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_criterion_scores_one_valid_per_slot_target_criterion
  ON criterion_scores (judge_slot_id, evaluation_target_id, criterion_id)
  WHERE status = 'valid';

-- =========================================================
-- 11. Rating snapshots at Round start
-- =========================================================

CREATE TABLE round_rating_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid NOT NULL,
  event_participant_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  rating_snapshot numeric(10,4) NOT NULL,
  calibration_rounds_completed_before smallint NOT NULL
    CHECK (calibration_rounds_completed_before BETWEEN 0 AND 3),
  rating_status_before text NOT NULL
    CHECK (rating_status_before IN ('calibrating','established')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, event_participant_id),
  UNIQUE (id, user_id),
  FOREIGN KEY (round_id, event_id)
    REFERENCES rounds(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (event_participant_id, event_id)
    REFERENCES event_participants(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (event_participant_id, user_id)
    REFERENCES event_participants(id, user_id) ON DELETE RESTRICT
);

CREATE INDEX ix_round_rating_snapshots_round
  ON round_rating_snapshots (round_id);

-- =========================================================
-- 12. Evaluation results / Round results / Event results
-- =========================================================

CREATE TABLE evaluation_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_stream_id uuid NOT NULL REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  evaluation_target_id uuid NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  is_current boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','published','superseded')),
  raw_score numeric(14,6),
  model_score numeric(14,6),
  display_score numeric(6,2),
  internal_rank integer,
  qualified boolean,
  tie_break_needed boolean NOT NULL DEFAULT false,
  calculation_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  needs_recalculation boolean NOT NULL DEFAULT false,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evaluation_stream_id, evaluation_target_id, version_no),
  CHECK (internal_rank IS NULL OR internal_rank > 0),
  CHECK (display_score IS NULL OR (display_score >= 0 AND display_score <= 100)),
  CHECK (NOT is_current OR status <> 'superseded'),
  CHECK (status <> 'published' OR published_at IS NOT NULL),
  FOREIGN KEY (evaluation_target_id, evaluation_stream_id)
    REFERENCES evaluation_targets(id, evaluation_stream_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_evaluation_results_current
  ON evaluation_results (evaluation_stream_id, evaluation_target_id)
  WHERE is_current = true;

CREATE TABLE round_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid NOT NULL,
  event_participant_id uuid NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  is_current boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','published','superseded')),
  display_score numeric(6,2),
  advanced boolean,
  competition_status_after text
    CHECK (competition_status_after IN (
      'active','eliminated','diploma_only','disqualified','completed'
    )),
  calculation_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  needs_recalculation boolean NOT NULL DEFAULT false,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, event_participant_id, version_no),
  CHECK (display_score IS NULL OR (display_score >= 0 AND display_score <= 100)),
  CHECK (NOT is_current OR status <> 'superseded'),
  CHECK (status <> 'published' OR published_at IS NOT NULL),
  FOREIGN KEY (round_id, event_id)
    REFERENCES rounds(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (event_participant_id, event_id)
    REFERENCES event_participants(id, event_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_round_results_current
  ON round_results (round_id, event_participant_id)
  WHERE is_current = true;

CREATE TABLE event_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  event_participant_id uuid REFERENCES event_participants(id) ON DELETE RESTRICT,
  evaluation_target_id uuid REFERENCES evaluation_targets(id) ON DELETE RESTRICT,
  result_kind text NOT NULL
    CHECK (result_kind IN ('personal','pair','team','group')),
  version_no integer NOT NULL CHECK (version_no > 0),
  is_current boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','published','superseded')),
  final_score numeric(10,4),
  internal_rank integer,
  award_place integer CHECK (award_place IS NULL OR award_place > 0),
  tie_break_needed boolean NOT NULL DEFAULT false,
  game_counted boolean,
  diploma_eligible boolean,
  calculation_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  needs_recalculation boolean NOT NULL DEFAULT false,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(event_participant_id, evaluation_target_id) = 1),
  CHECK (internal_rank IS NULL OR internal_rank > 0),
  CHECK (final_score IS NULL OR (final_score >= 0 AND final_score <= 100)),
  CHECK (NOT is_current OR status <> 'superseded'),
  CHECK (status <> 'published' OR published_at IS NOT NULL),
  FOREIGN KEY (event_participant_id, event_id)
    REFERENCES event_participants(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (evaluation_target_id, event_id)
    REFERENCES evaluation_targets(id, event_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_event_results_version_participant
  ON event_results (event_id, event_participant_id, result_kind, version_no)
  WHERE event_participant_id IS NOT NULL;

CREATE UNIQUE INDEX ux_event_results_version_target
  ON event_results (event_id, evaluation_target_id, result_kind, version_no)
  WHERE evaluation_target_id IS NOT NULL;

CREATE UNIQUE INDEX ux_event_results_current_participant
  ON event_results (event_id, event_participant_id, result_kind)
  WHERE is_current = true AND event_participant_id IS NOT NULL;

CREATE UNIQUE INDEX ux_event_results_current_target
  ON event_results (event_id, evaluation_target_id, result_kind)
  WHERE is_current = true AND evaluation_target_id IS NOT NULL;

-- =========================================================
-- 12. Rating ledger / league history
-- =========================================================

CREATE TABLE rating_transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ledger_seq bigserial UNIQUE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid REFERENCES rounds(id) ON DELETE RESTRICT,
  evaluation_stream_id uuid REFERENCES evaluation_streams(id) ON DELETE RESTRICT,
  round_rating_snapshot_id uuid REFERENCES round_rating_snapshots(id) ON DELETE RESTRICT,
  method text NOT NULL
    CHECK (method IN (
      'initial_seeding','pairwise_elo','criteria_virtual_elo',
      'manual_adjustment','recalculation'
    )),
  formula_version text NOT NULL,
  rating_before numeric(10,4),
  delta_before_cap numeric(10,4),
  delta_after_cap numeric(10,4),
  rating_after numeric(10,4) NOT NULL,
  k_used numeric(10,4),
  cap_used numeric(10,4),
  calibration_round_no smallint
    CHECK (calibration_round_no IS NULL OR calibration_round_no BETWEEN 1 AND 3),
  calibration_rounds_completed_before smallint
    CHECK (calibration_rounds_completed_before IS NULL OR calibration_rounds_completed_before BETWEEN 0 AND 3),
  calibration_rounds_completed_after smallint
    CHECK (calibration_rounds_completed_after IS NULL OR calibration_rounds_completed_after BETWEEN 0 AND 3),
  calculation_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','superseded','void')),
  superseded_by_id uuid REFERENCES rating_transactions(id) ON DELETE RESTRICT,
  idempotency_key text NOT NULL UNIQUE,
  applied_at timestamptz NOT NULL DEFAULT now(),
  CHECK (round_id IS NULL OR event_id IS NOT NULL),
  CHECK (evaluation_stream_id IS NULL OR round_id IS NOT NULL),
  FOREIGN KEY (round_id, event_id)
    REFERENCES rounds(id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (evaluation_stream_id, round_id)
    REFERENCES evaluation_streams(id, round_id) ON DELETE RESTRICT,
  FOREIGN KEY (round_rating_snapshot_id, user_id)
    REFERENCES round_rating_snapshots(id, user_id) ON DELETE RESTRICT
);

CREATE INDEX ix_rating_transactions_user_seq
  ON rating_transactions (user_id, ledger_seq);

CREATE TABLE league_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  season_id uuid NOT NULL REFERENCES seasons(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  old_league text CHECK (old_league IN ('bronze','silver','gold')),
  new_league text NOT NULL CHECK (new_league IN ('bronze','silver','gold')),
  rating_snapshot numeric(10,4) NOT NULL,
  threshold_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','superseded','void')),
  superseded_by_id uuid REFERENCES league_history(id) ON DELETE RESTRICT,
  changed_at timestamptz NOT NULL DEFAULT now(),
  CHECK (superseded_by_id IS NULL OR status = 'superseded'),
  FOREIGN KEY (event_id, season_id)
    REFERENCES events(id, season_id) ON DELETE RESTRICT
);

-- =========================================================
-- 13. League Points ledger
-- =========================================================

CREATE TABLE points_transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  lifetime_delta integer NOT NULL DEFAULT 0,
  available_delta integer NOT NULL DEFAULT 0,
  reason_code text NOT NULL,
  reason_text text,
  points_rule_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  idempotency_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_points_transactions_user
  ON points_transactions (user_id, created_at);

-- =========================================================
-- 14. Consents / notifications / support
-- =========================================================

CREATE TABLE consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  consent_type text NOT NULL,
  accepted boolean NOT NULL,
  document_version text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_consents_user_type
  ON consents (user_id, consent_type, recorded_at DESC);

CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid REFERENCES rounds(id) ON DELETE RESTRICT,
  notification_type text NOT NULL,
  channel text NOT NULL CHECK (channel IN ('telegram','email','in_app')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','sent','failed','cancelled','read')),
  idempotency_key text NOT NULL UNIQUE,
  sent_at timestamptz,
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_notifications_user_created
  ON notifications (user_id, created_at DESC);

CREATE TABLE support_threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  round_id uuid REFERENCES rounds(id) ON DELETE RESTRICT,
  submission_id uuid REFERENCES submissions(id) ON DELETE RESTRICT,
  payment_id uuid REFERENCES payments(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','waiting_user','waiting_admin','closed')),
  subject text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_support_threads_updated_at
BEFORE UPDATE ON support_threads
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE support_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  support_thread_id uuid NOT NULL REFERENCES support_threads(id) ON DELETE RESTRICT,
  author_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  author_role text NOT NULL CHECK (author_role IN ('participant','admin','system')),
  body text NOT NULL,
  delivery_channel text CHECK (delivery_channel IN ('telegram','email','in_app')),
  delivery_status text
    CHECK (delivery_status IN ('pending','sent','failed','not_required')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- =========================================================
-- 15. Audit / recalculation / jobs / technical errors
-- =========================================================

CREATE TABLE audit_log (
  id bigserial PRIMARY KEY,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  action text NOT NULL,
  before_data jsonb,
  after_data jsonb,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_entity
  ON audit_log (entity_type, entity_id, created_at DESC);

CREATE TABLE recalculation_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  requested_by uuid REFERENCES users(id) ON DELETE SET NULL,
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  reason text NOT NULL,
  dependency_chain jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','running','completed','cancelled','failed')),
  approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
  approved_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  token_hash text NOT NULL UNIQUE,
  token_type text NOT NULL CHECK (token_type IN ('set_password','reset_password','email_verify')),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE background_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type text NOT NULL,
  run_at timestamptz NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','running','completed','failed','cancelled')),
  idempotency_key text NOT NULL UNIQUE,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error text,
  locked_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_background_jobs_due
  ON background_jobs (run_at, status)
  WHERE status = 'pending';

CREATE TABLE system_errors (
  id bigserial PRIMARY KEY,
  severity text NOT NULL CHECK (severity IN ('info','warning','error','critical')),
  component text NOT NULL,
  error_code text,
  message text NOT NULL,
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  acknowledged_by uuid REFERENCES users(id) ON DELETE SET NULL,
  acknowledged_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_system_errors_unacked
  ON system_errors (severity, created_at DESC)
  WHERE acknowledged_at IS NULL;

-- Frequently traversed foreign-key/query paths
CREATE INDEX ix_participant_assignments_event_participant
  ON participant_assignments (event_participant_id, assignment_id);
CREATE INDEX ix_submissions_event_participant
  ON submissions (event_participant_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_submission_versions_submission
  ON submission_versions (submission_id, version_no);
CREATE INDEX ix_exchange_items_round_participant
  ON exchange_items (round_id, event_participant_id);
CREATE INDEX ix_exchange_assignments_item
  ON exchange_assignments (exchange_item_id) WHERE active = true;
CREATE INDEX ix_evaluation_targets_stream
  ON evaluation_targets (evaluation_stream_id, status);
CREATE INDEX ix_evaluation_target_members_target
  ON evaluation_target_members (evaluation_target_id);
CREATE INDEX ix_pairwise_stream_status
  ON pairwise_comparisons (evaluation_stream_id, status, phase);
CREATE INDEX ix_criterion_scores_target
  ON criterion_scores (evaluation_target_id, status);
CREATE INDEX ix_round_results_participant
  ON round_results (event_participant_id, round_id);
CREATE INDEX ix_event_results_participant
  ON event_results (event_participant_id, event_id) WHERE event_participant_id IS NOT NULL;
CREATE INDEX ix_league_history_user_season
  ON league_history (user_id, season_id, changed_at DESC);

COMMIT;
