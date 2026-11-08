from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app(tmp_path):
    settings = Settings(data_dir=tmp_path, poll_interval=3600, secure_cookies=False, session_hours=1)
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def csrf(client) -> str:
    """Create the admin, log in, and return the session's CSRF token."""
    password = "correct horse battery"
    client.post("/setup", data={"password": password, "confirm": password})
    response = client.post("/login", data={"password": password})
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, "login did not reach the admin page"
    return match.group(1)
