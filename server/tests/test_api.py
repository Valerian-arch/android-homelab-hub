from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

from app.integrations import CheckResult

CODE_RE = re.compile(r'class="pair-code">([A-Z0-9]{4}-[A-Z0-9]{4})<')
SECRET = "super-secret-key-9876"


def create_code(client, csrf, hub_url="http://192.168.1.50:8080") -> tuple[str, str]:
    page = client.post("/admin/phones/pair", data={"csrf_token": csrf, "hub_url": hub_url})
    assert page.status_code == 200
    return CODE_RE.search(page.text).group(1), page.text


def pair(client, csrf, name="Test phone") -> str:
    code, _ = create_code(client, csrf)
    response = client.post("/api/v1/pair", json={"code": code, "device_name": name})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pairing_page_shows_qr_and_code(client, csrf):
    code, html = create_code(client, csrf)
    assert "data:image/svg+xml" in html
    assert "expires in 10 minutes" in html
    assert "only works on this computer" not in html
    # Hub URL is remembered for next time.
    assert 'value="http://192.168.1.50:8080"' in client.get("/admin/phones").text


def test_pairing_warns_about_localhost(client, csrf):
    _, html = create_code(client, csrf, hub_url="http://127.0.0.1:8080")
    assert "only works on this computer" in html


def test_pairing_requires_valid_url_and_csrf(client, csrf):
    assert client.post("/admin/phones/pair", data={"csrf_token": csrf, "hub_url": "nope"}).status_code == 400
    assert client.post("/admin/phones/pair", data={"hub_url": "http://x.test"}).status_code == 400


def test_pair_and_read_dashboard(client, app, csrf):
    client.post(
        "/admin/services/new?type=http",
        data={"csrf_token": csrf, "name": "Web", "category_choice": "__new__", "category_new": "Apps",
              "url": "http://127.0.0.1:9", "expected_status": "200-399", "timeout": "2",
              "header_name": "X-Api-Key", "header_value": SECRET},
    )
    service = app.state.store.list()[0]
    app.state.poller.results[service.id] = CheckResult("up", "HTTP 200", 12, data={"extra": 1})

    token = pair(client, csrf, name="Galaxy")
    assert client.get("/api/v1/me", headers=auth(token)).json()["name"] == "Galaxy"

    response = client.get("/api/v1/dashboard", headers=auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["categories"] == ["Apps"]
    assert body["summary"]["paused"] == 1  # saved without "Monitor automatically"
    entry = body["services"][0]
    assert entry["name"] == "Web" and entry["type_label"] == "HTTP(S) check"
    assert entry["status"] == "paused" and entry["message"] == "HTTP 200" and entry["data"] == {"extra": 1}
    assert SECRET not in response.text
    assert "secrets_enc" not in response.text and "header_value" not in response.text

    # The admin page lists the phone with a last-seen time.
    phones = client.get("/admin/phones").text
    assert "Galaxy" in phones and "Last seen never" not in phones


def test_code_is_single_use_and_case_insensitive(client, csrf):
    code, _ = create_code(client, csrf)
    sloppy = code.lower().replace("-", " ")
    assert client.post("/api/v1/pair", json={"code": sloppy}).status_code == 200
    assert client.post("/api/v1/pair", json={"code": code}).status_code == 400


def test_expired_code_rejected(client, app, csrf):
    code, _ = create_code(client, csrf)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE pairing_codes SET expires_at = '2000-01-01T00:00:00+00:00'")
    response = client.post("/api/v1/pair", json={"code": code})
    assert response.status_code == 400 and "expired" in response.json()["detail"]


def test_missing_bad_and_revoked_tokens(client, app, csrf):
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.get("/api/v1/dashboard", headers=auth("not-a-token")).status_code == 401

    token = pair(client, csrf)
    assert client.get("/api/v1/dashboard", headers=auth(token)).status_code == 200
    device_id = app.state.devices.list()[0].id
    client.post(f"/admin/phones/{device_id}/revoke", data={"csrf_token": csrf})
    assert client.get("/api/v1/dashboard", headers=auth(token)).status_code == 401


def test_phone_can_unpair_itself(client, csrf):
    token = pair(client, csrf)
    assert client.post("/api/v1/unpair", headers=auth(token)).json() == {"status": "unpaired"}
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_pairing_rate_limited(client):
    for _ in range(10):
        assert client.post("/api/v1/pair", json={"code": "AAAA-AAAA"}).status_code == 400
    assert client.post("/api/v1/pair", json={"code": "AAAA-AAAA"}).status_code == 429


def test_tokens_stored_hashed(client, app, csrf):
    token = pair(client, csrf)
    for db_file in app.state.settings.data_dir.glob("hub.db*"):
        assert token.encode() not in db_file.read_bytes()


def test_qr_contains_hub_url_and_code(client, csrf, monkeypatch):
    captured = {}
    import segno

    real_make = segno.make

    def spy(content, **kwargs):
        captured["content"] = content
        return real_make(content, **kwargs)

    monkeypatch.setattr("app.routes_admin.segno.make", spy)
    code, _ = create_code(client, csrf, hub_url="http://100.64.1.2:8080")
    uri = urlsplit(captured["content"])
    assert uri.scheme == "homelabhub" and uri.netloc == "pair"
    params = parse_qs(uri.query)
    assert unquote(params["url"][0]) == "http://100.64.1.2:8080"
    assert params["code"][0] == code
