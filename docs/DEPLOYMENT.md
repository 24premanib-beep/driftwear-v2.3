# Deploying DriftWear

DriftWear has three parts:

- a **static frontend** (React build);
- **one API process** (FastAPI, which also runs the drift pipeline);
- **PostgreSQL**.

Model files go to a local directory or to S3-compatible object storage. Every setting is an environment
variable; see `backend/.env.example` and `.env.example`.

| Option | Frontend | API | Database | Model files |
|---|---|---|---|---|
| A. One server with Docker | nginx container | container | container | Docker volume |
| B. Render blueprint | Render static site | Render web service (Docker) | Render PostgreSQL | S3 / Supabase Storage / R2 |
| C. Vercel + Render/Railway + Neon/Supabase | Vercel | Render or Railway | Neon or Supabase | S3 / Supabase Storage / R2 |

## Rules that apply everywhere

1. **Run exactly one API process** (`--workers 1`; the Dockerfile does this). The drift detector needs a single
   writer. A second process, or the new instance during a zero-downtime deploy, waits in read-only *standby* and
   takes over when the first one stops. It never runs a second detector.
2. **Use a direct (session) PostgreSQL connection, not a transaction pooler.** The single-writer guard uses a
   session-level advisory lock.
   - **Neon:** use the connection string *without* `-pooler` in the host.
   - **Supabase:** use the direct connection or the session pooler on port 5432, **not** port 6543.
   - Add `?sslmode=require` for hosted databases.
3. **Hosts with ephemeral disks need object storage for model files.** This applies to Render, Railway without a
   volume, and Heroku-like platforms. Set `MODEL_STORAGE_BACKEND=s3`; otherwise model files disappear on redeploy
   and the API refuses to start. It never silently retrains the live model.
4. **Production refuses unsafe settings** when `ENVIRONMENT=production`:
   - `JWT_SECRET` must be at least 32 random characters;
   - `CORS_ORIGINS` must list explicit origins;
   - `S3_BUCKET` must be set when using S3.
5. **Migrations** run automatically at container start (`alembic upgrade head`). Outside Docker, run them yourself
   before starting the API.

## A. One server with Docker Compose

```bash
git clone <your repo> && cd fashion-concept-drift
cp .env.example .env        # set JWT_SECRET, ADMIN_PASSWORD and POSTGRES_PASSWORD
docker compose up -d --build
```

- App: `http://<server>:8080`. API docs: `http://<server>:8080/docs`.
- nginx proxies `/api` and `/ws` to the API, so browser, API and WebSocket share one origin and no CORS changes
  are needed.
- Put HTTPS in front with any reverse proxy (Caddy, Traefik, a cloud load balancer). The WebSocket path `/ws`
  needs `Upgrade` headers passed through and a long read timeout. `frontend/nginx.conf` shows the settings.
- Back up the `pgdata` volume, and the `models` volume when you use local model storage.

## B. Render (one-click blueprint)

`render.yaml` creates the database, the API and the static frontend.

1. Push the repository to GitHub or GitLab, then in Render choose **New → Blueprint** and select it.
2. Fill in the values Render asks for:
   - `ADMIN_EMAIL`, `ADMIN_PASSWORD`;
   - `CORS_ORIGINS` (the static site's URL, e.g. `https://driftwear-web.onrender.com`);
   - the S3 settings (section E);
   - `VITE_API_URL` for the static site (e.g. `https://driftwear-api.onrender.com`).
3. `JWT_SECRET` is generated automatically.
4. After the first deploy, sign in with the admin account at the static site's URL.

The API's health check is `/health` (also `/api/health`). It returns 200 in standby too, so zero-downtime deploys complete. Component checks: `/health/db` (connectivity, latency, migration revision), `/health/ml` (pipeline worker, loaded models, model files) and `/health/websocket` (event bus, clients); each returns 503 only when that component is in error.

## C. Vercel frontend + separate API

**Frontend on Vercel**

1. Import the repository and set **Root Directory** to `frontend`. Vercel detects Vite; `vercel.json` adds the SPA
   rewrite and security headers.
2. Set the environment variable `VITE_API_URL=https://<your-api-host>`. The WebSocket URL is derived from it
   (`wss://<your-api-host>/ws`), or you can set `VITE_WS_URL` explicitly.
3. Add the Vercel URL, and any custom domain, to the API's `CORS_ORIGINS`.

**API on Render**

Create a *Web Service* from the repository:
- Runtime: Docker.
- Dockerfile path: `backend/Dockerfile`.
- Docker context: repository root.
- Health check: `/health`.

Then set the environment variables from `backend/.env.example`.

**API on Railway**

1. Create a service from the repository.
2. Set the variable `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` and keep the root directory as the repository
   root. Railway provides `PORT`, and the container listens on it.
3. Either attach a Railway volume at `/srv/models`, or use S3 storage.

Railway PostgreSQL works as-is: copy its `DATABASE_URL` (a `postgres://` URL is accepted).

**Database on Neon or Supabase**

Create the database, copy the **direct** connection string, append `?sslmode=require` if it is not there, and set
it as `DATABASE_URL`. The schema is created by the migration on first start.

## E. Model storage on S3-compatible services

| Service | Settings |
|---|---|
| AWS S3 | `MODEL_STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Supabase Storage | as above, plus `S3_ENDPOINT_URL=https://<project-ref>.supabase.co/storage/v1/s3` and the S3 access keys from *Storage → S3 connection* |
| Cloudflare R2 | as above, plus `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`, `S3_REGION=auto` |
| MinIO | as above, plus `S3_ENDPOINT_URL=http://<minio-host>:9000` |

Keep the bucket **private**. Model files are pickles and must only ever be read by the API, which verifies a
SHA-256 checksum before loading each one. The API needs `GetObject`, `PutObject`, `HeadObject` and `DeleteObject`
(delete is used only when the simulation is reset).

## Production checklist

- [ ] `ENVIRONMENT=production`, a random `JWT_SECRET`, and a strong `ADMIN_PASSWORD`.
- [ ] `CORS_ORIGINS` lists only your frontend origins.
- [ ] HTTPS everywhere. The WebSocket then uses `wss://` automatically.
- [ ] A direct PostgreSQL connection, with backups enabled.
- [ ] Durable model storage: object storage, or a persistent volume.
- [ ] `SIMULATION_ENABLED=false` if the deployment should not offer the synthetic demo.
- [ ] The health check points at `/health`.
- [ ] `DATABASE_URL` is set explicitly (production refuses to start without it).
- [ ] `POSTGRES_PASSWORD` is a random value (Docker Compose refuses to start without it).
- [ ] One API process only.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| API exits with "The live model files could not be loaded" | Model storage lost the files (ephemeral disk) or the settings changed. Restore the storage or fix the `MODEL_STORAGE_*` settings. The live history is never silently re-created. |
| Requests return 503 "starting up" for a while after deploying | The new instance is in standby until the old one releases the pipeline lock. This normally takes seconds. If it lasts, check for a second API process using the same database. |
| The browser shows CORS errors | Add the exact frontend origin (scheme + host + port) to `CORS_ORIGINS` and restart the API. |
| The header says "Reconnecting…" all the time | The proxy is not passing WebSocket upgrades on `/ws`, or it closes idle connections. Allow `Upgrade` and raise the read timeout. The client pings every 25 s. |
| Startup fails with "ConfigError" | Production refused an unsafe setting. The message names it. |


## What changed in 2.1 (deployment-relevant)

- **`PYTHONPATH=/srv`** is set in the backend image: the API imports the ML engine from `/srv/ml`. Earlier images
  could not start (`ModuleNotFoundError: No module named 'ml'`). Outside Docker, `app/__init__.py` adds the
  repository root automatically, so `uvicorn app.main:app` from `backend/` works.
- **Migration `0002_audit_events`** adds `audit_logs`, `predictions.event_id` (unique per stream) and
  `predictions.explanation`. It runs automatically at container start; elsewhere run `alembic upgrade head`.
  `/health/db` reports a warning while the database is behind this revision.
- **`POSTGRES_PASSWORD` is required** by Docker Compose (no default password any more).
- **`PREDICTION_RATE_LIMIT`** (default 120 per user per minute) limits `/api/predict` and `/api/events/purchase`.
- nginx proxies `/health`, `/health/db`, `/health/ml` and `/health/websocket` to the backend.
