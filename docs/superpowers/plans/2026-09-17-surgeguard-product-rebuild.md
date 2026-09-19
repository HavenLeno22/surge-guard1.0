# SurgeGuard Product Rebuild Implementation Plan

> **Progress (2026-09-17 01:05 IST):** Phases A, B and C are complete (352 backend tests passing). Phase D is partly done: config files, tokens and types only, with no `src/main.tsx` yet. Current status, the exact changes made and next steps are in `HANDOFF.md` at the project root. Read it before continuing.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a new SurgeGuard frontend (landing page, authentication, Command Center app) and
the backend changes it needs: auth, realtime fixes, history, snapshots and operator actions.

**Architecture:** The FastAPI modular monolith gains an `auth` module (cookie sessions in SQLite
via Alembic), a `HistoryRecorder` subscriber, and small realtime and route additions. A new Vite +
React 19 SPA in `frontend/` talks to it same-origin: REST through TanStack Query, live state
through one WebSocket into a Zustand store, and MJPEG plus snapshots for video.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, pytest | Vite 8, React 19.3,
TypeScript 7, React Router 8, Tailwind 4.3, Zustand 5, TanStack Query 5, radix-ui, motion 13,
d3-scale/d3-shape, zod 4, react-hook-form, Vitest 5, oxlint.

**Spec:** `docs/superpowers/specs/2026-09-17-surgeguard-product-rebuild-design.md`

## Global Constraints

- Never modify `backend/.env` or anything under the user's `data/`. Tests and live runs use env overrides and scratch paths.
- Existing REST paths, bodies, response envelopes and WS message shapes keep their contracts; changes are additive.
- Terminology verbatim: Crowd Stability Index (CSI), Operational Status, Operational State, Operational Intelligence Report (OIR), Queue Intelligence, Evidence, Timeline, Camera Network, Source Mode.
- CSI is 0–100, higher = more stable; bands ≥80 STABLE, ≥60 OBSERVE, ≥40 ATTENTION_REQUIRED, ≥20 HIGH_ALERT, <20 CRITICAL.
- Operational State never uses the status palette. ESTIMATED counts are never shown as tracked. `is_metric=false` density is labelled relative, never p/m².
- 503 = waiting/degraded state, 404 on `/simulation/state` = "not run yet", stale data always visibly marked, simulation always labelled SIMULATION.
- Status colours: STABLE `#3CCB85`, OBSERVE `#5AB8FA`, ATTENTION `#EFDD55`, HIGH_ALERT `#F99442`, CRITICAL `#E8435F` (text `#F26F86`).
- Neutrals: canvas `#0B0E11`, surface-1 `#11161B`, surface-2 `#171D23`, surface-3 `#1E252C`, line `#242C34`, line-strong `#33404B`, ink-faint `#5D6A76`, ink-muted `#8A96A1`, ink-secondary `#B3BCC4`, ink `#E6EAED`, ink-strong `#F7F9FA`.
- Font: Archivo variable (wght + wdth), readouts wdth 75 tabular. No all-caps labels, no middle-dot meta strings, no decorative accent hue.
- No fabricated data anywhere. Illustrations and examples carry a visible label.
- Accessibility floor: visible focus, labelled icon buttons, ≥44px touch targets on mobile, reduced motion respected, colour never the only signal.
- No VCS in this project (not a git repository), so there are no commit steps. Checkpoints are the verification commands.

---

## File structure

### Backend (modified or new)

| Path | Responsibility |
|---|---|
| `backend/app/core/config.py` | + auth, session, migration and frontend-dist settings |
| `backend/app/core/exceptions.py` | + `UnauthorizedError`, `ForbiddenError`, `TooManyRequestsError` |
| `backend/app/db/session.py` | `DatabaseManager.session()` context; migrations runner |
| `backend/app/db/migrate.py` | run Alembic `upgrade head` for a given URL (thread) |
| `backend/alembic/env.py` | honour `config.attributes["database_url"]` |
| `backend/alembic/versions/0001_auth_and_history.py` | `user_account`, `user_session`, `observation_bucket` |
| `backend/app/models/auth.py` | `UserAccount`, `UserSession` |
| `backend/app/models/history.py` | `ObservationBucket` |
| `backend/app/models/__init__.py` | import models |
| `backend/app/auth/passwords.py` | PBKDF2 hash/verify |
| `backend/app/auth/tokens.py` | token generation + SHA-256 |
| `backend/app/auth/service.py` | `AuthService`: setup, login, sessions, users |
| `backend/app/auth/rate_limit.py` | `LoginRateLimiter` |
| `backend/app/auth/dependencies.py` | `current_principal`, `require_operator`, `require_admin`, `Principal` |
| `backend/app/schemas/auth.py` | request/response models |
| `backend/app/api/v1/auth.py` | `/auth/*` routes |
| `backend/app/api/v1/users.py` | `/users/*` routes |
| `backend/app/api/v1/history.py` | `/history/*` routes |
| `backend/app/api/v1/operations.py` | `/cameras/{id}/operations`, `/cameras/{id}/decisions` |
| `backend/app/services/history_recorder.py` | bucket aggregation + writes + pruning |
| `backend/app/services/history_query.py` | reads, downsampling, summary |
| `backend/app/services/operational_state.py` | operator transitions |
| `backend/app/services/decision_service.py` | `IssuedReport`, state-change dispatch, operator actions |
| `backend/app/realtime/publisher.py` | camera_id on OIR, `state.updated`, `health.updated` |
| `backend/app/realtime/snapshot.py` | `camera_decisions` |
| `backend/app/realtime/envelope.py` | `STATE_UPDATED` type |
| `backend/app/core/event_bus.py` | `OPERATIONAL_STATE_CHANGED` |
| `backend/app/streaming/live_stream.py` | `snapshot()` |
| `backend/app/streaming/annotator.py` | new status BGR palette |
| `backend/app/api/v1/cameras.py` | snapshot route; admin guards |
| `backend/app/api/router.py` | wire routers + dependencies |
| `backend/app/api/v1/realtime.py` | socket auth (4401) |
| `backend/app/api/deps.py` | settings/database from app state |
| `backend/app/main.py` | database from settings, migrations, recorder, publisher health, static SPA |
| `backend/app/web/spa.py` | serve `frontend/dist` with fallback |
| `backend/tests/conftest.py` | `auth_enabled=False` for legacy fixtures + auth-enabled fixture |
| `backend/tests/integration/test_auth_api.py` etc. | new tests |

### Frontend (all new, `frontend/`)

```
frontend/
  index.html  package.json  vite.config.ts  tsconfig.json  tsconfig.node.json  .env.example  oxlintrc.json
  public/favicon.svg
  src/main.tsx
  src/app/{router.tsx,providers.tsx,queryClient.ts,RouteError.tsx}
  src/styles/{tokens.css,global.css}
  src/lib/{cn.ts,format.ts,labels.ts,status.ts,time.ts,ringBuffer.ts,hooks/*.ts}
  src/types/{contracts.ts,api.ts,realtime.ts,auth.ts,history.ts}
  src/api/{client.ts,queryKeys.ts,endpoints/*.ts}
  src/realtime/{socketClient.ts,store.ts,reducers.ts,RealtimeProvider.tsx,useFallbackPolling.ts,selectors.ts}
  src/ui/*.tsx                      (primitives)
  src/components/{brand,status,data,charts,video,layout,feedback}/*.tsx
  src/features/landing/**            (page, sections, hero simulation)
  src/features/auth/**               (login, setup, gate, session hooks)
  src/features/shell/**              (AppShell, Sidebar, TopBar, StatusBar)
  src/features/command-center/**
  src/features/site/**  cameras/**  queues/**  alerts/**  timeline/**  analytics/**  simulation/**  system/**  settings/**  profile/**
```

---

## Phase A: Backend foundation

### Task A1: App-scoped settings and database; auto-migration

**Files:**
- Modify: `backend/app/core/config.py` (add fields after `history_baseline_min_samples`)
- Modify: `backend/app/db/session.py` (add `DatabaseManager.session()`; keep module globals)
- Create: `backend/app/db/migrate.py`
- Modify: `backend/alembic/env.py`
- Modify: `backend/app/api/deps.py` (`get_app_settings`, `get_app_database`, `get_app_session`; `SettingsDep`/`DatabaseDep`/`SessionDep` use them)
- Modify: `backend/app/main.py` (lifespan: `DatabaseManager(settings)`, `await run_migrations(settings)` when `database_auto_migrate`)
- Test: `backend/tests/integration/test_database_setup.py`

**Interfaces:**
- Produces: `Settings.auth_enabled: bool = True`, `session_ttl_hours: float = 12.0`, `session_cookie_name: str = "surgeguard_session"`, `session_cookie_secure: bool | None = None`, `login_max_failures: int = 5`, `login_lockout_seconds: float = 300.0`, `database_auto_migrate: bool = True`, `frontend_dist_dir: Path = PROJECT_ROOT / "frontend" / "dist"`, property `cookie_secure -> bool`.
- Produces: `DatabaseManager.session() -> AsyncContextManager[AsyncSession]` (commit/rollback/close).
- Produces: `async def run_migrations(database_url: str) -> None` in `app/db/migrate.py`.
- Produces: `app.state.database` is the app's `DatabaseManager`; deps read it.

- [ ] **Step 1: Write failing test**

```python
async def test_lifespan_uses_the_configured_database(client, settings):
    ready = await client.get("/api/v1/health/ready")
    assert ready.json()["database"] is True
    db_path = settings.database_url.split("///", 1)[1]
    assert Path(db_path).exists()          # created by our URL, not ./surgeguard.db

async def test_migrations_create_the_schema(client, settings):
    import sqlite3
    db_path = settings.database_url.split("///", 1)[1]
    tables = {r[0] for r in sqlite3.connect(db_path).execute(
        "select name from sqlite_master where type='table'")}
    assert {"user_account", "user_session", "observation_bucket", "alembic_version"} <= tables
```

- [ ] **Step 2: Run** `cd backend && ../.venv/Scripts/python -m pytest tests/integration/test_database_setup.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** the settings, `session()`, `migrate.py` (`alembic.config.Config(ini)`, `cfg.attributes["database_url"] = url`, `command.upgrade(cfg, "head")` via `asyncio.to_thread`), the env.py URL override, deps and lifespan changes. The migration itself lands in A2, so create the version file there and run the tests after A2.
- [ ] **Step 4: Run the full existing suite** `python -m pytest -q`. Expect the same pass count as the baseline.

### Task A2: Models and migration 0001

**Files:**
- Create: `backend/app/models/auth.py`, `backend/app/models/history.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0001_auth_and_history.py`

**Interfaces:**
- Produces: `UserAccount(id, email, display_name, password_hash, role, is_active, last_login_at, created_at, updated_at)`; `UserSession(id, user_id, token_hash, created_at, expires_at, last_seen_at, user_agent, ip_address, revoked_at)`; `ObservationBucket(id, camera_id, bucket_start, bucket_seconds, source_mode, samples, csi_mean, csi_min, csi_max, status_worst, status_last, status_samples(JSON), confidence_mean, people_mean, people_max, estimated_samples, density_max, density_is_metric, queue_length_mean, queue_length_max, wait_minutes_mean, arrival_rate_mean, service_rate_mean, degraded_samples, cameras_contributing_min, created_at)` with unique `(camera_id, bucket_start, bucket_seconds, source_mode)` and index `(camera_id, bucket_start)`.
- Role enum values: `"ADMIN"`, `"OPERATOR"`.

- [ ] **Step 1:** Write the models with `UUIDPrimaryKeyMixin`/`TimestampMixin` and a hand-written migration (batch-safe, named constraints).
- [ ] **Step 2: Run** A1 tests. Expect PASS. Then run `python -m pytest -q` for the full suite.

### Task A3: Password hashing and tokens

**Files:** Create `backend/app/auth/__init__.py`, `passwords.py`, `tokens.py`. Test: `backend/tests/unit/test_auth_primitives.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str` (format `pbkdf2_sha256$600000$<b64salt>$<b64hash>`), `verify_password(password: str, encoded: str) -> bool`, `needs_rehash(encoded: str) -> bool`, `new_session_token() -> str` (43-char urlsafe), `token_digest(token: str) -> str` (sha256 hex).

- [ ] **Step 1: Failing tests**

```python
def test_hash_round_trip_and_rejects_wrong_password():
    encoded = hash_password("correct horse battery")
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("wrong", encoded)

def test_hashes_are_salted():
    assert hash_password("same password here") != hash_password("same password here")

def test_malformed_hash_never_verifies():
    assert not verify_password("anything", "not-a-hash")

def test_token_digest_is_stable_and_hides_the_token():
    token = new_session_token()
    assert len(token) >= 43 and token_digest(token) == token_digest(token)
    assert token not in token_digest(token)
```

- [ ] **Step 2:** Run, expect FAIL. **Step 3:** Implement with `hashlib.pbkdf2_hmac`, `secrets.token_bytes`, `hmac.compare_digest`. **Step 4:** Run, expect PASS.

### Task A4: AuthService, rate limiter, principal dependencies

**Files:** Create `backend/app/auth/service.py`, `rate_limit.py`, `dependencies.py`, `backend/app/schemas/auth.py`; modify `backend/app/core/exceptions.py`, `backend/app/api/errors.py` (add status codes 401/403/429 mapping already partly present). Test: `backend/tests/unit/test_login_rate_limiter.py`

**Interfaces:**
- Produces exceptions: `UnauthorizedError(401,"UNAUTHORIZED")`, `InvalidCredentialsError(401,"INVALID_CREDENTIALS")`, `ForbiddenError(403,"FORBIDDEN")`, `TooManyAttemptsError(429,"TOO_MANY_ATTEMPTS", retry_after_seconds)`, `SetupCompleteError(409,"SETUP_COMPLETE")`. All `expected=True`.
- Produces `Principal(user_id: str | None, email: str | None, display_name: str, role: str, session_id: str | None, authenticated: bool)`.
- Produces `AuthService(database: DatabaseManager, settings: Settings)` with async `setup_required() -> bool`, `create_first_admin(email, display_name, password) -> UserAccount`, `authenticate(email, password) -> UserAccount`, `start_session(user, user_agent, ip) -> tuple[str, UserSession]`, `resolve(token) -> tuple[UserAccount, UserSession] | None`, `revoke(session_id, user_id)`, `list_sessions(user_id)`, `change_password(user_id, current, new, keep_session_id)`, `update_profile(user_id, display_name)`, `list_users()`, `create_user(email, display_name, password, role)`, `update_user(user_id, role?, is_active?, display_name?, acting_user_id)`.
- Produces `LoginRateLimiter(max_failures, window_seconds)` with `check(key) -> float | None` (seconds to wait), `record_failure(key)`, `reset(key)`.
- Produces FastAPI deps: `current_principal(request) -> Principal | None`, `require_operator(connection: HTTPConnection) -> Principal`, `require_admin(...) -> Principal`, and `resolve_socket_principal(websocket) -> Principal | None`.
- When `settings.auth_enabled` is false, `require_*` return `Principal(None,None,DEFAULT_OPERATOR_NAME,"ADMIN",None,False)`.

- [ ] **Step 1: Failing tests** for the limiter:

```python
def test_locks_after_max_failures_and_reports_wait():
    clock = FakeClock()
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.check("k") is None
        limiter.record_failure("k")
    wait = limiter.check("k")
    assert wait is not None and 0 < wait <= 60
    clock.advance(61)
    assert limiter.check("k") is None

def test_reset_clears_failures():
    limiter = LoginRateLimiter(max_failures=1, window_seconds=60)
    limiter.record_failure("k"); limiter.reset("k")
    assert limiter.check("k") is None
```

- [ ] **Step 2–4:** Run → FAIL → implement → PASS.

### Task A5: Auth and users routes; protect the API and socket

**Files:** Create `backend/app/api/v1/auth.py`, `backend/app/api/v1/users.py`; modify `backend/app/api/router.py`, `backend/app/api/v1/system.py`, `backend/app/api/v1/realtime.py`, `backend/app/api/v1/cameras.py` (admin guards on POST/PATCH/DELETE and zones PUT), `backend/app/api/v1/global_intel.py` (admin on PUT topology), `backend/app/api/v1/queue.py` (admin on POST /zones), `backend/app/main.py` (auth service + limiter on state); `backend/tests/conftest.py` (legacy fixture `auth_enabled=False`; new `auth_settings`/`auth_client` fixtures). Test: `backend/tests/integration/test_auth_api.py`

**Interfaces:**
- `GET /api/v1/auth/status` → `{auth_enabled: bool, setup_required: bool, user: UserRead | null}`
- `POST /api/v1/auth/setup` `{email, display_name, password}` → 201 `UserRead`, sets cookie
- `POST /api/v1/auth/login` `{email, password}` → `UserRead`, sets cookie
- `POST /api/v1/auth/logout` → `null`, clears cookie
- `GET|PATCH /api/v1/auth/me`, `POST /api/v1/auth/me/password` `{current_password,new_password}`
- `GET /api/v1/auth/sessions` → `[SessionRead]` (`current: bool`), `DELETE /api/v1/auth/sessions/{id}`
- `GET|POST /api/v1/users`, `PATCH /api/v1/users/{id}` (ADMIN)
- `UserRead = {id, email, display_name, role, is_active, last_login_at, created_at}`
- Socket: invalid session gets accept then `close(4401, "Authentication required")`.

- [ ] **Step 1: Failing tests** (auth-enabled app via `auth_client`):

```python
async def test_status_reports_setup_required_on_a_fresh_deployment(auth_client):
    body = (await auth_client.get("/api/v1/auth/status")).json()["data"]
    assert body == {"auth_enabled": True, "setup_required": True, "user": None}

async def test_protected_routes_refuse_without_a_session(auth_client):
    r = await auth_client.get("/api/v1/cameras")
    assert r.status_code == 401 and r.json()["error_code"] == "UNAUTHORIZED"

async def test_probes_stay_public(auth_client):
    assert (await auth_client.get("/api/v1/health/live")).status_code == 200

async def test_setup_creates_admin_and_signs_in_then_closes(auth_client):
    r = await auth_client.post("/api/v1/auth/setup", json=ADMIN)
    assert r.status_code == 201 and r.json()["data"]["role"] == "ADMIN"
    assert "surgeguard_session" in r.cookies
    assert (await auth_client.get("/api/v1/cameras")).status_code == 200
    again = await auth_client.post("/api/v1/auth/setup", json=ADMIN)
    assert again.status_code == 409 and again.json()["error_code"] == "SETUP_COMPLETE"

async def test_login_logout_cycle_and_wrong_password(auth_client):
    await auth_client.post("/api/v1/auth/setup", json=ADMIN)
    await auth_client.post("/api/v1/auth/logout")
    assert (await auth_client.get("/api/v1/cameras")).status_code == 401
    bad = await auth_client.post("/api/v1/auth/login", json={"email": ADMIN["email"], "password": "nope-nope-nope"})
    assert bad.status_code == 401 and bad.json()["error_code"] == "INVALID_CREDENTIALS"
    ok = await auth_client.post("/api/v1/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert ok.status_code == 200
    assert (await auth_client.get("/api/v1/auth/me")).json()["data"]["email"] == ADMIN["email"]

async def test_repeated_failures_are_rate_limited(auth_client): ...   # 5 failures then 429 TOO_MANY_ATTEMPTS

async def test_operator_cannot_manage_cameras_or_users(auth_client): ...  # admin creates OPERATOR; operator POST /cameras -> 403

async def test_password_change_revokes_other_sessions(auth_client): ...

def test_socket_without_session_is_closed_with_4401(auth_app): ...  # TestClient websocket_connect -> receive close code 4401

async def test_legacy_behaviour_when_auth_disabled(client):
    assert (await client.get("/api/v1/cameras")).status_code == 200
```

- [ ] **Step 2–4:** Run → FAIL → implement → PASS. Run the full suite; everything passes.

## Phase B: Realtime correctness, operator actions, snapshots

### Task B1: Camera-scoped OIR, state push, snapshot decisions, camera decisions route

**Files:** Modify `backend/app/core/event_bus.py`, `backend/app/services/decision_service.py`, `backend/app/realtime/envelope.py`, `backend/app/realtime/publisher.py`, `backend/app/realtime/snapshot.py`; create `backend/app/api/v1/operations.py` (GET decisions only in this task); modify router. Test: `backend/tests/unit/test_realtime_decisions.py`

**Interfaces:**
- `DomainEvent.OPERATIONAL_STATE_CHANGED = "operational_state.changed"`
- `@dataclass(frozen=True) IssuedReport(camera_id: str, report: OperationalIntelligenceReport)`
- `@dataclass(frozen=True) StateChange(camera_id: str, state: OperationalState, actor: str | None = None)`
- `WSEventType.STATE_UPDATED = "state.updated"`, data `{"camera_id": str, "operational_state": str}`
- Snapshot `camera_decisions: dict[str, {"report": dict | None, "operational_state": str}]`
- `GET /api/v1/cameras/{camera_id}/decisions` → `{camera_id, report|null, operational_state, received_at|null, age_seconds|null, is_stale}`

- [ ] **Step 1: Failing tests:** a `DecisionService` for `cam-02` emits `IssuedReport(camera_id="cam-02")` on the bus; the publisher broadcasts `oir.updated` with envelope `camera_id == "cam-02"` (fake broadcaster capturing calls); a state transition dispatches `StateChange` and the publisher sends `state.updated`; `SnapshotBuilder` output contains `camera_decisions` for every runtime (fake manager).
- [ ] **Step 2–4:** Run → FAIL → implement → PASS; full suite.

### Task B2: Health push

**Files:** Modify `backend/app/realtime/publisher.py` (optional `health: SystemHealthService`, loop every 5 s, publish `health.updated` when `(component,status,detail)` tuples change), `backend/app/main.py`. Test: extend `test_realtime_decisions.py` with a fake health service whose output changes once, so exactly one message is sent.

### Task B3: Operator actions

**Files:** Modify `backend/app/services/operational_state.py` (add `apply_operator_action(action) -> OperationalState`, raises `IllegalTransition`; `observe()` keeps INVESTIGATING/RESPONDING while status non-stable), `backend/app/services/decision_service.py` (`record_operator_action(action, actor, note, rule_id, status)`), `backend/app/api/v1/operations.py` (POST). Test: `backend/tests/unit/test_operator_actions.py`, extend `backend/tests/integration/test_decisions_api.py`-style integration in new `test_operations_api.py`.

**Interfaces:**
- `OperatorAction = Literal["ACKNOWLEDGE","LOG_ACTION","CLOSE"]` (StrEnum in `operational_state.py`)
- `POST /api/v1/cameras/{camera_id}/operations` `{action, note?: str<=500, rule_id?: str}` → `{camera_id, operational_state, timeline_entry}`; 409 `CONFLICT` on illegal transition.

- [ ] **Step 1: Failing tests:**

```python
def test_acknowledge_moves_observing_to_investigating_and_persists_while_unstable():
    m = OperationalStateService()
    m.observe(OperationalStatus.HIGH_ALERT)
    assert m.apply_operator_action(OperatorAction.ACKNOWLEDGE) is OperationalState.INVESTIGATING
    assert m.observe(OperationalStatus.HIGH_ALERT) is None
    assert m.state is OperationalState.INVESTIGATING

def test_log_action_moves_to_responding_then_recovery_still_automatic():
    m = OperationalStateService(recovery_windows=2)
    m.observe(OperationalStatus.CRITICAL)
    m.apply_operator_action(OperatorAction.LOG_ACTION)
    assert m.state is OperationalState.RESPONDING
    assert m.observe(OperationalStatus.STABLE) is OperationalState.RECOVERING
    assert m.observe(OperationalStatus.STABLE) is OperationalState.MONITORING

def test_acknowledge_at_rest_is_illegal():
    with pytest.raises(IllegalTransition):
        OperationalStateService().apply_operator_action(OperatorAction.ACKNOWLEDGE)

def test_close_requires_stable_conditions():
    m = OperationalStateService()
    m.observe(OperationalStatus.OBSERVE)
    with pytest.raises(IllegalTransition):
        m.apply_operator_action(OperatorAction.CLOSE, current_status=OperationalStatus.OBSERVE)
```

- [ ] **Step 2–4:** Run → FAIL → implement → PASS; the existing `test_the_operator_driven_phases_are_never_entered_automatically` still passes.

### Task B4: Camera snapshot endpoint and video palette

**Files:** Modify `backend/app/streaming/live_stream.py` (`async def snapshot(layers, timeout_seconds=2.0) -> bytes | None`), `backend/app/api/v1/cameras.py` (`GET /{camera_id}/snapshot`), `backend/app/streaming/annotator.py` (BGR palette). Test: `backend/tests/unit/test_live_stream_snapshot.py`

- [ ] **Step 1: Failing tests:** `snapshot()` with no frames arriving returns `None` after the timeout (use 0.2 s); a frame delivered during the wait (call `handle_frame` from a task) returns JPEG bytes starting with `b"\xff\xd8"`; viewer count returns to 0 afterwards.
- [ ] **Step 2–4:** Run → FAIL → implement → PASS.

## Phase C: Historical persistence

### Task C1: HistoryRecorder

**Files:** Create `backend/app/services/history_recorder.py`; modify `backend/app/main.py`. Test: `backend/tests/unit/test_history_recorder.py`

**Interfaces:**
- `BucketAccumulator.add_analysis(analysis: AnalysisResult)`, `.add_site(report: SiteReport)`, `.to_row() -> dict`
- `HistoryRecorder(settings, database, event_bus, clock=...)`: `start()`, `async stop()` (flushes), `async flush_due(now)`, `async prune(now)`; subscribes `ANALYSIS_RECEIVED`, `SITE_UPDATED`.
- `bucket_start_for(ts: datetime, seconds: int) -> datetime` (UTC floor)

- [ ] **Step 1: Failing tests:** accumulating 3 analyses (CSI 90, 70, 50; statuses STABLE, OBSERVE, ATTENTION_REQUIRED; people 10, 20, 30) gives csi mean 70/min 50/max 90, status_worst `ATTENTION_REQUIRED`, status_samples counts, people mean 20/max 30; an analysis in the next bucket flushes a row to the DB (temp SQLite migrated); `prune` deletes rows older than retention; a DB failure is logged and does not raise.
- [ ] **Step 2–4:** Run → FAIL → implement → PASS.

### Task C2: History query routes

**Files:** Create `backend/app/services/history_query.py`, `backend/app/schemas/history.py`, `backend/app/api/v1/history.py`; modify router. Test: `backend/tests/integration/test_history_api.py`

**Interfaces:**
- `GET /api/v1/history/cameras/{camera_id}?from=&to=&resolution=&source_mode=` → `{camera_id, from, to, resolution_seconds, source_mode, points: [HistoryPoint]}`
- `GET /api/v1/history/site?...` → same with `camera_id="site"`
- `GET /api/v1/history/summary?from=&to=&source_mode=` → `{from, to, baseline_min_samples, cameras: [{camera_id, samples_buckets, baseline_available, csi_mean, csi_min, people_max, queue_length_max, wait_minutes_max, status_share: {STATUS: fraction}}], site: {...}|null}`
- `HistoryPoint = {t, samples, csi_mean, csi_min, csi_max, status_worst, status_samples, confidence_mean, people_mean, people_max, estimated_share, density_max, density_is_metric, queue_length_mean, queue_length_max, wait_minutes_mean, arrival_rate_mean, service_rate_mean, cameras_contributing_min}`
- Resolution ≥ bucket seconds; points re-aggregated by sample-weighted means; range max 31 days; `to` defaults now, `from` defaults to 24h ago.

- [ ] **Step 1: Failing tests:** seed buckets directly, then fetch with resolution 60 on 30 s buckets gives merged points with weighted means; summary `baseline_available` flips at `history_baseline_min_samples`; auth required when enabled.
- [ ] **Step 2–4:** Run → FAIL → implement → PASS.

### Task C3: Serve the built frontend

**Files:** Create `backend/app/web/spa.py`; modify `backend/app/main.py`. Test: `backend/tests/integration/test_spa.py` (temp dist with `index.html` and `assets/app.js`: `/` and `/cameras/cam-01` return index; `/assets/app.js` returns file; `/api/v1/nope` still returns the JSON 404 envelope).

## Phase D: Frontend foundation

### Task D1: Scaffold and tooling

**Files:** `frontend/package.json` (scripts `dev`, `build` = `tsc -b && vite build`, `preview`, `test` = `vitest run`, `lint` = `oxlint src`, `typecheck` = `tsc --noEmit -p tsconfig.json`), `vite.config.ts` (react plugin, tailwind plugin, alias `@` → `src`, proxy `/api` and `/ws` with `ws: true` to `process.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8000"`, vitest config jsdom), `tsconfig.json` (`module esnext`, `moduleResolution bundler`, `jsx react-jsx`, `strict`, `paths {"@/*":["./src/*"]}`, no `baseUrl`), `index.html`, `.env.example`, `public/favicon.svg`, `src/main.tsx`.
- [ ] Verify: `npm install`, `npm run typecheck`, `npm run build` all succeed on a hello route.

### Task D2: Tokens, global styles, primitives

**Files:** `src/styles/tokens.css` (primitives, then semantic tokens as CSS vars + Tailwind `@theme` mapping: `--color-canvas`, `--color-surface-1..3`, `--color-line`, `--color-line-strong`, `--color-ink-*`, `--color-status-*`, radii, fonts, easing), `src/styles/global.css`, `src/ui/{Button,IconButton,Input,Textarea,Select,Switch,Slider,Field,Tabs,Dialog,Drawer,DropdownMenu,Tooltip,Badge,Skeleton,Kbd,Spinner,VisuallyHidden}.tsx`, `src/lib/cn.ts`.
- **Interfaces:** `Button({variant: "primary"|"secondary"|"ghost"|"danger", size: "sm"|"md"|"lg", loading?, iconStart?, iconEnd?, asChild?})`; `Field({label, htmlFor, help?, error?, required?, children})`.
- [ ] Verify: a `/__kitchen-sink` dev-only route renders every primitive (removed from prod router via `import.meta.env.DEV`); take screenshots and check focus rings and contrast.

### Task D3: Types, format and label rules (TDD)

**Files:** `src/types/contracts.ts` (mirrors of every contract used: enums as string unions, StabilityAssessment, EvidenceItem/Report, OIR, QueueReport, ForecastReport, ResourcePlanReport, ZoneFlowReport, SiteReport and parts, CameraRead, SystemHealth, PipelineStatus, PerceptionRead, TimelineEntry, SimulationRead, ZoneWrite, CounterState, TopologyRead, ConnectionTestRead), `src/types/api.ts`, `src/types/realtime.ts`, `src/types/auth.ts`, `src/types/history.ts`, `src/lib/{format.ts,labels.ts,status.ts,time.ts,ringBuffer.ts}`. Tests: `src/lib/*.test.ts`

- **Interfaces:** `statusFromCsi(csi: number): OperationalStatus`; `statusMeta(status) -> {label, token, icon, rank}`; `stateMeta(state) -> {label, step}`; `formatDensity(value, isMetric) -> {value: string, unit: "p/m²" | "relative"}`; `countLabel(method) -> "Tracked" | "Estimated"`; `formatWait(minutes: number | null, queueLength) -> string` (`null && length>0` → "Not draining"); `formatAge(seconds)`; `RingBuffer<T>(capacity)` with `push`, `toArray`, `last`.

- [ ] **Step 1: Failing tests**

```ts
test("CSI bands match the frozen spec, high is stable", () => {
  expect(statusFromCsi(80)).toBe("STABLE");
  expect(statusFromCsi(79.9)).toBe("OBSERVE");
  expect(statusFromCsi(40)).toBe("ATTENTION_REQUIRED");
  expect(statusFromCsi(19.99)).toBe("CRITICAL");
});
test("relative density is never labelled per square metre", () => {
  expect(formatDensity(1.84, false)).toEqual({ value: "1.84", unit: "relative" });
  expect(formatDensity(1.84, true).unit).toBe("p/m²");
});
test("an unbounded wait reads as not draining, never a number", () => {
  expect(formatWait(null, 12)).toBe("Not draining");
  expect(formatWait(null, 0)).toBe("No queue");
});
test("ring buffer keeps only the newest items in order", () => {
  const b = new RingBuffer<number>(3); [1,2,3,4].forEach(n => b.push(n));
  expect(b.toArray()).toEqual([2,3,4]);
});
```

- [ ] **Step 2–4:** `npx vitest run src/lib` → FAIL → implement → PASS.

### Task D4: API client and endpoints

**Files:** `src/api/client.ts`, `src/api/queryKeys.ts`, `src/api/endpoints/{auth,system,cameras,site,queue,decisions,simulation,history,operations,users}.ts`. Test: `src/api/client.test.ts`

- **Interfaces:** `class ApiError extends Error { status; code; retryAfterSeconds?; get isNetwork(); get isUnavailable(); get isUnauthorized(); get isForbidden(); get isNotFound() }`; `apiRequest<T>(path, {method, body, timeoutMs=10000, signal}) -> Promise<T>` (unwraps envelope, `credentials: "same-origin"`, dispatches `window` event `surgeguard:unauthorized` on 401 except for `/auth/*`); URL helpers `streamUrl(cameraId, layers)` and `snapshotUrl(cameraId, layers, bust)`.
- [ ] **Tests:** envelope unwrapping; 503 → `isUnavailable`; fetch rejection → status 0 `isNetwork`; timeout aborts → `isNetwork`; 401 on `/cameras` fires the event, 401 on `/auth/login` does not.

### Task D5: Realtime client, store, reducers, fallback polling

**Files:** `src/realtime/socketClient.ts`, `src/realtime/reducers.ts`, `src/realtime/store.ts`, `src/realtime/selectors.ts`, `src/realtime/RealtimeProvider.tsx`, `src/realtime/useFallbackPolling.ts`. Tests: `socketClient.test.ts`, `reducers.test.ts`

- **Interfaces:**
  - `type LinkState = "idle"|"connecting"|"syncing"|"live"|"reconnecting"|"offline"|"failed"|"unauthorized"`
  - `class SocketClient { constructor(opts: {url: () => string; onEnvelope(e: Envelope): void; onState(s: LinkSnapshot): void; WebSocketImpl?; now?; setTimer?; clearTimer?}); start(); stop(); retryNow(); }`
  - `LinkSnapshot = {state, attempts, nextRetryAt: number|null, lastMessageAt: number|null, staleAfterSeconds: number, isStale: boolean, connectedAt: number|null, resyncs: number, messages: number}`
  - `applyEnvelope(state: LiveData, env: Envelope, receivedAt: number): LiveData` (pure)
  - `useLive(selector)` Zustand hook; `LiveData = {primaryCameraId, health, pipeline, perception, cameras: Record<string, CameraRead>, cameraOrder: string[], analyses: Record<string, CameraAnalysis>, decisions: Record<string, CameraDecision>, site: SiteReport|null, timeline: TimelineEntry[], trends: Record<string, TrendPoint[]>, siteTrend: TrendPoint[], snapshotAt: number|null}`
- [ ] **Step 1: Failing tests (fake WebSocket + fake timers):**
  - snapshot seq 0 then seq 2 → client sends `{"action":"resync","data":{}}` exactly once
  - heartbeat → client sends `{"action":"pong","data":{}}`
  - close 1006 → reconnect after 500 ms, then 1000 ms (± jitter ≤ 20%), attempts capped 20 → `failed`
  - close 4401 → `unauthorized`, no reconnect
  - no message for `stale_after_seconds` → `isStale` true; next message clears it
  - reducer: `timeline.appended` duplicate `entry_id` not added twice; newest first; cap 300
  - reducer: snapshot replaces cameras/analyses/decisions/timeline; `camera.status` replaces camera map preserving order by `order`
  - reducer: `oir.updated` with `camera_id` updates that camera's decision only; `state.updated` updates state only
- [ ] **Step 2–4:** Run → FAIL → implement → PASS.

### Task D6: Router, providers, auth gate, error boundaries

**Files:** `src/app/router.tsx`, `src/app/providers.tsx`, `src/app/queryClient.ts`, `src/app/RouteError.tsx`, `src/features/auth/{AuthGate.tsx,useAuthStatus.ts,LoginPage.tsx,SetupPage.tsx,authSchemas.ts}`.
- Routes: `/` landing (lazy), `/login`, `/setup`, then an `AuthGate` layout with `AppShell` wrapping all app routes (each lazy) and `*` NotFound. `AuthGate` behaviour: `status.auth_enabled && status.setup_required` → `/setup`; `auth_enabled && !user` → `/login?next=`; else render. It listens for `surgeguard:unauthorized` to invalidate the status and navigate to login.
- Forms: zod schemas (email, password ≥12 for setup/new, confirm match), inline errors, server error mapping (`INVALID_CREDENTIALS` → field-level message; `TOO_MANY_ATTEMPTS` → countdown).
- [ ] Verify: vitest for the schemas; live check against the backend (setup → app → logout → login).

## Phase E: Landing page

### Task E1: Page frame, nav, footer, brand mark
Files: `src/features/landing/LandingPage.tsx`, `LandingNav.tsx`, `LandingFooter.tsx`, `src/components/brand/{Logo.tsx,BandScale.tsx}`. The nav is sticky with a blur backdrop after 24 px of scroll; section anchors; CTA adapts to `/auth/status` (signed in → "Open the Command Center", else "Sign in"). Mobile menu in a Drawer.

### Task E2: Hero with venue simulation
Files: `src/features/landing/hero/{Hero.tsx,VenueCanvas.tsx,venueSim.ts,venueSim.test.ts}`. `venueSim.ts` is pure: `createVenue(seed)`, `step(state, dt)`, `densityGrid(state)`, `stabilityIndex(pressures, weights, available)`, where the formula is the real one. Tests: CSI formula with renormalisation (`stabilityIndex({DENSITY_PRESSURE: 50, ...}, available all)` equals the hand-computed value; one indicator unavailable renormalises). Canvas pauses offscreen (IntersectionObserver) and when the tab is hidden, clamps DPR to 2, and renders a static frame under reduced motion. Label: "Illustrative simulation, not live data".

### Task E3: Narrative sections
Files: `src/features/landing/sections/{Precursors.tsx,IndexExplorer.tsx,Pipeline.tsx,GuidanceAnatomy.tsx,QueueLayers.tsx,SiteView.tsx,Hardware.tsx,Principles.tsx,FinalCta.tsx}`, `src/features/landing/content.ts` (all copy and product facts in one file, each fact with a `source` comment pointing at the backend file it comes from). `IndexExplorer` uses the same `stabilityIndex` and band functions as E2 plus `statusMeta`. `GuidanceAnatomy` renders the app's `ActionList` and `CausesList` components with an example object labelled "Example report".

### Task E4: Landing QA
- [ ] Screens at 1440/1024/768/375; keyboard tab order; reduced motion; Lighthouse (performance ≥ 90 desktop, accessibility ≥ 95); no console errors.

## Phase F: App shell and Command Center

### Task F1: Shell
Files: `src/features/shell/{AppShell.tsx,Sidebar.tsx,TopBar.tsx,UserMenu.tsx,MobileNav.tsx,LinkIndicator.tsx,SourceModeBadge.tsx,PageHeader.tsx}`. Sidebar groups: Live (Command Center, Site, Queues, Alerts, Timeline), Network (Cameras), Insight (Analytics, Simulation), Platform (System, Settings). The alert count badge comes from the live site alerts. TopBar shows primary status pill + CSI + state strip (compact) + link indicator + clock + user menu. A global banner shows socket reconnecting/failed/offline/stale with a retry button.

### Task F2: Status and data components
Files: `src/components/status/{StatusPill.tsx,StateStrip.tsx,SeverityMark.tsx,HealthDot.tsx,CameraStatus.tsx,StaleBadge.tsx,CountMethodTag.tsx,DensityValue.tsx,ConfidenceMeter.tsx,SimulationLabel.tsx}`, `src/components/data/{Panel.tsx,StatBlock.tsx,KeyValueList.tsx,EmptyState.tsx,ErrorState.tsx,WaitingState.tsx,DataTable.tsx}`, `src/components/charts/{CsiGauge.tsx,IndicatorBars.tsx,TimeSeries.tsx,Sparkline.tsx,ForecastFan.tsx,CapacityLadder.tsx,StatusShareBar.tsx,useChartTooltip.ts}`, `src/components/video/{LiveStream.tsx,LayerToggle.tsx,SnapshotImage.tsx}`, `src/components/intel/{EvidenceList.tsx,CausesList.tsx,ActionList.tsx,TimelineList.tsx,AlertCard.tsx,QueueNow.tsx,QueueForecast.tsx,QueuePlan.tsx}`.
- `Panel` props: `{title, meta?, actions?, state?: "ready"|"loading"|"empty"|"waiting"|"error"|"stale", stateMessage?, onRetry?, children}`.
- `LiveStream` props: `{cameraId, layers, running: boolean, statusDetail?}`. It renders `<img>` only when running, shows "Connecting video…" until `onLoad`, handles `onError` by retrying with backoff up to 3 times then showing "Video unavailable" with the reason, and unmounts the `<img>` (closing the connection) when hidden.
- Chart rules: one axis, thin marks, crosshair tooltip on hover/focus, recessive grid, legends for ≥2 series, table fallback toggle on TimeSeries.

### Task F3: Command Center page
Files: `src/features/command-center/{CommandCenterPage.tsx,FocusCameraSwitcher.tsx,CsiInstrument.tsx,GuidancePanel.tsx,OperatorActions.tsx,EvidencePanel.tsx,QueueStrip.tsx,SiteSummary.tsx,SessionTrends.tsx,LiveTimeline.tsx,useFocusCamera.ts}`. The focus camera lives in the URL (`?camera=`), defaulting to primary. Operator actions call `POST /cameras/{id}/operations` with an optional note dialog and disable illegal ones by current state and status. All panels use the designed states.

## Phase G: Remaining pages

- **G1 Cameras** `src/features/cameras/{CamerasPage.tsx,CameraTile.tsx,CameraFormDrawer.tsx,ConnectionTestResult.tsx,cameraSchemas.ts}`: snapshot tiles (4 s refresh, paused when hidden or offscreen); add, edit and delete (admin); registry_error banner.
- **G2 Camera detail** `src/features/cameras/detail/{CameraDetailPage.tsx,DeviceMetrics.tsx,CameraAnalysis.tsx,ZoneFlowTable.tsx,ZoneEditor.tsx,zoneGeometry.ts,zoneGeometry.test.ts,CountersEditor.tsx}`: zone editor draws on a snapshot at analysis resolution (from `metrics.analysis_width/height`), with point add, drag and delete, close polygon, type and width fields, numeric vertex editing, validation (≥3 points, unique id pattern) and PUT on save. Tests cover polygon hit-testing and the image↔screen coordinate transforms.
- **G3 Site** `src/features/site/{SitePage.tsx,HeadcountExplainer.tsx,FlowMap.tsx,HotspotPanel.tsx,PressureList.tsx,SiteForecastPanel.tsx}`.
- **G4 Queues** `src/features/queues/{QueuesPage.tsx,QueueZoneCard.tsx,PooledQueuePanel.tsx}`.
- **G5 Alerts** `src/features/alerts/AlertsPage.tsx` and **G6 Timeline** `src/features/timeline/{TimelinePage.tsx,TimelineFilters.tsx,GuidanceHistory.tsx,EvidenceHistory.tsx}`.
- **G7 Analytics** `src/features/analytics/{AnalyticsPage.tsx,RangePicker.tsx,CameraHistoryCharts.tsx,SummaryTable.tsx}`.
- **G8 Simulation** `src/features/simulation/{SimulationPage.tsx,SimulationForm.tsx,SimulationResults.tsx,presets.ts,simulationSchema.ts}` (the schema mirrors the backend bounds, with a test).
- **G9 System** `src/features/system/SystemPage.tsx`; **G10 Settings** `src/features/settings/{SettingsPage.tsx,TopologyEditor.tsx,OperatorsPanel.tsx,PreferencesPanel.tsx,usePreferences.ts}`; **G11 Profile** `src/features/profile/ProfilePage.tsx`; **NotFound** page.

Each page task verifies: typecheck, lint, the page's tests, then a live render against the backend with screenshots at desktop and mobile.

## Phase H: Integration, polish, verification

- **H1** Create `data/scenarios/00_placeholder.mp4` in a *scratch* data dir via `scripts/make_placeholder_clip.py`. Run the backend with env overrides (`SURGEGUARD_PIPELINE_SOURCE_MODE=DEMO`, `SURGEGUARD_DEMO_VIDEO_PATH`, `SURGEGUARD_DEMO_VIDEO_LOOP=true`, `SURGEGUARD_LIVE_CAMERA_DEVICE` irrelevant, camera 2 via the DroidCam emulator URL, registry/topology/zones/data dirs and `DATABASE_URL` in scratch). Run Vite and walk every flow.
- **H2** Failure drills: stop the emulator (camera offline, site degraded, alert), kill the backend (link reconnecting → failed → retry), block the socket (fallback polling), expire the session (4401 → login), 503 panels before the first frame.
- **H3** Self-critique pass against the spec's quality bar; fix.
- **H4** Final verification: backend `pytest -q`; frontend `npm run typecheck && npm run lint && npm test && npm run build`; production mode served by FastAPI from `frontend/dist`; no console errors; README updates (`frontend/README.md`, backend README auth/history notes, `.env.example` additions).
