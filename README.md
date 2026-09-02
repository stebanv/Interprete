# Intérprete

Subtítulos en vivo para entrevistas en inglés. El audio se captura en el
portátil, viaja al PC de escritorio, y vuelve como texto en la pantalla del
portátil. Todo el procesamiento pesado corre en la RTX 5070; el portátil solo
captura y muestra.

Dos modos, conmutables en cualquier momento incluso a mitad de llamada:

| Modo | Qué ves |
|---|---|
| **Inglés → Español** | El inglés pequeño arriba, el español grande abajo |
| **Solo inglés** | Únicamente la transcripción en inglés, en grande |

---

## Arranque

En el PC de escritorio, desde PowerShell:

```powershell
cd $HOME\Interprete
.\scripts\start.ps1
```

Levanta el servidor, abre un túnel de Cloudflare y te imprime (y copia al
portapapeles) una URL como:

```
https://algo-aleatorio.trycloudflare.com/?k=TOKEN
```

Esa URL se abre en el portátil, en **Chrome o Edge**. `Ctrl+C` apaga todo.

Para probar sin túnel, en este mismo PC: `.\scripts\start.ps1 -Local`

> La URL cambia cada vez que arrancas. El token no: vive en `.token` y es lo
> único que protege el servicio mientras el túnel está abierto.

---

## En el portátil, el día de la entrevista

1. Abre la reunión (Teams, Zoom o Meet) **en una pestaña de Chrome**.
2. En otra pestaña, abre la URL del Intérprete.
3. Elige el modo y presiona **Iniciar**.
4. En el diálogo de compartir, escoge la **pestaña de la reunión** y marca
   **«También compartir el audio de la pestaña»**. Sin esa casilla no llega audio.
5. Acomoda las dos ventanas lado a lado y listo.

La barra verde de nivel confirma que está entrando audio. Si no se mueve, es que
no marcaste la casilla del audio.

**Nada de esto se oye en la llamada.** El audio capturado se analiza y se
descarta; la página no reproduce nada.

### Controles

| Control | Para qué |
|---|---|
| `A+` / `A−` | Tamaño de letra (se recuerda entre sesiones) |
| **Limpiar** | Borra la pantalla y el contexto |
| **Guardar** | Descarga la transcripción en `.txt` |
| Clic en una línea | La copia al portapapeles |

---

## Saber si está arriba o abajo

### Desde el PC

```powershell
.\scripts\estado.ps1            # una foto
.\scripts\estado.ps1 -Vigilar   # refresca cada 5 s
```

Responde con un solo renglón — **ARRIBA**, **PARCIAL** (servidor vivo pero túnel
caído: el portátil no llega) o **ABAJO** — y si está arriba te reimprime la URL,
por si perdiste la que copiaste.

La ventana de `start.ps1` también lo dice en el título: *"Interprete - ARRIBA
(no cierres esta ventana)"*, visible desde la barra de tareas.

### Desde el portátil

La página misma es el indicador, y está hecha para que no se te pase:

| Señal | Significado |
|---|---|
| Punto verde + "conectado · large-v3 en GPU" | Todo bien |
| **Barra superior roja** + "SIN CONEXIÓN — reintentando" | Se cayó |
| Título de la pestaña: **⚠ Sin conexión** | Se cayó, y lo ves aunque la pestaña esté en segundo plano |
| Franja roja fija arriba | Se cayó; no se auto-oculta hasta que vuelva |
| Barra verde de nivel moviéndose | Está entrando audio de verdad |

Reconecta sola, con reintentos espaciados. Cuando vuelve, avisa en verde.

**Un WebSocket puede quedar "abierto" contra un túnel ya muerto** — el navegador
no se entera hasta que intenta escribir. Por eso la página vigila: si el
servidor lleva 8 segundos sin decir nada mientras estás capturando, corta y
reconecta en lugar de tragar audio al vacío.

## Apagarlo

`Ctrl+C` en la ventana de `start.ps1`. Pero si esa ventana se cierra de golpe, el
servidor y el túnel **quedan huérfanos**: el túnel sigue público y nada lo
delata. Para esos casos:

```powershell
.\scripts\detener.ps1
```

Los mata por ruta, sin depender de quién los lanzó, y verifica que el puerto
8777 dejó de responder antes de decirte que terminó. Si vas a dejar el PC solo
después de la entrevista, corre esto.

---

## Cómo funciona

```
Portátil                      Internet              PC (RTX 5070)
────────                      ────────              ─────────────
pestaña de la reunión
      │ audio
      ▼
 AudioWorklet ── PCM 16 kHz ──► túnel Cloudflare ──► VAD por energía
                (trozos 100 ms)      (HTTPS/WSS)          │
                                                          ▼
                                                   Whisper large-v3
                                                          │
                                                          ▼
                                                   opus-mt-tc-big-en-es
                                                          │
 subtítulos ◄──────── JSON ◄───────────────────────────────┘
```

Mientras alguien habla, cada 0.7 s se reescribe una transcripción **provisional**
(la línea gris de abajo). Cuando aparece un silencio de 0.6 s se cierra la frase
y se emite el texto **definitivo**, que sube al historial y ya no cambia.

**Latencia medida**: la frase definitiva aparece entre 1.5 y 2 s después de que
el interlocutor termina de hablar; la provisional va ~1 s detrás de su voz. Por
el túnel se suman unos 200 ms.

### El glosario

`server/glosario.py` es el archivo que vas a querer editar. Un traductor
generalista convierte "go live" en *"la transmisión"* y "CI pipeline" en
*"oleoducto de inteligencia"*. Para evitarlo, los términos de `TERMINOS` se
reemplazan por un marcador antes de traducir y se restituyen después.

Solo están ahí los que **se comprobó** que se rompen. Los que el modelo ya
traduce bien (downtime, stakeholders, onboarding, pipeline, dispatcher,
performer) se dejan sueltos a propósito: enmascararlos rompe la concordancia y
empeora la frase completa.

Agregar un término es una línea:

```python
("business exception", "business exception"),
```

`CORRECCIONES` es la red de seguridad sobre el español ya traducido, para lo que
se cuela de todas formas.

---

## Botón "explicar" (opcional)

Si defines `ANTHROPIC_API_KEY` antes de arrancar, cada línea muestra un botón
**explicar** que consulta a Claude y devuelve traducción, sentido de la pregunta
y el modismo o término difícil, si lo hay.

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
.\scripts\start.ps1
```

Va **fuera** de la ruta en vivo, bajo demanda: una llamada de red arruinaría la
latencia de los subtítulos. Sin la variable, el botón simplemente no aparece.

---

## Instalación desde cero

```powershell
.\scripts\setup.ps1
```

Crea el entorno con Python 3.12, instala torch con CUDA 12.8 (necesario para
Blackwell / RTX 50xx), baja los modelos (~3.5 GB) y cloudflared.

## Probar sin entrevista

Primero genera el audio de prueba (una sola vez; no va en el repositorio):

```powershell
.\scripts\generar-audio-prueba.ps1
```

Arma dos WAV con las voces de Windows: uno a ritmo normal y otro rápido con la
jerga que rompe traductores. Con el servidor arriba:

```powershell
.\.venv\Scripts\python.exe scripts\probar.py logs\prueba2.wav es
.\.venv\Scripts\python.exe scripts\probar.py logs\prueba2.wav en
```

Reproduce el WAV contra el servidor al mismo ritmo que lo haría el portátil e
imprime lo que va llegando, con tiempos.

---

## Ajustes

Todo por variables de entorno, o editando `server/config.py`:

| Variable | Predeterminado | Para qué |
|---|---|---|
| `INTERPRETE_WHISPER_MODEL` | `large-v3` | `distil-large-v3` o `medium.en` si hiciera falta más velocidad |
| `INTERPRETE_MT_MODEL` | `Helsinki-NLP/opus-mt-tc-big-en-es` | El traductor |
| `INTERPRETE_PORT` | `8777` | Puerto local |
| `ANTHROPIC_API_KEY` | — | Enciende el botón "explicar" |

Los tiempos de segmentación (`END_SILENCE`, `PARTIAL_INTERVAL`, `MAX_UTTERANCE`)
están en `server/config.py` con su explicación.

## Si algo falla

| Síntoma | Causa |
|---|---|
| La barra de nivel no se mueve | No marcaste «compartir el audio de la pestaña» |
| "token rechazado" | La URL se copió incompleta, sin el `?k=...` |
| El punto queda rojo | Se cayó el túnel; reconecta solo, o reinicia `start.ps1` |
| Frases muy largas sin cortar | Baja `END_SILENCE` en `config.py` |
| Se corta a mitad de frase | Sube `END_SILENCE` |
