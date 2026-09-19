# SurgeGuard 1.0

**See pressure building in a crowd. Know exactly why.**

SurgeGuard is a real-time crowd-safety platform. It turns ordinary camera feeds
(USB webcams, RTSP cameras, DroidCam phones or recorded clips) into an
explainable **Crowd Stability Index**. It tells control-room operators what is
happening, why, and what to do about it, and it can drive a physical alert light
and buzzer.

It is a full stack: a GPU-accelerated AI pipeline (YOLO + ByteTrack), a FastAPI
backend with authentication, real-time WebSockets and persisted history, a React
Command Center, and Arduino alert hardware.

---

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [The Command Center](#the-command-center)
- [Alert hardware](#alert-hardware)
- [Security](#security)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Further reading](#further-reading)

---

## What it does

- **Detects and tracks people** in every camera feed (Ultralytics YOLO, person
  class only, plus ByteTrack for persistent identities). It runs on CUDA with FP16
  when available and falls back to CPU, and it reports which one it is using.
- **Measures the crowd:** density on a grid, flow, zone occupancy, queues. Density
  is in persons/m² only when a camera is calibrated; otherwise it is labelled
  *relative*.
- **Computes the Crowd Stability Index (CSI)**, a score from 0 to 100 where
  **higher means more stable**:

  ```
  CSI = clamp(100 − Σ wᵢ·pᵢ, 0, 100)
  ```

  | Indicator | Weight | Operator label |
  |---|---|---|
  | `DENSITY_PRESSURE` | 0.35 | Crowd density |
  | `MOTION_SUPPRESSION` | 0.20 | Movement suppression |
  | `EGRESS_CONGESTION` | 0.20 | Exit congestion |
  | `FLOW_CONFLICT` | 0.15 | Opposing flow |
  | `RATE_OF_CHANGE` | 0.10 | Rate of change |

  The weights renormalise when an indicator cannot be measured. The score is
  smoothed, and each band change needs hysteresis before it takes effect. Every
  reading comes with a computed confidence and its limiting factor.

- **Maps the CSI to an Operational Status:**

  | CSI | Operational Status |
  |---|---|
  | 80–100 | Stable |
  | 60–79 | Observe |
  | 40–59 | Attention Required |
  | 20–39 | High Alert |
  | 0–19 | Critical |

- **Explains itself:** the Evidence Engine produces operator-readable
  observations ("Congestion forming…", "Opposing movement detected", …), and each
  one cites the measurement behind it.
- **Recommends actions:** the Decision Engine issues an **Operational
  Intelligence Report (OIR)** with rule-based guidance (for example
  `open-exit-zone`, "Open additional exit capacity at {zone}", or
  `deploy-personnel`). Operators can Acknowledge, Log an action or Close it, and
  each action is written to the Timeline with their name.
- **Queue Intelligence:** current queue formation, rates and wait (shown as
  "Not draining" when the queue is not being served); forecasts from two methods
  plus their agreement; a staffing plan (capacity ladder).
- **Site view across cameras:** headcount that accounts for camera overlap,
  cross-camera flow (tracked or correlated), hotspots, time to pressure and site
  alerts.
- **History:** aggregated CSI, people, queue and status-band statistics are
  persisted in 30-second buckets and can be charted for up to 31 days. It stores
  **aggregates only, never video frames.**
- **Simulation:** a queue simulator whose results are always labelled
  SIMULATION.
- **Physical alerts:** an Arduino RGB LED and buzzer show green, yellow or red
  according to the live Operational Status.

**Source modes:** `LIVE` reads the real cameras, and `DEMO` replays a recorded
clip through exactly the same pipeline. The data from the two modes is never
mixed.

---

## How it works

```
Camera / clip ─► FrameSource ─► YOLO detector ─► ByteTrack ─► PerceptionResult
                                                                    │
      ┌─────────────────────────────────────────────────────────────┘
      ▼
GridCrowdAnalyzer ─► WeightedStabilityAssessor (CSI) ─► RuleEvidenceEngine ─► Decision Engine (OIR)
                                                                                    │
      ┌──────────────────────────────┬─────────────────────────────┬───────────────┘
      ▼                              ▼                             ▼
 FastAPI REST + WebSocket     History recorder (SQLite)    HardwareAlertService
      │                                                            │ USB serial
      ▼                                                            ▼
 React Command Center                                   Arduino RGB LED + buzzer
```

- **`ai/`** (`surgeguard-ai`) is an independent package. It never imports from
  the backend, the database or the frontend. Its only interfaces are
  `FrameSource` (input) and `AnalysisSink` (output), so dependencies always run
  `backend → surgeguard_ai`, never the other way.
- **`backend/`** (`surgeguard-backend`) is a modular FastAPI monolith with layers
  `api → services → repositories → models → core`, plus boundary modules for
  realtime, ingest, workers and hardware. The pipeline runs in-process under a
  supervisor. Startup does not wait for the model to load, and if a camera fails
  it is retried with backoff while the rest of the platform keeps working.
- **`frontend/`** is one React application that holds both the landing page and
  the authenticated Command Center. In production the backend serves the built
  frontend itself, so a deployment is one process on one origin.

---

## Repository layout

```
ai/          AI pipeline package: perception, analysis, stability (CSI), evidence,
             forecast, queue, site, intelligence, contracts
backend/     FastAPI app, Alembic migrations, tests, .env.example
frontend/    React 19 + Vite landing page and Command Center, .env.example
hardware/    Arduino firmware (surgeguard_alert.ino) and wiring / protocol docs
scripts/     run_perception.py, droidcam_emulator.py, make_placeholder_clip.py,
             surgeguard_supervisor.py
docs/        Product rebuild design spec and implementation plan
data/        Runtime data (created on first run: model weights, camera registry,
             zones, topology). Not committed.
```

Each part has its own README with the details:
[`ai/README.md`](ai/README.md), [`backend/README.md`](backend/README.md),
[`frontend/README.md`](frontend/README.md) and
[`hardware/README.md`](hardware/README.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| AI | Python 3.11, Ultralytics YOLO (`yolo11s.pt` by default), ByteTrack, OpenCV, PyTorch (CUDA optional) |
| Backend | FastAPI, Uvicorn, Pydantic v2 / pydantic-settings, SQLAlchemy 2 (async) + aiosqlite, Alembic, pyserial |
| Frontend | Vite 8, React 19, TypeScript 7, React Router 8, Tailwind CSS 4, TanStack Query 5, Zustand 5, Radix, Motion, d3 (hand-built SVG charts), zod + react-hook-form |
| Hardware | Arduino Uno, RGB LED, piezo buzzer, 115200-baud line protocol |
| Tooling | pytest, ruff, Vitest + Testing Library, oxlint |

---

## Getting started

### Prerequisites

- Python **3.11+**
- Node.js **22+**
- An NVIDIA GPU with CUDA is optional. Without one, inference runs on the CPU.

### 1. Python environment

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate

# Optional, for GPU inference: install the CUDA build of PyTorch first
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

pip install -e "./ai[dev]"
pip install -e "./backend[dev]"
```

The detection model weights (`yolo11s.pt`) download automatically on first use
into `data/models/`.

### 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

`backend/.env.example` documents every setting. The ones you will most likely
change:

| Variable | Purpose |
|---|---|
| `SURGEGUARD_PIPELINE_SOURCE_MODE` | `LIVE` (real cameras) or `DEMO` (replay a clip) |
| `SURGEGUARD_DEMO_VIDEO_PATH` | The clip used in `DEMO` mode |
| `SURGEGUARD_LIVE_CAMERA_DEVICE` | The live camera (device index, RTSP URL or DroidCam address) |
| `SURGEGUARD_PIPELINE_ENABLED` | `false` runs the API without a camera or GPU |
| `SURGEGUARD_AUTH_ENABLED` | Operator sign-in (default `true`) |
| `SURGEGUARD_HARDWARE_ENABLED` / `SURGEGUARD_HARDWARE_SERIAL_PORT` | Arduino alert hardware (off by default; the port can be `auto`) |

You don't have footage yet? Generate a placeholder clip:

```bash
python scripts/make_placeholder_clip.py --output data/scenarios/00_placeholder.mp4
```

### 3. Run the backend

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the backend from `backend/`, because that is where it reads `.env` and
creates the SQLite database (`surgeguard.db`). Database migrations run
automatically on startup. Interactive API docs are at
`http://127.0.0.1:8000/docs`.

### 4. Run the frontend (development)

```bash
cd frontend
npm install
cp .env.example .env.local   # set VITE_BACKEND_URL if the backend is not on :8000
npm run dev                  # http://127.0.0.1:5180
```

The dev server proxies `/api` and `/ws` to the backend, so cookies, the
WebSocket and the video streams work exactly as they do in production.

### 5. Production (single process)

```bash
cd frontend && npm run build   # writes frontend/dist
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

When `frontend/dist` exists the backend serves the app at `/`. Client routes
fall back to `index.html`, hashed assets are cached as immutable, and `/api`,
`/ws` and `/docs` are never shadowed.

### 6. First sign-in

When no account exists, the app sends you to **/setup**, where you create the
first administrator. Anyone who reaches the deployment at this point can do
this, so **complete setup before exposing the service on a network**.

### Handy scripts

```bash
# Run the pipeline on its own, on a clip or a camera
python scripts/run_perception.py video data/scenarios/00_placeholder.mp4
python scripts/run_perception.py camera --device 0
python scripts/run_perception.py devices

# Emulate a DroidCam phone from a clip (for testing multi-camera setups)
python scripts/droidcam_emulator.py --port 4801 --video <clip>
```

---

## The Command Center

| Route | What it shows |
|---|---|
| `/` | Landing page, with an illustrative in-browser simulation that computes the real CSI formula and is clearly labelled as not live data |
| `/command-center` | Status bar, the focused live stream with overlay layers, the CSI instrument with each indicator's contribution, the OIR with operator actions, evidence, queue now/next/do, site alerts, session trends and the live timeline |
| `/site` | Overlap-aware headcount, per-camera summaries, flow map, hotspots, time to pressure, forecasts and staffing plan |
| `/cameras`, `/cameras/:id` | Camera network, adding and testing cameras, stream, device and pipeline metrics, the zone editor (draw polygons on a snapshot), counters, retry |
| `/queues` | Per queue: now, next (forecast fan with two methods and their agreement), do (capacity ladder) |
| `/alerts` | Active site alerts with evidence, and their raise and resolve history |
| `/timeline` | Filterable event timeline, guidance history and evidence history |
| `/analytics` | Persisted history: CSI band, people, queue and wait, time in each status band, LIVE/DEMO switch, ranges from 1 hour to 30 days |
| `/simulation` | Queue simulator (results labelled SIMULATION) |
| `/system` | Health components, GPU/FP16, ingest and stream status, socket diagnostics, **alert hardware panel** with test buttons |
| `/settings`, `/profile` | Site topology and operators (admin), preferences, name, password, active sessions |

**Real-time behaviour:**

- A single WebSocket (`/ws/command-center`) feeds the live state.
- The client resyncs once per sequence gap, answers heartbeats, and reconnects
  with capped exponential backoff.
- Data is marked **stale with its age** when messages stop.
- An offline camera shows **no figures** (never its last values).
- If the socket is blocked, the client falls back to bounded REST polling and
  stops as soon as the socket is back.
- To stay within the browser's per-origin connection budget, at most two MJPEG
  streams are open at once, and camera tiles poll snapshots instead.

**Design system:** a "dark cockpit" with one shared token set for the landing
page, sign-in and the app.

- Colour is reserved for meaning. Only the five Operational Status hues are
  saturated, and they always appear with a label.
- One variable typeface, Archivo.
- The app never animates numbers.
- `prefers-reduced-motion` is respected.
- Every page is responsive down to 375 px.

---

## Alert hardware

An Arduino Uno, an RGB LED and a buzzer show the site's live Operational Status
over USB serial. The backend decides what to show, and the Arduino only displays
it. With several cameras, the most urgent current camera decides. Offline or
stale cameras are left out.

| Level | When | LED | Buzzer |
|---|---|---|---|
| `NORMAL` | Stable or Observe (CSI ≥ 60) | Green | Off |
| `WARNING` | Attention Required or High Alert (CSI 20–59) | Yellow | Short chirp every 1.5 s |
| `CRITICAL` | Critical (CSI < 20) | Red | Continuous two-tone alarm |
| `NO_DATA` | No camera has a current report | Blue | Off |
| *(link lost)* | No command from the backend for 10 s | Blinking blue | Off |

**Wiring:**

| Part | Uno pin |
|---|---|
| LED blue | 9 |
| LED red | 10 |
| LED green | 11 |
| LED common cathode | GND |
| Buzzer | 8 |

Each LED colour goes through its own resistor. On boot, firmware 1.1.0 prints
`READY SURGEGUARD-ALERT 1.1.0 R10 G11 B9 BUZZER8 CATHODE`. Green on pin 11 uses
software PWM, because Timer2 belongs to `tone()`. The full protocol, test
commands, API (`GET /api/v1/hardware`, `POST|DELETE /api/v1/hardware/test`) and
verification notes are in [`hardware/README.md`](hardware/README.md).

---

## Security

- **Operator authentication:**
  - Passwords are hashed with PBKDF2-SHA256 (600,000 iterations) and must be at
    least 12 characters.
  - Sessions use HttpOnly, `SameSite=Lax` cookies (`Secure` in production). No
    token is ever stored in JavaScript.
  - Failed sign-ins are rate limited.
  - Changing a password ends that account's other sessions.
- **Roles:**
  - `ADMIN` can manage cameras, zones, topology and operators.
  - `OPERATOR` has every read, plus counters, retries, connection tests,
    simulation and operator actions.
  - The last active administrator cannot be demoted or deactivated.
- **WebSocket:** a connection without a valid session is closed with code
  `4401`. Signing out closes that session's sockets.
- **Secrets:** they stay in `backend/.env`, which is git-ignored, as are the
  database, runtime data and logs. No frontend variable is a secret.

---

## Testing

```bash
# AI pipeline
cd ai && pytest

# Backend (runs without a camera, GPU or model weights)
cd backend && pytest
cd backend && ruff check app tests alembic

# Frontend
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

At the time of this release, all tests pass: 423 in the AI package, 405 in the
backend and 72 in the frontend, with a clean typecheck. Beyond the unit and
integration suites, the system was checked end to end:

- **Live runs:** every route was walked at desktop and mobile (375 px) widths.
- **Failure drills:**
  - camera offline
  - backend killed and restarted
  - socket blocked, with fallback polling
  - `503` before the first frame
- **Real hardware:**
  - The full detection → CSI → Decision Engine → serial chain was run on the
    Arduino.
  - Each LED state was confirmed by eye.

---

## Known limitations

- The Timeline, evidence history and OIR history are in-memory ring buffers and
  are lost on restart. Only the aggregated history is persisted.
- `/decisions/history` and `/intelligence/evidence/history` describe the primary
  camera only.
- Operator actions exist per camera. Site alerts cannot be acknowledged
  individually, because the backend has no alert entity.
- First-run setup is open to whoever reaches the deployment first while no
  account exists.
- The login rate limiter keys on the client address, so behind a reverse proxy
  every client shares one key.
- SQLite is the default database. Access goes through SQLAlchemy, so moving to
  PostgreSQL means changing the URL and running the migrations.
- Not verified:
  - Lighthouse scores
  - browsers other than Chromium
  - multi-hour history retention
  - recovery of the alert hardware from a physical USB unplug (it is covered
    by tests but was not observed live)
- DroidCam phones serve only one viewer at a time. Close the DroidCam Windows
  client if a camera reports it is busy.

---

## Further reading

- [`docs/superpowers/specs/2026-09-17-surgeguard-product-rebuild-design.md`](docs/superpowers/specs/2026-09-17-surgeguard-product-rebuild-design.md): product and design spec
- [`docs/superpowers/plans/2026-09-17-surgeguard-product-rebuild.md`](docs/superpowers/plans/2026-09-17-surgeguard-product-rebuild.md): implementation plan
- [`backend/README.md`](backend/README.md): API surface, auth, operator actions, history, streams, migrations

---

## License

Proprietary. All rights reserved. The source is published for viewing, and no
licence to use, copy or redistribute it is granted.
