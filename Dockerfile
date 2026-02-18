# ===========================================
# StockPro V16 - Dockerfile
# Padrão: UV_SYSTEM_PYTHON=1 (igual ao Flowlog que funciona em aarch64)
# ===========================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    UV_SYSTEM_PYTHON=1

# Dependências de sistema
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

# Instala uv (igual ao Flowlog)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Instala dependências no Python do sistema (sem .venv — igual ao Flowlog)
COPY requirements.txt ./
RUN uv pip install -r requirements.txt --no-cache

# Copia o projeto
COPY . /app

# Diretórios necessários
RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data/backups

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthcheck/')" || exit 1

EXPOSE 8000

CMD ["gunicorn", "stock_control.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
