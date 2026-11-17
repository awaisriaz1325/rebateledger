# API, worker and scheduler image (Phase 11, ADR 0018). One image, three commands.
# UNVERIFIED: the python:3.14.10-slim tag matches the locally verified runtime; the first
# `docker build` confirms the tag exists.
FROM python:3.14.10-slim

# WeasyPrint (PDF reports) needs Pango; HarfBuzz subset is used for font embedding.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.13.6 \
 && useradd --create-home --uid 10001 app

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev && mkdir -p /data/storage && chown app:app /data/storage
USER app

# --proxy-headers: client IPs (rate limits, lockout, ops IP allowlist) come from
# X-Forwarded-For, trusted only from the stack's own network (see infra/prod/compose.yaml).
CMD ["sh", "-c", "uvicorn app.asgi:app --host 0.0.0.0 --port 8000 --no-server-header --proxy-headers --forwarded-allow-ips=\"$FORWARDED_ALLOW_IPS\""]
