.PHONY: help dev server worker test test-ui lint fmt migrate makemigrations shell reset-db kind-up kind-down venv release-docker

PYTHON ?= python
MANAGE := $(PYTHON) api/manage.py

help:
	@echo "Targets:"
	@echo "  dev           Run API server + worker (two terminals)"
	@echo "  server        Run Django dev server"
	@echo "  worker        Run k2p worker loop"
	@echo "  test          Run pytest"
	@echo "  test-ui       Run UI unit tests (requires npm)"
	@echo "  lint          Run ruff"
	@echo "  fmt           Run ruff format"
	@echo "  migrate       Apply migrations"
	@echo "  makemigrations Create migrations"
	@echo "  shell         Django shell"
	@echo "  reset-db      Flush DB and re-migrate"
	@echo "  kind-up       Create local kind cluster (if kind installed)"
	@echo "  kind-down     Delete local kind cluster"
	@echo "  venv          Print activate command for local venv"
	@echo "  release-docker Build local Docker image"

dev:
	@echo "Run in two terminals:"
	@echo "  make server"
	@echo "  make worker"

server:
	$(MANAGE) runserver

worker:
	$(MANAGE) k2p_worker

test:
	$(PYTHON) -m pytest
	npm run test:ui

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
	kind create cluster --name k2p

kind-down:
	kind delete cluster --name k2p

venv:
	@echo "Run: source .venv/bin/activate"

release-docker:
	docker build -t k2p-web:local .
