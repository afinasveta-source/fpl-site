-- Face Painting League — migration 014
-- Пуш-уведомления на телефон и компьютер (Web Push, 17.10): подписки устройств. Доставка отмечается в
-- messenger_deliveries с provider = 'webpush' (одна строка на уведомление — повтора нет).
-- Только добавляет таблицу и расширяет список каналов; существующие данные не меняет.

BEGIN;

CREATE TABLE push_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint text NOT NULL UNIQUE CHECK (endpoint ~ '^https://' AND length(endpoint) <= 1000),
  p256dh text NOT NULL CHECK (length(p256dh) BETWEEN 80 AND 100),
  auth text NOT NULL CHECK (length(auth) BETWEEN 16 AND 40),
  device text CHECK (device IS NULL OR length(device) <= 40),
  created_at timestamptz NOT NULL DEFAULT now(),
  last_ok_at timestamptz
);
CREATE INDEX ix_push_subscriptions_user ON push_subscriptions (user_id);

ALTER TABLE messenger_deliveries DROP CONSTRAINT messenger_deliveries_provider_check;
ALTER TABLE messenger_deliveries ADD CONSTRAINT messenger_deliveries_provider_check
  CHECK (provider IN ('telegram','vk','webpush'));

COMMIT;
