# surgeguard-frontend

The SurgeGuard landing page and Command Center: one React application sharing
one design system, talking to the FastAPI backend on the same origin.

## Running

```bash
npm install
cp .env.example .env.local   # point VITE_BACKEND_URL at the backend if it is not on :8000
npm run dev                   # http://127.0.0.1:5180
```

The dev server proxies `/api` and `/ws` to `VITE_BACKEND_URL`, so session
cookies, the Command Center socket and MJPEG streams behave exactly as they do
in production. For production, `npm run build` writes `dist/`, which the backend
serves itself at `/` (see `backend/README.md`, "Serving the frontend").

| Script | Does |
|---|---|
| `npm run dev` | Vite dev server with the API proxy |
| `npm run build` | Type-check, then build `dist/` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | oxlint |
| `npm test` | Vitest (jsdom) once; `npm run test:watch` to watch |

No variable here is a secret, and the interface stores no credentials: sign-in
lives in the backend's HttpOnly cookie.

## Stack

Vite 8, React 19, TypeScript 7, React Router 8 (data mode, route-level code
splitting), Tailwind CSS 4, TanStack Query 5, Zustand 5, Radix primitives,
Motion, d3-scale and d3-shape for hand-built SVG charts, zod with
react-hook-form, Vitest with Testing Library.

## Layout

```
src/
  app/          router, providers, query client, route error boundary
  api/          fetch client (envelope unwrapping, typed errors), endpoints, query keys
  realtime/     socket client, pure reducers, Zustand store, fallback polling, camera figures
  features/     one folder per page: landing, auth, shell, command-center, cameras, site,
                queues, alerts, timeline, analytics, simulation, system, settings, profile
  components/   shared domain components: charts, data (Panel, tables, states), intel,
                status, video, brand
  ui/           design-system primitives (Button, Field, Dialog, Tabs, Select, ...)
  lib/          formatting, labels, status semantics, small hooks
  types/        mirrors of the backend contracts
  styles/       global.css - every design token
```

Data logic stays out of presentation: pages read the store or a query and pass
plain values down; `components/` and `ui/` fetch nothing.

## How data flows

- **Live state** comes over `/ws/command-center` into the Zustand store
  (`src/realtime`). The client resyncs once per sequence gap, answers
  heartbeats, marks data stale after the snapshot's `stale_after_seconds`,
  reconnects with capped exponential backoff, and on close code `4401` sends the
  operator to sign-in.
- **While the socket is down**, `useFallbackPolling` reads the same data over
  REST every 5 s (only while the tab is visible) and writes it through the same
  reducers. It stops the moment the socket is live again.
- **Everything else** (history, zones, users, simulation) goes through TanStack
  Query.
- **A camera's figures** are read through `cameraFigures`: an offline or disabled
  camera shows none (never its last values), and figures that stopped arriving
  carry a stale badge with their age.
- **Connection budget:** at most two MJPEG streams are open at once; camera
  tiles poll snapshots and pause off-screen or in a hidden tab.

## Design rules worth knowing before changing a screen

- Colour is reserved for meaning. The five Operational Status hues (`stable`,
  `observe`, `attention`, `high`, `critical`) appear only for status, always with
  a label; everything else, chart series included, uses the ink scale.
- The app never animates numbers; only the landing page may.
- Density that is not calibrated is "relative", never p/m²; speed is m/s only on
  a calibrated camera; estimated counts are always labelled; simulated results
  are always labelled; a `503` is a waiting state, not an error.
- Charts draw in measured pixels (`useElementWidth`) and carry an accessible
  title; history time series also offer a table view.
- No all-caps labels, no "A · B" meta strings, no arrows on CTAs.
