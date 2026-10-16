-- Face Painting League — migration 012
-- Ключи для данных (решение Светланы 16.10): внешний инструмент контента (Codex) читает данные лиги для постов
-- в соцсетях — только чтение, по ключу, который выдаёт организатор в кабинете. Хранится только sha256 ключа;
-- сам ключ показывается один раз при создании. Отозванный ключ перестаёт действовать сразу.
-- Только добавляет таблицу; существующие данные не меняет.

BEGIN;

CREATE TABLE feed_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  comment text CHECK (comment IS NULL OR length(comment) <= 500),
  key_hash text NOT NULL UNIQUE CHECK (key_hash ~ '^[0-9a-f]{64}$'),
  key_hint text NOT NULL CHECK (length(key_hint) BETWEEN 4 AND 16),   -- начало ключа: узнать его в списке
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  use_count bigint NOT NULL DEFAULT 0 CHECK (use_count >= 0),
  revoked_at timestamptz,
  revoked_by uuid REFERENCES users(id) ON DELETE SET NULL
);

COMMIT;
