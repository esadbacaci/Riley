# =============================================================================
#  Riley - tek seferlik kurulum
#  Kullanim:  powershell -ExecutionPolicy Bypass -File scripts\kurulum.ps1
# =============================================================================
[CmdletBinding()]
param(
    [string]$Model = "qwen3:8b",
    [switch]$AtlaModel,        # buyuk model indirmesini atla
    [switch]$CpuModu           # NVIDIA karti yoksa CUDA paketlerini kurma
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Adim($n, $toplam, $mesaj) {
    Write-Host ""
    Write-Host "[$n/$toplam] $mesaj" -ForegroundColor Cyan
}
function Tamam($mesaj) { Write-Host "      OK  $mesaj" -ForegroundColor Green }
function Uyari($mesaj) { Write-Host "      !   $mesaj" -ForegroundColor Yellow }
function Hata($mesaj)  { Write-Host "      X   $mesaj" -ForegroundColor Red }

Write-Host ""
Write-Host "  ____  _ _            " -ForegroundColor Cyan
Write-Host " |  _ \(_) | ___ _   _ " -ForegroundColor Cyan
Write-Host " | |_) | | |/ _ \ | | |" -ForegroundColor Cyan
Write-Host " |  _ <| | |  __/ |_| |" -ForegroundColor Cyan
Write-Host " |_| \_\_|_|\___|\__, |" -ForegroundColor Cyan
Write-Host "                 |___/  yerel sesli asistan" -ForegroundColor DarkCyan
Write-Host ""

$TOPLAM = 7

# --- 1. Python -------------------------------------------------------------
Adim 1 $TOPLAM "Python denetleniyor"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Hata "Python bulunamadi. https://www.python.org/downloads/ adresinden 3.10+ kurun."
    Write-Host "      Kurulumda 'Add Python to PATH' secenegini isaretleyin."
    exit 1
}
$sur = (& python --version) -replace "Python ", ""
$parcalar = $sur.Split(".")
if ([int]$parcalar[0] -lt 3 -or ([int]$parcalar[0] -eq 3 -and [int]$parcalar[1] -lt 9)) {
    Hata "Python $sur cok eski. 3.10 veya ustu gerekli."
    exit 1
}
Tamam "Python $sur"

# --- 2. Node.js ------------------------------------------------------------
Adim 2 $TOPLAM "Node.js denetleniyor (arayuz penceresi icin)"
if (Get-Command node -ErrorAction SilentlyContinue) {
    Tamam "Node $((& node --version))"
} else {
    Uyari "Node.js yok. Masaustu penceresi yerine tarayici kullanilacak."
    Uyari "Kurmak icin: https://nodejs.org  (LTS surumu)"
}

# --- 3. Ollama -------------------------------------------------------------
Adim 3 $TOPLAM "Ollama denetleniyor (dil modeli motoru)"
$ollamaYol = "$env:LOCALAPPDATA\Programs\Ollama"
if (Test-Path $ollamaYol) { $env:Path += ";$ollamaYol" }

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Uyari "Ollama kurulu degil, winget ile kuruluyor..."
    try {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements --disable-interactivity
        $env:Path += ";$ollamaYol"
        Tamam "Ollama kuruldu"
    } catch {
        Hata "Ollama kurulamadi. Elle kurun: https://ollama.com/download"
        exit 1
    }
} else {
    Tamam "Ollama zaten kurulu"
}

# Servisin ayakta oldugundan emin ol
try {
    Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
    Tamam "Ollama servisi calisiyor"
} catch {
    Uyari "Ollama servisi baslatiliyor..."
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# --- 4. Dil modeli ---------------------------------------------------------
Adim 4 $TOPLAM "Dil modeli: $Model"
if ($AtlaModel) {
    Uyari "Atlandi (-AtlaModel verildi). Sonra: ollama pull $Model"
} else {
    $kurulu = & ollama list 2>$null | Select-String -SimpleMatch $Model
    if ($kurulu) {
        Tamam "$Model zaten indirilmis"
    } else {
        Write-Host "      Indiriliyor (~5 GB, internete gore 10-30 dakika)..."
        & ollama pull $Model
        if ($LASTEXITCODE -eq 0) { Tamam "$Model hazir" } else { Hata "Model indirilemedi" }
    }
}

# --- 5. Python paketleri ---------------------------------------------------
Adim 5 $TOPLAM "Python paketleri kuruluyor"
& python -m pip install --quiet --disable-pip-version-check --upgrade pip
& python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Hata "Paket kurulumu basarisiz"; exit 1 }
Tamam "Temel paketler kuruldu"

# NVIDIA karti varsa CUDA kutuphaneleri (Whisper'i GPU'da calistirir)
if (-not $CpuModu) {
    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidia) {
        Write-Host "      NVIDIA karti bulundu, CUDA kutuphaneleri kuruluyor..."
        & python -m pip install --quiet --disable-pip-version-check nvidia-cublas-cu12 nvidia-cudnn-cu12
        if ($LASTEXITCODE -eq 0) {
            Tamam "CUDA kutuphaneleri kuruldu (ses tanima GPU'da calisacak)"
        } else {
            Uyari "CUDA kutuphaneleri kurulamadi; ses tanima islemcide calisir"
        }
    } else {
        Uyari "NVIDIA karti yok; ses tanima islemcide calisacak (daha yavas)"
    }
}

# --- 6. Piper sesi ---------------------------------------------------------
Adim 6 $TOPLAM "Turkce ses motoru (Piper)"
& powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\fetch_models.ps1"
if (Test-Path "$root\tools\piper\piper.exe") { Tamam "Piper hazir" } else { Uyari "Piper kurulamadi, Windows sesi kullanilacak" }

# --- 7. Arayuz bagimliliklari ---------------------------------------------
Adim 7 $TOPLAM "Masaustu penceresi (Electron)"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    if (Test-Path "$root\node_modules\electron") {
        Tamam "Electron zaten kurulu"
    } else {
        Write-Host "      npm install calisiyor..."
        & npm install --no-audit --no-fund --silent
        if ($LASTEXITCODE -eq 0) { Tamam "Electron kuruldu" } else { Uyari "Electron kurulamadi" }
    }
} else {
    Uyari "npm yok, atlandi"
}

Write-Host ""
Write-Host "  Kurulum tamamlandi." -ForegroundColor Green
Write-Host ""
Write-Host "  Baslatmak icin:" -ForegroundColor White
Write-Host "     .\baslat.ps1              " -NoNewline -ForegroundColor Cyan
Write-Host "(masaustu penceresi)"
Write-Host "     .\baslat.ps1 -Tarayici    " -NoNewline -ForegroundColor Cyan
Write-Host "(tarayicida ac)"
Write-Host ""
Write-Host "  Ilk acilista ses tanima modeli (~0.5 GB) indirilecek." -ForegroundColor DarkGray
Write-Host ""
