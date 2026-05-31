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

# Install OS-level dependencies required by Playwright's Chromium browser.
# We install them manually instead of using --with-deps because that flag
# uses Ubuntu package names (ttf-unifont, ttf-ubuntu-font-family) that do
# not exist in Debian Bookworm slim, causing the build to fail with exit 100.
# Fonts are omitted — headless Chromium doesn't need them for court scraping.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright Chromium browser binary (system deps already installed above).
RUN playwright install chromium

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port (Cloud Run will set PORT dynamically)
EXPOSE 8080

# Run with PORT from environment, fallback to 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
