FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080
# Cloud Run sets $PORT; honor it. Single worker, the event loop handles
# concurrency for these IO-bound calls. Scale out with Cloud Run instances.
CMD exec uvicorn ticket_router.main:app --host 0.0.0.0 --port ${PORT} --workers 1
