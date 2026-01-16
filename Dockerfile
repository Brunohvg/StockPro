# ===========================================
# StockPro V11 - Dockerfile
# ===========================================
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Sao_Paulo

# Set work directory
WORKDIR /app

# Install system dependencies (libpq for PostgreSQL, libxml2 for lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Create directories for static, media, imports and celery data
RUN mkdir -p /app/staticfiles /app/media /app/imports /data

# Set permissions
RUN chmod -R 755 /app

# Expose port
EXPOSE 8000

# Default command (Gunicorn)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "stock_control.wsgi:application"]
