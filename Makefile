.PHONY: help dev server worker test test-py test-ui lint fmt \
        migrate makemigrations shell reset-db \
        kind-up kind-down kubeconfig-kind \
        docker-build docker-pull docker-ps \
        docker-api-up docker-api-down docker-api-logs docker-api-shell \
        docker-migrate \
        docker-worker-up docker-worker-down docker-worker-logs docker-worker-shell \
        docker-dev-up docker-dev-down venv tag-release

PYTHON ?= python
MANAGE := $(PYTHON) api/manage.py

# ---- Docker / "simulate prod" knobs ----
IMAGE ?= k2p-web:local                 # set to ghcr.io/<you>/<repo>:<tag> when you want
ENV_FILE ?= .env

API_NAME ?= k2pweb-api
WORKER_NAME ?= k2pweb-worker
PORT ?= 8000

# For kind connectivity from inside a container:
KIND_CLUSTER ?= k2p
KIND_NETWORK ?= kind
KUBECONFIG_KIND ?= var/kubeconfig-kind.yaml

# Mount repo into containers at /repo (matches your kind dev mount pattern)
REPO_MOUNT ?= /repo

help:
	@echo "Local (from source):"
	@echo "  make server            Run Django dev server"
	@echo "  make worker            Run k2p worker loop"
	@echo "  make test-py           Run pytest (python only)"
	@echo "  make test-ui           Run UI unit tests (requires npm)"
	@echo "  make test              Run all tests (UI tests only if npm+package.json exist)"
	@echo "  make lint              Run ruff"
	@echo "  make fmt               Run ruff format"
	@echo "  make migrate           Apply migrations"
	@echo "  make makemigrations    Create migrations"
	@echo "  make shell             Django shell"
	@echo "  make reset-db          Flush DB and re-migrate"
	@echo ""
	@echo "Kind:"
	@echo "  make kind-up           Create local kind cluster (recommended: uses scripts/kind-create.sh)"
	@echo "  make kind-down         Delete local kind cluster"
	@echo ""
	@echo "Docker (run from image; closer to production):"
	@echo "  make docker-build      Build local image ($(IMAGE))"
	@echo "  make docker-pull       Pull image ($(IMAGE))"
	@echo "  make docker-ps         Show API/worker containers"
	@echo "  make docker-migrate    Run migrations inside image"
	@echo "  make docker-api-up     Start API container from image"
	@echo "  make docker-worker-up  Start worker container from image (talks to kind)"
	@echo "  make docker-dev-up     kind-up + docker-build + docker-migrate + docker-api-up + docker-worker-up"
	@echo "  make docker-dev-down   Stop worker + API containers"
	@echo ""
	@echo "venv:"
	@echo "  make venv              Print activate command"
	@echo ""
	@echo "Release:"
	@echo "  make tag-release VERSION=v0.1.1"

# -----------------------
# Local (from source)
# -----------------------

dev:
	@echo "Run in two terminals:"
	@echo "  make server"
	@echo "  make worker"

server:
	$(MANAGE) runserver

worker:
	$(MANAGE) k2p_worker

test: test-py
	@if command -v npm >/dev/null 2>&1 && [ -f package.json ]; then \
		echo "Running UI tests..."; \
		npm run test:ui; \
	else \
		echo "Skipping UI tests (npm/package.json not found)."; \
	fi

test-py:
	$(PYTHON) -m pytest

test-ui:
	npm run test:ui

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

migrate:
	$(MANAGE) migrate

makemigrations:
	$(MANAGE) makemigrations

shell:
	$(MANAGE) shell

reset-db:
	./scripts/reset-db.sh

kind-up:
	@if [ -x ./scripts/kind-create.sh ]; then ./scripts/kind-create.sh; else kind create cluster --name $(KIND_CLUSTER); fi

kind-down:
	kind delete cluster --name $(KIND_CLUSTER)

venv:
	@echo "Run: source .venv/bin/activate"

tag-release:
	@if [ -z "$(VERSION)" ]; then echo "VERSION is required (e.g., VERSION=v0.1.1)"; exit 1; fi
	git tag -a $(VERSION) -m "Release $(VERSION)"
	git push origin $(VERSION)

# -----------------------
# Docker (run from image)
# -----------------------

docker-build:
	docker build -t $(IMAGE) .

docker-pull:
	docker pull $(IMAGE)

docker-ps:
	@docker ps --filter "name=$(API_NAME)" --filter "name=$(WORKER_NAME)" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

docker-migrate:
	docker run --rm \
	  --env-file $(ENV_FILE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  $(IMAGE) \
	  python api/manage.py migrate

docker-api-up:
	@docker rm -f $(API_NAME) >/dev/null 2>&1 || true
	docker run -d --name $(API_NAME) \
	  --env-file $(ENV_FILE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  -p $(PORT):8000 \
	  $(IMAGE) \
	  python api/manage.py runserver 0.0.0.0:8000
	@echo "API: http://127.0.0.1:$(PORT)/"

docker-api-down:
	@docker rm -f $(API_NAME) >/dev/null 2>&1 || true

docker-api-logs:
	docker logs -f $(API_NAME)

docker-api-shell:
	docker exec -it $(API_NAME) /bin/sh

kubeconfig-kind:
	./scripts/kubeconfig-kind.sh "$(KIND_CLUSTER)" "$(KUBECONFIG_KIND)"

docker-worker-up: kubeconfig-kind
	@docker rm -f $(WORKER_NAME) >/dev/null 2>&1 || true
	docker run -d --name $(WORKER_NAME) \
	  --env-file $(ENV_FILE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -e KUBECONFIG=/kube/config \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  -v "$(PWD)/$(KUBECONFIG_KIND):/kube/config:ro" \
	  --network $(KIND_NETWORK) \
	  $(IMAGE) \
	  python api/manage.py k2p_worker
	@echo "Worker started."

docker-worker-down:
	@docker rm -f $(WORKER_NAME) >/dev/null 2>&1 || true

docker-worker-logs:
	docker logs -f $(WORKER_NAME)

docker-worker-shell:
	docker exec -it $(WORKER_NAME) /bin/sh

docker-dev-up: kind-up docker-build docker-migrate docker-api-up docker-worker-up

docker-dev-down: docker-worker-down docker-api-down
