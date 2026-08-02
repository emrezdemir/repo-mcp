# Shared image for the gateway and the indexer. Both need the CBM binary: the
# gateway spawns it as an MCP server, the indexer invokes its CLI.
#
# CBM enforces an exact-build admission barrier — every CBM process sharing a
# cache root must be the same build. Pinning CBM_VERSION and running one image
# everywhere is what keeps that invariant true.
#
#   docker build -f deploy/Dockerfile --build-arg SERVICE=gateway .

# ── engine ────────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS engine

ARG CBM_VERSION=latest
# Optional: set to the published SHA-256 of the binary to verify the download.
ARG CBM_SHA256=

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) cbm_arch=amd64 ;; \
      arm64) cbm_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    base="https://github.com/DeusData/codebase-memory-mcp/releases"; \
    if [ "$CBM_VERSION" = "latest" ]; then \
      url="$base/latest/download/codebase-memory-mcp-linux-${cbm_arch}"; \
    else \
      url="$base/download/${CBM_VERSION}/codebase-memory-mcp-linux-${cbm_arch}"; \
    fi; \
    curl -fsSL --retry 3 --retry-delay 2 "$url" -o /out-cbm; \
    if [ -n "$CBM_SHA256" ]; then \
      echo "${CBM_SHA256}  /out-cbm" | sha256sum -c -; \
    fi; \
    chmod +x /out-cbm; \
    /out-cbm --version

# ── python dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

ARG SERVICE=gateway
WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY ${SERVICE}/pyproject.toml ./pyproject.toml
COPY ${SERVICE}/app ./app

# Installed into a self-contained prefix so the runtime stage copies one
# directory instead of rebuilding anything.
RUN pip install --no-cache-dir --prefix=/install .

# ── runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG SERVICE=gateway
ARG VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="repo-mcp ${SERVICE}" \
      org.opencontainers.image.description="Centralized code intelligence over MCP" \
      org.opencontainers.image.source="https://github.com/emrezdemir/repo-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

# git is a runtime dependency: the indexer clones and fetches working copies.
# tini reaps the engine processes the gateway spawns — without an init, a
# crashed CBM process would linger as a zombie for the container's lifetime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git tini curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin repomcp

COPY --from=builder /install /usr/local
COPY --from=engine /out-cbm /usr/local/bin/codebase-memory-mcp

RUN mkdir -p /var/lib/repo-mcp/cache /var/lib/repo-mcp/repos /etc/repo-mcp \
    && chown -R repomcp:repomcp /var/lib/repo-mcp

USER repomcp
WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CBM_BINARY=/usr/local/bin/codebase-memory-mcp \
    CBM_CACHE_ROOT=/var/lib/repo-mcp/cache \
    CBM_REPO_ROOT=/var/lib/repo-mcp/repos \
    PORT=8080 \
    WEB_CONCURRENCY=1

EXPOSE 8080

# Liveness only. Readiness is /readyz on the gateway, which additionally
# reports whether tenants loaded and the model backend is configured.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn app.asgi:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers"]
