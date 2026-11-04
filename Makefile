SHELL := /bin/bash
.PHONY: lock-backend setup dev dev-web stop lint lint-frontend lint-backend test test-backend test-frontend test-e2e smoke smoke-backend smoke-frontend smoke-real migration-check migration-head-check test-middleware build docker-build preflight preflight-lite remote-test
lock-backend:
	backend/.venv/bin/pip-compile --no-emit-index-url --no-emit-trusted-host --output-file backend/requirements.lock backend/requirements.txt
setup:
	python3 -m venv backend/.venv
	npm ci
	cd backend && .venv/bin/pip install -r requirements-dev.txt
dev:
	python3 scripts/local_runtime.py dev
dev-web:
	npm run dev -- --host 127.0.0.1
stop:
	docker compose -f docker-compose.yml -f docker-compose.local-build.yml --profile workers down
lint: lint-frontend lint-backend
lint-frontend:
	npm run format:check
	npm run lint
lint-backend:
	cd backend && .venv/bin/ruff check app tests migrations
	cd backend && .venv/bin/ruff format --check app tests migrations
	backend/.venv/bin/ruff check scripts/local_runtime.py scripts/local_middleware_proof.py
	backend/.venv/bin/ruff format --check scripts/local_runtime.py scripts/local_middleware_proof.py
test: test-backend test-frontend
test-backend:
	cd backend && .venv/bin/pytest -q --cov=app --cov-report=term-missing --cov-fail-under=55
test-frontend:
	npm test
test-e2e:
	npm run test:e2e
# 重大调整后的无费用主流程冒烟：API 完整旅程/隔离 + 浏览器 ASS/模型配置旅程。
smoke: smoke-backend smoke-frontend
smoke-backend:
	cd backend && .venv/bin/pytest -q tests/test_user_journey.py::test_complete_api_user_journey tests/test_multi_user.py::test_projects_and_private_resources_are_isolated tests/test_multi_user.py::test_general_storyboard_all_empty_outline_needs_no_cast tests/test_admin_console.py::test_non_admin_cannot_access_admin_but_can_read_model_options
smoke-frontend:
	npm run test:e2e:smoke
# 有真实费用；调用方必须显式指定 PLAYWRIGHT_BASE_URL（或 REMOTE_API_BASE_URL）。
smoke-real:
	npm run test:e2e:smoke-real
migration-check:
	./scripts/check-migrations.sh
build:
	npm run build
docker-build:
	python3 scripts/local_runtime.py build
migration-head-check:
	python3 scripts/local_runtime.py heads
test-middleware:
	python3 scripts/local_runtime.py middleware
# Native checks first; real PostgreSQL/Redis are disposable and never reused.
preflight: preflight-lite test-middleware
preflight-lite: lint migration-head-check test build
remote-test:
	npm run test:admin && npm run test:remote:all
