#!/usr/bin/env bash
set -euo pipefail

EXPECTED_UV="0.11.23"
EXPECTED_PYTHON="3.12.13"

command -v uv >/dev/null 2>&1 || { echo "未找到 uv ${EXPECTED_UV}" >&2; exit 1; }
ACTUAL_UV="$(uv --version | awk '{print $2}')"
[[ "${ACTUAL_UV}" == "${EXPECTED_UV}" ]] || {
  echo "uv 版本不一致：期望 ${EXPECTED_UV}，实际 ${ACTUAL_UV}" >&2
  exit 1
}

uv python install "${EXPECTED_PYTHON}"
uv python pin "${EXPECTED_PYTHON}"
uv lock
uv sync --all-groups
uv run python scripts/verify_dependency_policy.py

echo "Python 依赖环境初始化完成。请将 uv.lock 提交到 Git。"
