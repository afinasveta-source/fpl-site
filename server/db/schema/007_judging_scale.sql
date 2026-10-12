-- Face Painting League — migration 007
-- Судейство в кабинете (этап 4, решение Светланы 12.10.2026): балл тура — по шкале 1–100.
-- Шкала 40–100 была только в первом туре Игры 01 (её данные перенесены из бота с прежними названиями способа).
-- Чтобы старый и новый расчёт не путались, у нового — свои названия:
--   win_share_100_v1     — сравнение пар: балл = 1 + 99 × доля побед (с переголосованием), округление половина вверх;
--   criteria_mean_100_v1 — критерии: оценки судей 1–100, среднее с весами критериев, затем среднее по судьям.
-- Только расширяет правило; существующие данные не меняет.

BEGIN;

ALTER TABLE evaluation_streams DROP CONSTRAINT lr_stream_scoring_method;
ALTER TABLE evaluation_streams ADD CONSTRAINT lr_stream_scoring_method
  CHECK (scoring_method IS NULL OR scoring_method IN
         ('win_share_v1','bt_v1','criteria_mean_v1','win_share_100_v1','criteria_mean_100_v1'));

COMMIT;
