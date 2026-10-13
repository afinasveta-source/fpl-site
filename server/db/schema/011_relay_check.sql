-- Face Painting League — migration 011
-- Тур-эстафета с проверкой организатора (решение Светланы 13.10, вечер): исходники уходят участницам не сами,
-- а после ручной проверки. Организатор может убрать работу из исходников (плохое фото, не по заданию) — с причиной.
-- Только добавляет колонки; существующие данные не меняет.

BEGIN;

ALTER TABLE exchange_items ADD COLUMN excluded_at timestamptz;
ALTER TABLE exchange_items ADD COLUMN excluded_by uuid REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE exchange_items ADD COLUMN excluded_reason text CHECK (excluded_reason IS NULL OR length(excluded_reason) <= 500);

COMMIT;
