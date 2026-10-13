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
# name -> url, minimum plausible size in bytes (guards against a truncated
# download being silently accepted)
$files = @(
    @{ Name = "kokoro-v1.0.onnx"; Url = "$base/kokoro-v1.0.onnx"; MinBytes = 200MB }
    @{ Name = "voices-v1.0.bin";  Url = "$base/voices-v1.0.bin";  MinBytes = 10MB }
)
foreach ($f in $files) {
    $dest = Join-Path $models $f.Name
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -ge $f.MinBytes)) {
        Write-Host "  $($f.Name) already present, skipping."
        continue
    }
    # curl.exe (built into Windows 10+) resumes partial downloads (-C -).
    Write-Host "  Downloading $($f.Name) (resumable; the model is ~300MB)..."
    & curl.exe -L --retry 3 --retry-delay 2 -C - -o $dest $f.Url
    if ((-not (Test-Path $dest)) -or ((Get-Item $dest).Length -lt $f.MinBytes)) {
        Write-Host "  $($f.Name) is partial, downloading it again..." -ForegroundColor Yellow
        Remove-Item $dest -ErrorAction SilentlyContinue
        & curl.exe -L --retry 3 --retry-delay 2 -o $dest $f.Url
    }
    if ((-not (Test-Path $dest)) -or ((Get-Item $dest).Length -lt $f.MinBytes)) {
        Write-Host "  FAILED to download $($f.Name). Re-run install.ps1 (it resumes)." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Register the readback hook:   ./register_hook.ps1"
Write-Host "  2. Start the daemon:             ./start.ps1"
