"""RFC 6238 time-based one-time passwords (optional MFA), standard library only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def current_code(secret: str, at: float | None = None, step: int = 30) -> str:
    return _code(secret, int((at if at is not None else time.time()) // step))


def verify(secret: str, code: str, at: float | None = None, step: int = 30, window: int = 1) -> bool:
    if not code or not code.isdigit():
        return False
    counter = int((at if at is not None else time.time()) // step)
    return any(hmac.compare_digest(_code(secret, counter + d), code) for d in range(-window, window + 1))


def provisioning_uri(secret: str, username: str, issuer: str = "Project Atlas") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}"
