"""Secret encryption and password hashing.

* Service credentials are encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
  The key lives in ``secret.key`` next to the database, never inside it.
* The admin password is hashed with scrypt (standard library).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

# scrypt parameters: ~32 MiB memory per hash.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def load_or_create_key(path: Path) -> bytes:
    """Return the Fernet key from *path*, creating it (mode 600) on first run."""
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class SecretBox:
    """Encrypts a dict of secrets to a single opaque string."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt_json(self, data: dict[str, Any]) -> str | None:
        if not data:
            return None
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt_json(self, token: str | None) -> dict[str, Any]:
        """Raises ``cryptography.fernet.InvalidToken`` if the key does not match."""
        if not token:
            return {}
        return json.loads(self._fernet.decrypt(token.encode()))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p),
            maxmem=_SCRYPT_MAXMEM, dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    """Session/device tokens are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode()).hexdigest()
