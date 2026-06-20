$ErrorActionPreference = "Stop"

$ExpectedUv = "0.11.23"
$ExpectedPython = "3.12.13"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "未找到 uv。请先安装 uv $ExpectedUv。"
}

$ActualUv = ((uv --version) -split " ")[1]
if ($ActualUv -ne $ExpectedUv) {
    throw "uv 版本不一致：期望 $ExpectedUv，实际 $ActualUv。"
}

uv python install $ExpectedPython
uv python pin $ExpectedPython
uv lock
uv sync --all-groups
uv run python scripts/verify_dependency_policy.py

Write-Host "Python 依赖环境初始化完成。请将 uv.lock 提交到 Git。"
