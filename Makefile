# AIVANTA Relay (n8n) developer commands
.PHONY: install api worker web dev test e2e lint up down n8n-up n8n-bootstrap n8n-workflows n8n-test

install:            ## Python + Node dependencies
	python -m pip install -e ".[dev]"
	npm install

api:                ## API on :8000 (SQLite, mock LLM, emulated n8n by default)
	uvicorn aivanta_api.main:app --reload --port 8000

worker:             ## run worker (RUN_EXECUTION=worker)
	python -m aivanta_api.worker

web:                ## Next.js on :3000
	npm run dev

test:               ## unit + integration + runtime contract tests (emulated n8n, mock LLM)
	pytest -q

n8n-test:           ## the same contract tests against a real n8n (needs N8N_API_KEY, n8n reachable, API on :8000)
	N8N_MODE=rest pytest -q tests/live

e2e:                ## Playwright UI tests (API and web must be running)
	npx playwright install chromium && npm run test:e2e

lint:
	ruff check .

n8n-up:             ## databases, Redis, n8n main + worker
	docker compose up -d db n8n-db redis n8n n8n-worker

n8n-bootstrap:      ## create the n8n owner + API key and write N8N_API_KEY into .env
	python scripts/n8n_bootstrap.py --n8n http://localhost:5678 --email $${N8N_OWNER_EMAIL:-ops@example.com} --password $${N8N_OWNER_PASSWORD:?set N8N_OWNER_PASSWORD} --write-env .env

n8n-workflows:      ## regenerate n8n/workflows/*.json from the built-in templates
	python scripts/export_n8n_workflows.py --mode native
	python scripts/export_n8n_workflows.py --mode service

up:                 ## full stack in Docker (run n8n-bootstrap once first)
	docker compose up -d --build

down:
	docker compose down
