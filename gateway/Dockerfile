# ── Build stage ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user for security
RUN addgroup --system gateway && adduser --system --ingroup gateway gateway

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY plugins/ ./plugins/

# Ensure non-root ownership
RUN chown -R gateway:gateway /app

USER gateway

EXPOSE 8080

ENV HOST=0.0.0.0 \
    PORT=8080 \
    PLUGINS_DIR=/app/plugins

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
