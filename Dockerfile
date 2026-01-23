# ===========================================
# StockPro V16 - High Performance Dockerfile
# ===========================================

# Build stage
FROM ghcr.io/astral-sh/uv:latest AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Final stage
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    PATH="/app/.venv/bin:$PATH"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libjpeg62-turbo zlib1g libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy artifacts from build stage
COPY --from=build /app/.venv /app/.venv
COPY . /app

# Finalize setup
RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app /data && \
    chmod -R 755 /app /data

USER appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "stock_control.wsgi:application"]
