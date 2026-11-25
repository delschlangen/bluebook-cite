FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/app ./app

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# "exec" makes uvicorn replace the shell as process 1, so the SIGTERM a deploy sends reaches it
# and requests in flight are finished. Without it the signal went to the shell, which ignores
# it: measured in a container, the server was still running 40 s later and was then killed
# outright (exit 137), cutting off whatever it was doing.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
