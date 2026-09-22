PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: setup dev test test-e2e seed-demo verify-docs

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install "fastapi>=0.104" "uvicorn>=0.24" "pydantic>=2.5" "httpx>=0.28" "pytest>=8" PyYAML jsonschema
	cd frontend/nextjs && npm install --legacy-peer-deps

dev:
	PHARMA_RUNTIME_MODE=replay $(VENV_PYTHON) backend/run_server.py

test:
	$(VENV_PYTHON) -m pytest -q backend/tests

test-e2e:
	$(VENV_PYTHON) -m pytest -q backend/tests
	cd frontend/nextjs && npm run build

seed-demo:
	$(VENV_PYTHON) -c "from backend.pharma_scope_app import state; print('replay workspace seeded:', len(state.drugs), 'drugs,', len(state.records), 'source records,', len(state.observations), 'observations')"

verify-docs:
	$(VENV_PYTHON) docs/reference/PharmaScope_Lite_v1.0/scripts/verify_context.py
