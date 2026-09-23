PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: setup dev test test-e2e seed-demo verify-docs verify-deploy compose-config compose-up compose-down compose-logs migrate backup test-postgres test-proxy migrate-local worker

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r backend/requirements-runtime.lock "pytest==9.1.1" "pytest-asyncio==1.4.0" "playwright==1.63.0"
	npm --prefix frontend/nextjs ci --legacy-peer-deps
	$(VENV_PYTHON) -m playwright install chromium

dev:
	PHARMA_RUNTIME_MODE=replay $(VENV_PYTHON) backend/run_server.py

test:
	$(VENV_PYTHON) -m pytest -q backend/tests

test-e2e:
	NEXT_PUBLIC_PHARMA_RUNTIME_MODE=live NEXT_PUBLIC_PHARMA_API_URL='' npm --prefix frontend/nextjs run build
	$(VENV_PYTHON) scripts/test_frontend_e2e.py

test-postgres:
	bash scripts/test_postgres.sh

test-proxy:
	$(VENV_PYTHON) deploy/proxy-smoke.py

seed-demo:
	PHARMA_RUNTIME_MODE=replay $(VENV_PYTHON) -m backend.cli seed-demo


verify-docs:
	$(VENV_PYTHON) docs/reference/PharmaScope_Lite_v1.0/scripts/verify_context.py

verify-deploy:
	bash deploy/verify.sh

compose-config:
	bash deploy/compose.sh .env.example.demo config --quiet

compose-up:
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" up -d db
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" run --rm --build migrate
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" up -d --build api worker web

compose-down:
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" down

compose-logs:
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" logs -f api worker db

migrate:
	bash deploy/compose.sh "$${PHARMA_ENV_FILE:-.env.example.demo}" run --rm migrate

migrate-local:
	$(VENV_PYTHON) -m alembic upgrade head

worker:
	$(VENV_PYTHON) -m backend.worker

backup:
	$(VENV_PYTHON) deploy/backup.py

# Networked checks require a test-only DB and never invent missing credentials.
test-live-frontend:
	$(VENV_PYTHON) scripts/test_live_frontend.py

live-probe:
	$(VENV_PYTHON) -m backend.live_probe --sources --model
