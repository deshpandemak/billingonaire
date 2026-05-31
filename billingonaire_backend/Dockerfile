# Build timestamp: 2025-10-27T17:55:00Z - Force rebuild with spaCy model and --no-cache flag
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (gcc/g++ for C-extension wheels)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy language model - using direct URL for reliability
RUN pip install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# Install Playwright browser binary + all OS-level dependencies it needs.
# This step runs AFTER pip install so Playwright is already on PATH.
# --with-deps installs the required apt packages (libnss3, libgbm1, etc.)
# in a single RUN layer so the browser works in the container.
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port (Cloud Run will set PORT dynamically)
EXPOSE 8080

# Run with PORT from environment, fallback to 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
