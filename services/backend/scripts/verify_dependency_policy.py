from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PYTHON_VERSION_FILE = ROOT / ".python-version"
LOCK_FILE = ROOT / "uv.lock"
EXPECTED_PROJECT_VERSION = "1.0"
EXPECTED_PYTHON = "3.12.13"
EXPECTED_UV = "0.11.23"

REQUIRED_DIRECT = {
    "langchain-core": "1.4.8",
    "langgraph": "1.2.6",
    "langgraph-checkpoint-postgres": "3.1.0",
}

FORBIDDEN_DIRECT = {
    "langchain",
    "langchain-openai",
}

FORBIDDEN = {
    "torch",
    "tensorflow",
    "transformers",
    "sentence-transformers",
    "faster-whisper",
    "openai-whisper",
    "whisper",
    "funasr",
    "modelscope",
    "vllm",
    "llama-cpp-python",
    "onnxruntime-gpu",
}


def canonical_name(requirement: str) -> str:
    head = re.split(r"[<>=!~;\s\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", head).lower()


def dependency_lists(data: dict) -> list[str]:
    result = list(data["project"].get("dependencies", []))
    for values in data.get("dependency-groups", {}).values():
        result.extend(values)
    return result


def main() -> int:
    errors: list[str] = []
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    if data["project"].get("version") != EXPECTED_PROJECT_VERSION:
        errors.append(
            f"project version must be {EXPECTED_PROJECT_VERSION}; actual: "
            f"{data['project'].get('version')}"
        )

    if data["project"].get("requires-python") != ">=3.12,<3.13":
        errors.append("requires-python must be >=3.12,<3.13")

    pinned_python = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    if pinned_python != EXPECTED_PYTHON:
        errors.append(f".python-version must be {EXPECTED_PYTHON}; actual: {pinned_python}")

    dependencies = dependency_lists(data)
    direct_by_name = {canonical_name(requirement): requirement for requirement in dependencies}

    for requirement in dependencies:
        name = canonical_name(requirement)
        if "==" not in requirement:
            errors.append(f"direct dependency is not pinned exactly: {requirement}")
        if name in FORBIDDEN:
            errors.append(f"forbidden local model/GPU dependency found: {requirement}")
        if name in FORBIDDEN_DIRECT:
            errors.append(
                f"full LangChain package is not allowed in P0: {requirement}; "
                "create an ADR before changing this boundary"
            )

    for name, version in REQUIRED_DIRECT.items():
        requirement = direct_by_name.get(name)
        if requirement is None:
            errors.append(f"required direct dependency is missing: {name}=={version}")
        elif f"=={version}" not in requirement:
            errors.append(f"{name} must be pinned to {version}; actual: {requirement}")

    if LOCK_FILE.exists():
        lock_data = tomllib.loads(LOCK_FILE.read_text(encoding="utf-8"))
        locked_versions = {
            package.get("name"): package.get("version") for package in lock_data.get("package", [])
        }
        if locked_versions.get("langchain-core") != REQUIRED_DIRECT["langchain-core"]:
            errors.append(
                "uv.lock langchain-core must be "
                f"{REQUIRED_DIRECT['langchain-core']}; actual: "
                f"{locked_versions.get('langchain-core')}"
            )
        for forbidden_name in FORBIDDEN:
            if forbidden_name in locked_versions:
                errors.append(f"uv.lock contains forbidden dependency: {forbidden_name}")
        for forbidden_name in FORBIDDEN_DIRECT:
            if forbidden_name in locked_versions:
                errors.append(
                    f"uv.lock contains unapproved high-level dependency: {forbidden_name}"
                )

    if sys.version_info[:2] != (3, 12):
        errors.append(
            "current Python is "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; "
            "project requires Python 3.12.x"
        )

    try:
        output = subprocess.check_output(["uv", "--version"], text=True).strip()
        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if not match or match.group(1) != EXPECTED_UV:
            errors.append(f"uv must be {EXPECTED_UV}; actual output: {output}")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        errors.append(f"failed to detect uv: {exc}")

    if errors:
        print("Dependency policy verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Dependency policy verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
