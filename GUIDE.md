# Antigravity IDE — Corporate Network & TLS Fingerprint Fix
### Complete guide: what broke, why, how it's fixed, and how to maintain it

---

## 1. The Original Problem

Antigravity IDE's AI agent backend is **not** the Electron app itself — it's a separate
Go binary (`language_server_linux_x64`) that Electron spawns as a child process.
This Go binary opens its own raw TLS sockets directly to Google's Cloud Code API
(`cloudcode-pa.googleapis.com`, `daily-cloudcode-pa.googleapis.com`), and it does this
completely independently of:

- OS-level `http_proxy` / `https_proxy` environment variables
- Antigravity's own in-app proxy settings (`settings.json`)
- Chromium's `--proxy-server` flag

So no amount of app-level or OS-level proxy configuration touches it.

## 2. Two Separate Root Causes (both needed fixing)

### Cause A — Outdated app version (red herring, fixed for free)
Early troubleshooting kept hitting `CERT_HAS_EXPIRED` errors. Eventually traced to
running the **old apt-installed build (v1.23.2)** instead of the current, correct
install in `~/Downloads/Antigravity` (v1.107.0). Two separate Antigravity installs
existed on the machine; switching to the right binary alone fixed a chunk of the
symptoms that looked like a network problem but weren't.

### Cause B — TLS fingerprint filtering by the campus network (the real core issue)
Confirmed via packet capture (`tcpdump` + `tshark`):

1. TCP handshake to Google's IPs completes normally (SYN → SYN-ACK → ACK).
2. The Go binary sends its TLS ClientHello (~1500+ bytes — Go's `crypto/tls`
   produces a distinctly large, non-browser-like handshake).
3. The network silently swallows everything after that — no Server Hello, no RST,
   no error. Just a hang until timeout.
4. Meanwhile, `curl`/Chrome (OpenSSL-based, common ~200–500 byte ClientHello) sail
   through untouched, at the same IPs, same port, same moment.

This is the signature of **JA3-style TLS fingerprint filtering**: the firewall
allows "normal browser-looking" HTTPS and silently black-holes anything with an
unrecognized client fingerprint — common at institutions to block custom
VPN/tunnel clients that hide inside port 443.

Separately, this network also requires a corporate HTTP proxy
(`172.31.2.4:8080`) for general internet access — a second, independent
requirement layered on top of the fingerprinting issue.

## 3. Every Earlier Attempt, and Why Each One Failed

| Attempt | What it did | Why it failed |
|---|---|---|
| Wrapper scripts / `settings.json` | Set standard proxy env vars, edited app config | Go binary ignores both entirely |
| Mihomo (Clash) TUN + fake-IP DNS | Kernel-level traffic interception | Hijacked UDP/53; proxy rejected UDP, killed all internet |
| Redsocks + iptables | Transparent TCP redirect to proxy | Operates post-DNS, sent raw IPs; proxy required domain names |
| Proxychains4 + LD_PRELOAD | Hooked Electron's socket calls | Hijacked local IPC/MCP loopback traffic too; unrelated cert error from stale system clock/old app version muddied diagnosis |
| Linux network namespaces | Isolated the IDE process | Stripped `DBUS_SESSION_BUS_ADDRESS`; broke GNOME Keyring, caused logouts |
| **mitmdump local TLS re-terminator** ✅ | See below | **This is what actually worked** |

## 4. The Actual Fix: mitmdump as a Local TLS Re-Terminator

**mitmdump** (from the `mitmproxy` toolkit) sits locally between the Go binary and
the network. It terminates the Go binary's connection and **re-initiates the
outbound TLS handshake itself**, using its own TLS stack — one with a normal,
non-flagged fingerprint. This solves both root causes in one stroke:

```
Go binary (language_server_linux_x64)
        │
        │  (forced via iptables tproxy redirect + patched spawn() env vars)
        ▼
  mitmdump — 127.0.0.1:8081
        │
        │  re-encrypts with mitmdump's own normal-looking TLS handshake
        ▼
  ┌─────────────┴─────────────┐
  │                           │
On college network:      On hotspot/home:
→ forwards to             → connects directly
  172.31.2.4:8080            to the internet
  (corp proxy)
```

Because mitmdump does the actual handshake with the outside world, the campus
firewall sees a normal-fingerprint TLS connection and lets it through — the Go
binary's "suspicious" handshake never leaves the loopback interface.

### Two mechanisms feed traffic into mitmdump (found to be redundant, kept anyway since both work)
1. **iptables `REDIRECT`/tproxy rules** — transparently redirect all outbound
   traffic to Google's IP ranges (`172.217.0.0/16`, `142.250.0.0/15`,
   `142.251.0.0/16`) on port 443 into `127.0.0.1:8081`, excluding your own UID
   to avoid a redirect loop. *(These pre-existed from an earlier session; left
   in place since removing them risks breaking the working setup.)*
2. **Patched `child_process.spawn()`** inside Antigravity's own `main.js` —
   forces the Go binary's environment to include `HTTP_PROXY`,
   `HTTPS_PROXY=http://127.0.0.1:8081`, and `SSL_CERT_FILE` pointing at
   mitmdump's local CA cert.

### Network-aware switching (college proxy vs. hotspot)
A wrapper script checks whether the corp proxy (`172.31.2.4:8080`) is reachable
before starting mitmdump each time:
- **Reachable** → `mitmdump --mode upstream:http://172.31.2.4:8080 -p 8081`
- **Not reachable** → `mitmdump --mode regular -p 8081` (direct to internet)

This runs as a `systemd --user` service so it's always active, auto-restarts if
it crashes, and re-evaluates the network on every restart.

## 5. Files Created / Modified

| Path | Purpose |
|---|---|
| `~/Downloads/Antigravity/resources/app/out/main.js` | **Modified** — injected a `child_process.spawn` monkey-patch forcing the Go binary's proxy env vars |
| `~/Downloads/Antigravity/resources/app/out/main.js.backup` | Pre-patch backup — restore this if an Antigravity auto-update breaks things and you need to compare/reapply |
| `~/Downloads/Antigravity/resources/app/out/bootstrap-fork.js.backup` | Same, for the fork bootstrap file |
| `~/patch_spawn_esm_tls.js` | The patch script itself — **rerun this after every Antigravity update**, since updates overwrite `main.js` |
| `~/.local/bin/mitmdump-smart-start` | Detects corp-proxy vs. direct network; launches mitmdump in the right mode; writes mode to `/tmp/mitmdump-mode.status` |
| `~/.config/systemd/user/mitmdump-antigravity.service` | Runs `mitmdump-smart-start` persistently, auto-restarts on failure |
| `/etc/NetworkManager/dispatcher.d/99-mitmdump-restart` | Auto-restarts the mitmdump service whenever you connect to a new network |
| `~/.local/bin/antigravity-launch` | Launcher wrapper: sets `HTTP_PROXY`/`HTTPS_PROXY`/`SSL_CERT_FILE`, then starts Antigravity |
| `~/.local/bin/antigravity-tray.py` | GUI tray indicator (top bar): shows service status + current mode, lets you restart/launch/view logs |
| `~/.config/autostart/antigravity-tray.desktop` | Auto-starts the tray icon on login |
| `~/.mitmproxy/mitmproxy-ca-cert.pem` (+ `.cer`, `.p12`) | Local CA mitmdump uses to re-sign intercepted traffic |
| `/tmp/mitmdump.log` | Live traffic log (rotated via logrotate, see below) |
| `/tmp/mitmdump-mode.status` | One-word file (`college` / `direct`) the tray reads for its "Mode" display |
| `/etc/logrotate.d/mitmdump-antigravity` | Caps `/tmp/mitmdump.log` at 5MB, keeps 2 rotations, so the tray's mode detection never gets buried under traffic noise again |

### Settings changed
- GNOME system proxy (`gsettings org.gnome.system.proxy`) — set to `manual`,
  pointing at the corp proxy, during early troubleshooting. Currently harmless
  since nothing in the working setup depends on it, but if browsing outside
  Antigravity ever misbehaves on the college network, check this.
- `ubuntu-appindicators@ubuntu.com` GNOME Shell extension — enabled (was
  present but inactive by default), required for the tray icon to render.

## 6. Packages Installed / Removed

**Installed (in active use):**
- `mitmproxy` (provides `mitmdump`) — core of the fix
- `python3-gi`, `gir1.2-appindicator3-0.1`, `gir1.2-notify-0.7` — tray icon GUI
- `logrotate` — keeps the traffic log from growing forever

**Removed (dead ends from earlier failed attempts, confirmed unused):**
- `mihomo` binary (`/usr/local/bin/mihomo`) — TUN-mode attempt, abandoned
- `redsocks` — transparent-redirect attempt, abandoned
- `proxychains4` / `libproxychains4` — `LD_PRELOAD` attempt, abandoned
- `~/.local/bin/antigravity-proxy` custom script — only ever edited
  `settings.json`, which the Go binary ignores; functionally dead

## 7. How It Works Day-to-Day

1. On login: `mitmdump-antigravity.service` and the tray icon both auto-start.
2. The service checks if `172.31.2.4:8080` is reachable right now.
   - Yes → mitmdump forwards through it (**college mode**)
   - No → mitmdump connects directly (**hotspot/home mode**)
3. You launch Antigravity via `antigravity-launch` (or the tray menu's
   "Launch Antigravity"), which sets the proxy env vars before starting it.
4. The patched `main.js` forces the Go language-server child process
   specifically onto those same env vars (it wouldn't inherit/use them
   otherwise).
5. **When you switch networks:** either reconnect Wi-Fi (the NetworkManager
   dispatcher auto-restarts the service), or manually run:
   ```bash
   systemctl --user restart mitmdump-antigravity.service
   ```
6. Click the tray icon any time to see live status ("Service: Running",
   "Mode: College (via corp proxy)" / "Direct (hotspot/home)"), restart the
   service, launch Antigravity, or tail the logs — all without a terminal.

## 8. Maintenance — What Will Break and How to Fix It

- **After every Antigravity auto-update:** the patch inside `main.js` gets
  wiped, since the updater replaces that file wholesale.
  Symptom: `CERT_HAS_EXPIRED` / `Heartbeat error` returns.
  Fix: `node ~/patch_spawn_esm_tls.js`, then relaunch.

- **"Address already in use" crash-loop on the systemd service:**
  Happened once already — an orphaned manual `mitmdump` process (started
  during testing) held port 8081 forever, while the systemd service kept
  trying and failing to bind, restarting every 3 seconds indefinitely.
  Diagnose: `sudo lsof -i :8081` — if you see a PID that *isn't* the current
  active systemd unit's Main PID, kill it:
  ```bash
  sudo kill -9 <stray_pid>
  systemctl --user reset-failed mitmdump-antigravity.service
  systemctl --user restart mitmdump-antigravity.service
  ```

- **Tray shows "Mode: Unknown":** means `/tmp/mitmdump-mode.status` is
  missing or stale. Restart the service to regenerate it:
  ```bash
  systemctl --user restart mitmdump-antigravity.service
  cat /tmp/mitmdump-mode.status
  ```

## 9. Quick Reference — Useful Commands

```bash
# Check everything's healthy
systemctl --user status mitmdump-antigravity.service --no-pager
sudo lsof -i :8081
cat /tmp/mitmdump-mode.status

# Force a network re-check right now
systemctl --user restart mitmdump-antigravity.service

# Launch Antigravity correctly
antigravity-launch
# — or click "Launch Antigravity" in the tray icon menu

# Watch live proxy traffic
tail -f /tmp/mitmdump.log

# Re-apply the main.js patch after an Antigravity update
node ~/patch_spawn_esm_tls.js
```
