-- Face Painting League — migration 008
-- Платный аудиоразбор работы от судьи (решение Светланы 13.10.2026): проверка спроса в Игре 01.
--   одна работа — 300 ₽, все работы Игры — 700 ₽; разбор записывает судья (сначала Милена), около 5 минут.
-- Заказ — формой на сайте (участницы Игры 01 ещё не в кабинете), оплата — по ссылке, которую организатор
-- присылает вручную; аудио организатор загружает в кабинет, участница слушает его у себя в кабинете.
-- Только добавляет таблицу; существующие данные не меняет.

BEGIN;

CREATE TABLE review_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_no integer GENERATED ALWAYS AS IDENTITY UNIQUE,
  name text NOT NULL CHECK (char_length(btrim(name)) BETWEEN 2 AND 120),
  contact text NOT NULL CHECK (char_length(btrim(contact)) BETWEEN 3 AND 200),
  game_title text CHECK (game_title IS NULL OR char_length(game_title) <= 200),
  scope text NOT NULL CHECK (scope IN ('one','all')),
  round_no smallint CHECK (round_no IS NULL OR round_no BETWEEN 1 AND 30),
  comment text CHECK (comment IS NULL OR char_length(comment) <= 1000),
  price_rub integer NOT NULL CHECK (price_rub > 0),
  reviewer text NOT NULL CHECK (char_length(reviewer) BETWEEN 1 AND 120),
  terms_accepted_at timestamptz NOT NULL,
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','payment_sent','paid','done','cancelled')),
  org_note text CHECK (org_note IS NULL OR char_length(org_note) <= 2000),
  review_text text CHECK (review_text IS NULL OR char_length(review_text) <= 20000),
  audio_key text,
  audio_mime text,
  audio_bytes integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  paid_at timestamptz,
  done_at timestamptz,
  CHECK ((scope = 'one') = (round_no IS NOT NULL)),
  CHECK (status <> 'done' OR audio_key IS NOT NULL OR review_text IS NOT NULL)
);
CREATE INDEX ix_review_orders_status ON review_orders (status, created_at DESC);
CREATE INDEX ix_review_orders_user ON review_orders (user_id) WHERE user_id IS NOT NULL;

COMMIT;
