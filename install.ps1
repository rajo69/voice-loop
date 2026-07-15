# Sets up the local virtual environment, installs dependencies, and downloads
# the STT + Kokoro TTS models. Run from this folder:  ./install.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

Write-Host "== voice-loop installer ==" -ForegroundColor Cyan

# 1. venv
if (-not (Test-Path "$root\.venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv "$root\.venv"
} else {
    Write-Host ".venv already exists, reusing."
}
$py = "$root\.venv\Scripts\python.exe"

# 2. dependencies
Write-Host "Upgrading pip..."
& $py -m pip install --upgrade pip --quiet
Write-Host "Installing requirements..."
& $py -m pip install -r "$root\requirements.txt"

# 3. STT model (faster-whisper) cache
Write-Host "Pre-downloading the speech-to-text model (one-time)..."
& $py -c "from common import load_config; from faster_whisper import WhisperModel; c=load_config()['stt']; WhisperModel(c['model'], device='cpu', compute_type=c['compute_type']); print('stt model cached')"

# 4. Kokoro TTS model files
$models = Join-Path $root "models"
if (-not (Test-Path $models)) { New-Item -ItemType Directory -Path $models | Out-Null }
$base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
$files = @{
    "kokoro-v1.0.onnx" = "$base/kokoro-v1.0.onnx"
    "voices-v1.0.bin"  = "$base/voices-v1.0.bin"
}
foreach ($name in $files.Keys) {
    $dest = Join-Path $models $name
    if (Test-Path $dest) {
        Write-Host "  $name already present, skipping."
    } else {
        Write-Host "  Downloading $name (this is the big one, ~300MB for the model)..."
        Invoke-WebRequest -Uri $files[$name] -OutFile $dest
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Register the readback hook:   ./register_hook.ps1"
Write-Host "  2. Start the daemon:             ./start.ps1"
