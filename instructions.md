# POCUS-Health — Phone ↔ Desktop WebRTC Streaming

A full-stack application for pairing a phone with a desktop browser to control a 3D visualization using phone sensor data (gyroscope, accelerometer, orientation).

**Current Status:** Infrastructure complete. Skeleton deployed and working. Ready for frontend development.

---

## Quick Links

- **Production:** https://pocus.health
- **Dev:** https://dev.pocus.health
- **GitHub:** https://github.com/nstafford/POCUS-Health
- **Server:** Linode (Ubuntu) with Docker

---

## Architecture Overview

```
                          ┌─────────────────────────┐
                          │     Linode Server       │
                          │  (2x Isolated Stacks)   │
                          └────────┬────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
         (prod)      (dev isolated)
                │                  │                  │
        ┌───────┴────────┐  ┌──────┴─────────┐
        │   PROD STACK   │  │  DEV STACK     │
        │   (Port 80/   │  │  (Port 8001)   │
        │    443)        │  │                │
        │                │  │                │
        │ ┌────────────┐ │  │ ┌────────────┐│
        │ │   Caddy    │ │  │ │  Backend   ││
        │ │(Routes     │ │  │ │  (FastAPI) ││
        │ │pocus.health│ │  │ └────────────┘│
        │ │dev.pocus.. │ │  │                │
        │ └────────────┘ │  └────────────────┘
        │                │
        │ ┌────────────┐ │
        │ │   Backend  │ │
        │ │ (FastAPI)  │ │
        │ └────────────┘ │
        │                │
        └────────────────┘
```

**Prod (pocus.health):**
- Runs **Caddy** (TLS terminator) + **Backend** (FastAPI)
- Serves static frontend
- WebSocket signaling
- At `/opt/pocus-health` on server

**Dev (dev.pocus.health):**
- Runs **Backend only** on `127.0.0.1:8001`
- Prod **Caddy** proxies `dev.pocus.health` → `localhost:8001`
- Fully isolated from prod
- At `/opt/pocus-health-dev` on server

---

## Repository Structure

```
POCUS-Health/
│
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   │   └── main.py              (FastAPI signaling server)
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── frontend/
│       ├── index.html               (Desktop web page)
│       ├── images/
│       │   └── otternion.png        (Logo)
│       └── icons/                   (Favicon files)
│
├── deploy/
│   ├── Caddyfile                    (Routes prod + dev)
│   ├── Dockerfile                   (Caddy image)
│   ├── docker-compose.yml           (Prod stack)
│   ├── docker-compose.dev.yml       (Dev stack)
│
├── .github/
│   └── workflows/
│       ├── deploy-master.yml        (Merged PR → prod deploy)
│       └── deploy-dev.yml           (Push to dev → dev deploy)
│
├── instructions.md                  (This file)
└── README.md
```

**Key points:**
- **Single frontend source:** `apps/frontend/` only.
- **Single backend source:** `apps/backend/` only.
- **Deploy config:** Isolated in `deploy/`
- **CI/CD:** GitHub Actions in `.github/workflows/`

---

## Development Workflow

### 1) Make changes on `dev` branch

```bash
git checkout dev
git pull origin dev
# ... make changes ...
git add .
git commit -m "Your change"
git push origin dev
```

This **auto-deploys to `dev.pocus.health`** via `deploy-dev.yml` workflow.

### 2) Test on dev environment

- **Frontend:** https://dev.pocus.health
- **Backend API:** https://dev.pocus.health/api/session
- **WebSocket:** `wss://dev.pocus.health/ws`

### 3) Create PR: `dev` → `master`

```bash
# On GitHub web:
# 1. Click "New Pull Request"
# 2. base = master, compare = dev
# 3. Review, approve, merge
```

When merged, `deploy-master.yml` **auto-deploys to `pocus.health`** (prod).

---

## Deployment Details

### Production Deploy (via Merged PR)

Triggered when: **PR from `dev` is merged into `master`**

Steps:
1. Build Caddy image (from `deploy/Dockerfile`)
2. Build Backend image (from `apps/backend/Dockerfile`)
3. Push both to GitHub Container Registry (GHCR)
4. SSH into Linode
5. Pull new images, restart containers

**Prod address:** `/opt/pocus-health`

### Dev Deploy (via Push)

Triggered when: **Any push to `dev` branch**

Steps:
1. Build Backend image only (Caddy comes from prod)
2. Push to GHCR
3. SSH into Linode
4. Pull, restart dev backend

**Dev address:** `/opt/pocus-health-dev`

### GitHub Secrets Required

Set these in GitHub repo → Settings → Secrets and variables → Actions:

- `LINODE_HOST` — your Linode IP or domain
- `LINODE_USER` — SSH user (default: `nstaff`)
- `LINODE_SSH_KEY` — private SSH key for deploy user

---

## Backend API Reference for signaling server and session

### POST `/api/session`

Create a pairing session.

**Response:**
```json
{
  "sessionId": "uuid...",
  "token": "secret...",
  "phoneUrl": "/m/{sessionId}?token=secret"
}
```

### WebSocket `/ws`

**Hello message (required):**
```json
{
  "type": "hello",
  "role": "desktop" | "phone",
  "sessionId": "...",
  "token": "..."
}
```

**Signaling messages relayed:**
- `offer`, `answer`, `ice-candidate`
- `type`, `data` fields

**Fallback data messages:**
```json
{
  "type": "sensor",
  "t": 1700000000000,
  "seq": 12345,
  "orientation": { "alpha": 10.1, "beta": -2.3, "gamma": 45.0 }
}
```

---

## HTTPS & Certificates

**Caddy auto-provisions Let's Encrypt certificates** for domains in the Caddyfile:
- `pocus.health`
- `dev.pocus.health`

Certificates are stored in persistent volume `caddy_data` on the server.

---

## What's Next (MVP Roadmap)

### 1) Desktop Frontend (3D Visualization)
- [ ] HTML5 Canvas or Three.js for 3D model
- [ ] "Create Session" button → calls `POST /api/session`
- [ ] Display QR code (encode `phoneUrl`)
- [ ] Open WebSocket, send `hello`
- [ ] Handle WebRTC offer/answer/ICE
- [ ] Receive sensor data over DataChannel
- [ ] Update 3D model rotation based on phone orientation

### 2) Mobile/Phone Frontend
- [ ] Simple HTML page at `/m/{sessionId}`
- [ ] "Enable Motion" button (iOS Safari requirement)
- [ ] Request device orientation/motion permissions
- [ ] Open WebSocket, send `hello`
- [ ] Receive WebRTC offer, send answer
- [ ] Stream gyro + accelerometer + orientation data at 30–60Hz

### 3) WebRTC Data Channels
- [ ] Create unreliable channel for sensor streams (`ordered: false, maxRetransmits: 0`)
- [ ] Optional: create reliable channel for discrete events
- [ ] Handle fallback to WebSocket if DataChannel fails

### 4) Testing & Polish
- [ ] Test on real devices (iOS, Android)
- [ ] Optimize sensor streaming rate
- [ ] Error handling & reconnection logic

---

## Local Development (Optional)

If you want to run locally without Docker:

```bash
# Backend (FastAPI)
cd apps/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (static files)
# Serve apps/frontend/ via any HTTP server (e.g., Python)
python -m http.server 8001 -d apps/frontend
```

Then open `http://localhost:8000` (if backend also serves frontend).

---

## Troubleshooting

### Prod Caddy not updated?
```bash
cd /opt/pocus-health
docker compose pull
docker compose up -d --force-recreate
```

### Dev backend not responding?
```bash
cd /opt/pocus-health-dev
docker logs pocus-backend-dev --tail 50
```

### Certificate issues?
```bash
docker exec pocus-health-caddy-1 cat /etc/caddy/Caddyfile
```

---

## Notes

- **Merge-based deployment is enforced:** Direct push to `master` will not deploy. Always create a PR from `dev`.
- **Dev is isolated:** Changes to dev backend don't affect prod.
- **Frontend is shared:** Both prod and dev serve the same static frontend from `apps/frontend/`.
- **Session TTL:** Backend sessions expire after 10 minutes of inactivity.

---

## References

- [FastAPI docs](https://fastapi.tiangolo.com/)
- [Caddy docs](https://caddyserver.com/docs/)
- [WebRTC MDN](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)
- [Device Orientation API](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
