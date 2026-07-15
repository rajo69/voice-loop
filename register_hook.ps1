# Merges the voice-loop `Stop` hook into your user-level Claude Code settings
# (~/.claude/settings.json) so Claude reads its answers aloud in every session.
# Safe & idempotent: preserves existing settings and won't add the hook twice.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$hookScript = Join-Path $root "hooks\stop_hook.py"

# Prefer the venv python if present, else system python.
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$command = "`"$py`" `"$hookScript`""

$settingsDir = Join-Path $env:USERPROFILE ".claude"
$settingsPath = Join-Path $settingsDir "settings.json"
if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Path $settingsDir | Out-Null }

if (Test-Path $settingsPath) {
    $json = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    $json = [PSCustomObject]@{}
}

# Ensure .hooks.Stop exists as an array.
if (-not ($json.PSObject.Properties.Name -contains "hooks")) {
    $json | Add-Member -MemberType NoteProperty -Name "hooks" -Value ([PSCustomObject]@{})
}
if (-not ($json.hooks.PSObject.Properties.Name -contains "Stop")) {
    $json.hooks | Add-Member -MemberType NoteProperty -Name "Stop" -Value @()
}

# De-dupe: skip if a hook already points at stop_hook.py
$already = $false
foreach ($group in @($json.hooks.Stop)) {
    foreach ($h in @($group.hooks)) {
        if ($h.command -and $h.command -match "stop_hook\.py") { $already = $true }
    }
}

if ($already) {
    Write-Host "Stop hook already registered. Nothing to do." -ForegroundColor Yellow
} else {
    $entry = [PSCustomObject]@{
        matcher = ""
        hooks   = @(
            [PSCustomObject]@{ type = "command"; command = $command }
        )
    }
    $json.hooks.Stop = @($json.hooks.Stop) + $entry
    ($json | ConvertTo-Json -Depth 20) | Set-Content -Path $settingsPath -Encoding utf8
    Write-Host "Registered Stop hook in $settingsPath" -ForegroundColor Green
    Write-Host "Command: $command"
}

Write-Host ""
Write-Host "Restart Claude Code (or run /hooks) for it to take effect."
