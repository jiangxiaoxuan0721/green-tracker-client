# Uninstall green-tracker-client (Windows)
# Removes the app and shortcuts only; config and collected data are kept.
#
# NOTE: this file is intentionally kept pure ASCII. Windows PowerShell 5.1
#       reads BOM-less .ps1 files using the system ANSI codepage, so any
#       non-ASCII text would be mis-decoded (and may even break parsing).
#
#   .\uninstall.ps1
#   .\uninstall.ps1 -Purge        also delete the config directory
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\GreenTrackerClient",
    [string]$ConfigDir  = "$env:APPDATA\GreenTrackerClient",
    [switch]$Purge
)

$AppName = 'green-tracker-client'

function Remove-IfExists($path) {
    if (Test-Path $path) {
        Remove-Item -Path $path -Recurse -Force
        Write-Host "==> Removed: $path" -ForegroundColor Yellow
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
    Write-Host "==> Config kept: $ConfigDir (use -Purge to delete it)" -ForegroundColor Yellow
}
Write-Host "==> Collected data kept: $env:USERPROFILE\green_tracker_data" -ForegroundColor Yellow
Write-Host "Uninstall complete." -ForegroundColor Green
