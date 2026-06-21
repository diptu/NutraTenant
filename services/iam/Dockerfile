# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the NutraTenant IAM service.
#
#   builder  — full Debian toolchain (gcc/build-essential) to resolve and
#              install dependencies via uv. Never shipped in the final image.
#   runtime  — clean python:3.11.9-slim base; only the resolved virtualenv
#              and application code are copied in, owned by and run as a
#              fixed-uid non-root user.

########################################
# Builder
########################################
FROM python:3.11.9-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.9.5

WORKDIR /app

# Dependency layer first, isolated from application code — this layer is
# only invalidated when pyproject.toml/uv.lock change, not on every code edit.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Application code + migrations (alembic is included so an operator can run
# `docker run <image> alembic upgrade head` as a one-off; the default CMD
# below does not run migrations automatically — multi-replica deployments
# must not race each other applying schema changes on every container start).
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

########################################
# Runtime
########################################
FROM python:3.11.9-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Fixed numeric uid/gid (not a name that could collide with a host account,
# not root) — standard non-root-container hardening.
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser

COPY --from=builder --chown=appuser:appgroup /app /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
