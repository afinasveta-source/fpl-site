-- Face Painting League — migration 013
-- Уведомления в Telegram и ВКонтакте (решение Светланы 16.10): свой бот лиги вместо SaleBot.
-- Участница привязывает мессенджер в кабинете одноразовым кодом (15 минут, один раз); привязка — в external_identities
-- (provider telegram / vk). Бот только доставляет уведомления кабинета: войти в кабинет, сменить пароль или сдать работу
-- через него нельзя. Только добавляет таблицы; существующие данные не меняет.

BEGIN;

CREATE TABLE messenger_link_codes (
  code_hash text PRIMARY KEY CHECK (code_hash ~ '^[0-9a-f]{64}$'),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('telegram','vk')),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz
);
CREATE INDEX ix_messenger_link_codes_user ON messenger_link_codes (user_id, provider);

-- Доставка уведомлений кабинета в мессенджеры: одна строка на уведомление и канал — повтора не будет.
CREATE TABLE messenger_deliveries (
  notification_id uuid NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('telegram','vk')),
  external_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('sending','sent','failed','skipped')),
  error text CHECK (error IS NULL OR length(error) <= 300),
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  PRIMARY KEY (notification_id, provider)
);
CREATE INDEX ix_messenger_deliveries_created ON messenger_deliveries (created_at DESC);

COMMIT;
