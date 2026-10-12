"""Репозиторий открытый: ключи и пароли в нём быть не должны (они только на сервере в /etc/*.env)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(?i)\b(FPL_[A-Z_]*(KEY|PASSWORD|SECRET)[A-Z_]*|secret_key|access_key)\s*[=:]\s*["\']?[A-Za-z0-9/+=_-]{16,}'),
    re.compile(r'postgresql://[^:\s/]+:[^@\s{$]{6,}@'),
    re.compile(r'\bghp_[A-Za-z0-9]{30,}\b'),
]
ALLOW = {'kabinet/tests/test_no_secrets.py'}


def tracked_files():
    out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f not in ALLOW and not f.endswith(('.woff2', '.png', '.webp', '.jpg', '.zip', '.tgz', '.ico'))]


def test_no_secrets_in_repository():
    found = []
    for name in tracked_files():
        try:
            text = (ROOT / name).read_text(encoding='utf-8')
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for p in PATTERNS:
            m = p.search(text)
            if m:
                found.append('%s: %s' % (name, m.group(0)[:40]))
    assert not found, found
