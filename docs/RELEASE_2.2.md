# DriftWear 2.2: release notes

Five production improvements built on release 2.1 without replacing the model, detectors, pipeline, database,
authentication or deployment. The README is the reference; this file lists exactly what changed.

## Database migration

`backend/alembic/versions/0003_live_data_rollback.py` (additive, runs with `alembic upgrade head` at start-up):
`rejected_events`, `model_activations`, `data_records.record_hash` (indexed, back-filled for existing rows).

## Files created (21)

- `backend/alembic/versions/0003_live_data_rollback.py`
- `backend/app/services/ingestion.py`
- `backend/app/services/metrics.py`
- `backend/tests/test_api_demo_scenario.py`
- `backend/tests/test_api_live_data.py`
- `backend/tests/test_data_validation.py`
- `backend/tests/test_demo_scenario.py`
- `backend/tests/test_drift_comparison.py`
- `backend/tests/test_live_data.py`
- `backend/tests/test_rollback.py`
- `backend/tests/test_runtime_metrics.py`
- `frontend/src/components/validation.jsx`
- `frontend/src/lib/__tests__/comparison.test.js`
- `frontend/src/lib/__tests__/liveData.test.js`
- `frontend/src/lib/__tests__/validation.test.js`
- `frontend/src/lib/comparison.js`
- `frontend/src/lib/liveData.js`
- `frontend/src/lib/validation.js`
- `frontend/src/pages/DataValidation.jsx`
- `frontend/src/pages/DriftPerformance.jsx`
- `frontend/src/pages/LiveData.jsx`

## Files modified (35)

- `.env.example`
- `README.md`
- `backend/.env.example`
- `backend/app/__init__.py`
- `backend/app/api/common.py`
- `backend/app/api/dashboard.py`
- `backend/app/api/data.py`
- `backend/app/api/events_ingest.py`
- `backend/app/api/models.py`
- `backend/app/config.py`
- `backend/app/database/models.py`
- `backend/app/database/schemas.py`
- `backend/app/main.py`
- `backend/app/services/analytics.py`
- `backend/app/services/health.py`
- `backend/app/services/monitoring.py`
- `backend/app/services/pipeline.py`
- `backend/app/services/queries.py`
- `backend/app/services/repository.py`
- `backend/app/services/sql_repository.py`
- `backend/tests/memory_repository.py`
- `backend/tests/test_migrations.py`
- `docker-compose.yml`
- `e2e/test_e2e.py`
- `frontend/src/App.jsx`
- `frontend/src/components/Layout.jsx`
- `frontend/src/components/charts.jsx`
- `frontend/src/components/ui.jsx`
- `frontend/src/pages/DataManagement.jsx`
- `frontend/src/pages/Performance.jsx`
- `frontend/src/pages/Registry.jsx`
- `frontend/src/pages/SystemMonitoring.jsx`
- `ml/stream_engine.py`
- `ml/validation.py`
- `render.yaml`

No files were removed. The synthetic dataset, the simulation, the Random Forest and DDM / ADWIN / Page-Hinkley
are unchanged (the record-by-record parity test with the original prototype still passes).

## Behaviour changes worth knowing

- Activating or rolling back a model now cancels the scheduled refreshes of the model it replaces; before, a
  refresh could silently retrain away from an admin's rollback a few records later.
- CSV rows that an earlier upload already queued are skipped (reported per row) instead of being processed twice.
- Live events are validated by the shared rule set before Pydantic; error messages now match CSV messages and
  categorical values are matched case-insensitively (as CSV uploads already were).
- A rejected upload's message starts with "Upload rejected"; an accepted one with "Validation successful".
- `/api/system/monitoring` adds sections; every field it returned before is still returned.
