# Phone API (v1)

The Android app talks to the Hub only through these endpoints. All responses are JSON.
The API is **read-only**: no endpoint changes services or exposes credentials.

## Pairing

1. Admin opens **Phones → Create pairing code** on the Hub.
2. The Hub shows a QR code containing:
   ```
   homelabhub://pair?url=<hub address, URL-encoded>&code=ABCD-EFGH
   ```
   and the same 8-character code for manual entry. Codes work **once** and expire after **10 minutes**.
3. The app exchanges the code for a device token:

```http
POST /api/v1/pair
Content-Type: application/json

{"code": "ABCD-EFGH", "device_name": "Galaxy S26 Ultra"}
```

```json
{"token": "<device token>", "hub": {"name": "Homelab Hub", "version": "0.1.0"}}
```

- Codes are case-insensitive; spaces and dashes are ignored.
- `400`: invalid or expired code. `429`: too many failed attempts from this IP (10 per 10 minutes).
- The token is shown **once**. The Hub stores only its SHA-256 hash. The app should keep it in Android Keystore-backed storage.

## Authentication

Every other endpoint needs:

```
Authorization: Bearer <device token>
```

`401` means the token is missing, invalid, or was revoked on the Hub (Phones → Remove). The app should then ask the user to pair again.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/dashboard` | Everything for the main screen |
| `GET` | `/api/v1/me` | Check the token: `{"id", "name", "paired_at"}` |
| `POST` | `/api/v1/unpair` | The phone removes its own token |
| `GET` | `/healthz` | No auth. `{"status": "ok"}` |

### `GET /api/v1/dashboard`

```json
{
  "hub": {"name": "Homelab Hub", "version": "0.1.0", "poll_interval": 60, "generated_at": "2026-11-08T17:00:00+00:00"},
  "summary": {"up": 7, "degraded": 1, "down": 0, "unknown": 0, "pending": 0, "paused": 1},
  "categories": ["Infrastructure", "Media"],
  "services": [
    {
      "id": 2,
      "name": "Proxmox",
      "type": "proxmox",
      "type_label": "Proxmox VE",
      "category": "Infrastructure",
      "link_url": "https://192.168.1.20:8006",
      "status": "up",
      "message": "4/4 nodes online · 7/7 guests running",
      "latency_ms": 299,
      "checked_at": "2026-11-08T17:00:00+00:00",
      "data": { "nodes": [], "guests": [] }
    }
  ]
}
```

- `status` is one of `up`, `degraded`, `down`, `unknown`, `pending` (not checked yet), or `paused` (monitoring turned off).
- `category` may be `""` (no category).
- `data` depends on `type`. The field names match what each integration's admin detail view shows:

| type | `data` keys |
|---|---|
| `proxmox` | `nodes[]` (name, status, cpu_pct, mem_used, mem_total, mem_pct, uptime), `guests[]` (vmid, name, type, node, status, cpu_pct, mem_used, mem_total, mem_pct) |
| `sonarr`, `radarr` | `version`, `health[]`, `queue[]` (title, status, state, progress, timeleft, problem), `queue_total`, `upcoming[]` (title, date, kind, has_file) |
| `prowlarr` | `version`, `health[]`, `indexers[]` (name, enabled, protocol, failing, disabled_until) |
| `sabnzbd` | `paused`, `speed`, `timeleft`, `queue[]`, `queue_total`, `failed[]`, `failed_total`, `warnings[]`, `disk_free_gb` |
| `nzbget`, `qbittorrent` | `download_speed`, `upload_speed`, `paused`, `queue[]` (name, status, progress, speed, timeleft, category), `queue_total`, `failed[]`, `failed_total` |
| `qui` | `instances[]` (name, connected, error, download_speed, upload_speed, connection), `download_speed`, `upload_speed` |
| `jellyfin` | `server`, `version`, `streams[]` (user, device, client, title, progress, paused, method, transcoding), `counts` |
| `http`, `tcp` | `{}` |

The Hub refreshes results every `poll_interval` seconds, so the app doesn't need to poll faster than that.
