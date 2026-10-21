# Build from the repository root (the API needs ml/ and data/):
#   docker build -f backend/Dockerfile -t driftwear-api .
FROM python:3.12-slim

# PYTHONPATH=/srv: the API (backend/app) imports the ML engine from /srv/ml
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/srv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY ml ml
COPY data data
COPY backend backend

RUN useradd --create-home --uid 10001 app && mkdir -p /srv/models && chown -R app:app /srv/models
USER app
WORKDIR /srv/backend

ENV MODEL_STORAGE_DIR=/srv/models PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)" || exit 1

# Migrations first, then ONE worker: the drift detector needs a single writer (see README "Design decisions").
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
