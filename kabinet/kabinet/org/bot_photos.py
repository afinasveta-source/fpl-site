"""Фото работ туров 1–2 Игры 01 из бота (14.10).

База бота потеряла фото работ. Адреса фото восстановлены по ID участника SaleBot (тот же «ID участника», что в таблице
переноса): тур 1 — точно, тур 2 — частично догадки. Поэтому организатор сначала смотрит список (предпросмотр показывает
сами фото прямо с источника — сервер ничего не скачивает), снимает отметки с сомнительных и только потом переносит.

Перенос — маленькими пачками (страница шлёт по 5): сервер скачивает фото сам (только https и только с известных хостов
бота и ВК, без перехода на чужие адреса), сохраняет как обычное фото участницы (оригинал, копия для показа, миниатюра)
и оформляет работу тура: выданное задание (если переноса задания не было), работа, сданная версия «migration».
- Зачтена в конкурс (counts_for_competition) и «в срок» — только если у неё есть итог тура из бота; для диплома — всегда.
- Повтор с тем же адресом ничего не делает; новый адрес (исправление организатора) — новая версия работы.
- Работу, которую участница сдала (или начала) в кабинете сама, перенос не трогает.
Соответствие «фото из бота → работа» — в import_row_map (salebot_photo, «cid/rN»), в row_sha256 — отпечаток адреса.
"""
import hashlib
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from kabinet.participation import rules as R
from kabinet.participation import views as V
from kabinet.participation.media import MediaError
from kabinet.participation.routes import PHOTO_LOCK
from .bot_import import BOT_ROUNDS, PROJECT, existing_event
from .common import WRITE, Jsonb, audit, db, locked_admin, now_of, org_user, problem

router = APIRouter(prefix='/api/org/import/game01/photos', tags=['organizer'])

SOURCE_TABLE = 'salebot_photo'
# Откуда фото бота: файлы SaleBot и CDN ВКонтакте. Другие адреса не скачиваются (и не показываются в предпросмотре).
HOSTS_EXACT = ('files.salebot.pro',)
HOSTS_SUFFIX = ('userapi.com', 'vkuserphoto.ru')
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 30             # на одно фото целиком
SOCKET_TIMEOUT = 10      # на каждое ожидание сети
BUDGET = 12              # новое фото пачки начинается, только если с начала запроса прошло меньше (nginx ждёт ответ 60 с)
MAX_REDIRECTS = 5


# ---------- адреса и скачивание ----------

def url_host(url):
    try:
        p = urllib.parse.urlsplit(url)
        return (p.hostname or '').rstrip('.').lower()
    except ValueError:
        return ''


def allowed_url(url):
    """https, хост бота или ВК, без логина в адресе и без нестандартного порта."""
    if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() for c in url):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        port = p.port
    except ValueError:
        return False
    if p.scheme != 'https' or p.username or p.password or port not in (None, 443):
        return False
    host = url_host(url)
    return host in HOSTS_EXACT or any(host == s or host.endswith('.' + s) for s in HOSTS_SUFFIX)


class FetchError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise FetchError('bad_redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_photo(url):
    """Скачать фото (байты). Ошибка — FetchError с кодом: http_404, timeout, too_large, bad_redirect, network, tls…
    Подменяется в проверках через app.state.fetch_photo."""
    if not allowed_url(url):
        raise FetchError('bad_url')
    opener = urllib.request.build_opener(_Redirects())
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (FPL kabinet: bot photos)', 'Accept': 'image/*'})
    started = time.monotonic()
    try:
        with opener.open(req, timeout=SOCKET_TIMEOUT) as r:
            if not allowed_url(r.geturl()):
                raise FetchError('bad_redirect')
            size = r.headers.get('Content-Length')
            if size and size.isdigit() and int(size) > MAX_BYTES:
                raise FetchError('too_large')
            chunks, total = [], 0
            while True:
                if time.monotonic() - started > TIMEOUT:
                    raise FetchError('timeout')
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise FetchError('too_large')
                chunks.append(chunk)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError(f'http_{exc.code}') from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, FetchError):
            raise reason from None
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise FetchError('timeout') from None
        if isinstance(reason, ssl.SSLError):
            raise FetchError('tls') from None
        raise FetchError('network') from None
    except (socket.timeout, TimeoutError):
        raise FetchError('timeout') from None
    except ssl.SSLError:
        raise FetchError('tls') from None
    except OSError:
        raise FetchError('network') from None
    data = b''.join(chunks)
    if not data:
        raise FetchError('empty')
    return data


def url_sha(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


# ---------- что уже есть в кабинете ----------

class PhotoItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cid: str = Field(min_length=1, max_length=40)
    round: int
    url: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=300)


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[PhotoItem] = Field(min_length=1, max_length=500)


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[PhotoItem] = Field(min_length=1, max_length=10)


def game_of(conn):
    ev = existing_event(conn)
    if not ev or not (ev['settings'] or {}).get('moved_to_kabinet'):
        raise problem('not_moved', 409)
    rounds = {r['round_no']: r for r in conn.execute(
        'SELECT * FROM rounds WHERE event_id=%s AND round_no = ANY(%s)', (ev['id'], list(BOT_ROUNDS)))}
    tasks = {}
    for no, r in rounds.items():
        a = conn.execute('''SELECT * FROM assignments WHERE round_id=%s
ORDER BY (assignment_type='competition_work') DESC, code LIMIT 1''', (r['id'],)).fetchone()
        if a:
            tasks[no] = a
    return ev, rounds, tasks


def classify(conn, ev, rounds, tasks, items, root, lock_ep=False):
    """Состояние каждой строки списка (без скачивания). Возвращает список словарей в порядке строк."""
    cids = sorted({(it.cid or '').strip() for it in items})
    who = {r['external_id']: r['user_id'] for r in conn.execute('''SELECT external_id, user_id FROM external_identities
WHERE provider='salebot_client' AND project_ref=%s AND external_id = ANY(%s)''', (PROJECT, cids))}
    eps = {r['user_id']: r for r in conn.execute('''SELECT p.*, u.full_name FROM event_participants p JOIN users u ON u.id=p.user_id
WHERE p.event_id=%s AND p.user_id = ANY(%s) ORDER BY p.id''' + (' FOR UPDATE OF p' if lock_ep else ''), (ev['id'], list(set(who.values()))))}
    ep_ids = [p['id'] for p in eps.values()]
    task_ids = [a['id'] for a in tasks.values()]
    pas = {(p['event_participant_id'], p['assignment_id']): p for p in conn.execute(
        'SELECT * FROM participant_assignments WHERE event_participant_id = ANY(%s) AND assignment_id = ANY(%s) AND active', (ep_ids, task_ids))}
    subs = {s['participant_assignment_id']: s for s in conn.execute(
        'SELECT * FROM submissions WHERE participant_assignment_id = ANY(%s) AND deleted_at IS NULL', ([p['id'] for p in pas.values()],))}
    sub_ids = [s['id'] for s in subs.values()]
    own = {r['submission_id'] for r in conn.execute(
        "SELECT DISTINCT submission_id FROM submission_versions WHERE submission_id = ANY(%s) AND source <> 'migration'", (sub_ids,))}
    latest = [s['latest_version_id'] for s in subs.values() if s['latest_version_id']]
    photos = {}
    for m in conn.execute('''SELECT svm.submission_version_id, m.id, m.metadata, m.source_url FROM submission_version_media svm
JOIN media_files m ON m.id=svm.media_file_id WHERE svm.submission_version_id = ANY(%s) AND svm.field_key='photo'
ORDER BY svm.sort_order''', (latest,)):
        photos.setdefault(m['submission_version_id'], m)
    results = {(r['event_participant_id'], r['round_id']): r for r in conn.execute('''SELECT event_participant_id, round_id, display_score
FROM round_results WHERE event_participant_id = ANY(%s) AND is_current AND status='published' ''', (ep_ids,))}
    keys = [f'{(it.cid or "").strip()}/r{it.round}' for it in items]
    maps = {r['source_key']: r for r in conn.execute('''SELECT source_key, target_id, row_sha256 FROM import_row_map
WHERE source_table=%s AND target_table='submissions' AND source_key = ANY(%s)''', (SOURCE_TABLE, keys))}
    seen, out = set(), []
    for i, it in enumerate(items):
        cid, url, no = (it.cid or '').strip(), (it.url or '').strip(), it.round
        row = {'index': i, 'cid': cid, 'round': no, 'url': url, 'note': (it.note or '').strip() or None, 'name': None,
               'league': None, 'mode': None, 'has_result': False, 'score': None, 'current': None, 'status': 'ok'}
        out.append(row)
        uid = who.get(cid)
        ep = eps.get(uid) if uid else None
        if ep is not None:
            row.update(name=ep['full_name'], league=ep['entry_league'], mode=R.participation_mode(ep),
                       competition_status=ep['competition_status'])
            rnd = rounds.get(no)
            res = results.get((ep['id'], rnd['id'])) if rnd else None
            if res:
                row.update(has_result=True, score=float(res['display_score']) if res['display_score'] is not None else None)
        key = (cid, no)
        if key in seen:
            row['status'] = 'duplicate'
            continue
        seen.add(key)
        if no not in BOT_ROUNDS:
            row['status'] = 'bad_round'
        elif not allowed_url(url):
            row['status'] = 'bad_url'
        elif uid is None:
            row['status'] = 'unknown_cid'
        elif ep is None:
            row['status'] = 'not_in_game'
        elif no not in tasks:
            row['status'] = 'no_task'
        if row['status'] != 'ok':
            continue
        pa = pas.get((ep['id'], tasks[no]['id']))
        sub = subs.get(pa['id']) if pa else None
        row['_ep'], row['_uid'], row['_pa'], row['_sub'] = ep, uid, pa, sub
        if sub and sub['id'] in own:
            row['status'] = 'has_own'      # сдала (или начала) работу в кабинете сама — не трогаем
        mapped = maps.get(f'{cid}/r{no}')
        if sub and sub['latest_version_id'] in photos:
            m = photos[sub['latest_version_id']]
            row['current'] = V.photo_view(m, root) | {'source_url': m['source_url']}
        if row['status'] == 'ok' and mapped:
            row['status'] = 'same' if mapped['row_sha256'] == url_sha(url) else 'replace'
        elif row['status'] == 'ok' and sub and sub['latest_version_id']:
            row['status'] = 'replace'      # работа из переноса без записи соответствия (не должно быть) — новая версия
    return out


def public(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def summary(rows):
    out = {}
    for r in rows:
        out[r['status']] = out.get(r['status'], 0) + 1
    return out


@router.post('/preview', dependencies=WRITE)
def preview(body: PreviewIn, request: Request, user=Depends(org_user)):
    root = request.app.state.settings.root_path
    with db(request).transaction() as conn:
        ev, rounds, tasks = game_of(conn)
        rows = classify(conn, ev, rounds, tasks, body.items, root)
    rows = [public(r) for r in rows]
    return {'event_id': str(ev['id']), 'items': rows, 'counts': summary(rows), 'total': len(rows)}


# ---------- перенос ----------

class Photos:
    def __init__(self, request, user):
        self.request, self.user = request, user
        self.root = request.app.state.settings.root_path
        self.fetch = getattr(request.app.state, 'fetch_photo', None) or fetch_photo
        self.batch = None

    def ensure_batch(self, now):
        if self.batch is None:
            with db(self.request).transaction() as conn:
                self.batch = conn.execute('''INSERT INTO import_batches(source,source_project,status,started_by,started_at,notes)
VALUES ('salebot',%s,'started',%s,%s,'bot_photos game01') RETURNING id''', (PROJECT, self.user['id'], now)).fetchone()['id']
        return self.batch

    def store(self, data):
        with PHOTO_LOCK:
            return self.request.app.state.media.save_image(data)

    def media_row(self, conn, uid, info, it, batch):
        """Запись фото участницы (как при загрузке ею самой: тот же файл тем же человеком — та же запись)."""
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"media:{uid}:{info['sha256']}",))
        row = conn.execute('''SELECT * FROM media_files WHERE uploaded_by=%s AND sha256=%s AND deleted_at IS NULL
AND storage_key IS NOT NULL ORDER BY created_at LIMIT 1''', (uid, info['sha256'])).fetchone()
        if row is not None:
            return row
        media_id = uuid4()
        meta = {'width': info['width'], 'height': info['height'], 'source': 'salebot', 'bot_cid': it['cid'],
                'round': it['round'], 'url_host': url_host(it['url'])}
        return conn.execute('''INSERT INTO media_files(id,uploaded_by,storage_key,mime_type,size_bytes,optimized_storage_key,
thumbnail_storage_key,sha256,metadata,source_url,import_batch_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                            (media_id, uid, f"{info['storage_key']}#{media_id}", info['mime_type'], info['size_bytes'],
                             info['optimized_storage_key'], info['thumbnail_storage_key'], info['sha256'], Jsonb(meta),
                             it['url'], batch)).fetchone()

    def write(self, conn, ev, rounds, tasks, it, info, now):
        """Работа тура с фото из бота. it — строка classify (под блокировкой участницы)."""
        no, ep, uid = it['round'], it['_ep'], it['_uid']
        batch = self.batch
        task = tasks[no]
        pa = it['_pa']
        if pa is None:
            variants = conn.execute('SELECT * FROM assignment_variants WHERE assignment_id=%s ORDER BY code', (task['id'],)).fetchall()
            variant = R.pick_variant(variants, ep) or (variants[0] if variants else None)
            if variant is None:
                return 'failed', 'no_task'
            snapshot = {'variant_code': variant['code'], 'title_i18n': variant['title_i18n'],
                        'instructions_i18n': variant['instructions_i18n'], 'submission_schema': variant['submission_schema']}
            conn.execute('''INSERT INTO participant_assignments(event_id,event_participant_id,assignment_id,assignment_variant_id,source,
payload_snapshot,assigned_at) VALUES (%s,%s,%s,%s,'migration',%s,%s) ON CONFLICT (event_participant_id, assignment_id) WHERE active DO NOTHING''',
                         (ev['id'], ep['id'], task['id'], variant['id'], Jsonb(snapshot), rounds[no]['opens_at'] or now))
            pa = conn.execute('SELECT * FROM participant_assignments WHERE event_participant_id=%s AND assignment_id=%s AND active',
                              (ep['id'], task['id'])).fetchone()
        conn.execute('''INSERT INTO submissions(event_participant_id,participant_assignment_id) VALUES (%s,%s)
ON CONFLICT (participant_assignment_id) DO NOTHING''', (ep['id'], pa['id']))
        sub = conn.execute('SELECT * FROM submissions WHERE participant_assignment_id=%s FOR UPDATE', (pa['id'],)).fetchone()
        media = self.media_row(conn, uid, info, it, batch)
        key = f"{it['cid']}/r{no}"
        if sub['latest_version_id'] and conn.execute('''SELECT 1 FROM submission_version_media WHERE submission_version_id=%s
AND media_file_id=%s''', (sub['latest_version_id'], media['id'])).fetchone():
            # тот же файл по новому адресу — работа уже такая, запоминаем адрес
            self.remember(conn, batch, key, sub['id'], it['url'])
            return 'skipped', 'same_file'
        deadline = BOT_ROUNDS[no]['deadline']
        has_result = it['has_result']
        vno = conn.execute('SELECT coalesce(max(version_no),0)+1 AS n FROM submission_versions WHERE submission_id=%s', (sub['id'],)).fetchone()['n']
        # сначала черновик с фото (фото сданной версии менять нельзя), потом — сдана к сроку тура в боте
        v = conn.execute('''INSERT INTO submission_versions(submission_id,version_no,payload,source,created_by,created_at)
VALUES (%s,%s,%s,'migration',%s,%s) RETURNING *''', (sub['id'], vno, Jsonb({'source': 'salebot', 'bot_cid': it['cid'],
                                                                          'url_host': url_host(it['url'])}), self.user['id'], now)).fetchone()
        conn.execute("INSERT INTO submission_version_media VALUES (%s,%s,'photo',0)", (v['id'], media['id']))
        conn.execute('UPDATE submission_versions SET submitted_at=%s, is_final_submit=true WHERE id=%s', (deadline, v['id']))
        conn.execute('''UPDATE submissions SET status='locked', latest_version_id=%(v)s, diploma_version_id=%(v)s,
competition_version_id = CASE WHEN %(res)s THEN %(v)s ELSE competition_version_id END,
first_submitted_at=coalesce(first_submitted_at, %(dl)s), last_submitted_at=%(dl)s, locked_at=coalesce(locked_at, %(now)s),
is_on_time=%(res)s, deadline_applied_at=%(dl)s, deadline_source='import', counts_for_competition=%(res)s, counts_for_diploma=true
WHERE id=%(id)s''', {'v': v['id'], 'res': has_result, 'dl': deadline, 'now': now, 'id': sub['id']})
        self.remember(conn, batch, key, sub['id'], it['url'])
        it['_media'] = media
        it['_version'] = vno
        return 'done', None

    def remember(self, conn, batch, key, sub_id, url):
        conn.execute('''INSERT INTO import_row_map(first_batch_id,last_batch_id,source_table,source_key,target_table,target_id,row_sha256)
VALUES (%s,%s,%s,%s,'submissions',%s,%s) ON CONFLICT (source_table, source_key, target_table) DO UPDATE
SET last_batch_id=EXCLUDED.last_batch_id, target_id=EXCLUDED.target_id, row_sha256=EXCLUDED.row_sha256, updated_at=now()''',
                     (batch, batch, SOURCE_TABLE, key, sub_id, url_sha(url)))

    def one(self, item, now):
        """Одна строка: проверка → скачивание → запись. Исход: (result, reason, extra)."""
        with db(self.request).transaction() as conn:
            ev, rounds, tasks = game_of(conn)
            it = classify(conn, ev, rounds, tasks, [item], self.root)[0]
        if it['status'] == 'same':
            return it, 'skipped', 'same'
        if it['status'] not in ('ok', 'replace'):
            return it, 'skipped', it['status']
        try:
            data = self.fetch(it['url'])
        except FetchError as exc:
            return it, 'failed', exc.code
        try:
            info = self.store(data)
        except MediaError as exc:
            return it, 'failed', {'not_an_image': 'not_image'}.get(exc.code, exc.code)
        finally:
            del data
        self.ensure_batch(now)
        with db(self.request).transaction() as conn:
            locked_admin(conn, self.user)
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"bot-photo:{it['cid']}:{it['round']}",))
            ev, rounds, tasks = game_of(conn)
            # заново и под блокировкой участницы: пока качалось фото, она могла сдать работу сама, а другая вкладка — перенести
            fresh = classify(conn, ev, rounds, tasks, [item], self.root, lock_ep=True)[0]
            if fresh['status'] == 'same':
                return fresh, 'skipped', 'same'
            if fresh['status'] not in ('ok', 'replace'):
                return fresh, 'skipped', fresh['status']
            result, reason = self.write(conn, ev, rounds, tasks, fresh, info, now)
            return fresh, result, reason

    def run(self, items, now):
        started = time.monotonic()
        out, counts = [], {}
        for i, item in enumerate(items):
            if i and time.monotonic() - started > BUDGET:
                row = {'index': i, 'cid': item.cid.strip(), 'round': item.round, 'result': 'pending', 'reason': 'later'}
            else:
                try:
                    it, result, reason = self.one(item, now)
                except Exception as exc:      # одна строка не роняет пачку
                    if getattr(exc, 'status_code', None) in (401, 403):
                        raise
                    it, result, reason = {'cid': item.cid.strip(), 'round': item.round, 'status': None}, 'failed', 'error'
                row = {'index': i, 'cid': it['cid'], 'round': it['round'], 'status': it.get('status'), 'result': result, 'reason': reason,
                       'name': it.get('name')}
                if result == 'done':
                    row['photo'] = V.photo_view(it['_media'], self.root)
                    row['version_no'] = it['_version']
            counts[row['result']] = counts.get(row['result'], 0) + 1
            out.append(row)
        with db(self.request).transaction() as conn:
            ev = existing_event(conn)
            if self.batch is not None:
                conn.execute("UPDATE import_batches SET status='completed', finished_at=%s, notes=%s WHERE id=%s",
                             (now_of(self.request), 'bot_photos game01: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())), self.batch))
            audit(conn, self.user['id'], 'event', ev['id'], 'bot_photos_game01',
                  {'counts': counts, 'items': [{'cid': r['cid'], 'round': r['round'], 'result': r['result'], 'reason': r.get('reason')}
                                               for r in out]})
        return {'items': out, 'counts': counts}


@router.post('/apply', dependencies=WRITE)
def apply(body: ApplyIn, request: Request, user=Depends(org_user)):
    now = now_of(request)
    with db(request).transaction() as conn:
        locked_admin(conn, user)
        game_of(conn)
    return Photos(request, user).run(body.items, now)
