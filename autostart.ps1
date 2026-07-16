# Start the voice-loop daemon automatically at login (hidden window).
#   ./autostart.ps1 on     # install the Startup shortcut
#   ./autostart.ps1 off    # remove it
param(
    [ValidateSet("on", "off")]
    [string]$Action = "on"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "voice-loop.lnk"

if ($Action -eq "off") {
    if (Test-Path $lnk) {
        Remove-Item $lnk
        Write-Host "Removed autostart shortcut." -ForegroundColor Green
    } else {
        Write-Host "Autostart was not enabled."
    }
    exit 0
}

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\start.ps1`""
$s.WorkingDirectory = $root
$s.Description = "voice-loop daemon (voice interface for Claude Code)"
$s.Save()
Write-Host "voice-loop will start at login (tray icon = it's running)." -ForegroundColor Green
Write-Host "Disable with: ./autostart.ps1 off"
