# 一键安装 green-tracker-client（Windows，源码 + venv 形态）
#
# 用法（PowerShell，建议先执行 Set-ExecutionPolicy -Scope Process Bypass）：
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
    # packaging\windows\install.ps1 -> 仓库根
    $SourceDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
if (-not (Test-Path (Join-Path $SourceDir 'main.py'))) {
    throw "未在 $SourceDir 找到 main.py，请用 -SourceDir 指定源码目录"
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
if (-not $python) { throw "未找到 Python 3.10 及以上，请先安装（https://www.python.org/downloads/）" }
Write-Step "使用 Python: $($python -join ' ')"

# ---------------------------------------------------------------- 应用文件
Write-Step "安装应用到: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$exclude = @('.git', 'tests', 'doc', 'dist', 'build', '.pytest_cache',
             '.venv', '__pycache__', '.env')
Get-ChildItem -Path $SourceDir -Force | Where-Object { $exclude -notcontains $_.Name } |
    ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
    }

# ---------------------------------------------------------------- 虚拟环境
Write-Step "创建虚拟环境并安装依赖"
& $python[0] @($python[1..($python.Length - 1)]) -m venv (Join-Path $InstallDir '.venv')
$venvPython = Join-Path $InstallDir '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r (Join-Path $InstallDir 'requirements.txt') -q

# ---------------------------------------------------------------- 启动器
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
Write-Step "启动器: $launcher"

# ---------------------------------------------------------------- 配置模板
if (-not $NoConfig) {
    Write-Step "生成配置模板: $ConfigDir"
    & $python[0] @($python[1..($python.Length - 1)]) `
        (Join-Path $InstallDir 'packaging\common\prepare_config.py') $ConfigDir
}

# ---------------------------------------------------------------- 快捷方式
if (-not $NoShortcut) {
    $ws = New-Object -ComObject WScript.Shell
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Green Tracker Client'
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

    foreach ($dir in @($startMenu, $ws.SpecialFolders('Desktop'))) {
        if (-not $dir) { continue }
        $shortcut = $ws.CreateShortcut((Join-Path $dir 'Green Tracker Client.lnk'))
        $shortcut.TargetPath = $launcher
        $shortcut.WorkingDirectory = $ConfigDir
        $shortcut.Description = '环境/农业数据采集与设备远程管控客户端'
        $shortcut.Save()
    }
    Write-Step "已创建开始菜单与桌面快捷方式"
}

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "  应用目录: $InstallDir"
Write-Host "  启动脚本: $launcher"
Write-Host "  配置文件: $ConfigDir\.env"
Write-Host "  指令策略: $ConfigDir\command_policy.json"
Write-Host "请填写 .env 后从开始菜单启动；重装或升级不会覆盖已改过的配置。"
