# Kazi Hakika

**Kazi Hakika: verified roles, tracked your way.**

A free job-application tracker with a community board of verified roles, built first for tech job seekers in Kenya. *Kazi hakika* means "verified work" in Kiswahili. The platform never promises anyone a job: it helps you keep track of your applications and spot fake ads.

> Status: early development (Phase 1, the private tracker).

## What it does

- A private tracker for roles, stages, deadlines and notes, with a daily reminder digest.
- Export everything as JSON, and delete your account for good.
- Coming later: a shared board of checked roles, a public "Is this job real?" checker, and a connector so your own AI assistant can help with your applications.

## Principles

1. The AI coaches; it never applies. Nothing here submits applications or emails employers.
2. We hold tracker data only. No CVs, no phone numbers, no model running on our side.
3. Private by default. Only you can see your applications.
4. Verification is rule-based and gives the same answer to everyone.
5. Free to use, cheap to run, with hard caps on every cost.
6. Everything works without AI.

## Architecture

One FastAPI service serves the API and the built React frontend, alongside one Postgres database and one daily cron job.

| Layer | Choice |
| --- | --- |
| API | Python 3.12, FastAPI, Pydantic v2 |
| Database | PostgreSQL, SQLAlchemy 2, Alembic, row-level security |
| Frontend | React + TypeScript (Vite), built into `app/static` |
| Email | Resend (HTTPS API, 5 s timeout), behind a daily send budget |

## Run it locally

Needs Python 3.12+, Node 22 and Docker (or any PostgreSQL 16+).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

docker compose up -d db
# Create the tables and the kazi_app role as the database owner...
MIGRATIONS_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/kazi_hakika alembic upgrade head
# ...then let the app log in as kazi_app, a non-superuser, so row-level security applies.
docker compose exec db psql -U postgres -c "ALTER ROLE kazi_app LOGIN PASSWORD 'kazi_app'"

(cd web && npm ci && npm run build)   # builds the frontend into app/static
uvicorn app.main:app --reload
```

Open http://localhost:8000. For frontend work, run `npm run dev` in `web/` (it proxies `/api` to port 8000).

### Privacy model

Each user's rows are protected twice: every query filters by the signed-in user, and Postgres row-level security (`FORCE`d, so it applies to the table owner too) only shows rows whose `user_id` matches `app.user_id`. That setting is made transaction-local at the start of every transaction, so a pooled connection never carries one user's identity into another request. The app connects as `kazi_app`, which is not a superuser, cannot bypass RLS and owns no tables.

## Checks

```bash
ruff check . && ruff format --check . && mypy app tests
TEST_ADMIN_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest -q
(cd web && npm run lint && npm run typecheck && npm test)
```

## Cost guardrails

The target is about $5 a month on Railway's Hobby plan, with hard caps so a bug can't produce a large bill:

- Request bodies capped at 64 KB.
- Email budget: at most 90 emails a UTC day (under Resend's free 100). The count and the send share one transaction, so a failed send uses no budget and the 91st is refused and logged.
- More caps arrive with each feature: rate limits, pagination, outbound timeouts.
