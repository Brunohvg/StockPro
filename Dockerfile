# ===========================================
# StockPro V16 - Dockerfile
# ===========================================

# Build stage — python:3.11-slim com uv instalado
FROM python:3.11-slim AS build

# Instala uv via pip (não usa a imagem distroless)
RUN pip install uv --no-cache-dir

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Instala dependências primeiro (cache layer)
COPY pyproject.toml uv.lock* /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copia o projeto e instala
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Instala gevent no venv (ARM/aarch64 Celery pool)
RUN uv pip install gevent --python /app/.venv

# ===========================================
# Final stage
# ===========================================
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    PATH="/app/.venv/bin:$PATH"

# Dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    zlib1g \
    libxml2 \
    libxslt1.1 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copia o venv do build stage
COPY --from=build /app/.venv /app/.venv

# Copia o projeto
COPY . /app

# Diretórios e usuário não-root
RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data/backups && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app /data && \
    chmod -R 755 /app /data

USER appuser

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
