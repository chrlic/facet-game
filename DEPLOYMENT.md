# Deployment guide — FACET / BACKBONE game server

A runbook for running the server on a Linux host behind nginx (with a valid
public TLS certificate), either as a **Docker container** or a **systemd
service**. Both paths end at the same place: the Python app listening on a
local port, nginx terminating TLS and proxying to it.

```
   Internet ──HTTPS──> nginx (TLS, rate limit) ──HTTP──> app (127.0.0.1:8080)
                                                            │
                                                            └── SQLite file (persistent volume/dir)
```

The app is stdlib-only Python 3.10+ — no pip dependencies. State lives in a
single SQLite file; nothing else is persistent.

---

## 1. Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port the app listens on. |
| `HOST` | `0.0.0.0` | Bind address. Set `127.0.0.1` for a systemd service so the app port isn't publicly reachable. Leave default in Docker. |
| `FACET_DB` | `./facet.db` | SQLite file path. **Point this at a persistent volume/dir.** |
| `FACET_TRUST_PROXY` | off | Set to `1` behind nginx so per-IP rate limits read the forwarded client IP. **Required for correct rate limiting.** |
| `FACET_ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins allowed to call the API cross-origin. Leave empty — the SPA is same-origin. |
| `FACET_ADMIN` | *(none)* | Name of a **registered** account to auto-grant admin on startup. |
| `FACET_AI_RATE` | `30` | Max AI-move requests per user per minute. |
| `FACET_ACTION_RATE` | `30` | Max game/seek creations per user per minute. |
| `FACET_MOVE_SECONDS` | `259200` (3 d) | PvP move allowance before forfeit. |
| `FACET_AI_ABANDON_SECONDS` | `604800` (7 d) | Idle AI games cleaned up after this. |
| `FACET_SWEEP_SECONDS` | `60` | Housekeeping interval (forfeits, expiries, cache prune). |
| `PYTHONUNBUFFERED` | — | Set `1` so logs (requests, rate-limit hits, errors) flush live. |

Security-relevant minimum behind nginx: **`FACET_TRUST_PROXY=1`**,
**`FACET_DB` on persistent storage**, and `PYTHONUNBUFFERED=1` for visible logs.

---

## 2. Option A — Docker container

The included `Dockerfile` already sets `PYTHONUNBUFFERED=1` and
`FACET_TRUST_PROXY=1` and copies all required modules.

**Build:**
```bash
docker build -t facet-server .
```

**Run** (publish only to localhost so nginx on the host reaches it, and mount a
volume for the DB):
```bash
docker run -d --name facet \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v /srv/facet-data:/data \
  -e PORT=8080 \
  -e FACET_DB=/data/facet.db \
  facet-server
```

`-p 127.0.0.1:8080:8080` binds the published port to loopback only, so the
container is reachable by nginx on the same host but not from the internet.
`/srv/facet-data` on the host holds the SQLite file across container replacement.

**docker compose** equivalent:
```yaml
services:
  facet:
    build: .
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - /srv/facet-data:/data
    environment:
      PORT: "8080"
      FACET_DB: /data/facet.db
      # FACET_ADMIN: yourname   # after you register the account
```

**Logs:** `docker logs -f facet`

---

## 3. Option B — systemd service (no Docker)

Run the app directly on the host as an unprivileged user.

**Install the code and a data dir:**
```bash
sudo useradd --system --home /opt/facet --shell /usr/sbin/nologin facet
sudo mkdir -p /opt/facet /var/lib/facet
sudo cp -r facet_engine.py backbone_engine.py server.py service.py \
          storage.py manage.py docs/ /opt/facet/
sudo chown -R facet:facet /opt/facet /var/lib/facet
```

**Create `/etc/facet.env`:**
```ini
PORT=8080
HOST=127.0.0.1
FACET_DB=/var/lib/facet/facet.db
FACET_TRUST_PROXY=1
PYTHONUNBUFFERED=1
# FACET_ADMIN=yourname
```

**Create `/etc/systemd/system/facet.service`:**
```ini
[Unit]
Description=FACET / BACKBONE game server
After=network.target

[Service]
Type=simple
User=facet
Group=facet
WorkingDirectory=/opt/facet
EnvironmentFile=/etc/facet.env
ExecStart=/usr/bin/python3 server.py
Restart=on-failure
RestartSec=3

# hardening (the app only needs to read its code and write its DB dir)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/facet
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now facet
sudo systemctl status facet
journalctl -u facet -f          # live logs
```

With `HOST=127.0.0.1` the app port is loopback-only — nginx on the same host
reaches it, the internet cannot.

---

## 4. nginx + TLS

Use the provided [`nginx.sample.conf`](nginx.sample.conf) — copy it to
`/etc/nginx/sites-available/facet` (or `conf.d/facet.conf`), edit the
`server_name` and certificate paths, and reload. The two `limit_*_zone` lines
go in the `http{}` context.

The non-negotiable line is `proxy_set_header X-Real-IP $remote_addr;` — without
it the app can't see real client IPs and per-IP rate limiting collapses to one
bucket.

**TLS certificate** (Let's Encrypt example):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d games.example.com
```
certbot writes the cert paths and a renewal timer automatically. If you already
have a commercial cert, just point `ssl_certificate` / `ssl_certificate_key` at
its `fullchain.pem` and `privkey.pem`.

**Reload nginx:**
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 5. First admin account

Admin is granted to an existing **registered** (non-guest) account:

1. Open the site, register an account through the UI.
2. Grant admin one of two ways:
   - **Env:** set `FACET_ADMIN=yourname` and restart the service/container, or
   - **CLI:** run manage.py against the same DB:
     ```bash
     # Docker:
     docker exec facet python3 manage.py make-admin yourname
     # systemd:
     sudo -u facet FACET_DB=/var/lib/facet/facet.db \
       python3 /opt/facet/manage.py make-admin yourname
     ```
3. `/admin.html` is now available to that account.

`manage.py` is safe to run while the server is up (SQLite WAL). Other commands:
`list-players [query]`, `reset-password <name>`, `stats`.

---

## 6. Persistence & backups

Everything is in the one SQLite file (`FACET_DB`). Games are stored as move
logs and replayed by the deterministic engine, so this file *is* the whole
server state. Back it up with SQLite's online backup (safe while running):

```bash
# Docker:
docker exec facet sh -c 'sqlite3 /data/facet.db ".backup /data/backup-$(date +%F).db"'
# systemd:
sudo -u facet sqlite3 /var/lib/facet/facet.db \
  ".backup /var/lib/facet/backup-$(date +%F).db"
```

Then copy the backup off-box. A nightly cron/systemd-timer doing this is
plenty at this scale. Do **not** just `cp` the live `.db` while running — use
`.backup` so WAL state is consistent.

---

## 7. Upgrades / redeploys

The DB schema self-migrates on startup (`init_db` runs idempotent
`CREATE TABLE IF NOT EXISTS` + column migrations), so upgrades are just
"replace code, restart."

- **Docker:** `docker build -t facet-server . && docker rm -f facet && docker run …`
  (same run command). The volume keeps the DB.
- **systemd:** copy new files into `/opt/facet`, then `sudo systemctl restart facet`.

Client-side, the PWA service worker is network-first, so browsers pick up new
frontend code on their next online load. The GitHub Pages `pages.yml` workflow
stamps a fresh service-worker cache version on deploy; if you deploy the
frontend some other way, no action is needed for the API server.

---

## 8. Monitoring & health

- **Health check:** `GET /api/v1/boards` returns `200` with a JSON board list
  and needs no auth — use it as a liveness probe.
- **Admin stats:** `/admin.html` or `manage.py stats` (players, active games,
  moves, sessions).
- **Logs:** request lines, rate-limit `429`s, and tracebacks go to stdout
  (`docker logs` / `journalctl -u facet`). 500s log a full traceback server-side
  but return only `{"error":"internal error"}` to clients.

---

## 9. Sizing recap

Memory is trivial (~9 MB base + ~12 KB per active game). The only real
constraint is CPU for FACET **"hard"** AI (up to 2.5 s of pure-Python,
GIL-bound work per move) — one process ≈ one core regardless of threads.

- Defaulting AI to **"normal"**: a **2 vCPU / 1 GB** host handles ~100 concurrent
  users (≈⅓ AI, ⅔ PvP) comfortably.
- If **"hard"** AI is heavily used: run **multiple app processes** (they share
  the one SQLite file fine at this write volume — start N containers/services on
  different `PORT`s and list them all in an nginx `upstream`), or move the AI
  search to a process pool. Budget ~one core per concurrent hard-AI move; ~4
  vCPU / 4 processes for this mix with headroom.

`FACET_AI_RATE` caps how much AI CPU any single user can pull — lower it to
tighten the bound.

For the full security audit and measurements behind these numbers, see the
notes referenced in the project history.
