# 卸载 green-tracker-client —— 只删应用与快捷方式，保留配置与采集数据
#
#   .\uninstall.ps1
#   .\uninstall.ps1 -Purge       连配置目录一起删除
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GreenTrackerClient",
    [string]$ConfigDir  = "$env:APPDATA\GreenTrackerClient",
    [switch]$Purge
)

$AppName = 'green-tracker-client'

function Remove-IfExists($path) {
    if (Test-Path $path) {
        Remove-Item -Path $path -Recurse -Force
        Write-Host "==> 已删除: $path" -ForegroundColor Yellow
    }
}

Remove-IfExists $InstallDir

$ws = New-Object -ComObject WScript.Shell
Remove-IfExists (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Green Tracker Client')
foreach ($dir in @($ws.SpecialFolders('Desktop'))) {
    if ($dir) { Remove-IfExists (Join-Path $dir 'Green Tracker Client.lnk') }
}

if ($Purge) {
    Remove-IfExists $ConfigDir
} else {
    Write-Host "==> 已保留配置: $ConfigDir（如需清除请加 -Purge）" -ForegroundColor Yellow
}
Write-Host "==> 已保留采集数据: $env:USERPROFILE\green_tracker_data" -ForegroundColor Yellow
Write-Host "卸载完成。" -ForegroundColor Green
