# CLAUDE.md — job-tracker-v2

This file is read by Claude Code at the start of every session. It contains everything needed to write correct code in this repo without re-explanation. **PRD.md is the source of truth for decisions. BLUEPRINT.md is the source of truth for build order. This file is the source of truth for implementation rules.**

---

## 1. What This Project Is

A job application tracker that requires zero manual entry. A Chrome extension detects when a user is filling out an application form, captures the job description from the page, and creates an `IN_PROGRESS` record in the dashboard. When the employer sends a confirmation email, Gemini 2.5 Flash classifies it and automatically advances the application to `APPLIED`. Subsequent emails (interview invites, rejections, offers) continue to advance the status automatically. The user never has to type anything.

**The two core differentiators:** (1) the `IN_PROGRESS` state — tracked before the user even submits; (2) JD captured at apply time before the posting goes down.

---

## 2. Repo Structure

```
job-tracker-v2/
├── backend/          # FastAPI — all API logic, email polling, Gemini calls
│   ├── app/
│   │   ├── main.py          # FastAPI app + lifespan context manager
│   │   ├── scheduler.py     # APScheduler instance (module-level, not started here)
│   │   ├── database.py      # SQLAlchemy engine + SessionLocal + get_db()
│   │   ├── models/          # SQLAlchemy ORM models only — no logic
│   │   ├── schemas/         # Pydantic request/response schemas only
│   │   ├── routers/         # HTTP handlers only — delegate to services
│   │   ├── services/        # All business logic lives here
│   │   ├── jobs/            # APScheduler job functions
│   │   ├── dependencies/    # FastAPI Depends (auth, rate limiting)
│   │   └── utils/           # Pure shared utilities (encryption, logging, normalization)
│   ├── alembic/             # DB migrations — uses DATABASE_URL_DIRECT only
│   └── tests/
├── frontend/         # Next.js (App Router) + TypeScript + Tailwind + shadcn/ui
├── extension/        # Chrome Extension MV3 — Vanilla JS
├── PRD.md            # Source of truth for all product/architecture decisions
├── BLUEPRINT.md      # Source of truth for build order and chunk prompts
├── SECURITY.md       # Fernet rotation procedure + env var reference
└── CLAUDE.md         # This file
```

**Layer discipline — enforce strictly:**
- Route handlers contain no business logic. They parse the request, call a service, return the response.
- Services contain all business logic. They are tested directly without HTTP.
- Utils are pure functions with no side effects and no DB access.
- Models are ORM definitions only — no methods, no logic.

---

## 3. Tech Stack — Exact Versions Matter

### Backend
| Concern | Choice | Critical detail |
|---------|--------|-----------------|
| Language | Python 3.13 | |
| Framework | FastAPI | Use lifespan context manager, NOT deprecated `@app.on_event` |
| ORM | SQLAlchemy 2.0 | Use `select()` style queries, not legacy `Query` API |
| Migrations | Alembic | Uses `DATABASE_URL_DIRECT` — never `DATABASE_URL` |
| Validation | Pydantic v2 | `model_config = ConfigDict(...)`, not `class Config:` |
| Background jobs | APScheduler `BackgroundScheduler` | NOT `AsyncIOScheduler` |
| Rate limiting | slowapi | |
| Logging | python-json-logger | JSON format — see logging rules below |
| LLM | `gemini-2.5-flash` | This exact model string |
| Token encryption | `cryptography` Fernet | |

### Database
| Connection string | Port | Used by | Notes |
|-------------------|------|---------|-------|
| `DATABASE_URL` | 6543 | FastAPI runtime, SQLAlchemy | PgBouncer pooled — **runtime only** |
| `DATABASE_URL_DIRECT` | 5432 | Alembic migrations only | Direct — **never use at runtime** |

**This is the single most important infrastructure detail in the project.** PgBouncer (port 6543) does not support the DDL transactions that Alembic requires for migrations. Swapping these will either silently fail migrations or exhaust the connection pool.

### Frontend
- Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui
- Supabase Auth SDK (`@supabase/ssr`) — handles Google OAuth2 and JWT refresh
- Direct browser → FastAPI calls (no Next.js API route proxy)

### Extension
- Chrome MV3, Vanilla JS only (no framework)
- Communicates with backend via `fetch()` to FastAPI

---

## 4. Environment Variables

### Backend (`backend/.env.example`)

| Variable | Description | Notes |
|----------|-------------|-------|
| `DATABASE_URL` | Supabase pooled connection (port 6543) | Runtime only |
| `DATABASE_URL_DIRECT` | Supabase direct connection (port 5432) | Alembic only |
| `SUPABASE_URL` | Supabase project URL | |
| `SUPABASE_JWT_SECRET` | JWT verification secret | From Supabase dashboard |
| `GOOGLE_CLIENT_ID` | Gmail OAuth2 client ID | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Gmail OAuth2 client secret | Never expose client-side |
| `GEMINI_API_KEY` | Gemini 2.5 Flash API key | Server-side only, never in frontend/extension |
| `TOKEN_ENCRYPTION_KEY` | Fernet key (base64) | Encrypts Gmail tokens at rest — see SECURITY.md for rotation |
| `FRONTEND_URL` | Deployed Vercel URL (or `http://localhost:3000` in dev) | Used by `/gmail/callback` redirect — never hardcode |
| `EXTENSION_ORIGIN` | `chrome-extension://<id>` | CORS allowlist — differs between dev (unpacked) and prod |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | Include Vercel URL and `EXTENSION_ORIGIN` |
| `SENTRY_DSN` | Sentry error tracking DSN | Optional in dev — skip init if not set |

### Frontend (`frontend/.env.example`)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (safe to expose) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key (intentionally public) |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI backend URL (DigitalOcean Droplet HTTPS URL in production) |
| `NEXT_PUBLIC_EXTENSION_ID` | Extension ID for `chrome.runtime.sendMessage` |

**Rules:**
- No hardcoded URLs anywhere. Always read from env vars.
- `http://localhost:3000` and `http://localhost:8000` must never appear in production code paths — only in `.env.example` defaults.
- `GEMINI_API_KEY` never leaves the backend. Never reference it in frontend or extension code.

---

## 5. Data Model — Quick Reference

All PKs are UUID. All FKs use `ON DELETE CASCADE` except `raw_emails.linked_application_id` which uses `ON DELETE SET NULL`.

```
users           id (UUID PK = Supabase Auth UUID)
                email, created_at

companies       id, user_id→users, name, normalized_name, location, link, created_at
                UniqueConstraint(user_id, normalized_name)

applications    id, user_id→users, company_id→companies, role, status(ENUM),
                source_url (nullable), date_applied (nullable), notes, created_at

interviews      id, application_id→applications, round_type(ENUM), scheduled_at,
                outcome(ENUM), notes, created_at

job_descriptions  id, application_id→applications (unique), raw_text, captured_at
                  NO source_url — canonical URL lives on applications.source_url

email_accounts  id, user_id→users, email, access_token(encrypted), refresh_token(encrypted),
                token_expiry, last_polled_at, created_at

raw_emails      id, email_account_id→email_accounts, gmail_message_id(unique),
                subject, sender, received_at, body_snippet, gemini_signal,
                gemini_confidence, linked_application_id→applications(SET NULL), created_at

gmail_oauth_states  state_token(PK), user_id→users(CASCADE), expires_at
```

**Critical data model rules:**
- `users.id` IS the Supabase Auth UUID — set directly from `payload["sub"]`. There is no `supabase_id` column.
- `job_descriptions` has no `source_url` column. Read it from `applications.source_url`.
- `companies` stores both `name` (original) and `normalized_name` (normalized). Both must be set on insert.
- `applications.date_applied` is set to the `received_at` of the confirmation email, not `datetime.utcnow()`.

---

## 6. Application Status Model

```
IN_PROGRESS → APPLIED → INTERVIEW → OFFER
                      ↘              ↘
                       REJECTED       REJECTED
```

**Valid system-triggered transitions only:**

| From | To | Trigger |
|------|----|---------|
| `IN_PROGRESS` | `APPLIED` | Confirmation email (Gemini signal) |
| `APPLIED` | `INTERVIEW` | Interview invite email |
| `APPLIED` | `REJECTED` | Rejection email |
| `INTERVIEW` | `OFFER` | Offer email |
| `INTERVIEW` | `REJECTED` | Rejection email |

**Rules:**
- `IN_PROGRESS` → `APPLIED` is the only valid transition out of `IN_PROGRESS`. All others are no-ops.
- `OFFER` and `REJECTED` are terminal states — no transitions out.
- Invalid transitions are **no-ops with logging**, never errors. The poll worker must not raise on an invalid transition.
- Manual override via `PATCH /applications/{id}` bypasses transition rules entirely — users can correct wrong Gemini classifications. The only restriction: `IN_PROGRESS` can never be set via PATCH. `ApplicationUpdate.status` must be `Literal["APPLIED", "INTERVIEW", "OFFER", "REJECTED"]` — `IN_PROGRESS` excluded.
- `IN_PROGRESS` is only settable by `POST /extension/capture`. Never by any other path.

---

## 7. Deduplication Strategy

When an email is classified, the system must find an existing application to update rather than creating a duplicate. The dedup key is:

**1. Primary — `(user_id, source_url)`**: When an `IN_PROGRESS` application exists with a `source_url`, match against it. This is deterministic — the URL doesn't change between extension capture and confirmation email.

**2. Fallback — `(user_id, normalized_company_name)`**: When no `source_url` match exists, fall back to normalized company name. Role is **excluded** from the fallback key — role titles between the extension and email frequently differ ("Software Engineer Intern" vs "SWE Intern 2026").

**Company name normalization** — lives in `utils/company.py`, imported by both `company_service.py` and `email_application_service.py`. Never reimplement inline.

```python
def normalize_company_name(name: str) -> str:
    name = name.lower().strip()
    # Step 1: strip trailing punctuation FIRST
    # Important: "google inc." becomes "google inc" here — so the suffix list
    # must include both "inc." AND "inc" to handle both orderings robustly.
    name = name.rstrip(".,;:")
    # Step 2: strip legal suffixes — loop until no more matches
    # Single-pass loop fails on "Google Inc. LLC" (strips "llc", misses "inc.")
    suffixes = ["llc", "inc.", "inc", "corp.", "corp", "ltd.", "ltd",
                "limited", "co.", "co"]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if name.endswith(f" {suffix}"):
                name = name[: -(len(suffix) + 1)].rstrip()
                changed = True
                break  # restart the loop after each match
    return name
```

**Company find-or-create** — shared utility, used in both `/extension/capture` and email → application paths:
1. Normalize the name
2. Query by `(user_id, normalized_name)`
3. If found → return existing
4. If not found → create with **both** `name` (original) **and** `normalized_name` set. If `normalized_name` is missing on insert, all future lookups against that record silently return nothing.

---

## 8. Non-Negotiable Code Patterns

These apply to every file, every chunk. Claude Code must not deviate from these.

### Pydantic Schemas
Every request schema must have:
```python
model_config = ConfigDict(extra='forbid')
```
Without this, extra fields are silently ignored — a mass assignment vulnerability.

Field length limits (enforce with `Field(max_length=...)`):
- `company.name`: 255 | `company.location`: 255 | `company.link`: 2048
- `application.role`: 255 | `application.notes`: 5000
- `interview.notes`: 5000
- `extension.company_name`: 255 | `extension.role`: 255 | `extension.source_url`: 2048
- `extension.job_description`: 50000 ← critical cap, extension can scrape huge pages

### Route Handlers
```python
# PATCH must use exclude_unset=True — partial updates only
update_data = body.model_dump(exclude_unset=True)

# All queries scoped to user_id
application = db.scalar(
    select(Application).where(
        Application.id == application_id,
        Application.user_id == current_user.id  # always
    )
)
if not application:
    raise HTTPException(status_code=404)  # 404, never 403
```

### APScheduler
```python
# Instance created at module level in app/scheduler.py
scheduler = BackgroundScheduler()  # not started here

# Started in main.py lifespan:
@asynccontextmanager
async def lifespan(app):
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

# Every poll job registered with max_instances=1:
scheduler.add_job(fn, "interval", minutes=15, id=job_id,
                  max_instances=1, replace_existing=True)

# Job cancellation in DELETE /users/me:
try:
    scheduler.remove_job(f"poll_{account.id}")
except JobLookupError:
    pass  # job not registered yet — ignore gracefully
```

### Token Encryption
Fresh OAuth tokens from Google are plaintext. Encrypt before storing — never "decrypt then re-encrypt":
```python
# Storing new tokens:
account.access_token = encrypt_token(credentials.token)
account.refresh_token = encrypt_token(credentials.refresh_token)

# Reading for use:
access_token = decrypt_token(account.access_token)
```

### Body Snippet Truncation
Always explicit — never assume truncation happens elsewhere:
```python
body_snippet = email_body[:500]  # explicit — do not rely on DB constraints
```

### chrome.runtime in Next.js
All `chrome.runtime.*` calls must be inside `useEffect` with a guard — Next.js App Router runs code server-side and `chrome` does not exist in Node.js:
```typescript
useEffect(() => {
  if (typeof chrome === 'undefined' || !chrome.runtime) return;
  // safe to use chrome.runtime here
}, []);
```

---

## 9. Security Rules

### Log Hygiene — GDPR/PIPEDA requirement
The poll worker processes PII. These fields **must never appear in any log statement**:
- Email body content or body snippets
- Email subject lines
- Sender email addresses (in full)
- Any user-authored text

**Permitted log fields only:** `gmail_message_id`, `email_account_id`, `gemini_signal`, `gemini_confidence`, `action_taken`, `application_id`, `user_id`, timestamps, error types.

### Pre-filter Rule — PRD Section 11
Emails that fail the pre-filter (not from a known ATS domain and no job-related keywords in subject) are:
- Logged with `action_taken="pre_filter_skip"`
- **NOT written to `raw_emails`**

This is non-negotiable. Storing pre-filtered emails defeats the cost control purpose and bloats the user's data export with noise.

### Gmail OAuth CSRF
`GET /gmail/callback` has **no auth dependency**. There is no JWT on this request — Google's redirect carries none. The `user_id` comes exclusively from the `gmail_oauth_states` DB row:
```python
user_id = consume_state_token(db, state)  # validates + deletes the state row
# proceed to store tokens under user_id
```
Never add an auth dependency to this endpoint.

### CORS
```python
origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
origins.append(os.getenv("EXTENSION_ORIGIN", ""))
# Never: allow_origins=["*"]
```

### extension externally_connectable
The `manifest.json` must restrict which origins can send `SET_AUTH_TOKEN` messages:
```json
"externally_connectable": {
  "matches": ["https://your-vercel-app.vercel.app", "http://localhost:3000"]
}
```
Without this, any website can inject a fake JWT into the extension.

### Extension DOM Scraping
The content script must **never** read values from form fields. Only structural elements:
- Allowed: `h1, h2, h3, p, li, section, article`
- Forbidden: `input, textarea, select, [type=password]`

---

## 10. Testing Conventions

- **Real PostgreSQL** for all integration tests via `DATABASE_URL_DIRECT` (set to test DB in CI and locally)
- **Transaction rollback** per test — not truncation, not a fresh DB per test
- **Gmail API**: always use `MockGmailClient`. Never call real Gmail API in tests or CI.
- **Gemini API**: always mock. Never call real Gemini API in tests or CI.
- **APScheduler**: import `scheduler` from `app.scheduler` and mock `scheduler.add_job` / `scheduler.remove_job` in tests that verify job registration
- `conftest.py` provides: `db` session fixture, `test_user` fixture (real DB row), `auth_headers` fixture (valid JWT headers)

### CI Pipeline
```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: tracker
      POSTGRES_PASSWORD: tracker
      POSTGRES_DB: tracker_test

env:
  DATABASE_URL_DIRECT: postgresql://tracker:tracker@localhost:5432/tracker_test
  DATABASE_URL: postgresql://tracker:tracker@localhost:5432/tracker_test

steps:
  - ruff check backend/
  - pip-audit
  - alembic upgrade head   # run before pytest — tables must exist
  - pytest backend/tests/ -v
```

---

## 11. Gemini Integration

**Model:** `gemini-2.5-flash` — exact string, no variation.

**Classification signals:** `APPLIED | INTERVIEW | OFFER | REJECTED | IRRELEVANT`

**Signal dispositions — what happens with each result:**

| Signal | Confidence | Action | Stored in raw_emails? |
|--------|-----------|--------|----------------------|
| `APPLIED` / `INTERVIEW` / `OFFER` / `REJECTED` | ≥ 0.75 | Status transition fires | ✓ Yes |
| Any actionable signal | < 0.75 | `gemini_signal = "BELOW_THRESHOLD"`, no status change | ✓ Yes |
| `IRRELEVANT` | Any | No status change | ✓ Yes — email passed the pre-filter, Gemini ran, result stored |
| `PARSE_ERROR` | N/A | Gemini failed after retries | ✓ Yes |
| Pre-filter skip | N/A | Never reaches Gemini | ✗ No — log only |

The key distinction: **pre-filter skips are never stored**. Everything that reaches Gemini is stored, regardless of the outcome.

**Backoff on rate limit (429):**
- Retry up to 3 times: 2s → 4s → 8s (add `random.uniform(0, 1)` jitter to each)
- After 3 retries: `gemini_signal = "PARSE_ERROR"`, move on — never block the poll cycle

**Gemini key is server-side only.** Never reference `GEMINI_API_KEY` in frontend or extension code.

---

## 12. What NOT To Do

Read this list before writing any code. These are the most likely mistakes.

| Don't | Do instead |
|-------|-----------|
| Add a `supabase_id` column to users | Use `users.id` = `payload["sub"]` directly |
| Use `ON DELETE RESTRICT` on any FK | Use `ON DELETE CASCADE` (except `linked_application_id` → `SET NULL`) |
| Store pre-filtered emails in `raw_emails` | Log `pre_filter_skip` and `continue` — no DB write |
| Set `date_applied = datetime.utcnow()` | Set `date_applied = raw_email.received_at` |
| Put `source_url` on `job_descriptions` | `source_url` lives on `applications` only |
| Use `allow_origins=["*"]` | Use explicit origin list from env vars |
| Hardcode `http://localhost:3000` or `:8000` | Use `FRONTEND_URL`, `NEXT_PUBLIC_API_BASE_URL` env vars |
| Call `scheduler.start()` at module level | Start it in the `lifespan` context manager only |
| Put business logic in route handlers | Put it in `services/` |
| Set `IN_PROGRESS` via `PATCH /applications/{id}` | `IN_PROGRESS` only settable by `/extension/capture` |
| "Decrypt then re-encrypt" fresh OAuth tokens | Fresh tokens are plaintext — just `encrypt_token()` |
| Use `DATABASE_URL` (port 6543) in Alembic | Use `DATABASE_URL_DIRECT` (port 5432) in `alembic/env.py` |
| Add `supabase_id` kwarg to `get_or_create_user` | Use `id=payload["sub"]` |
| Log email body content or subject lines | Log only permitted metadata fields |
| Check `if not result: raise 403` | Always `raise 404` for non-owned resources |
| Import `routers/gmail.py` before it exists | Apply Gmail rate limits in chunk 7 when the router is created |
| Leave `gmail_oauth_states` row after `/gmail/callback` succeeds | Delete it immediately — state token is single-use; leaving it open is a security regression |
| Enable "automatic RLS" toggle in Supabase settings | Enable RLS manually per table in SQL Editor after migrations run (chunk 3) — automatic RLS fires before policies exist |

---

## 13. Current Build Status

Update this section after completing each chunk. **Do not start a chunk until all listed prerequisites are complete** — later chunks import from earlier ones and will fail otherwise.

| Chunk | Description | Prerequisites | Status |
|-------|-------------|---------------|--------|
| 1 | Repo setup, CI, skeleton | None | ✅ Complete |
| 2 | Supabase Auth integration | 1 | ⬜ Not started |
| 3 | DB migrations | 1, 2 | ⬜ Not started |
| 4 | Core CRUD | 1, 2, 3 | ⬜ Not started |
| 5 | Security baseline | 1, 2, 3, 4 | ⬜ Not started |
| 6 | Logging + Sentry | 1 | ⬜ Not started |
| 7 | Gmail OAuth flow | 1, 2, 3, 5, 6 | ⬜ Not started |
| 8 | Data export + delete | 1, 2, 3, 7 | ⬜ Not started |
| 9 | APScheduler setup | 1, 7 | ⬜ Not started |
| 10 | Gmail polling worker | 1, 7, 8, 9 | ⬜ Not started |
| 11 | Gemini integration | 1, 6, 10 | ⬜ Not started |
| 12 | Email → application logic | 3, 4, 10, 11 | ⬜ Not started |
| 13 | Extension capture endpoint | 3, 4, 5 | ⬜ Not started |
| 14 | Next.js frontend | 2, 3, 4, 7, 8, 13 | ⬜ Not started |
| 15 | Chrome Extension | 5, 13, 14 | ⬜ Not started |
| 16 | Phase 2 transitions | 12 | ⬜ Not started |
| 17 | Email timeline component | 8, 14, 16 | ⬜ Not started |

**Key dependency notes:**
- Chunk 5 (security baseline) creates the shared `Limiter` instance. Chunk 7 (Gmail router) must import and use that limiter — never create a new one.
- Chunk 7 must come before chunks 8, 9, 10 — they all depend on `email_accounts` which is migrated in chunk 7.
- Chunk 9 starts APScheduler. Chunks 10+ rely on the scheduler being correctly configured.

---

## 14. Reference

- Full product decisions, architecture, and data model: **PRD.md**
- Step-by-step build order with Claude Code prompts: **BLUEPRINT.md**
- Fernet rotation procedure and full env var list: **SECURITY.md**
