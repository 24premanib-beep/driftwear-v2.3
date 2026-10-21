# DriftWear

**Real-Time Concept Drift Detection and Adaptive Fashion Prediction Platform**

DriftWear predicts a customer's next fashion category in real time, and, more importantly, notices when the
model that makes those predictions has stopped describing reality. It watches the prediction-error stream,
detects **concept drift** with DDM, ADWIN or Page-Hinkley, retrains on the data after the change, versions the
new model in a registry, and pushes every step to the browser over WebSockets.

The central question the platform answers continuously:

> **Has the underlying relationship between the input features and the predicted fashion category changed over time?**

What changed in this release: [`docs/RELEASE_2.3.md`](docs/RELEASE_2.3.md).

## Problem

Fashion preferences and customer behaviour change over time. A model trained on historical data keeps answering
confidently after trends move on, just wrongly. Nothing crashes, so nobody notices until the business does.

## Solution

DriftWear continuously monitors prediction errors, detects concept drift, and adapts the model when necessary:

```
Incoming data → Prediction → Actual outcome → Prediction error → Drift detection → Drift alert
             → Model adaptation → New model version → Performance recovery
```

Every adaptation is measured (accuracy, precision, recall, F1 and error rate before drift, during drift and after
adaptation) instead of assumed, and every version can be compared and rolled back.

## Architecture

```
 Live event from any external system (POST /api/events, /batch) · prediction form · CSV upload · simulation
        │
        ▼
 Data validation ────────────── ml/validation.py: the same rules for events and CSV rows; rejected input is
        │                       stored with its errors (rejected_events / upload report) and never predicted
        ▼
 Feature processing ─────────── ml/feature_engineering.py (final price, cyclical month)
        │
        ▼
 Prediction model ───────────── Random Forest (scikit-learn) + per-prediction explanation (ml/explain.py)
        │
        ▼
 Prediction (stored with model version + explanation) ─── PostgreSQL: predictions
        │            ...later...
        ▼
 Actual outcome (POST /api/events/outcome)
        │
        ▼
 Prediction error (0 / 1) ──────────────────────────────── re-scored by the current model if it was replaced
        │
        ▼
 Concept drift detection ── DDM / ADWIN / Page-Hinkley (primary + shadow detectors)
        │
        ▼
 STABLE / WARNING / DRIFT
        │ (DRIFT)
        ▼
 Model adaptation ───────────── change point → retrain on the post-change window
        │
        ▼
 New model version (v2.0, v2.1 …) ── checksummed file in model storage
        │
        ▼
 Model registry ─────────────── PostgreSQL: model_versions, drift_events (+ compare / rollback)
        │
        ▼
 Monitoring + dashboard ─────── model health · data vs concept drift · system monitoring · audit log
        │
        ▼
 Real-time WebSocket updates ── EventBus → ConnectionManager → browser (toasts, notification center)
```

Runtime layout:

```
 Browser (React + Vite + Tailwind)
    │  HTTPS /api/*  ·  WSS /ws  ·  /health*
    ▼
 nginx (frontend container) ──► FastAPI (backend container, 1 worker)
                                  ├─ PipelineService ── in-process ordered queue ── DriftEngine (ml/)
                                  ├─ EventBus ── WebSocket fan-out + audit recorder
                                  ├─ SQLAlchemy ── PostgreSQL (Alembic migrations)
                                  └─ Model storage (local volume or S3-compatible)
```

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS, Recharts, React Router |
| Backend | FastAPI, Python 3.12, Pydantic v2, JWT (PyJWT), WebSockets |
| Database | PostgreSQL, SQLAlchemy 2, Alembic |
| ML | scikit-learn Random Forest, DDM, ADWIN, Page-Hinkley (River; built-in DDM fallback) |
| Infrastructure | Docker, Docker Compose, GitHub Actions CI, Render blueprint |

## Main features

- **Live data pathway**: any external application sends purchase events to `POST /api/events` (one) or
  `POST /api/events/batch` (up to `EVENT_BATCH_MAX`). Each event is validated, predicted and stored with the model
  version and timestamps; the actual category arrives later through `POST /api/events/outcome` (or `/outcomes` in
  bulk), linked by `event_id` or `prediction_id`. Idempotent by `event_id` (duplicates get 409). The **Live data**
  page sends test events and follows each one: received → validated → prediction → id → model version → outcome →
  error status. Simulated data never enters this path.
- **Strong data validation**: one rule set (`ml/validation.py`) for CSV rows and live events: required columns /
  fields, types, whole numbers, missing values, dates (parseable, not future, not before 2000), price > 0, no
  negative values, discount 0–90 %, the category / season / preference / target vocabularies, safe ids,
  unexpected columns (ignored with a warning) or fields (rejected). Uploads report "Upload rejected — Missing
  column: Customer_Preference" or "Validation successful — 2,100 records accepted"; rows an earlier upload already
  queued are detected by fingerprint and skipped; `strict=true` rejects a file with any invalid row. Rejected live
  events are stored with their errors and counted.
- **Fashion prediction with explanation**: "Why this prediction?" shows each input's contribution, computed
  from the Random Forest's own decision paths; contributions add up exactly to the confidence.
- **Concept drift detection**: DDM, ADWIN or Page-Hinkley on the error stream, with a warning zone, severity
  (High / Medium / Low) and shadow detectors for comparison.
- **Data drift monitoring**: PSI and KS per input feature, shown separately and clearly labelled as diagnostic
  only. Data drift never triggers adaptation; concept drift does.
- **Automatic model adaptation**: change-point estimation, retraining on the post-change window, scheduled
  refreshes as more new-pattern data arrives.
- **Model registry, versioning and rollback**: lineage, comparison of any two versions, checksummed write-once
  model files. Admins roll back with `POST /api/models/rollback` after a confirmation dialog; a reason of at least
  three characters is required (also when `POST /api/models/{v}/activate` targets an older version), the target
  must exist and be older, its file is checksum-verified before loading, the switch and an activation record (who,
  from, to, when, why) commit in one transaction, scheduled refreshes of the replaced model are cancelled, users
  are notified, and every later prediction uses the restored model. Nothing is ever deleted.
- **Model health score**: one 0–100 score from recent accuracy, F1, detector status, recent drift and model age,
  with a visible breakdown.
- **Drift performance (before / during / after)**: accuracy, precision, recall, F1 and error rate before drift,
  during drift and after adaptation for every drift event, from labeled outcomes only, with the drift timestamp,
  detector, versions before / after, outcomes handled by each model, the preceding warning and trend change, a
  shaded timeline and a comparison chart (**Drift performance** page, `GET /api/performance/comparison`).
- **System monitoring**: component health plus application, ML (prediction count, success rate, error rate,
  inference latency, version, adaptations, drift events), drift (warnings vs confirmed drifts, detector, status),
  data (events processed, valid / rejected events, uploads, simulation), performance and system health (process
  CPU, memory, load, database latency, API request latency and error rates). Unmeasured values show N/A.
- **Real-time notifications**: toasts and a notification center fed only by backend events.
- **Audit log**: user actions and pipeline actions, filterable by action, user, resource, severity, stream and date.
- **Simulation**: replays a synthetic dataset with three fashion trend periods to demonstrate drift on demand.
  Simulated data is labelled as such everywhere and never mixed into live statistics.
- **Authentication and role-based access**: user, analyst and admin roles; JWT with server-side revocation.
- **One coherent, role-aware interface**: grouped navigation per role, a persistent state rail (stream, detector
  state, active model, detector, recent accuracy) on every page, URL-addressable state (stream, tab, selected drift
  event, version, comparison, upload report) and a plain-language guide with twelve topics. See *Interface* below.

## Pages

The sidebar is grouped; each role sees only the groups and pages it may open (the server enforces the same rules,
hiding a link is only a convenience). Opening a page you may not use shows an explanation, not an empty screen.

| Group | Page | Who | What it answers |
|---|---|---|---|
| Overview | Dashboard | all | Has the relationship changed? A verdict from the detector, the Stable → Warning → Drift track, health score with its breakdown, accuracy or error over time against the frozen v1.0, what the pipeline did on its own, whether the last adaptation worked |
| | Live prediction | all | Prediction form, probabilities, "Why this prediction?" (contributions add up to the confidence), close-call note, recording the actual category |
| | Prediction history | all (own; staff: all) | Every prediction with its version, outcome, re-scoring and stored explanation; late outcomes from the drawer |
| | Live data | all (own; staff: all) | Send events (form, JSON, batch) and follow one through seven stages: received, validated, predicted, recorded, outcome, error, detector; 409 duplicates, 422 rejections, integration example |
| Model intelligence | Drift monitoring | analyst, admin | Detector state and thresholds, primary and shadow detectors (unavailable ones say why), error stream, drift events, detector switch (admin) |
| | Data vs concept drift | analyst, admin | P(X) versus P(y \| X): PSI / KS per input (diagnostic only) next to the error-based detector |
| | Adaptation & performance | analyst, admin | Two tabs: how adaptation ran (stages, versions, failures, retrain now, scheduled refreshes) and performance (timeline, per-version, confusion matrix, importance). `/app/performance` redirects here |
| | Drift performance | analyst, admin | Before / during / after each drift, with an honest "Measuring recovery" until enough outcomes exist |
| | Model registry | analyst, admin | Lineage, version detail (validation vs live, checksum), compare any two, activation and rollback history; rollback with a required reason (admin) |
| Data operations | Data management | analyst, admin (upload: admin) | CSV upload with strict / partial mode and its report, processing queued records, upload history |
| | Data validation | analyst, admin | The rules, CSV and live-event acceptance, each upload's report, rejected events, most common problems |
| System | System monitoring | analyst, admin | Application, ML, drift, model performance, data, pipeline and system health; unmeasured values show N/A |
| | Simulation mode | analyst, admin | A ten-step guided demonstration whose steps complete from server state, plus manual controls; always marked as simulation |
| Administration | Audit logs | admin | Filterable trail of user and pipeline actions, with readable details |
| | Users | admin | Roles and account status, each change confirmed |
| Help | How DriftWear works | everyone (also public at `/how-it-works`) | Twelve topics in plain language, from a single prediction to rollback, with an FAQ |

## Interface

- **Visual language.** Warm neutral canvas, charcoal text, deep navy for structure and one restrained plum accent.
  Archivo (variable width) for everything; condensed widths for headings and figures. No gradients, no emoji.
- **State is never colour alone.** Stable, Warning, Drift and Adapting, health bands, severities and outcomes always
  pair an icon with a word. Charts use solid / dashed / dotted lines as well as colour, with legends.
- **Simulation is separate.** Simulation pages carry a hatched banner and chip, the state rail switches to the
  simulation stream, and users never see simulation data (the API refuses it).
- **Nothing is invented.** Every figure comes from the API; missing values show N/A and explain why; recovery is
  "Measuring" until enough outcomes exist; detectors the server cannot run are listed as unavailable.
- **Destructive actions are confirmed.** Rollback, activation, detector changes, retraining, simulation reset,
  role changes and disabling accounts go through a dialog; the UI reports what the server confirmed.
- **Notifications.** Toasts for drift, adaptation, new versions, activations and failures; a notification center
  with categories, unread markers and a link to the relevant page. Both are fed only by backend events.
- **Code layout.** `src/lib/endpoints.js` is the only place that knows API paths; `src/lib/nav.js` defines the
  navigation, access levels and breadcrumbs; shared building blocks live in `components/ui.jsx`,
  `components/insights.jsx` and `components/charts.jsx`; design tokens are in `tailwind.config.js` and
  component classes in `src/index.css`.

## Data drift vs concept drift

| | Data drift | Concept drift |
|---|---|---|
| In one sentence | Data drift means the input data changed. | Concept drift means the relationship between the input and target changed. |
| In symbols | P(X) changes | P(y \| X) changes |
| Needs labels | No | Yes (actual outcomes) |
| Measured by | PSI per feature (+ KS for numbers) vs a reference window | DDM / ADWIN / Page-Hinkley on the error stream |
| Triggers retraining | **No** | **Yes** |

The synthetic dataset shows why both are needed. Within one trend period, purchase frequency, recency and
season drift strongly while the model stays accurate (data drift, no concept drift). Across a trend change,
price and preference keep their distribution while the purchase rule changes (concept drift without drift in
those inputs). Both cases are covered by `tests/test_data_drift.py`.

## How the pipeline behaves

| Situation | What happens |
|---|---|
| Event / prediction without an outcome | Prediction and explanation stored with the model version and detector status at that moment. The detector is **not** touched: there is no error yet. |
| Actual category arrives | Error computed, detector updated, status may move to WARNING or DRIFT. |
| Label arrives after the model already adapted | The record is **re-scored by the current model** before feeding the detector; the stored prediction is never rewritten (`rescored=true`). |
| Detector confirms DRIFT | Change point estimated; new model trained on the post-change window; **major** version (v1.0 → v2.0); detector reset and calibrated on the new model's out-of-fold errors. |
| +25 / +75 / +150 records after a drift | Scheduled refresh with more new-pattern data → minor versions (v2.1, v2.2, v2.3). |
| Admin "retrain now" | Minor version on recent labeled data. |
| Admin rolls back to an older version | File checksum verified; detector restarts for that model; scheduled refreshes of the replaced model are cancelled; activation record + audit entry `model.rollback` (with reason); `MODEL_ACTIVATED` carries `rollback: true`. |
| A live event fails validation | 422 with every problem (`field`, `value`, `message`); stored in `rejected_events`; never predicted. |
| A CSV re-uploads rows queued earlier | Those rows are skipped (warning per row naming the earlier upload); only new rows are queued. |
| Retraining fails | The previous model stays active; `ADAPTATION_FAILED` is broadcast and audited. |
| A database write fails | Nothing is half-applied: the engine reloads its state from the database and the request returns 503. |
| Same `event_id` sent twice | 409 Conflict with the original prediction id. |

**Model metrics.** `accuracy / precision / recall / f1_score` on a version are **out-of-fold validation** metrics
on its training window; `live_metrics` are measured on real outcomes after deployment. Small windows give low,
noisy validation scores; that is the honest number.

**Model health score** (`app/services/model_health.py`): recent accuracy 40 pts, recent macro-F1 20, detector
status 20 (STABLE 20 / WARNING 10 / DRIFT or adapting 0), recent drift events 10, model freshness 10. Bands:
≥ 80 HEALTHY, 60–79 AT RISK, < 60 DEGRADED; drift or a running adaptation always reports DEGRADED. With fewer
than 10 live outcomes, validation metrics are used and the response says `basis: "validation"`.

**Prediction explanation** (`ml/explain.py`): every tree's decision path moves the probability of the predicted
class; each move is credited to the split feature and averaged over the forest, then one-hot / engineered
columns are folded back into the eight input fields. Base value + contributions = the confidence shown.
No SHAP dependency.

## Demo: concept drift → adaptation → recovery → rollback

Sign in as the admin. Simulation data is a controlled demonstration and is labelled as such everywhere. The
*Guided demonstration* panel on Simulation mode follows the same steps and ticks each one off from server state.

1. **Simulation mode** → *Reset simulation…* (optional) → *Next 50* twice. The state rail stays on Stable and the
   error rate settles.
2. **Change fashion trend**, then *Start streaming* with *Pause when drift is confirmed* on. Errors rise, the track
   moves to Warning, then Drift. Toasts announce *Concept drift detected*, *Model adaptation started* and *New
   model created* (v2.0); the stream pauses.
3. *Next 50* once or twice so the adapted model collects outcomes (scheduled refreshes create v2.1, v2.2…).
4. **Drift performance** (simulation): accuracy, precision, recall, F1 and error rate before the drift, while the
   old model failed and after adaptation, the recovery verdict and the shaded timeline.
5. **Dashboard** with *Simulation* selected: the verdict, the health score and "What the system did".
6. **Model registry** (simulation) → *Review rollback…* → choose an older version → give a reason → *Roll back to
   …*. The page reports "Rollback confirmed by the server", the activation history shows who, from, to, when and
   why, and a toast reaches everyone. *Next 10* in Simulation mode predicts with the restored model.
7. **Audit logs** → Action *Models: retraining, activation, rollback*: `model.rollback` with the reason.
8. **Live data**: send an event, then its actual category, and watch it reach the detector; send the same event ID
   again (409, with the original prediction) and `"price": -500` in the JSON tab (422, every problem listed; it
   appears under *Rejected events* and in **Data validation**).

The same scenario is automated: `tests/test_demo_scenario.py` (pipeline) and `tests/test_api_demo_scenario.py` (HTTP).

## Local setup

### Everything with Docker (recommended)

```bash
cp .env.example .env
# edit .env: set JWT_SECRET, ADMIN_PASSWORD and POSTGRES_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(48))"      # a JWT_SECRET
docker compose up --build
```

- App: http://localhost:8080 (sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`)
- API docs: http://localhost:8080/docs
- Health: http://localhost:8080/health

Startup order: PostgreSQL becomes healthy → the backend runs `alembic upgrade head`, trains v1.0 for both
streams on first start and becomes healthy → the frontend starts.

### Backend without Docker

```bash
# PostgreSQL (any instance works; this is the quickest local one)
docker run -d --name driftwear-db -e POSTGRES_USER=driftwear -e POSTGRES_PASSWORD=driftwear \
  -e POSTGRES_DB=driftwear -p 5432:5432 postgres:16-alpine

cd backend
python -m venv .venv && source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                    # set DATABASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD
alembic upgrade head
uvicorn app.main:app --reload --port 8000 --workers 1
```

### Frontend without Docker

```bash
cd frontend
npm install
cp .env.example .env            # VITE_API_URL=http://localhost:8000 (empty = same origin)
npm run dev                     # http://localhost:5173
```

## Environment variables

Root `.env` (Docker Compose) and `backend/.env` (local backend). Never commit real values; `.env` is git-ignored.

| Variable | Required | Purpose |
|---|---|---|
| `JWT_SECRET` | yes (production) | HMAC key for access tokens, at least 32 random characters |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | yes | First admin account, created at startup if missing |
| `POSTGRES_PASSWORD` | yes (Compose) | Database password; Compose refuses to start without it |
| `DATABASE_URL` | yes (production) | SQLAlchemy URL; `postgres://` URLs are accepted |
| `ENVIRONMENT` | no | `production` enables strict checks (secrets, CORS, explicit DATABASE_URL) |
| `CORS_ORIGINS` | production | Comma-separated frontend origins (`*` is refused in production) |
| `JWT_EXPIRE_MINUTES` | no | Token lifetime (default 60) |
| `LOGIN_RATE_LIMIT`, `LOGIN_RATE_WINDOW_SECONDS` | no | Sign-in attempts per IP and per email (default 10 per 300 s) |
| `PREDICTION_RATE_LIMIT` | no | Predictions + events per user per minute (default 120; a batch counts each event) |
| `EVENT_BATCH_MAX` | no | Most events / outcomes in one batch request (default 100) |
| `MODEL_STORAGE_BACKEND`, `MODEL_DIR`, `S3_*` | no | `local` (default) or `s3` for model files |
| `SIMULATION_ENABLED`, `DEFAULT_DETECTOR`, `MAX_UPLOAD_MB` | no | Feature switches and limits |
| `VITE_API_URL` | frontend | API base URL baked into the frontend build; empty = same origin |

The frontend contains no secrets: it only knows the API URL.

## API documentation

FastAPI generates OpenAPI documentation from the code: **Swagger UI at `/docs`**, ReDoc at `/redoc`, the schema
at `/openapi.json`. Authenticate in Swagger with `POST /api/auth/login` and paste the token into *Authorize*.

| Method | Path | Purpose | Role |
|---|---|---|---|
| POST | `/api/events` · `/api/events/purchase` | One live purchase event → validation → stored prediction (model version, timestamps) + explanation + pipeline trace; 422 lists every problem | any user |
| POST | `/api/events/batch` | `{"events": [...]}`: each event validated and processed on its own; per-item results | any user |
| POST | `/api/events/outcome` | Actual category for an event (`event_id` or `prediction_id`) → error → detector | owner / admin |
| POST | `/api/events/outcomes` | `{"outcomes": [...]}`: many late outcomes, per-item results | owner / admin |
| GET | `/api/events/summary` | Live events received / labeled / awaiting / rejected | any user (own) |
| GET | `/api/events/rejections` | Rejected live events with their validation errors | staff |
| POST | `/api/predict` | Prediction form (optionally with the actual category) | any user |
| POST | `/api/predictions/{id}/outcome` | Late outcome for a prediction | owner / admin |
| GET | `/api/dashboard` | KPIs, series, markers, health, detectors, drift cycle, impact | any user (simulation: staff) |
| GET | `/api/drift/statistics` | Concept drift: detector, error series, events, before/during/after impact | staff |
| GET | `/api/drift/data` | Data drift: PSI / KS per feature vs a reference window | staff |
| GET | `/api/performance/comparison` | Before / during / after drift metrics, story, timeline series | staff |
| POST | `/api/data/upload?strict=true` | CSV upload; strict rejects the file if any row is invalid | admin |
| GET | `/api/data/validation` | Validation rules, CSV and live-event acceptance, recent rejections | staff |
| GET | `/api/models` · `/api/models/{v}` | Registry list and detail | staff |
| GET | `/api/models/compare?a=&b=` | Two versions side by side with deltas | staff |
| GET | `/api/models/health` | Model health score | any user (simulation: staff) |
| POST | `/api/models/rollback` | `{stream, to_version, reason}`: restore an older version; `reason` is required, 3–500 characters (422 missing or blank, 404 unknown, 409 active or newer, 503 unreadable file) | admin |
| POST | `/api/models/{v}/activate` | Activate any stored version; `reason` is optional for a newer version and required (3+ characters, else 422) when the target is older than the active one, because that is a rollback | admin |
| GET | `/api/models/activations` | Activation / rollback history and timeline (who, from, to, when, why) | staff |
| GET | `/api/system/monitoring` | Component health, pipeline metrics, current model, model health, plus `application`, `ml`, `drift`, `data`, `performance`, `system_health` | staff |
| GET | `/api/audit-logs` · `/api/audit-logs/facets` | Audit trail and filter values | admin |
| GET | `/health` · `/health/db` · `/health/ml` · `/health/websocket` | Real health checks (also under `/api/health/*`); 503 on error | public |

Existing endpoints (auth, users, data upload, simulation, detector selection) are unchanged; see `/docs`.

### WebSocket

Connect to `/ws`, then send `{"type": "auth", "token": "<JWT>"}` within 10 seconds (the token never appears in a
URL). The server replies `CONNECTED` with a status snapshot and then pushes events such as:

```json
{"event": "DRIFT_DETECTED", "stream": "live", "detector": "DDM", "severity": "High", "model_version": "v1.0",
 "timestamp": "2026-10-04T12:00:00.000+00:00",
 "message": "Concept drift detected by DDM (High severity). Model adaptation initiated.",
 "data": {"step": 412, "change_point_step": 380, "from_version": "v1.0", "to_version": "v2.0", "...": "..."}}
```

Sequence on drift: `WARNING_DETECTED` → `DRIFT_DETECTED` → `ADAPTATION_STARTED` → `ADAPTATION_COMPLETED` →
`MODEL_VERSION_CREATED` (and later `MODEL_ACTIVATED`, with `rollback: true` for rollbacks). Users receive their
own prediction events plus live status and model events; analysts and admins receive everything.

## Database

Tables: `users`, `predictions`, `drift_events`, `model_versions`, `data_records`, `uploads`, `stream_state`,
`audit_logs`, `rejected_events`, `model_activations`. Migrations live in `backend/alembic/versions/`:

- `0001_initial`: the original schema.
- `0002_audit_events`: `audit_logs` (FK to users, check constraint on severity, indexes on time, action, user and
  resource); `predictions.event_id` with a unique `(stream, event_id)` index; `predictions.explanation`;
  `(stream, outcome_at)` index for monitoring.
- `0003_live_data_rollback` (additive): `rejected_events` (live events that failed validation, with their
  errors); `model_activations` (rollback / activation history, check constraint on `action`);
  `data_records.record_hash` (indexed fingerprint used to skip re-uploaded rows; existing rows are back-filled).

A live event is NOT stored twice: an accepted event is its prediction row (`source = "event"`, `event_id`,
`model_version`, `created_at` = prediction time, `outcome_at` = when the actual category arrived).

A real-time event is stored as its prediction row (`source = "event"`), so features are not duplicated.
`/health/db` reports the database's Alembic revision and warns while it is behind the code.

## Security

- Passwords: stdlib `hashlib.scrypt` with per-user salt; constant-time comparison; dummy hash for unknown emails.
- JWT: HS256, expiry, required claims, per-user `token_version` (logout or disabling revokes every token).
- Authorization: role checks on every route; simulation data and monitoring for analysts/admins; audit log, users,
  uploads, detector changes and activation/rollback for admins only.
- Rate limiting: sign-in (per IP and per email) and predictions/events (per user).
- Input validation: Pydantic schemas with ranges, enums and `extra="forbid"`; CSV uploads checked for extension,
  size, rows and every value; event ids restricted to a safe pattern.
- SQL: SQLAlchemy ORM / parameter binding only; user search text is escaped for `LIKE`.
- Files: model storage keys are validated against path traversal; SHA-256 is verified before unpickling.
- No secrets in code or the frontend; production refuses weak/missing `JWT_SECRET`, `*` CORS, or a missing
  `DATABASE_URL`; Compose requires `POSTGRES_PASSWORD`.
- Errors: a consistent `{"error": {code, message, details, request_id}}` body; no stack traces or exception text
  in responses; health messages contain no hosts, paths or exception strings.
- The audit log never stores passwords, tokens or secrets (keys are filtered, strings truncated), and the admin's
  email is no longer broadcast to all users when a model is activated.

## Running the tests

```bash
cd backend && pytest                 # fast suite
cd backend && pytest -m slow         # full-stream parity and restart tests (a few minutes)
cd frontend && npm test              # Vitest unit tests
# end-to-end against a running stack:
E2E_BASE_URL=http://localhost:8080 ADMIN_PASSWORD=... pytest e2e
```

CI (`.github/workflows/ci.yml`) runs backend tests on SQLite and PostgreSQL (including migrations), frontend
tests and build, and the Docker Compose end-to-end suite.

### Verification status of this release (2.3)

Built in a sandbox where package registries were blocked, so dependencies were assembled from their sources
(FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.13, Alembic 1.15, scikit-learn 1.9 on Python 3.13; PostgreSQL 16;
Node 22). River was not available, so only the built-in DDM ran. What was actually executed, with real results:

| Check | Result |
|---|---|
| Backend suite, `pytest` including the slow parity and restart tests (SQLite, as configured in `tests/conftest.py`) | **154 passed** |
| Backend against PostgreSQL 16: `alembic upgrade head`, then the app with `--workers 1` | **ran**; used by every check below |
| `e2e/test_e2e.py` against that running stack (through a local static + proxy server, not nginx) | **8 passed** |
| Frontend unit tests (`src/lib/__tests__`) with a Vitest-compatible runner on `node:test` | **32 passed** |
| Frontend production bundle of the real sources (esbuild, minified, real Tailwind 3.4.17, Recharts, React Router, lucide-react) | **built** (app.js 783 KB, app.css 57 KB) |
| Nine browser flows in Chromium against the real backend: sign-in states and session revocation; predict → explain → outcome; live event journey with 409 and 422; user and analyst role limits; CSV upload partial and strict; rollback with a required reason through to the audit log; simulation reset → trend change → drift toast → figures update; phone width without horizontal scroll | **9 passed, no page or console errors** (except the blocked Google Fonts request; fonts were served locally) |
| Pages rendered and reviewed in screenshots: every page as admin, the user's and analyst's views, four pages at phone width | **done**; layout problems found this way were fixed |
| `npm run build` (Vite), `npm test` (Vitest), Docker Compose | **not executed here** (no registry access); the CI workflow runs them. React 19.2 stood in for React 18.3 in the bundle |

## Design decisions

- **No Celery/Redis.** The detector needs one ordered writer and retraining takes about a second. All
  state-changing work goes through an in-process ordered queue with CPU work in a worker thread.
  `workers/queue.py` defines the `TaskQueue` seam, so a distributed queue can replace it without touching the
  ML pipeline. The queue now reports completed / rejected / failed job counters for monitoring.
- **Single writer, zero-downtime friendly.** On PostgreSQL the process holding an advisory lock runs the pipeline;
  a second process serves reads in standby and takes over when the lock is released. Run uvicorn with `--workers 1`.
- **Engine without I/O.** `ml/stream_engine.py` returns results and the backend persists them, which makes the
  parity and restart tests possible.
- **Auditing through the event bus.** System actions (drift, retraining, new models) are audited by an EventBus
  subscriber, so the ML loop did not need to change; user actions are audited in the routes with user and IP.
- **Data drift is diagnostic.** Retraining on input shifts alone would chase seasonality; DriftWear retrains on
  confirmed concept drift and shows data drift for diagnosis.

### Upgrading the ML stack

Model files are tied to the scikit-learn version in `requirements.txt`. Back up the database and model storage,
install the new version, reset the simulation stream, and for the live stream prefer a fresh deployment that
bootstraps v1.0 again.

## Known limitations

- The ordered in-process queue means one API worker runs the pipeline (others stand by). That is deliberate for
  correctness; horizontal write scaling would need a distributed queue behind the existing `TaskQueue` seam.
- Tokens are stored in `localStorage` (no refresh tokens). An httpOnly-cookie session would need CSRF protection.
- Job failure counters (`failed_jobs`) are per process since start; everything else on System monitoring comes
  from the database.
- DDM becomes very sensitive right after a model reaches zero validation error on a uniform window (any single
  error is then significant). Realistic data does not do this, but hand-made test data with one label can.
- ADWIN and Page-Hinkley need River; without it only DDM (built-in) is available and shadows are hidden.
- Prediction latency, prediction success rate, API request metrics and CPU are measured per API process since it
  started (labelled as such); everything else on System monitoring comes from the database. Inside a container,
  system memory and load are the host's view; a container memory limit is not reflected.
- Live events without an `event_id` cannot be de-duplicated (there is nothing to compare); send ids from producers.
- There is no public fashion data feed wired in: the live pathway is a generic, authenticated event API that any
  external application can call. The simulation remains the controlled way to demonstrate drift.
- Before / during / after phases use windows of up to 50 outcomes around each drift (`PERF_EVAL_WINDOW`), so a
  drift with few outcomes after it shows "Measuring recovery" until enough real outcomes arrive.
- DDM measures a rise above the lowest error rate it has seen since its last reset. A model that is wrong on
  every outcome from the start of that window (for example after rolling back to a version trained for an
  earlier trend) gives it nothing to rise from, so it can stay below its drift threshold. The health score still
  drops to Degraded and says the model is underperforming; *Retrain now* or another activation is the remedy.
- The notification center's history comes from the backend's in-memory event buffer (last 300 events), so it
  starts empty after a backend restart. The audit log is the durable record.
- Uploading CSV files is limited to administrators by the API; analysts see the data and the reports.

## Legacy prototype

The original Streamlit app is kept, unchanged, in `legacy_streamlit/`.

## Deployment

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) covers a single server with Docker Compose, a Render blueprint
(`render.yaml`), Vercel for the frontend with Render or Railway for the API, Neon or Supabase PostgreSQL, and
S3-compatible model storage. In short: the frontend is a static build served by nginx (or any static host with
`VITE_API_URL` set), the backend is one container with `PYTHONPATH=/srv` running `alembic upgrade head` before
uvicorn, and PostgreSQL is any managed instance referenced by `DATABASE_URL`. Point load-balancer health checks
at `/health`.
