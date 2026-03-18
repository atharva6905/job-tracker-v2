# Deploy to DigitalOcean Droplet: build image, run with --restart unless-stopped
# so it auto-restarts on reboot.
# Example:
#   docker build -t job-tracker-backend .
#   docker run -d --restart unless-stopped -p 80:8000 --env-file .env job-tracker-backend

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
