from __future__ import annotations

import stat

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.crypto import SecretBox, hash_password, load_or_create_key, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert "correct horse battery" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong password", stored)


def test_verify_password_rejects_garbage():
    assert not verify_password("anything", "not-a-hash")


def test_key_file_created_private_and_reused(tmp_path):
    path = tmp_path / "secret.key"
    key = load_or_create_key(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_or_create_key(path) == key


def test_secret_box_roundtrip():
    box = SecretBox(Fernet.generate_key())
    token = box.encrypt_json({"api_key": "abc123"})
    assert token is not None and "abc123" not in token
    assert box.decrypt_json(token) == {"api_key": "abc123"}
    assert box.encrypt_json({}) is None
    assert box.decrypt_json(None) == {}


def test_secret_box_wrong_key_fails():
    token = SecretBox(Fernet.generate_key()).encrypt_json({"k": "v"})
    with pytest.raises(InvalidToken):
        SecretBox(Fernet.generate_key()).decrypt_json(token)
