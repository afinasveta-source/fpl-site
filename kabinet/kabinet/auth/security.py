import hashlib
import secrets
import threading

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


class Busy(Exception):
    """Слишком много входов сразу — ответить «попробуйте через минуту», а не держать поток."""


class BoundedHasher:
    """Argon2id берёт 64 МБ памяти на каждую проверку пароля. Сервер маленький (служба — до 350 МБ), а после рассылки
    в кабинет входят сразу десятки человек: без ограничения 6 одновременных входов останавливали службу (нагрузочный
    тест 13.10: 20 входов сразу — 1,2 ГБ). Поэтому не больше двух вычислений одновременно (~0,2 с каждое) и не больше
    max_waiting ждущих: ждущий занимает поток службы, а их всего 40 на все страницы — лишним сразу «занято»."""

    def __init__(self, inner, limit=2, max_waiting=20):
        self.inner = inner
        self.gate = threading.BoundedSemaphore(limit)
        self.max_waiting = max_waiting
        self.waiting = 0
        self.lock = threading.Lock()

    def _run(self, fn, *args):
        with self.lock:
            if self.waiting >= self.max_waiting:
                raise Busy()
            self.waiting += 1
        try:
            self.gate.acquire()
        finally:
            with self.lock:
                self.waiting -= 1
        try:
            return fn(*args)
        finally:
            self.gate.release()

    def hash(self, password):
        return self._run(self.inner.hash, password)

    def verify(self, password, encoded):
        return self._run(self.inner.verify, password, encoded)


password_hasher = BoundedHasher(PasswordHash.recommended())  # Argon2id
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def new_token():
    return secrets.token_urlsafe(32)  # 256 random bits


def token_hash(raw: str):
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_password(password: str, stored_hash: str | None):
    try:
        return password_hasher.verify(password, stored_hash or DUMMY_HASH) and stored_hash is not None
    except (UnknownHashError, ValueError):
        # Unknown/malformed imported hashes cannot authorize a login.
        password_hasher.verify(password, DUMMY_HASH)
        return False
