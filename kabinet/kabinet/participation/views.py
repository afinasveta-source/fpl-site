"""Ответы API участника: Игра, туры, задание. Только сборка данных — правила в rules.py."""
from . import rules as R


def iso(value):
    return value.isoformat() if value is not None else None


def photo_view(m, root):
    base = f"{root}/api/media/{m['id']}"
    meta = m.get('metadata') or {}
    return {'id': str(m['id']), 'view_url': base + '?size=view', 'thumb_url': base + '?size=thumb',
            'width': meta.get('width'), 'height': meta.get('height')}


def event_brief(event):
    return {'id': str(event['id']), 'title': event['title'], 'type': event['event_type'], 'status': event['status'],
            'game_no': event['game_no'], 'starts_at': iso(event['starts_at']), 'ends_at': iso(event['ends_at']),
            'completion_deadline': iso(R.game_deadline(event)),
            'registration_closes_at': iso(event['registration_closes_at']),
            'timezone': event['official_timezone'] or 'Europe/Moscow'}


def me_view(game):
    ep = game.ep
    if ep is None:
        return None
    missed_no = None
    if ep['eliminated_round_id']:
        missed_no = next((r['round_no'] for r in game.rounds if r['id'] == ep['eliminated_round_id']), None)
    return {'mode': game.mode, 'registration_status': ep['registration_status'], 'payment_status': ep['payment_status'],
            'league': ep['entry_league'], 'elimination_reason': ep['elimination_reason'], 'round_no_of_exit': missed_no,
            'out_of_competition_at': iso(ep['out_of_competition_at']), 'joined_at': iso(ep['joined_at'])}


def round_state(rnd, assignments, game, now):
    if not R.round_opened(rnd, now):
        return 'plan'
    if rnd['status'] == 'published':
        return 'pub'
    main = assignments[0] if assignments else None
    if main is not None and not R.competition_deadline_passed(rnd, main, game.pas.get(main['id']), now) \
            and rnd['status'] not in R.ACCEPTANCE_OVER:
        return 'open'
    if main is None and rnd['status'] == 'open':
        return 'open'
    return 'judging'


def my_work_state(game, rnd, assignment, now):
    """Что с работой: none / draft / sent / sent_late / missed."""
    sub = game.subs.get(assignment['id'])
    pa = game.pas.get(assignment['id'])
    if sub and sub['latest_version_id']:
        return 'sent' if sub['is_on_time'] else 'sent_late'
    if sub and game.versions.get(sub['id'], {}).get('draft'):
        draft = 'draft'
    else:
        draft = 'none'
    if R.round_opened(rnd, now) and R.competition_deadline_passed(rnd, assignment, pa, now) and assignment['required_for_competition']:
        return 'missed'
    return draft


def result_view(res, rating=None):
    # Места до конца Игры не показываются (Правила, п. 7.3; решение 12.10) — только балл, TOP WORK, проход, рейтинг.
    if not res:
        return None
    return {'score': float(res['display_score']) if res['display_score'] is not None else None,
            'advanced': res['advanced'], 'league': res['league'], 'top_work': res['top_work'],
            'published_at': iso(res['published_at']), 'rating': rating}


def work_photo(game, assignment, root):
    """Миниатюра сданной работы тура (первое фото действующей версии) — в списке туров и итоге тура;
    у туров 1–2 Игры 01 — фото из бота (source='migration')."""
    sub = game.subs.get(assignment['id'])
    version = game.versions.get(sub['id'], {}).get('latest') if sub else None
    media = game.media.get(version['id']) if version else None
    if not media:
        return None
    return photo_view(media[0], root) | {'from_bot': version['source'] == 'migration'}


def rounds_view(game, now, conn=None, user_id=None, rules_ok=True, root=None):
    out = []
    for rnd in game.rounds:
        items = game.assignments.get(rnd['id'], [])
        main = items[0] if items else None
        entry = {'id': str(rnd['id']), 'round_no': rnd['round_no'], 'title': rnd['title'],
                 'state': round_state(rnd, items, game, now), 'opens_at': iso(rnd['opens_at']),
                 'judging_deadline': iso(rnd['judging_deadline']), 'assignment_id': str(main['id']) if main else None,
                 'deadline': None, 'work': None, 'can_submit': False, 'closed_reason': None,
                 'result': result_view(game.results.get(rnd['id']), game.rating.get(rnd['id']))}
        if main is not None:
            deadline, _ = R.competition_deadline(rnd, main, game.pas.get(main['id']))
            entry['deadline'] = iso(deadline)
            if game.ep is not None:
                w = R.submission_window(game.event, rnd, main, game.pas.get(main['id']), game.mode, now, rules_ok)
                entry['work'] = my_work_state(game, rnd, main, now)
                entry['can_submit'] = w.open
                entry['closed_reason'] = w.reason
                entry['submit_deadline'] = iso(w.deadline)
                if root is not None:
                    entry['photo'] = work_photo(game, main, root)
        out.append(entry)
    return out


def version_view(game, version, root):
    if version is None:
        return None
    return {'id': str(version['id']), 'version_no': version['version_no'],
            'photos': [photo_view(m, root) for m in game.media.get(version['id'], [])],
            'link': (version['payload'] or {}).get('link'), 'source': version['source'],
            'submitted_at': iso(version['submitted_at']), 'saved_at': iso(version['created_at'])}


def localized(value, locale='ru'):
    if isinstance(value, dict):
        return value.get(locale) or next(iter(value.values()), None)
    return value


def task_view(game, assignment, now, rules_ok, root, variant):
    rnd = game.round_of(assignment)
    pa = game.pas.get(assignment['id'])
    w = R.submission_window(game.event, rnd, assignment, pa, game.mode, now, rules_ok)
    deadline, source = R.competition_deadline(rnd, assignment, pa)
    opened = R.round_opened(rnd, now)
    sub = game.subs.get(assignment['id'])
    versions = game.versions.get(sub['id'], {}) if sub else {}
    snapshot = (pa or {}).get('payload_snapshot') or {}
    title = localized(snapshot.get('title_i18n')) or (localized(variant['title_i18n']) if variant else None) or assignment['title']
    instructions = localized(snapshot.get('instructions_i18n')) if snapshot else None
    if instructions is None and variant is not None:
        instructions = localized(variant['instructions_i18n'])
    form = R.submission_form(variant) if variant is not None else None
    return {
        'event': event_brief(game.event), 'me': me_view(game), 'round': {
            'id': str(rnd['id']), 'round_no': rnd['round_no'], 'title': rnd['title'],
            'state': round_state(rnd, game.assignments.get(rnd['id'], []), game, now),
            'opens_at': iso(rnd['opens_at']), 'judging_deadline': iso(rnd['judging_deadline'])},
        'assignment': {'id': str(assignment['id']), 'code': assignment['code'], 'title': title,
                       'type': assignment['assignment_type']},
        'instructions': instructions if opened else None,
        'form': form if opened else None,
        'task_ready': variant is not None,
        'competition_deadline': iso(deadline), 'competition_deadline_source': source,
        'window': {'open': w.open, 'reason': w.reason, 'deadline': iso(w.deadline), 'source': w.deadline_source},
        'work': my_work_state(game, rnd, assignment, now) if game.ep else None,
        'draft': version_view(game, versions.get('draft'), root),
        'submitted': version_view(game, versions.get('latest'), root) | {
            'is_on_time': sub['is_on_time'], 'first_submitted_at': iso(sub['first_submitted_at']),
            'counts_for_competition': sub['counts_for_competition']} if sub and versions.get('latest') else None,
        'result': result_view(game.results.get(rnd['id']), game.rating.get(rnd['id'])),
    }
