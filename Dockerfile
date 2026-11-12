# ── build stage ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Build deps only live in this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install .

# ── runtime stage ────────────────────────────────────────────
FROM python:3.11-slim

# Run as a non-root user. Nothing in this app needs root.
RUN groupadd --gid 1001 jawab \
    && useradd --uid 1001 --gid jawab --create-home --shell /bin/bash jawab

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=jawab:jawab app ./app
COPY --chown=jawab:jawab pyproject.toml README.md ./

# SQLite lives here; docker-compose mounts a volume over it.
RUN mkdir -p /app/data && chown -R jawab:jawab /app/data

USER jawab

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    DATABASE_URL=sqlite:////app/data/jawab.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
