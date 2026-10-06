# syntax=docker/dockerfile:1.7
# TourDesk – one image for API (incl. frontend), worker and scheduler.

# ---------------------------------------------------------------- frontend build
FROM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- python runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOURDESK_HOME=/app \
    TOURDESK_DATA_DIR=/data \
    TOURDESK_FRONTEND_DIST=/app/frontend/dist \
    TOURDESK_HOST=0.0.0.0 \
    TOURDESK_PORT=8080

RUN apt-get update \
 && apt-get install -y --no-install-recommends tini tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 tourdesk \
 && useradd --system --uid 1000 --gid tourdesk --home-dir /app --shell /usr/sbin/nologin tourdesk

WORKDIR /app
COPY backend/ backend/
COPY crawler/ crawler/
RUN pip install ./backend ./crawler

COPY alembic.ini ./
COPY migrations/ migrations/
COPY database/ database/
COPY --from=frontend /src/frontend/dist/ frontend/dist/
COPY frontend/public/wallpapers/ frontend/public/wallpapers/
COPY docker/entrypoint.sh /usr/local/bin/tourdesk-entrypoint
RUN chmod 0755 /usr/local/bin/tourdesk-entrypoint \
 && mkdir -p /data \
 && chown -R tourdesk:tourdesk /data

USER tourdesk
VOLUME ["/data"]
EXPOSE 8080

# The health check is defined in docker-compose.yml (only the api role serves HTTP).
ENTRYPOINT ["/usr/bin/tini", "--", "tourdesk-entrypoint"]
CMD ["api"]
