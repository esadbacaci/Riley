# =============================================================================
#  Riley'yi baslatir.
#    .\baslat.ps1              -> masaustu penceresi (Electron)
#    .\baslat.ps1 -Tarayici    -> sadece sunucu, tarayicida ac
#    .\baslat.ps1 -Sessiz      -> mikrofon kapali (yalnizca yazarak)
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Tarayici,
    [switch]$Sessiz,
    [int]$Port = 8756
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:RILEY_PORT = "$Port"
if ($Sessiz) { $env:RILEY_NO_MIC = "1" }

# Ollama ayakta mi?
$ollamaYol = "$env:LOCALAPPDATA\Programs\Ollama"
if (Test-Path $ollamaYol) { $env:Path += ";$ollamaYol" }
try {
    Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "Ollama baslatiliyor..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
}

# Onceki oturumdan kalan sunucuyu kapat
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*backend*main.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

New-Item -ItemType Directory -Force -Path "$root\data\logs" | Out-Null

if ($Tarayici -or -not (Test-Path "$root\node_modules\electron")) {
    if (-not $Tarayici) {
        Write-Host "Electron kurulu degil, tarayici kipine geciliyor." -ForegroundColor Yellow
        Write-Host "Kurmak icin: npm install" -ForegroundColor DarkGray
    }
    Write-Host "Riley baslatiliyor -> http://127.0.0.1:$Port" -ForegroundColor Cyan

    Start-Process python -ArgumentList "backend/main.py" -WorkingDirectory $root `
        -RedirectStandardOutput "$root\data\logs\server.log" `
        -RedirectStandardError  "$root\data\logs\server.err.log" -WindowStyle Hidden

    $bitis = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $bitis) {
        try {
            Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
            break
        } catch { Start-Sleep -Seconds 2 }
    }
    Start-Process "http://127.0.0.1:$Port"
    Write-Host "Acildi. Kayitlar: data\logs\server.log" -ForegroundColor DarkGray
} else {
    # Electron hem sunucuyu baslatir hem pencereyi acar
    & npm start
}
