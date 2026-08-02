# Shared image for the gateway and the indexer. Both need the engine binary: the
# gateway spawns it as an MCP server, the indexer invokes its CLI.
#
# The engine enforces an exact-build admission barrier — every engine process sharing a
# cache root must be the same build. Pinning CBM_VERSION and running one image
# everywhere is what keeps that invariant true.
#
#   docker build -f deploy/Dockerfile --build-arg SERVICE=gateway .

# ── engine ────────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS engine

ARG CBM_VERSION=latest
# Optional: the published SHA-256 of the *archive*. Leave it empty and the
# build verifies against the release's own checksums.txt instead, which is
# strictly better — it covers every architecture and needs no manual copying.
ARG CBM_SHA256=
# Where to fetch the engine from. Override to point at an internal mirror or
# artifact repository — useful in air-gapped builds and when you want the
# supply chain to run through your own infrastructure.
ARG CBM_RELEASE_BASE=https://github.com/DeusData/codebase-memory-mcp/releases
# Set to a full URL to bypass the version/architecture layout entirely. It must
# point at a .tar.gz laid out like the upstream one.
ARG CBM_DOWNLOAD_URL=
# "" for the glibc build, "-portable" for the static one. The runtime below is
# Debian, so the default is right unless your mirror only carries the other.
ARG CBM_VARIANT=

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# The release ships a .tar.gz containing the binary, its licence and its own
# installer — not a bare executable. Downloading the bare name gives a 404,
# which surfaces as a build that fails with curl exit 22 and no explanation.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) cbm_arch=amd64 ;; \
      arm64) cbm_arch=arm64 ;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    archive="codebase-memory-mcp-linux-${cbm_arch}${CBM_VARIANT}.tar.gz"; \
    if [ "$CBM_VERSION" = "latest" ]; then \
      base="${CBM_RELEASE_BASE}/latest/download"; \
    else \
      base="${CBM_RELEASE_BASE}/download/${CBM_VERSION}"; \
    fi; \
    if [ -n "$CBM_DOWNLOAD_URL" ]; then \
      url="$CBM_DOWNLOAD_URL"; \
    else \
      url="${base}/${archive}"; \
    fi; \
    curl -fsSL --retry 3 --retry-delay 2 "$url" -o /tmp/cbm.tar.gz; \
    if [ -n "$CBM_SHA256" ]; then \
      echo "${CBM_SHA256}  /tmp/cbm.tar.gz" | sha256sum -c -; \
    elif curl -fsSL --retry 3 --retry-delay 2 "${base}/checksums.txt" -o /tmp/checksums.txt; then \
      # The file lists every asset. Take the hash for ours and rebuild the
      # line, rather than rewriting the filename in place: the published file
      # separates the two fields with two spaces, and an off-by-one there
      # produces a checksum that silently never matches anything.
      published="$(awk -v a="${archive}" '$2 == a { print $1 }' /tmp/checksums.txt)"; \
      [ -n "$published" ] || { echo "checksums.txt has no entry for ${archive}" >&2; exit 1; }; \
      echo "${published}  /tmp/cbm.tar.gz" | sha256sum -c -; \
    else \
      echo "no checksums.txt and no CBM_SHA256: the engine download is unverified" >&2; \
    fi; \
    mkdir -p /tmp/cbm; \
    tar -xzf /tmp/cbm.tar.gz -C /tmp/cbm; \
    # The archive has the binary at its root; find it rather than assuming a
    # layout that upstream is free to change.
    binary="$(find /tmp/cbm -maxdepth 2 -type f -name codebase-memory-mcp | head -n1)"; \
    [ -n "$binary" ] || { echo "no codebase-memory-mcp in $archive" >&2; tar -tzf /tmp/cbm.tar.gz >&2; exit 1; }; \
    mv "$binary" /out-cbm; \
    chmod +x /out-cbm; \
    /out-cbm --version

# ── python dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

ARG SERVICE=gateway
WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

# Both services depend on repo-mcp-common, which is a path dependency and is
# not published anywhere. `[tool.uv.sources]` says where it lives, but pip does
# not read that — so the source has to be in the build context, and the two
# projects have to be installed in one command. Installed separately, the
# second run resolves repo-mcp-common against PyPI and fails.
COPY common/pyproject.toml common/README.md ./common/
COPY common/repo_mcp_common ./common/repo_mcp_common

COPY ${SERVICE}/pyproject.toml ${SERVICE}/README.md ./service/
COPY ${SERVICE}/app ./service/app

# Installed into a self-contained prefix so the runtime stage copies one
# directory instead of rebuilding anything.
RUN pip install --no-cache-dir --prefix=/install ./common ./service

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
# crashed engine process would linger as a zombie for the container's lifetime.
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
