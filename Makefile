SHELL := /bin/bash
.PHONY: setup dev stop lint lint-frontend lint-backend test test-backend test-frontend test-e2e smoke smoke-backend smoke-frontend smoke-real migration-check build docker-build preflight preflight-lite remote-test
setup:
	npm ci
	cd backend && .venv/bin/pip install -r requirements-dev.txt
dev:
	docker compose -f docker-compose.yml -f docker-compose.local-build.yml up -d
stop:
	docker compose down
lint: lint-frontend lint-backend
lint-frontend:
	npm run format:check
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
	docker compose -f docker-compose.yml -f docker-compose.local-build.yml build
preflight: lint migration-check test build docker-build
# 日常提交前快速卡口：跳过 Docker 构建（约省一半时间），发布前仍跑完整 preflight
preflight-lite: lint migration-check test build
remote-test:
	npm run test:admin && npm run test:remote:all
