[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$SkipHealthCheck
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

function Assert-DockerDaemon {
    Write-Host "==> docker info --format {{.ServerVersion}}"
    & docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker daemon 不可用。请启动 Docker Desktop，等待 Docker Engine running；如果当前使用 Windows containers，请切换到 Linux containers 后重试。"
    }
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Name 已就绪：$Url"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name 在 $TimeoutSeconds 秒内未就绪：$Url"
}

$repoRoot = Get-RepoRoot
$composeFile = Join-Path $repoRoot "infra/docker-compose.yml"

Assert-Command "docker" "请先安装并启动 Docker Desktop。"
Invoke-External "docker" @("compose", "version")
Assert-DockerDaemon

if ($Build) {
    Invoke-External "docker" @("compose", "-f", $composeFile, "build") $repoRoot
}

Invoke-External "docker" @("compose", "-f", $composeFile, "up", "-d", "postgres") $repoRoot
Invoke-External "docker" @("compose", "-f", $composeFile, "run", "--rm", "api", "uv", "run", "alembic", "upgrade", "head") $repoRoot
Invoke-External "docker" @("compose", "-f", $composeFile, "run", "--rm", "api", "uv", "run", "python", "scripts/setup_checkpointer.py") $repoRoot
Invoke-External "docker" @("compose", "-f", $composeFile, "up", "-d", "api", "worker", "scheduler", "web") $repoRoot
Invoke-External "docker" @("compose", "-f", $composeFile, "ps") $repoRoot

if (-not $SkipHealthCheck) {
    Wait-Http "API" "http://localhost:8000/api/v1/health"
    Wait-Http "Web" "http://localhost:5173"
}

Write-Host ""
Write-Host "开发环境已启动。"
Write-Host "前端：http://localhost:5173"
Write-Host "后端：http://localhost:8000/api/v1/health"
Write-Host "API 文档：http://localhost:8000/docs"
Write-Host ""
Write-Host "首次需要管理员账号时运行："
Write-Host "docker compose -f infra/docker-compose.yml run --rm api uv run python -m app.scripts.create_admin --nickname admin"
