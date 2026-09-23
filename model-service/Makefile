PYTHON ?= ../backend/.venv/bin/python
RUFF ?= ../backend/.venv/bin/ruff
.PHONY: test check build browser dev stop
test:
	$(PYTHON) -m pytest -c pytest.ini tests -q
check:
	$(RUFF) check .
	$(RUFF) format --check .
	npx prettier --check 'admin-web/src/**/*.{ts,vue,css}' 'admin-web/*.{json,ts}' 'user-web/src/**/*.{ts,vue,css}' 'user-web/*.{json,ts}'
	$(MAKE) test
	$(MAKE) build
build:
	npm run build --prefix admin-web
	npm run build --prefix user-web
browser:
	node tests/browser.mjs
dev:
	$(PYTHON) scripts/dev.py start
stop:
	$(PYTHON) scripts/dev.py stop
