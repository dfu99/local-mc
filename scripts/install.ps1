#Requires -Version 5.1
<#
.SYNOPSIS
    Installs local-mc on Windows.

.DESCRIPTION
    Creates a virtual environment under %LOCALAPPDATA%\lmc-venv, pip-installs
    the local-mc package from the current directory, and writes a lmc.cmd
    shim to %LOCALAPPDATA%\lmc-venv\Scripts\ so that `lmc` resolves from any
    terminal once that directory is on PATH.

.PARAMETER Reinstall
    Wipe %LOCALAPPDATA%\lmc-venv and start fresh.

.EXAMPLE
    # From the repo root in PowerShell:
    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\install.ps1

.EXAMPLE
    # Force a clean reinstall:
    .\scripts\install.ps1 -Reinstall
#>
param(
    [switch]$Reinstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── helpers ─────────────────────────────────────────────────────────────────

function Write-Step([string]$msg) {
    Write-Host "  >> $msg" -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host "  OK $msg" -ForegroundColor Green
}
function Write-Fail([string]$msg) {
    Write-Host "FAIL $msg" -ForegroundColor Red
    exit 1
}

# ── locate Python ────────────────────────────────────────────────────────────

Write-Step "Locating Python 3.10+..."

$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $python = $candidate
                Write-Ok "Found $ver at '$candidate'"
                break
            }
        }
    } catch { }
}

if (-not $python) {
    Write-Fail "Python 3.10+ not found. Install from https://python.org and re-run."
}

# ── set up venv ──────────────────────────────────────────────────────────────

$venvDir = Join-Path $env:LOCALAPPDATA 'lmc-venv'
$scriptsDir = Join-Path $venvDir 'Scripts'

if ($Reinstall -and (Test-Path $venvDir)) {
    Write-Step "Removing existing venv at $venvDir..."
    Remove-Item -Recurse -Force $venvDir
    Write-Ok "Removed."
}

if (-not (Test-Path $venvDir)) {
    Write-Step "Creating venv at $venvDir..."
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "venv creation failed." }
    Write-Ok "Venv created."
} else {
    Write-Ok "Venv already exists at $venvDir (use -Reinstall to rebuild)."
}

$pip = Join-Path $scriptsDir 'pip.exe'
$pythonExe = Join-Path $scriptsDir 'python.exe'

if (-not (Test-Path $pip)) { Write-Fail "pip not found inside venv at $pip" }

# ── ensure UTF-8 output in the venv Python ───────────────────────────────────
# Windows cmd.exe defaults to cp1252; force UTF-8 so log output is legible.
# We bake this into the shim rather than mutating system settings.

# ── install local-mc ─────────────────────────────────────────────────────────

$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $repoRoot 'pyproject.toml'))) {
    Write-Fail "pyproject.toml not found in $repoRoot — run this script from inside the repo."
}

Write-Step "Installing local-mc from $repoRoot..."
& $pip install --upgrade --quiet pip
& $pip install --quiet "$repoRoot"
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install failed." }
Write-Ok "local-mc installed."

# ── write lmc.cmd shim ───────────────────────────────────────────────────────
# The venv's Scripts\ already contains lmc.exe after install, but that only
# works if the venv is activated or Scripts\ is on PATH.  We write a .cmd
# shim that hardcodes the absolute path so `lmc` works from any terminal
# without activation.

$shimPath = Join-Path $scriptsDir 'lmc.cmd'

# The shim sets PYTHONIOENCODING so UTF-8 output works on any Windows console.
$shimContent = @"
@echo off
setlocal
set PYTHONIOENCODING=utf-8
"$pythonExe" -m lmc.cli %*
endlocal
"@

Set-Content -Path $shimPath -Value $shimContent -Encoding ASCII
Write-Ok "Shim written to $shimPath"

# ── PATH advisory ────────────────────────────────────────────────────────────

$userPath = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
$alreadyOnPath = ($userPath -split ';') -contains $scriptsDir

if (-not $alreadyOnPath) {
    Write-Host ""
    Write-Host "  ACTION REQUIRED: add the following directory to your PATH:" -ForegroundColor Yellow
    Write-Host "    $scriptsDir" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Run this once in an elevated PowerShell to do it permanently:" -ForegroundColor Yellow
    Write-Host "    [Environment]::SetEnvironmentVariable('PATH', `$env:PATH + ';$scriptsDir', 'User')" -ForegroundColor Yellow
    Write-Host ""

    $addNow = Read-Host "  Add to user PATH now? [y/N]"
    if ($addNow -match '^[Yy]') {
        $newPath = $userPath + ';' + $scriptsDir
        [System.Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
        $env:PATH = $env:PATH + ';' + $scriptsDir
        Write-Ok "PATH updated. Open a new terminal for it to take effect."
    } else {
        Write-Host "  Skipped. Add manually when ready." -ForegroundColor DarkYellow
    }
} else {
    Write-Ok "$scriptsDir already on PATH."
}

# ── smoke test ───────────────────────────────────────────────────────────────

Write-Step "Verifying installation..."
$lmcExe = Join-Path $scriptsDir 'lmc.exe'
try {
    & $lmcExe --help 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "lmc --help returned 0."
    } else {
        Write-Host "  WARN: lmc --help returned $LASTEXITCODE (may still work)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WARN: could not run $lmcExe — PATH not yet updated? Try in a new terminal." -ForegroundColor Yellow
}

# ── next steps ───────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  local-mc installed." -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    lmc init"
Write-Host "    lmc add myproject C:\path\to\project"
Write-Host "    lmc serve"
Write-Host ""
Write-Host "  Data lives at:"
Write-Host "    Config : $env:APPDATA\lmc\config\"
Write-Host "    History: $env:LOCALAPPDATA\lmc\data\"
Write-Host ""
