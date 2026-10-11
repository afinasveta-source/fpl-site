#!/usr/bin/env python3
"""FPL: запись файлов в закрытый бакет S3 (Selectel), только стандартная библиотека.

Настройки: /var/lib/fpl/private/backup-s3.json
  {"bucket": "...", "pool": "ru-7", "access_key": "...", "secret_key": "...", "addressing": "vhost"|"path"}
Запуск:  fpl_s3.py put <локальный файл> <ключ в бакете>   (код выхода 0 — записано)
         fpl_s3.py ping                                   (пробная запись check/ping-<время>.txt)
"""
import datetime, hashlib, hmac, json, os, sys, urllib.error, urllib.parse, urllib.request

CONFIG = os.environ.get('FPL_S3_CONFIG', '/var/lib/fpl/private/backup-s3.json')


SCHEME = os.environ.get('FPL_S3_SCHEME', 'https')            # для проверок: http
ENDPOINT_FMT = os.environ.get('FPL_S3_ENDPOINT', 's3.%s.storage.selcloud.ru')


def endpoint(pool):
    return ENDPOINT_FMT % pool if '%s' in ENDPOINT_FMT else ENDPOINT_FMT


def _sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def sign_put(host, path, payload_hash, access_key, secret_key, region, now=None, content_type=None):
    """Заголовки SigV4 для PUT (сервис s3). path — уже закодированный путь, начинается с '/'."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    day = now.strftime('%Y%m%d')
    headers = {'host': host, 'x-amz-content-sha256': payload_hash, 'x-amz-date': amz_date}
    if content_type:
        headers['content-type'] = content_type
    names = sorted(headers)
    canonical = '\n'.join(['PUT', path, '', ''.join('%s:%s\n' % (n, headers[n].strip()) for n in names),
                           ';'.join(names), payload_hash])
    scope = '%s/%s/s3/aws4_request' % (day, region)
    to_sign = '\n'.join(['AWS4-HMAC-SHA256', amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(('AWS4' + secret_key).encode(), day)
    k = _sign(k, region)
    k = _sign(k, 's3')
    k = _sign(k, 'aws4_request')
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    headers['authorization'] = 'AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s' % (
        access_key, scope, ';'.join(names), signature)
    return headers


def quote_key(key):
    return '/'.join(urllib.parse.quote(part, safe='-_.~') for part in key.split('/'))


def put_bytes(cfg, key, data, content_type='application/octet-stream', timeout=120):
    """Возвращает (http_code, addressing, сообщение). Пробует vhost, затем path-style."""
    pool = cfg['pool']
    order = [cfg['addressing']] if cfg.get('addressing') in ('vhost', 'path') else ['vhost', 'path']
    payload_hash = hashlib.sha256(data).hexdigest()
    last = (0, None, 'not tried')
    for mode in order:
        if mode == 'vhost':
            host, path = '%s.%s' % (cfg['bucket'], endpoint(pool)), '/' + quote_key(key)
        else:
            host, path = endpoint(pool), '/%s/%s' % (urllib.parse.quote(cfg['bucket'], safe='-_.~'), quote_key(key))
        headers = sign_put(host, path, payload_hash, cfg['access_key'], cfg['secret_key'], pool, content_type=content_type)
        req = urllib.request.Request('%s://%s%s' % (SCHEME, host, path), data=data, method='PUT',
                                     headers={k: v for k, v in headers.items() if k != 'host'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, mode, 'ok'
        except urllib.error.HTTPError as e:
            body = e.read(600).decode('utf-8', 'replace')
            code = ''
            if '<Code>' in body:
                code = body.split('<Code>', 1)[1].split('</Code>', 1)[0]
            last = (e.code, mode, code or e.reason)
            if e.code in (401, 403) and code in ('SignatureDoesNotMatch', 'InvalidAccessKeyId', 'AccessDenied'):
                return last
        except Exception as e:
            last = (0, mode, str(e)[:200])
    return last


def load():
    with open(CONFIG, encoding='utf-8') as f:
        return json.load(f)


def main(argv):
    if len(argv) >= 2 and argv[1] == 'ping':
        cfg = load()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        code, mode, msg = put_bytes(cfg, 'check/ping-%s.txt' % stamp, b'fpl ok ' + stamp.encode(), 'text/plain')
        print(code, mode, msg)
        return 0 if 200 <= code < 300 else 1
    if len(argv) == 4 and argv[1] == 'put':
        cfg = load()
        with open(argv[2], 'rb') as f:
            data = f.read()
        code, mode, msg = put_bytes(cfg, argv[3], data, timeout=600)
        print(code, mode, msg)
        return 0 if 200 <= code < 300 else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
