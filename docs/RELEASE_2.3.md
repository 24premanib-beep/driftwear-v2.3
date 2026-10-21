# DriftWear 2.3: release notes

A rebuild of the web interface into one coherent, role-aware product on top of release 2.2. The model, the
detectors, the pipeline, the database schema, authentication and deployment are unchanged. The README is the
reference; this file lists what changed and why.

## What changed for people using it

- **One navigation, grouped by purpose.** Overview, Model intelligence, Data operations, System, Administration
  and Help. Each role sees only the groups it can use; opening a page you may not use explains why. Breadcrumbs and
  page titles come from the same list (`src/lib/nav.js`).
- **The central question answered first.** The dashboard opens with a verdict ("No change right now.",
  "Possibly. Errors are rising.", "Yes. Concept drift is confirmed.") taken from the detector, the Stable → Warning → Drift track, the
  health score with its breakdown, and "What the system did" (drift, adaptations, refreshes, rollbacks).
- **A state rail on every page**: stream, detector state, active model, detector and recent accuracy, updated over
  the WebSocket. On simulation pages it is hatched and says so.
- **Live data journey**: an event is followed through seven stages (received, validated, predicted, recorded,
  outcome, error, detector) with the server's own trace. Duplicates (409) offer the original prediction or a new
  event ID; rejections (422) list every problem.
- **Predictions explain themselves**: "Starting point (training average) + inputs = confidence", a close-call note
  when the runner-up is within five points, and the outcome form right under the result.
- **Adaptation and performance merged** into one page with two tabs; `/app/performance` redirects there.
- **Drift performance** reads as before / during / after with a recovery verdict that stays "Measuring recovery"
  until enough outcomes exist.
- **Model registry**: lineage, version detail (validation and live metrics never mixed), comparison of any two
  versions with better / worse marked, activation and rollback history, and a rollback dialog that requires a
  reason and reports what the server confirmed.
- **Data operations**: drag-and-drop upload with strict / partial mode, the expected columns taken from the
  server's rules, a report per upload (linkable as `/app/validation?upload=<id>`), and "queued, not yet predicted".
- **System monitoring** grouped into application, machine learning, concept drift, model performance, data,
  pipeline and system health; unmeasured values show N/A.
- **Simulation**: a ten-step guided demonstration whose steps complete from server state, kept visibly separate
  from live data.
- **How DriftWear works**: twelve topics, each with a small figure, a sticky table of contents and an FAQ; public
  at `/how-it-works`.
- **Notifications**: the notification center opens above everything (it was clipped by the header before), has
  category tabs and "New" markers, and every item links to the page that explains it. Toasts carry the key facts
  and a "View details" link.
- **Sign-in states**: a revoked or expired session returns to sign-in with the server's reason; an unreachable
  server shows a retry screen instead of signing you out.

## Visual language

Warm neutral canvas, charcoal text, deep navy for structure and one plum accent. Archivo (variable width) for
everything, condensed for headings and figures. No gradients, no emoji: states, health bands and severities always
pair an icon with a word. Tokens live in `tailwind.config.js`, component classes in `src/index.css`.

## API and backend changes

1. **A rollback needs a reason.** `POST /api/models/rollback` now requires `reason` (3–500 characters after
   trimming); a missing, blank or one-character reason returns 422 with `details[0].field == "reason"`.
   `POST /api/models/{v}/activate` requires the same when the target is older than the active version (that is a
   rollback); activating a newer version keeps `reason` optional. Nothing changes when the request is refused.
   The UI always sent a reason; this makes the server enforce it.
2. **Model health text names the actual reason for "Degraded"**: an adaptation is running, drift was confirmed, or
   the model is underperforming (in which case it says it is only retrained once drift is confirmed). It previously
   said "adaptation is required" in all three cases. Same fields (`band`, `text`, `emoji`), same scores.
3. Version 2.3.0 (`backend/app/__init__.py`, `frontend/package.json`).

No database migration. No new dependencies, frontend or backend.

## Frontend code

- `src/lib/endpoints.js` (new): every API path in one place.
- `src/lib/nav.js` (new): navigation groups, access levels, breadcrumbs.
- `useApi` applies overlapping refreshes in order instead of discarding all but the newest, so figures keep moving
  while the pipeline is busy; `useLiveRefresh` throttles instead of debouncing for the same reason.
- Timeline charts thin out labels of clustered drift and version markers (the lines are all still drawn).
- Removed: `components/EventFeed.jsx` (replaced by `ActivityFeed`), `pages/Performance.jsx` (merged into
  Adaptation & performance).

## Tests

- `backend/tests/test_api_demo_scenario.py`: missing, blank and one-character rollback reasons → 422; activating
  an older version without a reason → 422 on `reason`, active version unchanged.
- `backend/tests/test_api_drift.py`: the activate-to-older case now sends a reason and checks the 422 without one.
- `backend/tests/test_model_health.py`: the Degraded text names the reason.
- `frontend/src/lib/__tests__/*`: updated for the emoji-free labels, notification links and the seven-stage
  journey.

Results of the runs actually performed for this release are in the README under *Verification status*.
