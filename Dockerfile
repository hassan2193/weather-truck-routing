# Single-image deployment: React build is served by Django (WhiteNoise) next to the API.

# ---- 1) build the frontend ----------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2) Django runtime ----------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /frontend/dist ./frontend_dist
# collectstatic is a no-op for our apps but keeps WhiteNoise's manifest consistent.
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput
RUN useradd --system --uid 10001 app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --threads 4 --timeout 120 --access-logfile -"]
