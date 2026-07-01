[CmdletBinding()]
param(
    [switch]$LocalDeps,
    [switch]$SkipDockerBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到 $Name。$InstallHint"
    }
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [string]$WorkingDirectory = ""
    )

    $display = "$FilePath $($ArgumentList -join ' ')"
    Write-Host "==> $display"

    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
        try {
            & $FilePath @ArgumentList
        }
        finally {
            Pop-Location
        }
    }
    else {
        & $FilePath @ArgumentList
    }

    if ($LASTEXITCODE -ne 0) {
        throw "命令失败，退出码 $LASTEXITCODE：$display"
    }
}

function Assert-DockerCompose {
    Assert-Command "docker" "请先安装并启动 Docker Desktop。"
    Invoke-External "docker" @("compose", "version")
}

function Install-LocalDependencies {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $backendDir = Join-Path $RepoRoot "services/backend"
    $packageJson = Get-Content -Raw -Encoding UTF8 (Join-Path $RepoRoot "package.json") |
        ConvertFrom-Json
    $expectedPnpm = (($packageJson.packageManager -split "@")[-1]).Trim()
    $expectedPython = (Get-Content -Raw -Encoding UTF8 (Join-Path $backendDir ".python-version")).Trim()
    $expectedUv = "0.11.23"

    Assert-Command "uv" "请先安装 uv $expectedUv。"
    $actualUv = ((& uv --version) -split " ")[1]
    if ($actualUv -ne $expectedUv) {
        throw "uv 版本不一致：期望 $expectedUv，实际 $actualUv。"
    }

    Assert-Command "corepack" "请先安装 Node.js 22，并确认 corepack 可用。"

    $uvDefaultIndexWasSet = -not [string]::IsNullOrWhiteSpace($env:UV_DEFAULT_INDEX)
    $previousUvDefaultIndex = $env:UV_DEFAULT_INDEX
    if (-not $uvDefaultIndexWasSet) {
        $env:UV_DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple"
    }

    try {
        Invoke-External "uv" @("python", "install", $expectedPython) $backendDir
        Invoke-External "uv" @("lock", "--check") $backendDir
        Invoke-External "uv" @("sync", "--locked", "--all-groups") $backendDir
        Invoke-External "uv" @("run", "python", "scripts/verify_dependency_policy.py") $backendDir
    }
    finally {
        if ($uvDefaultIndexWasSet) {
            $env:UV_DEFAULT_INDEX = $previousUvDefaultIndex
        }
        else {
            Remove-Item Env:\UV_DEFAULT_INDEX -ErrorAction SilentlyContinue
        }
    }

    Invoke-External "corepack" @("enable") $RepoRoot
    Invoke-External "corepack" @("prepare", "pnpm@$expectedPnpm", "--activate") $RepoRoot
    Invoke-External "pnpm" @("install", "--frozen-lockfile") $RepoRoot
}

$repoRoot = Get-RepoRoot
$composeFile = Join-Path $repoRoot "infra/docker-compose.yml"

Write-Host "项目根目录：$repoRoot"

if (-not $SkipDockerBuild) {
    Assert-DockerCompose
    Invoke-External "docker" @("compose", "-f", $composeFile, "build") $repoRoot
}

if ($LocalDeps) {
    Install-LocalDependencies $repoRoot
}

Write-Host ""
Write-Host "项目环境初始化完成。"
Write-Host "启动开发环境：.\scripts\start-dev.ps1"

if (-not $LocalDeps) {
    Write-Host "如需同步本机 uv/pnpm 依赖：.\scripts\setup-env.ps1 -LocalDeps -SkipDockerBuild"
}
