# syntax=docker/dockerfile:1

# 1) Build the React frontend into app/static.
FROM node:26-trixie-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2) Python runtime: one image for the web service and the daily cron job.
FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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
