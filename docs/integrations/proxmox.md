# Proxmox VE integration

Shows every node and every VM/LXC in a cluster, with status, CPU, and RAM.
One Hub entry covers the whole cluster, because any node answers for all of them.

The Hub only **reads** data (`GET /api2/json/cluster/resources`). It never changes anything.

## 1. Create a read-only API token

In the Proxmox web UI, go to **Datacenter → Permissions**.

1. **Users → Add**
   - User name: `homelab-hub`, Realm: **Proxmox VE authentication server** (`pve`)
   - User names are **case-sensitive**. Whatever you type here becomes part of the token ID.
2. **API Tokens → Add**
   - User: `homelab-hub@pve`, Token ID: `hub`
   - Copy the **secret** right away. Proxmox shows it only once. Store it in a password manager.
3. **Permissions → Add → User Permission**
   - Path `/`, User `homelab-hub@pve`, Role **PVEAuditor**, Propagate ✅
4. **If "Privilege Separation" was ticked on the token** (it is by default), also add:
   **Permissions → Add → API Token Permission**
   - Path `/`, API Token `homelab-hub@pve!hub`, Role **PVEAuditor**, Propagate ✅

> [!WARNING]
> **Privilege Separation:** with privilege separation on, a token can only do what **both** the user and the token
> are allowed to do. If you skip step 4, the Hub sees node names but no CPU/RAM and no guests,
> and shows a yellow "Limited data" warning.

**Check:** the **Permissions** table should list PVEAuditor on `/` for both the user and the token.

`PVEAuditor` is a built-in role. You don't need to create a role or a group.

## 2. Add it to the Hub

**Add service → Proxmox VE**

| Field | Value |
|---|---|
| Proxmox URL | Any node, e.g. `https://192.168.1.20:8006` |
| API token ID | `homelab-hub@pve!hub` (exactly as Proxmox shows it, including capitals) |
| API token secret | The secret from step 2 |
| Verify TLS certificate | Leave unticked unless you installed a trusted certificate on Proxmox |

## Troubleshooting

| What you see | Cause |
|---|---|
| `HTTP 401` | Wrong token ID or secret (check capitalization) |
| `HTTP 403` | Token has no permission on `/` |
| Yellow, "Limited data", 0 guests | Privilege Separation is on and the API Token Permission (step 4) is missing |
| `Connection failed: ... CERTIFICATE_VERIFY_FAILED` | Untick "Verify TLS certificate" or install a trusted certificate |
