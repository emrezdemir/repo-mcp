# Shared image for the gateway and the indexer. Both need the CBM binary:
# the gateway spawns it as an MCP server, the indexer invokes its CLI.
#
# CBM enforces an exact-build admission barrier — every CBM process sharing a
# cache root must be the same build. Pinning the version here, and running one
# image everywhere, is what keeps that invariant true.
FROM python:3.12-slim AS base

ARG CBM_VERSION=latest
ARG SERVICE=gateway

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) cbm_arch=amd64 ;; \
      arm64) cbm_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    if [ "$CBM_VERSION" = "latest" ]; then \
      url="https://github.com/DeusData/codebase-memory-mcp/releases/latest/download/codebase-memory-mcp-linux-${cbm_arch}"; \
    else \
      url="https://github.com/DeusData/codebase-memory-mcp/releases/download/${CBM_VERSION}/codebase-memory-mcp-linux-${cbm_arch}"; \
    fi; \
    curl -fsSL "$url" -o /usr/local/bin/codebase-memory-mcp; \
    chmod +x /usr/local/bin/codebase-memory-mcp; \
    codebase-memory-mcp --version

WORKDIR /srv
COPY ${SERVICE}/pyproject.toml ./pyproject.toml
COPY ${SERVICE}/app ./app
RUN pip install --no-cache-dir .

# The engine refuses to run as a shared account across tenants, and there is no
# reason for these services to be root.
RUN useradd --system --create-home --uid 10001 repomcp \
    && mkdir -p /var/lib/repo-mcp/cache /var/lib/repo-mcp/repos \
    && chown -R repomcp:repomcp /var/lib/repo-mcp
USER repomcp

ENV PYTHONUNBUFFERED=1 \
    CBM_BINARY=/usr/local/bin/codebase-memory-mcp \
    CBM_CACHE_ROOT=/var/lib/repo-mcp/cache \
    CBM_REPO_ROOT=/var/lib/repo-mcp/repos

EXPOSE 8080
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
