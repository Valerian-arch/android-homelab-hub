# Setup guide

This guide goes from nothing to your homelab on your phone in about 15 minutes.

**You need:**
- A machine that runs **Docker** (a VM, LXC, NAS, or Raspberry Pi; `amd64` and `arm64` images are published).
- An **Android phone** (Android 8.0 or newer) that can reach that machine, on your home Wi-Fi or over a VPN such as Tailscale or WireGuard.

> [!IMPORTANT]
> The Hub holds API keys for your services. Keep it on your LAN or VPN. **Do not port-forward it or publish it to the internet.**

---

## 1. Run the Hub

### Create the data folder

The Hub stores its database (`hub.db`, with encrypted credentials) and its encryption key (`secret.key`) in one folder.
It runs as an unprivileged user (UID 10001), so create the folder with that owner:

```sh
sudo mkdir -p /opt/homelab-hub
sudo chown 10001:10001 /opt/homelab-hub
sudo chmod 700 /opt/homelab-hub
```

Use any path you like; just use the same one in the compose file below.

### Start the container

Paste this into **Dockge** or **Portainer**, or save it as `compose.yaml` and run `docker compose up -d`:

```yaml
services:
  homelab-hub:
    image: ghcr.io/valerian-arch/android-homelab-hub:latest
    container_name: homelab-hub
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      HUB_POLL_INTERVAL: "60"      # seconds between status checks
      HUB_SECURE_COOKIES: "false"  # "true" if you put HTTPS in front of the Hub
    volumes:
      - /opt/homelab-hub:/data     # the folder from the previous step
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    mem_limit: 512m
    pids_limit: 200
```

A fully commented version is in [`server/docker-compose.example.yml`](../server/docker-compose.example.yml).

## 2. First login

1. Open the container's **logs** (Dockge: the stack's log view; or `docker logs homelab-hub`). On first start you'll see:

   ```
   ================================================================
     Homelab Hub: first start

     Admin password:  xxxxxxxxxxxxxxxx
   ```

2. Open `http://<your-server-ip>:8080` and log in with that password.
3. Choose your own password (12+ characters).
4. You'll get **5 recovery codes**. **Save them in your password manager.** Each one can reset a forgotten password once.

## 3. Add your services

Click **+ Add service** and pick a type:

| Type | Use it for | Setup notes |
|---|---|---|
| **HTTP(S) check** | Any web app | Up/down, response time |
| **TCP port check** | SSH, databases, devices without a web page | Up/down |
| **Proxmox VE** | Nodes, VMs, LXCs with CPU/RAM | [proxmox.md](integrations/proxmox.md) (read-only token) |
| **Sonarr / Radarr / Prowlarr** | Queue, upcoming, health, indexers | [arr.md](integrations/arr.md) |
| **SABnzbd / NZBGet / qBittorrent / qui** | Download speed, queue, failures | [downloaders.md](integrations/downloaders.md), [sabnzbd-jellyfin.md](integrations/sabnzbd-jellyfin.md) |
| **Jellyfin** | Who's watching, library size | [sabnzbd-jellyfin.md](integrations/sabnzbd-jellyfin.md) |

Tips:
- **Category** groups services on the phone (e.g. *Media*, *Infrastructure*). Pick an existing one from the dropdown or add a new one.
- **Link URL** is what opens when you tap the service in the app.
- Use **read-only** credentials wherever a service offers them (e.g. Proxmox `PVEAuditor`).
- API keys and passwords are encrypted on the Hub and **never shown again**, not even to you. To change one, type a new value.

## 4. Install the app

1. On your phone, open the **[latest release](https://github.com/Valerian-arch/android-homelab-hub/releases/latest)** and download `homelab-hub-<version>.apk`.
2. Open the file and tap **Install**. Android will ask you to allow **"Install unknown apps"** for your browser or file manager. Play Protect may warn about an unknown app; choose **Install anyway**.
3. *(Optional)* Compare the file with the `.sha256` checksum published next to it.

The app asks for **Camera** only to scan the pairing QR code. It needs no Google services and works on de-Googled phones too.

## 5. Pair your phone

1. On the Hub, open **Phones**. Check that **Hub address for the phone** is an address your phone can reach (your server's LAN IP, or its VPN/Tailscale address). `127.0.0.1` or `localhost` won't work.
2. Click **Create pairing code**. A QR code and an 8-character code appear. They work once and expire after 10 minutes.
3. In the app, tap **Scan QR code** (or type the address and code).

That's it: your dashboard appears and refreshes every minute while the app is open.

Each phone gets its own token. Lost a phone? **Phones → Remove** on the Hub, and its token stops working immediately.

## 6. Access from outside your home

Use a VPN. Don't open ports. Two common options:

- **Tailscale:** install it on the Hub's machine, or advertise your home subnet from any Tailscale device (a "subnet router"). Install Tailscale on your phone and use the same Hub address.
- **WireGuard** or your router's VPN: connect, then use the Hub's LAN address.

Over plain `http://` the app shows a small "not encrypted" note. Inside a VPN tunnel the traffic is already encrypted.
To use HTTPS anyway, put a reverse proxy (Caddy, Nginx Proxy Manager, `tailscale serve`) in front and set `HUB_SECURE_COOKIES: "true"`.

## Updating

- **Hub:** pull the new image (Dockge: **Update**; or `docker compose pull && docker compose up -d`). Your data folder is kept.
- **App:** install the newer APK from Releases over the old one. You stay paired.

## Backups

Back up **both** files in the data folder together:

- `hub.db`: services, encrypted credentials, paired phones
- `secret.key`: the key that decrypts the credentials

Without `secret.key`, the saved API keys can't be decrypted and you'd have to re-enter them. Keep backups private.

## Troubleshooting

| Problem | Fix |
|---|---|
| Forgot the admin password | Login page → **Forgot password?** → use a recovery code |
| Lost password **and** recovery codes | On the server: `docker exec -it homelab-hub python -m app.admin_cli reset-password` |
| "Too many failed attempts" | 3 wrong passwords lock that device out for 15 minutes. Wait. |
| Container restarts / `Permission denied` on `/data` | The data folder must be owned by UID 10001: `sudo chown 10001:10001 /path/to/data` |
| Phone: "Can't reach …" | Is the phone on your Wi-Fi or VPN? Does the Hub address on the Phones page match what the phone can reach? |
| Phone: "Invalid or expired pairing code" | Codes last 10 minutes and work once. Create a new one. |
| App: "This phone was removed on the Hub" | It was removed under **Phones**, or the Hub's data was reset. Pair again. |
| A service is red | Open it on the Hub's admin page; the message says why (wrong key, timeout, wrong port…). Click **Test** after fixing. |
| A service is yellow | Reachable, but it reports a warning (health issue, failing indexer, paused downloads…). Expand its details. |
| Proxmox shows nodes but no VMs | The token lacks permission. See "Privilege Separation" in [proxmox.md](integrations/proxmox.md). |
