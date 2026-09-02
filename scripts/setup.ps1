<#
    Interprete - instalacion desde cero.

    Solo hay que correrlo una vez (o si se borra .venv). Deja listos el entorno
    virtual, los modelos descargados y cloudflared.
#>

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$venv   = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

# Python 3.12: torch y CTranslate2 todavia no publican ruedas para 3.14.
$base = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $base)) {
    $found = & py -0p 2>$null | Select-String -Pattern "3\.12" | Select-Object -First 1
    if ($found) { $base = ($found.Line -split "\s{2,}")[-1].Trim() }
}
if (-not (Test-Path $base)) {
    Write-Host "No encontre Python 3.12. Instalalo desde python.org y vuelve a correr esto." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $python)) {
    Write-Host "Creando entorno virtual con $base ..." -ForegroundColor Cyan
    & $base -m venv $venv
}

Write-Host "Actualizando pip..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip --quiet

Write-Host "Instalando torch con CUDA 12.8 (Blackwell / RTX 50xx)... esto pesa ~3 GB" -ForegroundColor Cyan
& $python -m pip install torch --index-url https://download.pytorch.org/whl/cu128

Write-Host "Instalando el resto de dependencias..." -ForegroundColor Cyan
& $python -m pip install -r (Join-Path $root "requirements.txt")

$bin = Join-Path $root "bin"
if (-not (Test-Path $bin)) { New-Item -ItemType Directory -Path $bin | Out-Null }
$cloudflared = Join-Path $bin "cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Write-Host "Descargando cloudflared..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cloudflared
}

Write-Host "Descargando modelos (Whisper large-v3 ~3 GB + traductor ~300 MB)..." -ForegroundColor Cyan
& $python -c @"
import sys
sys.path.insert(0, r'$root')
from server.stt import WhisperEngine
from server.mt import Translator
WhisperEngine(); Translator()
print('modelos listos')
"@

Write-Host ""
Write-Host "Listo. Ahora corre:  .\scripts\start.ps1" -ForegroundColor Green
