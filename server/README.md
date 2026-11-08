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

On first start the Hub prints a **temporary admin password** to the log/terminal. Open
http://127.0.0.1:8080, log in with it, and choose your own password. You then get **5 recovery codes**:
save them, because they let you reset a forgotten password (login page → "Forgot password?").
Local data goes to `server/data/` (git-ignored).

Lost the password and all recovery codes? Run this on the server:

```sh
docker exec -it homelab-hub python -m app.admin_cli reset-password   # Docker
python -m app.admin_cli reset-password                                # local, from server/
```

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
| `HUB_INITIAL_ADMIN_PASSWORD` | random | Optional: the first-start password instead of a random one (must still be changed) |

## Security model

- Service credentials are encrypted with a key in `secret.key` (created on first run, mode 600).
  **Back up `hub.db` and `secret.key` together**, and keep the backups private.
- Secrets are write-only in the UI. They are never displayed or returned after saving, and any
  secret that shows up in a service's reply or error is replaced with `***`.
- First start uses a random temporary password that must be changed. There is no open setup page.
- The admin password is hashed with scrypt. **3 failed attempts lock that IP out for 15 minutes.**
  Attempts are counted before the password is checked, and only 2 checks run at once.
- Forms are protected with CSRF tokens and `SameSite=Strict` cookies. Login and recovery
  forms reject submissions from other websites.
- Replies from monitored services are capped at 5 MB, and the Hub doesn't follow redirects unless
  you allow it per service. Auth headers are never sent to a different server.
- The example compose file runs the container read-only, with no Linux capabilities and `no-new-privileges`.
- **Plain HTTP:** run it on your LAN, or better behind Tailscale/WireGuard (encrypted), or put HTTPS in front
  and set `HUB_SECURE_COOKIES=true`. Give the Hub its own host or IP; browsers share cookies between
  apps on the same IP.
