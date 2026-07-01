from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ARTIFACT_PATHS = (
    Path("infra/docker-compose.prod.yml"),
    Path("infra/nginx/default.conf"),
    Path("infra/nginx/Dockerfile"),
    Path("services/backend/pyproject.toml"),
    Path("apps/web/package.json"),
)
PRIVATE_RELEASE_PATHS = (
    Path("infra/env.production"),
    Path("infra/certs"),
    Path("backups"),
    Path("secrets"),
)


def build_release_manifest(*, repo_root: Path = REPO_ROOT, image_tag: str) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    image_tag = _normalize_image_tag(image_tag)
    git_commit = _git_output(repo_root, "rev-parse", "HEAD")
    git_short_commit = _git_output(repo_root, "rev-parse", "--short=12", "HEAD")
    worktree_status = _git_output(repo_root, "status", "--porcelain")
    alembic_heads = _alembic_heads(repo_root / "services" / "backend" / "alembic" / "versions")

    return {
        "schema_version": 1,
        "image_tag": image_tag,
        "git_commit": git_commit,
        "git_short_commit": git_short_commit,
        "worktree_status": "dirty" if worktree_status else "clean",
        "alembic_heads": alembic_heads,
        "artifact_hashes": _release_artifact_hashes(repo_root),
    }


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _alembic_heads(versions_dir: Path) -> list[str]:
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for migration_file in sorted(versions_dir.glob("*.py")):
        revision, down_revision = _read_alembic_revision(migration_file)
        revisions.add(revision)
        down_revisions.update(down_revision)

    heads = sorted(revisions - down_revisions)
    if not heads:
        raise RuntimeError(f"no Alembic heads found in {versions_dir}")
    return heads


def _read_alembic_revision(migration_file: Path) -> tuple[str, set[str]]:
    tree = ast.parse(migration_file.read_text(encoding="utf-8"), filename=str(migration_file))
    revision: str | None = None
    down_revision: set[str] = set()

    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                revision_value = ast.literal_eval(statement.value)
                if isinstance(revision_value, str):
                    revision = revision_value
            elif target.id == "down_revision":
                down_revision.update(_revision_values(statement.value))

    if revision is None:
        raise RuntimeError(f"{migration_file} does not define revision")
    return revision, down_revision


def _revision_values(value: ast.AST) -> set[str]:
    evaluated = ast.literal_eval(value)
    if evaluated is None:
        return set()
    if isinstance(evaluated, str):
        return {evaluated}
    if isinstance(evaluated, (tuple, list)):
        return {item for item in evaluated if isinstance(item, str)}
    raise RuntimeError(f"unsupported down_revision value: {evaluated!r}")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_artifact_hashes(repo_root: Path) -> dict[str, str]:
    return {
        artifact_path.as_posix(): _sha256_file(repo_root / artifact_path)
        for artifact_path in RELEASE_ARTIFACT_PATHS
    }


def _normalize_image_tag(image_tag: str) -> str:
    normalized = image_tag.strip()
    if not normalized:
        raise ValueError("image tag must not be blank")
    if any(character.isspace() for character in normalized):
        raise ValueError("image tag must not contain whitespace")
    return normalized


def _validate_output_path(*, repo_root: Path, output_path: Path) -> Path:
    resolved_repo_root = repo_root.resolve()
    resolved_output_path = output_path.resolve()
    if resolved_output_path.suffix.lower() != ".json":
        raise ValueError("--output must end with .json")

    release_artifacts = {
        (resolved_repo_root / artifact_path).resolve() for artifact_path in RELEASE_ARTIFACT_PATHS
    }
    if resolved_output_path in release_artifacts:
        raise ValueError("--output must not overwrite release source or configuration artifacts")

    for private_path in PRIVATE_RELEASE_PATHS:
        resolved_private_path = (resolved_repo_root / private_path).resolve()
        if resolved_output_path == resolved_private_path or resolved_output_path.is_relative_to(
            resolved_private_path
        ):
            raise ValueError("--output must not be inside private release artifact paths")

    return resolved_output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a non-secret release manifest for deployment signoff.",
    )
    parser.add_argument(
        "--image-tag",
        required=True,
        help="Image tag intended for this release, for example thinking-coach:20260625-abcdef.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root. Defaults to the current checked-out project.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the manifest JSON for release evidence.",
    )
    args = parser.parse_args(argv)

    try:
        manifest = build_release_manifest(repo_root=args.repo_root, image_tag=args.image_tag)
        output_path = (
            _validate_output_path(repo_root=args.repo_root, output_path=args.output)
            if args.output is not None
            else None
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(manifest_json, encoding="utf-8")
    print(manifest_json, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
