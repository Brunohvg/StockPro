# ===========================================
# StockPro V11 - Dockerfile
# ===========================================
FROM python:3.11-slim

# ===========================================
# Environment
# ===========================================
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Sao_Paulo

# ===========================================
# Workdir
# ===========================================
WORKDIR /app

# ===========================================
# System dependencies
# ===========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# ===========================================
# Python dependencies
# ===========================================
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ===========================================
# Project files
# ===========================================
COPY . /app/

# ===========================================
# Runtime directories & Permissions
# ===========================================
RUN mkdir -p /app/static /app/staticfiles /app/media /app/imports /data && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app /data && \
    chmod -R 755 /app /data

# ===========================================
# Security: Run as non-root
# ===========================================
USER appuser

# ===========================================
# Healthcheck
# ===========================================
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# ===========================================
# Expose
# ===========================================
EXPOSE 8000

# ===========================================
# Default command (Production Optimized)
# ===========================================
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "stock_control.wsgi:application"]
