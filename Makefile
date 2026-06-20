.PHONY: lint typecheck test backend-lint backend-typecheck backend-test web-lint web-typecheck web-test web-build

lint: backend-lint web-lint

typecheck: backend-typecheck web-typecheck

test: backend-test web-test

backend-lint:
	cd services/backend && uv run ruff check . && uv run ruff format --check .

backend-typecheck:
	cd services/backend && uv run mypy app

backend-test:
	cd services/backend && uv run pytest -q

web-lint:
	pnpm --dir apps/web lint

web-typecheck:
	pnpm --dir apps/web type-check

web-test:
	pnpm --dir apps/web test

web-build:
	pnpm --dir apps/web build
