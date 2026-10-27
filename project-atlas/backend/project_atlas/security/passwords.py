"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with library defaults (t=3, m=64MiB, p=4)

MIN_LENGTH = 12
_COMMON = {"password1234", "123456789012", "qwertyuiop12", "letmein12345", "administrator", "projectatlas1"}


class WeakPasswordError(ValueError):
    pass


def check_policy(password: str, username: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > 256:
        raise WeakPasswordError("Password is too long")
    if password.lower() in _COMMON:
        raise WeakPasswordError("Password is too common")
    if username and username.lower() in password.lower():
        raise WeakPasswordError("Password must not contain the username")
    classes = sum(
        [any(c.islower() for c in password), any(c.isupper() for c in password),
         any(c.isdigit() for c in password), any(not c.isalnum() for c in password)]
    )
    if classes < 3:
        raise WeakPasswordError("Password must mix at least three of: lowercase, uppercase, digits, symbols")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


# Pre-computed hash used to equalise timing when a username does not exist.
DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
