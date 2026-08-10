SHELL := /bin/bash
.PHONY: setup dev stop lint lint-frontend lint-backend test test-backend test-frontend test-e2e migration-check build docker-build preflight remote-test
setup:
	npm ci
	cd backend && .venv/bin/pip install -r requirements-dev.txt
dev:
	docker compose up -d
stop:
	docker compose down
lint: lint-frontend lint-backend
lint-frontend:
	npm run lint
lint-backend:
	cd backend && .venv/bin/ruff check app tests migrations
	cd backend && .venv/bin/ruff format --check app tests migrations
test: test-backend test-frontend
test-backend:
	cd backend && .venv/bin/pytest -q --cov=app --cov-report=term-missing --cov-fail-under=55
test-frontend:
	npm test
test-e2e:
	npm run test:e2e
migration-check:
	./scripts/check-migrations.sh
build:
	npm run build
docker-build:
	docker compose -f docker-compose.yml -f docker-compose.local-build.yml build
preflight: lint migration-check test build docker-build
remote-test:
	npm run test:admin && npm run test:remote:all
