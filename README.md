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
| API | Python 3.14, FastAPI, Pydantic v2 |
| Database | PostgreSQL, SQLAlchemy 2, Alembic, row-level security |
| Frontend | React + TypeScript (Vite), built into `app/static` |
| Email | Resend (HTTPS API, 5 s timeout), behind a daily send budget |

## Run it locally

Needs Python 3.14+, Node 22.22+ (the image builds on Node 26) and Docker (or any PostgreSQL 16+).

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

Each user's rows are protected twice: every query filters by the signed-in user, and Postgres row-level security (`FORCE`d, so it applies to the table owner too) only shows rows whose `user_id` matches `app.user_id`. That setting is made transaction-local at the start of every transaction, so a pooled connection never carries one user's identity into another request. The app connects as `kazi_app`, which is not a superuser, cannot bypass RLS and owns no tables. For that role, stage history is append-only: it can add events but not change or delete them (deleting an application or account still removes them by cascade).

RLS covers the tracker tables (`applications`, `stage_events`). The account tables (`users`, `sessions`, `auth_tokens`) have to be read before anyone is signed in (to log in, or to check a session or reset link), so they're guarded by the code alone: only the auth and account endpoints touch them, always by the signed-in user's ID or by a hashed token.

Logs never hold request bodies, email addresses or database values: database errors are logged by SQLSTATE and constraint name only. The plain-language notice for users is at `/privacy`.

### Accounts and sessions

- Passwords are hashed with argon2id (19 MiB, OWASP's minimum profile, sized for a 512 MB service).
- Sessions are random 256-bit tokens in an HTTP-only, SameSite=Lax cookie (Secure and `__Host-` prefixed in production). The database stores only their SHA-256.
- Every state-changing request needs the session's CSRF token in `X-CSRF-Token`, must be JSON, and is refused if the browser says it came from another origin.
- Sign-up and password reset answer the same way whether or not an email has an account. Unknown emails take the same hashing time on login.
- Rate limits: 5 failed logins a minute per IP (successful ones don't count, since many people share an address on mobile data); failed logins 10 an hour per account from one IP and 50 an hour per account overall (successful logins never count, so others can't lock you out from elsewhere); sign-up 5 an hour per IP; reset 3 an hour per email.
- Verification (24 h) and reset (1 h) links are single-use, stored hashed, and carry the token in the URL fragment so it never reaches server logs. A reset signs you out everywhere.

### Daily reminders

`python -m app.jobs.daily` runs once a day as a Railway cron service (`0 3 * * *`, which is 06:00 in Nairobi). It sends each opted-in user with a confirmed email one digest of deadlines in the next 3 days, oldest sign-ups first if the email budget runs short. Then it clears expired sessions and tokens, logs counts and exits. A user is marked before their email goes out, so a re-run never sends a second digest the same day. A failed send is unmarked and tried again next run. There is no scheduler or loop inside the web service.

The same job deletes accounts whose email was never confirmed and which never tracked a role, 30 days after sign-up. Signed-in users can see what their next digest would hold under Settings (`/api/account/digest-preview`), and the export in Settings includes their account, applications, stage history and active sign-ins.

## Checks

```bash
ruff check . && ruff format --check . && mypy app tests scripts
TEST_ADMIN_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres pytest -q
(cd web && npm run lint && npm run typecheck && npm test)
```

## Dependencies

Dependabot raises security fixes as soon as an advisory lands, plus weekly update PRs: minor and patch updates are grouped, and each major update comes as its own PR. Nothing is ignored. Every update gets applied, along with whatever code it breaks, and goes through all the checks above before it ships. If an update can't be done yet, the reason goes on its PR. `requirements.txt` pins the exact versions the image installs, and CI runs `pip-audit` on it.

## Deploy (Railway)

Two services and one database, all built from the same `Dockerfile`:

| Service | Start command | Settings |
| --- | --- | --- |
| web | `scripts/start-web.sh` (the image default) | Serverless on (sleeps when idle), 0.5 vCPU / 512 MB replica limits, health check `/health` |
| daily | `python -m app.jobs.daily` | Cron schedule `0 3 * * *` (06:00 in Nairobi). It runs, sends, exits |
| Postgres | Railway Postgres | |

Before the first deploy, set the workspace usage limits: an email alert at $5 and a hard limit (Railway takes everything offline at the hard limit instead of billing more).

Variables:

| Variable | web | daily |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | `production` |
| `DATABASE_URL` | the `kazi_app` URL (see below) | the `kazi_app` URL |
| `MIGRATIONS_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (owner) | not set |
| `SECRET_KEY` | long random string | same |
| `BASE_URL` | `https://<your-app>.up.railway.app` | same |
| `TRUSTED_PROXY_HOPS` | `1` (required in production) | `1` |
| `RESEND_API_KEY`, `EMAIL_FROM` | from Resend | same |

Until a domain is verified in Resend, `EMAIL_FROM` can only be Resend's test sender (`onboarding@resend.dev`), and it delivers only to the Resend account owner's own address. Fine for trying it out; real users need the domain (Phase 4).

`scripts/start-web.sh` runs `alembic upgrade head` as the owner, then unsets `MIGRATIONS_DATABASE_URL` before starting the server, so the running app never holds the owner's password. The first migration creates the `kazi_app` role without a login. After the first deploy, give it one once (`railway connect Postgres`, then `ALTER ROLE kazi_app LOGIN PASSWORD '<random>';`) and build `DATABASE_URL` from it: `postgresql://kazi_app:<random>@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`.

### Backups and restore

Users' trackers live only in Postgres, so:

- Turn on backups for the Postgres volume in Railway (service → Backups) if the plan offers them, and note the schedule and how many are kept. If it doesn't, take the manual dump below at least weekly.
- Before any migration that changes or drops data, take a dump by hand: `railway connect Postgres`, or from your machine `pg_dump --format=custom "$DATABASE_PUBLIC_URL" > ~/kazi-backups/kazi-$(date +%F).dump`. Keep dumps outside the repo and somewhere private: they hold emails and notes (`*.dump` is git-ignored as a safety net).
- Restore into an empty database with `pg_restore --no-owner --dbname "$TARGET_URL" kazi-YYYY-MM-DD.dump`, then run `alembic upgrade head` and give `kazi_app` its password again.
- Users can always download their own data from Settings.

Smoke test after each deploy: `python scripts/smoke_test.py https://<your-app>.up.railway.app`. It signs up a throwaway account, adds an application due tomorrow, checks the digest preview lists it, checks the security headers, and deletes the account again (one sign-up email from the day's budget).

### Secrets

Secrets come only from environment variables; `.env` is git-ignored. CI runs detect-secrets against `.secrets.baseline`, which lists the reviewed local-development placeholders (localhost database URLs, test passwords), so any new secret fails the build. After adding a deliberate placeholder, refresh the baseline with `detect-secrets scan --baseline .secrets.baseline --exclude-files '^web/package-lock\.json$'` and review it with `detect-secrets audit .secrets.baseline`.

## Cost guardrails

The target is about $5 a month on Railway's Hobby plan, with hard caps so a bug can't produce a large bill:

- One web service that sleeps when idle, one Postgres, one cron job that exits. No in-process schedulers or loops.
- Request bodies capped at 64 KB; notes at 5,000 characters; lists paginated at 50; at most 2,000 applications per user.
- Email budget: at most 90 emails a UTC day (under Resend's free 100). The count and the send share one transaction, so a failed send uses no budget and the 91st is refused and logged. Sign-up and reset emails stop at 60, keeping 30 for the morning reminders, and each address gets at most one sign-up email a day.
- More caps arrive with each feature: rate limits, pagination, outbound timeouts.
