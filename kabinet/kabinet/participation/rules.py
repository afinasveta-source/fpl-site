"""Правила участия в Игре: состояние участника, сроки, можно ли сдать или заменить работу.

Здесь только чистые функции над строками базы (dict) и временем `now` — без запросов, чтобы правила
проверялись тестами напрямую. Решения владельца, на которых они основаны:
- сданные фото и ссылку можно заменять до конца срока; после сохранения замены действует новая версия (08.10);
- вне конкурса сроков туров нет: все работы — до конца Игры (completion_deadline); работы вне конкурса не судят (11.10);
- опоздавший (не сдал работу тура в срок) переходит вне конкурса с открытия следующего тура (12.10);
- не прошедший отбор жюри сам выбирает «Участвовать вне конкурса», вернуться в конкурс нельзя (04–05.10);
- зачёт Игры — каждая работа сдана в срок своего тура; диплом — все работы сданы до конца Игры (11.10);
- новая редакция Правил не принята — приём и замена работ закрыты (11.10).
"""
from dataclasses import dataclass

OPENED = {'open', 'closed', 'judging', 'tie_break', 'results_review', 'published'}
ACCEPTANCE_OVER = {'closed', 'judging', 'tie_break', 'results_review', 'published'}
GAME_OVER = {'finished', 'archived'}

# Состояние участия (главная плашка). Хранимые статусы базы → то, что видит человек.
IN, OUTSIDE, OUT_PENDING, ELIMINATED, WITHDRAWN, DISQUALIFIED, PENDING, COMPLETED = (
    'in', 'outside', 'out_pending', 'eliminated', 'withdrawn', 'disqualified', 'pending', 'completed')


def participation_mode(ep):
    """Состояние участия по записи event_participants (None — человек не записан)."""
    if ep is None:
        return None
    reg, comp = ep['registration_status'], ep['competition_status']
    if reg in ('withdrawn', 'cancelled'):
        return WITHDRAWN
    if comp == 'disqualified':
        return DISQUALIFIED
    if reg in ('pre_registered', 'payment_pending'):
        return PENDING
    if comp == 'diploma_only':
        return OUTSIDE
    if comp == 'eliminated':
        return OUT_PENDING if ep['elimination_reason'] == 'judged_out' else ELIMINATED
    if comp == 'completed' or reg == 'completed':
        return COMPLETED
    return IN


def round_opened(rnd, now):
    """Тур открыт (задание видно): организатор открыл его или наступило время открытия."""
    if rnd['status'] == 'draft':
        return False
    if rnd['status'] in OPENED:
        return True
    return rnd['opens_at'] is not None and rnd['opens_at'] <= now


def competition_deadline(rnd, assignment, pa=None):
    """Срок сдачи в конкурсе: личное продление → срок задания → срок тура. (срок, источник)"""
    if pa is not None and pa.get('deadline_override'):
        return pa['deadline_override'], 'personal'
    if assignment.get('deadline'):
        return assignment['deadline'], 'assignment'
    if rnd.get('deadline'):
        return rnd['deadline'], 'round'
    return None, None


def game_deadline(event):
    """Общий срок всех работ вне конкурса — конец Игры."""
    return event['completion_deadline'] or event['ends_at']


def competition_deadline_passed(rnd, assignment, pa, now):
    deadline, _ = competition_deadline(rnd, assignment, pa)
    if deadline is not None:
        return now > deadline
    return rnd['status'] in ACCEPTANCE_OVER


@dataclass
class Window:
    open: bool
    reason: str | None      # почему закрыто: game_over, withdrawn, not_participating, choose_first, eliminated,
                            # not_open, deadline_passed, rules
    deadline: object = None
    deadline_source: str | None = None


def submission_window(event, rnd, assignment, pa, mode, now, rules_ok=True):
    """Можно ли сейчас сдать (или заменить) работу этого задания и до какого срока."""
    if event['status'] in GAME_OVER or mode == COMPLETED:
        return Window(False, 'game_over')
    if mode == WITHDRAWN:
        return Window(False, 'withdrawn')
    if mode in (None, PENDING):
        return Window(False, 'not_participating')
    if mode == OUT_PENDING:
        return Window(False, 'choose_first')
    if mode in (ELIMINATED, DISQUALIFIED):
        return Window(False, 'eliminated')
    if not round_opened(rnd, now):
        return Window(False, 'not_open')
    if mode == IN:
        deadline, source = competition_deadline(rnd, assignment, pa)
        if rnd['status'] in ACCEPTANCE_OVER or (deadline is not None and now > deadline):
            return Window(False, 'deadline_passed', deadline, source)
    else:  # OUTSIDE
        deadline, source = game_deadline(event), 'completion'
        if deadline is not None and now > deadline:
            return Window(False, 'game_over', deadline, source)
    if not rules_ok:
        return Window(False, 'rules', deadline, source)
    return Window(True, None, deadline, source)


def submission_marks(event, rnd, assignment, pa, mode, submitted_at, first_submitted_at):
    """Отметки работы при сдаче: в срок ли тура, идёт ли в конкурс, в диплом.

    «В срок» считается по первой сдаче: замена вне конкурса после срока тура не отменяет того,
    что работа была сдана вовремя (зачёт Игры у отсеянного жюри сохраняется).
    """
    deadline, source = competition_deadline(rnd, assignment, pa)
    first = first_submitted_at or submitted_at
    on_time = deadline is None or first <= deadline
    end = game_deadline(event)
    return {
        'is_on_time': on_time,
        'deadline_applied_at': deadline if deadline is not None else first,
        'deadline_source': source or 'completion',
        'counts_for_competition': mode == IN and on_time,
        'counts_for_diploma': end is None or submitted_at <= end,
    }


def missed_round(event, rounds, assignments_by_round, submitted, pa_by_assignment, now):
    """Первый тур, работу которого человек в конкурсе не сдал в срок (или None).

    submitted — множество id заданий, по которым есть сданная в срок работа.
    Учитываются только обязательные для конкурса задания с правилом «после срока — вне конкурса».
    """
    for rnd in rounds:
        if not round_opened(rnd, now):
            continue
        for a in assignments_by_round.get(rnd['id'], []):
            if not (a['required_for_competition'] and a['on_missed_deadline'] == 'diploma_track'):
                continue
            pa = pa_by_assignment.get(a['id'])
            if competition_deadline_passed(rnd, a, pa, now) and a['id'] not in submitted:
                return rnd
    return None


def late_transfer_due(rounds, missed, now):
    """Опоздавший переходит вне конкурса с открытия следующего тура; если туров больше нет — сразу."""
    later = [r for r in rounds if r['round_no'] > missed['round_no']]
    if not later:
        return True
    return any(round_opened(r, now) for r in later)


def audience_match(rules, ep):
    leagues = (rules or {}).get('leagues')
    if leagues:
        return ep is not None and ep.get('entry_league') in leagues
    return True


def pick_variant(variants, ep):
    """Вариант задания для участника: подходящий по лиге, иначе общий. Неоднозначно — None."""
    active = [v for v in variants if v['active']]
    specific = [v for v in active if (v['audience_rules'] or {}).get('leagues') and audience_match(v['audience_rules'], ep)]
    if len(specific) == 1:
        return specific[0]
    if specific:
        return None
    general = [v for v in active if not (v['audience_rules'] or {}).get('leagues')]
    return general[0] if len(general) == 1 else None


DEFAULT_FORM = {'photo': 'required', 'link': 'optional', 'photo_max': 1}


def submission_form(variant):
    """Состав формы сдачи задаёт организатор: фото, ссылка или оба; поле обязательно / необязательно / нет."""
    schema = dict(DEFAULT_FORM)
    for key in ('photo', 'link'):
        value = (variant.get('submission_schema') or {}).get(key)
        if value in ('required', 'optional', 'none'):
            schema[key] = value
    photo_max = (variant.get('submission_schema') or {}).get('photo_max')
    if isinstance(photo_max, int) and 1 <= photo_max <= 10:
        schema['photo_max'] = photo_max
    if schema['photo'] == 'none':
        schema['photo_max'] = 0
    return schema


def payload_problems(form, photos, link):
    """Чего не хватает, чтобы сдать (пустой список — можно сдавать)."""
    problems = []
    if form['photo'] == 'required' and not photos:
        problems.append('photo_required')
    if len(photos) > form['photo_max']:
        problems.append('too_many_photos')
    if form['link'] == 'required' and not link:
        problems.append('link_required')
    if form['link'] == 'none' and link:
        problems.append('link_not_accepted')
    if form['photo'] == 'none' and form['link'] == 'none':
        problems.append('nothing_to_submit')
    if not photos and not link:
        problems.append('empty')
    return problems


def game_flags(event, mode, rounds, assignments_by_round, on_time, by_end, pa_by_assignment, now):
    """Предварительный статус зачёта Игры и диплома (до подведения итогов).

    on_time — id заданий со сданной в срок тура работой; by_end — со сданной до конца Игры.
    counted: 'ok' (пока всё в срок) / 'lost' / 'no'; diploma: 'pending' / 'all_sent' / 'no'.
    """
    if mode in (WITHDRAWN, DISQUALIFIED, ELIMINATED, None, PENDING):
        return {'counted': 'no', 'diploma': 'no'}
    counted = 'ok'
    for rnd in rounds:
        for a in assignments_by_round.get(rnd['id'], []):
            if a['required_for_game_count'] and competition_deadline_passed(rnd, a, pa_by_assignment.get(a['id']), now) \
                    and a['id'] not in on_time:
                counted = 'lost'
    required = [a for rnd in rounds for a in assignments_by_round.get(rnd['id'], []) if a['required_for_diploma']]
    end = game_deadline(event)
    over = event['status'] in GAME_OVER or (end is not None and now > end)
    if required and all(a['id'] in by_end for a in required):
        diploma = 'all_sent'      # все известные работы сданы до конца Игры; выдачу решают итоги Игры
    elif over:
        diploma = 'no'
    else:
        diploma = 'pending'
    return {'counted': counted, 'diploma': diploma}
