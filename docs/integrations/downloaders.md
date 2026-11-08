# qBittorrent, qui, and NZBGet

All read-only: the Hub never pauses, deletes, or adds downloads.

## qBittorrent

Shows download/upload speed, active downloads (progress, speed, ETA), errored torrents, and connection status.

- **URL:** the WebUI address, e.g. `http://192.168.1.10:8080`
- **Username / password:** your WebUI login (Options → WebUI → Authentication).
  Leave blank only if qBittorrent bypasses authentication for the Hub's IP/subnet.

> [!WARNING]
> qBittorrent temporarily **bans an IP after repeated failed logins**. If the Hub shows "banned",
> fix the password first, then wait for the ban to expire or restart qBittorrent.

Yellow means at least one torrent is in an error state, or qBittorrent reports no connection.
"Firewalled" is shown but isn't treated as a problem (common behind a VPN without port forwarding).

## qui

[qui](https://github.com/autobrr/qui) is a web UI that manages one or more qBittorrent instances.
One Hub entry shows every **active** instance qui knows about: connected/disconnected (with qui's error text) and speeds.

- **URL:** e.g. `http://192.168.1.10:7476`
- **API key:** qui → **Settings → API Keys**. This is the regular API key, not a "Client Proxy" key.

If you use qui, you can add **either** qui (an overview of all instances) **or** each qBittorrent directly (queue details), **or** both.

## NZBGet

Shows speed (or "Paused"), the queue with progress, estimated time left, free disk space, and recent failures from history.

- **URL:** e.g. `http://192.168.1.10:6789`
- **Username / password:** from NZBGet **Settings → Security**.
  Prefer the **RestrictedUsername** account: it can view status but cannot change settings.
  `ControlUsername` also works.

Yellow means downloads are paused. Failures in history are listed but don't change the colour,
because NZBGet keeps old history entries.
