# surgeguard-backend

The SurgeGuard orchestration layer (`07_Backend.md`).

Receives structured results from the AI Pipeline, applies operational logic,
persists Crowd Events, and delivers real-time updates to the Command Center.
It performs no AI analysis of its own (`07:17-23`).

## Architecture

A **modular monolith**. `07:108` describes a service-oriented architecture;
for a single-camera prototype that is read as seven service *modules* inside one
FastAPI application, not seven deployables. Identical modularity, none of the
distributed-systems cost, and extractable later
(`Claude_Responses/00_Architecture_Review.md`, Accepted Decision A6).

Layers may import downward and never upward:

```
api/           HTTP and WebSocket surface - thin, delegates immediately
services/      operational logic
repositories/  data access - the only place that issues queries
models/        persistence schema
core/          config, logging, errors, event bus  (imports nothing above)
```

Three boundary modules sit outside that stack:

- `realtime/` — owns the WebSocket contract. Nothing else writes to a socket.
- `ingest/` — owns the AI Pipeline contract. Implements `PerceptionSink` and
  `AnalysisSink`.
- `workers/` — owns work that outlives a request. Runs and supervises the
  pipeline.

Modules that would otherwise depend on each other publish and subscribe on
`core.event_bus` instead.

## The AI Pipeline

The pipeline runs inside this process, supervised by `PerceptionWorker`, and
delivers results through `InProcessPerceptionSink`:

```
FrameSource ─► [ AI PIPELINE ] ─► InProcessPerceptionSink ─┬─► PerceptionStateService
                                                           └─► event bus
```

The dependency direction is always `backend → surgeguard_ai`. The pipeline is
handed a sink and never learns what kind it is, so moving it onto its own host
later is a sink swap and no pipeline change (`07:99-103`).

**Startup does not wait for it.** Loading model weights takes seconds; the
worker returns as soon as its supervision task is scheduled, and the API answers
throughout. **Failures do not take the backend down**: a camera that cannot be
opened is retried with a doubling backoff, and the rest of the platform keeps
serving.

Set `SURGEGUARD_PIPELINE_ENABLED=false` to run the API without a camera or GPU.

## Running

```bash
# From the repository root, with the shared virtual environment active:
uvicorn app.main:app --reload --app-dir backend
```

`/docs` lists every route with its schema. The groups, all under `/api/v1`:

| Area | Routes |
|---|---|
| Health | `health/live`, `health/ready` (public); `system-health`, `system-info` |
| Auth | `auth/status` (public), `auth/setup`, `auth/login`, `auth/logout`, `auth/me`, `auth/me/password`, `auth/sessions`; `users` (admin) |
| Perception and pipeline | `perception/latest`, `perception/status`, `pipeline/status` |
| Cameras | `cameras`, `cameras/{id}` and its `status`, `analytics`, `decisions`, `operations`, `stream`, `snapshot`, `zones`, `counters`, `retry`, `test-connection` |
| Intelligence | `intelligence/current`, `intelligence/evidence/history`, `decisions/current`, `decisions/history`, `decisions/timeline` |
| Site and queues | `global/analytics`, `global/forecast`, `global/topology`, `queue/current`, `queue/prediction`, `recommendations`, `counters`, `zones` |
| History | `history/cameras/{id}`, `history/site`, `history/summary` |
| Simulation | `simulation/run`, `simulation/state`, `simulation/reset` |
| Alert hardware | `hardware`, `hardware/test` |

The Command Center socket is `/ws/command-center`. A `503` from a data route
means "not available yet" (no frame analysed, no queue configured), not a
fault; the frontend shows it as a waiting state.

## Authentication

On by default (`SURGEGUARD_AUTH_ENABLED`). Operators sign in with an email and
password; the session is an HttpOnly, `SameSite=Lax` cookie (`Secure` in
production), so the same credential reaches REST, the socket and the MJPEG
`<img>` streams without any token in JavaScript.

- **First run:** while no account exists, `GET auth/status` reports
  `setup_required` and `POST auth/setup` creates the first administrator. It is
  open to whoever reaches the deployment first, as is usual for self-hosted
  tools, so complete it before exposing the service.
- **Roles:** `ADMIN` may add, edit and remove cameras, save zones and site
  topology, and manage operators. `OPERATOR` has every read, counters, retries,
  connection tests, simulation and operator actions. The last active
  administrator cannot be demoted or deactivated.
- **Passwords:** PBKDF2-SHA256, at least 12 characters. Failed sign-ins are rate
  limited per client address and email. Changing a password ends the account's
  other sessions.
- **Socket:** without a valid session it accepts, then closes with code `4401`.
  Signing out closes that session's sockets.

## Operator actions

`POST cameras/{id}/operations` records `ACKNOWLEDGE`, `LOG_ACTION` (with an
optional note) or `CLOSE` against the camera's Operational State. Each is written
to the Timeline with the operator's name and broadcast as `state.updated`. An
action that does not apply in the current state is refused with `409` and a
reason. Recovery to Monitoring stays automatic once conditions are stable.

## History

`HistoryRecorder` folds each camera's and the site's analysis into
`SURGEGUARD_HISTORY_BUCKET_SECONDS` buckets in the database: CSI mean, min and
max, time in each status band, people, queue length and wait, confidence and the
share of estimated counts. It stores **aggregates only, never frames**, and
prunes past `SURGEGUARD_HISTORY_RETENTION_DAYS`. The `history/*` routes query a
range of up to 31 days in one Source Mode; LIVE and DEMO records are never mixed.

The Timeline, evidence history and guidance history remain in-memory and are
lost on restart; only the aggregated history above is persisted.

## Streams and snapshots

`cameras/{id}/stream?layers=` is the annotated MJPEG feed. `cameras/{id}/snapshot`
returns one JPEG captured after the request (`no-store`); an empty `layers=`
gives a clean frame, which the zone editor draws over. Camera tiles poll
snapshots instead of holding streams open, because a browser allows only about
six connections per origin.

## Alert hardware

`app/hardware/` drives an Arduino RGB LED and buzzer over USB serial from the
Decision Engine's reports: `NORMAL`, `WARNING`, `CRITICAL`, or `NO_DATA` when no
camera has a current report. It wakes on every report, reconnects after an unplug,
and exposes `GET /api/v1/hardware` plus a bounded test mode
(`POST`/`DELETE /api/v1/hardware/test`). Off unless
`SURGEGUARD_HARDWARE_ENABLED=true`. Wiring, firmware and protocol are in
`hardware/README.md`.

## Serving the frontend

When `frontend/dist` exists (`npm run build` in `frontend/`), this process
serves it at `/`, so a deployment is one origin and one process. Client routes
fall back to `index.html` (`no-cache`), hashed assets are cached as immutable,
and `/api`, `/ws`, `/docs`, `/redoc` and `/openapi.json` are never shadowed.
Set `SURGEGUARD_FRONTEND_DIST_DIR` to serve a build from elsewhere.

## Migrations

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

The database URL comes from application settings, not `alembic.ini`, so
migrations and the running application cannot disagree about which database
they are pointed at.

## Tests

```bash
pytest
```

The suite runs without a camera, a GPU or model weights: the pipeline is
disabled in test settings and worker behaviour is exercised against doubles. A
suite that silently required hardware would pass on one machine and hang on
every other.
