-- Face Painting League — migration 006
-- Кабинет организатора (этап 3, 12.10.2026): ссылка-приглашение для входа; анонимные пожелания с сайта.
-- Участницы из бота заведены без email. Организатор создаёт ссылку (кабинет показывает её, писем пока нет),
-- человек по ней сам указывает email и пароль. Такая ссылка — новый вид одноразового кода 'invite'
-- (email в нём не записан; у 'set_password' email по-прежнему обязателен).
-- Только расширяет правило; существующие данные не меняет.

BEGIN;

ALTER TABLE auth_tokens DROP CONSTRAINT auth_tokens_token_type_check;
ALTER TABLE auth_tokens ADD CONSTRAINT auth_tokens_token_type_check
  CHECK (token_type IN ('set_password','reset_password','email_verify','invite'));

------------------------------------------------------------------------
-- Пожелания лиге с сайта (решение 12.10): без входа, анонимно. Хранится только текст, время и — если человек
-- сам указал — контакт для ответа. IP-адрес и данные браузера не записываются.
------------------------------------------------------------------------
CREATE TABLE feedback_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  body text NOT NULL CHECK (char_length(btrim(body)) BETWEEN 1 AND 2000),
  contact text CHECK (contact IS NULL OR char_length(contact) BETWEEN 1 AND 200),
  page text CHECK (page IS NULL OR char_length(page) <= 200),
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','read','archived')),
  read_at timestamptz,
  read_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status = 'new' OR read_at IS NOT NULL)
);
CREATE INDEX ix_feedback_messages_status ON feedback_messages (status, created_at DESC);

COMMIT;
