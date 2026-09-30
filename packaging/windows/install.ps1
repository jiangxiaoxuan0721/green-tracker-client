# Install green-tracker-client (Windows, source + venv layout)
#
# NOTE: this file is intentionally kept pure ASCII. Windows PowerShell 5.1
#       reads BOM-less .ps1 files using the system ANSI codepage, so any
#       non-ASCII text would be mis-decoded (and may even break parsing).
#
# Usage (PowerShell):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install.ps1
#   .\install.ps1 -InstallDir D:\Apps\GreenTracker -ConfigDir D:\Config\GreenTracker
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GreenTrackerClient",
    [string]$ConfigDir  = "$env:APPDATA\GreenTrackerClient",
    [string]$SourceDir  = "",
    [switch]$NoConfig,
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
$AppName = 'green-tracker-client'

if (-not $SourceDir) {
    # packaging\windows\install.ps1 -> repo root
    $SourceDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
if (-not (Test-Path (Join-Path $SourceDir 'main.py'))) {
    throw "main.py not found under $SourceDir - pass -SourceDir to point at the source tree"
}

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Green }

# ---------------------------------------------------------------- Python
$python = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $args = @()
    if ($candidate -eq 'py') { $args = @('-3') }
    try {
        $ver = & $cmd @args -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch { continue }
    if ($ver -and ([version]$ver -ge [version]'3.10')) {
        $python = @($cmd.Source) + $args
        break
    }
}
if (-not $python) { throw "Python 3.10+ not found - install it first (https://www.python.org/downloads/)" }
Write-Step "Using Python: $($python -join ' ')"

# ---------------------------------------------------------------- app files
Write-Step "Installing app to: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$exclude = @('.git', 'tests', 'doc', 'dist', 'build', '.pytest_cache',
             '.venv', '__pycache__', '.env')
Get-ChildItem -Path $SourceDir -Force | Where-Object { $exclude -notcontains $_.Name } |
    ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
    }

# ---------------------------------------------------------------- virtualenv
Write-Step "Creating virtual environment and installing dependencies"
& $python[0] @($python[1..($python.Length - 1)]) -m venv (Join-Path $InstallDir '.venv')
$venvPython = Join-Path $InstallDir '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r (Join-Path $InstallDir 'requirements.txt') -q

# ---------------------------------------------------------------- launcher
$launcher = Join-Path $InstallDir "$AppName.cmd"
@"
@echo off
setlocal
set "APP_DIR=$InstallDir"
if not defined GREEN_TRACKER_CONFIG_DIR set "GREEN_TRACKER_CONFIG_DIR=$ConfigDir"
if not exist "%GREEN_TRACKER_CONFIG_DIR%\.env" (
    if exist "%APP_DIR%\packaging\common\prepare_config.py" (
        python "%APP_DIR%\packaging\common\prepare_config.py" "%GREEN_TRACKER_CONFIG_DIR%"
    )
)
if not exist "%GREEN_TRACKER_CONFIG_DIR%" mkdir "%GREEN_TRACKER_CONFIG_DIR%"
cd /d "%GREEN_TRACKER_CONFIG_DIR%"
"%APP_DIR%\.venv\Scripts\python.exe" "%APP_DIR%\main.py" %*
"@ | Set-Content -Path $launcher -Encoding ASCII
Write-Step "Launcher: $launcher"

# ---------------------------------------------------------------- config
if (-not $NoConfig) {
    Write-Step "Writing config template: $ConfigDir"
    & $python[0] @($python[1..($python.Length - 1)]) `
        (Join-Path $InstallDir 'packaging\common\prepare_config.py') $ConfigDir
}

# ---------------------------------------------------------------- shortcuts
if (-not $NoShortcut) {
    $ws = New-Object -ComObject WScript.Shell
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Green Tracker Client'
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

    foreach ($dir in @($startMenu, $ws.SpecialFolders('Desktop'))) {
        if (-not $dir) { continue }
        $shortcut = $ws.CreateShortcut((Join-Path $dir 'Green Tracker Client.lnk'))
        $shortcut.TargetPath = $launcher
        $shortcut.WorkingDirectory = $ConfigDir
        $shortcut.Description = 'Environment and agriculture data acquisition / remote device control client'
        $shortcut.Save()
    }
    Write-Step "Start menu and desktop shortcuts created"
}

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "  App dir:     $InstallDir"
Write-Host "  Launcher:    $launcher"
Write-Host "  Config file: $ConfigDir\.env"
Write-Host "  Cmd policy:  $ConfigDir\command_policy.json"
Write-Host "Fill in .env, then start from the Start menu. Reinstall/upgrade keeps your config."
