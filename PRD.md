# PRD — job-tracker-v2
**Status:** Draft v2.2 — Final  
**Last Updated:** 2026-03-17

---

## 1. Problem Statement

Job seekers lose track of their applications because every existing tool requires manual data entry. Users forget to log applications, forget to update statuses after interviews or rejections, and often lose the original job description before they can use it for interview prep or resume tailoring. The friction of manual entry means most people give up on tracking entirely.

The core insight: **the data already exists** — it lives in the job posting page, in the confirmation email, in the recruiter's calendar invite, in the rejection email. The user should never have to type anything.

---

## 2. Target Users

**Primary persona:** Active job seekers — anyone currently applying to jobs, regardless of industry or seniority. This includes new grads, career changers, and experienced professionals in a job search.

**What they have in common:**
- Applying to multiple roles simultaneously (often 10–50+ at a time)
- Using Gmail as their primary email client
- Applying through company websites and ATS platforms (Workday, Greenhouse, Lever, Ashby, etc.)
- Frustrated with the overhead of manually maintaining a spreadsheet or existing tracker

---

## 3. Competitive Landscape

| Tool | Gmail Integration | Zero Manual Entry | Captures JD | "In Progress" State | AI Parsing |
|------|:-----------------:|:-----------------:|:-----------:|:-------------------:|:----------:|
| Teal | ✗ | ✗ | Partial (manual) | ✗ | Generic |
| Huntr | Partial (unreliable) | ✗ | ✗ | ✗ | Generic |
| Simplify | ✗ | ✗ | ✗ | ✗ | ✗ |
| G-Track | ✓ (AI-parsed) | Partial | ✗ | ✗ | ✓ (claims 95%+) |
| **job-tracker-v2** | **✓ (reliable, LLM-parsed)** | **✓** | **✓ (at apply time)** | **✓** | **✓ (structured)** |

**Key differentiation:**
1. **True zero manual entry** — from filling out the form to receiving the rejection, the user never needs to touch the dashboard
2. **JD captured at apply time** — before the posting gets taken down, available for interview prep and resume tailoring later
3. **"In Progress" state** — tracks applications while the user is still filling out the form, not only after submission
4. **Reliable LLM-based email parsing** (Gemini 2.5 Flash) instead of keyword matching, which is why existing integrations like Huntr's miss emails frequently

---

## 4. Product Goals

### Phase 1 Goals (MVP)
- Detect when a user is actively filling out a job application form
- Capture the job description from the page automatically
- Create an application record in the dashboard as "In Progress" with zero user action
- Parse Gmail inbox for job-related emails using Gemini 2.5 Flash
- Auto-create application records from confirmation emails if no "In Progress" record exists
- Auto-update application status from "In Progress" → "Applied" when a confirmation email is received

### Phase 2 Goals (Partial — included in this PRD)
- Auto-update status from "Applied" → "Interview" when an interview invite email is detected
- Auto-update status from "Interview" → "Rejected" or "Offer" when a final outcome email is detected

---

## 5. Non-Goals (Future Scope — not in this PRD)

The following are acknowledged but explicitly out of scope for this build:

- **Stale "In Progress" archiving** — if a user begins an application but never submits it, the JD is captured and the record stays "In Progress". In a future phase, applications stuck in "In Progress" beyond a configurable time window should be automatically moved to an Archive, preserving the data but removing it from the active dashboard. Users should be able to view and restore archived applications. The threshold (e.g. 7 days) is measured in calendar days since `created_at` of the application record — not since last activity, since IN_PROGRESS records have no activity after creation.
- **Follow-up reminders** — "You applied to X 2 weeks ago with no response"
- **Contact tracking** — storing recruiter/hiring manager name and email per application
- **Application analytics** — response rates, avg time per stage, conversion funnels
- **Autofill** — using past answer history to pre-fill application forms
- **Resume tailoring** — AI suggestions based on captured JD
- **Cover letter generation**
- **Interview prep question generation**
- **Salary benchmarking**
- **Monetization / tiered pricing** — free vs. pro vs. premium tiers
- **Per-email sync controls** — the current Gmail integration operates at the account level (connected or not). A future phase should allow users to approve/reject individual synced emails, exclude specific senders or domains, and see a raw list of all emails the system has processed for their account. This is the difference between "we only look at job-related emails" (what the pre-filter does technically) and "you control which emails are synced" (what users actually want to see in a UI).
- **Google OAuth verification trust badge** — once the app completes Google's OAuth verification review for the `gmail.readonly` scope, the resulting "approved by Google" status should be surfaced as a visible trust signal on the landing page. Completing verification is not just a compliance hurdle — it is a marketing asset that directly addresses user privacy concerns about giving Gmail access to a third-party app.

---

## 6. Application Status Model

The full status lifecycle for this product:

```
IN_PROGRESS → APPLIED → INTERVIEW → OFFER
                      ↘              ↘
                       REJECTED       REJECTED
```

**Status definitions:**

| Status | Triggered By |
|--------|-------------|
| `IN_PROGRESS` | Chrome extension detects user on application form |
| `APPLIED` | Confirmation email received (Gemini classified) |
| `INTERVIEW` | Interview invite email received (Gemini classified) |
| `OFFER` | Offer email received (Gemini classified) |
| `REJECTED` | Rejection email received (Gemini classified) |

**Valid transitions (enforced by backend):**

| From | To | Trigger |
|------|----|---------|
| `IN_PROGRESS` | `APPLIED` | Confirmation email |
| `APPLIED` | `INTERVIEW` | Interview invite email |
| `APPLIED` | `REJECTED` | Rejection email |
| `INTERVIEW` | `OFFER` | Offer email |
| `INTERVIEW` | `REJECTED` | Rejection email |

`IN_PROGRESS` can **only** transition to `APPLIED`. It cannot transition directly to `REJECTED` or any other status via email parsing. `OFFER` and `REJECTED` are terminal states.

**Manual override:** The automated transition rules apply only to system-triggered status changes (email parsing). When a user manually changes a status via the detail page, the rules are bypassed entirely — a user can correct any status to any other status, including moving backwards (e.g. correcting a wrong Gemini classification from OFFER back to INTERVIEW). The `PATCH /applications/{id}` endpoint accepts any valid status value when called by the authenticated user directly, **except `IN_PROGRESS`** — `IN_PROGRESS` is only settable by `POST /extension/capture`, never by a user-initiated `PATCH`. The `ApplicationUpdate` Pydantic schema must explicitly exclude `IN_PROGRESS` from the status field's allowed values. The frontend detail page exposes a status correction dropdown for this purpose, clearly labeled "Correct status" to distinguish it from the automated pipeline.

**`date_applied` setting:** When an application transitions to `APPLIED`, `date_applied` is set to the `received_at` timestamp of the confirmation email that triggered the transition — not the current time. This is the most accurate value since it reflects when the employer actually received and acknowledged the application. This is set explicitly in the email → application update path.

**Deduplication strategy (source_url primary, company name fallback):** Matching on `(user_id, company_name, role)` is fragile because role titles extracted by Gemini from emails often differ from what the extension captures from the page (e.g. "Software Engineer Intern" vs "SWE Intern 2026"). The deduplication key is:

1. **Primary key — `source_url`:** When a `source_url` is available on the `IN_PROGRESS` record, match incoming emails against it using `(user_id, source_url)`. The URL is deterministic and doesn't change between the extension capture and the confirmation email. The `source_url` column is added to the `applications` table for this purpose.
2. **Fallback key — `(user_id, normalized_company_name)`:** When no `IN_PROGRESS` record with a matching `source_url` exists, fall back to normalized company name matching. Role is excluded from the fallback key — the risk of two simultaneous applications to the same company is lower than the risk of role title mismatch causing missed deduplication.

**Company name normalization (required for fallback dedup):** Before any company name comparison, normalize: lowercase, strip trailing punctuation, remove common legal suffixes (LLC, Inc, Inc., Corp, Corp., Ltd, Ltd., Limited, Co., Co). Store the original name in the DB but compare only the normalized form.

**Company find-or-create logic (required):** Applications have a `company_id` FK. When the extension sends `company_name` or when Gemini returns a company from an email, the backend must:
1. Normalize the company name (lowercase, strip legal suffixes)
2. Query `companies` for an existing record with `(user_id, normalized_name)`
3. If found → use existing `company_id`
4. If not found → create a new `companies` record, setting **both** `name` (original, unmodified) **and** `normalized_name` (normalized form) on insert. If `normalized_name` is not explicitly set at insert time, all future dedup lookups against that record will silently fail.

This logic applies both in `POST /extension/capture` and in the email → application create path. It must be a shared utility function, not duplicated.

---

## 7. Tech Stack

### Backend
| Concern | Choice | Reason |
|---------|--------|--------|
| Language | Python 3.13 | |
| Framework | FastAPI | Fresh repo, same framework |
| ORM | SQLAlchemy 2.0 | Consistent with project 1 |
| Migrations | Alembic | Consistent with project 1 |
| Background jobs | APScheduler | Gmail polling, no extra infrastructure |
| Rate limiting | slowapi | Per-user rate limiting on extension endpoint |
| Validation | Pydantic v2 | Consistent with project 1 |
| Linting | Ruff | Consistent with project 1 |

### Database & Auth
| Concern | Choice | Reason |
|---------|--------|--------|
| Database | Supabase (hosted PostgreSQL) | Free tier, no sleep, replaces local Postgres |
| Auth | Supabase Auth | Google OAuth2 out of the box, no manual implementation |
| JWT verification | FastAPI dependency | Verify Supabase-issued JWT on all protected routes |

### AI & Email
| Concern | Choice | Reason |
|---------|--------|--------|
| LLM | Gemini 2.5 Flash | Latest capable model, free tier during dev |
| API key model | Server-side, project key | Standard SaaS pattern, user never sees key |
| Email access | Gmail API | OAuth2, separate scope from Supabase Auth |
| Email polling | APScheduler | Every 15 minutes per connected account |

### Frontend
| Concern | Choice | Reason |
|---------|--------|--------|
| Framework | Next.js | Best React framework for dashboards |
| Styling | Tailwind CSS | Utility-first, fast to build with |
| Components | shadcn/ui | Pre-built kanban, tables, cards, modals |
| Language | TypeScript | Better than plain JS |

### Chrome Extension
| Concern | Choice | Reason |
|---------|--------|--------|
| Standard | Manifest V3 | Current Chrome standard |
| Language | Vanilla JavaScript | No framework needed for extension logic |
| Communication | REST API calls to FastAPI | Simple, consistent with rest of stack |

### Infrastructure
| Concern | Choice | Reason |
|---------|--------|--------|
| Backend hosting | DigitalOcean (via GitHub Student Pack) | $200 free credit for 1 year, always-on VPS, no sleep |
| Frontend hosting | Vercel | Free tier, zero-config Next.js deployment |
| Database hosting | Supabase | Free tier, hosted PostgreSQL |
| CI | GitHub Actions | Consistent with project 1 |

### Cost at Zero Users
| Service | Cost |
|---------|------|
| DigitalOcean (FastAPI, via GitHub Student Pack) | $0 — covered by $200 student credit |
| Supabase (DB + Auth) | $0 free tier |
| Vercel (Frontend) | $0 free tier |
| Gemini API | $0 free tier |
| Gmail API | $0 free |
| **Total** | **$0/month** |

---

## 8. Architecture

### System Overview

```
Chrome Extension (Vanilla JS, MV3)
    │
    │  POST /extension/capture (rate limited: 60 req/hr per user)
    ▼
FastAPI Backend (DigitalOcean Droplet)
    │  verifies Supabase JWT on all protected routes
    │  stores JD + creates IN_PROGRESS application
    │  APScheduler polls Gmail every 15 min
    │  sends candidate emails to Gemini 2.5 Flash
    │  updates application status based on parsed result
    │
    ├──── Supabase PostgreSQL (all app data + Alembic migrations)
    └──── Supabase Auth (Google OAuth2 → issues JWT)

Next.js Frontend (Vercel)
    │  Supabase Auth SDK for login
    │  fetches all data from FastAPI
    └──── renders kanban dashboard, application detail, settings
```

### Auth Architecture

Supabase Auth handles the full Google OAuth2 flow. FastAPI has **no auth endpoints** — it only verifies the JWT that Supabase issues.

**Login flow:**
```
User clicks "Sign in with Google" on Next.js frontend
→ Supabase Auth SDK redirects to Google OAuth consent screen
→ Google redirects back to Supabase
→ Supabase creates or retrieves user, issues JWT
→ Frontend stores JWT via Supabase Auth SDK (managed automatically)
→ All FastAPI requests include JWT in Authorization header
→ FastAPI dependency verifies JWT signature against Supabase public key
```

**FastAPI auth dependency (on every protected route):**
```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    payload = verify_supabase_jwt(token)  # validates signature + expiry
    user = get_or_create_user(db, id=payload["sub"], email=payload["email"])
    return user
```

**Why this is simpler than project 1:** No password hashing, no token generation, no register/login endpoints to maintain. FastAPI becomes a pure data API.

**Gmail connection** (separate OAuth scope, triggered explicitly in settings):
```
User clicks "Connect Gmail" in settings
→ Backend generates a random state token, stores it server-side (short-lived, 10 min TTL)
→ Backend initiates Gmail OAuth2 with gmail.readonly scope and state parameter
→ Google OAuth consent screen (separate from Supabase login)
→ Google redirects to /gmail/callback with code AND state
→ Backend verifies state matches stored value before proceeding (CSRF protection)
→ Backend exchanges code for access_token + refresh_token
→ Tokens stored encrypted in email_accounts table
→ User can disconnect at any time — deletes stored tokens
```

**Gmail OAuth CSRF protection (required):** The `state` parameter is mandatory, not optional. Without it, `GET /gmail/callback` is vulnerable to CSRF — an attacker can trick a user's browser into submitting a forged callback with an attacker-controlled authorization code, potentially linking the attacker's Gmail tokens to the victim's account.

The state token must be stored in a **DB table**, not an in-memory dict. The FastAPI process can restart at any time — during a deploy, on an OOM kill, or on a manual server reboot. If the process restarts between the user clicking "Connect Gmail" and the OAuth callback returning, an in-memory dict loses the state token — the callback verification fails and the user gets a confusing error with no recovery path. A DB row survives restarts.

State storage table: `gmail_oauth_states` with columns `(state_token VARCHAR PK, user_id UUID FK → users, expires_at TIMESTAMP)`. On `/gmail/connect`: insert a row with `state_token = secrets.token_urlsafe(32)`, `expires_at = now() + 10 minutes`. On `/gmail/callback`: query by `state_token`, verify it exists and has not expired, retrieve the `user_id` from the state row — this is the user who initiated the OAuth flow, and is the correct binding without needing a JWT (there is no authenticated user at callback time; Google's redirect carries no JWT). Delete the row (single use), then proceed to exchange the code and store tokens under that `user_id`. This table gets one migration added in step 7 of the build order.

**Why two separate consent screens:** Login identity (Supabase) and Gmail data access are different trust levels. Bundling them into one first-run consent screen feels invasive and is a common reason users abandon OAuth-gated products. `gmail.readonly` scope only also addresses privacy concerns about giving small apps broad Gmail access.

### Email Polling Architecture

**Approach:** APScheduler (in-process, inside FastAPI). Polls every 15 minutes per connected Gmail account.

**Why not Celery + Redis for MVP:** Adds ops complexity — a Redis instance and a separate worker process to deploy and manage on the Droplet. APScheduler runs inside the FastAPI process and is sufficient for MVP scale. If polling volume grows, the worker logic can be extracted to Celery without changes to the job functions themselves.

**Polling flow per account:**
1. Fetch emails from Gmail API since `last_polled_at` timestamp
2. Pre-filter: pass only emails from known ATS senders (greenhouse.io, lever.co, myworkday.com, ashbyhq.com, icims.com, etc.) or emails whose subject line contains job-related keywords ("application", "interview", "offer", "next steps", "unfortunately", "thank you for applying")
3. For each candidate email, call Gemini 2.5 Flash with structured classification prompt
4. Gemini returns `{ company, role, signal, confidence }`
5. If `confidence >= 0.75` and signal is actionable:
   - Find existing application using dedup strategy from Section 6: `(user_id, source_url)` as primary key if `source_url` is known, falling back to `(user_id, normalized_company_name)` — role excluded from fallback
   - If `IN_PROGRESS` and signal is `APPLIED` → update to `APPLIED`, set `date_applied` to this email's `received_at`
   - If `APPLIED` and signal is `INTERVIEW` → update to `INTERVIEW`
   - If `INTERVIEW` and signal is `OFFER` or `REJECTED` → update accordingly
   - If no matching record → create new application at signalled status
   - If transition is invalid per status model → no-op, log the event
6. Store raw email in `raw_emails` (always, regardless of confidence or action taken). Truncate before insert: `body_snippet = email_body[:500]` — this must be explicit in the worker code, not assumed.
7. Update `last_polled_at` on `email_accounts`

**On APScheduler process restart:** `last_polled_at` is persisted in the DB. The next scheduled poll catches up from where it left off — no emails are permanently missed.

**APScheduler `max_instances=1` (required):** Every poll job must be registered with `max_instances=1`. Without this, if a poll cycle takes longer than 15 minutes (possible with many emails and sequential Gemini calls), APScheduler will launch a second concurrent instance for the same account — processing the same emails twice and creating duplicate records or double status transitions.

**Single-instance deployment note:** For MVP, the DigitalOcean Droplet runs a single FastAPI process. `max_instances=1` is safe because there is only one APScheduler instance. If multi-instance deployment is needed in future, polling must move to a dedicated worker process or use a DB-backed advisory lock.

**Gmail API pagination:** The Gmail API returns results in pages (default 100 messages per page with a `nextPageToken`). The polling worker must follow `nextPageToken` until exhausted for each poll cycle. For MVP with a fresh account and 15-minute poll intervals, one page is usually sufficient — but the loop must be implemented correctly from the start.

**Gemini rate limit handling:** Gemini 2.5 Flash free tier has per-minute request limits. If a poll cycle processes many emails, sequential Gemini calls can hit the rate limit. The worker must implement exponential backoff with jitter on `429` responses from Gemini — retry up to 3 times with 2s, 4s, 8s delays before giving up on that email and logging the failure. A failed Gemini call stores the raw email with `gemini_signal = "PARSE_ERROR"` and moves on — it does not block the rest of the poll cycle.

### Chrome Extension Architecture

**Detection logic:**
- Content script injected on all pages
- Identifies job application forms via:
  - URL patterns for known ATS platforms (Workday, Greenhouse, Lever, Ashby, iCIMS)
  - Presence of expected form fields: "first name", "last name", "resume", "cover letter"
- On detection, extracts visible page text as JD (prioritizes structured sections: job title, responsibilities, qualifications)
- Shows a small non-intrusive overlay: "Track this application?" with a one-click confirm
- On confirm, POSTs to `/extension/capture` with `{ company_name, role, job_description, source_url }`

**Extension authentication — JWT handshake (non-trivial, must be explicitly implemented):**

The Supabase JWT is not automatically available to the extension. The web app must explicitly pass it after login. The required handshake:

1. The extension's `background.js` registers a `chrome.runtime.onMessageExternal` listener that accepts a `{ type: "SET_AUTH_TOKEN", token: "..." }` message and writes it to `chrome.storage.session`
2. After Supabase Auth completes on the Next.js frontend, the frontend detects whether the extension is installed by calling `chrome.runtime.sendMessage(EXTENSION_ID, { type: "PING" })` — if it resolves without error, the extension is present
3. If present, the frontend sends `{ type: "SET_AUTH_TOKEN", token: session.access_token }` to the extension
4. The extension stores the token and uses it on subsequent `fetch()` calls to FastAPI
5. On token refresh (Supabase Auth SDK handles silently), the frontend re-sends the updated token to the extension

`EXTENSION_ID` is the published Chrome Web Store ID in production and the unpacked dev ID in development — stored as `NEXT_PUBLIC_EXTENSION_ID` in the frontend env vars. **To get the dev ID:** load the unpacked extension in Chrome via `chrome://extensions` → "Load unpacked" → select the extension folder. The assigned ID appears under the extension name. Set it as `NEXT_PUBLIC_EXTENSION_ID` in `frontend/.env.local`. Note: this ID is stable as long as the extension folder path and `manifest.json` key don't change; reloading the extension does not change the ID.

**Critical SSR guard (required):** Next.js App Router runs some code server-side. `chrome.runtime` does not exist in Node.js — calling it during SSR throws `ReferenceError: chrome is not defined` and crashes the page. All `chrome.runtime.*` calls must be:
1. Wrapped in a `typeof chrome !== 'undefined'` guard
2. Placed inside a `useEffect` hook (client-side only, never in server components or top-level module scope)

**`externally_connectable` manifest entry (required — security gap if omitted):** `chrome.runtime.onMessageExternal` accepts messages from any origin by default. Without restricting which origins can send messages, any website the user visits could send a crafted `{ type: "SET_AUTH_TOKEN", token: "attacker_controlled_token" }` message to the extension — replacing the real JWT with a malicious one. The `manifest.json` must include:
```json
"externally_connectable": {
  "matches": [
    "https://your-vercel-app.vercel.app",
    "http://localhost:3000"
  ]
}
```
The production Vercel URL is added once known. Only origins in this list can send external messages to the extension. This is a one-line manifest entry but without it the token handshake has a meaningful attack surface.

On any `401` response from FastAPI, the extension clears `chrome.storage.session` and shows a prompt to re-open the web app (which will re-trigger the handshake on load).

**Extension detection from the frontend (for first-run checklist):**

The first-run checklist needs to know whether the extension is installed to mark step 2 complete. Standard approach: the extension injects a known DOM element (`<div id="job-tracker-v2-ext" style="display:none">`) into every page at content script load time. The frontend checks for the presence of this element on mount via `document.getElementById("job-tracker-v2-ext")`. If found → extension is installed → checklist step 2 is complete. If not found → show install instructions. This avoids relying solely on `chrome.runtime.sendMessage` which can fail silently in certain browser states.

---

## 9. Data Model

All schema changes are managed through **Alembic migrations** against the Supabase-hosted PostgreSQL instance. Supabase's own migration tooling is not used — Alembic keeps the workflow consistent with project 1.

### Tables

**Primary key convention:** All tables use UUID PKs. This is required because Supabase Auth issues UUIDs for user identities — `users.id` is the Supabase Auth UUID directly (the JWT `sub` claim). Using UUID for all other table PKs is consistent and avoids mixing types across FKs.

#### `users`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | **Is** the Supabase Auth user ID — set directly from the JWT `sub` claim on first login. No separate `supabase_id` column needed. |
| `email` | VARCHAR | Unique |
| `created_at` | TIMESTAMP | |

No `hashed_password`, no `supabase_id` — `id` IS the Supabase identity. Supabase Auth owns credential storage entirely.

#### `companies`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `name` | VARCHAR | Original name as provided |
| `normalized_name` | VARCHAR | Lowercase, legal suffixes stripped — used for dedup matching |
| `location` | VARCHAR | Nullable |
| `link` | VARCHAR | Nullable |
| `created_at` | TIMESTAMP | |

Composite unique constraint on `(user_id, normalized_name)`. Index on `(user_id, normalized_name)`.

#### `applications`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `company_id` | UUID FK → companies | |
| `role` | VARCHAR | |
| `status` | ENUM | `IN_PROGRESS`, `APPLIED`, `INTERVIEW`, `OFFER`, `REJECTED` |
| `source_url` | VARCHAR | Nullable — page URL captured by extension; used as primary dedup key |
| `date_applied` | DATE | Nullable — set to `received_at` of confirmation email when transitioning to `APPLIED` |
| `notes` | TEXT | |
| `created_at` | TIMESTAMP | |

#### `interviews`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `application_id` | UUID FK → applications | |
| `round_type` | ENUM | |
| `scheduled_at` | TIMESTAMP | Nullable |
| `outcome` | ENUM | Nullable |
| `notes` | TEXT | Nullable |
| `created_at` | TIMESTAMP | |

#### `job_descriptions`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `application_id` | UUID FK → applications | 1:1 |
| `raw_text` | TEXT | Full JD text captured by extension |
| `captured_at` | TIMESTAMP | |

`source_url` is **not** stored on `job_descriptions` — it is stored only on `applications.source_url`. Both values come from the same extension capture event and are always identical at creation, so storing it twice is redundant. `applications.source_url` is the canonical location — it serves as the dedup key and can be read from there when needed for display on the detail page.

#### `email_accounts`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | |
| `email` | VARCHAR | Connected Gmail address |
| `access_token` | TEXT | Encrypted at rest (Fernet) |
| `refresh_token` | TEXT | Encrypted at rest (Fernet) |
| `token_expiry` | TIMESTAMP | |
| `last_polled_at` | TIMESTAMP | Incremental polling window |
| `created_at` | TIMESTAMP | |

#### `raw_emails`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `email_account_id` | UUID FK → email_accounts | |
| `gmail_message_id` | VARCHAR | Unique — dedup key, prevents reprocessing |
| `subject` | TEXT | |
| `sender` | VARCHAR | |
| `received_at` | TIMESTAMP | |
| `body_snippet` | TEXT | First ~500 chars — stored intentionally for audit trail; included in `/users/me/export` and deleted by `DELETE /users/me` |
| `gemini_signal` | VARCHAR | `APPLIED` / `INTERVIEW` / `OFFER` / `REJECTED` / `IRRELEVANT` / `BELOW_THRESHOLD` / `PARSE_ERROR` |
| `gemini_confidence` | FLOAT | |
| `linked_application_id` | UUID FK → applications | Nullable — set if a status action was taken |
| `created_at` | TIMESTAMP | |

#### `gmail_oauth_states`
| Column | Type | Notes |
|--------|------|-------|
| `state_token` | VARCHAR PK | `secrets.token_urlsafe(32)` — single use, deleted after callback |
| `user_id` | UUID FK → users ON DELETE CASCADE | Cascades automatically when user is deleted — no manual cleanup needed in `DELETE /users/me` |
| `expires_at` | TIMESTAMP | 10 minutes from creation — callback rejects expired tokens |

This table exists solely to make CSRF state verification survive process restarts. Rows are deleted immediately after a successful callback. A periodic APScheduler job (registered in build step 9 alongside the other APScheduler jobs) purges expired rows hourly: `DELETE FROM gmail_oauth_states WHERE expires_at < now()`. Volume is negligible at MVP scale but the job is a one-liner and prevents unbounded table growth.

### Indexes
- `companies`: unique index on `(user_id, normalized_name)`
- `applications`: index on `(user_id, status)`; index on `(user_id, date_applied)`; index on `(company_id)`; index on `(user_id, source_url)` — for primary dedup lookup
- `email_accounts`: index on `(user_id)`
- `raw_emails`: unique index on `gmail_message_id`; index on `(email_account_id, received_at)`
- `job_descriptions`: unique index on `application_id`
- `gmail_oauth_states`: index on `(user_id)` — for user-scoped cleanup queries; index on `expires_at` — for the hourly expired-row purge job (prevents full table scan)

---

## 10. API Endpoints

### Auth
Supabase Auth handles all OAuth flows. FastAPI exposes no auth endpoints except `GET /auth/me`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check |
| GET | `/auth/me` | Required | Returns current user from verified JWT |
| GET | `/users/me/export` | Required | Returns a full JSON export of all data associated with the authenticated user: applications, companies, interviews, job descriptions, and email account metadata (tokens excluded). Required for GDPR/PIPEDA right to data portability. Response is a single JSON object structured by entity type, downloadable as a `.json` file via the frontend. |
| DELETE | `/users/me` | Required | Permanently deletes the authenticated user and all associated data. **Before executing the cascade delete**, the endpoint must cancel any active APScheduler poll jobs for the user's email accounts: iterate `user.email_accounts`, call `scheduler.remove_job(f"poll_{account.id}")` for each. This prevents a race condition where a mid-poll worker finishes a Gemini call and tries to write to `raw_emails` with an `email_account_id` that the cascade has already deleted — causing an FK violation and a noisy Sentry error. After job cancellation, revoke Gmail tokens via the Gmail API for each connected account, then proceed with cascade delete. Cascades to: `applications`, `companies`, `interviews`, `job_descriptions`, `email_accounts`, `raw_emails`, and `gmail_oauth_states` (via `ON DELETE CASCADE` on its `user_id` FK). All cascades enforced at DB level. Required for GDPR/PIPEDA compliance. |

### Gmail Integration
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/gmail/connect` | Required | Initiates Gmail OAuth2 scope request |
| GET | `/gmail/callback` | None | Handles Gmail OAuth redirect, stores encrypted tokens |
| DELETE | `/gmail/disconnect/{account_id}` | Required | Revokes and deletes stored Gmail tokens for a specific connected account |
| GET | `/gmail/accounts` | Required | Lists all connected Gmail accounts for current user |
| POST | `/gmail/accounts/{account_id}/poll` | Required | Manually triggers a poll cycle for a specific connected Gmail account. Explicit account targeting required because a user may have multiple accounts connected. |

### Extension
| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|------------|-------------|
| POST | `/extension/capture` | Required | 60/hr per user | Receives JD + metadata, creates `IN_PROGRESS` application |

### Applications, Companies, Interviews
All carried forward from project 1. Ownership scoping and transition logic extended for `IN_PROGRESS`.

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/companies` | List / create |
| GET/PATCH/DELETE | `/companies/{id}` | Single company CRUD |
| GET/POST | `/applications` | List with filters + pagination / create |
| GET/PATCH/DELETE | `/applications/{id}` | Single application CRUD |
| POST/GET | `/applications/{id}/interviews` | Interview rounds |

---

## 11. Gemini Integration

**Model:** `gemini-2.5-flash`  
**API key:** Server-side environment variable on the DigitalOcean Droplet. Never exposed to client.

### Classification Prompt

```
You are classifying a job application email.

Email subject: {subject}
Email sender: {sender}
Email body: {body_snippet}

Respond ONLY with a JSON object, no markdown, no explanation:
{
  "company": "<company name or null>",
  "role": "<job title or null>",
  "signal": "APPLIED|INTERVIEW|OFFER|REJECTED|IRRELEVANT",
  "confidence": <0.0 to 1.0>
}

signal definitions:
- APPLIED: confirms a job application was received by the employer
- INTERVIEW: invites the candidate to interview or schedule a screening call
- OFFER: extends a job offer to the candidate
- REJECTED: informs the candidate they will not be moving forward
- IRRELEVANT: this email is not related to a job application
```

### Confidence Threshold
Only act on results with `confidence >= 0.75`. Below threshold, the raw email is stored with `gemini_signal = "BELOW_THRESHOLD"` but no status change fires.

### Cost Control (Pre-filtering before every Gemini call)
1. **Known ATS sender list** (`@greenhouse.io`, `@lever.co`, `@myworkday.com`, `@ashbyhq.com`, `@icims.com`) → send to Gemini directly
2. **Subject keyword screen** for unknown senders: "application", "interview", "opportunity", "position", "thank you for applying", "unfortunately", "next steps", "offer" → send to Gemini
3. **Everything else** → skip, no Gemini call, no storage

---

## 12. Frontend

**Framework:** Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui  
**Hosting:** Vercel

### Routes

| Route | Description |
|-------|-------------|
| `/` | Landing / sign-in page. If user is already authenticated, redirect to `/dashboard`. |
| `/dashboard` | Kanban pipeline grouped by status. If user is not authenticated, redirect to `/`. |
| `/applications/[id]` | Detail: JD, status timeline, linked emails. Redirect to `/` if unauthenticated. |
| `/settings` | Gmail connect/disconnect, account info, data export, account deletion. Redirect to `/` if unauthenticated. |

### Dashboard Pipeline Columns
`In Progress` → `Applied` → `Interview` → `Offer` / `Rejected`

### Key UI Decisions
- Status is system-driven. No manual status dropdowns on the main dashboard. Override available on the detail page.
- JD displayed prominently on the detail page with "Captured at apply time" label — core differentiator, surfaced visibly.
- Email timeline on detail page shows which email triggered each status transition. *(Phase 2 — placeholder section only in Phase 1 frontend build; fully implemented in Phase 2 step 17.)*
- Settings page exposes three data rights actions in a dedicated section: **Export my data** (triggers `GET /users/me/export`, downloads a `.json` file), **Delete my account** (calls `DELETE /users/me` with a confirmation modal), and **Disconnect Gmail** per connected account (calls `DELETE /gmail/disconnect/{account_id}`). These must be clearly labeled and not buried — they are trust signals, not edge-case admin features.
- **"Applied without extension" state:** When an application is created from email parsing with no `IN_PROGRESS` predecessor (meaning the extension was not active when the user applied), the detail page should clearly surface: "Job description not captured — the extension was not active when this application was detected." This prevents users from being confused by applications that appear with no JD.
- **Status correction dropdown:** The detail page exposes a "Correct status" dropdown for manual overrides. It accepts any valid status value regardless of transition rules (the rules govern system behavior only, not user intent). The dropdown is clearly labeled to distinguish it from the automated pipeline status.
- **First-run / onboarding:** When a user logs in for the first time (empty dashboard, no Gmail connected, no extension installed), the dashboard shows a setup checklist rather than an empty Kanban board. The checklist has three steps: (1) Connect Gmail — links to settings, (2) Install the Chrome extension — links to install instructions, (3) Apply to a job — explains the flow. The checklist is dismissed once all three steps are completed and persists in local state so it doesn't reappear. This is the single most important activation feature — without it, users see an empty screen with no direction and leave before experiencing any value.

---

## 13. Security

This section is the authoritative security specification for the project. Every point here must be implemented from the first chunk, not retrofitted later. Follows OWASP API Security Top 10 guidelines.

### 13.1 Rate Limiting

**Library:** `slowapi` (FastAPI-compatible wrapper around `limits`)

Two key types: **IP-based** for unauthenticated/public endpoints (to block anonymous abuse), and **user-based** for authenticated endpoints (to prevent per-account flooding).

| Endpoint | Limit | Key | Rationale |
|----------|-------|-----|-----------|
| `GET /health` | 60 requests / minute | IP | Public, no auth — prevent hammering |
| `GET /gmail/callback` | 20 requests / minute | IP | Public OAuth redirect — prevent callback flooding |
| `GET /auth/me` | 60 requests / minute | User ID | Low risk but should have a ceiling |
| `GET /gmail/connect` | 10 requests / minute | User ID | Prevent OAuth initiation spam |
| `DELETE /gmail/disconnect/{account_id}` | 10 requests / minute | User ID | Prevent token deletion loops |
| `GET /gmail/accounts` | 30 requests / minute | User ID | Read endpoint, light limit |
| `POST /gmail/accounts/{account_id}/poll` | 10 requests / hour | User ID | Manual poll — expensive operation |
| `POST /extension/capture` | 60 requests / hour | User ID | Core write endpoint — prevent JD flooding |
| `GET /users/me/export` | 5 requests / hour | User ID | Full DB scan per user — most expensive read endpoint |
| `DELETE /users/me` | 3 requests / hour | User ID | Destructive — should be near-impossible to hit accidentally |
| `GET/POST /companies` | 60 requests / minute | User ID | Standard CRUD |
| `GET/PATCH/DELETE /companies/{id}` | 60 requests / minute | User ID | Standard CRUD |
| `GET/POST /applications` | 60 requests / minute | User ID | Standard CRUD |
| `GET/PATCH/DELETE /applications/{id}` | 60 requests / minute | User ID | Standard CRUD |
| `POST/GET /applications/{id}/interviews` | 60 requests / minute | User ID | Standard CRUD |

All exceeded limits return `HTTP 429` with a `Retry-After` header. Responses must never leak internal state in the 429 body — return a plain `{"detail": "Rate limit exceeded. Try again later."}`.

**Implementation note:** `slowapi` supports a callable key function. For authenticated endpoints, key on `user.id` extracted from the verified JWT. For public endpoints, key on `request.client.host`. Both are set up in the same `Limiter` instance — no separate infrastructure needed.

### 13.2 Input Validation and Sanitization

**Library:** Pydantic v2 (already in stack)

All request schemas must be hardened with three things that Pydantic does not apply by default:

**1. Reject unexpected fields — prevents mass assignment attacks**

Every request schema must include:
```python
model_config = ConfigDict(extra='forbid')
```
Without this, Pydantic silently ignores extra fields. `extra='forbid'` returns a 422 if the client sends any field not defined in the schema.

**2. Field-level length constraints — prevents oversized payload attacks**

All free-text fields must have explicit `max_length` constraints. Required minimums:

| Schema | Field | Max Length |
|--------|-------|------------|
| `CompanyCreate` / `CompanyUpdate` | `name` | 255 |
| `CompanyCreate` / `CompanyUpdate` | `location` | 255 |
| `CompanyCreate` / `CompanyUpdate` | `link` | 2048 |
| `ApplicationCreate` / `ApplicationUpdate` | `role` | 255 |
| `ApplicationCreate` / `ApplicationUpdate` | `notes` | 5000 |
| `InterviewCreate` / `InterviewUpdate` | `notes` | 5000 |
| `ExtensionCaptureRequest` | `company_name` | 255 |
| `ExtensionCaptureRequest` | `role` | 255 |
| `ExtensionCaptureRequest` | `source_url` | 2048 |
| `ExtensionCaptureRequest` | `job_description` | 50000 |

The `job_description` limit (50,000 chars) is the most critical. A Chrome extension can scrape an arbitrarily large page — without a cap, a malicious or buggy extension could push megabytes into the DB repeatedly.

**3. Type enforcement**

Pydantic v2 handles this by default — all fields must match their declared type or the request is rejected with 422. Do not use `Any` types on request schemas.

**4. URL validation**

`link` (company) and `source_url` (extension capture) must be validated as proper URLs using Pydantic's `HttpUrl` type, not raw strings. This prevents garbage or script-injection values in URL fields.

**Note on sanitization:** This API serves JSON to a TypeScript frontend that uses React. React escapes output by default, so stored text being rendered as HTML injection is not a risk in the normal flow. Do not strip or escape stored text at the API layer — that would corrupt JD content. The defense here is input length limits + type validation, not HTML sanitization.

**5. Request body size limit at the ASGI layer**

Pydantic's field length constraints only run after FastAPI has already read the entire request body into memory. A sufficiently large payload (e.g. 50MB) can exhaust process memory before Pydantic ever validates it. Apply Starlette's `ContentSizeLimit` middleware with a hard ceiling of **1MB** on all requests. This is a one-line middleware addition and is the correct place to catch oversized bodies before any application logic runs.

**6. Chrome extension scraping scope**

The content script runs on every page and extracts text for JD capture. It must operate on a strict allowlist of DOM elements — never read form field values. Application forms contain sensitive inputs: passwords, SSNs, salary expectations, EEO data. The scraper must target only structural, non-input page elements: `<h1>`, `<h2>`, `<h3>`, and non-interactive `<p>`, `<li>`, `<section>`, `<article>` elements. Any element matching `input`, `textarea`, `select`, or `[type=password]` is explicitly excluded. This rule must be documented in the extension's content script with a comment explaining why.

### 13.3 Secrets and API Key Handling

**All secrets are environment variables. Nothing is hardcoded. No secret ever appears in source code or version control.**

Required environment variables — **backend** (documented in `backend/.env.example`):

| Variable | Description | Rotation Impact |
|----------|-------------|-----------------|
| `SUPABASE_URL` | Supabase project URL | Low — changes only if project is recreated |
| `SUPABASE_JWT_SECRET` | Used to verify Supabase-issued JWTs | High — rotate in Supabase dashboard, redeploy FastAPI |
| `GOOGLE_CLIENT_ID` | Gmail OAuth2 client ID | Medium — update in Google Cloud Console + Droplet env |
| `GOOGLE_CLIENT_SECRET` | Gmail OAuth2 client secret | High — invalidates all active Gmail connections on rotation |
| `GEMINI_API_KEY` | Gemini 2.5 Flash API key | Low — rotate in Google AI Studio, redeploy |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting stored Gmail tokens | Critical — see rotation note below |
| `DATABASE_URL` | Supabase PostgreSQL **pooled** connection string (port 6543, PgBouncer) — used by FastAPI/SQLAlchemy at runtime | High — update Droplet env, restart service |
| `DATABASE_URL_DIRECT` | Supabase PostgreSQL **direct** connection string (port 5432) — used only by Alembic migrations. PgBouncer (pooled) does not support the DDL transactions Alembic requires. These two vars must point to the same DB but on different ports. | High — update when DB changes |
| `SENTRY_DSN` | Sentry error tracking DSN | Low — update env var, redeploy |
| `EXTENSION_ORIGIN` | Chrome extension origin for CORS (`chrome-extension://<id>`) — differs between dev (unpacked ID) and prod (Web Store ID) | Low — update when extension ID changes |
| `FRONTEND_URL` | Frontend base URL — used by `/gmail/callback` to redirect back after OAuth. Set to Vercel URL in production, `http://localhost:3000` in dev. Never hardcode; always read via `os.getenv("FRONTEND_URL", "http://localhost:3000")` | Low — update when Vercel URL changes |

Required environment variables — **frontend** (documented in `frontend/.env.example`):

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (public — safe to expose) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key (public by design — see note below) |
| `NEXT_PUBLIC_API_BASE_URL` | FastAPI backend base URL (DigitalOcean Droplet IP or domain in production) |
| `NEXT_PUBLIC_EXTENSION_ID` | Chrome extension ID — used by the frontend to send JWT to the extension via `chrome.runtime.sendMessage`. Differs between dev (unpacked) and prod (Web Store). |

**Fernet key rotation strategy:**

The Fernet key encrypts every `access_token` and `refresh_token` stored in `email_accounts`. If this key is rotated without a migration, all stored tokens become unreadable and every connected Gmail account silently breaks.

Rotation procedure:
1. Decrypt all existing tokens using the old key
2. Re-encrypt all tokens using the new key (one-off migration script)
3. Update `TOKEN_ENCRYPTION_KEY` in the Droplet environment
4. Deploy — this is the only safe order

For the MVP, document this procedure in `SECURITY.md` in the repo root. A rotation has not happened yet, but the procedure must exist before any real users connect Gmail accounts.

**Client-side exposure check:**
- Gemini API key: never sent to Next.js frontend or Chrome extension — all Gemini calls go through the FastAPI backend. ✓
- Gmail OAuth client secret: never sent to frontend — only used server-side in the OAuth callback. ✓
- Supabase anon key (used by Next.js Supabase Auth SDK): this key is intentionally public — Supabase's Row Level Security (RLS) is designed around it being exposed. This is expected and safe as long as RLS policies are configured. Note: since FastAPI enforces its own ownership scoping (`user_id` on all queries), and the frontend only reads via FastAPI (not direct Supabase queries), RLS is a **secondary** defense layer for the DB. It must still be configured manually for defense in depth. **Do NOT use the "Enable automatic RLS" toggle in Supabase project settings** — that fires on every new table at creation time before policies exist. Instead, after Alembic migrations run in chunk 3, manually enable RLS and create `user_id = auth.uid()` policies in the Supabase SQL Editor on: `users`, `companies`, `applications`, `interviews`, `job_descriptions`, `email_accounts`. Skip `raw_emails` and `gmail_oauth_states` — these have no direct `user_id` column and are never accessed via the Supabase REST API.

### 13.4 Additional OWASP Mitigations

**Broken Object Level Authorization (OWASP API1):**
All queries are scoped to the authenticated `user_id`. Resources belonging to other users return `404` (not `403`) to prevent existence leaking. This pattern is carried forward from project 1 and applies to every endpoint.

**Security Misconfiguration (OWASP API7):**
- CORS must be configured explicitly on FastAPI with an explicit list of allowed origins:
  - Development: `http://localhost:3000`
  - Production: the Vercel deployment URL (e.g. `https://job-tracker-v2.vercel.app`)
  - Chrome extension: the value of `EXTENSION_ORIGIN` environment variable (format: `chrome-extension://<extension-id>`). This is an env var because the extension ID differs between environments — the unpacked local dev ID (visible in `chrome://extensions`) and the published Chrome Web Store ID are different. Storing it as `EXTENSION_ORIGIN` means no code changes are needed between environments, only an env var update.
  - Never use `allow_origins=["*"]` in production.
- FastAPI's default error responses must not leak stack traces in production. Set `debug=False` in the production environment. Use a custom exception handler that returns a plain `{"detail": "Internal server error"}` for unhandled exceptions.

**HTTPS:**
Vercel terminates TLS at the platform level for the frontend. For the DigitalOcean Droplet, HTTPS must be configured explicitly — use Caddy or nginx with a Let's Encrypt certificate (both are free and auto-renew). The Droplet's public IP or domain must serve HTTPS in production. The Chrome extension must only make requests to `https://` endpoints — never `http://`. This must be enforced in the extension's `manifest.json` `host_permissions` — list only the production `https://` backend URL, not a wildcard.

**Extension JWT expiry:**
Supabase JWTs expire after 1 hour. The Chrome extension reads the JWT from `chrome.storage.session` and attaches it to requests. On any `401` response from FastAPI, the extension must clear the stored token and surface a prompt: "Your session has expired. Please log in again via the web app." The extension does not implement its own token refresh — token renewal is handled by the Supabase Auth SDK in the Next.js frontend, which writes the refreshed token back to `chrome.storage.session` on each page load.

**Log hygiene:**
The Gmail polling worker processes email content that contains PII — names, email addresses, personal job-related details. Log statements must never include raw email body content, body snippets, or any user-authored text. Permitted log fields: `gmail_message_id`, `email_account_id`, `gemini_signal`, `gemini_confidence`, `action_taken` (e.g. `"status_updated"` or `"no_op"`), timestamps, and error types. Violating this is both a privacy issue and a GDPR/PIPEDA exposure. This rule must be enforced with a code review checklist item.

**Dependency vulnerability scanning:**
`pip-audit` must be added to the GitHub Actions CI pipeline and run on every push. It scans all pinned dependencies against known CVE databases. A failing `pip-audit` scan fails the CI build. This catches supply chain vulnerabilities in `google-auth`, `google-api-python-client`, `apscheduler`, `cryptography`, and other new dependencies that were not present in project 1. Setup is one step in the CI YAML:
```yaml
- name: Audit dependencies
  run: pip-audit
```

**Frontend → backend communication pattern:**
The Next.js frontend calls FastAPI directly from the browser (not proxied through Next.js API routes). The Supabase JWT is a standard bearer token designed to be sent as an `Authorization` header — it is not a secret that needs to be hidden from browser network tabs. This pattern is simpler, avoids a proxy layer, and means CORS on FastAPI is required (configured above). All API calls from the frontend use the Supabase session's `access_token`, refreshed automatically by the Supabase Auth SDK.

**Account deletion and data privacy:**
`DELETE /users/me` performs a hard delete of the authenticated user and all associated data. This is required under GDPR (right to erasure) and PIPEDA. Deletion must cascade to: `applications`, `companies`, `interviews`, `job_descriptions`, `email_accounts` (including revoking stored Gmail tokens via the Gmail API before deleting), `raw_emails`, and `gmail_oauth_states` (via `ON DELETE CASCADE` on its `user_id` FK). All cascades are enforced at the DB level via foreign key `ON DELETE CASCADE` constraints — not in application code — so no records are orphaned even if the application layer has a bug. The settings page in the frontend must expose a "Delete my account" action with a confirmation step.

---

## 14. Technical Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gmail OAuth verification (Google's review process for `gmail.readonly`) | Blocks Gmail integration from non-test users | Start verification submission early; up to 100 test users allowed under unverified app during development |
| ATS HTML variability (Workday, Greenhouse, Lever, Ashby all differ) | Extension fails to detect forms or extract JD on some platforms | Build platform-specific content script selectors for top 4 ATS platforms first; generic fallback heuristic for the rest |
| Gemini classification errors on ambiguous emails | Wrong status transitions, erodes user trust | Confidence threshold (0.75+); all raw emails stored for audit; manual override on detail page |
| Gmail refresh token expiry / revocation | Polling silently fails | Check token validity before each poll; surface "reconnect Gmail" prompt in settings if refresh fails |
| APScheduler job loss across process restarts | Gmail polling silently stops after every deploy and never resumes | Register a FastAPI `startup` event handler that queries `email_accounts` for all connected accounts on boot and re-registers their poll jobs with APScheduler. `last_polled_at` ensures no emails are missed; the startup handler ensures jobs are always running. |
| Duplicate application records | Confusing dashboard | Deduplication using `(user_id, source_url)` as primary key when available, falling back to `(user_id, normalized_company_name)` — role excluded from fallback. Company name normalized before comparison (lowercase, strip legal suffixes). |
| Gmail access token exposed if DB compromised | User Gmail access compromised | Encrypt `access_token` + `refresh_token` with Fernet; encryption key stored in Droplet environment variable |
| Supabase free tier database pause | DB becomes unavailable after 7 days of inactivity; first request after pause takes 20–30 seconds and appears as an error — makes the product look broken to interviewers | The APScheduler keep-alive job hits `GET /health` every 3 days. This costs nothing and keeps the Supabase project active indefinitely. |
| Supabase free tier connection limit (20 direct connections) | SQLAlchemy pool + APScheduler background jobs exhaust connections; hard-to-debug production failures | Use Supabase's **pooled connection string** (port 6543, routes through PgBouncer) as `DATABASE_URL` instead of the direct connection string (port 5432). Set `pool_pre_ping=True` and `pool_size=5, max_overflow=5` on the SQLAlchemy engine. Document this in the setup guide — it is a one-line config difference but prevents a class of silent production failures. |
| Chrome extension distribution barrier | Any user (including interviewers testing the product) must enable Chrome developer mode and manually load an unpacked folder — a 5-step process that most non-technical users will not complete. This limits demo-ability significantly for portfolio purposes. | Acknowledge this limitation upfront in the README. Provide a step-by-step "Install for testing" guide. Chrome Web Store submission is the correct long-term fix but requires a $5 developer account and a review process. |
| Competitive landscape narrowing | G-Track now has AI Gmail parsing and claims 95%+ accuracy, making it closer to this product than the competitive table suggests. The table may become more outdated over time. | The genuine moat is the IN_PROGRESS state + JD capture at apply time — no existing tool does these. Focus on these as the primary differentiators in any demo or portfolio description, not just "AI email parsing" which is now table stakes. |

---

## 15. Observability

Without structured logging and error tracking, production failures in the polling worker, Gemini integration, or Gmail token refresh are invisible. This is not optional for a deployed product.

### Logging

Use Python's standard `logging` module with a JSON formatter (e.g. `python-json-logger`). On the DigitalOcean Droplet, stdout is captured by Docker and can be viewed with `docker logs`. Every log entry must include at minimum: `timestamp`, `level`, `service` (e.g. `"gmail_poller"`, `"gemini_classifier"`), `user_id` (where applicable), and a `message`. Raw email content is never logged — see log hygiene rule in Section 13.4.

Key events that must produce log entries:
- Poll cycle start/end per account, with count of emails fetched and processed
- Every Gemini classification result: `message_id`, `signal`, `confidence`, `action_taken`
- Every application status transition triggered by email
- Every failed token refresh with `email_account_id`
- Every rate limit hit (429 response)
- Every unhandled exception

### Error Tracking

Add **Sentry** (student tier via GitHub Student Developer Pack — 500k events/month; link your GitHub account at sentry.io after claiming the pack to activate, vs 5k/month on the regular free tier) for exception tracking. One `sentry_sdk.init()` call in the FastAPI app captures all unhandled exceptions with full stack traces and sends them to the Sentry dashboard. This means production errors are visible immediately without having to SSH into the Droplet and tail Docker logs. The Sentry DSN is stored as an environment variable (`SENTRY_DSN`). Add it to `.env.example`.

---

## 16. Project 1 vs Project 2

This is a **new repo**. Project 1 (`job-tracker-api`) is referenced as prior work. The design patterns carry forward but no code is directly copied.

| Area | Project 1 | Project 2 |
|------|-----------|-----------|
| Repo | `job-tracker-api` | New repo |
| Auth | Custom JWT, email/password, bcrypt | Supabase Auth (Google OAuth2 only) |
| Database | Local PostgreSQL via Docker Compose | Supabase hosted PostgreSQL (pooled connection) |
| Backend hosting | Not deployed | DigitalOcean Droplet (GitHub Student Pack — $200 credit) |
| Frontend | None | Next.js on Vercel |
| Extension | None | Chrome MV3, Vanilla JS |
| Email integration | None | Gmail API + APScheduler |
| LLM | None | Gemini 2.5 Flash |
| Status model | Applied / Interview / Offer / Rejected | + IN_PROGRESS |
| Observability | None | Structured JSON logging + Sentry |

**What carries forward in spirit:** SQLAlchemy 2.0, Alembic, Pydantic v2, Ruff, pytest integration tests, GitHub Actions CI, `PATCH` with `exclude_unset=True`, ownership scoping (all queries scoped to `user_id`), 404 for non-owned resources.

---

## 17. Build Order (Phased)

### Phase 1 — MVP
1. Repo setup: FastAPI skeleton, Supabase **pooled** `DATABASE_URL` (port 6543) for runtime and **direct** `DATABASE_URL_DIRECT` (port 5432) for Alembic in `alembic/env.py` — these must be separate env vars, Alembic cannot use PgBouncer. SQLAlchemy engine configured with `pool_pre_ping=True, pool_size=5, max_overflow=5` to stay within Supabase free tier connection limits. **APScheduler `BackgroundScheduler` instance created at module level** (e.g. `scheduler = BackgroundScheduler()` in a `scheduler.py` module) — the instance must exist from step 1 so any route handler can import and call `scheduler.remove_job()` without circular dependencies. `scheduler.start()` and job registration happen in step 9; the instance is importable from step 1 onward. DigitalOcean Droplet deployment via Docker (Dockerfile included), GitHub Actions CI with `pip-audit` step, `backend/.env.example` and `frontend/.env.example` committed with all placeholder variables including `DATABASE_URL_DIRECT` and `NEXT_PUBLIC_EXTENSION_ID`
2. Supabase Auth integration: JWT verification dependency — `users.id` is set directly from the JWT `sub` claim (UUID), no separate `supabase_id` column. `GET /auth/me`, user sync on first login (get-or-create by `id`). Stub `GET /users/me/export` and `DELETE /users/me` endpoints (return 501 — completed in steps 7/8)
3. DB migrations: `users`, `companies` (with `normalized_name` column — this is a new column, not auto-generated; Alembic migration must explicitly add it and populate it), `applications` (with `IN_PROGRESS` status, `date_applied` nullable, `source_url` nullable), `interviews`, `job_descriptions` (no `source_url` — canonical URL lives on `applications`) — all FK constraints with `ON DELETE CASCADE`
4. Core CRUD: companies (with find-or-create utility), applications (with updated status transitions including manual override bypass), interviews — Pydantic schemas with `extra='forbid'` and field-level length constraints on every schema. For URL fields (`link` on `CompanyCreate`, `source_url` on `ExtensionCaptureRequest`): apply `HttpUrl` first; if testing reveals it rejects valid ATS or company career page URLs, switch to `AnyUrl` — apply the same decision consistently to both fields. Integration tests: status transition enforcement, ownership scoping, manual override, IN_PROGRESS create
5. Full security baseline: slowapi rate limiting on all endpoints per Section 13.1 table (IP-keyed for public, user-keyed for authenticated), `ContentSizeLimit` middleware (1MB), CORS configured for dev + prod + `EXTENSION_ORIGIN` env var, `debug=False` in production, `SECURITY.md` with Fernet rotation procedure
6. Structured JSON logging (`python-json-logger`) + Sentry error tracking wired up
7. Gmail OAuth connection flow: `gmail_oauth_states` + `email_accounts` DB migrations (both needed here — `/gmail/callback` inserts into `email_accounts` immediately after exchanging tokens, so that table must exist before the callback handler runs). `/gmail/connect` (generates state token, inserts DB row with 10min TTL), `/gmail/callback` (queries DB for state token, verifies not expired, retrieves `user_id` from state row — no JWT at callback time — deletes row, exchanges code, stores tokens encrypted in `email_accounts`), `/gmail/disconnect/{account_id}`, `/gmail/accounts`. Wire `DELETE /users/me` to cancel APScheduler jobs before cascade — call `scheduler.remove_job(f"poll_{account.id}")` for each email account; wrap each call in a `try/except JobLookupError` and ignore it gracefully (the job may not be registered yet if the account was connected before step 9 ran, or if the scheduler restarted). Integration tests: CSRF state verification, expired state rejection, token encryption round-trip, APScheduler job cancellation on delete
8. `raw_emails` DB migration. Complete `GET /users/me/export` (now includes email account metadata and raw email records) and `DELETE /users/me` (now fully cascades all tables). Integration tests: export completeness, cascade delete
9. APScheduler setup with `startup` event handler that re-registers all poll jobs from `email_accounts` on boot, `max_instances=1` per poll job, keep-alive ping to Supabase every 3 days, and hourly expired-state cleanup job: `DELETE FROM gmail_oauth_states WHERE expires_at < now()`
10. Gmail polling worker: Gmail API client abstracted behind a thin wrapper interface (all `google-api-python-client` calls go through this wrapper so tests can swap in a mock — real Gmail API must never be called in CI). Pagination loop (`nextPageToken`), pre-filter, log hygiene enforced (metadata only). Integration tests: pre-filter logic, pagination handling with mocked Gmail client
11. Gemini 2.5 Flash integration: classification prompt, confidence gate, exponential backoff on 429, `PARSE_ERROR` signal on exhausted retries. Integration tests: mocked Gemini responses for each signal type
12. Email → application create/update logic: company normalization + `normalized_name` stored on company record, find-or-create company (shared utility used here and in step 13), deduplication using `source_url` as primary key and `(user_id, normalized_company_name)` as fallback, `date_applied` set to email `received_at` on APPLIED transition, transition enforcement. Integration tests: dedup with source_url match, dedup fallback with name variants, each valid transition, invalid transition no-op, date_applied value
13. `POST /extension/capture` wired end-to-end with company find-or-create, `source_url` stored on application. **Validate `source_url` against real ATS URLs** (Workday, Greenhouse, Lever) before finalizing the Pydantic schema — Pydantic's `HttpUrl` normalizes strictly and can reject non-standard but valid ATS URL structures. If too strict, use `AnyUrl` instead, which ensures a valid URL format without strict normalization. Integration tests: captures JD, creates IN_PROGRESS with source_url, rate limit enforcement, IN_PROGRESS excluded from PATCH status values
14. Next.js frontend: Supabase Auth login (redirect to `/dashboard` if already authenticated), first-run setup checklist with extension detection via DOM element injection, Kanban dashboard (redirect to `/` if unauthenticated), application detail with JD + placeholder for email timeline (Phase 2) + "Correct status" dropdown + "No JD captured" state, settings page (Gmail connect/disconnect per account, "Export my data", "Delete my account"). Frontend → extension JWT handshake: all `chrome.runtime.*` calls wrapped in `typeof chrome !== 'undefined'` guard and placed in `useEffect` only. `NEXT_PUBLIC_EXTENSION_ID` used for targeting.
15. Chrome Extension: `background.js` message listener for `SET_AUTH_TOKEN`, `externally_connectable.matches` in `manifest.json` set to Vercel URL + `http://localhost:3000` (restricts which origins can send external messages — required security entry), DOM element injection for extension detection, form detection with allowlisted DOM elements only, JD extraction, overlay UI, JWT expiry handling (clear + prompt on 401), `/extension/capture` integration

### Phase 2 (Partial — Interview + Final Outcome)
16. Wire backend transition logic for `APPLIED → INTERVIEW` and `INTERVIEW → OFFER/REJECTED`. The Gemini prompt already returns `INTERVIEW`, `OFFER`, and `REJECTED` signals — the backend currently receives them but takes no action. This step wires the action: look up the application, validate the transition, update status. Integration tests: each new transition fires correctly, invalid transitions (e.g. IN_PROGRESS → INTERVIEW directly) remain no-ops.
17. Email timeline component on application detail page — shows each `raw_emails` record linked to the application with its signal, confidence, and the status it triggered
