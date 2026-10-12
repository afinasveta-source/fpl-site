-- Face Painting League — migration 007
-- Этапы 4–5 кабинета (12.10.2026): балл тура 1–100, итоги Игры, номера дипломов.
--
-- Судейство в кабинете (этап 4, решение Светланы 12.10.2026): балл тура — по шкале 1–100.
-- Шкала 40–100 была только в первом туре Игры 01 (её данные перенесены из бота с прежними названиями способа).
-- bt_v1 из схемы 003 не используется: его шкала не была определена.
-- Чтобы старый и новый расчёт не путались, у нового — свои названия:
--   bt_100_v1            — сравнение пар, модель Брэдли–Терри: балл = 1 + 99 × вероятность обыграть среднюю работу тура
--                          (с переголосованием), округление половина вверх;
--   criteria_mean_100_v1 — критерии: оценки судей 1–100, среднее с весами критериев, затем среднее по судьям.
-- Только расширяет правило; существующие данные не меняет.

BEGIN;

ALTER TABLE evaluation_streams DROP CONSTRAINT lr_stream_scoring_method;
ALTER TABLE evaluation_streams ADD CONSTRAINT lr_stream_scoring_method
  CHECK (scoring_method IS NULL OR scoring_method IN
         ('win_share_v1','bt_v1','criteria_mean_v1','bt_100_v1','criteria_mean_100_v1'));

------------------------------------------------------------------------
-- Итоги Игры (этап 5, решения 12.10).
-- Номер диплома с буквой лиги: FPL-S1-01-G-0001 (сезон, Игра, лига G/S/B, номер в лиге по месту, потом по алфавиту).
-- Прежний формат без лиги (FPL-S1-01-0247) не выдавался — правило заменяется.
------------------------------------------------------------------------
ALTER TABLE certificates DROP CONSTRAINT lr_cert_number_format;
ALTER TABLE certificates ADD CONSTRAINT lr_cert_number_format
  CHECK (certificate_number IS NULL OR certificate_number ~ '^FPL-S[0-9]{1,2}-[0-9]{2}-[GSB]-[0-9]{4}$');

-- Очки FPL за итог Игры — одно (самое высокое) достижение на человека и Игру; отмена — только сторно.
CREATE UNIQUE INDEX lr_pt_one_game_result ON points_transactions (event_id, user_id)
  WHERE reason_code = 'game_result' AND reversal_of_id IS NULL;
-- TOP WORK — +1 за работу, одно начисление на итог тура.
CREATE UNIQUE INDEX lr_pt_one_top_work ON points_transactions (source_id)
  WHERE reason_code = 'top_work' AND reversal_of_id IS NULL;

COMMIT;
