<#
.SYNOPSIS
  Install local-mc on Windows without requiring pipx.

.DESCRIPTION
  Creates an isolated venv under %LOCALAPPDATA%\lmc-venv, installs the
  package from the current directory (`pip install .`), and drops a
  `lmc.cmd` shim in %LOCALAPPDATA%\Microsoft\WindowsApps\ (already on
  PATH for current-user installs of recent Windows).

  Why this script: the audit (tasks/audit-2026-05-05.md, P1) noted that
  pipx may not be present on locked-down corporate work machines.
  System Python is usually fine; we just need a venv + a shim.

.PARAMETER VenvDir
  Override the venv location. Default: %LOCALAPPDATA%\lmc-venv

.PARAMETER ShimDir
  Override the shim location. Default:
  %LOCALAPPDATA%\Microsoft\WindowsApps (on PATH by default since
  Windows 10 1809).

.PARAMETER Python
  Override the system Python. Default: `py` (Windows Python launcher),
  falls back to `python` if `py` is not present.

.EXAMPLE
  PS> .\scripts\install.ps1
  PS> lmc init
  PS> lmc add work C:\projects\work
  PS> lmc serve

.NOTES
  Tested manually against the Windows install path. The CI matrix in
  .github/workflows/test.yml exercises `pip install -e .[dev]` on
  windows-latest, which is the same install model.
#>
[CmdletBinding()]
param(
  [string]$VenvDir = (Join-Path $env:LOCALAPPDATA "lmc-venv"),
  [string]$ShimDir = (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
  param([string]$Override)
  if ($Override) { return $Override }
  $candidates = @("py", "python", "python3")
  foreach ($c in $candidates) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
  }
  throw "No Python launcher found. Install Python 3.10+ from https://www.python.org/downloads/windows/ and re-run."
}

function Test-PythonVersion {
  param([string]$Exe)
  $version = & $Exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  $major, $minor = $version.Split(".")
  if (([int]$major -lt 3) -or (([int]$major -eq 3) -and ([int]$minor -lt 10))) {
    throw "Python $version found, but local-mc requires Python >= 3.10."
  }
  return $version
}

# Repo root is the parent dir of scripts/
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Write-Host "local-mc installer" -ForegroundColor Cyan
Write-Host "  repo:    $RepoRoot"
Write-Host "  venv:    $VenvDir"
Write-Host "  shim in: $ShimDir"

$PythonExe = Resolve-Python -Override $Python
$Version = Test-PythonVersion -Exe $PythonExe
Write-Host "  python:  $PythonExe (v$Version)"

# 1. Create venv
if (-not (Test-Path $VenvDir)) {
  Write-Host "`nCreating venv..." -ForegroundColor Yellow
  & $PythonExe -m venv $VenvDir
} else {
  Write-Host "`nReusing existing venv at $VenvDir." -ForegroundColor Yellow
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  throw "venv created but $VenvPython is missing — installer can't continue."
}

# 2. Install package
Write-Host "`nInstalling package (pip install .)..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip wheel
& $VenvPython -m pip install $RepoRoot.Path

# 3. Drop shim — a .cmd file is the simplest reliable Windows shim.
if (-not (Test-Path $ShimDir)) {
  New-Item -ItemType Directory -Path $ShimDir | Out-Null
}
$ShimPath = Join-Path $ShimDir "lmc.cmd"
$LmcEntryPoint = Join-Path $VenvDir "Scripts\lmc.exe"
if (-not (Test-Path $LmcEntryPoint)) {
  throw "Expected entry point at $LmcEntryPoint after install — pip install may have failed silently."
}

@"
@echo off
"$LmcEntryPoint" %*
"@ | Set-Content -Path $ShimPath -Encoding ASCII

Write-Host "`nInstalled lmc.cmd at $ShimPath" -ForegroundColor Green

# 4. Verify the shim resolves on PATH
$Resolved = Get-Command lmc -ErrorAction SilentlyContinue
if ($Resolved) {
  Write-Host "  PATH lookup: $($Resolved.Source)" -ForegroundColor Green
} else {
  Write-Host "  WARNING: 'lmc' did not resolve on PATH. You may need to log out/in or add $ShimDir to PATH manually." -ForegroundColor DarkYellow
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  lmc init"
Write-Host "  lmc add <name> <path-to-project>"
Write-Host "  lmc serve"
