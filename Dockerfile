# syntax=docker/dockerfile:1

# 1) Build the React frontend into app/static.
FROM node:22-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) Python runtime: one image for the web service and the daily cron job.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-deps -r requirements.txt

# Runs from /srv (no package install), so app/static sits next to the code.
COPY alembic.ini ./
COPY app/ app/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY --from=web /src/app/static/ app/static/
RUN useradd --system --uid 10001 --no-create-home kazi \
    && chmod 0555 scripts/start-web.sh

USER kazi
EXPOSE 8000
# Web: scripts/start-web.sh. Cron service: python -m app.jobs.daily
CMD ["scripts/start-web.sh"]
