<#
.SYNOPSIS
    Manual Deployment Script for Signal Producer on Windows PowerShell.
    Matches GitHub Actions (.github/workflows/deploy.yml).

.DESCRIPTION
    Syncs repository files to GCP VM (excluding .venv, .env, sessions, git, logs) and executes remote deploy.sh.
    Optionally manages or skips the local Docker Kafka container.

.PARAMETER VmHost
    Override Host IP/DNS for Producer VM.

.PARAMETER VmUser
    Override SSH User.

.PARAMETER SshKey
    Path to private SSH key.

.PARAMETER SkipKafka
    Switch to skip running ensure-kafka.sh (useful if Kafka is hosted on OCI or dedicated VM).

.EXAMPLE
    .\deploy\manual_deploy.ps1
    .\deploy\manual_deploy.ps1 -SkipKafka
    .\deploy\manual_deploy.ps1 -VmHost "34.93.x.x" -VmUser "pawanbudati"
#>

[CmdletBinding()]
param(
    [string]$VmHost = $null,
    [string]$VmUser = $null,
    [string]$SshKey = $null,
    [int]$Port = 0,
    [string]$DeployPath = $null,
    [switch]$SkipKafka
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = (Resolve-Path "$scriptDir\..").Path

# Helper to load simple KEY=VALUE file
function Load-EnvFile($path) {
    if (Test-Path $path) {
        Write-Host "Loading configuration from $path" -ForegroundColor Cyan
        Get-Content $path | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
                $idx = $line.IndexOf('=')
                $key = $line.Substring(0, $idx).Trim()
                $val = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
                if (-not [string]::IsNullOrEmpty($key)) {
                    [Environment]::SetEnvironmentVariable($key, $val, 'Process')
                }
            }
        }
    }
}

# Check for config files
$envCandidates = @(
    "$rootDir\.env.deploy",
    "$scriptDir\.env.deploy",
    "$rootDir\.deploy.env",
    "$scriptDir\deploy.env"
)
foreach ($f in $envCandidates) {
    if (Test-Path $f) {
        Load-EnvFile $f
        break
    }
}

$hostName = if ($VmHost) { $VmHost } elseif ($env:GCP_VM_HOST) { $env:GCP_VM_HOST } else { $env:VM_HOST }
$userName = if ($VmUser) { $VmUser } elseif ($env:GCP_VM_USER) { $env:GCP_VM_USER } else { $env:VM_USER }
$keyPath  = if ($SshKey) { $SshKey } elseif ($env:GCP_VM_SSH_KEY) { $env:GCP_VM_SSH_KEY } else { $env:SSH_KEY_PATH }
$portNum  = if ($Port -gt 0) { $Port } elseif ($env:GCP_VM_SSH_PORT) { [int]$env:GCP_VM_SSH_PORT } elseif ($env:VM_PORT) { [int]$env:VM_PORT } else { 22 }
$remoteDir = if ($DeployPath) { $DeployPath } elseif ($env:PRODUCER_DEPLOY_PATH) { $env:PRODUCER_DEPLOY_PATH } else { $env:DEPLOY_PATH }
$advHost  = if ($env:KAFKA_ADVERTISED_HOST) { $env:KAFKA_ADVERTISED_HOST } else { "" }

if (-not $hostName -or -not $userName) {
    throw "Host and User must be configured in .env.deploy or passed via parameters."
}

if (-not $remoteDir -or $remoteDir -eq '/home/') {
    $remoteDir = "/home/$userName/apps/neo-tel-signal-producer"
}

$shouldSkipKafka = $SkipKafka.IsPresent -or ($env:SKIP_KAFKA -eq "true")

Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host ">>> Deploying Producer to ${userName}@${hostName}:${portNum}" -ForegroundColor Green
Write-Host ">>> Remote Path: $remoteDir" -ForegroundColor Green
Write-Host ">>> Skip Kafka Container: $shouldSkipKafka" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green

$sshArgs = @("-p", "$portNum", "-o", "StrictHostKeyChecking=accept-new")
if ($keyPath -and (Test-Path $keyPath)) {
    $sshArgs += @("-i", $keyPath)
}

# 1. Ensure target directory exists on remote VM
& ssh $sshArgs "${userName}@${hostName}" "mkdir -p '$remoteDir'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create remote directory '$remoteDir' on $hostName."
}

# 2. Sync files using tar stream or rsync
$hasRsync = (Get-Command rsync -ErrorAction SilentlyContinue)
if ($hasRsync) {
    Write-Host ">>> Syncing files via rsync..." -ForegroundColor Yellow
    $rsyncSsh = "ssh -p $portNum -o StrictHostKeyChecking=accept-new"
    if ($keyPath -and (Test-Path $keyPath)) { $rsyncSsh += " -i '$keyPath'" }

    & rsync -az --delete `
        --exclude='.git/' `
        --exclude='.env' --include='.env.example' --exclude='.env.*' `
        --exclude='.venv/' --exclude='venv/' `
        --exclude='*.session' --exclude='*.session-*' `
        --exclude='logs/' --exclude='*.log' `
        --exclude='__pycache__/' `
        -e $rsyncSsh `
        "$rootDir/" "${userName}@${hostName}:${remoteDir}/"
} else {
    Write-Host ">>> Syncing files via tar over SSH stream..." -ForegroundColor Yellow
    $excludes = @(
        "--exclude=.git",
        "--exclude=.env",
        "--exclude=.env.*",
        "--exclude=.venv",
        "--exclude=venv",
        "--exclude=*.session",
        "--exclude=*.session-*",
        "--exclude=logs",
        "--exclude=*.log",
        "--exclude=__pycache__"
    )
    
    $tarCmd = "tar -C `"$rootDir`" $($excludes -join ' ') -czf - ."
    $sshCmd = "ssh $($sshArgs -join ' ') ${userName}@${hostName} `"tar -xzf - -C '$remoteDir'`""
    cmd.exe /c "$tarCmd | $sshCmd"
}

if ($LASTEXITCODE -ne 0) {
    throw "File sync to $hostName failed."
}

# 3. Ensure Kafka container if not skipped
if (-not $shouldSkipKafka) {
    Write-Host ">>> Ensuring Kafka container is running on $hostName..." -ForegroundColor Yellow
    & ssh $sshArgs "${userName}@${hostName}" "DEPLOY_PATH='$remoteDir' KAFKA_ADVERTISED_HOST='$advHost' bash '$remoteDir/deploy/ensure-kafka.sh'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to ensure Kafka container on $hostName."
    }
} else {
    Write-Host ">>> Skipping Kafka container management (SkipKafka is true)." -ForegroundColor Cyan
}

# 4. Execute remote deploy.sh
Write-Host ">>> Executing remote deploy.sh on $hostName..." -ForegroundColor Yellow
& ssh $sshArgs "${userName}@${hostName}" "DEPLOY_PATH='$remoteDir' bash '$remoteDir/deploy/deploy.sh'"
if ($LASTEXITCODE -ne 0) {
    throw "Remote deploy.sh on $hostName reported an error."
}

Write-Host ">>> Producer deployment succeeded!" -ForegroundColor Green
