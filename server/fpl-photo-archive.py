#!/usr/bin/env python3
"""FPL: архив фото работ (cron, каждые 10 минут).

Бот присылает список фото в закрытый набор: POST /api/ingest?name=private-photos[...]
  [{"key": "fpl_game1_2026/r2/work/123", "url": "https://sun9-…userapi.com/…jpg"}, …]
  key — постоянный идентификатор работы (марафон / тур / трек / номер), url — где фото сейчас.
Наборов может быть несколько: private-photos, private-photos-free, private-photos-cards …
(все файлы /var/lib/fpl/private/private-photos*.json).

Архиватор скачивает каждое ещё не сохранённое фото в /var/lib/fpl/archive/files/<sha256>.<ext>
(папка не отдаётся сайтом), записывает журнал /var/lib/fpl/archive/index.json
и повторяет неудачные попытки (до MAX_ATTEMPTS). Если по тому же key пришла новая ссылка
(работу заменили), сохраняется и новая версия.
Наружу публикуется только сводка без ссылок и имён: /var/lib/fpl/data/photo-archive-status.json.
"""
import glob, hashlib, json, os, shutil, sys, tempfile, time, urllib.request

PRIVATE = os.environ.get('FPL_PRIVATE', '/var/lib/fpl/private')
ARCHIVE = os.environ.get('FPL_ARCHIVE', '/var/lib/fpl/archive')
DATA = os.environ.get('FPL_DATA', '/var/lib/fpl/data')
MAX_BYTES = 25 * 1024 * 1024
MAX_ATTEMPTS = 6
MIN_FREE = int(os.environ.get('FPL_ARCHIVE_MIN_FREE', str(800 * 1024 * 1024)))
PER_RUN = int(os.environ.get('FPL_ARCHIVE_PER_RUN', '300'))
TIMEOUT = 30
MAGIC = [(b'\xff\xd8\xff', 'jpg'), (b'\x89PNG\r\n\x1a\n', 'png'), (b'RIFF', 'webp'), (b'GIF8', 'gif')]


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def write_json(path, obj, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=0)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def kind(data):
    for sig, ext in MAGIC:
        if data.startswith(sig) and (ext != 'webp' or data[8:12] == b'WEBP'):
            return ext
    if data[4:12] in (b'ftypheic', b'ftypheix', b'ftypmif1'):
        return 'heic'
    return None


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (FPL photo archive)'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if r.status != 200:
            raise ValueError('http %s' % r.status)
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('too large')
    ext = kind(data)
    if not ext:
        raise ValueError('not an image')
    return data, ext


def load_queue():
    items = {}
    for path in sorted(glob.glob(os.path.join(PRIVATE, 'private-photos*.json'))):
        try:
            rows = json.load(open(path, encoding='utf-8'))
        except Exception as e:
            print('skip %s: %s' % (os.path.basename(path), e), file=sys.stderr)
            continue
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            key, url = str(row.get('key') or '').strip(), str(row.get('url') or '').strip()
            if key and url.startswith(('http://', 'https://')):
                items[(key, url)] = row
    return items


def main():
    os.makedirs(os.path.join(ARCHIVE, 'files'), mode=0o700, exist_ok=True)
    idx_path = os.path.join(ARCHIVE, 'index.json')
    try:
        index = json.load(open(idx_path, encoding='utf-8'))
    except FileNotFoundError:
        index = {}
    # index: "<key>\n<url>" -> {key,url,status,sha256,file,bytes,attempts,first_seen,last_try,error}
    queue = load_queue()
    for (key, url) in queue:
        index.setdefault(key + '\n' + url, {'key': key, 'url': url, 'status': 'pending', 'attempts': 0, 'first_seen': now()})

    done = 0
    for rec in sorted(index.values(), key=lambda r: r['first_seen']):
        if rec['status'] == 'archived' or rec['attempts'] >= MAX_ATTEMPTS or done >= PER_RUN:
            continue
        if shutil.disk_usage(ARCHIVE).free < MIN_FREE:
            print('low disk space, stopping', file=sys.stderr)
            break
        rec['attempts'] += 1
        rec['last_try'] = now()
        done += 1
        try:
            data, ext = fetch(rec['url'])
        except Exception as e:
            rec['error'] = str(e)[:200]
            rec['status'] = 'lost' if rec['attempts'] >= MAX_ATTEMPTS else 'retry'
            continue
        sha = hashlib.sha256(data).hexdigest()
        name = sha + '.' + ext
        path = os.path.join(ARCHIVE, 'files', name)
        if not os.path.exists(path):
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        rec.update(status='archived', sha256=sha, file=name, bytes=len(data), archived_at=now())
        rec.pop('error', None)
        if done % 25 == 0:
            write_json(idx_path, index)
    write_json(idx_path, index)

    st = {'updated_at': now(), 'items': len(index),
          'archived': sum(r['status'] == 'archived' for r in index.values()),
          'pending': sum(r['status'] in ('pending', 'retry') for r in index.values()),
          'lost': sum(r['status'] == 'lost' for r in index.values()),
          'works': len({r['key'] for r in index.values()}),
          'works_without_copy': len({r['key'] for r in index.values()} - {r['key'] for r in index.values() if r['status'] == 'archived'}),
          'disk_free_mb': shutil.disk_usage(ARCHIVE).free // (1024 * 1024)}
    write_json(os.path.join(DATA, 'photo-archive-status.json'), st, mode=0o644)
    print(json.dumps(st, ensure_ascii=False))


if __name__ == '__main__':
    main()
