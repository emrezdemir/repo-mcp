# repo-mcp — see scripts/ for what each target actually runs.

.DEFAULT_GOAL := help
SHELL := /bin/bash

SERVICES := gateway indexer
IMAGE_REPO ?= ghcr.io/emrezdemir/repo-mcp
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
VCS_REF ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
CBM_VERSION ?= latest
# The container engine for 'make build' and 'make push': docker or podman.
CONTAINER_ENGINE ?= docker

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── development ───────────────────────────────────────────────────────

.PHONY: setup
setup: ## Create virtualenvs, install dependencies, choose components, generate configuration (ARGS=--config-only for a Docker-only server)
	@scripts/setup.sh $(ARGS)

.PHONY: dev
dev: ## Run both services locally with auto-reload
	@scripts/dev.sh

.PHONY: test
test: ## Run linting and tests
	@scripts/test.sh

.PHONY: lint
lint: ## Lint only
	@scripts/test.sh --lint

.PHONY: fmt
fmt: ## Apply lint autofixes and formatting
	@scripts/test.sh --fix --no-lint

.PHONY: cov
cov: ## Run tests with a coverage report
	@scripts/test.sh --cov

.PHONY: debug
debug: ## Diagnose the current setup
	@scripts/debug.sh

.PHONY: upgrade
upgrade: ## Check for a newer release and upgrade this install (ARGS=--check to only check)
	@scripts/upgrade.sh $(ARGS)

.PHONY: generate-key
generate-key: ## Print a new SECRETS_KEY
	@common/.venv/bin/repo-mcp-admin generate-key 2>/dev/null || \
	 python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

.PHONY: check-branch
check-branch: ## Check the current branch name against the convention
	@scripts/check-branch.sh

.PHONY: check-docs
check-docs: ## Enforce the documentation rules (docs/code-standards.md §5)
	@scripts/check-docs.sh

.PHONY: check-secrets
check-secrets: ## Scan every tracked file for secrets and forbidden paths
	@scripts/check-secrets.sh --all

.PHONY: wizard
wizard: ## Choose which optional components the stack runs, and write deploy/.env
	@scripts/wizard.sh --force

.PHONY: version
version: ## Print the project version (scripts/version.sh --set X.Y.Z to change it)
	@scripts/version.sh

.PHONY: check-version
check-version: ## Check that every file agrees with VERSION
	@scripts/version.sh --check

.PHONY: screenshots
site: ## assemble the project site and the rendered docs into _site/ (--serve to preview)
	scripts/build-site.sh $(ARGS)

screenshots: ## Regenerate docs/images from a live gateway
	@scripts/screenshots.sh

.PHONY: check-chart
check-chart: ## Check the Helm templates against values.yaml (no cluster, no helm)
	@scripts/check-chart.sh

.PHONY: verify
verify: check-branch test check-docs check-chart check-version check-secrets ## Everything the definition of done requires
	@echo "verify: all checks passed"

.PHONY: hooks
hooks: ## Install the pre-commit hook that blocks secrets
	@scripts/check-secrets.sh --install

# ── docker ────────────────────────────────────────────────────────────

.PHONY: build
build: ## Build both container images
	@for service in $(SERVICES); do \
	  echo "==> building $$service"; \
	  $(CONTAINER_ENGINE) build -f deploy/Dockerfile \
	    --build-arg SERVICE=$$service \
	    --build-arg CBM_VERSION=$(CBM_VERSION) \
	    --build-arg VERSION=$(VERSION) \
	    --build-arg VCS_REF=$(VCS_REF) \
	    -t $(IMAGE_REPO)-$$service:$(VERSION) \
	    -t $(IMAGE_REPO)-$$service:latest . || exit 1; \
	done

.PHONY: push
push: ## Push both images
	@for service in $(SERVICES); do \
	  $(CONTAINER_ENGINE) push $(IMAGE_REPO)-$$service:$(VERSION) || exit 1; \
	  $(CONTAINER_ENGINE) push $(IMAGE_REPO)-$$service:latest || exit 1; \
	done

.PHONY: up
up: ## Start the Docker stack (ARGS=--pull to fetch images instead of building)
	@scripts/stack.sh up $(ARGS)

.PHONY: down
down: ## Stop the Docker stack
	@scripts/stack.sh down $(ARGS)

.PHONY: logs
logs: ## Follow stack logs
	@scripts/stack.sh logs $(ARGS)

.PHONY: smoke
smoke: ## Smoke test a running stack
	@scripts/smoke.sh

.PHONY: e2e
e2e: ## Full end-to-end run: build, index a real repository, query, tear down
	@scripts/e2e.sh

# ── helm ──────────────────────────────────────────────────────────────

.PHONY: helm-lint
helm-lint: ## Lint the Helm chart
	@helm lint deploy/helm/repo-mcp --set database.url=x --set secretsKey=y

.PHONY: helm-template
helm-template: ## Render the chart to stdout
	@helm template repo-mcp deploy/helm/repo-mcp \
	  --set database.url=postgresql+asyncpg://u:p@db:5432/repomcp \
	  --set secretsKey=render-only-not-a-real-key

.PHONY: helm-package
helm-package: ## Package the chart into dist/
	@mkdir -p dist && helm package deploy/helm/repo-mcp -d dist

# ── housekeeping ──────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove build artefacts, caches and local dev data
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \
	  -o -name '*.egg-info' \) -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf dist .dev
	@echo "cleaned (virtualenvs kept; remove */.venv by hand)"
