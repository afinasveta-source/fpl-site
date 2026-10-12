-- Face Painting League — migration 004
-- Скидки в магазине по итогам Игры (InSales), пары и группы в задании, набор автоматических уведомлений,
-- призы Игры, материал от организатора, «судья не участник» в обе стороны.
-- Решения Светланы 11–12.10.2026 (прототип кабинетов, CHANGES_FOR_REVIEW.txt). База на 11.10 пустая — данных не трогаем.
-- Диплом: один тип ('diploma'); место (только 1–3) и лига пишутся в certificates.issue_snapshot — схема не меняется.

BEGIN;

------------------------------------------------------------------------
-- 1. Призы Игры: строки «за что — приз» в описании Игры.
------------------------------------------------------------------------
CREATE TABLE event_prizes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  sort_order integer NOT NULL DEFAULT 0,
  criterion text NOT NULL CHECK (btrim(criterion) <> ''),
  prize text NOT NULL CHECK (btrim(prize) <> ''),
  league text CHECK (league IS NULL OR league IN ('bronze','silver','gold')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_event_prizes_event ON event_prizes (event_id, sort_order);
CREATE TRIGGER trg_event_prizes_updated_at BEFORE UPDATE ON event_prizes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

------------------------------------------------------------------------
-- 2. Скидки участникам по итогам Игры.
--    Правило: кому (все прошедшие Игру / 1 место / 2–3 / 1–3 / лига), скидка, срок, откуда коды.
--    Коды: 'generate_push' — кабинет сам создаёт код и загружает его в магазин через API InSales;
--          'uploaded' — готовый список, выгруженный из InSales.
--    Выдача — при подведении итога Игры, вместе с номерами дипломов. Один код — одному человеку.
--    Ключ API InSales хранится в файле на сервере, не в базе.
------------------------------------------------------------------------
ALTER TABLE events ADD COLUMN reward_multi_mode text NOT NULL DEFAULT 'all'
  CHECK (reward_multi_mode IN ('all','first'));
COMMENT ON COLUMN events.reward_multi_mode IS
  'Если участник подходит под несколько правил скидок: all — выдать все, first — только первое по sort_order';

CREATE TABLE reward_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  sort_order integer NOT NULL DEFAULT 0,
  audience text NOT NULL
    CHECK (audience IN ('finished','place_1','place_2_3','place_1_3','league')),
  league text CHECK (league IS NULL OR league IN ('bronze','silver','gold')),
  discount_type text NOT NULL CHECK (discount_type IN ('percent','fixed')),
  discount_value numeric(12,2) NOT NULL CHECK (discount_value > 0),
  currency char(3) NOT NULL DEFAULT 'RUB',
  valid_until timestamptz,
  code_source text NOT NULL CHECK (code_source IN ('generate_push','uploaded')),
  code_prefix text,
  message_template text,
  active boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((audience = 'league') = (league IS NOT NULL)),
  CHECK (discount_type <> 'percent' OR discount_value <= 100)
);
CREATE INDEX ix_reward_rules_event ON reward_rules (event_id, sort_order) WHERE active;
CREATE TRIGGER trg_reward_rules_updated_at BEFORE UPDATE ON reward_rules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE reward_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reward_rule_id uuid NOT NULL REFERENCES reward_rules(id) ON DELETE RESTRICT,
  code text NOT NULL CHECK (btrim(code) <> ''),
  origin text NOT NULL CHECK (origin IN ('generated','uploaded')),
  status text NOT NULL DEFAULT 'available'
    CHECK (status IN ('available','issued','redeemed','void')),
  event_participant_id uuid REFERENCES event_participants(id) ON DELETE RESTRICT,
  issued_at timestamptz,
  redeemed_at timestamptz,
  shop_provider text NOT NULL DEFAULT 'insales',
  shop_code_id text,
  shop_sync_status text NOT NULL DEFAULT 'not_needed'
    CHECK (shop_sync_status IN ('not_needed','pending','synced','failed')),
  shop_synced_at timestamptz,
  shop_error text,
  notification_id uuid REFERENCES notifications(id) ON DELETE RESTRICT,
  void_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- выданный код всегда с человеком и временем
  CHECK (status NOT IN ('issued','redeemed') OR (event_participant_id IS NOT NULL AND issued_at IS NOT NULL)),
  CHECK (status <> 'available' OR (event_participant_id IS NULL AND issued_at IS NULL)),
  CHECK (status <> 'redeemed' OR redeemed_at IS NOT NULL),
  CHECK (status <> 'void' OR void_reason IS NOT NULL),
  -- созданный кабинетом код сначала загружается в магазин, иначе в магазине он не сработает
  CHECK (origin <> 'generated' OR shop_sync_status <> 'not_needed'),
  CHECK (status NOT IN ('issued','redeemed') OR shop_sync_status IN ('not_needed','synced')),
  CHECK (shop_sync_status <> 'synced' OR shop_synced_at IS NOT NULL)
);
CREATE UNIQUE INDEX ux_reward_codes_code ON reward_codes (shop_provider, lower(code));
CREATE UNIQUE INDEX ux_reward_codes_one_per_rule ON reward_codes (reward_rule_id, event_participant_id)
  WHERE status IN ('issued','redeemed');
CREATE INDEX ix_reward_codes_pool ON reward_codes (reward_rule_id, status);
CREATE INDEX ix_reward_codes_participant ON reward_codes (event_participant_id) WHERE event_participant_id IS NOT NULL;
CREATE TRIGGER trg_reward_codes_updated_at BEFORE UPDATE ON reward_codes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Код выдаётся только участнику той же Игры; выданный код не переходит к другому человеку.
CREATE FUNCTION lr_reward_code_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rule_event uuid; part_event uuid;
BEGIN
  IF NEW.event_participant_id IS NOT NULL THEN
    SELECT event_id INTO rule_event FROM reward_rules WHERE id = NEW.reward_rule_id;
    SELECT event_id INTO part_event FROM event_participants WHERE id = NEW.event_participant_id;
    IF rule_event IS DISTINCT FROM part_event THEN
      RAISE EXCEPTION 'reward code can be issued only to a participant of the same Game';
    END IF;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status IN ('issued','redeemed') AND (
       NEW.event_participant_id IS DISTINCT FROM OLD.event_participant_id
       OR NEW.code IS DISTINCT FROM OLD.code
       OR NEW.reward_rule_id IS DISTINCT FROM OLD.reward_rule_id
       OR NEW.status = 'available') THEN
    RAISE EXCEPTION 'issued reward code cannot be moved; void it and issue another one';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_reward_code_guard BEFORE INSERT OR UPDATE ON reward_codes
  FOR EACH ROW EXECUTE FUNCTION lr_reward_code_guard();

------------------------------------------------------------------------
-- 3. Пары и группы в задании тура (2–6 человек).
--    Кто с кем, как собраны, сдаёт каждый или одна работа на группу, какой контакт видят партнёры.
--    Капитан, проход группы и выбывший партнёр — решения владельца позже (роль 'captain' уже есть).
------------------------------------------------------------------------
CREATE TABLE task_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id uuid NOT NULL REFERENCES rounds(id) ON DELETE RESTRICT,
  group_no integer NOT NULL CHECK (group_no > 0),
  formation text NOT NULL
    CHECK (formation IN ('random','city','cross_league','same_league','manual')),
  submission_mode text NOT NULL CHECK (submission_mode IN ('each','one_per_group')),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','void')),
  sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (round_id, group_no),
  UNIQUE (id, round_id),
  CHECK (status <> 'sent' OR sent_at IS NOT NULL)
);
CREATE TRIGGER trg_task_groups_updated_at BEFORE UPDATE ON task_groups
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE task_group_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_group_id uuid NOT NULL,
  round_id uuid NOT NULL,
  event_participant_id uuid NOT NULL REFERENCES event_participants(id) ON DELETE RESTRICT,
  member_role text NOT NULL DEFAULT 'member' CHECK (member_role IN ('member','captain')),
  shared_contact_id uuid REFERENCES user_contacts(id) ON DELETE RESTRICT,
  source text NOT NULL DEFAULT 'automatic' CHECK (source IN ('automatic','manual','late_join')),
  active boolean NOT NULL DEFAULT true,
  joined_at timestamptz NOT NULL DEFAULT now(),
  left_at timestamptz,
  left_reason text,
  FOREIGN KEY (task_group_id, round_id) REFERENCES task_groups(id, round_id) ON DELETE RESTRICT,
  CHECK (active OR left_at IS NOT NULL)
);
-- В одном туре человек — только в одной действующей группе.
CREATE UNIQUE INDEX ux_task_group_members_one_active ON task_group_members (round_id, event_participant_id)
  WHERE active;
CREATE INDEX ix_task_group_members_group ON task_group_members (task_group_id) WHERE active;

-- Группа — из участников той же Игры, не больше 6 человек; контакт для партнёров — контакт самого участника.
CREATE FUNCTION lr_task_group_member_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE round_event uuid; part_event uuid; part_user uuid; n integer;
BEGIN
  SELECT event_id INTO round_event FROM rounds WHERE id = NEW.round_id;
  SELECT event_id, user_id INTO part_event, part_user FROM event_participants WHERE id = NEW.event_participant_id;
  IF round_event IS DISTINCT FROM part_event THEN
    RAISE EXCEPTION 'group member must be a participant of the same Game';
  END IF;
  IF NEW.shared_contact_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM user_contacts c WHERE c.id = NEW.shared_contact_id AND c.user_id = part_user) THEN
    RAISE EXCEPTION 'shared contact must belong to the group member';
  END IF;
  IF NEW.active THEN
    SELECT count(*) INTO n FROM task_group_members
      WHERE task_group_id = NEW.task_group_id AND active AND id <> NEW.id;
    IF n >= 6 THEN
      RAISE EXCEPTION 'a group can have at most 6 members';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_task_group_member_guard BEFORE INSERT OR UPDATE ON task_group_members
  FOR EACH ROW EXECUTE FUNCTION lr_task_group_member_guard();

------------------------------------------------------------------------
-- 4. Набор автоматических уведомлений: какое событие, включено ли, каналы, текст.
--    event_id NULL — общий набор лиги; строка с event_id — настройка конкретной Игры поверх общего.
--    Отправленные сообщения по-прежнему пишутся в notifications (notification_type = rule_key).
------------------------------------------------------------------------
CREATE TABLE notification_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid REFERENCES events(id) ON DELETE RESTRICT,
  rule_key text NOT NULL CHECK (rule_key ~ '^[a-zA-Z][a-zA-Z0-9_]*$'),
  group_title text NOT NULL,
  title text NOT NULL,
  audience text NOT NULL,
  timing text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  channels text[] NOT NULL DEFAULT ARRAY['in_app','telegram']::text[]
    CHECK (cardinality(channels) > 0 AND channels <@ ARRAY['in_app','telegram','email']::text[]),
  template_text text NOT NULL CHECK (btrim(template_text) <> ''),
  sort_order integer NOT NULL DEFAULT 0,
  updated_by uuid REFERENCES users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (event_id, rule_key)
);
CREATE TRIGGER trg_notification_rules_updated_at BEFORE UPDATE ON notification_rules
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO notification_rules (rule_key, group_title, title, audience, timing, channels, template_text, sort_order) VALUES
  ('reg', 'Регистрация и Игра', 'Регистрация в Игре подтверждена', 'участник', 'сразу', ARRAY['in_app','telegram']::text[], 'Вы записаны на {Игра}. Старт — {дата старта}. Правила и задания — в кабинете.', 0),
  ('start', 'Регистрация и Игра', 'Игра начинается', 'участники Игры', 'за 1 день до старта', ARRAY['in_app','telegram']::text[], 'Завтра стартует {Игра}. Первое задание откроется {дата}.', 10),
  ('rules', 'Регистрация и Игра', 'Вышла новая редакция Правил', 'активные участники', 'при публикации', ARRAY['in_app','telegram']::text[], 'Обновились Правила лиги (редакция {версия}). Примите их в кабинете — без этого сдача работ закрыта.', 20),
  ('rulesRemind', 'Регистрация и Игра', 'Напоминание: Правила не приняты', 'не принявшие новую редакцию', 'за 2 дня до срока сдачи', ARRAY['in_app','telegram']::text[], 'Чтобы сдать работу тура {N}, примите Правила {версия} в кабинете.', 30),
  ('prep', 'Сбор, материалы и группы', 'Начался сбор (тема / картинка)', 'участники тура', 'при открытии сбора', ARRAY['in_app','telegram']::text[], 'Пришлите {что} для тура {N} до {срок сбора}.', 40),
  ('prepRemind', 'Сбор, материалы и группы', 'Скоро конец сбора', 'не приславшие', 'за 1 день', ARRAY['in_app','telegram']::text[], 'До конца сбора к туру {N} остался день. Пришлите {что} до {срок сбора}.', 50),
  ('mat', 'Сбор, материалы и группы', 'Материал выдан', 'участник', 'при открытии тура', ARRAY['in_app','telegram']::text[], 'В задании тура {N} — ваш материал. Посмотрите его в кабинете.', 60),
  ('matChange', 'Сбор, материалы и группы', 'Материал изменён', 'участник', 'сразу после изменения', ARRAY['in_app','telegram']::text[], 'Организатор заменил ваш материал к туру {N}. Новый — в задании.', 70),
  ('grp', 'Сбор, материалы и группы', 'Группа собрана', 'участник', 'при открытии тура', ARRAY['in_app','telegram']::text[], 'Вы делаете тур {N} вместе с: {партнёры}. Контакты — в задании.', 80),
  ('grpChange', 'Сбор, материалы и группы', 'Состав группы изменён', 'затронутые участники', 'сразу после изменения', ARRAY['in_app','telegram']::text[], 'Состав вашей группы в туре {N} изменился: {партнёры}.', 90),
  ('round', 'Тур и работы', 'Открылся тур', 'участники тура', 'при открытии', ARRAY['in_app','telegram']::text[], 'Тур {N} «{задание}» открыт. Сдать до {срок}.', 100),
  ('deadline', 'Тур и работы', 'Приближается срок сдачи', 'не сдавшие', 'за 1 день и за 3 часа', ARRAY['in_app','telegram']::text[], 'До конца сдачи тура {N} — {осталось}. Работа ещё не сдана.', 110),
  ('sent', 'Тур и работы', 'Работа принята / заменена', 'участник', 'сразу', ARRAY['in_app','telegram']::text[], 'Работа тура {N} принята. До {срок} её можно заменить.', 120),
  ('fix', 'Тур и работы', 'Организатор исправил материалы работы', 'участник', 'сразу', ARRAY['in_app','telegram']::text[], 'Организатор поправил материалы вашей работы тура {N}: {что}.', 130),
  ('mateSent', 'Тур и работы', 'Партнёр по группе сдал работу', 'остальные в группе', 'сразу', ARRAY['in_app']::text[], '{Партнёр} сдал(а) работу тура {N}.', 140),
  ('grpRemind', 'Тур и работы', 'В группе сдали не все', 'не сдавшие в группе', 'за 1 день до срока', ARRAY['in_app','telegram']::text[], 'В вашей группе ещё не все сдали работу тура {N}. Срок — {срок}.', 150),
  ('gallery', 'Тур и работы', 'Открылась галерея тура', 'участники тура', 'после конца приёма', ARRAY['in_app','telegram']::text[], 'Работы тура {N} — в галерее.', 160),
  ('judge', 'Судейство', 'Судье назначены пары', 'судья', 'сразу', ARRAY['telegram']::text[], 'Вам назначено {N} пар в туре {N}. Срок — {срок оценивания}.', 170),
  ('judgeRemind', 'Судейство', 'Напоминание о сроке оценивания', 'судьи с незавершёнными парами', 'за 1 день и по кнопке', ARRAY['telegram']::text[], 'Осталось оценить {N} пар до {срок}.', 180),
  ('revote', 'Судейство', 'Назначено переголосование', 'выбранные судьи', 'сразу', ARRAY['telegram']::text[], 'Срочно: переголосование, {лига}, {N} пар. До {срок}.', 190),
  ('revoteExt', 'Судейство', 'Срок переголосования продлён', 'судьи переголосования', 'сразу', ARRAY['telegram']::text[], 'Срок переголосования продлён до {срок}.', 200),
  ('results', 'Результаты и дипломы', 'Опубликованы результаты тура', 'участники тура', 'при публикации', ARRAY['in_app','telegram']::text[], 'Итоги тура {N} опубликованы: ваша оценка, место и что дальше — в кабинете.', 210),
  ('status', 'Результаты и дипломы', 'Выбыл или перешёл вне конкурса', 'участник', 'при смене статуса', ARRAY['in_app','telegram']::text[], 'По итогам тура {N} вы продолжаете вне конкурса. Диплом — если все работы сданы до конца Игры.', 220),
  ('revoteRes', 'Результаты и дипломы', 'Итог переголосования', 'организатор', 'сразу', ARRAY['in_app']::text[], 'Переголосование ({лига}) завершено. Проверьте результаты перед публикацией.', 230),
  ('diploma', 'Результаты и дипломы', 'Диплом готов (номер присвоен)', 'участники с дипломом', 'при подведении итога Игры', ARRAY['in_app','telegram']::text[], 'Ваш диплом {номер} готов — скачайте его в кабинете.', 240),
  ('revoke', 'Профиль и поддержка', 'Отзыв согласия на публикацию принят', 'участник', 'сразу', ARRAY['in_app']::text[], 'Согласие отозвано. Ваши работы больше не показываются в галерее и не уходят в соцсети.', 250),
  ('support', 'Профиль и поддержка', 'Получен ответ поддержки', 'участник', 'сразу', ARRAY['in_app','telegram']::text[], 'Ответ на ваше обращение «{тема}» — в кабинете.', 260),
  ('discount', 'Результаты и дипломы', 'Скидка за прохождение Игры', 'получившие скидку', 'при подведении итога Игры', ARRAY['in_app','telegram']::text[], 'Спасибо за {Игра}! Ваша скидка {скидка}: {код}. Действует до {дата}.', 270);

------------------------------------------------------------------------
-- 5. Материал к заданию от организатора (личный референс), а не только от участника.
------------------------------------------------------------------------
ALTER TABLE exchange_items ALTER COLUMN event_participant_id DROP NOT NULL;
ALTER TABLE exchange_items ADD COLUMN provided_by uuid REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE exchange_items ADD CONSTRAINT lr_exchange_item_author
  CHECK (num_nonnulls(event_participant_id, provided_by) >= 1);
COMMENT ON COLUMN exchange_items.provided_by IS 'Организатор, загрузивший материал (если материал не от участника)';

------------------------------------------------------------------------
-- 6. Судья не участник этой Игры — и в обратную сторону (в 003 проверялось только назначение судьи на пары).
------------------------------------------------------------------------
CREATE FUNCTION lr_participant_not_judge() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.registration_status <> 'cancelled' AND (
       EXISTS (SELECT 1 FROM event_staff s WHERE s.event_id = NEW.event_id AND s.user_id = NEW.user_id
               AND s.role = 'judge' AND s.active)
       OR EXISTS (SELECT 1 FROM evaluation_judge_assignments a JOIN evaluation_streams st ON st.id = a.evaluation_stream_id
               WHERE st.event_id = NEW.event_id AND a.user_id = NEW.user_id AND a.status = 'active')) THEN
    RAISE EXCEPTION 'a judge of this Game cannot take part in it';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_participant_not_judge BEFORE INSERT OR UPDATE OF user_id, event_id, registration_status ON event_participants
  FOR EACH ROW EXECUTE FUNCTION lr_participant_not_judge();

CREATE FUNCTION lr_staff_judge_not_participant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role = 'judge' AND NEW.active AND EXISTS (
       SELECT 1 FROM event_participants p WHERE p.event_id = NEW.event_id AND p.user_id = NEW.user_id
       AND p.registration_status <> 'cancelled') THEN
    RAISE EXCEPTION 'a participant of this Game cannot judge it';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER lr_staff_judge_not_participant BEFORE INSERT OR UPDATE ON event_staff
  FOR EACH ROW EXECUTE FUNCTION lr_staff_judge_not_participant();

COMMIT;
