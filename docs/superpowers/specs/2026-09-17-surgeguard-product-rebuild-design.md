# SurgeGuard product rebuild: design spec

Date: 2026-09-17
Status: approved for implementation (autonomous run, per the brief)
Scope: new frontend (landing page, authentication, Command Center application) plus the backend
changes that product needs.

The source code is the source of truth. `SURGEGUARD_CONTEXT.md` was checked against it and is wrong
in several places that matter to a UI (see section 1.2).

---

## 1. What SurgeGuard is, verified from source

### 1.1 The product

An AI crowd-intelligence and decision-support platform for control rooms. Cameras the venue already
has (USB webcams, RTSP/IP CCTV, Android phones running DroidCam, or a recorded clip in Demonstration
Mode) feed a per-camera pipeline:

1. **Capture**: `FrameSource` (live or file, paced to source fps), reconnect with doubling backoff.
2. **Perceive**: YOLO11 person detection (CUDA FP16 or CPU fallback, with the reason reported) and
   ByteTrack tracking. Track identities are ephemeral and per camera, never persisted or matched
   across cameras.
3. **Measure**: density grid (persons/m² only when calibrated, otherwise *relative*), flow (median
   speed against the camera's own baseline, heading, opposing fraction), zone occupancy.
4. **Assess**: Crowd Stability Index, `CSI = clamp(100 − Σ wᵢ·pᵢ, 0, 100)`, from five indicator
   pressures (density 0.35, motion suppression 0.20, egress congestion 0.20, flow conflict 0.15,
   rate of change 0.10). Unavailable indicators are excluded and the remaining weights renormalised.
   EMA smoothing (10 s). Band hysteresis: 3 windows to escalate, 5 to de-escalate.
   **High CSI means stable**: ≥80 Stable, ≥60 Observe, ≥40 Attention Required, ≥20 High Alert,
   below 20 Critical. Decision Confidence is the product of detection quality, track stability and
   temporal sufficiency, and names its limiting factor.
5. **Explain**: Evidence Engine. Prioritised observations in operator language, each carrying the
   supporting metrics with units and baselines.
6. **Advise**: Operational Decision Engine. The Operational Intelligence Report (OIR): situation
   summary, primary causes with their contribution share, recommended actions from a *closed*
   vocabulary, each with rationale, confidence, urgency and `rule_id`. The engine never acts.
7. **Queue Intelligence** (per QUEUE zone): formation classification with the geometry behind it,
   counted arrival/service/abandonment rates, wait by Little's Law with its assumptions, forecasts at
   +5/+10/+15 min (Holt trend, flow balance, consensus, method agreement), abnormal growth against
   the queue's own baseline (z-score), and a staffing plan computed by re-running the projection at
   every counter count.
8. **Site Intelligence** (all cameras, 1 Hz): overlap-aware headcount (shared coverage areas take the
   largest single count and report the sum as an upper bound), pooled queues, site forecasts that are
   *withheld* when coverage is incomplete, hotspot score (density, instability, growth, capacity;
   never headcount alone), time to pressure, zone flow map (TRACKED same-camera links versus
   CORRELATED cross-camera links), and alerts with evidence.
9. **Deliver**: one WebSocket (`/ws/command-center`) with snapshot-first delivery, per-connection
   sequence numbers, resync on gap, heartbeat, and a staleness threshold. The annotated MJPEG video
   has selectable overlays (hud, tracks, trails, zones, flow, heatmap).
10. **Simulation Mode**: what-if queue scenarios. The input is synthetic; the forecaster and
    allocator are the production ones, and every response is tagged `SIMULATION`.

Principles stated throughout the code, which the UI must honour and the landing page may state
because they are true:

- An offline camera is absent, never zero. Estimated counts are labelled. Relative density is never
  shown as persons/m².
- Stale data is visible. A frozen display is more dangerous than a failed one.
- Forecasts and plans are withheld, with a reason, when their inputs are incomplete or provisional.
- Status is quicker to warn than to reassure (hysteresis).
- The operator decides. Every recommendation is traceable to a rule and to measurements.
- Simulated figures are always labelled.

### 1.2 Corrections to `SURGEGUARD_CONTEXT.md`

| Context doc says | Source says |
|---|---|
| CSI is 0–1 | CSI is 0–100, and **higher is more stable** |
| Indicators MOTION_COHERENCE, EGRESS_FLOW, FLOW_VARIABILITY, ARRIVAL_RATE | DENSITY_PRESSURE, MOTION_SUPPRESSION, EGRESS_CONGESTION, FLOW_CONFLICT, RATE_OF_CHANGE |
| Health status HEALTHY/DEGRADED/OFFLINE, components AI_PIPELINE/CAMERA/DATABASE | HEALTHY/WARNING/OFFLINE; CAMERA, AI_PIPELINE, BACKEND, DATABASE, NETWORK |
| Camera status CONNECTED/DISCONNECTED/RECONNECTING/FAILED | CONNECTING/ONLINE/DEGRADED/RECOVERING/OFFLINE/DISABLED |
| Worker states uppercase | lowercase `disabled/stopped/starting/running/recovering/completed/failed` |
| Camera origin ENV/REGISTRY/RUNTIME, url_source ENV/REGISTRY/MANUAL | origin ENVIRONMENT/OPERATOR; url_source ENVIRONMENT/REGISTRY/UNSET |
| Zone types QUEUE/WAITING_AREA/ENTRY/EXIT/SERVICE/GENERAL | ENTRY/EXIT/PLATFORM/CONCOURSE/STAIRWELL/QUEUE/COUNTER |
| Heartbeat data `{}` | `{"clients": n}` |
| Stability fields `csi`, `smoothed_csi`, `indicators` | `csi_raw`, `csi_smoothed`, `breakdown.readings[]`, `confidence{value,factors,limiting_factor}` |
| A `frontend/` directory exists | It does not. There is no frontend at all. |

### 1.3 Gaps found in the backend

1. **No authentication.** The brief requires Landing → Login → Application. Role-based access is
   named as production architecture in `core/constants.py`, and `User` is a planned entity.
2. **`oir.updated` carries no camera id.** Every camera's DecisionService dispatches
   `OIR_GENERATED`, and the publisher forwards each one with `camera_id: null`, so with two cameras
   the reports interleave and cannot be told apart. The snapshot carries only the primary camera's
   report and state.
3. **Operational State is never pushed.** It arrives only in the snapshot, so a socket client shows
   it stale until the next resync.
4. **`health.updated` is declared but never published.**
5. **Historical persistence is configured but not implemented.** `history_enabled`,
   `history_bucket_seconds`, `history_retention_days` and `history_baseline_min_samples` exist in
   settings and `.env.example`, but nothing reads them and `models/` is empty.
6. **The app ignores its own database settings.** `lifespan` connects the module-global
   `DatabaseManager(get_settings())` rather than `app.state.settings`, so tests would write to the
   developer database the moment any table exists. `SettingsDep` has the same shape.
7. **Only MJPEG streams exist.** Browsers allow about 6 concurrent HTTP/1.1 connections per origin,
   so a grid of live camera tiles starves every REST call. A single-frame snapshot endpoint is needed
   for thumbnails.
8. **No operator actions.** `OperationalState` INVESTIGATING and RESPONDING are unreachable, and the
   timeline's `actor` field is never set, because nothing identified an operator until now.

---

## 2. Backend changes

All additive or corrective. Existing routes, payload shapes and WebSocket messages keep their
contracts. Existing tests must keep passing.

### 2.1 Authentication (new)

- Settings: `auth_enabled` (default `true`), `session_ttl_hours` (12, one shift),
  `session_cookie_name` (`surgeguard_session`), `session_cookie_secure` (defaults to true in
  production), `login_max_failures` (5), `login_lockout_seconds` (300),
  `database_auto_migrate` (true).
- Models (Alembic migration `0001`): `user_account` (uuid, email unique, display_name,
  password_hash, role ADMIN/OPERATOR, is_active, last_login_at, timestamps) and `user_session`
  (uuid, user_id, token_hash unique, created_at, expires_at, last_seen_at, user_agent, ip_address,
  revoked_at).
- Passwords: PBKDF2-HMAC-SHA256, 600 000 iterations, 16-byte salt, stdlib only, run off the event
  loop, constant-time comparison. Minimum 12 characters.
- Sessions: 256-bit random token in an HttpOnly, SameSite=Lax cookie. Only its SHA-256 is stored.
  The cookie also reaches the WebSocket upgrade and the MJPEG `<img>` requests, which bearer tokens
  cannot.
- First run: while no account exists, `POST /auth/setup` creates the first ADMIN. After that it
  returns 409. No default credentials exist anywhere.
- Routes, under `/api/v1/auth`: `GET /status` (public: auth_enabled, setup_required, user|null),
  `POST /setup`, `POST /login`, `POST /logout`, `GET /me`, `PATCH /me`, `POST /me/password` (revokes
  the other sessions), `GET /sessions`, `DELETE /sessions/{id}`.
  Admin routes under `/api/v1/users`: `GET`, `POST`, `PATCH /{id}` (role, active, name).
  Accounts are deactivated, never deleted, so timeline attribution survives.
- Protection: every existing REST route, both MJPEG routes and the socket require a session.
  `/health/live` and `/health/ready` stay public for orchestration. Camera add/edit/remove, zones
  and topology writes require ADMIN. Counters, retries, connection tests and simulation are OPERATOR
  actions.
- Socket: an invalid session is accepted, then closed with code **4401**, so the client can tell
  "sign in again" from "reconnect".
- Failed logins are rate limited per client and email, and return 429 with `retry_after_seconds`.
- Error codes: `UNAUTHORIZED` 401, `FORBIDDEN` 403, `INVALID_CREDENTIALS` 401,
  `TOO_MANY_ATTEMPTS` 429, `SETUP_COMPLETE` 409.
- With `auth_enabled=false` every route behaves as before and `GET /auth/status` says so. The UI
  then skips sign-in. The existing test fixtures set this explicitly; new tests cover auth.

### 2.2 Realtime correctness

- `DecisionService` dispatches `OIR_GENERATED` with an `IssuedReport(camera_id, report)` value.
  The publisher sets the envelope `camera_id`, and the wire payload is unchanged.
- New domain event `OPERATIONAL_STATE_CHANGED` becomes WS `state.updated`,
  data `{camera_id, operational_state}`.
- Snapshot adds `camera_decisions: {camera_id: {report, operational_state}}`.
- `health.updated` is published when component health changes (checked every 5 s).
- REST `GET /cameras/{camera_id}/decisions` returns that camera's report (nullable),
  operational state and age. It always answers.

### 2.3 Historical persistence (implements the existing `history_*` settings)

- Table `observation_bucket`: one row per camera (plus `camera_id="site"`) per bucket (30 s).
  Columns: bucket_start, bucket_seconds, source_mode, samples, csi mean/min/max,
  status_worst, status_last, per-status sample counts, confidence mean, people mean/max,
  estimated_samples, density_max plus is_metric, queue length mean/max, wait mean, arrival and
  service rate means, degraded_samples, and for site rows headcount mean/max and minimum
  contributing cameras. Unique on (camera_id, bucket_start, bucket_seconds, source_mode).
- Aggregated measurements only. Never frames, images or track identities.
- `HistoryRecorder` subscribes to `ANALYSIS_RECEIVED` and `SITE_UPDATED`. It accumulates in memory,
  flushes a bucket on rollover, on a 10 s sweep for silent cameras and at shutdown, and prunes past
  `history_retention_days`. A failed write is logged and never reaches the pipeline.
- Routes under `/api/v1/history`: `GET /cameras/{camera_id}` and `GET /site`
  (`from`, `to`, `resolution` seconds, `source_mode`), `GET /summary` (per-camera range figures,
  time in each band, and `baseline_available` against `history_baseline_min_samples`).

### 2.4 Camera snapshot

`GET /cameras/{camera_id}/snapshot?layers=` returns one annotated JPEG (`no-store`). It waits up to
2 s for a fresh frame and returns 503 otherwise, so thumbnails never hold connections open.

### 2.5 Operator actions (enables INVESTIGATING and RESPONDING)

`POST /api/v1/cameras/{camera_id}/operations` with body `{action: ACKNOWLEDGE | LOG_ACTION | CLOSE,
note?, rule_id?}`:

- ACKNOWLEDGE moves OBSERVING to INVESTIGATING.
- LOG_ACTION moves OBSERVING or INVESTIGATING to RESPONDING.
- CLOSE moves any state to MONITORING, and is allowed only while the status is STABLE.
- An operator-entered phase persists while conditions stay unstable. Recovery to STABLE still moves
  to RECOVERING and then MONITORING, as today.
- Each action writes an `OPERATOR_ACTION` timeline entry with `actor` set to the operator's display
  name and publishes `state.updated`.
- An illegal transition returns 409 `CONFLICT`.

### 2.6 Corrections

- Lifespan builds `DatabaseManager(app.state.settings)`. The `DatabaseDep`, `SessionDep` and
  `SettingsDep` dependencies read from app state.
- Schema: on startup, if `database_auto_migrate` is set, Alembic `upgrade head` runs in a worker
  thread against the app's own URL. `alembic/env.py` accepts an explicit URL.
- The video overlay status colours in `streaming/annotator.py` move to the new status palette
  (section 3.2), so video and panels still speak one colour language.
- If `frontend/dist` exists, it is served with SPA fallback, so a single process serves the whole
  product in production. `/api`, `/ws`, `/docs`, `/redoc` and `/openapi.json` are never shadowed.

---

## 3. Design system: "Dark cockpit"

### 3.1 Concept

Control rooms run long shifts in low light, and the platform's whole ethic is that nothing on
screen may overstate what was measured. The design borrows the aviation *dark cockpit* philosophy:
when everything is normal the instrument is quiet and nearly monochrome, and colour appears only to
say that something needs attention. **Colour is reserved for meaning.** Chrome is graphite and ink.
The five status colours are the only saturated hues in the product, and they always travel with a
label and an icon.

The one bold, memorable element is the **band**: the Crowd Stability Index scale, five segments
from Critical to Stable with ticks at 20/40/60/80. It is the brand's structural motif, appearing in
the hero, the gauge, the status bar and the logo.

Why this is not the generic dark-plus-accent template: there is no decorative accent colour, the
surfaces are layered instrument graphite rather than flat black, every coloured pixel encodes a
state, and the type is an engineered width-variable grotesque with signage-like proportions, set
condensed for readouts.

### 3.2 Colour tokens (dark, the only theme)

Neutrals (instrument graphite, cool undertone):

| Token | Hex | Role |
|---|---|---|
| `canvas` | `#0B0E11` | page and app background, video letterbox |
| `surface-1` | `#11161B` | panels |
| `surface-2` | `#171D23` | raised panels, inputs |
| `surface-3` | `#1E252C` | hover, selected rows |
| `line` | `#242C34` | hairlines |
| `line-strong` | `#33404B` | control borders, dividers |
| `ink-faint` | `#5D6A76` | decorative and disabled only (never body text) |
| `ink-muted` | `#8A96A1` | secondary labels (≥5.1:1 on every surface) |
| `ink-secondary` | `#B3BCC4` | supporting text |
| `ink` | `#E6EAED` | body text |
| `ink-strong` | `#F7F9FA` | headings, primary button fill |

Status (validated with the dataviz validator on `#11161B`, all pairs: CVD ΔE ≥ 8.6, normal
ΔE ≥ 17.5, contrast ≥ 3:1):

| Operational Status | Fill | Text on dark |
|---|---|---|
| STABLE | `#3CCB85` | same |
| OBSERVE | `#5AB8FA` | same |
| ATTENTION_REQUIRED | `#EFDD55` | same |
| HIGH_ALERT | `#F99442` | same |
| CRITICAL | `#E8435F` | `#F26F86` (4.37:1 on surface-2 for the fill is too low for text) |

Derived semantics:

- Camera connection: ONLINE stable, DEGRADED attention, RECOVERING high (pulsing), OFFLINE critical,
  CONNECTING ink-muted (pulsing), DISABLED ink-faint.
- Health: HEALTHY stable, WARNING attention, OFFLINE critical.
- Severity: INFO ink-secondary, WARNING attention, CRITICAL critical.
- **Operational State never uses the status palette** (a contract rule). It renders as a neutral
  five-step progress strip in ink intensities.
- SIMULATION label: a hatched ink-strong outline chip, not a hue.
- Focus ring: 2 px `ink-strong`, 2 px offset. Selection: `ink-strong` at 8%.

### 3.3 Typography

One family: **Archivo** (variable, `wght` 100–900, `wdth` 62–125), self-hosted via fontsource.
It is a grotesque with a real width axis, so one family covers editorial display, UI text and
condensed instrument readouts.

| Role | Setting |
|---|---|
| Display (landing) | wdth 112, wght 640, tracking −0.02em, leading 0.95 |
| H1 / page title | wdth 100, wght 600, 28–32 px |
| H2 / panel title | wdth 100, wght 600, 15–16 px |
| Body | wdth 100, wght 400, 15–16 px, leading 1.55 |
| Label | wdth 100, wght 500, 12–13 px, sentence case, no letterspaced caps |
| Readout (CSI, counts) | wdth 75, wght 560, tabular figures |
| Identifiers (rule ids, URLs) | `ui-monospace` system stack, only where the string is code-like |

Scale: 12, 13, 14, 16, 18, 22, 28, 36, 48, 64, 88, 120 px. Line lengths ≤ 72ch.

### 3.4 Space, radius, elevation, motion

- 4 px base unit. Dashboard density: panel padding 16 px, gaps 12 px; landing uses 96–160 px
  section rhythm.
- Radius by hierarchy: 4 px (chips, inputs), 8 px (panels), 12 px (dialogs and hero frames). Never
  one radius for everything.
- Elevation is expressed with surface steps and hairlines, not drop shadows. One shadow is reserved
  for overlays (dialogs, menus).
- Motion: 120 ms (hover and press), 200 ms (enter), 160 ms (exit, faster than enter), with
  `cubic-bezier(.2,.7,.2,1)`. Status transitions cross-fade. Numbers do not animate in the
  app, where an animated count would show a value that was never measured. Everything respects
  `prefers-reduced-motion`.

### 3.5 Components

Primitives: Button (primary ink-strong fill, secondary outline, ghost, danger), IconButton (always
labelled), Input, Textarea, Select, Switch, Slider, Stepper, Field (label, help and inline error),
Tabs, Dialog, Drawer, DropdownMenu, Tooltip, Toast, Badge, StatusPill, SeverityMark, Skeleton, Kbd.

Composites: Panel (title, meta and actions slots; loading, empty, error, stale and degraded states
built in), StatBlock, KeyValueList, DataTable, EmptyState, ErrorState, StaleBadge, ConnectionMeter,
SourceModeBadge, CountMethodTag, DensityValue (applies the is_metric rule), BandScale, CsiGauge,
IndicatorBars, ConfidenceMeter, OperationalStateStrip, EvidenceList, ActionList, TimelineList,
AlertCard, CameraTile, LiveStream (MJPEG with 503 and not-running handling), LayerToggle, Charts
(TimeSeries with crosshair tooltip, Sparkline, ForecastFan, CapacityLadder, StackedBands).

Built on Radix primitives (`radix-ui`) for focus management and ARIA, styled with Tailwind 4 over
the tokens above.

---

## 4. Frontend architecture

- **Stack**: Vite 8, React 19, TypeScript 7, React Router 8 (data mode, lazy routes), Tailwind 4,
  Zustand 5 for live socket state, TanStack Query 5 for REST resources, `radix-ui`, `motion`
  (landing interactions only), d3-scale/d3-shape for charts, zod plus react-hook-form for forms,
  lucide-react icons, Vitest and Testing Library, oxlint.
- **Same origin.** In development Vite proxies `/api` and `/ws` (with `ws: true`) to
  `VITE_BACKEND_URL`. In production FastAPI serves `dist`. The client builds its WebSocket URL from
  `location`. Credentials are cookies, and no token ever touches JavaScript.
- **Layout**: `src/app` (router, providers), `src/styles` (tokens), `src/ui` (primitives),
  `src/components` (composites and charts), `src/features/<area>` (pages and area components),
  `src/realtime` (socket client, store, reducers, fallback polling), `src/api` (client, endpoints,
  query keys), `src/types` (contract mirrors), `src/lib` (format, labels, time, hooks).
- **Realtime client**: snapshot resets state; seq gap sends `resync` once per gap; heartbeat gets
  `pong`; staleness uses `stale_after_seconds`; reconnect uses exponential backoff from 500 ms,
  capped at 8 s with jitter, and fails after 20 attempts with a manual retry. The browser
  `online`/`offline` events and tab visibility trigger an immediate retry. Close code 4401 hands off
  to the auth layer. Timeline entries dedupe by `entry_id`.
- **Fallback**: while the socket is not open, REST polling on the same reducers covers cameras,
  site, health, timeline and the focused camera's analysis and decisions. Polling stops when the
  socket opens.
- **Session trends**: ring buffers per camera (CSI, people, queue) and for the site headcount, fed
  by socket messages and labelled "this session". Long-range trends come from `/history`.
- **Connection budget**: at most two MJPEG streams open at once (the focused camera, plus the camera
  detail view). Tiles use the snapshot endpoint every 4 s while visible.

---

## 5. Landing page

A launch page with a narrative, not a feature grid. Nothing on it is fabricated: product facts come
from the code, the interactive index uses the real formula, weights and bands, and illustrations are
labelled as illustrations.

1. **Hero**. Left: "See pressure building in a crowd. Know exactly why." A subhead on cameras
   already installed, the live index, forecasts and traceable guidance. CTAs "Open the Command
   Center" and "How it works". Right: a canvas "venue" instrument. Schematic zones (entry,
   concourse, queue lanes and counters, exit), people moving, tracking brackets and trails, a
   density bloom forming at the exit neck, and a HUD band whose status follows hysteresis. Labelled
   "Illustrative simulation, not live data". Paused off screen, static under reduced motion.
2. **A crowd rarely fails all at once.** The five measurable precursors, which are the five
   indicators in plain language.
3. **The index, explained by touching it.** Five pressure sliders with real weights, availability
   toggles that renormalise, the live CSI on the band, and the hysteresis rule.
4. **How it works.** A seven-stage pipeline diagram (a real sequence, so numbering is honest) with
   the real parameters.
5. **Guidance you can audit.** The anatomy of an OIR, drawn with the real app components and
   labelled as an example. Real action vocabulary and rule ids.
6. **Queues: now, next, and what to do.** The three separated layers, with schematic (unscaled)
   forecast-fan and capacity-ladder illustrations.
7. **Every camera, one site.** Overlap-aware counting, tracked versus correlated flow, hotspot
   factors, and withheld forecasts.
8. **Cameras you already have.** USB, RTSP, DroidCam, recorded clips, connection tests, reconnection
   and device telemetry, GPU or CPU fallback.
9. **Built not to mislead.** The integrity rules and privacy: no face recognition, ephemeral
   per-camera identities, aggregates-only history.
10. **Final CTA** and footer.

---

## 6. Application

Routes (all behind the auth gate except `/`, `/login` and `/setup`):

| Route | Purpose |
|---|---|
| `/command-center` | Live operational picture: status bar (Operational Status, CSI, state strip, people, site coverage), focused camera stream with overlays and camera switcher, CSI instrument, OIR guidance with operator actions, evidence, queue now/next/do, site alerts, session trends, live timeline |
| `/site` | Headcount with aggregation and limits, per-camera summary, flow map, hotspot factors, time to pressure, site forecasts, staffing plan or withheld reason |
| `/cameras` | Camera network: coverage summary, tiles with snapshots, status and metrics, add camera with connection test |
| `/cameras/:cameraId` | Stream with layer toggles, device and pipeline metrics, analysis, zone flow, queue, zone editor, counters, retry, test, edit, enable/disable, remove |
| `/queues` | Every queue zone: now, forecast (fan with both methods), plan (capacity ladder), counters; pooled site queue |
| `/alerts` | Active site alerts with evidence, plus alert raise and resolve history |
| `/timeline` | Full timeline with filters, guidance revision history, evidence history |
| `/analytics` | Stored history: CSI, people, queue and wait over 1 h to 30 d, time in each band, baseline availability |
| `/simulation` | What-if runner with presets; everything labelled SIMULATION |
| `/system` | Component health, pipeline and device, ingest, stream, realtime link diagnostics, build info |
| `/settings` | Site topology links (admin), operators (admin), local preferences (default overlays, desktop notifications for critical alerts) |
| `/profile` | Name, password, active sessions |

Designed states for every data surface: loading skeleton, empty (with the next action), waiting
(503 means degraded, not failure), error (with retry), stale (age shown), camera offline, simulation
label, permission denied, backend unreachable, session expired, and socket reconnecting or failed.

Responsive rules: sidebar becomes a drawer below 1024 px, and the status bar compresses to Status,
CSI and the connection indicator. The Command Center reflows 12 → 8 → 1 columns. Tables become
stacked rows below 640 px. Touch targets are at least 44 px.

---

## 7. Verification

- Backend: full pytest (existing plus new auth, history, realtime, operations and snapshot tests).
- Frontend: `tsc --noEmit`, oxlint, Vitest (socket client, reducers, formatting and label rules),
  `vite build`.
- Live: backend in DEMO mode on a placeholder clip plus the DroidCam emulator as a second camera,
  and the Vite dev server. Walk every route at 1440, 1024, 768 and 375 px. Check the console and
  network. Kill a camera, the socket and the backend to see the degraded states. Run Lighthouse on
  the landing page.
- The user's `backend/.env` and data are never modified. Test runs use process environment
  overrides and scratch paths.
