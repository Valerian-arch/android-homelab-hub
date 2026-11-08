# Homelab Hub (server)

Python + FastAPI + SQLite, packaged as a Docker image.

**Phase 1 (current):** admin login, encrypted credential storage, add/edit/delete services,
and generic **HTTP(S)** and **TCP port** up/down checks. Service-specific integrations
(Proxmox, *arr, etc.) and the phone API come next. See [../docs/PLAN.md](../docs/PLAN.md).

## Run locally (development)

```sh
cd server
python -m venv .venv
source .venv/bin/activate        # fish: source .venv/bin/activate.fish
pip install -r requirements-dev.txt
pytest
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080 --reload
```

Open http://127.0.0.1:8080. The first visit asks you to create the admin password.
Local data goes to `server/data/` (git-ignored).

## Run with Docker

```sh
cd server
cp docker-compose.example.yml docker-compose.yml   # then edit the volume path
docker compose up -d --build
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HUB_DATA_DIR` | `./data` (`/data` in Docker) | Where `hub.db` and `secret.key` live |
| `HUB_POLL_INTERVAL` | `60` | Seconds between checks (min 10) |
| `HUB_SESSION_HOURS` | `12` | Admin login lifetime |
| `HUB_SECURE_COOKIES` | `false` | Set `true` when served over HTTPS |

## Security model

- Service credentials are encrypted with a key in `secret.key` (created on first run, mode 600).
  **Back up `hub.db` and `secret.key` together**, and keep the backups private.
- Secrets are write-only in the UI. They are never displayed or returned after saving.
- The admin password is hashed with scrypt. Failed logins are rate-limited.
- Forms are protected with CSRF tokens and `SameSite=Strict` cookies.
- Run it on your LAN or behind a VPN only.
