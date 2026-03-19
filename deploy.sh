#!/usr/bin/env bash
# deploy.sh — run this on the Droplet after SSHing in
# Usage: bash deploy.sh
#
# =============================================================================
# PRE-DEPLOY CHECKLIST — ensure /root/job-tracker-v2/.env contains all of:
# =============================================================================
#
#   DATABASE_URL          — Supabase pooled connection string (port 6543)
#   DATABASE_URL_DIRECT   — Supabase direct connection string (port 5432)
#   SUPABASE_URL          — https://your-project.supabase.co
#   SUPABASE_JWT_SECRET   — JWT verification secret from Supabase dashboard
#   GOOGLE_CLIENT_ID      — OAuth2 client ID from Google Cloud Console
#   GOOGLE_CLIENT_SECRET  — OAuth2 client secret from Google Cloud Console
#   GEMINI_API_KEY        — Gemini API key (server-side only)
#   TOKEN_ENCRYPTION_KEY  — Fernet key (base64) for encrypting Gmail tokens
#   FRONTEND_URL          — Vercel deployment URL (used by /gmail/callback)
#   EXTENSION_ORIGIN      — chrome-extension://<your-extension-id>
#   ALLOWED_ORIGINS       — comma-separated CORS origins
#   BACKEND_URL           — http://<droplet-ip>:8000 (until Caddy is added)
#   SENTRY_DSN            — optional; omit or leave blank to skip Sentry init
#
# =============================================================================

set -euo pipefail

REPO_DIR="/root/job-tracker-v2"
CONTAINER_NAME="job-tracker-v2"
IMAGE_NAME="job-tracker-v2"
ENV_FILE="${REPO_DIR}/.env"

echo "==> Pulling latest code..."
cd "$REPO_DIR"
git pull origin main

echo "==> Building Docker image..."
docker build -t "$IMAGE_NAME" ./backend

echo "==> Stopping and removing old container (if running)..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm   "$CONTAINER_NAME" 2>/dev/null || true

echo "==> Starting new container..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file "$ENV_FILE" \
  "$IMAGE_NAME"

echo "==> Running database migrations..."
docker exec "$CONTAINER_NAME" alembic upgrade head

echo "==> Deploy complete. Testing health endpoint..."
curl -f http://localhost:8000/health || echo "WARNING: health check failed"
