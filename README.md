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

### Accounts and sessions

- Passwords are hashed with argon2id (19 MiB, OWASP's minimum profile, sized for a 512 MB service).
- Sessions are random 256-bit tokens in an HTTP-only, SameSite=Lax cookie (Secure and `__Host-` prefixed in production). The database stores only their SHA-256.
- Every state-changing request needs the session's CSRF token in `X-CSRF-Token`, must be JSON, and is refused if the browser says it came from another origin.
- Sign-up and password reset answer the same way whether or not an email has an account. Unknown emails take the same hashing time on login.
- Rate limits: login 5 a minute per IP (and 10 an hour per email), sign-up 5 an hour per IP, reset 3 an hour per email.
- Verification (24 h) and reset (1 h) links are single-use, stored hashed, and carry the token in the URL fragment so it never reaches server logs. A reset signs you out everywhere.

### Daily reminders

`python -m app.jobs.daily` runs once a day as a Railway cron service (`0 3 * * *`, which is 06:00 in Nairobi). It sends each opted-in user with a confirmed email one digest of deadlines in the next 3 days, oldest sign-ups first if the email budget runs short. Then it clears expired sessions and tokens, logs counts and exits. A user is marked before their email goes out, so a re-run never sends a second digest the same day. A failed send is unmarked and tried again next run. There is no scheduler or loop inside the web service.

Signed-in users can see what their next digest would hold at `/api/account/digest-preview`.

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
