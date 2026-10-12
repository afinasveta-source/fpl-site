"""Игра участника в базе: загрузка, выдача задания, черновик, сдача и замена работы, переход вне конкурса.

Все изменения — внутри одной транзакции с блокировкой записи участника (event_participants FOR UPDATE),
поэтому сдача, смена состояния и переход вне конкурса не могут перемешаться.
"""
import re
from dataclasses import dataclass, field

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import rules as R

LINK_RE = re.compile(r'^https?://[^\s<>"\']{3,}$', re.I)


@dataclass
class Game:
    event: dict
    ep: dict | None
    rounds: list
    assignments: dict                 # round_id → [assignment]
    variants: dict                    # assignment_id → [variant]
    pas: dict = field(default_factory=dict)          # assignment_id → active participant_assignment
    subs: dict = field(default_factory=dict)         # assignment_id → submission
    versions: dict = field(default_factory=dict)     # submission_id → {'draft': v, 'latest': v}
    media: dict = field(default_factory=dict)        # version_id → [media rows]
    results: dict = field(default_factory=dict)      # round_id → published round_result

    @property
    def mode(self):
        return R.participation_mode(self.ep)

    def assignment(self, assignment_id):
        for items in self.assignments.values():
            for a in items:
                if str(a['id']) == str(assignment_id):
                    return a
        return None

    def round_of(self, assignment):
        return next(r for r in self.rounds if r['id'] == assignment['round_id'])

    def on_time_ids(self):
        return {aid for aid, s in self.subs.items() if s['first_submitted_at'] is not None and s['is_on_time']}

    def by_end_ids(self):
        return {aid for aid, s in self.subs.items() if s['latest_version_id'] is not None and s['counts_for_diploma']}


def load(conn, event_id, user_id, lock=False):
    event = conn.execute("SELECT * FROM events WHERE id=%s AND status<>'draft'", (event_id,)).fetchone()
    if not event:
        raise HTTPException(404, 'Game not found')
    ep = conn.execute('SELECT * FROM event_participants WHERE event_id=%s AND user_id=%s' + (' FOR UPDATE' if lock else ''),
                      (event_id, user_id)).fetchone()
    rounds = conn.execute("SELECT * FROM rounds WHERE event_id=%s AND status<>'draft' ORDER BY round_no", (event_id,)).fetchall()
    ids = [r['id'] for r in rounds]
    assignments = {r['id']: [] for r in rounds}
    for a in conn.execute('''SELECT * FROM assignments WHERE round_id = ANY(%s)
ORDER BY (assignment_type='competition_work') DESC, code''', (ids,)):
        assignments[a['round_id']].append(a)
    a_ids = [a['id'] for items in assignments.values() for a in items]
    variants = {aid: [] for aid in a_ids}
    for v in conn.execute('SELECT * FROM assignment_variants WHERE assignment_id = ANY(%s) ORDER BY code', (a_ids,)):
        variants[v['assignment_id']].append(v)
    game = Game(event, ep, rounds, assignments, variants)
    if ep:
        _load_participant(conn, game)
    return game


def _load_participant(conn, game):
    ep = game.ep
    game.pas = {p['assignment_id']: p for p in conn.execute(
        'SELECT * FROM participant_assignments WHERE event_participant_id=%s AND active', (ep['id'],))}
    pa_to_assignment = {p['id']: aid for aid, p in game.pas.items()}
    subs = conn.execute('SELECT * FROM submissions WHERE event_participant_id=%s AND deleted_at IS NULL', (ep['id'],)).fetchall()
    game.subs = {pa_to_assignment[s['participant_assignment_id']]: s for s in subs
                 if s['participant_assignment_id'] in pa_to_assignment}
    sub_ids = [s['id'] for s in game.subs.values()]
    game.versions = {sid: {'draft': None, 'latest': None} for sid in sub_ids}
    latest = {s['latest_version_id'] for s in game.subs.values()}
    rows = conn.execute('''SELECT * FROM submission_versions WHERE submission_id = ANY(%s)
AND (submitted_at IS NULL OR id = ANY(%s))''', (sub_ids, list(latest - {None}))).fetchall()
    for v in rows:
        game.versions[v['submission_id']]['draft' if v['submitted_at'] is None else 'latest'] = v
    v_ids = [v['id'] for v in rows]
    game.media = {vid: [] for vid in v_ids}
    for m in conn.execute('''SELECT svm.submission_version_id, svm.sort_order, m.id, m.metadata, m.created_at
FROM submission_version_media svm JOIN media_files m ON m.id = svm.media_file_id
WHERE svm.submission_version_id = ANY(%s) AND svm.field_key='photo' ORDER BY svm.sort_order''', (v_ids,)):
        game.media[m['submission_version_id']].append(m)
    game.results = {r['round_id']: r for r in conn.execute('''SELECT * FROM round_results
WHERE event_participant_id=%s AND is_current AND status='published' ''', (ep['id'],))}


def current_document(conn, kind, now):
    """Действующая редакция документа (последняя опубликованная к моменту now, не заменённая) или None."""
    return conn.execute('''SELECT * FROM legal_documents
WHERE doc_type=%s AND published_at <= %s AND (superseded_at IS NULL OR superseded_at > %s)
ORDER BY published_at DESC LIMIT 1''', (kind, now, now)).fetchone()


def rules_document(conn, now):
    return current_document(conn, 'rules', now)


def accepted(conn, user_id, document_id):
    row = conn.execute('''SELECT status FROM consents WHERE user_id=%s AND legal_document_id=%s
ORDER BY recorded_at DESC, id DESC LIMIT 1''', (user_id, document_id)).fetchone()
    return bool(row and row['status'] == 'accepted')


def rules_ok(conn, user_id, now):
    doc = rules_document(conn, now)
    return doc is None or accepted(conn, user_id, doc['id'])


def notify(conn, user_id, kind, key, payload, event_id=None, round_id=None):
    """Сообщение в кабинете (in_app). Повтор с тем же ключом ничего не создаёт."""
    conn.execute('''INSERT INTO notifications(user_id,event_id,round_id,notification_type,channel,payload,idempotency_key,status,sent_at)
VALUES (%s,%s,%s,%s,'in_app',%s,%s,'sent',now()) ON CONFLICT (idempotency_key) DO NOTHING''',
                 (user_id, event_id, round_id, kind, Jsonb(payload), key))


def audit(conn, actor, entity, entity_id, action, after=None):
    conn.execute('INSERT INTO audit_log(actor_user_id,entity_type,entity_id,action,after_data) VALUES (%s,%s,%s,%s,%s)',
                 (actor, entity, entity_id, action, Jsonb(after) if after is not None else None))


def sync_late(conn, game, now):
    """Опоздавший в конкурсе переходит вне конкурса (решение 12.10). Безопасно вызывать сколько угодно раз."""
    if game.mode != R.IN:
        return False
    missed = R.missed_round(game.event, game.rounds, game.assignments, game.on_time_ids(), game.pas, now)
    if not missed or not R.late_transfer_due(game.rounds, missed, now):
        return False
    row = conn.execute('''UPDATE event_participants SET competition_status='diploma_only', elimination_reason='late',
eliminated_round_id=%s, out_of_competition_at=%s, out_of_competition_source='auto'
WHERE id=%s AND registration_status='participating' AND (competition_status IS NULL OR competition_status='active')
RETURNING *''', (missed['id'], now, game.ep['id'])).fetchone()
    if not row:
        return False
    game.ep = row
    audit(conn, None, 'event_participant', row['id'], 'late_to_outside', {'round_no': missed['round_no']})
    notify(conn, row['user_id'], 'status', f"status:late:{row['id']}",
           {'title': f"Срок сдачи тура {missed['round_no']} прошёл",
            'text': 'Работа не сдана в срок. Игра продолжается вне конкурса: все работы — до конца Игры, тогда будет диплом.',
            'route': 'game', 'event_id': str(row['event_id'])}, row['event_id'], missed['id'])
    return True


def variant_for(game, assignment):
    pa = game.pas.get(assignment['id'])
    if pa:
        return next((v for v in game.variants[assignment['id']] if v['id'] == pa['assignment_variant_id']), None)
    return R.pick_variant(game.variants[assignment['id']], game.ep)


def materialize(conn, game, assignment):
    """Выдать участнику задание (вариант по лиге). Повторный вызов возвращает уже выданное."""
    if assignment['id'] in game.pas:
        return game.pas[assignment['id']]
    variant = R.pick_variant(game.variants[assignment['id']], game.ep)
    if variant is None:
        conn.execute('''INSERT INTO system_errors(severity,component,error_code,message,context)
VALUES ('warning','kabinet','TASK_VARIANT_AMBIGUOUS','No single task variant fits the participant',%s)''',
                     (Jsonb({'assignment_id': str(assignment['id']), 'event_participant_id': str(game.ep['id'])}),))
        raise HTTPException(409, 'task_not_ready')
    snapshot = {'variant_code': variant['code'], 'title_i18n': variant['title_i18n'],
                'instructions_i18n': variant['instructions_i18n'], 'submission_schema': variant['submission_schema']}
    conn.execute('''INSERT INTO participant_assignments(event_id,event_participant_id,assignment_id,assignment_variant_id,payload_snapshot)
VALUES (%s,%s,%s,%s,%s) ON CONFLICT (event_participant_id, assignment_id) WHERE active DO NOTHING''',
                 (game.event['id'], game.ep['id'], assignment['id'], variant['id'], Jsonb(snapshot)))
    pa = conn.execute('SELECT * FROM participant_assignments WHERE event_participant_id=%s AND assignment_id=%s AND active',
                      (game.ep['id'], assignment['id'])).fetchone()
    game.pas[assignment['id']] = pa
    return pa


def window(conn, game, assignment, now, user_id):
    rnd = game.round_of(assignment)
    return R.submission_window(game.event, rnd, assignment, game.pas.get(assignment['id']), game.mode, now,
                               rules_ok(conn, user_id, now))


def require_open(conn, game, assignment, now, user_id):
    w = window(conn, game, assignment, now, user_id)
    if not w.open:
        raise HTTPException(409, w.reason)
    return w


def clean_link(link):
    if link is None:
        return None
    link = link.strip()
    if not link:
        return None
    if len(link) > 500 or not LINK_RE.match(link):
        raise HTTPException(422, 'bad_link')
    return link


def form_of(game, assignment):
    variant = variant_for(game, assignment)
    if variant is None:
        return None
    return R.submission_form(variant)


def own_media(conn, user_id, media_ids):
    if not media_ids:
        return []
    if len(set(map(str, media_ids))) != len(media_ids):
        raise HTTPException(422, 'duplicate_photo')
    rows = conn.execute('''SELECT id FROM media_files WHERE id = ANY(%s) AND uploaded_by=%s AND deleted_at IS NULL
AND storage_key IS NOT NULL''', (list(media_ids), user_id)).fetchall()
    if len(rows) != len(media_ids):
        raise HTTPException(422, 'unknown_photo')
    return list(media_ids)


def ensure_submission(conn, game, assignment):
    pa = materialize(conn, game, assignment)
    conn.execute('''INSERT INTO submissions(event_participant_id,participant_assignment_id) VALUES (%s,%s)
ON CONFLICT (participant_assignment_id) DO NOTHING''', (game.ep['id'], pa['id']))
    sub = conn.execute('SELECT * FROM submissions WHERE participant_assignment_id=%s FOR UPDATE', (pa['id'],)).fetchone()
    game.subs[assignment['id']] = sub
    game.versions.setdefault(sub['id'], {'draft': None, 'latest': None})
    return sub


def save_draft(conn, game, assignment, photos, link, user_id, now):
    require_open(conn, game, assignment, now, user_id)
    form = form_of(game, assignment)
    if form is None:
        raise HTTPException(409, 'task_not_ready')
    link = clean_link(link)
    photos = own_media(conn, user_id, photos)
    problems = [p for p in R.payload_problems(form, photos, link) if p in ('too_many_photos', 'link_not_accepted')]
    if form['photo'] == 'none' and photos:
        problems.append('photo_not_accepted')
    if problems:
        raise HTTPException(422, problems[0])
    sub = ensure_submission(conn, game, assignment)
    draft = conn.execute('SELECT * FROM submission_versions WHERE submission_id=%s AND submitted_at IS NULL FOR UPDATE',
                         (sub['id'],)).fetchone()
    if draft:
        conn.execute('DELETE FROM submission_version_media WHERE submission_version_id=%s', (draft['id'],))
        draft = conn.execute('UPDATE submission_versions SET payload=%s, created_at=%s WHERE id=%s RETURNING *',
                             (Jsonb({'link': link}), now, draft['id'])).fetchone()
    else:
        no = conn.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM submission_versions WHERE submission_id=%s',
                          (sub['id'],)).fetchone()['n']
        draft = conn.execute('''INSERT INTO submission_versions(submission_id,version_no,payload,source,created_by,created_at)
VALUES (%s,%s,%s,'web',%s,%s) RETURNING *''', (sub['id'], no, Jsonb({'link': link}), user_id, now)).fetchone()
    for i, mid in enumerate(photos):
        conn.execute("INSERT INTO submission_version_media VALUES (%s,%s,'photo',%s)", (draft['id'], mid, i))
    return draft


def discard_draft(conn, game, assignment):
    sub = game.subs.get(assignment['id'])
    if not sub:
        return
    draft = conn.execute('SELECT id FROM submission_versions WHERE submission_id=%s AND submitted_at IS NULL FOR UPDATE',
                         (sub['id'],)).fetchone()
    if draft:
        conn.execute('DELETE FROM submission_version_media WHERE submission_version_id=%s', (draft['id'],))
        conn.execute('DELETE FROM submission_versions WHERE id=%s', (draft['id'],))


def submit(conn, game, assignment, draft_id, user_id, now):
    """Сдать черновик: он становится действующей сданной версией. Прежняя сданная остаётся в истории."""
    require_open(conn, game, assignment, now, user_id)
    form = form_of(game, assignment)
    sub = ensure_submission(conn, game, assignment)
    draft = conn.execute('SELECT * FROM submission_versions WHERE submission_id=%s AND submitted_at IS NULL FOR UPDATE',
                         (sub['id'],)).fetchone()
    if not draft or str(draft['id']) != str(draft_id):
        raise HTTPException(409, 'draft_changed')
    photos = [r['media_file_id'] for r in conn.execute(
        "SELECT media_file_id FROM submission_version_media WHERE submission_version_id=%s AND field_key='photo' ORDER BY sort_order",
        (draft['id'],))]
    problems = R.payload_problems(form, photos, (draft['payload'] or {}).get('link'))
    if problems:
        raise HTTPException(422, problems[0])
    version = conn.execute('''UPDATE submission_versions SET submitted_at=%s, is_final_submit=true
WHERE id=%s RETURNING *''', (now, draft['id'])).fetchone()
    rnd = game.round_of(assignment)
    marks = R.submission_marks(game.event, rnd, assignment, game.pas.get(assignment['id']), game.mode, now,
                               sub['first_submitted_at'])
    in_competition = marks['counts_for_competition']
    sub = conn.execute('''UPDATE submissions SET latest_version_id=%(v)s,
  competition_version_id = CASE WHEN %(comp)s THEN %(v)s ELSE competition_version_id END,
  diploma_version_id = CASE WHEN %(dip)s THEN %(v)s ELSE diploma_version_id END,
  status = CASE WHEN %(on_time)s THEN 'submitted' ELSE 'late' END,
  first_submitted_at = coalesce(first_submitted_at, %(now)s), last_submitted_at=%(now)s,
  is_on_time=%(on_time)s, deadline_applied_at=%(dl)s, deadline_source=%(src)s,
  counts_for_competition = CASE WHEN %(comp)s THEN true ELSE coalesce(counts_for_competition, false) END,
  counts_for_diploma=%(dip)s
WHERE id=%(id)s RETURNING *''', {'v': version['id'], 'comp': in_competition, 'dip': marks['counts_for_diploma'],
                                   'on_time': marks['is_on_time'], 'now': now, 'dl': marks['deadline_applied_at'],
                                   'src': marks['deadline_source'], 'id': sub['id']}).fetchone()
    game.subs[assignment['id']] = sub
    audit(conn, user_id, 'submission', sub['id'], 'submission_submitted',
          {'version_no': version['version_no'], 'photos': len(photos), 'on_time': marks['is_on_time'],
           'mode': game.mode})
    replaced = version['version_no'] > 1 and conn.execute(
        'SELECT 1 FROM submission_versions WHERE submission_id=%s AND submitted_at IS NOT NULL AND id<>%s LIMIT 1',
        (sub['id'], version['id'])).fetchone() is not None
    notify(conn, user_id, 'sent', f"sent:{version['id']}",
           {'title': (f"Работа к туру {rnd['round_no']} заменена" if replaced else f"Работа к туру {rnd['round_no']} принята"),
            'text': 'Действует версия от последней сдачи.', 'route': 'task', 'event_id': str(game.event['id']),
            'assignment_id': str(assignment['id'])}, game.event['id'], rnd['id'])
    return version


def choose_outside(conn, game, user_id, now):
    """«Участвовать вне конкурса» после отбора жюри. Вернуться в конкурс нельзя."""
    if game.event['status'] in R.GAME_OVER:
        raise HTTPException(409, 'game_over')
    if game.mode != R.OUT_PENDING:
        raise HTTPException(409, 'not_allowed')
    row = conn.execute('''UPDATE event_participants SET competition_status='diploma_only', out_of_competition_at=%s,
out_of_competition_source='participant' WHERE id=%s AND competition_status='eliminated' RETURNING *''',
                       (now, game.ep['id'])).fetchone()
    game.ep = row
    audit(conn, user_id, 'event_participant', row['id'], 'chose_outside')
    return row
