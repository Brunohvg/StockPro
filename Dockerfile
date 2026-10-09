# ===========================================
# StockPro / Bibelo - Production Dockerfile
# Padrao de deploy inspirado no VidalysFlow/Coolify
# ===========================================
# ---- Etapa 1: gera o CSS do Tailwind a partir dos templates ----
# (substitui o cdn.tailwindcss.com; ver tailwind.config.js)
FROM node:22-bookworm-slim AS assets
WORKDIR /build
COPY package.json package-lock.json tailwind.config.js ./
RUN npm ci --no-audit --no-fund
COPY templates ./templates
COPY apps ./apps
COPY static ./static
COPY scripts/fetch_vendor.mjs ./scripts/fetch_vendor.mjs
RUN node scripts/fetch_vendor.mjs && npm run build:css

# ---- Etapa 2: aplicação ----
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    UV_SYSTEM_PYTHON=1 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libjpeg62-turbo \
    zlib1g \
    libxml2 \
    libxslt1.1 \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Mantem cache de dependencias entre builds quando o codigo muda.
COPY pyproject.toml requirements.txt ./
RUN uv pip install -r requirements.txt --no-cache

# Entrypoint de producao: aguarda banco, migra e coleta static.
COPY docker/entrypoint.prod.sh /usr/local/bin/entrypoint.prod.sh
RUN chmod +x /usr/local/bin/entrypoint.prod.sh

COPY . /app
# CSS recém-gerado na etapa 1 (sobrescreve o static/css/app.css do repositório)
COPY --from=assets /build/static/css/app.css /app/static/css/app.css
COPY --from=assets /build/static/vendor/html5-qrcode-2.3.8.min.js /app/static/vendor/html5-qrcode-2.3.8.min.js

RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data/backups

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/healthcheck/" || exit 1

ENTRYPOINT ["entrypoint.prod.sh"]

CMD ["sh", "-c", "gunicorn stock_control.wsgi:application --no-sendfile --bind 0.0.0.0:${PORT:-8000} --workers=${GUNICORN_WORKERS:-2} --threads=${GUNICORN_THREADS:-4} --timeout=${GUNICORN_TIMEOUT:-120} --access-logfile=- --error-logfile=-"]
