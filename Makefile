# repo-mcp — see scripts/ for what each target actually runs.

.DEFAULT_GOAL := help
SHELL := /bin/bash

SERVICES := gateway indexer
IMAGE_REPO ?= ghcr.io/emrezdemir/repo-mcp
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
VCS_REF ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
CBM_VERSION ?= latest

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── development ───────────────────────────────────────────────────────

.PHONY: setup
setup: ## Create virtualenvs, install dependencies, generate configuration
	@scripts/setup.sh

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

.PHONY: check-secrets
check-secrets: ## Scan every tracked file for secrets and forbidden paths
	@scripts/check-secrets.sh --all

.PHONY: hooks
hooks: ## Install the pre-commit hook that blocks secrets
	@scripts/check-secrets.sh --install

# ── docker ────────────────────────────────────────────────────────────

.PHONY: build
build: ## Build both container images
	@for service in $(SERVICES); do \
	  echo "==> building $$service"; \
	  docker build -f deploy/Dockerfile \
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
	  docker push $(IMAGE_REPO)-$$service:$(VERSION) || exit 1; \
	  docker push $(IMAGE_REPO)-$$service:latest || exit 1; \
	done

.PHONY: up
up: ## Start the Docker stack
	@scripts/stack.sh up

.PHONY: down
down: ## Stop the Docker stack
	@scripts/stack.sh down

.PHONY: logs
logs: ## Follow stack logs
	@scripts/stack.sh logs

.PHONY: smoke
smoke: ## Smoke test a running stack
	@scripts/smoke.sh

.PHONY: e2e
e2e: ## Full end-to-end run: build, index a real repository, query, tear down
	@scripts/e2e.sh

# ── helm ──────────────────────────────────────────────────────────────

.PHONY: helm-lint
helm-lint: ## Lint the Helm chart
	@helm lint deploy/helm/repo-mcp

.PHONY: helm-template
helm-template: ## Render the chart to stdout
	@helm template repo-mcp deploy/helm/repo-mcp

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
