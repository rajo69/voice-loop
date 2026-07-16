# Stops the running voice-loop daemon. Tries a graceful socket shutdown first,
# then force-kills by port if needed. Run from any terminal:  ./stop.ps1
$port = 8765

# 1. graceful: ask the daemon to shut itself down (with its auth token)
try {
    $tokenFile = Join-Path $env:USERPROFILE ".voiceloop_token"
    $token = if (Test-Path $tokenFile) { (Get-Content $tokenFile -Raw).Trim() } else { "" }
    $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $port)
    $stream = $client.GetStream()
    $bytes = [Text.Encoding]::UTF8.GetBytes(('{"cmd":"shutdown","token":"' + $token + '"}'))
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close(); $client.Close()
    Start-Sleep -Milliseconds 700
} catch {}

# 2. force: kill whatever still holds the port
$c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($c) {
    $procId = $c.OwningProcess | Select-Object -First 1
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
}

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Could not stop the daemon on port $port." -ForegroundColor Red
} else {
    Write-Host "voice-loop daemon stopped." -ForegroundColor Green
}
