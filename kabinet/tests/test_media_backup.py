"""fpl-media-backup (server/kabinet): отправка оригиналов и архива бота в бакет, удаление старых оригиналов с сервера."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'server' / 'kabinet' / 'fpl-media-backup'

FAKE_S3 = textwrap.dedent('''
    import json, os
    CONFIG = os.environ['FAKE_CFG']
    def load():
        return json.load(open(CONFIG))
    def put_bytes(cfg, key, data, content_type='application/octet-stream', timeout=120):
        if os.environ.get('FAKE_FAIL'):
            return 500, 'vhost', 'InternalError'
        out = os.path.join(os.environ['FAKE_BUCKET'], key)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, 'wb').write(data)
        return 200, 'vhost', 'ok'
''')


def setup(tmp):
    media, archive, bucket, lib = tmp / 'media', tmp / 'archive', tmp / 'bucket', tmp / 'lib'
    for d in (media, archive / 'files', bucket, lib):
        d.mkdir(parents=True, exist_ok=True)
    (lib / 'fpl_s3.py').write_text(FAKE_S3)
    (tmp / 'cfg.json').write_text('{}')
    env = dict(os.environ, FPL_MEDIA_DIR=str(media), FPL_ARCHIVE=str(archive), FPL_MEDIA_JOURNAL=str(tmp / 'journal.json'),
               FPL_MEDIA_STATUS=str(tmp / 'status'), FPL_S3_LIB=str(lib / 'fpl_s3.py'), FAKE_CFG=str(tmp / 'cfg.json'),
               FAKE_BUCKET=str(bucket))
    return media, archive, bucket, env


def photo(media, digest, views=True):
    for kind, ext in (('orig', 'png'), ('view', 'jpg'), ('thumb', 'jpg')):
        if kind != 'orig' and not views:
            continue
        p = media / kind / digest[:2] / f'{digest}.{ext}'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(kind.encode() * 1000)
    return media / 'orig' / digest[:2] / f'{digest}.png'


def run(env, **extra):
    r = subprocess.run([sys.executable, str(SCRIPT)], env=dict(env, **extra), capture_output=True, text=True)
    return r.returncode


def test_sent_then_pruned_after_grace(tmp_path):
    media, archive, bucket, env = setup(tmp_path)
    a = photo(media, 'aa' + '1' * 62)
    b = photo(media, 'bb' + '2' * 62, views=False)          # копий для показа нет — оригинал не трогаем
    (archive / 'files' / 'x1.jpg').write_bytes(b'bot photo')
    (archive / 'index.json').write_text('{"k": "x1.jpg"}')
    assert run(env) == 0
    assert (bucket / 'media' / 'orig' / 'aa' / a.name).is_file()
    assert (bucket / 'media' / 'orig' / 'bb' / b.name).is_file()
    assert (bucket / 'archive' / 'files' / 'x1.jpg').read_bytes() == b'bot photo'
    assert list((bucket / 'archive').glob('index-*.json'))
    assert a.is_file() and b.is_file()                        # только что отправлены — сутки держим
    status = (tmp_path / 'status').read_text()
    assert status.startswith('ok ') and 'sent 3' in status and 'pruned 0' in status
    assert run(env, FPL_MEDIA_PRUNE_AFTER='0') == 0
    assert not a.exists() and b.is_file()                     # отправлен и есть view/thumb — удалён
    assert (media / 'view' / 'aa' / ('aa' + '1' * 62 + '.jpg')).is_file()
    assert (archive / 'files' / 'x1.jpg').is_file()           # архив бота на сервере остаётся
    status = (tmp_path / 'status').read_text()
    assert 'pruned 1' in status and 'files 2' in status and 'archive 1' in status
    # повторный запуск: удалённый оригинал заново не отправляется, ошибок нет
    assert run(env, FPL_MEDIA_PRUNE_AFTER='0') == 0
    assert 'sent 0' in (tmp_path / 'status').read_text()


def test_keep_orig_switch_and_failed_upload(tmp_path):
    media, archive, bucket, env = setup(tmp_path)
    a = photo(media, 'cc' + '3' * 62)
    assert run(env, FAKE_FAIL='1', FPL_MEDIA_PRUNE_AFTER='0') == 1   # бакет не принял — ничего не удаляем
    assert a.is_file() and 'error' in (tmp_path / 'status').read_text()
    assert run(env, FPL_MEDIA_PRUNE_AFTER='0', FPL_MEDIA_KEEP_ORIG='1') == 0
    assert a.is_file()                                        # выключатель: оригиналы остаются
    assert run(env, FPL_MEDIA_PRUNE_AFTER='0') == 0
    assert not a.exists()


def test_old_journal_list_gets_grace(tmp_path):
    media, archive, bucket, env = setup(tmp_path)
    a = photo(media, 'dd' + '4' * 62)
    rel = os.path.relpath(a, media)
    (tmp_path / 'journal.json').write_text(json.dumps([rel]))   # журнал старого вида — без времени
    assert run(env) == 0
    assert a.is_file()                                         # время отправки неизвестно — сутки ждём
    journal = json.loads((tmp_path / 'journal.json').read_text())
    assert isinstance(journal, dict) and rel in journal
    assert run(env, FPL_MEDIA_PRUNE_AFTER='0') == 0
    assert not a.exists()
