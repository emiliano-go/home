# Multi-stage: build the React SPA, then a slim Python runtime.
# Self-contained: totem is fetched from git (the local path override in
# pyproject.toml is stripped here; it only exists for local development).

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.14-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# pip install instead of COPY --from=ghcr.io so builds work where GHCR is blocked
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# Drop the dev-only editable path override for totem; uv then resolves it
# from the git URL in the dependency spec.
RUN sed -i '/^\[tool.uv.sources\]/,$d' pyproject.toml \
    && uv sync --no-dev --no-editable --extra browser
# Chromium + system libraries for browser-use (the optional browser extra).
RUN /app/.venv/bin/browser-use install
COPY --from=web /web/dist ./web/dist

ENV DATA_DIR=/data \
    PORT=8080
VOLUME /data
EXPOSE 8080

CMD ["/app/.venv/bin/uvicorn", "hestia.main:app", "--host", "0.0.0.0", "--port", "8080"]
