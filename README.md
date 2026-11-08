# Android Homelab Hub

A self-hosted **Hub** plus an **Android app** that show all your homelab devices and services in one place.

> **Status:** early development. Not ready for use yet.

## How it works

```
Android app ──(your LAN or VPN, e.g. Tailscale)──► Homelab Hub ──► your services
     │                                                  │
     └ stores only: Hub URL + one device token          └ stores all API keys/passwords (encrypted)
```

- **Your credentials stay on your server.** You enter API keys and passwords in the Hub's admin page. The phone never sees them.
- **One revocable token per phone.** Pair a phone by scanning a QR code. If you lose the phone, revoke its token.
- **Read-only.** The first version only *shows* status. It never changes anything on your services.
- **Bring your own services.** Nothing is hard-coded. Add only the services you run.

## Planned integrations (v1)

| Integration | Shows |
|---|---|
| Proxmox VE | Node and VM/LXC status, CPU, RAM |
| TrueNAS SCALE | Pool health, storage use |
| Pi-hole | Queries, blocked count, status |
| Sonarr / Radarr / Prowlarr | Queue, upcoming, health warnings |
| SABnzbd | Speed, queue |
| Jellyfin | Server status, active streams |
| Generic HTTP / ping | Up/down for anything else |

## Repository layout

```
server/    Hub: Python (FastAPI), runs in Docker
android/   Android app: Kotlin + Jetpack Compose
docs/      Plan, setup guide, API reference
```

## Security notes

- Run the Hub on your LAN or behind a VPN. **Do not expose it to the public internet.**
- Use read-only or least-privilege credentials wherever a service supports them (e.g. a Proxmox API token with the `PVEAuditor` role).
- Never commit real config. Only `*.example` files belong in this repo.

## License

[GNU General Public License v3.0](LICENSE). This covers both the Hub (`server/`) and the Android app (`android/`).

You're free to use, study, change, and share it. If you distribute a modified version, it must also be
released under the GPL-3.0 with its source code. Running the Hub and the app for yourself carries no obligations.
