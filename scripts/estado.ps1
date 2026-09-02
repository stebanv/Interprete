<#
    Interprete - estado del servicio.

    Responde una sola pregunta: esta arriba o no. Se puede correr desde
    cualquier PowerShell, sin tocar la ventana donde arranco start.ps1.

    Uso:
        .\scripts\estado.ps1              # una foto
        .\scripts\estado.ps1 -Vigilar     # se queda mirando, refresca cada 5 s
#>

param(
    [switch]$Vigilar
)

$root      = Split-Path -Parent $PSScriptRoot
$tokenFile = Join-Path $root ".token"
$tunnelLog = Join-Path $root "logs\tunnel.log"
$port      = 8777

function Get-Estado {
    $info = [ordered]@{
        Servidor = $false
        Modelos  = $false
        Tunel    = $false
        Url      = $null
        Pid      = $null
    }

    $proc = Get-Process python -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -like "*Interprete*" } |
            Select-Object -First 1
    if ($proc) {
        $info.Servidor = $true
        $info.Pid = $proc.Id
    }

    try {
        $res = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 3
        if ($res.ready) { $info.Modelos = $true }
    } catch {}

    $tunel = Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($tunel) {
        $info.Tunel = $true
        if (Test-Path $tunnelLog) {
            $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue |
                     Select-Object -Last 1
            if ($match -and (Test-Path $tokenFile)) {
                $token = (Get-Content $tokenFile -Raw).Trim()
                $info.Url = "$($match.Matches[0].Value)/?k=$token"
            }
        }
    }

    return $info
}

function Show-Estado {
    $e = Get-Estado

    $arriba = $e.Servidor -and $e.Modelos
    Write-Host ""
    if ($arriba -and $e.Tunel) {
        Write-Host "  ARRIBA  " -ForegroundColor Black -BackgroundColor Green -NoNewline
        Write-Host "  el servicio esta listo y alcanzable desde el portatil."
    }
    elseif ($arriba) {
        Write-Host "  PARCIAL " -ForegroundColor Black -BackgroundColor Yellow -NoNewline
        Write-Host "  el servidor corre, pero el tunel esta caido: el portatil no llega."
    }
    else {
        Write-Host "  ABAJO   " -ForegroundColor White -BackgroundColor DarkRed -NoNewline
        Write-Host "  el servicio no esta corriendo. Arrancalo con .\scripts\start.ps1"
    }
    Write-Host ""

    $marca = { param($ok) if ($ok) { "  [ok] " } else { "  [--] " } }
    $color = { param($ok) if ($ok) { "Green" } else { "DarkGray" } }

    Write-Host (& $marca $e.Servidor) -ForegroundColor (& $color $e.Servidor) -NoNewline
    if ($e.Servidor) { Write-Host "proceso del servidor (PID $($e.Pid))" }
    else { Write-Host "proceso del servidor" -ForegroundColor DarkGray }

    Write-Host (& $marca $e.Modelos) -ForegroundColor (& $color $e.Modelos) -NoNewline
    if ($e.Modelos) { Write-Host "Whisper y el traductor cargados en la GPU" }
    else { Write-Host "modelos cargados" -ForegroundColor DarkGray }

    Write-Host (& $marca $e.Tunel) -ForegroundColor (& $color $e.Tunel) -NoNewline
    if ($e.Tunel) { Write-Host "tunel de Cloudflare abierto" }
    else { Write-Host "tunel de Cloudflare" -ForegroundColor DarkGray }

    if ($e.Url) {
        Write-Host ""
        Write-Host "  URL para el portatil:" -ForegroundColor DarkGray
        Write-Host "  $($e.Url)" -ForegroundColor White
    }
    Write-Host ""
}

if ($Vigilar) {
    try {
        while ($true) {
            Clear-Host
            Write-Host "  Interprete - vigilando (Ctrl+C para salir)   $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor DarkGray
            Show-Estado
            Start-Sleep -Seconds 5
        }
    }
    finally {
        Write-Host "  Fin de la vigilancia." -ForegroundColor DarkGray
    }
}
else {
    Show-Estado
}
