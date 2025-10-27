# Build timestamp: 2025-10-27T01:15:00Z - Force rebuild with spaCy model
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy language model - using direct URL for reliability
RUN pip install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose port (Cloud Run will set PORT dynamically)
EXPOSE 8080

# Run with PORT from environment, fallback to 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
