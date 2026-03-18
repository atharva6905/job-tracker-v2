# job-tracker-v2

A job application tracker that requires zero manual entry. A Chrome extension detects when you're filling out an application, captures the job description, and creates an `IN_PROGRESS` record. Confirmation emails automatically advance the status to `APPLIED`. Subsequent emails (interview invites, rejections, offers) continue to advance status automatically.

## Project Structure

```
job-tracker-v2/
├── backend/          # FastAPI — API, email polling, Gemini classification
├── frontend/         # Next.js (App Router) — dashboard UI
├── extension/        # Chrome Extension MV3 — captures JDs at apply time
├── .github/
│   └── workflows/
│       └── ci.yml    # Lint, audit, migrate, test
├── PRD.md
├── BLUEPRINT.md
├── CLAUDE.md
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

## Required Secrets (GitHub Actions)

| Secret | Description |
|--------|-------------|
| `TOKEN_ENCRYPTION_KEY` | Fernet key (base64) — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
