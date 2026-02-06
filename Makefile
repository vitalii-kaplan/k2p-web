#************************************************************************#
# make docker-dev-up
# make docker-api-logs
# make docker-worker-logs
# make docker-dev-down 
#************************************************************************#

.DEFAULT_GOAL := help

.PHONY: help dev server worker test test-py test-ui lint fmt \
        migrate makemigrations shell reset-db \
        docker-build docker-pull docker-ps \
        docker-api-up docker-api-down docker-api-logs docker-api-shell \
        docker-migrate \
        docker-worker-up docker-worker-down docker-worker-logs docker-worker-shell \
        docker-dev-up docker-dev-down venv tag-release

# Load .env into Make variables (and export them to subcommands), if present.
ifneq (,$(wildcard .env))
  include .env
  export
endif

ifneq (,$(wildcard .venv/bin/python))
  PYTHON ?= .venv/bin/python
else
  PYTHON ?= python
endif
MANAGE := $(PYTHON) api/manage.py

# ---- Docker / "simulate prod" knobs ----
IMAGE ?= k2p-web:local                 # set to ghcr.io/<you>/<repo>:<tag> when you want
ENV_FILE ?= .env

API_NAME ?= k2pweb-api
WORKER_NAME ?= k2pweb-worker
PORT ?= 8000
WORKER_METRICS_PORT ?= 8001
DOCKER_DB_ENGINE ?= sqlite

# Mount repo into containers at /repo (matches your kind dev mount pattern)
REPO_MOUNT ?= /repo

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "}; /^[A-Za-z0-9][^:]*:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -----------------------
# Local (from source)
# -----------------------

print-%: ## Print a Make variable (e.g., make print-PYTHON)
	@echo '$*=$($*)'

dev: ## Print local dev run instructions
	@echo "Run in two terminals:"
	@echo "  make server"
	@echo "  make worker"

server: ## Run Django dev server
	$(MANAGE) runserver

worker: ## Run k2p worker loop
	$(MANAGE) k2p_worker

test: test-py ## Run tests (UI tests only if npm+package.json exist)
	@if command -v npm >/dev/null 2>&1 && [ -f package.json ]; then \
		echo "Running UI tests..."; \
		npm run test:ui; \
	else \
		echo "Skipping UI tests (npm/package.json not found)."; \
	fi

test-py: ## Run pytest
	$(PYTHON) -m pytest

test-ui: ## Run UI unit tests
	npm run test:ui

lint: ## Run ruff checks
	$(PYTHON) -m ruff check .

fmt: ## Run ruff format
	$(PYTHON) -m ruff format .

migrate: ## Apply migrations
	$(MANAGE) migrate

makemigrations: ## Create migrations
	$(MANAGE) makemigrations

shell: ## Open Django shell
	$(MANAGE) shell

reset-db: ## Flush DB and re-migrate
	./scripts/reset-db.sh

venv: ## Print activate command
	@echo "Run: source .venv/bin/activate"

tag-release: ## Tag release and push (requires VERSION=vX.Y.Z)
	@if [ -z "$(VERSION)" ]; then echo "VERSION is required (e.g., VERSION=v0.1.1)"; exit 1; fi
	git tag -a $(VERSION) -m "Release $(VERSION)"
	git push origin $(VERSION)

# -----------------------
# Docker (run from image)
# -----------------------

docker-build: ## Build local image
	docker build -t $(IMAGE) .

docker-pull: ## Pull image
	docker pull $(IMAGE)

docker-ps: ## Show API/worker containers
	@docker ps --filter "name=$(API_NAME)" --filter "name=$(WORKER_NAME)" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

docker-migrate: ## Run migrations inside image
	docker run --rm \
	  --env-file $(ENV_FILE) \
	  -e DB_ENGINE=$(DOCKER_DB_ENGINE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  $(IMAGE) \
	  python api/manage.py migrate

docker-api-up: ## Start API container from image
	@docker rm -f $(API_NAME) >/dev/null 2>&1 || true
	docker run -d --name $(API_NAME) \
	  --env-file $(ENV_FILE) \
	  -e DB_ENGINE=$(DOCKER_DB_ENGINE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  -p $(PORT):8000 \
	  $(IMAGE) \
	  python api/manage.py runserver 0.0.0.0:8000 --insecure
	@echo "API: http://127.0.0.1:$(PORT)/"

docker-api-down: ## Stop API container
	@docker rm -f $(API_NAME) >/dev/null 2>&1 || true

docker-api-logs: ## Tail API logs
	docker logs -f $(API_NAME)

docker-api-shell: ## Shell into API container
	docker exec -it $(API_NAME) /bin/sh

docker-worker-up: ## Start worker container (local Docker runner)
	@docker rm -f $(WORKER_NAME) >/dev/null 2>&1 || true
	docker run -d --name $(WORKER_NAME) \
	  --env-file $(ENV_FILE) \
	  -e DB_ENGINE=$(DOCKER_DB_ENGINE) \
	  -e REPO_ROOT=$(REPO_MOUNT) \
	  -e HOST_REPO_ROOT=$(PWD) \
	  -e HOST_JOB_STORAGE_ROOT=$(PWD)/var/jobs \
	  -e HOST_RESULT_STORAGE_ROOT=$(PWD)/var/results \
	  -e WORKER_METRICS_PORT=$(WORKER_METRICS_PORT) \
	  -v "$(PWD):$(REPO_MOUNT)" \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -p $(WORKER_METRICS_PORT):$(WORKER_METRICS_PORT) \
	  $(IMAGE) \
	  python api/manage.py k2p_worker
	@echo "Worker started."

docker-worker-down: ## Stop worker container
	@docker rm -f $(WORKER_NAME) >/dev/null 2>&1 || true

docker-worker-logs: ## Tail worker logs
	docker logs -f $(WORKER_NAME)

docker-worker-shell: ## Shell into worker container
	docker exec -it $(WORKER_NAME) /bin/sh

docker-dev-up: docker-build docker-migrate docker-api-up docker-worker-up ## Full dev stack (api + worker)

docker-dev-down: docker-worker-down docker-api-down ## Stop dev containers

# -----------------------
# Production (droplet) via docker compose
# -----------------------
PROD_COMPOSE ?= docker-compose.prod.nginx.yml

prod-up: ## Start production stack (api+nginx+postgres+worker)
	docker compose -f $(PROD_COMPOSE) up -d --remove-orphans

prod-down: ## Stop production stack
	docker compose -f $(PROD_COMPOSE) down --remove-orphans

prod-ps: ## Show production containers
	docker compose -f $(PROD_COMPOSE) ps

prod-api-logs: ## Tail API logs
	docker compose -f $(PROD_COMPOSE) logs -f api

prod-worker-logs: ## Tail worker logs
	docker compose -f $(PROD_COMPOSE) logs -f worker

prod-nginx-logs: ## Tail nginx logs
	docker compose -f $(PROD_COMPOSE) logs -f nginx

prod-migrate: ## Run migrations in production stack
	docker compose -f $(PROD_COMPOSE) run --rm api python manage.py migrate

prod-check: ## Run your production smoke-check script
	./scripts/prod-droplet-check.sh
