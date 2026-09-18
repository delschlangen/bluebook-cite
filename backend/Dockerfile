FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Shell form so ${PORT} expands. Railway assigns the port at runtime; the exec
# form hardcoded 8000, so if this Dockerfile were ever built without the
# matching railway.json startCommand the container would listen on the wrong
# port and every health check would fail.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
