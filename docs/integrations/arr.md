# Sonarr, Radarr, and Prowlarr

Add each app as its own service. The phone app combines them into one media overview.
The Hub only makes read-only `GET` requests.

| App | Shows | API used |
|---|---|---|
| Sonarr | Download queue, upcoming episodes, health warnings | `/api/v3/system/status`, `/health`, `/queue`, `/calendar` |
| Radarr | Download queue, upcoming releases (cinema/digital/physical), health warnings | same as Sonarr |
| Prowlarr | Enabled and failing indexers, health warnings | `/api/v1/system/status`, `/health`, `/indexer`, `/indexerstatus` |

## Setup

1. In each app: **Settings → General → Security → API Key**. Copy the key.
2. In the Hub: **Add service → Sonarr / Radarr / Prowlarr**.

| Field | Value |
|---|---|
| URL | The app's address, e.g. `http://192.168.1.10:8989`. If you set a **URL Base** in the app (e.g. `/sonarr`), include it: `http://192.168.1.10:8989/sonarr` |
| API key | From step 1 |
| Upcoming window | How many days ahead to show (Sonarr/Radarr, default 7) |

> [!NOTE]
> These apps only offer **full-access** API keys; there is no read-only key. The Hub stores the key encrypted
> and never uses it to change anything, but treat it like a password, and keep the Hub on your LAN/VPN.

## Status colours

| Colour | Meaning |
|---|---|
| Green | Reachable, no health warnings (and, for Prowlarr, no failing indexers) |
| Yellow | Reachable, but the app reports warnings/errors, or an indexer is failing |
| Red | Unreachable, wrong API key (`HTTP 401`), or the URL points at a different app |

Queue items that need attention (e.g. "No files found are eligible for import") are flagged with ⚠.
