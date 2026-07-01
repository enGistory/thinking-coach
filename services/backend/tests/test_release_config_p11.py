from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from scripts.release_manifest import build_release_manifest
from scripts.release_manifest import main as release_manifest_main
from scripts.validate_release_env import main, validate_release_env

_VALID_RELEASE_ENV_VALUES = {
    "POSTGRES_DB": "thinking",
    "POSTGRES_USER": "thinking",
    "POSTGRES_PASSWORD": "prod-postgres-password-32-chars-long",
    "APP_ENV": "production",
    "APP_BASE_URL": "https://api.thinking.invalid",
    "WEB_BASE_URL": "https://app.thinking.invalid",
    "TZ": "Asia/Shanghai",
    "JWT_SECRET": "prod-jwt-secret-32-chars-long-value",
    "LANGGRAPH_AES_KEY": "prod-langgraph-aes-key-32-chars-long",
    "AI_PROVIDER": "aliyun",
    "AI_PROVIDER_MODE": "aliyun",
    "DASHSCOPE_API_KEY": "sk-prod-shaped-value",
    "DASHSCOPE_BASE_URL": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "DASHSCOPE_HTTP_BASE_URL": "https://dashscope.aliyuncs.com/api/v1",
    "DASHSCOPE_WEBSOCKET_BASE_URL": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
    "QWEN_DIALOG_MODEL": "qwen-dialog-prod",
    "QWEN_QUESTION_MODEL": "qwen-question-prod",
    "QWEN_REVIEW_MODEL": "qwen-review-prod",
    "QWEN_VERIFY_MODEL": "qwen-verify-prod",
    "QWEN_FALLBACK_MODEL": "qwen-fallback-prod",
    "ALIYUN_ASR_MODEL": "fun-asr",
    "ALIYUN_TTS_MODEL": "cosyvoice-v3-flash",
    "ALIYUN_TTS_VOICE": "longanyang",
    "ALIYUN_EMBEDDING_MODEL": "text-embedding-v4",
    "ALIYUN_EMBEDDING_DIMENSIONS": "1024",
    "SEARCH_PROVIDER": "bocha",
    "BOCHA_API_KEY": "bocha-prod-shaped-value",
    "BOCHA_SEARCH_ENDPOINT": "https://api.bochaai.com/v1/web-search",
    "BOCHA_SEARCH_COUNT": "8",
    "BOCHA_FRESHNESS": "oneYear",
    "WEB_PUSH_VAPID_PUBLIC_KEY": "vapid-public-shaped-value",
    "WEB_PUSH_VAPID_PRIVATE_KEY": "vapid-private-shaped-value-32-chars",
    "WEB_PUSH_ALLOW_FAKE_IP_HOSTS": "",
}


def _write_release_env(tmp_path: Path, overrides: dict[str, str] | None = None) -> Path:
    env_file = tmp_path / "env.production"
    values = dict(_VALID_RELEASE_ENV_VALUES)
    if overrides is not None:
        values.update(overrides)
    env_file.write_text(
        "\n".join(f"{name}={value}" for name, value in values.items()),
        encoding="utf-8",
    )
    return env_file


def test_production_env_example_satisfies_startup_validators() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env_example = repo_root / "infra" / "env.production.example"

    settings = Settings(_env_file=env_example)

    settings.validate_auth()
    settings.validate_ai()
    settings.validate_search()
    settings.validate_push()


def test_release_manifest_records_migration_head_and_image_tag_without_secrets(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    image_tag = "thinking-coach:test-release-tag"
    output_file = tmp_path / "release" / "manifest.json"

    manifest = build_release_manifest(repo_root=repo_root, image_tag=image_tag)
    exit_code = release_manifest_main(
        [
            "--repo-root",
            str(repo_root),
            "--image-tag",
            image_tag,
            "--output",
            str(output_file),
        ]
    )
    output = capsys.readouterr().out
    cli_manifest = json.loads(output)
    saved_manifest = json.loads(output_file.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert cli_manifest == manifest
    assert saved_manifest == manifest
    assert manifest["image_tag"] == image_tag
    assert manifest["alembic_heads"] == ["0010_release_privacy"]
    assert len(manifest["git_commit"]) == 40
    assert manifest["git_short_commit"] == manifest["git_commit"][:12]
    assert manifest["worktree_status"] in {"clean", "dirty"}
    assert set(manifest["artifact_hashes"]) == {
        "apps/web/package.json",
        "infra/docker-compose.prod.yml",
        "infra/nginx/Dockerfile",
        "infra/nginx/default.conf",
        "services/backend/pyproject.toml",
    }
    assert all(len(value) == 64 for value in manifest["artifact_hashes"].values())

    serialized_manifest = json.dumps(manifest, ensure_ascii=False)
    forbidden_fragments = (
        "POSTGRES_PASSWORD",
        "JWT_SECRET",
        "DASHSCOPE_API_KEY",
        "BOCHA_API_KEY",
        "WEB_PUSH_VAPID_PRIVATE_KEY",
        "ALIYUN_OSS_ACCESS_KEY_SECRET",
        "env.production",
        "fullchain.pem",
        "privkey.pem",
    )
    for fragment in forbidden_fragments:
        assert fragment not in serialized_manifest


@pytest.mark.parametrize(
    ("image_tag", "expected_error"),
    [
        ("   ", "image tag must not be blank"),
        ("thinking coach:test-release-tag", "image tag must not contain whitespace"),
    ],
)
def test_release_manifest_rejects_invalid_image_tag(
    capsys: pytest.CaptureFixture[str],
    image_tag: str,
    expected_error: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    exit_code = release_manifest_main(["--repo-root", str(repo_root), "--image-tag", image_tag])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert expected_error in captured.err


def test_release_manifest_rejects_non_json_output_path(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    output_file = tmp_path / "release-manifest.txt"

    exit_code = release_manifest_main(
        [
            "--repo-root",
            str(repo_root),
            "--image-tag",
            "thinking-coach:test-release-tag",
            "--output",
            str(output_file),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "--output must end with .json" in captured.err
    assert not output_file.exists()


@pytest.mark.parametrize(
    ("relative_output", "expected_error"),
    [
        (
            "apps/web/package.json",
            "--output must not overwrite release source or configuration artifacts",
        ),
        ("infra/certs/release-manifest.json", "--output must not be inside private"),
        ("backups/release-manifest.json", "--output must not be inside private"),
    ],
)
def test_release_manifest_rejects_source_or_private_output_paths(
    capsys: pytest.CaptureFixture[str],
    relative_output: str,
    expected_error: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    output_file = repo_root / relative_output
    output_existed_before = output_file.exists()
    package_json = repo_root / "apps" / "web" / "package.json"
    package_json_hash = hashlib.sha256(package_json.read_bytes()).hexdigest()

    exit_code = release_manifest_main(
        [
            "--repo-root",
            str(repo_root),
            "--image-tag",
            "thinking-coach:test-release-tag",
            "--output",
            str(output_file),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert expected_error in captured.err
    assert output_file.exists() is output_existed_before
    assert hashlib.sha256(package_json.read_bytes()).hexdigest() == package_json_hash


def test_release_private_artifacts_are_git_ignored() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "infra/env.production",
            "infra/certs/fullchain.pem",
            "infra/certs/privkey.pem",
            "backups/postgres/thinking-test.dump",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    ignored_paths = set(result.stdout.splitlines())
    assert ignored_paths == {
        "infra/env.production",
        "infra/certs/fullchain.pem",
        "infra/certs/privkey.pem",
        "backups/postgres/thinking-test.dump",
    }


def test_release_private_artifacts_are_docker_ignored() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8")
    patterns = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "infra/env.production" in patterns
    assert "infra/certs/" in patterns
    assert "backups/" in patterns
    assert "secrets" in patterns
    assert "*.pem" in patterns
    assert "*.key" in patterns


def test_production_nginx_enforces_https_and_proxies_api() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = (repo_root / "infra" / "nginx" / "default.conf").read_text(encoding="utf-8")

    assert "listen 80;" in config
    assert "return 301 https://$host$request_uri;" in config
    assert "listen 443 ssl http2;" in config
    assert "ssl_certificate /etc/nginx/certs/fullchain.pem;" in config
    assert "ssl_certificate_key /etc/nginx/certs/privkey.pem;" in config
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in config
    assert "client_max_body_size 64m;" in config
    assert "location /api/" in config
    assert "proxy_pass http://api:8000;" in config
    assert "proxy_set_header X-Forwarded-Proto https;" in config


def test_production_nginx_sets_security_headers_on_served_responses() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    config = (repo_root / "infra" / "nginx" / "default.conf").read_text(encoding="utf-8")

    expected_headers = (
        'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;',
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header X-Frame-Options "DENY" always;',
        'add_header Referrer-Policy "same-origin" always;',
    )
    for header in expected_headers:
        assert config.count(header) == 3

    assert 'add_header Cache-Control "no-store" always;' in config
    assert 'add_header Cache-Control "public, max-age=2592000, immutable" always;' in config


def test_production_compose_wires_nginx_certs_audio_and_migrations() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "infra" / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "dockerfile: infra/nginx/Dockerfile" in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert "./certs:/etc/nginx/certs:ro" in compose
    assert "audio_data:/data/audio" in compose
    assert "uv run alembic upgrade head" in compose
    assert "uv run python scripts/setup_checkpointer.py" in compose
    assert "postgres_data:" in compose
    assert "audio_data:" in compose


def test_production_compose_only_publishes_nginx_ports() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "infra" / "docker-compose.prod.yml").read_text(encoding="utf-8")

    postgres_service = compose.split("\n  postgres:", maxsplit=1)[1].split(
        "\n  api:",
        maxsplit=1,
    )[0]
    api_service = compose.split("\n  api:", maxsplit=1)[1].split("\n  worker:", maxsplit=1)[0]
    worker_service = compose.split("\n  worker:", maxsplit=1)[1].split(
        "\n  scheduler:",
        maxsplit=1,
    )[0]
    scheduler_service = compose.split("\n  scheduler:", maxsplit=1)[1].split(
        "\n  nginx:",
        maxsplit=1,
    )[0]
    nginx_service = compose.split("\n  nginx:", maxsplit=1)[1].split("\nvolumes:", maxsplit=1)[0]

    for private_service in (
        postgres_service,
        api_service,
        worker_service,
        scheduler_service,
    ):
        assert "\n    ports:" not in private_service

    assert '\n    ports:\n      - "80:80"\n      - "443:443"' in nginx_service


def test_production_nginx_does_not_expose_private_audio_storage() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "infra" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    config = (repo_root / "infra" / "nginx" / "default.conf").read_text(encoding="utf-8")

    nginx_service = compose.split("\n  nginx:", maxsplit=1)[1].split("\nvolumes:", maxsplit=1)[0]

    assert "audio_data" not in nginx_service
    assert "/data/audio" not in nginx_service
    assert "location /audio" not in config
    assert "/data/audio" not in config


def test_production_nginx_final_image_only_copies_static_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (repo_root / "infra" / "nginx" / "Dockerfile").read_text(
        encoding="utf-8",
    )
    final_stage = dockerfile.split("FROM ${NGINX_IMAGE}", maxsplit=1)[1]

    assert "COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf" in final_stage
    assert "COPY --from=web-build /workspace/apps/web/dist /usr/share/nginx/html" in final_stage

    disallowed_final_copies = (
        "COPY apps/web",
        "COPY package.json",
        "COPY pnpm-lock.yaml",
        "COPY pnpm-workspace.yaml",
        "COPY .",
        ".env",
        "env.production",
    )
    for disallowed in disallowed_final_copies:
        assert disallowed not in final_stage


def test_backup_script_writes_portable_checksum_sidecar() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "infra" / "scripts" / "backup-postgres.sh").read_text(encoding="utf-8")

    umask_index = script.index("umask 077")
    retention_index = script.index(
        'require_minimum_integer "BACKUP_RETENTION_DAILY" "${daily_keep}" 7',
        script.index('require_env_file_without_bom "${env_file}"'),
    )
    mkdir_index = script.index('mkdir -p "${backup_dir}"')
    dump_index = script.index("pg_dump")
    assert umask_index < mkdir_index
    assert umask_index < dump_index
    assert retention_index < dump_index
    assert 'temp_output="${output}.tmp"' in script
    assert 'temp_checksum_output="${checksum_output}.tmp"' in script
    assert "trap cleanup_incomplete_backup EXIT" in script
    assert "sha256sum is required to write backup checksum sidecar" in script
    assert 'sha256sum "${temp_backup_file}"' in script
    assert 'printf \'%s  %s\\n\' "${checksum_hash}" "${backup_file}"' in script
    assert 'mv -- "${temp_output}" "${output}"' in script
    assert 'mv -- "${temp_checksum_output}" "${checksum_output}"' in script
    assert 'backup_file="$(basename "${output}")"' in script
    assert 'cd "${backup_dir}"' in script
    assert "strip_carriage_return POSTGRES_USER" in script
    assert "strip_carriage_return POSTGRES_DB" in script


def test_backup_script_removes_partial_dump_when_pg_dump_fails(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is required for backup failure smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "backup-postgres.sh"
    backup_dir = tmp_path / "backups"
    env_file = tmp_path / "env.production"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=release-rehearsal",
                "POSTGRES_USER=thinking",
                "POSTGRES_DB=thinking",
            ]
        ),
        encoding="utf-8",
    )

    command = " ".join(
        [
            "docker() { printf 'fake pg_dump failure\\n' >&2; return 42; };",
            "export -f docker;",
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            f"BACKUP_DIR={shlex.quote(backup_dir.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 42
    assert "fake pg_dump failure" in (result.stdout + result.stderr)
    assert list(backup_dir.glob("thinking-*.dump")) == []
    assert list(backup_dir.glob("thinking-*.dump.tmp")) == []
    assert list(backup_dir.glob("thinking-*.sha256")) == []


def test_backup_script_removes_dump_when_checksum_fails(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is required for backup checksum failure smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "backup-postgres.sh"
    backup_dir = tmp_path / "backups"
    env_file = tmp_path / "env.production"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=release-rehearsal",
                "POSTGRES_USER=thinking",
                "POSTGRES_DB=thinking",
            ]
        ),
        encoding="utf-8",
    )

    command = " ".join(
        [
            "docker() { printf 'fake dump bytes'; return 0; };",
            "export -f docker;",
            "sha256sum() { printf 'fake checksum failure\\n' >&2; return 43; };",
            "export -f sha256sum;",
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            f"BACKUP_DIR={shlex.quote(backup_dir.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 43
    assert "fake checksum failure" in (result.stdout + result.stderr)
    assert list(backup_dir.glob("thinking-*.dump")) == []
    assert list(backup_dir.glob("thinking-*.dump.tmp")) == []
    assert list(backup_dir.glob("thinking-*.sha256")) == []


def test_backup_script_strips_crlf_env_values_before_pg_dump(tmp_path: Path) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for backup CRLF env smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "backup-postgres.sh"
    backup_dir = tmp_path / "backups"
    env_file = tmp_path / "env.production"
    env_file.write_bytes(
        b"APP_ENV=release-rehearsal\r\nPOSTGRES_USER=thinking\r\nPOSTGRES_DB=thinking\r\n"
    )

    command = " ".join(
        [
            "docker() {",
            "local arg;",
            'for arg in "$@"; do',
            "case \"$arg\" in *$'\\r'*)",
            "printf 'carriage return leaked into docker args\\n' >&2;",
            "return 44;;",
            "esac;",
            "done;",
            "printf 'fake dump bytes';",
            "return 0;",
            "};",
            "export -f docker;",
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            f"BACKUP_DIR={shlex.quote(backup_dir.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "carriage return leaked" not in output
    dumps = list(backup_dir.glob("thinking-*.dump"))
    assert len(dumps) == 1
    assert dumps[0].read_text(encoding="utf-8") == "fake dump bytes"
    assert dumps[0].with_suffix(".dump.sha256").exists()


def test_backup_script_prune_only_retains_daily_and_weekly_snapshots(
    tmp_path: Path,
) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is required for backup retention smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "backup-postgres.sh"
    backup_dir = tmp_path / "postgres-backups"
    backup_dir.mkdir()

    newest_day = date(2026, 6, 25)
    stamps = [f"{(newest_day - timedelta(days=offset)):%Y%m%d}T000000Z" for offset in range(36)]
    for stamp in stamps:
        dump = backup_dir / f"thinking-{stamp}.dump"
        dump.write_text(stamp, encoding="utf-8")
        dump.with_suffix(".dump.sha256").write_text(
            f"{'0' * 64}  {dump.name}\n",
            encoding="utf-8",
        )
    manual_dump = backup_dir / "thinking-manual.dump"
    manual_dump.write_text("manual", encoding="utf-8")

    backup_dir_for_bash = backup_dir.relative_to(repo_root).as_posix()
    backup_command = " ".join(
        [
            f"BACKUP_DIR={shlex.quote(backup_dir_for_bash)}",
            "BACKUP_RETENTION_DAILY=7",
            "BACKUP_RETENTION_WEEKLY=4",
            shlex.quote(script.relative_to(repo_root).as_posix()),
            "--prune-only",
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", backup_command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    kept_names = {path.name for path in backup_dir.glob("*.dump")}
    expected_kept_offsets = {0, 1, 2, 3, 4, 5, 6, 7, 14, 21, 28}
    expected_kept = {
        f"thinking-{(newest_day - timedelta(days=offset)):%Y%m%d}T000000Z.dump"
        for offset in expected_kept_offsets
    }
    expected_kept.add("thinking-manual.dump")
    assert kept_names == expected_kept
    removed_dump = backup_dir / "thinking-20260617T000000Z.dump"
    assert not removed_dump.exists()
    assert not removed_dump.with_suffix(".dump.sha256").exists()
    for name in kept_names - {"thinking-manual.dump"}:
        assert (backup_dir / f"{name}.sha256").exists()


def test_restore_script_verifies_checksum_before_restore() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = (repo_root / "infra" / "scripts" / "restore-postgres.sh").read_text(encoding="utf-8")

    missing_sidecar_index = script.index("checksum sidecar not found")
    checksum_index = script.index('actual_hash="$(sha256sum "${backup_path}"')
    restore_index = script.index("pg_restore --clean --if-exists --no-owner")
    assert 'checksum_path="${backup_path}.sha256"' in script
    assert "RESTORE_ALLOW_MISSING_CHECKSUM" in script
    assert 'expected_hash="$(awk \'NR == 1 {print $1}\' "${checksum_path}")"' in script
    assert 'if [[ ! "${expected_hash}" =~ ^[0-9a-fA-F]{64}$ ]]; then' in script
    assert missing_sidecar_index < restore_index
    assert checksum_index < restore_index


def test_restore_script_requires_checksum_sidecar_before_env_or_docker(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is required for restore script missing checksum smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")

    result = subprocess.run(
        [
            "bash",
            script.relative_to(repo_root).as_posix(),
            dump.relative_to(repo_root).as_posix(),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "checksum sidecar not found" in output
    assert "RESTORE_ALLOW_MISSING_CHECKSUM=1" in output
    assert "env.production" not in output
    assert "pg_restore" not in output


def test_restore_script_missing_checksum_override_keeps_production_guard(
    tmp_path: Path,
) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is required for restore script missing checksum override smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")
    env_file = tmp_path / "env.production"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "POSTGRES_USER=thinking",
                "POSTGRES_DB=thinking",
            ]
        ),
        encoding="utf-8",
    )

    command = " ".join(
        [
            "RESTORE_ALLOW_MISSING_CHECKSUM=1",
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
            shlex.quote(dump.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "warning: restoring without checksum sidecar" in output
    assert "RESTORE_ALLOW_PRODUCTION=1" in output
    assert "pg_restore" not in output


def test_restore_script_rejects_bad_checksum_before_env_or_docker(tmp_path: Path) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for restore script checksum smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")
    dump.with_suffix(".dump.sha256").write_text(
        f"{'0' * 64}  {dump.name}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            script.relative_to(repo_root).as_posix(),
            dump.relative_to(repo_root).as_posix(),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "FAILED" in output
    assert "env.production" not in output
    assert "pg_restore" not in output


def test_restore_script_verifies_checksum_against_selected_backup_path(tmp_path: Path) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for restore script checksum smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-selected.dump"
    dump.write_bytes(b"selected dump")
    other_dump = tmp_path / "thinking-other.dump"
    other_dump.write_bytes(b"other dump")
    dump.with_suffix(".dump.sha256").write_text(
        f"{hashlib.sha256(other_dump.read_bytes()).hexdigest()}  {other_dump.name}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            script.relative_to(repo_root).as_posix(),
            dump.relative_to(repo_root).as_posix(),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert f"{dump.relative_to(repo_root).as_posix()}: FAILED" in output
    assert other_dump.name not in output
    assert "env.production" not in output
    assert "pg_restore" not in output


def test_restore_script_rejects_production_env_without_explicit_confirmation(
    tmp_path: Path,
) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for restore production guard smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")
    dump.with_suffix(".dump.sha256").write_text(
        f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  {dump.name}\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "env.production"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "POSTGRES_USER=thinking",
                "POSTGRES_DB=thinking",
            ]
        ),
        encoding="utf-8",
    )

    command = " ".join(
        [
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
            shlex.quote(dump.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 2
    assert "RESTORE_ALLOW_PRODUCTION=1" in output
    assert "pg_restore" not in output


def test_restore_script_strips_crlf_production_override_before_guard(
    tmp_path: Path,
) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for restore production override smoke")

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")
    dump.with_suffix(".dump.sha256").write_text(
        f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  {dump.name}\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "env.production"
    env_file.write_bytes(
        b"APP_ENV=production\r\n"
        b"RESTORE_ALLOW_PRODUCTION=1\r\n"
        b"POSTGRES_USER=thinking\r\n"
        b"POSTGRES_DB=thinking\r\n"
    )

    command = " ".join(
        [
            "docker() {",
            "local arg;",
            'for arg in "$@"; do',
            "case \"$arg\" in *$'\\r'*)",
            "printf 'carriage return leaked into docker args\\n' >&2;",
            "return 44;;",
            "esac;",
            "done;",
            "printf 'fake restore ok';",
            "return 0;",
            "};",
            "export -f docker;",
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            shlex.quote(script.relative_to(repo_root).as_posix()),
            shlex.quote(dump.relative_to(repo_root).as_posix()),
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "fake restore ok" in output
    assert "carriage return leaked" not in output
    assert "RESTORE_ALLOW_PRODUCTION=1" not in output


def test_backup_and_restore_scripts_reject_bom_env_before_docker(tmp_path: Path) -> None:
    if shutil.which("bash") is None or shutil.which("sha256sum") is None:
        pytest.skip("bash and sha256sum are required for BOM env smoke")

    repo_root = Path(__file__).resolve().parents[3]
    backup_script = repo_root / "infra" / "scripts" / "backup-postgres.sh"
    restore_script = repo_root / "infra" / "scripts" / "restore-postgres.sh"
    env_file = tmp_path / "env.production"
    env_file.write_bytes(
        b"\xef\xbb\xbfAPP_ENV=release-rehearsal\nPOSTGRES_USER=thinking\nPOSTGRES_DB=thinking\n"
    )
    dump = tmp_path / "thinking-test.dump"
    dump.write_bytes(b"not a real dump")
    dump.with_suffix(".dump.sha256").write_text(
        f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  {dump.name}\n",
        encoding="utf-8",
    )

    backup_command = " ".join(
        [
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            shlex.quote(backup_script.relative_to(repo_root).as_posix()),
        ]
    )
    backup_result = subprocess.run(
        ["bash", "-lc", backup_command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    backup_output = backup_result.stdout + backup_result.stderr
    assert backup_result.returncode == 2
    assert "UTF-8 without BOM" in backup_output
    assert "command not found" not in backup_output
    assert "pg_dump" not in backup_output

    restore_command = " ".join(
        [
            f"COMPOSE_ENV_FILE={shlex.quote(env_file.relative_to(repo_root).as_posix())}",
            shlex.quote(restore_script.relative_to(repo_root).as_posix()),
            shlex.quote(dump.relative_to(repo_root).as_posix()),
        ]
    )
    restore_result = subprocess.run(
        ["bash", "-lc", restore_command],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    restore_output = restore_result.stdout + restore_result.stderr
    assert restore_result.returncode == 2
    assert "UTF-8 without BOM" in restore_output
    assert "command not found" not in restore_output
    assert "pg_restore" not in restore_output


def test_release_env_preflight_rejects_checked_in_placeholders() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    errors = validate_release_env(repo_root / "infra" / "env.production.example")

    assert "POSTGRES_PASSWORD still uses a placeholder value" in errors
    assert "APP_BASE_URL still uses a placeholder value" in errors
    assert "DASHSCOPE_API_KEY still uses a placeholder value" in errors
    assert "WEB_PUSH_VAPID_PRIVATE_KEY still uses a placeholder value" in errors


def test_release_env_preflight_rejects_bom_env_without_printing_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "env.production"
    secret_value = "prod-secret-value-that-should-not-print"
    env_file.write_bytes(
        b"\xef\xbb\xbfPOSTGRES_DB=thinking\n" + f"JWT_SECRET={secret_value}\n".encode()
    )

    errors = validate_release_env(env_file)
    output = "\n".join(errors)

    assert errors == [f"{env_file} must be UTF-8 without BOM"]
    assert secret_value not in output


def test_release_env_preflight_rejects_invalid_utf8(tmp_path: Path) -> None:
    env_file = tmp_path / "env.production"
    env_file.write_bytes(b"\xff\xfePOSTGRES_DB=thinking\n")

    assert validate_release_env(env_file) == [f"{env_file} must be valid UTF-8"]


def test_release_env_preflight_rejects_duplicate_names_without_printing_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "env.production"
    secret_values = {
        "first": "prod-jwt-secret-first-should-not-print",
        "second": "prod-jwt-secret-second-should-not-print",
    }
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=thinking",
                f"JWT_SECRET={secret_values['first']}",
                f"JWT_SECRET={secret_values['second']}",
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_release_env(env_file)
    output = "\n".join(errors)

    assert errors == [f"{env_file} contains duplicate variable: JWT_SECRET"]
    for secret in secret_values.values():
        assert secret not in output


def test_release_env_preflight_rejects_malformed_line_without_printing_value(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "env.production"
    secret_value = "prod-jwt-secret-line-should-not-print"
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=thinking",
                f"JWT_SECRET {secret_value}",
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_release_env(env_file)
    output = "\n".join(errors)

    assert errors == [f"{env_file} contains malformed env line: 2"]
    assert secret_value not in output


def test_release_env_preflight_rejects_invalid_variable_name_without_value(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "env.production"
    secret_values = {
        "name": "prod-jwt-secret-name-side-should-not-print",
        "value": "prod-jwt-secret-value-side-should-not-print",
    }
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=thinking",
                f"export JWT_SECRET {secret_values['name']}={secret_values['value']}",
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_release_env(env_file)
    output = "\n".join(errors)

    assert errors == [f"{env_file} contains invalid variable name on line 2"]
    for secret in secret_values.values():
        assert secret not in output


def test_release_env_preflight_accepts_realistic_non_secret_shape(tmp_path: Path) -> None:
    env_file = _write_release_env(tmp_path)

    assert validate_release_env(env_file) == []


def test_release_env_preflight_rejects_insecure_public_base_urls(tmp_path: Path) -> None:
    env_file = _write_release_env(
        tmp_path,
        {
            "APP_BASE_URL": "http://api.thinking.invalid",
            "WEB_BASE_URL": "http://app.thinking.invalid",
        },
    )

    errors = validate_release_env(env_file)

    assert "APP_BASE_URL must use https:// for release env validation" in errors
    assert "WEB_BASE_URL must use https:// for release env validation" in errors


def test_release_env_preflight_rejects_non_public_base_url_hosts(tmp_path: Path) -> None:
    env_file = _write_release_env(
        tmp_path,
        {
            "APP_BASE_URL": "https://localhost:8000",
            "WEB_BASE_URL": "https://127.0.0.1:5173",
        },
    )

    errors = validate_release_env(env_file)

    assert "APP_BASE_URL must use a public hostname for release env validation" in errors
    assert "WEB_BASE_URL must use a public hostname for release env validation" in errors


def test_release_env_preflight_rejects_local_domain_and_url_userinfo(
    tmp_path: Path,
) -> None:
    env_file = _write_release_env(
        tmp_path,
        {
            "APP_BASE_URL": "https://api.local",
            "WEB_BASE_URL": "https://user:pass@app.thinking.invalid",
        },
    )

    errors = validate_release_env(env_file)

    assert "APP_BASE_URL must use a public hostname for release env validation" in errors
    assert "WEB_BASE_URL must not include userinfo for release env validation" in errors


def test_release_env_preflight_rejects_fake_ip_push_allowlist(tmp_path: Path) -> None:
    env_file = _write_release_env(
        tmp_path,
        {"WEB_PUSH_ALLOW_FAKE_IP_HOSTS": "fcm.googleapis.com"},
    )

    errors = validate_release_env(env_file)

    assert "WEB_PUSH_ALLOW_FAKE_IP_HOSTS must be empty for release env validation" in errors


def test_release_env_preflight_rejects_short_release_secrets(tmp_path: Path) -> None:
    secret_values = {
        "POSTGRES_PASSWORD": "short-db-secret",
        "JWT_SECRET": "short-jwt-secret",
        "LANGGRAPH_AES_KEY": "short-langgraph-secret",
        "WEB_PUSH_VAPID_PRIVATE_KEY": "short-vapid-secret",
    }
    env_file = _write_release_env(tmp_path, secret_values)

    errors = validate_release_env(env_file)
    output = "\n".join(errors)

    assert "POSTGRES_PASSWORD is too short for release env validation" in errors
    assert "JWT_SECRET is too short for release env validation" in errors
    assert "LANGGRAPH_AES_KEY is too short for release env validation" in errors
    assert "WEB_PUSH_VAPID_PRIVATE_KEY is too short for release env validation" in errors
    for secret in secret_values.values():
        assert secret not in output


def test_release_env_preflight_output_does_not_expose_secret_values(
    tmp_path: Path,
    capsys,
) -> None:
    env_file = tmp_path / "env.production"
    secret_values = {
        "POSTGRES_PASSWORD": "prod-postgres-secret-should-not-print",
        "JWT_SECRET": "prod-jwt-secret-should-not-print",
        "LANGGRAPH_AES_KEY": "prod-langgraph-secret-should-not-print",
        "DASHSCOPE_API_KEY": "sk-prod-secret-should-not-print",
        "BOCHA_API_KEY": "bocha-secret-should-not-print",
        "WEB_PUSH_VAPID_PRIVATE_KEY": "vapid-private-secret-should-not-print",
    }
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=thinking",
                "POSTGRES_USER=thinking",
                f"POSTGRES_PASSWORD={secret_values['POSTGRES_PASSWORD']}",
                "APP_ENV=staging",
                "APP_BASE_URL=https://api.thinking.invalid",
                "WEB_BASE_URL=https://app.thinking.invalid",
                "TZ=Asia/Shanghai",
                f"JWT_SECRET={secret_values['JWT_SECRET']}",
                f"LANGGRAPH_AES_KEY={secret_values['LANGGRAPH_AES_KEY']}",
                "AI_PROVIDER=aliyun",
                "AI_PROVIDER_MODE=mock",
                f"DASHSCOPE_API_KEY={secret_values['DASHSCOPE_API_KEY']}",
                "DASHSCOPE_BASE_URL=https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_HTTP_BASE_URL=https://dashscope.aliyuncs.com/api/v1",
                "DASHSCOPE_WEBSOCKET_BASE_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference",
                "QWEN_DIALOG_MODEL=qwen-dialog-prod",
                "QWEN_QUESTION_MODEL=qwen-question-prod",
                "QWEN_REVIEW_MODEL=qwen-review-prod",
                "QWEN_VERIFY_MODEL=qwen-verify-prod",
                "QWEN_FALLBACK_MODEL=qwen-fallback-prod",
                "ALIYUN_ASR_MODEL=fun-asr",
                "ALIYUN_TTS_MODEL=cosyvoice-v3-flash",
                "ALIYUN_TTS_VOICE=longanyang",
                "ALIYUN_EMBEDDING_MODEL=text-embedding-v4",
                "ALIYUN_EMBEDDING_DIMENSIONS=1024",
                "SEARCH_PROVIDER=bocha",
                f"BOCHA_API_KEY={secret_values['BOCHA_API_KEY']}",
                "BOCHA_SEARCH_ENDPOINT=https://api.bochaai.com/v1/web-search",
                "WEB_PUSH_VAPID_PUBLIC_KEY=vapid-public-shaped-value",
                f"WEB_PUSH_VAPID_PRIVATE_KEY={secret_values['WEB_PUSH_VAPID_PRIVATE_KEY']}",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main([str(env_file)])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert exit_code == 1
    assert "APP_ENV must be production" in output
    assert "AI_PROVIDER_MODE must be aliyun" in output
    for secret in secret_values.values():
        assert secret not in output


def test_release_env_preflight_uses_target_file_not_process_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_PROVIDER_MODE", "aliyun")
    monkeypatch.setenv("SEARCH_PROVIDER", "bocha")

    env_file = tmp_path / "env.production"
    env_file.write_text(
        "\n".join(
            [
                "POSTGRES_DB=thinking",
                "POSTGRES_USER=thinking",
                "POSTGRES_PASSWORD=prod-postgres-password-32-chars-long",
                "APP_ENV=staging",
                "APP_BASE_URL=https://api.thinking.invalid",
                "WEB_BASE_URL=https://app.thinking.invalid",
                "TZ=Asia/Shanghai",
                "JWT_SECRET=prod-jwt-secret-32-chars-long-value",
                "LANGGRAPH_AES_KEY=prod-langgraph-aes-key-32-chars-long",
                "AI_PROVIDER=aliyun",
                "AI_PROVIDER_MODE=mock",
                "DASHSCOPE_API_KEY=sk-prod-shaped-value",
                "DASHSCOPE_BASE_URL=https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_HTTP_BASE_URL=https://dashscope.aliyuncs.com/api/v1",
                "DASHSCOPE_WEBSOCKET_BASE_URL=wss://dashscope.aliyuncs.com/api-ws/v1/inference",
                "QWEN_DIALOG_MODEL=qwen-dialog-prod",
                "QWEN_QUESTION_MODEL=qwen-question-prod",
                "QWEN_REVIEW_MODEL=qwen-review-prod",
                "QWEN_VERIFY_MODEL=qwen-verify-prod",
                "QWEN_FALLBACK_MODEL=qwen-fallback-prod",
                "ALIYUN_ASR_MODEL=fun-asr",
                "ALIYUN_TTS_MODEL=cosyvoice-v3-flash",
                "ALIYUN_TTS_VOICE=longanyang",
                "ALIYUN_EMBEDDING_MODEL=text-embedding-v4",
                "ALIYUN_EMBEDDING_DIMENSIONS=1024",
                "SEARCH_PROVIDER=mock",
                "BOCHA_API_KEY=bocha-prod-shaped-value",
                "BOCHA_SEARCH_ENDPOINT=https://api.bochaai.com/v1/web-search",
                "WEB_PUSH_VAPID_PUBLIC_KEY=vapid-public-shaped-value",
                "WEB_PUSH_VAPID_PRIVATE_KEY=vapid-private-shaped-value-32-chars",
            ]
        ),
        encoding="utf-8",
    )

    errors = validate_release_env(env_file)

    assert "APP_ENV must be production for release env validation" in errors
    assert "AI_PROVIDER_MODE must be aliyun for release env validation" in errors
    assert "SEARCH_PROVIDER must be bocha for release env validation" in errors
