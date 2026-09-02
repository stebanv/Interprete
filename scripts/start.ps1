<#
    Interprete - arranque completo.

    Levanta el servidor de transcripcion y un tunel de Cloudflare, y te imprime
    la URL HTTPS que debes abrir en el portatil.

    Uso:
        .\scripts\start.ps1           # servidor + tunel publico
        .\scripts\start.ps1 -Local    # solo local, sin tunel (para probar aqui)
#>

param(
    [switch]$Local
)

$ErrorActionPreference = "Stop"

$root        = Split-Path -Parent $PSScriptRoot
$python      = Join-Path $root ".venv\Scripts\python.exe"
$cloudflared = Join-Path $root "bin\cloudflared.exe"
$logDir      = Join-Path $root "logs"
$serverLog   = Join-Path $logDir "server.log"
$tunnelLog   = Join-Path $logDir "tunnel.log"
$tokenFile   = Join-Path $root ".token"
$port        = 8777

if (-not (Test-Path $python)) {
    Write-Host "No existe el entorno virtual. Corre primero: .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
Remove-Item $serverLog, $tunnelLog -ErrorAction SilentlyContinue

$serverProc = $null
$tunnelProc = $null

# --- Atar los hijos a la vida de esta ventana ------------------------------
# Ctrl+C corre el bloque finally, pero cerrar la ventana con la X mata este
# PowerShell sin ejecutar nada: el servidor y el tunel quedaban huerfanos, con
# la URL publica viva y nadie enterado.
#
# Un Job Object con KILL_ON_JOB_CLOSE resuelve eso a nivel de sistema
# operativo: cuando muere este proceso se cierra el handle del job y Windows
# termina a todos sus miembros, muera como muera el padre.
$codigoJob = @"
using System;
using System.Runtime.InteropServices;

public static class InterpreteJob
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

    [DllImport("kernel32.dll")]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits
    {
        public BasicLimits BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    private const int ExtendedLimitInformation = 9;
    private const uint KillOnJobClose = 0x2000;

    private static IntPtr job = IntPtr.Zero;

    public static bool Crear()
    {
        job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) { return false; }

        ExtendedLimits limites = new ExtendedLimits();
        limites.BasicLimitInformation.LimitFlags = KillOnJobClose;

        int tamano = Marshal.SizeOf(typeof(ExtendedLimits));
        IntPtr buffer = Marshal.AllocHGlobal(tamano);
        try
        {
            Marshal.StructureToPtr(limites, buffer, false);
            return SetInformationJobObject(job, ExtendedLimitInformation, buffer, (uint)tamano);
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    public static bool Adoptar(IntPtr proceso)
    {
        if (job == IntPtr.Zero) { return false; }
        return AssignProcessToJobObject(job, proceso);
    }
}
"@

$jobActivo = $false
try {
    if (-not ("InterpreteJob" -as [type])) { Add-Type -TypeDefinition $codigoJob -Language CSharp }
    $jobActivo = [InterpreteJob]::Crear()
} catch {
    $jobActivo = $false
}

function Adoptar-Proceso($proc) {
    if ($script:jobActivo -and $proc -ne $null) {
        try { [InterpreteJob]::Adoptar($proc.Handle) | Out-Null } catch {}
    }
}

function Stop-All {
    foreach ($proc in @($script:tunnelProc, $script:serverProc)) {
        if ($proc -ne $null -and -not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
        }
    }
}

try {
    $Host.UI.RawUI.WindowTitle = "Interprete - cargando modelos..."
    Write-Host ""
    Write-Host "  Interprete" -ForegroundColor Cyan
    Write-Host "  ----------" -ForegroundColor DarkGray
    Write-Host "  Cargando Whisper large-v3 en la GPU (la primera vez tarda ~30 s)..."

    $serverProc = Start-Process -FilePath $python `
        -ArgumentList "-m", "server.main" `
        -WorkingDirectory $root `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError  "$serverLog.err" `
        -WindowStyle Hidden -PassThru
    Adoptar-Proceso $serverProc

    # Espera a que los modelos esten cargados
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        if ($serverProc.HasExited) {
            Write-Host "  El servidor murio al arrancar. Log:" -ForegroundColor Red
            Get-Content "$serverLog.err" -Tail 30 -ErrorAction SilentlyContinue
            exit 1
        }
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2
            if ($res.ready) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 700
    }
    if (-not $ready) {
        Write-Host "  El servidor no quedo listo a tiempo. Revisa $serverLog.err" -ForegroundColor Red
        Stop-All
        exit 1
    }

    $token = (Get-Content $tokenFile -Raw).Trim()
    Write-Host "  Modelos listos." -ForegroundColor Green
    $Host.UI.RawUI.WindowTitle = "Interprete - ARRIBA (no cierres esta ventana)"

    if ($Local) {
        $url = "http://127.0.0.1:$port/?k=$token"
    }
    else {
        Write-Host "  Abriendo el tunel de Cloudflare..."
        $tunnelProc = Start-Process -FilePath $cloudflared `
            -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$port" `
            -RedirectStandardOutput "$tunnelLog.out" `
            -RedirectStandardError  $tunnelLog `
            -WindowStyle Hidden -PassThru
        Adoptar-Proceso $tunnelProc

        $public = $null
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 700
            if (Test-Path $tunnelLog) {
                $match = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue |
                         Select-Object -First 1
                if ($match) { $public = $match.Matches[0].Value; break }
            }
        }
        if (-not $public) {
            Write-Host "  No se pudo abrir el tunel. Revisa $tunnelLog" -ForegroundColor Red
            Stop-All
            exit 1
        }
        $url = "$public/?k=$token"
    }

    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor DarkGray
    Write-Host "   Abre esta URL en el portatil (Chrome o Edge):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   $url" -ForegroundColor White
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor DarkGray
    try { Set-Clipboard -Value $url; Write-Host "   (copiada al portapapeles)" -ForegroundColor DarkGray } catch {}
    Write-Host ""
    if ($jobActivo) {
        Write-Host "   Al cerrar esta ventana el servicio se apaga solo." -ForegroundColor DarkGray
    }
    else {
        Write-Host "   OJO: no se pudo atar el servicio a esta ventana." -ForegroundColor Yellow
        Write-Host "   Si la cierras con la X, apagalo con .\scripts\detener.ps1" -ForegroundColor Yellow
    }
    Write-Host "   Mientras esta ventana siga abierta, el servicio esta arriba." -ForegroundColor DarkGray
    Write-Host "   Ctrl+C para apagarlo. Para consultarlo desde otra ventana:" -ForegroundColor DarkGray
    Write-Host "   .\scripts\estado.ps1" -ForegroundColor DarkGray
    Write-Host ""

    # Muestra el log del servidor en vivo hasta que se corte
    Get-Content "$serverLog.err" -Wait -Tail 5
}
finally {
    Write-Host ""
    Write-Host "  Apagando..." -ForegroundColor DarkGray
    $Host.UI.RawUI.WindowTitle = "Interprete - apagado"
    Stop-All
    Write-Host "  Servicio detenido. El portatil vera 'SIN CONEXION'." -ForegroundColor DarkGray
}
