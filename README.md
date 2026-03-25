# job-tracker-v2

A job application tracker that requires zero manual entry. A Chrome extension auto-captures job descriptions from Workday pages when you click Apply, creating an `IN_PROGRESS` record. When you complete the application, the extension marks it `APPLIED`. Subsequent employer emails (interview invites, rejections, offers) are classified by Gemini and automatically advance the status.

## Project Structure

```
job-tracker-v2/
├── backend/          # FastAPI — API, email polling, Gemini classification
├── frontend/         # Next.js (App Router) — dashboard UI
├── extension/        # Chrome Extension MV3 — Workday auto-capture
├── .github/
│   └── workflows/
│       └── ci.yml    # Lint, audit, migrate, test
└── SECURITY.md
```

## Backend Setup

```bash
cd backend
cp .env.example .env
# Fill in all values in .env

pip install -r requirements.txt

# Run migrations (uses DATABASE_URL_DIRECT — port 5432 direct connection)
alembic upgrade head

# Start the dev server
uvicorn app.main:app --reload
```

## Frontend Setup

```bash
cd frontend
cp .env.example .env.local
# Fill in all values

npm install
npm run dev
```

## Environment Variables

- **Backend:** see `backend/.env.example` for all required variables and descriptions
- **Frontend:** see `frontend/.env.example`

## CI

GitHub Actions runs on every push/PR to `main`:
1. `ruff check` — lint
2. `pip-audit` — dependency vulnerability scan
3. `alembic upgrade head` — migrate test DB
4. `pytest` — integration tests against real PostgreSQL

## Production Deployment

**Backend** runs on a DigitalOcean Droplet via Docker:

```bash
docker build -t job-tracker-backend .
docker run -d --restart unless-stopped -p 80:8000 --env-file .env job-tracker-backend
```

**Frontend** deploys to Vercel. Set `NEXT_PUBLIC_API_BASE_URL` to the Droplet's HTTPS URL.

## Chrome Extension — Install for Testing

### Step 1 — Enable Developer Mode

Open `chrome://extensions` in Chrome and enable **Developer mode** (toggle, top right).

### Step 2 — Load the Extension

Click **Load unpacked** and select the `extension/` folder from this repo.

### Step 3 — Copy the Extension ID

Copy the Extension ID shown under the extension name. It is a 32-character string like `abcdefghijklmnopabcdefghijklmnop`.

> **Note:** The Extension ID is stable as long as you don't move the `extension/` folder or add/change the `"key"` field in `manifest.json`. Reloading the extension (after editing files) does **not** change the ID.

### Step 4 — Configure the Frontend

Add to `frontend/.env.local`:

```
NEXT_PUBLIC_EXTENSION_ID=<your-extension-id>
```

Then restart the Next.js dev server (`npm run dev`).

### Step 5 — Configure the Backend

Add to `backend/.env`:

```
EXTENSION_ORIGIN=chrome-extension://<your-extension-id>
```

Then restart the FastAPI server (`uvicorn app.main:app --reload`).

### Step 6 — Verify the Flow

1. Log in at `http://localhost:3000`
2. Navigate to a Workday job page (e.g. `bmo.wd3.myworkdayjobs.com/en-US/External/details/...`)
3. A passive **"Job Tracker active"** overlay should appear after ~1.5 seconds and auto-dismiss after 3s
4. Click **Apply** on the job page — the extension auto-captures and shows **"Tracking this application..."**
5. Complete the application — on the completion page the extension shows a green **"Applied ✓"** overlay
6. Check your dashboard — the application should appear as `IN_PROGRESS` (then `APPLIED` after step 5)

> **Session note:** `chrome.storage.session` is cleared on browser restart. After restarting Chrome, open the web app once to re-send the JWT to the extension.

### Before Deploying to Production

Update these three places:

| File | Field | Change to |
|------|-------|-----------|
| `extension/manifest.json` | `host_permissions` | Your DigitalOcean Droplet HTTPS URL |
| `extension/manifest.json` | `externally_connectable.matches` | Your Vercel deployment URL |
| `extension/background.js` | `API_BASE` constant | Your DigitalOcean Droplet HTTPS URL |

---

## Required Secrets (GitHub Actions)

| Secret | Description |
|--------|-------------|
| `TOKEN_ENCRYPTION_KEY` | Fernet key (base64) — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
