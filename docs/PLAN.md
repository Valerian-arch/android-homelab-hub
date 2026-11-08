# Project plan

Public, generic version of the project plan. It deliberately contains no details about any specific homelab.

## Goal

An Android app that shows all of a user's homelab devices and services in one place, similar to a self-hosted dashboard. All credentials live in a self-hosted **Hub**. The phone holds only a single revocable token.

## Principles

1. **Credentials never leave the server.** API keys and passwords are entered only on the Hub's admin page and encrypted at rest. They are never returned by any API.
2. **Generic and user-configured.** No IPs, hostnames, or service lists are hard-coded. Every integration is optional.
3. **Read-only first.** Version 1 only reads status. Any future control action (restart, etc.) must be opt-in per service.
4. **Private network only.** The Hub is meant to be reached over a LAN or a VPN (e.g. Tailscale or WireGuard), not the public internet.
5. **Least privilege.** The docs recommend the most limited credential each service supports.

## Architecture

### Hub (`server/`)

- Python, FastAPI, SQLite, one Docker container.
- **Admin web UI:** admin login; add, edit, and test services; pair and revoke phones.
- **Secret storage:** service credentials encrypted with a master key stored outside the database (key file in the mounted config directory).
- **Poller:** checks each configured service on an interval (default 30–60 s) and caches the results. Phone requests read the cache.
- **Phone API (read-only, token auth):**
  - `POST /api/v1/pair`: exchange a one-time pairing code (shown as a QR code) for a device token
  - `GET /api/v1/dashboard`: everything needed for the main screen
  - `GET /api/v1/services/{id}`: detail for one service
- **Device tokens:** random, stored hashed, one per device, revocable.
- **Integrations:** each one is a small plugin with a common interface (`test_connection()`, `poll()`) so new service types can be added easily.

### Android app (`android/`)

- Kotlin + Jetpack Compose. Distributed as an APK.
- Stores only the Hub URL and the device token, encrypted with Android Keystore. Excluded from cloud backup.
- Optional biometric lock.
- Screens: Overview (all services with status), Infrastructure, Media, Settings.
- Tapping a service opens its web UI.
- Later: home-screen widgets (Jetpack Glance), alerts.

## v1 integrations and recommended credentials

| Service | Credential | Least-privilege option |
|---|---|---|
| Proxmox VE | API token | Token with `PVEAuditor` role |
| TrueNAS SCALE (25.x) | API key (JSON-RPC over WebSocket) | Key for a read-only user/role |
| Pi-hole (v6) | App password | Full Pi-hole access only |
| Sonarr / Radarr / Prowlarr | API key | Full access only |
| SABnzbd | API key | Full access needed for queue |
| Jellyfin | API key | Admin only; prefer LAN URL |
| Generic HTTP / ping | none | n/a |

## Build phases

1. Hub skeleton: admin login, encrypted secret store, service CRUD, generic up/down checks.
2. Integrations, one at a time, each with a "test connection" button.
3. Phone API and QR pairing, token revoke.
4. Android app v1.
5. Docker packaging, example compose file, setup guide.
6. Later: widgets, alerts, HTTPS guidance, optional desktop web view.

## Before going public

- ~~Choose a license.~~ GPL-3.0 (chosen 2026-11-08).
- Write a setup guide for new users.
- Audit the git history for any committed secrets or personal details.
