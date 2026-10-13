#!/usr/bin/env python3
"""FPL: приёмник данных из бота.

POST /api/ingest?name=<набор>[&part=<i>&parts=<n>]
  Ключ: заголовок X-FPL-Key, или параметр key в адресе, или поле key в теле.
  Тело: JSON, или форма с полем data (строка JSON).
  Набор из нескольких частей: каждая часть — JSON-массив; когда пришли все n частей,
  они склеиваются в один массив.
  Результат: /var/lib/fpl/data/<набор>.json (атомарная замена), сайт отдаёт его как /data/<набор>.json.
  Наборы с именем private-… сохраняются в /var/lib/fpl/private/ — сайт их НЕ отдаёт
  (например, private-photos: список фото работ для архива, см. fpl-photo-archive.py).
GET /api/health -> {"ok": true}
POST /api/settings/backup  (заголовок X-FPL-Key) {"bucket","pool","access_key","secret_key"}
  Сохраняет доступ к закрытому бакету для копий (/var/lib/fpl/private/backup-s3.json, 0600)
  только после успешной пробной записи check/ping-….txt. Секрет в ответе не возвращается.
POST /api/settings/mail  (заголовок X-FPL-Key) {"host","port","username","password","from_name","test_to"}
  Почта кабинета (письма «новый пароль»): сохраняется (/var/lib/fpl/private/mail-smtp.json, 0600) только после того,
  как пробное письмо ушло на test_to. Дальше fpl-kabinet-mail (служба по изменению файла) включает почту в кабинете.
"""
import json, os, re, sys, time, tempfile, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import fpl_s3
except Exception:  # архив без модуля — настройка копий недоступна
    fpl_s3 = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.environ.get('FPL_DATA', '/var/lib/fpl/data')
PRIVATE = os.environ.get('FPL_PRIVATE', '/var/lib/fpl/private')
PARTS = os.environ.get('FPL_PARTS', '/var/lib/fpl/parts')
KEY = os.environ.get('FPL_INGEST_KEY', '')
MAX = 5 * 1024 * 1024
NAME = re.compile(r'^[a-z0-9_-]{1,40}$')


def target_dir(name):
    return PRIVATE if name.startswith('private-') else DATA


def write_atomic(path, obj, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.chmod(tmp, 0o600 if private or path.startswith(PRIVATE) else 0o644)
    os.replace(tmp, path)


class H(BaseHTTPRequestHandler):
    server_version = 'fpl'

    def reply(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *a):
        print('%s %s' % (self.address_string(), fmt % a), flush=True)

    def do_GET(self):
        if self.path.split('?')[0] == '/api/health':
            return self.reply(200, {'ok': True})
        self.reply(404, {'ok': False})

    def settings_backup(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 4096:
            return self.reply(413, {'ok': False, 'error': 'too_large'})
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return self.reply(400, {'ok': False, 'error': 'bad_json'})
        if not KEY or self.headers.get('X-FPL-Key') != KEY:
            time.sleep(1)
            return self.reply(403, {'ok': False, 'error': 'bad_key'})
        if fpl_s3 is None:
            return self.reply(500, {'ok': False, 'error': 'no_s3_module'})
        cfg = {k: str(body.get(k) or '').strip() for k in ('bucket', 'pool', 'access_key', 'secret_key')}
        checks = [('bucket', r'^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'), ('pool', r'^(ru-1|ru-3|ru-6|ru-7|gis-1)$'),
                  ('access_key', r'^[A-Za-z0-9]{8,128}$'), ('secret_key', r'^[A-Za-z0-9/+=_-]{16,256}$')]
        for k, rx in checks:
            if not re.match(rx, cfg[k]):
                return self.reply(400, {'ok': False, 'error': 'bad_' + k})
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        code, mode, msg = fpl_s3.put_bytes(cfg, 'check/ping-%s.txt' % stamp, ('fpl ok ' + stamp).encode(), 'text/plain', timeout=30)
        if not (200 <= code < 300):
            return self.reply(502, {'ok': False, 'error': 'upload_failed', 'http': code, 'detail': msg})
        cfg['addressing'] = mode
        cfg['saved_at'] = stamp
        path = os.path.join(PRIVATE, 'backup-s3.json')
        write_atomic(path, cfg)
        os.chmod(path, 0o600)
        return self.reply(200, {'ok': True, 'bucket': cfg['bucket'], 'pool': cfg['pool'], 'addressing': mode,
                                'warning': 'same_city' if cfg['pool'] in ('ru-1', 'ru-3') else None})

    def settings_mail(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > 4096:
            return self.reply(413, {'ok': False, 'error': 'too_large'})
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return self.reply(400, {'ok': False, 'error': 'bad_json'})
        if not KEY or self.headers.get('X-FPL-Key') != KEY:
            time.sleep(1)
            return self.reply(403, {'ok': False, 'error': 'bad_key'})
        cfg = {k: str(body.get(k) or '').strip() for k in ('host', 'port', 'username', 'password', 'from_name', 'test_to')}
        email = r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$'
        checks = [('host', r'^[a-z0-9][a-z0-9.-]{1,200}[a-z0-9]$'), ('port', r'^(465|587)$'), ('username', email),
                  ('password', r'^[^\s]{6,200}$'), ('from_name', r'^[^\r\n<>"]{0,80}$'), ('test_to', email)]
        for k, rx in checks:
            if not re.match(rx, cfg[k]):
                return self.reply(400, {'ok': False, 'error': 'bad_' + k})
        import smtplib, ssl
        from email.message import EmailMessage
        from email.utils import formataddr
        msg = EmailMessage()
        msg['From'] = formataddr((cfg['from_name'] or 'Face Painting League', cfg['username']))
        msg['To'] = cfg['test_to']
        msg['Subject'] = 'Face Painting League: проверка почты кабинета'
        msg.set_content('Это пробное письмо: почта кабинета Face Painting League настроена.\n'
                        'Теперь участницы смогут сами получать ссылку для нового пароля.')
        try:
            ctx = ssl.create_default_context()
            if cfg['port'] == '465':
                client = smtplib.SMTP_SSL(cfg['host'], 465, timeout=20, context=ctx)
            else:
                client = smtplib.SMTP(cfg['host'], 587, timeout=20)
                client.starttls(context=ctx)
            with client:
                client.login(cfg['username'], cfg['password'])
                client.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            return self.reply(502, {'ok': False, 'error': 'auth_failed'})
        except Exception as e:
            return self.reply(502, {'ok': False, 'error': 'send_failed', 'detail': type(e).__name__})
        cfg['saved_at'] = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        path = os.path.join(PRIVATE, 'mail-smtp.json')
        write_atomic(path, cfg)
        os.chmod(path, 0o600)
        return self.reply(200, {'ok': True, 'from': cfg['username'], 'test_to': cfg['test_to']})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/settings/mail':
            try:
                return self.settings_mail()
            except Exception as e:
                print('settings_mail error: %s' % type(e).__name__, flush=True)
                return self.reply(500, {'ok': False, 'error': 'server_error'})
        if u.path == '/api/settings/backup':
            try:
                return self.settings_backup()
            except Exception as e:
                print('settings_backup error: %s' % type(e).__name__, flush=True)
                return self.reply(500, {'ok': False, 'error': 'server_error'})
        if u.path != '/api/ingest':
            return self.reply(404, {'ok': False})
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX:
            return self.reply(413, {'ok': False, 'error': 'too_large'})
        raw = self.rfile.read(n).decode('utf-8', 'replace')
        ctype = (self.headers.get('Content-Type') or '').lower()
        body, form = None, {}
        try:
            if 'json' in ctype or raw.lstrip()[:1] in ('{', '['):
                body = json.loads(raw)
                if isinstance(body, dict) and 'data' in body and set(body) <= {'data', 'key', 'name', 'part', 'parts'}:
                    form = body
                    body = body['data']
                    if isinstance(body, str):
                        body = json.loads(body)
            else:
                form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
                body = json.loads(form.get('data', 'null'))
        except Exception:
            return self.reply(400, {'ok': False, 'error': 'bad_json'})
        key = self.headers.get('X-FPL-Key') or q.get('key') or form.get('key') or ''
        if not KEY or key != KEY:
            return self.reply(403, {'ok': False, 'error': 'bad_key'})
        name = q.get('name') or form.get('name') or ''
        if not NAME.match(name):
            return self.reply(400, {'ok': False, 'error': 'bad_name'})
        try:
            part = int(q.get('part') or form.get('part') or 1)
            parts = int(q.get('parts') or form.get('parts') or 1)
        except ValueError:
            return self.reply(400, {'ok': False, 'error': 'bad_part'})
        if not (1 <= part <= parts <= 200):
            return self.reply(400, {'ok': False, 'error': 'bad_part'})
        if parts == 1:
            write_atomic(os.path.join(target_dir(name), name + '.json'), body)
            return self.reply(200, {'ok': True, 'name': name, 'rows': len(body) if isinstance(body, list) else None})
        if not isinstance(body, list):
            return self.reply(400, {'ok': False, 'error': 'part_not_list'})
        d = os.path.join(PARTS, name)
        os.makedirs(d, exist_ok=True)
        # новая серия частей: части от прошлой загрузки (старше 1 часа или с другим числом частей) удаляются
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if not f.startswith('%d-' % parts) or time.time() - os.path.getmtime(p) > 3600:
                os.remove(p)
        os.chmod(d, 0o700)
        write_atomic(os.path.join(d, '%d-%03d.json' % (parts, part)), body, private=name.startswith('private-'))
        got = sorted(f for f in os.listdir(d) if f.startswith('%d-' % parts))
        if len(got) < parts:
            return self.reply(200, {'ok': True, 'name': name, 'part': part, 'received': len(got), 'parts': parts})
        rows = []
        for f in got:
            with open(os.path.join(d, f), encoding='utf-8') as fh:
                rows.extend(json.load(fh))
            os.remove(os.path.join(d, f))
        write_atomic(os.path.join(target_dir(name), name + '.json'), rows)
        self.reply(200, {'ok': True, 'name': name, 'rows': len(rows), 'complete': True})


if __name__ == '__main__':
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(PRIVATE, mode=0o700, exist_ok=True)
    ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('FPL_PORT', '8081'))), H).serve_forever()
