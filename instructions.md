# POCUS-Health — Phone ↔ Desktop Web Demo (WebRTC + Fallback WS)

This repo is a reference implementation for “pair a phone with a desktop web app” using:
- Desktop web app shows a QR code (pairing link)
- Phone opens the link and streams sensor + touch/controller data
- Desktop receives and visualizes it in real-time
- Primary transport: **WebRTC DataChannel**
- Fallback transport: **WebSocket relay** via the same server

The backend is **FastAPI (ASGI)** and everything runs via **Docker + docker-compose** on a single Linode. **Caddy** terminates TLS and reverse-proxies to the app.

---

## Goals

- One Linode does:
  - HTTPS (Caddy)
  - Static hosting (desktop app + phone page)
  - Signaling server (WebSocket)
  - Optional fallback transport (WebSocket data messages when WebRTC fails)
- Pairing is quick and safe:
  - Desktop creates session `{sessionId, token}`
  - QR encodes a phone URL containing sessionId + token
- Streaming design:
  - **“Latest state wins”** updates (orientation / gyro / accel) rather than reliable event logs
  - WebRTC DataChannel config for sensor streams:
    - `ordered: false`
    - `maxRetransmits: 0`
  - (Optional) keep reliable channel for discrete events like “button press” / “tap”

---

## Repo Layout

Recommended structure:

pocus-health/
backend/
app/
main.py
signaling.py
sessions.py
static/
desktop/ # built desktop bundle
phone/ # built phone bundle
pyproject.toml / requirements.txt
Dockerfile
web/
desktop/ # desktop web app source (vanilla HTML/JS/CSS)
phone/ # phone web app source (vanilla HTML/JS/CSS)
deploy/
Caddyfile
docker-compose.yml
.github/
workflows/
deploy-dev.yml
deploy-master.yml
deploy-feature.yml
instructions.md
README.md


Notes:
- `backend/static/*` is where web assets end up (CI can build them and copy in, or the backend container can build them in a multi-stage Dockerfile).
- Keep the runtime containers minimal: build artifacts in CI or build stage, serve static from backend container or Caddy.

---

## Local Dev Prereqs

- VSCode
- Docker Desktop (or Docker Engine)
- docker-compose

---

## Local Dev: Quick Start

### 1) Start everything
From repo root:

```bash
docker compose -f deploy/docker-compose.yml up --build


Then open:

Desktop app: http://localhost/

Phone page (normally via QR): http://localhost/m/<sessionId>

In local dev, you may skip TLS. WebRTC works best on HTTPS, but localhost is usually allowed.

2) Dev workflow (fast iteration)

Typical:

Run backend via docker

Run desktop + phone dev servers on host (python) and point backend to them

If you want pure-container dev, you can add “dev” services to compose (not required for MVP).

System Overview
HTTP routes (backend)

GET / → desktop web app (static)

GET /m/{sessionId} → phone web app (static)

POST /api/session → create session (returns sessionId + token + phoneUrl)

GET /api/session/{sessionId} → optional status/presence

WebSocket signaling

GET /ws → WebSocket endpoint

Clients connect and send a hello:

Desktop:

{ "type":"hello", "role":"desktop", "sessionId":"...", "token":"..." }


Phone:

{ "type":"hello", "role":"phone", "sessionId":"...", "token":"..." }


Server validates token and pairs sockets in that session, then relays messages:

offer, answer, ice

bye, error, ping

Transport strategy

Desktop creates session and waits

Phone joins via QR link

Server relays WebRTC offer/answer/ICE over WS

Once DataChannel opens, phone streams sensor/touch data over DataChannel

If DataChannel fails or closes, fallback to WS using the same message schema

DataChannel Configuration (Sensor Streams)

For high-rate sensor streams (orientation/gyro/accel), use:

    ordered: false

    maxRetransmits: 0

This yields unordered + unreliable delivery (low latency; drops are fine). Your application logic should use “latest state wins” semantics:

Each sensor packet includes:

t (timestamp, ms)

seq (monotonic sequence number)

Desktop keeps only the most recent seq per stream and ignores older ones.

Recommended:

One DataChannel dedicated to sensor stream (unreliable)

Optionally, a second reliable channel for discrete events:

ordered: true (default)

no maxRetransmits constraint

If you only want one channel for MVP, use unreliable and accept that discrete events might drop (or repeat them a couple times client-side).

Message Schema (Shared Across Transports)

Keep payloads identical whether they go via:

WebRTC DataChannel

WebSocket fallback

Sensor update
{
  "type": "sensor",
  "t": 1700000000000,
  "seq": 12345,
  "orientation": { "alpha": 10.1, "beta": -2.3, "gamma": 45.0 },
  "gyro": { "x": 0.01, "y": -0.02, "z": 0.00 },
  "accel": { "x": 0.1, "y": 0.0, "z": 9.7 }
}


iOS Motion Permission Notes

On iOS Safari:

Motion sensors require a user gesture (tap) to request permission.

Phone UI should show a big “Enable Motion” button on first load.

Don’t start streaming until permission is granted.

Docker + Compose (Production)
Containers

caddy: TLS + reverse proxy

backend: FastAPI (Uvicorn) + static assets + WS signaling

deploy/docker-compose.yml (concept)

Expose ports 80/443 via Caddy

Backend listens on internal port (e.g. 8000)

Caddy proxies /ws with websocket upgrade

Caddy (TLS + Reverse Proxy)

deploy/Caddyfile should roughly:

Serve HTTPS for your domain

Reverse proxy:

/* → backend (which serves static + API)

/ws → backend (websocket upgrade)

Caddy automatically handles websocket upgrade when reverse_proxy is used.

Security (MVP-level, still important)

Each session has:

sessionId (unguessable)

token (secret)

Server only pairs phone+desktop if token matches.

Sessions expire (TTL), e.g. 10 minutes since creation or 2 minutes since last presence.

Optional: rate limit session creation endpoints on the server and/or Caddy.

Git Workflow + Branching Model

You will use:

master — production

dev — staging

feature/* — ephemeral preview (optional: deploy to a subdomain or a different path)

Suggested:

PRs go into dev

Promote dev → master via PR when stable

CI/CD: GitHub Actions Deploy to Linode
Deployment approach

GitHub Actions:

builds images (or builds web assets)

ships the repo (or build artifacts) to Linode via SSH

runs docker compose pull && docker compose up -d --build

Linode runs docker/docker-compose and persists volumes if needed.

Linode prerequisites

On your Linode:

Docker + docker-compose installed

A deploy directory, e.g. /opt/pocus-health

SSH access for a deploy user (recommended: non-root, in docker group)

Caddy run inside docker

GitHub Secrets you must set

In your GitHub repo settings → Secrets and variables → Actions:

    LINODE_HOST = your.server.ip.or.hostname

    LINODE_USER = deploy (or your chosen user)

    LINODE_SSH_KEY = private SSH key for deploy user

    LINODE_KNOWN_HOSTS = output of ssh-keyscan -H <host>

    POCUS_DOMAIN = demo.yourdomain.com (if needed by compose/Caddy)

Any additional env vars (TURN creds later, etc.)

Prefer a dedicated SSH key for GitHub Actions deploy.

Environments / Targets

A simple mapping:

feature/* → preview deployment

Option A: deploy to same Linode under a distinct path prefix

Option B: deploy to a preview subdomain (requires DNS wildcard and Caddy routing)

Option C: don’t auto-deploy feature branches (still run CI checks)

dev → staging

e.g. staging.pocus-health.yourdomain.com

master → production

e.g. pocus-health.yourdomain.com

If you want to keep one Linode and one domain initially:

deploy dev to https://<domain>/staging (lets do this)

deploy master to https://<domain>/

(That’s easiest; add subdomains later.)

GitHub Actions: What to Include

You want three workflow files:

1) deploy-master.yml

    Trigger:

    push to master

    Steps:

    checkout

    build web assets (desktop + phone), no build with vanilla HTML

    build backend image (optional)

    ssh into Linode:

    git pull or rsync repo

    docker compose up -d --build

    prune old images (optional)

2) deploy-dev.yml

Trigger:

push to dev

Same as master, but uses staging compose override or different env variables.

3) deploy-feature.yml

Trigger:

push to feature/**

Option A (recommended MVP): run CI only (lint/test/build) but do not deploy
Option B: deploy to a preview path (more work; do later)

Docker Compose: Multiple Environments (Recommended)

Use:

deploy/docker-compose.yml (base)

deploy/docker-compose.dev.yml (staging overrides)

deploy/docker-compose.prod.yml (prod overrides)

So deploy commands are:

Staging:

docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build


Prod:

docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build

Minimal Backend Responsibilities (Implementation Checklist)

    POST /api/session

        generate sessionId, token

        store in memory with TTL

        return JSON including phoneUrl

    GET /ws WebSocket

        accept

        require hello message within N seconds

        validate token + role

        pair sockets inside session

        relay signaling messages

        optionally relay fallback data messages

    TTL cleanup task

        run every 30–60s

        expire old sessions

    Disconnect handling

        if phone disconnects: notify desktop

        if desktop disconnects: notify phone

Web Apps (Desktop + Phone) Implementation Checklist
Desktop

    “Create session” button calls /api/session

    show QR with phoneUrl

    open WebSocket, send hello

    create RTCPeerConnection

    create DataChannel (unreliable sensor)

    send offer over WS; receive answer; handle ICE

    on DataChannel message: update visualization (“latest state wins”)

    detect DataChannel failure and allow WS fallback

Phone

    parse sessionId + token from URL

    big “Enable Motion” button (iOS)

    open WebSocket, send hello

    wait for offer; set remote; create answer; return over WS; handle ICE

    when DataChannel opens: start streaming at fixed rate (e.g. 30–60Hz)

    if DataChannel not available: stream over WS fallback at reduced rate (e.g. 15–30Hz)

    include seq and t on packets

Performance Notes

    Sensor streaming at 60Hz is often fine.

    Consider sending a compact subset:

        orientation + gyro OR orientation + accel

    Use a fixed packet rate (e.g. 30Hz) to avoid flooding slower clients.

    The unreliable channel means drops happen; that’s expected.

Future Enhancements (Not Required for MVP)

    TURN integration (coturn or managed TURN)

    Multi-instance scaling (Redis session store)

    Auth/billing/quotas

    Telemetry: connection success rate, TURN usage, time-to-connect, disconnect reasons

VSCode Setup (Recommended)

    Use Dev Containers (optional) or normal workspace

    Add .vscode/launch.json for backend debugging

    Add formatting:

        Python: ruff/black

        JS/TS: eslint/prettier

Definition of Done (MVP)

    Desktop loads over HTTPS on Linode

    Desktop creates session, shows QR

    Phone scans QR, grants sensor permission

    DataChannel connects and streams

    Desktop responds visually in real time

    If WebRTC fails, WS fallback still streams (at least basic sensor updates)

    CI deploys dev and master via GitHub Actions automatically