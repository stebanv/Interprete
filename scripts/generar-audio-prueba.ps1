<#
    Interprete - genera el audio de prueba.

    Los WAV no van al repositorio (pesan y se regeneran en segundos). Esto los
    reconstruye con las voces de Windows, en el formato que espera probar.py:
    16 kHz, mono, 16 bits.

    Necesita una voz en ingles instalada (Microsoft Zira o similar). Si no la
    hay: Configuracion > Hora e idioma > Idioma > agregar English (United
    States) con el paquete de voz.
#>

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

function Get-Voz($idioma) {
    return $synth.GetInstalledVoices() |
           Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $idioma } |
           Select-Object -First 1
}

$vozEn = Get-Voz "en"
$vozEs = Get-Voz "es"
if (-not $vozEn) {
    Write-Host "No hay ninguna voz en ingles instalada. Voces disponibles:" -ForegroundColor Red
    $synth.GetInstalledVoices() | ForEach-Object { "  " + $_.VoiceInfo.Name + " (" + $_.VoiceInfo.Culture + ")" }
    exit 1
}
Write-Host "Voz inglesa: $($vozEn.VoiceInfo.Name)" -ForegroundColor DarkGray
if ($vozEs) {
    Write-Host "Voz espanola: $($vozEs.VoiceInfo.Name)" -ForegroundColor DarkGray
} else {
    Write-Host "Sin voz en espanol: no se genera prueba-es.wav" -ForegroundColor Yellow
}

$formato = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

# prueba.wav - ritmo normal, pausas amplias
$guion1 = @'
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
<break time="700ms"/>
Hi, thanks for joining us today. <break time="900ms"/>
So, to kick things off, could you walk me through your experience with UiPath and the REFramework? <break time="1100ms"/>
And how do you usually handle exceptions when a bot fails in the middle of a queue transaction? <break time="1100ms"/>
Tell me about a time you had to automate a really messy process for a bank. <break time="1000ms"/>
What would you say is the biggest bottleneck when you scale unattended robots in production? <break time="900ms"/>
</speak>
'@

# prueba2.wav - rapido y con pausas cortas, ademas de jerga que rompe traductores
$guion2 = @'
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
<break time="600ms"/>
Right, so tell me about your dispatcher and performer design, and whether you deploy through a CI pipeline. <break time="500ms"/>
We run unattended robots in production, so what is your approach to exception handling and retries? <break time="500ms"/>
I pushed a hotfix to the main branch and opened a pull request, does that workflow sound familiar to you? <break time="450ms"/>
Honestly, the onboarding was rough and scope creep pushed the deadline by a month. <break time="500ms"/>
Did you meet the SLA and reduce downtime after go live? <break time="600ms"/>
Why are you looking to leave your current role, and what are your salary expectations? <break time="800ms"/>
</speak>
'@

# prueba-es.wav - reunion en espanol, para el modo audio espanol -> texto espanol
$guion3 = @'
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="es-MX">
<break time="700ms"/>
Buenos dias a todos, gracias por conectarse. <break time="900ms"/>
Quiero que revisemos el avance del robot de conciliacion bancaria antes del cierre de mes. <break time="1000ms"/>
El proceso viene fallando cuando la cola tiene mas de mil transacciones pendientes. <break time="1000ms"/>
Necesito que alguien se encargue del manejo de excepciones y me confirme la fecha de despliegue. <break time="1000ms"/>
Steban, cuentanos como vas con la automatizacion del reporte diario, por favor. <break time="900ms"/>
</speak>
'@

$casos = @(
    @{ Archivo = "prueba.wav";  Guion = $guion1; Rate = 0; Voz = $vozEn },
    @{ Archivo = "prueba2.wav"; Guion = $guion2; Rate = 2; Voz = $vozEn }
)
if ($vozEs) {
    $casos += @{ Archivo = "prueba-es.wav"; Guion = $guion3; Rate = 0; Voz = $vozEs }
}

foreach ($caso in $casos) {
    $destino = Join-Path $logDir $caso.Archivo
    $synth.SelectVoice($caso.Voz.VoiceInfo.Name)
    $synth.Rate = $caso.Rate
    $synth.SetOutputToWaveFile($destino, $formato)
    $synth.SpeakSsml($caso.Guion)
    $synth.SetOutputToNull()
    $segundos = [math]::Round((Get-Item $destino).Length / 32000, 1)
    Write-Host "  $($caso.Archivo)  -  $segundos s" -ForegroundColor Green
}

$synth.Dispose()

Write-Host ""
Write-Host "Listo. Pruebalos con el servidor arriba:" -ForegroundColor DarkGray
Write-Host "  .\.venv\Scripts\python.exe scripts\probar.py logs\prueba2.wav en-es"
Write-Host "  .\.venv\Scripts\python.exe scripts\probar.py logs\prueba2.wav en-en"
Write-Host "  .\.venv\Scripts\python.exe scripts\probar.py logs\prueba-es.wav es-es"
