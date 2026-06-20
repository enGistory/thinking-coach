$ErrorActionPreference = "Stop"
uv lock --check
uv sync --locked --all-groups
uv run python scripts/verify_dependency_policy.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
