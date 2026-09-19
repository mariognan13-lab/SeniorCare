# ── Stage 1: dependency install ──────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /install

# System libs needed by cryptography / asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install/pkg --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from build stage
COPY --from=deps /install/pkg /usr/local

# Copy application source
COPY . .

# Railway injects PORT; uvicorn binds to it
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Use shell form so $PORT is expanded at container start-time
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
