# Piper TTS motorunu ve Turkce ses modelini indirir.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $root "tools\piper"
$voiceDir = Join-Path $root "models\piper"
$tmp = Join-Path $env:TEMP "riley_dl"

New-Item -ItemType Directory -Force -Path $toolsDir, $voiceDir, $tmp | Out-Null
$ProgressPreference = "SilentlyContinue"

# --- 1. Piper çalıştırılabilir dosyasi ---
$piperExe = Join-Path $toolsDir "piper.exe"
if (Test-Path $piperExe) {
    Write-Host "[1/3] Piper zaten kurulu, atlaniyor."
} else {
    Write-Host "[1/3] Piper indiriliyor..."
    $zip = Join-Path $tmp "piper_windows.zip"
    $url = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    # Arsiv içeriği tek bir "piper" klasörü altinda geliyor
    $inner = Join-Path $tmp "piper"
    if (Test-Path $inner) {
        Copy-Item -Path (Join-Path $inner "*") -Destination $toolsDir -Recurse -Force
    } else {
        Copy-Item -Path (Join-Path $tmp "*.exe"), (Join-Path $tmp "*.dll") -Destination $toolsDir -Force
    }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Host "      -> $piperExe"
}

# --- 2. Turkce sesler ---
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR"
$voices = @(
    @{ name = "tr_TR-fahrettin-medium"; path = "fahrettin/medium" },
    @{ name = "tr_TR-dfki-medium";      path = "dfki/medium" }
)

$step = 2
foreach ($v in $voices) {
    Write-Host "[$step/3] Ses modeli: $($v.name)"
    foreach ($ext in @(".onnx", ".onnx.json")) {
        $dest = Join-Path $voiceDir ($v.name + $ext)
        if (Test-Path $dest) { continue }
        $url = "$base/$($v.path)/$($v.name)$ext" + "?download=true"
        try {
            Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        } catch {
            Write-Warning "      $($v.name)$ext indirilemedi: $($_.Exception.Message)"
            Remove-Item $dest -Force -ErrorAction SilentlyContinue
        }
    }
    $step++
}

Write-Host ""
Write-Host "Tamamlandi. Dosyalar:"
Get-ChildItem $toolsDir -Filter "piper.exe" | ForEach-Object { "  " + $_.FullName }
Get-ChildItem $voiceDir -Filter "*.onnx" | ForEach-Object { "  " + $_.Name + "  (" + [math]::Round($_.Length/1MB,1) + " MB)" }
