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
            f"项目版本必须为 {EXPECTED_PROJECT_VERSION}，实际为 "
            f"{data['project'].get('version')}"
        )

    if data["project"].get("requires-python") != ">=3.12,<3.13":
        errors.append("requires-python 必须为 >=3.12,<3.13")

    pinned_python = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    if pinned_python != EXPECTED_PYTHON:
        errors.append(f".python-version 应为 {EXPECTED_PYTHON}，实际为 {pinned_python}")

    dependencies = dependency_lists(data)
    direct_by_name = {canonical_name(requirement): requirement for requirement in dependencies}

    for requirement in dependencies:
        name = canonical_name(requirement)
        if "==" not in requirement:
            errors.append(f"直接依赖未使用精确版本：{requirement}")
        if name in FORBIDDEN:
            errors.append(f"发现禁止的本地模型/GPU依赖：{requirement}")
        if name in FORBIDDEN_DIRECT:
            errors.append(
                f"当前架构不直接引入完整 LangChain 高层包：{requirement}；"
                "如确需使用，必须先建立 ADR 并更新 SPEC/依赖策略"
            )

    for name, version in REQUIRED_DIRECT.items():
        requirement = direct_by_name.get(name)
        if requirement is None:
            errors.append(f"缺少必需直接依赖：{name}=={version}")
        elif f"=={version}" not in requirement:
            errors.append(f"{name} 必须固定为 {version}，实际为：{requirement}")

    if LOCK_FILE.exists():
        lock_data = tomllib.loads(LOCK_FILE.read_text(encoding="utf-8"))
        locked_versions = {
            package.get("name"): package.get("version")
            for package in lock_data.get("package", [])
        }
        if locked_versions.get("langchain-core") != REQUIRED_DIRECT["langchain-core"]:
            errors.append(
                "锁文件中的 langchain-core 必须为 "
                f"{REQUIRED_DIRECT['langchain-core']}，实际为 "
                f"{locked_versions.get('langchain-core')}"
            )
        for forbidden_name in FORBIDDEN_DIRECT:
            if forbidden_name in locked_versions:
                errors.append(f"uv.lock 中发现未经批准的高层依赖：{forbidden_name}")

    if sys.version_info[:2] != (3, 12):
        errors.append(
            f"当前 Python 为 {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}，"
            "项目要求 Python 3.12.x"
        )

    try:
        output = subprocess.check_output(["uv", "--version"], text=True).strip()
        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if not match or match.group(1) != EXPECTED_UV:
            errors.append(f"uv 应为 {EXPECTED_UV}，实际输出为：{output}")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        errors.append(f"无法检测 uv：{exc}")

    if errors:
        print("依赖策略校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print("依赖策略校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
