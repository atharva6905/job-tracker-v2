# BLUEPRINT — job-tracker-v2
**Status:** v1.4  
**Last Updated:** 2026-03-17  
**Companion document:** PRD v2.2

---

## How to Use This Document

This blueprint is the step-by-step build guide for job-tracker-v2. Each chunk maps to one Claude Code session. Rules:

- **One chunk per Claude Code session.** Never combine chunks. Each prompt is scoped to be completable in one focused session.
- **Do not start the next chunk until the current one passes all tests and runs locally.**
- **PRD.md is the source of truth.** If this blueprint conflicts with the PRD, the PRD wins. The blueprint translates PRD decisions into build prompts.
- **Use Claude Chat (this conversation) for architecture decisions, debugging, and PRD alignment. Use Claude Code for file generation and implementation.**
- After completing each chunk, commit to GitHub with a message like `feat: chunk 3 — db migrations`.

---

## Repo Structure

```
job-tracker-v2/
├── backend/                  # FastAPI app
│   ├── app/
│   │   ├── main.py
│   │   ├── scheduler.py      # APScheduler instance (created in chunk 1)
│   │   ├── database.py       # SQLAlchemy engine + session
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── routers/          # FastAPI route handlers
│   │   ├── services/         # Business logic
│   │   ├── dependencies/     # FastAPI Depends (auth, db session)
│   │   └── utils/            # Shared utilities (company normalization, etc.)
│   ├── alembic/
│   │   ├── env.py            # Uses DATABASE_URL_DIRECT (port 5432)
│   │   └── versions/
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 # Next.js app
│   ├── app/                  # App Router pages
│   ├── components/
│   ├── lib/
│   ├── .env.example
│   └── package.json
├── extension/                # Chrome Extension MV3
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   └── overlay.html
├── .github/
│   └── workflows/
│       └── ci.yml
├── PRD.md
├── BLUEPRINT.md
├── SECURITY.md
└── README.md
```

---

## Phase 1 — MVP

---

### Chunk 1 — Repo Setup

**What this builds:** The complete project skeleton. FastAPI app with working database connection to Supabase, Alembic configured for migrations, APScheduler instance at module level, Docker setup for DigitalOcean Droplet deployment, GitHub Actions CI with pip-audit, and both `.env.example` files with every required variable.

**Why this chunk matters:** Every subsequent chunk imports from `database.py`, `scheduler.py`, or uses the CI pipeline. Getting this right first prevents rework.

**Key decisions from PRD:**
- Two connection strings: `DATABASE_URL` (port 6543, pooled, PgBouncer) for runtime; `DATABASE_URL_DIRECT` (port 5432, direct) for Alembic migrations. PgBouncer does not support DDL transactions that Alembic requires.
- SQLAlchemy engine: `pool_pre_ping=True, pool_size=5, max_overflow=5` — required to stay within Supabase free tier's 20-connection limit.
- APScheduler `BackgroundScheduler` instance created at module level in `scheduler.py` — not started yet, just instantiated. Route handlers need to import this object from chunk 7 onward (`scheduler.remove_job()`). Starting it happens in chunk 9.
- `GET /health` endpoint exists from day one — it's used by the keep-alive APScheduler job in chunk 9.

**Claude Code Prompt:**
```
I'm building a new FastAPI project called job-tracker-v2. Set up the complete project skeleton.

PROJECT STRUCTURE:
Create the following layout:
- backend/ — FastAPI app
- frontend/ — placeholder directory with a .env.example only (Next.js built in chunk 14)
- extension/ — placeholder directory (Chrome extension built in chunk 15)
- .github/workflows/ci.yml

BACKEND SETUP (backend/):

1. requirements.txt — include these exact packages:
fastapi, uvicorn[standard], sqlalchemy==2.0.*, alembic, pydantic[email]>=2.0, python-jose[cryptography], httpx, apscheduler, python-dotenv, ruff, pytest, pytest-asyncio, requests, sentry-sdk, python-json-logger, pip-audit, cryptography, google-auth, google-auth-oauthlib, google-api-python-client, slowapi, google-generativeai

2. backend/app/database.py — SQLAlchemy engine and session:
- Read DATABASE_URL from environment (this is the POOLED Supabase connection string, port 6543)
- Engine configured with: pool_pre_ping=True, pool_size=5, max_overflow=5
- Standard SessionLocal and get_db() dependency
- Include a comment: "Use DATABASE_URL (port 6543, pooled) for runtime. Alembic uses DATABASE_URL_DIRECT (port 5432)."

3. backend/app/scheduler.py — APScheduler instance:
- Create a BackgroundScheduler instance at module level: scheduler = BackgroundScheduler()
- Do NOT call scheduler.start() here — that happens in chunk 9
- Include a comment: "Instantiated here so any module can import it. Started in main.py lifespan event (chunk 9)."

4. backend/app/main.py:
- FastAPI app instance
- GET /health endpoint returning {"status": "ok"}
- Include a lifespan context manager placeholder (empty for now, scheduler.start() added in chunk 9)
- CORS middleware with origins from ALLOWED_ORIGINS env var (comma-separated string)
- Mount all routers (only health router for now)

5. backend/alembic/ — Alembic setup:
- alembic/env.py must read from DATABASE_URL_DIRECT (not DATABASE_URL) for the connection
- Include a comment in env.py: "Uses DATABASE_URL_DIRECT (port 5432, direct connection). Do NOT use DATABASE_URL here — PgBouncer (port 6543) does not support DDL transactions that Alembic requires."
- alembic.ini configured for the backend directory
- Empty alembic/versions/ directory with a .gitkeep

6. backend/.env.example — every required variable with placeholder values:
DATABASE_URL=postgresql://postgres:[password]@[host]:6543/postgres?sslmode=require
DATABASE_URL_DIRECT=postgresql://postgres:[password]@[host]:5432/postgres?sslmode=require
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWT_SECRET=your-supabase-jwt-secret
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GEMINI_API_KEY=your-gemini-api-key
TOKEN_ENCRYPTION_KEY=your-fernet-key-base64
SENTRY_DSN=https://your-sentry-dsn
EXTENSION_ORIGIN=chrome-extension://your-extension-id
ALLOWED_ORIGINS=http://localhost:3000
FRONTEND_URL=http://localhost:3000

7. frontend/.env.example:
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_EXTENSION_ID=your-extension-id

8. .github/workflows/ci.yml:
- Trigger on push and pull_request to main
- Python 3.13 (required for integration tests — same pattern as project 1):
  ```yaml
  services:
    postgres:
      image: postgres:16
      env:
        POSTGRES_USER: tracker
        POSTGRES_PASSWORD: tracker
        POSTGRES_DB: tracker_test
      ports:
        - 5432:5432
      options: >-
        --health-cmd pg_isready
        --health-interval 5s
        --health-timeout 5s
        --health-retries 5
  ```
- Set env vars in the CI steps:
  DATABASE_URL_DIRECT=postgresql://tracker:tracker@localhost:5432/tracker_test
  DATABASE_URL=postgresql://tracker:tracker@localhost:5432/tracker_test
  (Both point to the test DB in CI — the pooled/direct distinction only matters in production)
  SUPABASE_JWT_SECRET=test-secret-for-ci
  TOKEN_ENCRYPTION_KEY=(generate a valid Fernet key as a CI secret or hardcode a test key)
- Run: ruff check backend/
- Run: pip-audit (fails build on known CVEs)
- Run: alembic upgrade head (runs migrations against test DB before tests)
- Run: pytest backend/tests/ -v
- Note: pip-audit runs in the backend directory

9. backend/Dockerfile:
- Python 3.13 slim base
- Copy requirements and install
- CMD: uvicorn app.main:app --host 0.0.0.0 --port 8000
- This runs on a DigitalOcean Droplet via: docker build, docker run -d --restart unless-stopped -p 80:8000 (or 443:8000 with TLS)
- Include a comment: "Deploy to DigitalOcean Droplet: build image, run with --restart unless-stopped so it auto-restarts on reboot"

10. README.md — brief project overview with setup instructions referencing .env.example files.

After creating all files, verify the FastAPI app imports cleanly (no import errors) and GET /health returns 200.
```

---

### Chunk 2 — Supabase Auth Integration

**What this builds:** JWT verification dependency, user get-or-create on first login, `GET /auth/me`, and stubbed `GET /users/me/export` and `DELETE /users/me` (returning 501 until their dependent tables exist in later chunks).

**Key decisions from PRD:**
- `users.id` IS the Supabase UUID — set directly from `payload["sub"]`. No `supabase_id` column exists.
- `get_or_create_user(db, id=payload["sub"], email=payload["email"])` — the `id` kwarg maps directly to `users.id`.
- `GET /auth/me` returns the user row from the local `users` table, not the raw JWT payload.
- Stubs return HTTP 501 Not Implemented with body `{"detail": "Not yet implemented"}`.
- No `/auth/register` or `/auth/login` endpoints — Supabase Auth handles those entirely.

**Claude Code Prompt:**
```
I'm building chunk 2 of job-tracker-v2: Supabase Auth integration.

The users table does not exist in the DB yet (that's chunk 3). Build the auth dependency and route handlers now so they're ready when migrations run.

EXISTING FILES to be aware of:
- backend/app/database.py — has get_db() dependency
- backend/app/main.py — has FastAPI app instance

BUILD THE FOLLOWING:

1. backend/app/dependencies/auth.py — JWT verification dependency:
- Read SUPABASE_JWT_SECRET and SUPABASE_URL from environment
- verify_supabase_jwt(token: str) -> dict: decode and validate the JWT using python-jose, verify audience and expiry. Raise HTTP 401 on any failure.
- get_current_user(token, db) FastAPI dependency: calls verify_supabase_jwt, then calls get_or_create_user(db, id=payload["sub"], email=payload["email"]). Returns the User object.
- The real User ORM model does not exist until chunk 3. For now, define a simple stub dataclass in this file:
  @dataclass
  class User:
      id: str
      email: str
      created_at: datetime = field(default_factory=datetime.utcnow)
  This stub is fully replaced by the real SQLAlchemy model in chunk 3 — at that point, update this import to use the real model. Using a stub here is cleaner than conditional imports or TYPE_CHECKING gymnastics.

2. backend/app/services/user_service.py:
- get_or_create_user(db, id: str, email: str) -> User:
  - Query users table by id (UUID)
  - If found, return existing user
  - If not found, create new user with id=id, email=email
  - This is the only place users are created

3. backend/app/routers/auth.py:
- GET /auth/me — requires auth dependency — returns current user as UserResponse schema
- GET /users/me/export — requires auth — returns HTTP 501 {"detail": "Not yet implemented"}
- DELETE /users/me — requires auth — returns HTTP 501 {"detail": "Not yet implemented"}

4. backend/app/schemas/user.py:
- UserResponse: id (UUID), email (str), created_at (datetime)
- model_config = ConfigDict(from_attributes=True)

5. Register the auth router in main.py with prefix="" (no prefix, paths are /auth/me and /users/me/export).

No tests yet for auth — the users table doesn't exist. Tests come in chunk 3 after migrations.
```

---

### Chunk 3 — Database Migrations

**What this builds:** All core Alembic migrations for the initial schema: `users`, `companies`, `applications`, `interviews`, `job_descriptions`. All PKs are UUID. All FK constraints use `ON DELETE CASCADE`.

**Key decisions from PRD:**
- `companies` has both `name` (original) and `normalized_name` (lowercase, legal suffixes stripped). Unique constraint on `(user_id, normalized_name)`.
- `applications.status` enum: `IN_PROGRESS`, `APPLIED`, `INTERVIEW`, `OFFER`, `REJECTED`.
- `applications.date_applied` is nullable — not set until status reaches `APPLIED`.
- `applications.source_url` is nullable — set by extension capture, used as primary dedup key.
- `job_descriptions` has NO `source_url` column — the canonical URL lives on `applications`.
- `interviews.round_type` and `interviews.outcome` are enums — define appropriate values.
- No `hashed_password`, no `supabase_id` on users.

**Claude Code Prompt:**
```
I'm building chunk 3 of job-tracker-v2: all core database migrations.

EXISTING CONTEXT:
- backend/alembic/env.py reads from DATABASE_URL_DIRECT (port 5432, direct connection)
- All PKs must be UUID type
- All FK constraints must include ON DELETE CASCADE

CREATE THE FOLLOWING:

1. backend/app/models/ — SQLAlchemy ORM models (one file per model):

models/user.py — User model:
  id: UUID PK (mapped to Supabase Auth user UUID)
  email: VARCHAR(255), unique, not null
  created_at: TIMESTAMP with timezone, server_default=now()

models/company.py — Company model:
  id: UUID PK, default=uuid4
  user_id: UUID FK → users.id ON DELETE CASCADE, not null
  name: VARCHAR(255), not null (original name as provided)
  normalized_name: VARCHAR(255), not null (lowercase + legal suffixes stripped)
  location: VARCHAR(255), nullable
  link: VARCHAR(2048), nullable
  created_at: TIMESTAMP with timezone, server_default=now()
  UniqueConstraint on (user_id, normalized_name)
  Index on (user_id, normalized_name)

models/application.py — Application model:
  id: UUID PK, default=uuid4
  user_id: UUID FK → users.id ON DELETE CASCADE, not null
  company_id: UUID FK → companies.id ON DELETE CASCADE, not null
  role: VARCHAR(255), not null
  status: Enum('IN_PROGRESS','APPLIED','INTERVIEW','OFFER','REJECTED'), not null
  source_url: VARCHAR(2048), nullable
  date_applied: DATE, nullable
  notes: TEXT, nullable
  created_at: TIMESTAMP with timezone, server_default=now()
  Index on (user_id, status)
  Index on (user_id, date_applied)
  Index on (company_id)
  Index on (user_id, source_url)

models/interview.py — Interview model:
  id: UUID PK, default=uuid4
  application_id: UUID FK → applications.id ON DELETE CASCADE, not null
  round_type: Enum('PHONE','TECHNICAL','BEHAVIORAL','SYSTEM_DESIGN','FINAL','OTHER'), not null
  scheduled_at: TIMESTAMP with timezone, nullable
  outcome: Enum('PASSED','FAILED','PENDING'), nullable
  notes: TEXT, nullable
  created_at: TIMESTAMP with timezone, server_default=now()
  Index on (application_id)

models/job_description.py — JobDescription model:
  id: UUID PK, default=uuid4
  application_id: UUID FK → applications.id ON DELETE CASCADE, not null, unique (1:1)
  raw_text: TEXT, not null
  captured_at: TIMESTAMP with timezone, server_default=now()
  UniqueConstraint on application_id

2. Generate a single Alembic migration file that creates all these tables in the correct order (users first, then companies, then applications, then interviews, then job_descriptions).

3. Write a conftest.py for tests:
- Use a real PostgreSQL test DB (use DATABASE_URL_DIRECT with a test schema or test DB)
- Each test runs in a transaction that is rolled back after the test (not committed)
- Provide: db session fixture, authenticated user fixture (creates a User row), auth headers fixture

4. Write integration tests in backend/tests/test_auth.py:
- GET /auth/me with valid JWT returns 200 with user data
- GET /auth/me with invalid JWT returns 401
- GET /auth/me creates user on first login (get-or-create)
- GET /auth/me returns existing user on subsequent login (no duplicate created)
- GET /users/me/export returns 501
- DELETE /users/me returns 501

Run alembic upgrade head against the test DB to verify migrations apply cleanly.

IMPORTANT — replace stub User in auth.py:
After creating the real SQLAlchemy User model in models/user.py, update backend/app/dependencies/auth.py:
- Remove the stub User dataclass that was defined in chunk 2
- Add: from app.models.user import User
- Verify get_or_create_user() returns the real ORM model, not the stub
This is a required cleanup step — the stub was only needed because models didn't exist yet.

IMPORTANT — enable RLS manually in Supabase after migrations run:
After `alembic upgrade head` completes, go to the Supabase dashboard → Table Editor (or SQL Editor) and do the following for every table: `users`, `companies`, `applications`, `interviews`, `job_descriptions`, `email_accounts`, `raw_emails`, `gmail_oauth_states`.

For each table, run in the Supabase SQL Editor:
```sql
-- Enable RLS on the table
ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;

-- Allow users to only access their own rows
CREATE POLICY "user_isolation" ON <table_name>
  USING (user_id = auth.uid());
```

Notes:
- `gmail_oauth_states` and `raw_emails` don't have a direct `user_id` — skip RLS on these two tables. They are only ever accessed via FastAPI's server-side connection which bypasses RLS entirely (postgres superuser). They are protected by FK cascade and by the fact that no client ever queries them directly.
- `users` table: use `id = auth.uid()` instead of `user_id = auth.uid()`
- Do NOT use the "Enable automatic RLS" toggle in Supabase project settings — that fires on table creation before policies exist. Always enable manually after migrations.
- FastAPI's SQLAlchemy connection (DATABASE_URL, postgres superuser) is unaffected by RLS — these policies only apply to Supabase's own REST API layer, which is the secondary defense. FastAPI's `user_id` scoping on every query is the primary defense.
```

---

### Chunk 4 — Core CRUD

**What this builds:** Full CRUD for companies, applications, and interviews. Company find-or-create utility. Status transition enforcement. Pydantic schemas with security hardening. Integration tests.

**Key decisions from PRD:**
- `extra='forbid'` on ALL request schemas — rejects unexpected fields.
- Field length limits: `role` 255, `notes` 5000, `company.name` 255, `company.link` 2048.
- URL fields (`company.link`, `application.source_url`): use `HttpUrl` first. If real ATS/career page URLs fail validation during testing, switch to `AnyUrl` consistently for both fields.
- Status transitions enforced in service layer: `IN_PROGRESS→APPLIED`, `APPLIED→INTERVIEW`, `APPLIED→REJECTED`, `INTERVIEW→OFFER`, `INTERVIEW→REJECTED`. Invalid transitions return HTTP 400.
- Manual override via `PATCH /applications/{id}`: bypasses transition rules, BUT `IN_PROGRESS` is excluded from `ApplicationUpdate.status` allowed values — it can never be set via PATCH.
- All queries scoped to `user_id` — non-owned resources return 404, not 403.
- `PATCH` uses `model_dump(exclude_unset=True)` for partial updates.
- Company find-or-create: normalize name → query by `(user_id, normalized_name)` → return existing or create with both `name` and `normalized_name` set.
- Normalization: lowercase, strip trailing punctuation, remove suffixes: LLC, Inc, Corp, Ltd, Limited, Co., Co (word boundary).

**Claude Code Prompt:**
```
I'm building chunk 4 of job-tracker-v2: core CRUD for companies, applications, and interviews.

CRITICAL REQUIREMENTS — read before writing any code:

1. ALL Pydantic request schemas must have: model_config = ConfigDict(extra='forbid')
2. Field length limits (enforce with Field(max_length=...)):
   - company name: 255, location: 255, link: 2048
   - application role: 255, notes: 5000
   - interview notes: 5000
3. Status transition rules (enforced in service layer, not route handler):
   Valid automated transitions: IN_PROGRESS→APPLIED, APPLIED→INTERVIEW, APPLIED→REJECTED, INTERVIEW→OFFER, INTERVIEW→REJECTED
   Only IN_PROGRESS is excluded from user PATCH. OFFER and REJECTED are valid manual override targets — the user may need to correct a wrong classification (e.g. set status back from OFFER to INTERVIEW if Gemini misclassified). ApplicationUpdate.status must use a Literal or Enum of: APPLIED | INTERVIEW | OFFER | REJECTED (IN_PROGRESS excluded, everything else allowed)
4. Manual override: PATCH /applications/{id} bypasses transition rules entirely (user is correcting a mistake), EXCEPT IN_PROGRESS which can never be set via PATCH
5. All routes: scope every query with user_id filter. Return 404 for non-owned resources (not 403).
6. PATCH uses model_dump(exclude_unset=True) — only update fields present in the request

BUILD:

1. backend/app/utils/company.py — company name normalization utility:
   normalize_company_name(name: str) -> str:
   - lowercase
   - strip leading/trailing whitespace
   - remove trailing punctuation
   - strip common legal suffixes as whole words: LLC, Inc, Inc., Corp, Corp., Ltd, Ltd., Limited, Co., Co
   - return normalized string

2. backend/app/services/company_service.py:
   find_or_create_company(db, user_id: UUID, name: str, location=None, link=None) -> Company:
   - normalize name
   - query companies where user_id=user_id AND normalized_name=normalized
   - if found: return it
   - if not found: create with name=original, normalized_name=normalized, set location and link if provided
   IMPORTANT: both name and normalized_name must be set on insert or future dedup lookups silently fail

3. backend/app/schemas/ — create these schemas:
   companies.py: CompanyCreate (name, location, link), CompanyUpdate (all optional), CompanyResponse
   applications.py: ApplicationCreate (company_id, role, notes), ApplicationUpdate (role, notes, status — status excludes IN_PROGRESS), ApplicationResponse
   interviews.py: InterviewCreate (round_type, scheduled_at, notes), InterviewUpdate (all optional), InterviewResponse
   All request schemas: extra='forbid', field length constraints as above

4. backend/app/services/application_service.py:
   apply_status_transition(current_status, new_status, is_system_triggered=True):
   - If is_system_triggered=True: enforce transition rules, raise 400 on invalid
   - If is_system_triggered=False (user PATCH): allow any transition EXCEPT to IN_PROGRESS, raise 400 if target is IN_PROGRESS
   
5. backend/app/routers/companies.py — full CRUD:
   GET /companies, POST /companies, GET /companies/{id}, PATCH /companies/{id}, DELETE /companies/{id}
   
6. backend/app/routers/applications.py — full CRUD:
   GET /applications (filters: status, company_id, date_applied_start, date_applied_end; pagination: skip, limit), POST /applications, GET /applications/{id}, PATCH /applications/{id}, DELETE /applications/{id}

7. backend/app/routers/interviews.py:
   GET /applications/{application_id}/interviews, POST /applications/{application_id}/interviews

8. Register all routers in main.py

9. Integration tests:
   test_companies.py: CRUD happy paths, ownership (404 on other user's company), duplicate normalized name returns 409
   test_applications.py: valid transitions, invalid transition returns 400, IN_PROGRESS via PATCH returns 400, manual override bypasses rules, pagination, status filter, ownership 404
   test_interviews.py: create and list, ownership through parent application
```

---

### Chunk 5 — Security Baseline

**What this builds:** Rate limiting on every endpoint, request body size limit, CORS hardening, production debug mode off, and `SECURITY.md`.

**Key decisions from PRD (Section 13.1 rate limit table — implement exactly):**

| Endpoint | Limit | Key |
|----------|-------|-----|
| `GET /health` | 60/min | IP |
| `GET /gmail/callback` | 20/min | IP |
| `GET /auth/me` | 60/min | User ID |
| `GET /gmail/connect` | 10/min | User ID |
| `DELETE /gmail/disconnect/{account_id}` | 10/min | User ID |
| `GET /gmail/accounts` | 30/min | User ID |
| `POST /gmail/accounts/{account_id}/poll` | 10/hr | User ID |
| `POST /extension/capture` | 60/hr | User ID |
| `GET /users/me/export` | 5/hr | User ID |
| `DELETE /users/me` | 3/hr | User ID |
| All CRUD endpoints | 60/min | User ID |

**Claude Code Prompt:**
```
I'm building chunk 5 of job-tracker-v2: the full security baseline.

BUILD THE FOLLOWING:

1. Rate limiting with slowapi:
   - Create backend/app/dependencies/rate_limit.py
   - Set up a Limiter instance with two key functions:
     - get_ip_key(request): returns request.client.host (for public endpoints)
     - get_user_key(request): extracts user ID from the verified JWT in Authorization header (for authenticated endpoints). If no valid JWT, fall back to IP.
   - Apply rate limits ONLY to routes that exist at this point in the build. Gmail routes do not exist until chunk 7 — do NOT import from routers/gmail.py here or the build will break with an ImportError.
   - Routes to rate limit now:
     GET /health: "60/minute" keyed by IP
     GET /auth/me: "60/minute" keyed by user
     GET /users/me/export: "5/hour" keyed by user
     DELETE /users/me: "3/hour" keyed by user
     POST /extension/capture: "60/hour" keyed by user  (stub — wired in chunk 13)
     All /companies endpoints: "60/minute" keyed by user
     All /applications endpoints: "60/minute" keyed by user
     All /interviews endpoints: "60/minute" keyed by user
   - Gmail route limits (apply these in chunk 7 when gmail.py is created):
     GET /gmail/connect: "10/minute" keyed by user
     GET /gmail/callback: "20/minute" keyed by IP
     DELETE /gmail/disconnect/{account_id}: "10/minute" keyed by user
     GET /gmail/accounts: "30/minute" keyed by user
     POST /gmail/accounts/{account_id}/poll: "10/hour" keyed by user
   - All 429 responses must return: {"detail": "Rate limit exceeded. Try again later."} with Retry-After header
   - Register SlowAPIMiddleware on the FastAPI app

2. Request body size limit:
   - Add Starlette ContentSizeLimit middleware with a 1MB limit (1_048_576 bytes)
   - Add BEFORE the rate limit middleware so oversized bodies are rejected before any logic runs

3. CORS hardening in main.py:
   - Read ALLOWED_ORIGINS from env (comma-separated: "http://localhost:3000,chrome-extension://abc123")
   - Also read EXTENSION_ORIGIN from env and add to allowed origins
   - CORSMiddleware with allow_origins=parsed list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
   - Add a comment: "Never use allow_origins=['*'] in production"

4. Production safety:
   - FastAPI app instantiated with debug=False (read DEBUG env var, default False)
   - Add a custom exception handler for unhandled exceptions that returns {"detail": "Internal server error"} — never leak stack traces

5. Write SECURITY.md in the repo root with:
   - Fernet key rotation procedure (4 steps from PRD Section 13.3)
   - List of all environment variables and what they do — include FRONTEND_URL (backend env var: the deployed Vercel URL in production, http://localhost:3000 in dev; used by /gmail/callback redirect)
   - Note that gmail_oauth_states.user_id FK has ON DELETE CASCADE

6. Integration tests:
   test_rate_limits.py: hit /health 61 times in a loop, verify 61st returns 429 with Retry-After header. Test that a request over 1MB to /applications returns 413. Test that a request with an unexpected field (extra field in JSON body) to POST /companies returns 422.
```

---

### Chunk 6 — Structured Logging and Sentry

**What this builds:** JSON-structured logging across the entire app, Sentry error tracking, and the log hygiene rules enforced via a custom logger wrapper.

**Key decisions from PRD:**
- Use `python-json-logger`. Every log entry includes: `timestamp`, `level`, `service`, `user_id` (where applicable), `message`.
- Log hygiene: email body content, body snippets, and any user-authored text must NEVER appear in logs. Only permitted fields: `gmail_message_id`, `email_account_id`, `gemini_signal`, `gemini_confidence`, `action_taken`, timestamps, error types.
- Sentry: one `sentry_sdk.init()` call in `main.py`, DSN from `SENTRY_DSN` env var.

**Claude Code Prompt:**
```
I'm building chunk 6 of job-tracker-v2: structured logging and Sentry error tracking.

BUILD THE FOLLOWING:

1. backend/app/utils/logging.py — structured logger setup:
   - Configure Python's logging module with pythonjsonlogger.JsonFormatter
   - Log format fields: timestamp, level, service, user_id, message, plus any extra kwargs passed at log call time
   - get_logger(service_name: str) -> Logger: returns a logger pre-configured with the service name bound
   - Example usage: logger = get_logger("gmail_poller"); logger.info("Poll started", extra={"email_account_id": str(account_id), "action_taken": "poll_start"})
   - Add a prominent comment block: 
     "LOG HYGIENE RULE: Never log raw email body content, body snippets, or any user-authored text.
      Permitted fields only: gmail_message_id, email_account_id, gemini_signal, gemini_confidence,
      action_taken, timestamps, error types, user_id, application_id.
      Violating this rule is a GDPR/PIPEDA privacy exposure."

2. Add Sentry initialization in backend/app/main.py:
   - import sentry_sdk at top
   - In app startup (before routes mount): sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.1)
   - If SENTRY_DSN is not set, skip init (don't crash in local dev)

3. Replace any print() statements in existing code with proper logger calls.

4. Add structured log calls to existing route handlers:
   - GET /auth/me: log at DEBUG level with user_id on successful auth
   - Any 400/404/422/429 responses: log at WARNING level with endpoint and status code (no request body content)
   - Unhandled exceptions: already captured by Sentry; also log at ERROR level

5. Write a brief test in backend/tests/test_logging.py:
   - Verify that the JSON formatter outputs valid JSON
   - Verify that get_logger() returns a logger with the service field bound
   - Verify that log records do NOT contain any field named "body", "snippet", "email_body", or "raw_text"
```

---

### Chunk 7 — Gmail OAuth Connection Flow

**What this builds:** Gmail OAuth2 connect/callback/disconnect/list endpoints, `gmail_oauth_states` and `email_accounts` DB migrations, token encryption with Fernet, and completing the `DELETE /users/me` wiring with APScheduler job cancellation.

**Key decisions from PRD:**
- `GET /gmail/callback` has NO auth — there is no JWT on this request. The `user_id` comes from the `gmail_oauth_states` row, not a JWT.
- CSRF protection: state token stored in `gmail_oauth_states` DB table (not in-memory — the process can restart at any time during deploys or OOM kills). On callback: query by state token, verify not expired, retrieve `user_id` from row, delete row (single use).
- `gmail_oauth_states`: `state_token VARCHAR PK`, `user_id UUID FK→users ON DELETE CASCADE`, `expires_at TIMESTAMP`. TTL: 10 minutes.
- `email_accounts`: tokens encrypted with Fernet before storage. Encryption key from `TOKEN_ENCRYPTION_KEY` env var.
- `DELETE /users/me`: before cascade, call `scheduler.remove_job(f"poll_{account.id}")` for each account. Wrap in `try/except JobLookupError` — the job may not be registered yet (APScheduler starts in chunk 9).
- `gmail.readonly` scope only.

**Claude Code Prompt:**
```
I'm building chunk 7 of job-tracker-v2: Gmail OAuth connection flow.

CRITICAL: GET /gmail/callback has NO auth dependency. There is no JWT on the callback request — Google's redirect carries no JWT. The user identity comes ONLY from the gmail_oauth_states DB row. Do not add auth dependency to this endpoint.

MIGRATIONS — create two Alembic migrations:

Migration 1: gmail_oauth_states table
  state_token: VARCHAR(255) PK
  user_id: UUID FK → users.id ON DELETE CASCADE, not null
  expires_at: TIMESTAMP with timezone, not null
  Index on (user_id)
  Index on (expires_at)

Migration 2: email_accounts table
  id: UUID PK, default=uuid4
  user_id: UUID FK → users.id ON DELETE CASCADE, not null
  email: VARCHAR(255), not null
  access_token: TEXT, not null (encrypted)
  refresh_token: TEXT, not null (encrypted)
  token_expiry: TIMESTAMP with timezone, nullable
  last_polled_at: TIMESTAMP with timezone, nullable
  created_at: TIMESTAMP with timezone, server_default=now()
  Index on (user_id)

ENCRYPTION UTILITY — backend/app/utils/encryption.py:
  - Read TOKEN_ENCRYPTION_KEY from env (base64-encoded Fernet key)
  - encrypt_token(token: str) -> str: encrypt and return base64 string
  - decrypt_token(encrypted: str) -> str: decrypt and return plaintext
  - Both functions raise ValueError on failure (not silently return None)

GMAIL OAUTH SERVICE — backend/app/services/gmail_oauth_service.py:
  - GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
  - build_oauth_flow() -> Flow: creates google_auth_oauthlib Flow with GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri pointing to /gmail/callback
  - create_state_token(db, user_id) -> str: generates secrets.token_urlsafe(32), inserts into gmail_oauth_states with expires_at = now() + 10 minutes, returns token
  - consume_state_token(db, state_token) -> UUID: queries gmail_oauth_states by state_token. If not found: raise HTTP 400 "Invalid state". If expired: raise HTTP 400 "State token expired". Delete row. Return user_id.
  - store_gmail_tokens(db, user_id, credentials): encrypt tokens before storage (fresh OAuth tokens are plaintext — there is nothing to decrypt), upsert into email_accounts

ROUTERS — backend/app/routers/gmail.py:
  Apply the rate limits listed in the chunk 5 Gmail section to each route below using @limiter.limit.
  Import the limiter from app.dependencies.rate_limit — do not create a new Limiter instance.

  GET /gmail/connect (requires auth):
    - Create state token via service
    - Generate authorization URL via OAuth flow with state param
    - Return {"authorization_url": url} — frontend redirects user there

  GET /gmail/callback (NO auth):
    - Extract state and code from query params
    - Call consume_state_token() to get user_id (this validates CSRF and expiry)
    - Exchange code for credentials via OAuth flow
    - Store encrypted tokens via store_gmail_tokens()
    - Redirect to: f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/settings"
    - FRONTEND_URL is a backend env var set to the Vercel URL in production, http://localhost:3000 in dev. Without it, hardcoding localhost:3000 will break in production.

  DELETE /gmail/disconnect/{account_id} (requires auth):
    - Verify account belongs to current user (404 if not)
    - Revoke token via Google API (best effort — don't fail if revoke errors)
    - Delete email_accounts row

  GET /gmail/accounts (requires auth):
    - Return list of connected accounts for current user (email field only, no tokens)

  POST /gmail/accounts/{account_id}/poll (requires auth, 10/hr rate limit):
    - Stub returning {"detail": "Not yet implemented"} — wired in chunk 10

COMPLETE DELETE /users/me (replace the 501 stub from chunk 2):
  - Import scheduler from app.scheduler
  - For each of user's email_accounts:
    - Try: scheduler.remove_job(f"poll_{account.id}")
    - Except JobLookupError: pass (job not registered yet — ignore gracefully)
    - Revoke Gmail token via Google API (best effort, catch and log any errors)
  - Delete the user row (ON DELETE CASCADE handles all children)
  - Return 204 No Content

INTEGRATION TESTS:
  test_gmail_oauth.py:
  - /gmail/connect returns authorization_url containing accounts.google.com
  - /gmail/callback with valid state and mock code stores encrypted tokens (mock the OAuth exchange)
  - /gmail/callback with expired state token returns 400
  - /gmail/callback with unknown state token returns 400
  - /gmail/callback with no JWT still works (confirm no 401)
  - /gmail/disconnect/{id} for non-owned account returns 404
  - DELETE /users/me calls scheduler.remove_job for each account (mock scheduler, verify called)
  - DELETE /users/me cascades: user and all accounts deleted
```

---

### Chunk 8 — Data Export and Complete Delete

**What this builds:** `raw_emails` migration, completing `GET /users/me/export` with all user data, and completing `DELETE /users/me` to fully cascade all tables.

**Key decisions from PRD:**
- `GET /users/me/export`: returns all user data as a single JSON object structured by entity type. Tokens excluded from email account data. Rate limit: 5/hr.
- `raw_emails.body_snippet` is stored for audit trail — included in export.
- Export includes: user info, companies, applications (with job descriptions), interviews, email accounts (metadata only, no tokens), raw emails.
- `DELETE /users/me` is already wired in chunk 7. This chunk adds `raw_emails` to the cascade (handled automatically by FK ON DELETE CASCADE on `email_account_id`).

**Claude Code Prompt:**
```
I'm building chunk 8 of job-tracker-v2: raw_emails migration and completing export/delete.

MIGRATION — create Alembic migration for raw_emails:
  id: UUID PK, default=uuid4
  email_account_id: UUID FK → email_accounts.id ON DELETE CASCADE, not null
  gmail_message_id: VARCHAR(255), unique, not null
  subject: TEXT, nullable
  sender: VARCHAR(255), nullable
  received_at: TIMESTAMP with timezone, nullable
  body_snippet: TEXT, nullable (first 500 chars of email body — stored for audit trail)
  gemini_signal: VARCHAR(50), nullable (values: APPLIED/INTERVIEW/OFFER/REJECTED/IRRELEVANT/BELOW_THRESHOLD/PARSE_ERROR)
  gemini_confidence: FLOAT, nullable
  linked_application_id: UUID FK → applications.id ON DELETE SET NULL, nullable
  created_at: TIMESTAMP with timezone, server_default=now()
  Unique index on (gmail_message_id)
  Index on (email_account_id, received_at)

ORM MODEL — backend/app/models/raw_email.py matching above

COMPLETE GET /users/me/export (replace the 501 stub):
  Returns a JSON object with this structure:
  {
    "user": { id, email, created_at },
    "companies": [ array of company objects ],
    "applications": [ array with nested job_description if exists ],
    "interviews": [ array ],
    "email_accounts": [ { id, email, last_polled_at, created_at } — NO tokens ],
    "raw_emails": [ { id, gmail_message_id, subject, sender, received_at, body_snippet, gemini_signal, gemini_confidence, linked_application_id, created_at } ]
  }
  
  IMPORTANT: The export query must return ALL raw_emails for the user's email accounts — including rows where linked_application_id is NULL (emails that were processed but did not match any application). Do NOT filter by linked_application_id IS NOT NULL — that would silently omit unlinked emails from the export.
  Note: body_snippet is included — it is stored intentionally for the audit trail. The privacy policy (future) will document this.
  Rate limit: 5/hour (already configured in chunk 5 — verify it applies)

INTEGRATION TESTS:
  test_export.py:
  - GET /users/me/export returns 200 with correct structure
  - Export includes companies, applications, email accounts (no tokens), raw emails
  - Export does NOT include access_token or refresh_token fields anywhere in the response
  - After DELETE /users/me, a second call returns 401 (user no longer exists)
  
  test_cascade_delete.py:
  - Create user with company, application, interview, job_description, email_account, raw_email
  - DELETE /users/me
  - Verify all rows are gone from all tables (query each table directly)
  - Verify 204 response
```

---

### Chunk 9 — APScheduler Setup

**What this builds:** Starts APScheduler, registers the startup event handler that re-registers poll jobs on boot, the Supabase keep-alive ping, and the `gmail_oauth_states` hourly cleanup job.

**Key decisions from PRD:**
- `scheduler.start()` is called in the FastAPI lifespan context manager.
- On startup: query `email_accounts` for all connected accounts, register a poll job for each (`max_instances=1` per job).
- Poll jobs: `poll_gmail_account(account_id)` function — stubbed for now, wired in chunk 10.
- Keep-alive: hits `GET /health` internally every 3 days. On the DigitalOcean Droplet running Docker, the port is always 8000 (set in the Dockerfile CMD). Use: `requests.get("http://localhost:8000/health")`
- Cleanup job: `DELETE FROM gmail_oauth_states WHERE expires_at < now()` — runs hourly.
- `max_instances=1` on every poll job — prevents concurrent runs if a poll takes >15 minutes.

**Claude Code Prompt:**
```
I'm building chunk 9 of job-tracker-v2: APScheduler setup and job registration.

EXISTING: backend/app/scheduler.py has `scheduler = BackgroundScheduler()` (instance only, not started).

BUILD THE FOLLOWING:

1. backend/app/jobs/poll_job.py:
   poll_gmail_account(account_id: str):
   - Stub function for now: just log "Poll job triggered for account {account_id}"
   - This is fully implemented in chunk 10
   - Import get_logger from utils.logging; log with service="gmail_poller"

2. backend/app/jobs/cleanup_job.py:
   cleanup_expired_oauth_states():
   - Open a new DB session (not using FastAPI dependency — this runs outside request context)
   - Execute: DELETE FROM gmail_oauth_states WHERE expires_at < now()
   - Log number of rows deleted at DEBUG level
   - Close session in finally block

3. backend/app/jobs/keepalive_job.py:
   ping_health():
   - Make an internal HTTP GET to http://localhost:8000/health
   - The port is always 8000 when running via Docker on the DigitalOcean Droplet (set in Dockerfile CMD)
   - If it fails (connection error), log at WARNING level but do not raise
   - This keeps Supabase free tier from pausing after 7 days of inactivity

4. Update backend/app/main.py — add lifespan context manager:
   @asynccontextmanager
   async def lifespan(app):
     # Startup
     scheduler.start()
     
     # Re-register poll jobs for all connected Gmail accounts
     db = SessionLocal()
     try:
       accounts = db.query(EmailAccount).all()
       for account in accounts:
         scheduler.add_job(
           poll_gmail_account,
           trigger="interval",
           minutes=15,
           id=f"poll_{account.id}",
           args=[str(account.id)],
           max_instances=1,
           replace_existing=True
         )
     finally:
       db.close()
     
     # Register cleanup job — hourly
     scheduler.add_job(
       cleanup_expired_oauth_states,
       trigger="interval",
       hours=1,
       id="cleanup_oauth_states",
       max_instances=1,
       replace_existing=True
     )
     
     # Register keep-alive — every 3 days
     scheduler.add_job(
       ping_health,
       trigger="interval",
       days=3,
       id="keepalive",
       max_instances=1,
       replace_existing=True
     )
     
     yield
     
     # Shutdown
     scheduler.shutdown(wait=False)
   
   app = FastAPI(lifespan=lifespan, debug=False)

5. Update /gmail/connect service to also register the poll job immediately when a new Gmail account is connected:
   After inserting email_accounts row:
   scheduler.add_job(poll_gmail_account, trigger="interval", minutes=15, id=f"poll_{account.id}", args=[str(account.id)], max_instances=1, replace_existing=True)

6. Update /gmail/disconnect service to remove the poll job when disconnecting:
   try:
     scheduler.remove_job(f"poll_{account.id}")
   except JobLookupError:
     pass

7. Tests — backend/tests/test_scheduler.py:
   - Verify scheduler.start() is called during app lifespan startup (use TestClient with lifespan)
   - Verify cleanup_expired_oauth_states() deletes expired rows and leaves valid rows
   - Verify that after connecting a Gmail account, a poll job is registered with the correct ID
   - Verify that after disconnecting, the poll job is removed
```

---

### Chunk 10 — Gmail Polling Worker

**What this builds:** The real `poll_gmail_account()` function. Gmail API client wrapper (mockable), email fetching with pagination, pre-filtering, body snippet truncation.

**Key decisions from PRD:**
- Gmail API client must be behind a thin wrapper interface so integration tests can swap in a mock. Real Gmail API must never be called in CI.
- Pagination: follow `nextPageToken` until exhausted.
- Pre-filter before calling Gemini: known ATS senders (`greenhouse.io`, `lever.co`, `myworkday.com`, `ashbyhq.com`, `icims.com`) OR subject line keywords (`application`, `interview`, `offer`, `next steps`, `unfortunately`, `thank you for applying`). Everything else: skip.
- Body snippet: `body_snippet = email_body[:500]` — explicit truncation before insert.
- Log hygiene: only log `gmail_message_id`, `email_account_id`, `action_taken`, timestamps. No body content.

**Claude Code Prompt:**
```
I'm building chunk 10 of job-tracker-v2: the Gmail polling worker.

IMPORTANT — LOG HYGIENE: Never log email body content, subject lines, or sender addresses in full. Only log: gmail_message_id, email_account_id, action_taken (e.g. "pre_filter_pass", "pre_filter_skip", "stored", "dedup_skip"), timestamps, and error types. Note: pre_filter_skip is logged but no DB write occurs — this is intentional.

1. backend/app/utils/gmail_client.py — Gmail API wrapper interface:
   
   class GmailClientInterface:
     def get_messages_since(self, account_id: str, since_timestamp: datetime, page_token=None) -> dict:
       raise NotImplementedError
     def get_message_detail(self, message_id: str) -> dict:
       raise NotImplementedError
   
   class RealGmailClient(GmailClientInterface):
     def __init__(self, credentials):
       self.service = build("gmail", "v1", credentials=credentials)
     def get_messages_since(self, account_id, since_timestamp, page_token=None):
       # Call Gmail API: users.messages.list with q="after:{unix_timestamp}" and pageToken if provided
       # Returns {"messages": [...], "nextPageToken": "..." or absent}
     def get_message_detail(self, message_id):
       # Call Gmail API: users.messages.get with format="metadata" + "snippet"
       # Returns message with headers (Subject, From, Date) and snippet
   
   class MockGmailClient(GmailClientInterface):
     def __init__(self, messages=None):
       self.messages = messages or []
     def get_messages_since(self, account_id, since_timestamp, page_token=None):
       return {"messages": [{"id": m["id"]} for m in self.messages]}
     def get_message_detail(self, message_id):
       return next(m for m in self.messages if m["id"] == message_id)

2. backend/app/utils/email_filter.py — pre-filter logic:
   
   KNOWN_ATS_DOMAINS = ["greenhouse.io", "lever.co", "myworkday.com", "ashbyhq.com", "icims.com", "smartrecruiters.com", "taleo.net", "successfactors.com"]
   
   JOB_SUBJECT_KEYWORDS = ["application", "interview", "offer", "next steps", "unfortunately", "thank you for applying", "position", "opportunity", "career", "hiring", "candidate"]
   
   is_job_related(sender: str, subject: str) -> bool:
   - Check if sender domain is in KNOWN_ATS_DOMAINS → True
   - Check if any keyword appears in subject.lower() → True
   - Otherwise → False

3. backend/app/jobs/poll_job.py — replace stub with real implementation:
   
   poll_gmail_account(account_id: str, gmail_client: GmailClientInterface = None):
   - Open DB session
   - Load EmailAccount by account_id; if not found log warning and return
   - Decrypt access_token and refresh_token using encryption utility
   - Build google.oauth2.credentials.Credentials from tokens
   - If gmail_client is None: use RealGmailClient(credentials)
   - Set since = account.last_polled_at or (now() - 30 days) for first poll
   
   PAGE LOOP:
   - Call gmail_client.get_messages_since(account_id, since, page_token)
   - For each message_id in results:
     - Check if gmail_message_id already exists in raw_emails (dedup) — skip if yes
     - Call gmail_client.get_message_detail(message_id)
     - Extract: subject, sender, received_at (from Date header), body = message["snippet"]
     - body_snippet = body[:500]  # EXPLICIT truncation — required
     - Pre-filter: if not is_job_related(sender, subject): log action_taken="pre_filter_skip" and continue — do NOT write to raw_emails. Per PRD Section 11: "Everything else → skip, no Gemini call, no storage." Storing pre-filtered emails defeats the purpose of the filter and bloats the table with noise.
     - Otherwise: store email with gemini_signal=None for now (Gemini classification added in chunk 11)
     - Log: {"gmail_message_id": id, "email_account_id": account_id, "action_taken": "stored"}
   - If nextPageToken present: loop with new page_token
   - After all pages: update account.last_polled_at = now()
   
   Handle token refresh: if credentials.expired, refresh using google.auth.transport.requests.Request(). Update stored tokens in DB.
   
   If token refresh fails: log warning with email_account_id, do NOT raise (let other accounts poll normally).

4. INTEGRATION TESTS — backend/tests/test_poll_worker.py:
   Use MockGmailClient — never call real Gmail API in tests.
   
   - poll_gmail_account with empty inbox: last_polled_at updated, no raw_emails created
   - poll_gmail_account with ATS sender email: raw_email row created with correct fields, body_snippet truncated to 500 chars
   - poll_gmail_account with non-ATS, non-keyword email: raw_email NOT stored at all (verify raw_emails table has 0 rows after poll)
   - poll_gmail_account with already-seen gmail_message_id: no duplicate created
   - poll_gmail_account with paginated results (mock returns nextPageToken): all pages processed
   - Verify body_snippet is never longer than 500 characters regardless of input length
```

---

### Chunk 11 — Gemini Integration

**What this builds:** The Gemini 2.5 Flash classification service with the structured prompt, confidence threshold, exponential backoff on rate limit errors, and `PARSE_ERROR` handling.

**Key decisions from PRD:**
- Model: `gemini-2.5-flash`
- Confidence threshold: `>= 0.75`. Below threshold: store with `gemini_signal = "BELOW_THRESHOLD"`, no status change.
- Backoff: on 429 from Gemini, retry up to 3 times with delays: 2s, 4s, 8s (with jitter). After 3 retries: store with `gemini_signal = "PARSE_ERROR"`, move on.
- Prompt must request JSON-only response — no markdown, no explanation.
- The poll worker calls classify_email() after the pre-filter pass.

**Claude Code Prompt:**
```
I'm building chunk 11 of job-tracker-v2: Gemini 2.5 Flash email classification.

1. backend/app/services/gemini_service.py:
   
   CLASSIFICATION_PROMPT = """
   You are classifying a job application email.
   
   Email subject: {subject}
   Email sender: {sender}
   Email body: {body_snippet}
   
   Respond ONLY with a JSON object, no markdown, no explanation:
   {{
     "company": "<company name or null>",
     "role": "<job title or null>",
     "signal": "APPLIED|INTERVIEW|OFFER|REJECTED|IRRELEVANT",
     "confidence": <0.0 to 1.0>
   }}
   
   signal definitions:
   - APPLIED: confirms a job application was received by the employer
   - INTERVIEW: invites the candidate to interview or schedule a screening call
   - OFFER: extends a job offer to the candidate
   - REJECTED: informs the candidate they will not be moving forward
   - IRRELEVANT: this email is not related to a job application
   """
   
   class GeminiClassificationResult:
     company: str | None
     role: str | None
     signal: str  # APPLIED|INTERVIEW|OFFER|REJECTED|IRRELEVANT|BELOW_THRESHOLD|PARSE_ERROR
     confidence: float
   
   classify_email(subject: str, sender: str, body_snippet: str) -> GeminiClassificationResult:
   - Build prompt with subject, sender, body_snippet
   - Call Gemini 2.5 Flash API (model="gemini-2.5-flash")
   - Parse JSON response — strip any markdown backticks before json.loads()
   - On any API error (ResourceExhausted/429): exponential backoff with jitter:
     attempt 1: sleep 2s + random(0, 1)
     attempt 2: sleep 4s + random(0, 1)
     attempt 3: sleep 8s + random(0, 1)
     After 3 retries: return GeminiClassificationResult(signal="PARSE_ERROR", confidence=0.0, company=None, role=None)
   - On JSON parse failure: return GeminiClassificationResult(signal="PARSE_ERROR", ...)
   - On confidence < 0.75: return result with signal="BELOW_THRESHOLD" (overwrite the parsed signal)
   
   LOG per classification (using get_logger("gemini_classifier")):
   {"gemini_signal": result.signal, "gemini_confidence": result.confidence, "action_taken": "classified"}
   Never log subject, sender, or body_snippet.

2. Update backend/app/jobs/poll_job.py — integrate Gemini after pre-filter pass:
   For each pre-filter passing email:
   - Call classify_email(subject, sender, body_snippet)
   - Update raw_emails row with gemini_signal and gemini_confidence
   - Log result (signal + confidence only, no email content)
   - If signal is APPLIED/INTERVIEW/OFFER/REJECTED and confidence >= 0.75: pass to application update logic (chunk 12 — leave as TODO stub for now)

3. INTEGRATION TESTS — backend/tests/test_gemini.py:
   Mock the Gemini API client — never call real Gemini in tests.
   
   - APPLIED signal with confidence 0.9: returns APPLIED signal
   - APPLIED signal with confidence 0.6: returns BELOW_THRESHOLD (confidence gate fires)
   - Malformed JSON response: returns PARSE_ERROR
   - API 429 on first call, success on second: verify retry logic (mock returns 429 once then 200)
   - Three consecutive 429s: returns PARSE_ERROR after exhausting retries
   - IRRELEVANT signal: returned as-is, no status change triggered
   - Verify no email content appears in log output during classification
```

---

### Chunk 12 — Email → Application Logic

**What this builds:** The core intelligence layer — company normalization, find-or-create, deduplication, and status transition logic triggered by classified emails.

**Key decisions from PRD:**
- Dedup: `(user_id, source_url)` primary → `(user_id, normalized_company_name)` fallback. Role excluded.
- `date_applied`: set to `received_at` from the `raw_emails` record, not `now()`.
- Find-or-create: shared utility from chunk 4. Both `name` and `normalized_name` must be set on insert.
- Phase 2 transitions (`APPLIED→INTERVIEW`, `INTERVIEW→OFFER/REJECTED`) are intentionally not wired yet — this chunk only wires `IN_PROGRESS→APPLIED` and creates new records for other signals.

**Claude Code Prompt:**
```
I'm building chunk 12 of job-tracker-v2: email to application create/update logic.

This is the core intelligence layer. It is called by the poll worker after a Gemini classification returns an actionable signal.

1. backend/app/services/email_application_service.py:

process_email_signal(db, user_id: UUID, raw_email: RawEmail, classification: GeminiClassificationResult):
"""
Called after Gemini classifies an email with confidence >= 0.75 and signal in APPLIED/INTERVIEW/OFFER/REJECTED.
"""

STEP 1 — Find matching application:
  # Primary dedup: source_url
  if classification signal is APPLIED:
    # Try to find an IN_PROGRESS application for this user with a matching source_url
    # We don't have the source_url from the email — we search all IN_PROGRESS apps for this user
    # and check if any have a source_url (they were created by the extension)
    # If exactly one IN_PROGRESS application exists for this user with this company (normalized),
    # use source_url matching: find IN_PROGRESS where user_id=user_id AND source_url IS NOT NULL
    # ordered by created_at DESC — take the most recently created one if company matches
    # Fallback: find application where user_id=user_id AND company.normalized_name = normalize(classification.company)
    # and status = IN_PROGRESS
  else:
    # For INTERVIEW/OFFER/REJECTED signals: find APPLIED application by normalized company name
    # (source_url matching not applicable here — these are follow-up emails)
    # find application where user_id=user_id AND company.normalized_name = normalize(classification.company) AND status = APPLIED/INTERVIEW

STEP 2 — Apply transition or create:
  If IN_PROGRESS found and signal is APPLIED:
    - Update status to APPLIED
    - Set date_applied = raw_email.received_at (NOT now())
    - Set raw_email.linked_application_id = application.id
    - Log: {"action_taken": "status_updated", "from": "IN_PROGRESS", "to": "APPLIED", "application_id": str(app.id)}
  
  If APPLIED found and signal is INTERVIEW:
    [Phase 2 — not wired yet]
    Log: {"action_taken": "no_op_phase2", "signal": "INTERVIEW"}
    return
  
  If INTERVIEW found and signal is OFFER or REJECTED:
    [Phase 2 — not wired yet]
    Log: {"action_taken": "no_op_phase2", "signal": signal}
    return
  
  If no matching application found and signal is APPLIED:
    - find_or_create_company(db, user_id, classification.company)
    - Create new Application with status=APPLIED, date_applied=raw_email.received_at, role=classification.role
    - Set raw_email.linked_application_id = application.id
    - Log: {"action_taken": "application_created", "status": "APPLIED"}
  
  If no matching application found and signal is INTERVIEW/OFFER/REJECTED:
    - Create new Application with that status (company find-or-create)
    - Log: {"action_taken": "application_created", "status": signal}
  
  Invalid transition:
    - Log: {"action_taken": "no_op_invalid_transition", "reason": "..."}
    - Do NOT raise — just return

2. Update backend/app/jobs/poll_job.py:
   Replace the "TODO stub" from chunk 11 with a call to process_email_signal()

3. INTEGRATION TESTS — backend/tests/test_email_application_service.py:
   - IN_PROGRESS application + APPLIED signal: updates to APPLIED, date_applied = email received_at (not now)
   - IN_PROGRESS application + APPLIED signal: dedup by source_url — find correct app among multiple IN_PROGRESS
   - No matching application + APPLIED signal: creates new APPLIED application
   - No matching application + APPLIED signal with company "Google LLC": normalizes to "google", finds existing "Google" company
   - APPLIED application + INTERVIEW signal: no_op (Phase 2 not wired), no status change
   - duplicate gmail_message_id: not processed twice (dedup in poll worker)
   - date_applied is set to received_at of email, not current timestamp
```

---

### Chunk 13 — Extension Capture Endpoint

**What this builds:** `POST /extension/capture` — the endpoint the Chrome extension calls when a user confirms tracking a job application. Creates an `IN_PROGRESS` application with a job description record.

**Key decisions from PRD:**
- Rate limit: 60/hr per user (configured in chunk 5 — verify it applies).
- `source_url` stored on application — used as primary dedup key for later email matching.
- `IN_PROGRESS` status only settable through this endpoint.
- `job_descriptions` record created alongside the application.
- Validate `source_url` with `HttpUrl`. If test ATS URLs (Workday, Greenhouse, Lever) fail validation, switch to `AnyUrl` for both `source_url` and `company.link` consistently.
- Company find-or-create shared utility from chunk 4.

**Claude Code Prompt:**
```
I'm building chunk 13 of job-tracker-v2: the POST /extension/capture endpoint.

This endpoint is called by the Chrome extension when a user confirms they want to track an application.

1. backend/app/schemas/extension.py:
   ExtensionCaptureRequest:
   - company_name: str, max_length=255
   - role: str, max_length=255
   - job_description: str, max_length=50000  # CRITICAL: must be capped — extension can scrape large pages
   - source_url: HttpUrl (or AnyUrl if HttpUrl rejects valid ATS URLs — test before finalizing)
   - model_config = ConfigDict(extra='forbid')
   
   ExtensionCaptureResponse:
   - application_id: UUID
   - company_id: UUID
   - status: str  # always "IN_PROGRESS"
   - message: str

2. backend/app/routers/extension.py:
   POST /extension/capture (requires auth, 60/hr rate limit):
   - Parse ExtensionCaptureRequest
   - find_or_create_company(db, user_id=current_user.id, name=request.company_name)
   - Check if an IN_PROGRESS application already exists for (user_id, source_url) — if so, update job_description and return existing application (idempotent)
   - Create Application: user_id, company_id, role=request.role, status=IN_PROGRESS, source_url=str(request.source_url)
   - Create JobDescription: application_id=application.id, raw_text=request.job_description, captured_at=now()
   - Return ExtensionCaptureResponse

3. IMPORTANT URL VALIDATION TEST:
   Before finalizing the schema, test these URLs with Pydantic's HttpUrl:
   - https://myworkday.com/wday/cxs/google/googlecareers/jobs/12345
   - https://boards.greenhouse.io/google/jobs/12345
   - https://jobs.lever.co/google/abc-123
   - https://app.ashbyhq.com/google/job/12345
   If any are rejected, switch source_url to AnyUrl AND switch company.link in CompanyCreate to AnyUrl too (same decision for both).
   Document which validator was chosen and why in a comment in the schema file.

4. INTEGRATION TESTS — backend/tests/test_extension_capture.py:
   - POST /extension/capture with valid data: creates IN_PROGRESS application and job_description
   - source_url is stored on application
   - Duplicate capture (same source_url): returns existing application, updates job_description
   - job_description.raw_text is stored correctly
   - company find-or-create: "Google LLC" normalized to "google", matches existing "Google" company
   - Field over max_length returns 422
   - Extra field in request body returns 422 (extra='forbid')
   - IN_PROGRESS cannot be set via PATCH /applications/{id}: verify 400 is returned
   - Rate limit: 61st request in an hour returns 429
```

---

### Chunk 14 — Next.js Frontend

**What this builds:** The complete Next.js frontend application. Auth with Supabase, Kanban dashboard, application detail page, settings page with data rights actions, and the first-run setup checklist.

**Key decisions from PRD:**
- Auth redirects: `/` redirects to `/dashboard` if authenticated; all protected routes redirect to `/` if not.
- First-run checklist: Gmail connect (1), Install extension (2), Apply to a job (3). Extension detection via `document.getElementById("job-tracker-v2-ext")` (injected by extension in chunk 15).
- Email timeline is a **Phase 2 feature** — render a placeholder on the detail page only.
- "Correct status" dropdown: all valid statuses except `IN_PROGRESS`.
- "No JD captured" state: shown when application has no linked `job_description`.
- JWT handshake: all `chrome.runtime.*` calls must be inside `useEffect` with `typeof chrome !== 'undefined'` guard.
- Settings page: Export (downloads JSON), Delete account (confirmation modal), Disconnect Gmail per account.
- `NEXT_PUBLIC_EXTENSION_ID` used to target the extension for message passing.

**Claude Code Prompt:**
```
I'm building chunk 14 of job-tracker-v2: the complete Next.js frontend.

Stack: Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui.
All API calls go to NEXT_PUBLIC_API_BASE_URL (FastAPI). Auth via Supabase Auth SDK.

SETUP:
- Initialize Next.js project in frontend/ directory
- Install: @supabase/supabase-js, @supabase/ssr, shadcn/ui (init with default theme)
- Configure Tailwind

AUTH SETUP (frontend/lib/supabase.ts):
- createBrowserClient using NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
- Auth provider component wrapping the app
- useUser() hook returning current session

MIDDLEWARE (frontend/middleware.ts):
- Protect /dashboard, /applications/*, /settings — redirect to / if no session
- Redirect / to /dashboard if session exists

PAGES:

1. / (Landing page):
- "Sign in with Google" button using Supabase Auth signInWithOAuth({provider: 'google'})
- Brief product description
- If authenticated: redirect to /dashboard (handled by middleware)
- Placeholder section for "Approved by Google" badge (shows nothing now)

2. /dashboard (Kanban board):
- Fetch GET /applications from FastAPI with Authorization header
- 5 columns: In Progress, Applied, Interview, Offer, Rejected
- Each card shows: company name, role, date_applied (or created_at for IN_PROGRESS), status badge
- Click card → navigates to /applications/[id]
- FIRST-RUN CHECKLIST: Show if checklist not yet dismissed (localStorage key: "checklist_dismissed") AND at least one of step 1 or step 2 is incomplete. Once both Gmail is connected AND extension is detected, auto-dismiss (set localStorage key) — the user is fully set up without needing to manually dismiss.
  Step 1: Connect Gmail — shows green checkmark if GET /gmail/accounts returns ≥1 account; otherwise shows link to /settings
  Step 2: Install extension — check document.getElementById("job-tracker-v2-ext") in useEffect; green checkmark if found, install instructions if not
  Step 3: Apply to a job — shown as pending always; auto-disappears with the rest of the checklist once steps 1+2 are complete and checklist is dismissed. This step is informational — it explains what happens next, not something the frontend can detect.
  "Dismiss" button always available — sets localStorage key and hides checklist regardless of completion state

3. /applications/[id] (Application detail):
- Fetch GET /applications/{id} from FastAPI
- Show: company name, role, status badge, date_applied, source_url (link if present), notes
- JOB DESCRIPTION SECTION:
  If job_description exists: show raw_text in a scrollable block with "Captured at apply time" label
  If no job_description: show "Job description not captured — the extension was not active when this application was detected."
- EMAIL TIMELINE SECTION: Placeholder only — "Email history will appear here (coming soon)"
- CORRECT STATUS: Dropdown with options: APPLIED, INTERVIEW, OFFER, REJECTED (NOT IN_PROGRESS)
  On change: PATCH /applications/{id} with {status: newStatus}
  On success: refetch and update display

4. /settings (Settings page):
- Connected Gmail accounts section:
  List from GET /gmail/accounts
  Each account: email address + "Disconnect" button (calls DELETE /gmail/disconnect/{account_id} with confirmation)
  "Connect Gmail" button (calls GET /gmail/connect, redirects to returned authorization_url)
- Data section (prominent, not buried):
  "Export my data" button: GET /users/me/export, trigger JSON file download named "job-tracker-export.json"
  "Delete my account" button: shows confirmation modal ("This will permanently delete all your data. This cannot be undone."), on confirm: DELETE /users/me, then sign out and redirect to /
- Account info: show email

EXTENSION JWT HANDSHAKE (frontend/lib/extension.ts):
sendTokenToExtension(token: string):
- MUST be called only from useEffect (never during SSR)
- Guard: if (typeof chrome === 'undefined' || !chrome.runtime) return
- const extensionId = process.env.NEXT_PUBLIC_EXTENSION_ID
- if (!extensionId) return
- chrome.runtime.sendMessage(extensionId, { type: "SET_AUTH_TOKEN", token }, (response) => { ... })

Call sendTokenToExtension after successful Supabase sign-in and on every session refresh.

API UTILITY (frontend/lib/api.ts):
- fetchAPI(path, options): adds Authorization: Bearer {token} header automatically
- Handles 401 by signing out and redirecting to /

This is a large chunk — focus on functionality over visual polish. Clean, readable UI using shadcn components is the goal.
```

---

### Chunk 15 — Chrome Extension

**What this builds:** The complete Chrome Extension MV3. Background service worker with JWT handshake, content script with form detection and JD extraction, overlay UI, and the extension detection marker.

**Key decisions from PRD:**
- `externally_connectable.matches` in `manifest.json`: locked to `https://your-vercel-app.vercel.app` and `http://localhost:3000`. This is the required security entry — any website could send `SET_AUTH_TOKEN` messages without it.
- Form detection: URL patterns for Workday, Greenhouse, Lever, Ashby, iCIMS AND field presence heuristics.
- JD scraping allowlist: `h1`, `h2`, `h3`, `p`, `li`, `section`, `article` — never `input`, `textarea`, `select`, or `[type=password]`.
- DOM detection element: `<div id="job-tracker-v2-ext" style="display:none">` injected by content script on every page.
- On `401` from FastAPI: clear token, prompt re-login.

**Claude Code Prompt:**
```
I'm building chunk 15 of job-tracker-v2: the Chrome Extension (Manifest V3).

Create all extension files in extension/ directory.

1. extension/manifest.json:
{
  "manifest_version": 3,
  "name": "job-tracker-v2",
  "version": "1.0.0",
  "description": "Automatically tracks job applications",
  "permissions": ["storage", "activeTab", "scripting"],
  "host_permissions": ["https://[your-droplet-ip-or-domain]/*"],
  "background": { "service_worker": "background.js" },
  "content_scripts": [{
    "matches": ["<all_urls>"],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "externally_connectable": {
    "matches": [
      "https://[your-vercel-app].vercel.app",
      "http://localhost:3000"
    ]
  },
  "action": { "default_popup": "popup.html", "default_title": "Job Tracker" }
}

NOTE: Use placeholder URLs. Document in README: "Replace [your-droplet-ip-or-domain] and [your-vercel-app] with actual deployed URLs before publishing."

SECURITY NOTE IN MANIFEST: Add a comment block at top:
/* externally_connectable.matches restricts which origins can send SET_AUTH_TOKEN messages.
   Only the frontend origin is allowed. Without this, any website could inject a fake JWT. */

2. extension/background.js — service worker:

const API_BASE = "https://[your-droplet-ip-or-domain]";

// Listen for SET_AUTH_TOKEN from the frontend (only allowed from externally_connectable origins)
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (message.type === "SET_AUTH_TOKEN") {
    chrome.storage.session.set({ auth_token: message.token }, () => {
      sendResponse({ success: true });
    });
    return true; // async response
  }
  if (message.type === "PING") {
    sendResponse({ pong: true });
    return true;
  }
});

// Listen for capture requests from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "CAPTURE_APPLICATION") {
    chrome.storage.session.get("auth_token", async ({ auth_token }) => {
      if (!auth_token) {
        sendResponse({ success: false, error: "not_authenticated" });
        return;
      }
      try {
        const response = await fetch(`${API_BASE}/extension/capture`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${auth_token}`
          },
          body: JSON.stringify(message.payload)
        });
        if (response.status === 401) {
          // Token expired — clear it and notify content script
          await chrome.storage.session.remove("auth_token");
          sendResponse({ success: false, error: "token_expired" });
          return;
        }
        const data = await response.json();
        sendResponse({ success: true, data });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    });
    return true; // async
  }
});

3. extension/content.js — content script:

// EXTENSION DETECTION MARKER
// Inject a known DOM element so the frontend can detect if the extension is installed
// Frontend checks: document.getElementById("job-tracker-v2-ext")
const marker = document.createElement("div");
marker.id = "job-tracker-v2-ext";
marker.style.display = "none";
document.body.appendChild(marker);

// KNOWN ATS URL PATTERNS
const ATS_PATTERNS = [
  /myworkday\.com/,
  /greenhouse\.io/,
  /lever\.co/,
  /ashbyhq\.com/,
  /icims\.com/,
  /smartrecruiters\.com/,
  /taleo\.net/
];

// JOB FORM FIELD KEYWORDS (look for these in label/placeholder text)
const FORM_FIELD_KEYWORDS = ["first name", "last name", "resume", "cover letter", "phone", "linkedin"];

function isJobApplicationPage() {
  const url = window.location.href.toLowerCase();
  if (ATS_PATTERNS.some(p => p.test(url))) return true;
  
  // Check for form fields suggesting an application form
  const inputs = document.querySelectorAll("input, textarea");
  const labels = document.querySelectorAll("label");
  const allText = [...inputs, ...labels]
    .map(el => (el.placeholder || el.textContent || "").toLowerCase())
    .join(" ");
  return FORM_FIELD_KEYWORDS.filter(k => allText.includes(k)).length >= 2;
}

function extractJobDescription() {
  // SECURITY: Only scrape structural elements — NEVER form field values
  // This prevents accidentally capturing passwords, SSNs, salary expectations, EEO data
  const ALLOWED_SELECTORS = "h1, h2, h3, p, li, section, article";
  const FORBIDDEN_SELECTORS = "input, textarea, select, [type='password'], [type='email']";
  
  const forbidden = new Set(document.querySelectorAll(FORBIDDEN_SELECTORS));
  const elements = document.querySelectorAll(ALLOWED_SELECTORS);
  
  const text = [...elements]
    .filter(el => !forbidden.has(el) && !el.closest(FORBIDDEN_SELECTORS))
    .map(el => el.textContent.trim())
    .filter(t => t.length > 20)
    .join("\n")
    .substring(0, 50000); // Cap at 50000 chars
  
  return text;
}

function extractCompanyAndRole() {
  const title = document.title || "";
  const h1 = document.querySelector("h1")?.textContent || "";
  return { company: "", role: h1 || title }; // Extension user confirms/edits in overlay
}

// Show overlay if this looks like a job application page
let overlayShown = false;
function maybeShowOverlay() {
  if (overlayShown) return;
  if (!isJobApplicationPage()) return;
  overlayShown = true;
  
  const overlay = document.createElement("div");
  overlay.id = "jt-overlay";
  overlay.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:999999;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px;box-shadow:0 4px 6px rgba(0,0,0,0.1);font-family:sans-serif;max-width:300px;";
  overlay.innerHTML = `
    <p style="margin:0 0 8px;font-weight:600;font-size:14px;">Track this application?</p>
    <p style="margin:0 0 12px;font-size:12px;color:#64748b;">job-tracker-v2 will save this to your dashboard</p>
    <div style="display:flex;gap:8px;">
      <button id="jt-confirm" style="flex:1;background:#3b82f6;color:#fff;border:none;border-radius:4px;padding:6px 12px;cursor:pointer;font-size:13px;">Track it</button>
      <button id="jt-dismiss" style="flex:1;background:#f1f5f9;border:none;border-radius:4px;padding:6px 12px;cursor:pointer;font-size:13px;">Dismiss</button>
    </div>
    <p id="jt-status" style="margin:8px 0 0;font-size:12px;color:#64748b;"></p>
  `;
  document.body.appendChild(overlay);
  
  document.getElementById("jt-dismiss").onclick = () => overlay.remove();
  
  document.getElementById("jt-confirm").onclick = () => {
    const { role } = extractCompanyAndRole();
    const jd = extractJobDescription();
    const status = document.getElementById("jt-status");
    status.textContent = "Saving...";
    
    chrome.runtime.sendMessage({
      type: "CAPTURE_APPLICATION",
      payload: {
        company_name: document.title.split("-")[0].trim() || "Unknown",
        role: role.substring(0, 255),
        job_description: jd,
        source_url: window.location.href
      }
    }, (response) => {
      if (response?.error === "token_expired") {
        status.textContent = "Session expired. Please log in via the web app.";
      } else if (response?.error === "not_authenticated") {
        status.textContent = "Please log in to job-tracker-v2 first.";
      } else if (response?.success) {
        status.textContent = "Saved! ✓";
        setTimeout(() => overlay.remove(), 2000);
      } else {
        status.textContent = "Error saving. Try again.";
      }
    });
  };
}

// Run after DOM is ready
if (document.readyState === "complete" || document.readyState === "interactive") {
  setTimeout(maybeShowOverlay, 1500);
} else {
  document.addEventListener("DOMContentLoaded", () => setTimeout(maybeShowOverlay, 1500));
}

4. extension/popup.html — minimal popup:
Simple HTML showing "job-tracker-v2" title and a link to open the dashboard.

5. Update README.md with:
- "Install for testing" guide (5 steps: enable dev mode, load unpacked, copy extension ID, set NEXT_PUBLIC_EXTENSION_ID in .env.local, set EXTENSION_ORIGIN in backend .env)
- Note that externally_connectable URLs must be updated before deploying to production
```

---

## Phase 2 — Interview + Final Outcome

---

### Chunk 16 — Backend Transition Logic for Interview and Final Outcomes

**What this builds:** Wires the `APPLIED→INTERVIEW` and `INTERVIEW→OFFER/REJECTED` transitions in `email_application_service.py`. The Gemini prompt already returns these signals from chunk 11 — this chunk activates the backend action.

**Claude Code Prompt:**
```
I'm building chunk 16 of job-tracker-v2: wiring APPLIED→INTERVIEW and INTERVIEW→OFFER/REJECTED backend transitions.

The Gemini prompt already classifies emails with INTERVIEW, OFFER, and REJECTED signals. Currently in email_application_service.py, these signals hit a "no_op_phase2" branch. This chunk wires the actual transitions.

UPDATE backend/app/services/email_application_service.py:

Replace the Phase 2 no-op branches with real logic:

APPLIED → INTERVIEW:
  - Find application where user_id=user_id AND company.normalized_name = normalize(classification.company) AND status = APPLIED
  - If found: update status to INTERVIEW, set raw_email.linked_application_id
  - If multiple APPLIED applications for same company (unlikely but possible): use the one with most recent created_at
  - Log: {"action_taken": "status_updated", "from": "APPLIED", "to": "INTERVIEW"}
  - If not found: create new INTERVIEW application (they may have applied without extension/Gmail connected earlier)

APPLIED → REJECTED:
  [Already wired from chunk 12 — verify it works]

INTERVIEW → OFFER:
  - Find application where user_id=user_id AND company.normalized_name = normalize(classification.company) AND status = INTERVIEW
  - Update to OFFER
  - Log: {"action_taken": "status_updated", "from": "INTERVIEW", "to": "OFFER"}

INTERVIEW → REJECTED:
  - Same pattern, update to REJECTED

INVALID TRANSITIONS (e.g. IN_PROGRESS → INTERVIEW directly from email):
  - Log: {"action_taken": "no_op_invalid_transition", "current_status": current, "signal": signal}
  - Do NOT raise — just return

INTEGRATION TESTS — backend/tests/test_phase2_transitions.py:
- APPLIED application + INTERVIEW signal: transitions to INTERVIEW
- INTERVIEW application + OFFER signal: transitions to OFFER
- INTERVIEW application + REJECTED signal: transitions to REJECTED
- IN_PROGRESS application + INTERVIEW signal: no_op (invalid transition — IN_PROGRESS can only go to APPLIED)
- OFFER application + REJECTED signal: no_op (terminal state)
- REJECTED application + INTERVIEW signal: no_op (terminal state)
- Each valid transition sets raw_email.linked_application_id correctly
```

---

### Chunk 17 — Email Timeline Component

**What this builds:** The email timeline on the application detail page, showing which emails triggered which status changes.

**Claude Code Prompt:**
```
I'm building chunk 17 of job-tracker-v2: the email timeline component on the application detail page.

BACKEND — add new endpoint:
GET /applications/{id}/emails (requires auth):
- Verify application belongs to current user (404 if not)
- Return all raw_emails where linked_application_id = application_id
- Ordered by received_at ASC
- Response fields per email: id, subject, sender, received_at, gemini_signal, gemini_confidence, body_snippet (for display)
- Rate limit: 60/min per user

Add this route to backend/app/routers/applications.py.

FRONTEND — replace the placeholder in /applications/[id]:

EmailTimeline component (frontend/components/EmailTimeline.tsx):
- Fetches GET /applications/{id}/emails
- Shows a vertical timeline, each entry:
  - Date and time (received_at formatted)
  - Signal badge (color-coded: APPLIED=blue, INTERVIEW=purple, OFFER=green, REJECTED=red, IRRELEVANT=gray)
  - Confidence percentage
  - Sender (truncated)
  - Body snippet (collapsed by default, expand on click)
- Empty state: "No emails linked to this application yet."
- Loading state: skeleton placeholder

Update /applications/[id] page to render <EmailTimeline applicationId={id} /> in place of the "coming soon" placeholder.

INTEGRATION TESTS:
- GET /applications/{id}/emails returns 200 with correct emails
- GET /applications/{id}/emails for non-owned application returns 404
- Empty timeline returns 200 with empty array
- Emails ordered by received_at ASC
```

---

## Deployment Checklist

After all chunks are complete, before sharing the portfolio link:

**Backend (DigitalOcean Droplet):**
- [ ] GitHub Student Developer Pack claimed at education.github.com
- [ ] DigitalOcean $200 credit activated
- [ ] Droplet created: Ubuntu 22.04, 1GB RAM / 1 vCPU ($6/month size)
- [ ] Docker installed on Droplet (`apt install docker.io`)
- [ ] All environment variables set in a `.env` file on the Droplet (use `backend/.env.example` as checklist — includes `DATABASE_URL_DIRECT` and `FRONTEND_URL`)
- [ ] `DATABASE_URL` is the pooled connection (port 6543)
- [ ] `DATABASE_URL_DIRECT` is the direct connection (port 5432)
- [ ] Run `alembic upgrade head` against production DB from the Droplet
- [ ] Docker container running with `--restart unless-stopped` flag (auto-restarts on reboot)
- [ ] Claim free domain via Namecheap in the GitHub Student Developer Pack (e.g. `jobtrackerv2.me`) — required for Let's Encrypt HTTPS; point the domain's A record to the Droplet's public IP in Namecheap's DNS settings
- [ ] HTTPS configured — Caddy or nginx + Let's Encrypt certificate using the Namecheap domain (free, auto-renews)
- [ ] Verify `GET /health` returns 200 over HTTPS
- [ ] Firewall configured: only ports 22 (SSH), 80 (HTTP redirect), 443 (HTTPS) open

**Frontend (Vercel):**
- [ ] All `NEXT_PUBLIC_*` env vars set in Vercel dashboard
- [ ] `NEXT_PUBLIC_API_BASE_URL` points to Droplet HTTPS URL
- [ ] `NEXT_PUBLIC_EXTENSION_ID` set to unpacked extension ID (for dev) or Web Store ID (for prod)
- [ ] Test auth flow end-to-end

**Supabase:**
- [ ] Google OAuth provider enabled in Supabase Auth dashboard
- [ ] Redirect URLs configured: Droplet HTTPS callback URL, localhost for dev
- [ ] RLS manually enabled on all applicable tables in Supabase SQL Editor (done in chunk 3 — verify policies exist before going live)

**Extension:**
- [ ] `manifest.json` `host_permissions` updated to actual Droplet HTTPS URL
- [ ] `externally_connectable.matches` updated to actual Vercel URL
- [ ] Test unpacked extension loads without errors in Chrome
- [ ] README "Install for testing" guide verified by someone else following it cold

**Gmail OAuth:**
- [ ] Google Cloud Console project created with Gmail API enabled
- [ ] OAuth consent screen configured with `gmail.readonly` scope
- [ ] Authorized redirect URI set to `/gmail/callback` on Droplet HTTPS URL
- [ ] Begin Google OAuth verification process (required before non-test users can connect Gmail)
