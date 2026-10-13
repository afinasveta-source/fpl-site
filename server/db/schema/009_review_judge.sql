-- Face Painting League — migration 009
-- Аудиоразбор (решение Светланы 13.10, вечер): разбор записывает судья прямо в кабинете и он сразу уходит участнице;
-- заказ открывается после окончания Игры; оплата — по счёту (ссылку присылает организатор).
--   reviewer_id — судья, которому организатор поручил разбор (видит работы участницы этой Игры и записывает аудио);
--   event_id    — Игра, работы которой разбираются.
-- Только добавляет колонки; существующие данные не меняет.

BEGIN;

ALTER TABLE review_orders ADD COLUMN reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE review_orders ADD COLUMN event_id uuid REFERENCES events(id) ON DELETE SET NULL;
CREATE INDEX ix_review_orders_reviewer ON review_orders (reviewer_id) WHERE reviewer_id IS NOT NULL;

COMMIT;
