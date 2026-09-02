<#
    Interprete - apagado explicito.

    Ctrl+C en la ventana de start.ps1 normalmente basta, pero si esa ventana se
    cierra de golpe (o se pierde), el servidor y el tunel quedan huerfanos: el
    tunel sigue publico y nadie se entera. Esto los mata por ruta, sin depender
    de quien los lanzo.
#>

$root = Split-Path -Parent $PSScriptRoot
$muertos = 0

$servidores = Get-Process python -ErrorAction SilentlyContinue |
              Where-Object { $_.Path -and $_.Path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) }
foreach ($proc in $servidores) {
    Write-Host "  deteniendo servidor (PID $($proc.Id))" -ForegroundColor DarkGray
    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop; $muertos++ } catch {}
}

$tuneles = Get-Process cloudflared -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) }
foreach ($proc in $tuneles) {
    Write-Host "  cerrando tunel (PID $($proc.Id))" -ForegroundColor DarkGray
    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop; $muertos++ } catch {}
}

Start-Sleep -Milliseconds 600

# Verificacion de verdad: que el puerto ya no responda.
$sigueVivo = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8777/healthz" -TimeoutSec 2 | Out-Null
    $sigueVivo = $true
} catch {}

Write-Host ""
if ($sigueVivo) {
    Write-Host "  ATENCION: el puerto 8777 sigue respondiendo." -ForegroundColor Red
    Write-Host "  Algo quedo vivo. Revisa con: .\scripts\estado.ps1" -ForegroundColor Red
}
elseif ($muertos -eq 0) {
    Write-Host "  No habia nada corriendo." -ForegroundColor DarkGray
}
else {
    Write-Host "  Servicio detenido ($muertos proceso(s)). El tunel ya no es alcanzable." -ForegroundColor Green
}
Write-Host ""
