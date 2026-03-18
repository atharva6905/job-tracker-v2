# SECURITY.md — job-tracker-v2

This document covers the Fernet key rotation procedure and the full environment variable reference for backend and frontend.

---

## Fernet Key Rotation Procedure

`TOKEN_ENCRYPTION_KEY` is a Fernet key that encrypts every `access_token` and `refresh_token` stored in the `email_accounts` table. If this key is rotated without a data migration, all stored tokens become unreadable and every connected Gmail account silently breaks.

**The only safe rotation order is:**

1. **Decrypt all existing tokens** using the old key. Run a one-off migration script that reads every row in `email_accounts`, decrypts `access_token` and `refresh_token` with the current `TOKEN_ENCRYPTION_KEY`, and holds them in memory.

2. **Re-encrypt all tokens** using the new key. Write the new ciphertext back to each row in the same migration script.

3. **Update `TOKEN_ENCRYPTION_KEY`** in the DigitalOcean Droplet environment (or wherever the backend runs) to the new key value.

4. **Deploy** — restart the FastAPI process so it picks up the new key. This is the only safe order; deploying before step 2 is complete will break all Gmail connections.

> A rotation has not happened yet. This procedure must be in place before any real users connect Gmail accounts.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Supabase **pooled** connection string (port **6543**, PgBouncer). Used by FastAPI/SQLAlchemy at runtime only. Never use this in Alembic. |
| `DATABASE_URL_DIRECT` | Yes | Supabase **direct** connection string (port **5432**). Used by Alembic migrations only. Never use this at runtime — direct connections bypass PgBouncer and will exhaust the connection pool. |
| `SUPABASE_URL` | Yes | Supabase project URL (e.g. `https://<project>.supabase.co`). |
| `SUPABASE_JWT_SECRET` | Yes | JWT signing secret from the Supabase dashboard. Used to verify Supabase-issued JWTs on every authenticated request. Rotate in the Supabase dashboard then redeploy FastAPI. |
| `GOOGLE_CLIENT_ID` | Yes | Gmail OAuth2 client ID from Google Cloud Console. |
| `GOOGLE_CLIENT_SECRET` | Yes | Gmail OAuth2 client secret. Never expose client-side. Invalidates all active Gmail connections if rotated. |
| `GEMINI_API_KEY` | Yes | Gemini 2.5 Flash API key. Server-side only — never reference in frontend or extension code. Rotate in Google AI Studio then redeploy. |
| `TOKEN_ENCRYPTION_KEY` | Yes | Fernet key (base64-encoded) used to encrypt `access_token` and `refresh_token` at rest in `email_accounts`. See rotation procedure above — do NOT simply swap this value without migrating the existing ciphertext first. |
| `FRONTEND_URL` | Yes | The deployed Vercel URL in production (e.g. `https://job-tracker-v2.vercel.app`); `http://localhost:3000` in development. Used by `GET /gmail/callback` to redirect the user back to the frontend after OAuth completes. Never hardcode — always read from this env var. |
| `EXTENSION_ORIGIN` | Yes | Full Chrome extension origin in the form `chrome-extension://<extension-id>`. Differs between local dev (unpacked extension ID visible in `chrome://extensions`) and the published Chrome Web Store ID. Added to the CORS allowlist so the extension can call the API. |
| `ALLOWED_ORIGINS` | Yes | Comma-separated list of CORS-allowed origins, e.g. `http://localhost:3000,https://job-tracker-v2.vercel.app`. `EXTENSION_ORIGIN` is appended automatically; do not duplicate it here. |
| `SENTRY_DSN` | No | Sentry DSN for error tracking. If unset, Sentry initialisation is skipped silently. |
| `DEBUG` | No | Set to `true` to enable FastAPI debug mode. Defaults to `false`. Never set to `true` in production — debug mode can expose stack traces. |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Yes | Supabase project URL. Safe to expose — same value as backend `SUPABASE_URL`. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | Supabase anon key. Intentionally public; Supabase's RLS is designed around this being exposed. |
| `NEXT_PUBLIC_API_BASE_URL` | Yes | FastAPI backend base URL (DigitalOcean Droplet HTTPS URL in production; `http://localhost:8000` in development). All browser → API calls use this. |
| `NEXT_PUBLIC_EXTENSION_ID` | No | Chrome extension ID used by the dashboard to send `SET_AUTH_TOKEN` messages via `chrome.runtime.sendMessage`. |

---

## Database Notes

### gmail_oauth_states — ON DELETE CASCADE

The `gmail_oauth_states` table has a foreign key `user_id → users.id` with `ON DELETE CASCADE`. When a user's account is deleted, all their pending OAuth state tokens are automatically removed. State tokens are also single-use — they are deleted immediately after `GET /gmail/callback` succeeds; leaving a used state token in the table is a security regression.

### RLS

Row Level Security must be enabled manually per table in the Supabase SQL Editor **after** Alembic migrations run. Do **not** use the "Enable automatic RLS" toggle in Supabase project settings — it fires at table creation time before policies exist. Tables requiring RLS: `users`, `companies`, `applications`, `interviews`, `job_descriptions`, `email_accounts`. Skip `raw_emails` and `gmail_oauth_states` — they have no direct `user_id` column and are never accessed via the Supabase REST API.
