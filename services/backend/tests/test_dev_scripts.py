from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_setup_env_script_uses_locked_dependency_sync_and_docker_build() -> None:
    script = _read_repo_file("scripts/setup-env.ps1")

    assert "Assert-DockerDaemon" in script
    assert "Docker daemon 不可用" in script
    assert '@("compose", "-f", $composeFile, "build")' in script
    assert '@("lock", "--check")' in script
    assert '@("sync", "--locked", "--all-groups")' in script
    assert '"--frozen-lockfile"' in script
    assert "uv lock" not in script
    assert "uv sync --all-groups" not in script


def test_start_dev_script_runs_migrations_before_services() -> None:
    script = _read_repo_file("scripts/start-dev.ps1")

    daemon_index = script.index("Assert-DockerDaemon")
    postgres_index = script.index('"up", "-d", "postgres"')
    migration_index = script.index('"alembic", "upgrade", "head"')
    checkpointer_index = script.index('"scripts/setup_checkpointer.py"')
    services_index = script.index('"up", "-d", "api", "worker", "scheduler", "web"')

    assert daemon_index < postgres_index < migration_index < checkpointer_index < services_index
    assert "Docker daemon 不可用" in script
    assert "http://localhost:8000/api/v1/health" in script
    assert "http://localhost:5173" in script


def test_readme_documents_windows_setup_and_start_scripts() -> None:
    readme = _read_repo_file("README.md")

    assert ".\\scripts\\setup-env.ps1" in readme
    assert ".\\scripts\\start-dev.ps1" in readme
