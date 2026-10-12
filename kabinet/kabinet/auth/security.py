import hashlib
import secrets
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hasher = PasswordHash.recommended()  # Argon2id
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
