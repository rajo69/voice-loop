# Starts the voice-loop daemon: input (hotkey -> dictation) + output (readback).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No .venv found. Run ./install.ps1 first." -ForegroundColor Red
    exit 1
}
& $py (Join-Path $root "voiced.py")
