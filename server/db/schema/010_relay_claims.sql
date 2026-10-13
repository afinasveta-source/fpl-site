-- Face Painting League — migration 010
-- Игра 01 переходит из бота в кабинет с 3 тура (решения Светланы 13.10, вечер):
--   1. Тур-эстафета («Б повторяет работу А», «А усложняет работу Б»): после срока первой лиги каждой участнице второй лиги
--      выдаётся работа первой лиги как исходник. Таблицы exchange_items / exchange_assignments есть с 001 (одна действующая
--      выдача на участницу в туре — ux_exchange_assignments_active_recipient); здесь — одна запись на сданную версию.
--   2. Заявки на вход участниц Игры 01 из бота (account_claims): участница по общей ссылке оставляет ФИО, email, пароль,
--      страну, город и согласия; организатор находит её в списке перенесённых и подтверждает — у записи из бота
--      появляется вход. До подтверждения аккаунта нет (пароль хранится только хешем).
-- Существующие данные не меняются.

BEGIN;

CREATE UNIQUE INDEX ux_exchange_item_version ON exchange_items (round_id, exchange_group_key, source_submission_version_id)
  WHERE source_submission_version_id IS NOT NULL;

CREATE TABLE account_claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_no integer GENERATED ALWAYS AS IDENTITY UNIQUE,
  event_id uuid REFERENCES events(id) ON DELETE SET NULL,
  full_name text NOT NULL CHECK (length(full_name) BETWEEN 2 AND 200),
  email text NOT NULL CHECK (length(email) BETWEEN 3 AND 254),
  password_hash text NOT NULL,
  country_code text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
  city text NOT NULL CHECK (length(city) BETWEEN 1 AND 120),
  contact text CHECK (contact IS NULL OR length(contact) <= 200),
  consents jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','withdrawn')),
  matched_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
  decided_at timestamptz,
  decision_note text CHECK (decision_note IS NULL OR length(decision_note) <= 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'approved' OR (matched_user_id IS NOT NULL AND decided_at IS NOT NULL)),
  CHECK (status = 'pending' OR decided_at IS NOT NULL)
);
-- одна незакрытая заявка на email; подтверждённая запись из бота — только одна
CREATE UNIQUE INDEX ux_account_claims_pending_email ON account_claims (lower(email)) WHERE status = 'pending';
CREATE UNIQUE INDEX ux_account_claims_approved_user ON account_claims (matched_user_id) WHERE status = 'approved';
CREATE INDEX ix_account_claims_status ON account_claims (status, created_at);

COMMENT ON TABLE account_claims IS 'Заявки участниц из бота на вход в кабинет (Игра 01 с 3 тура); подтверждает организатор';

COMMIT;
