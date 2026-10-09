# ===========================================
# StockPro / Bibelo - Production Dockerfile
# Padrao de deploy inspirado no VidalysFlow/Coolify
# ===========================================
FROM python:3.11-slim

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
    postgresql-client \
    curl \
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

RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data/backups

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/healthcheck/" || exit 1

ENTRYPOINT ["entrypoint.prod.sh"]

CMD ["sh", "-c", "gunicorn stock_control.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers=${GUNICORN_WORKERS:-2} --threads=${GUNICORN_THREADS:-4} --timeout=${GUNICORN_TIMEOUT:-120} --access-logfile=- --error-logfile=-"]
