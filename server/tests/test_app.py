from __future__ import annotations

import re

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
PASSWORD = "correct horse battery"
SECRET = "super-secret-api-key-123"


def setup_and_login(client) -> str:
    response = client.post("/setup", data={"password": PASSWORD, "confirm": PASSWORD})
    assert response.url.path == "/login"
    response = client.post("/login", data={"password": PASSWORD})
    assert response.url.path == "/admin"
    match = CSRF_RE.search(response.text)
    assert match
    return match.group(1)


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_first_visit_goes_to_setup(client):
    assert client.get("/admin").url.path == "/setup"


def test_setup_rejects_short_or_mismatched_password(client):
    assert client.post("/setup", data={"password": "short", "confirm": "short"}).status_code == 400
    assert client.post("/setup", data={"password": PASSWORD, "confirm": PASSWORD + "x"}).status_code == 400


def test_setup_only_works_once(client):
    setup_and_login(client)
    client.post("/logout", data={"csrf_token": CSRF_RE.search(client.get("/admin").text).group(1)})
    client.post("/setup", data={"password": "another long password", "confirm": "another long password"})
    # Original password still works; the second setup was ignored.
    assert client.post("/login", data={"password": PASSWORD}).url.path == "/admin"


def test_wrong_password_and_lockout(client):
    client.post("/setup", data={"password": PASSWORD, "confirm": PASSWORD})
    for _ in range(5):
        assert client.post("/login", data={"password": "wrong password!"}).status_code == 401
    assert client.post("/login", data={"password": PASSWORD}).status_code == 429


def test_admin_requires_login(client):
    client.post("/setup", data={"password": PASSWORD, "confirm": PASSWORD})
    assert client.get("/admin").url.path == "/login"


def test_csrf_required(client):
    setup_and_login(client)
    response = client.post("/admin/services/new?type=tcp", data={"name": "SSH", "host": "127.0.0.1", "port": "22"})
    assert response.status_code == 400


def test_secret_encrypted_and_never_rendered(client, app):
    csrf = setup_and_login(client)
    response = client.post(
        "/admin/services/new?type=http",
        data={
            "csrf_token": csrf, "name": "Example", "category": "Test",
            "url": "http://127.0.0.1:9", "expected_status": "200-399", "verify_tls": "on",
            "timeout": "2", "header_name": "X-Api-Key", "header_value": SECRET, "enabled": "on",
        },
    )
    assert response.url.path == "/admin"
    assert "Example" in response.text
    assert SECRET not in response.text

    service = app.state.store.list()[0]
    assert SECRET not in (service.secrets_enc or "")
    assert app.state.box.decrypt_json(service.secrets_enc) == {"header_value": SECRET}

    data_dir = app.state.settings.data_dir
    for db_file in data_dir.glob("hub.db*"):
        assert SECRET.encode() not in db_file.read_bytes()

    edit = client.get(f"/admin/services/{service.id}/edit")
    assert SECRET not in edit.text
    assert "saved (leave blank to keep)" in edit.text

    # Saving without re-entering the secret keeps it.
    client.post(
        f"/admin/services/{service.id}/edit",
        data={"csrf_token": csrf, "name": "Renamed", "url": "http://127.0.0.1:9",
              "expected_status": "200-399", "timeout": "2", "header_name": "X-Api-Key", "enabled": "on"},
    )
    updated = app.state.store.get(service.id)
    assert updated.name == "Renamed"
    assert app.state.box.decrypt_json(updated.secrets_enc) == {"header_value": SECRET}


def test_validation_error_shown(client):
    csrf = setup_and_login(client)
    response = client.post(
        "/admin/services/new?type=http",
        data={"csrf_token": csrf, "name": "Bad", "url": "ftp://x", "expected_status": "200", "timeout": "5"},
    )
    assert response.status_code == 400
    assert "must start with http://" in response.text


def test_name_autofill_and_category_dropdown(client, app, csrf):
    # Integration name is pre-filled; generic checks stay blank.
    assert 'name="name" value="Sonarr"' in client.get("/admin/services/new?type=sonarr").text
    assert 'name="name" value=""' in client.get("/admin/services/new?type=http").text

    base = {"csrf_token": csrf, "host": "127.0.0.1", "port": "9", "timeout": "1"}
    # "+ Add new category" with a name creates it...
    client.post("/admin/services/new?type=tcp",
                data={**base, "name": "A", "category_choice": "__new__", "category_new": "Media"})
    # ...after which it appears in the dropdown and can be picked.
    form_page = client.get("/admin/services/new?type=tcp").text
    assert '<option value="Media"' in form_page
    client.post("/admin/services/new?type=tcp", data={**base, "name": "B", "category_choice": "Media"})
    # "+ Add new" without a name is an error.
    bad = client.post("/admin/services/new?type=tcp",
                      data={**base, "name": "C", "category_choice": "__new__", "category_new": ""})
    assert bad.status_code == 400 and "Enter a name for the new category" in bad.text

    services = {s.name: s.category for s in app.state.store.list()}
    assert services == {"A": "Media", "B": "Media"}
    assert app.state.store.categories() == ["Media"]


def test_test_and_delete_service(client, app):
    csrf = setup_and_login(client)
    client.post(
        "/admin/services/new?type=tcp",
        data={"csrf_token": csrf, "name": "Closed port", "host": "127.0.0.1", "port": "9", "timeout": "1", "enabled": "on"},
    )
    service = app.state.store.list()[0]
    response = client.post(f"/admin/services/{service.id}/test", data={"csrf_token": csrf})
    assert response.url.path == "/admin"
    assert app.state.poller.results[service.id].status == "down"

    client.post(f"/admin/services/{service.id}/delete", data={"csrf_token": csrf})
    assert app.state.store.list() == []
    assert service.id not in app.state.poller.results
