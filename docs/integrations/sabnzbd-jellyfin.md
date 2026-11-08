# SABnzbd and Jellyfin

Both are read-only: the Hub never pauses, deletes, or changes anything.

## SABnzbd

Shows download speed (or "Paused"), the queue with progress, the last few failed downloads, and SABnzbd's warnings.

1. In SABnzbd: **Config (⚙) → General → Security → API Key**. Use the **API Key**, not the *NZB Key*. The NZB key can only add downloads and can't read the queue.
2. In the Hub: **Add service → SABnzbd**. URL is the address you open in the browser, e.g. `http://192.168.1.10:8080` (plus `/sabnzbd` if you use a URL base).

| Colour | Meaning |
|---|---|
| Green | Downloading or idle, no warnings |
| Yellow | Paused, or SABnzbd has warnings (e.g. a news server failing) |
| Red | Unreachable or wrong API key |

> [!NOTE]
> SABnzbd's API takes the key as a URL parameter. The Hub never shows request URLs in error messages,
> and it scrubs any saved secret from messages as an extra safeguard.

SABnzbd keeps warnings until you clear them in its UI (**Status → Warnings**), so a yellow dot can come from an old warning.

## Jellyfin

Shows who is watching what (user, device, progress, direct play vs. transcode) and library counts.

1. In Jellyfin (as an admin): **Dashboard → API Keys → +**, and name it e.g. `Homelab Hub`.
2. In the Hub: **Add service → Jellyfin**. URL e.g. `http://192.168.1.10:8096`.

> [!NOTE]
> Jellyfin API keys have admin-level access. Prefer the LAN address over a public hostname, and keep the Hub on your LAN/VPN.
