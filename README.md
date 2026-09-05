# Intérprete

**Subtítulos en vivo de una reunión, generados en tu propia máquina.**

Capturas el audio de una videollamada y lo lees como texto en tiempo real. Todo
el procesamiento ocurre en tu computador: el audio **no sale hacia ningún
servicio de terceros**, no hay cuenta que crear, no hay suscripción, y funciona
igual si la reunión es confidencial.

El equipo que hace el trabajo pesado no tiene que ser el mismo donde estás en la
reunión. Un PC con GPU en tu casa puede darle subtítulos a un portátil que está
en otra red, a través de un túnel cifrado.

---

## Para quién es esto

Nació de un problema concreto: entender inglés escrito con soltura, pero
perderse cuando lo hablan rápido. Resultó servir para más:

- **Personas con pérdida auditiva**, que necesitan leer lo que se dice en una
  reunión en su propio idioma, sin depender de que alguien les transcriba.
- **Quien trabaja en otro idioma** y sigue mejor por escrito que de oído.
- **Cualquiera que no quiera** mandar el audio de sus reuniones a un servicio de
  transcripción en la nube.

### Tres modos, conmutables a mitad de llamada

| Modo | Qué ves |
|---|---|
| **Audio inglés → texto español** | El inglés pequeño arriba, el español grande abajo |
| **Audio inglés → texto inglés** | Solo la transcripción, en grande |
| **Audio español → texto español** | Solo la transcripción, en grande |

Whisper large-v3 es multilingüe, así que los tres modos comparten la **misma
copia del modelo en la GPU**: cambiar de idioma no recarga nada ni cuesta
memoria extra.

---

## Instalación

Necesitas **Python 3.10 o superior** (3.12 es lo más probado) y **git**.

```bash
git clone https://github.com/stebanv/Interprete.git
cd Interprete
python interprete.py instalar
```

Eso crea el entorno, detecta si tienes GPU NVIDIA, instala la versión correcta
de PyTorch, descarga los modelos (~3,4 GB) y baja `cloudflared`. Tarda un rato
la primera vez y no vuelve a pasar.

```bash
python interprete.py iniciar
```

Te imprime una URL HTTPS y la copia al portapapeles. Ábrela en **Chrome o Edge**,
en el equipo donde tengas la reunión — puede ser otro computador, en otra red.

| Comando | Qué hace |
|---|---|
| `python interprete.py instalar` | Entorno, modelos y cloudflared |
| `python interprete.py iniciar` | Servidor + túnel público |
| `python interprete.py iniciar --local` | Sin túnel: solo esta máquina |
| `python interprete.py estado` | ARRIBA / PARCIAL / ABAJO, y la URL |
| `python interprete.py detener` | Apaga todo |

En Windows hay atajos equivalentes en `scripts/*.ps1`.

---

## Usarlo

1. Abre la reunión (Teams, Zoom, Meet) **en una pestaña de Chrome**.
2. En otra pestaña, abre la URL del Intérprete.
3. Elige el modo y presiona **Iniciar**.
4. En el diálogo de compartir, escoge la **pestaña de la reunión** y marca
   **«También compartir el audio de la pestaña»**. Sin esa casilla no llega audio.

La barra verde de nivel confirma que está entrando audio. Nada se reproduce: el
audio se analiza y se descarta, así que no hay eco ni te escuchan.

| Control | Para qué |
|---|---|
| `A+` / `A−` | Tamaño de letra, se recuerda entre sesiones |
| **Limpiar** | Borra la pantalla y el contexto |
| **Guardar** | Descarga la transcripción en `.txt` |
| Clic en una línea | La copia al portapapeles |

Si el otro equipo pierde la conexión, la barra superior se pone roja y el título
de la pestaña cambia a **⚠ Sin conexión** — visible aunque la pestaña esté de
fondo. Reconecta sola.

---

## Requisitos reales

Medido, no estimado. Pico de memoria de video incluyendo el contexto de CUDA:

| Configuración | VRAM | GPU mínima | Velocidad |
|---|---|---|---|
| `large-v3` float16 **(por defecto)** | 5,6 GB | 8 GB cómoda · 6 GB justa | 11× tiempo real |
| `large-v3` int8_float16 | 3,7 GB | 6 GB cómoda · 4 GB justa | 10× |
| `medium.en` int8_float16 | 2,7 GB | 4 GB | 16× |
| `small.en` int8_float16 | 2,0 GB | 4 GB · 2 GB justa | 25× |
| `small.en` int8 **en CPU** | — | ninguna | 5× |

Hace falta ~2× tiempo real para que sirva en vivo, así que **todas** las filas
pasan, incluida la de CPU. Sin GPU NVIDIA el instalador lo detecta y pone la
versión de PyTorch para CPU; conviene un modelo pequeño:

```bash
INTERPRETE_WHISPER_MODEL=small.en python interprete.py iniciar
```

Ojo con la memoria que reporta `nvidia-smi`: CTranslate2 cachea de forma
oportunista y puede mostrar el doble de lo que necesita. En una tarjeta más
pequeña simplemente cachea menos.

**Latencia**: la frase definitiva aparece entre 1,5 y 2 s después de que el otro
deja de hablar; una transcripción provisional va ~1 s detrás de su voz. El túnel
suma ~200 ms.

### Soporte por plataforma

| Sistema | Estado |
|---|---|
| **Windows** | Probado. Es donde se desarrolló |
| **Linux** | Debería funcionar; el código no tiene nada específico de Windows. Sin probar |
| **macOS** | Solo CPU: faster-whisper no usa Metal. Sin probar |

Si lo corres en Linux o macOS, cuenta cómo te fue en un issue.

---

## Cómo funciona

```
Otro equipo                   Internet              Tu máquina
───────────                   ────────              ──────────
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

Mientras alguien habla, cada 0,7 s se reescribe una transcripción **provisional**.
Cuando aparece un silencio de 0,6 s se cierra la frase y se emite el texto
**definitivo**, que ya no cambia.

| Componente | Modelo | En disco |
|---|---|---|
| Transcripción | `Systran/faster-whisper-large-v3` (1.550 M parámetros) | 2,9 GB |
| Traducción | `Helsinki-NLP/opus-mt-tc-big-en-es` (235 M) | 447 MB |

La traducción es **local a propósito**. Una llamada de red en la ruta crítica
arruinaría la latencia de los subtítulos.

---

## Ajustes

Todo vive en [`server/config.py`](server/config.py):

| Ajuste | Por defecto | Efecto |
|---|---|---|
| `END_SILENCE` | 0,60 s | Silencio que cierra una frase. Súbelo si te corta a la mitad |
| `PARTIAL_INTERVAL` | 0,7 s | Cada cuánto se refresca el texto provisional |
| `MAX_UTTERANCE` | 12 s | Corte forzado si alguien habla sin pausas |
| `VAD_START_MULT` | 3,5 | Sensibilidad del detector de voz. Súbelo si hay ruido |

Los modelos y el puerto aceptan además variables de entorno con prefijo
`INTERPRETE_`, así puedes probar una configuración sin dejar el cambio pegado.

### El glosario

[`server/glosario.py`](server/glosario.py) resuelve un problema concreto: un
traductor generalista convierte *"go live"* en **"la transmisión"** y
*"CI pipeline"* en **"oleoducto de inteligencia"**.

La solución no es corregir la salida, sino no dejar que los traduzca: los
términos de `TERMINOS` se reemplazan por un marcador antes de traducir y se
restituyen después. Agregar uno es una línea:

```python
("business exception", "business exception"),
```

Solo están ahí los que **se comprobó** que se rompen. Los que el modelo ya
traduce bien se dejan sueltos a propósito: enmascararlos rompe la concordancia
del español y empeora la frase entera.

El glosario por defecto es de automatización de procesos (RPA), que es el
contexto donde nació. Cámbialo por el vocabulario de lo tuyo.

### Los prompts por idioma

`PROMPT_EN` y `PROMPT_ES` le sugieren a Whisper el vocabulario que va a
escuchar. Cada uno debe estar **en el idioma de su audio**: un prompt en inglés
delante de audio en español empuja al modelo a traducir en vez de transcribir.

Y `PROMPT_ES` va **con tildes a propósito**. Whisper imita la ortografía del
prompt: escrito sin acentos, transcribe *"conciliacion"* y *"dias"*.

---

## Botón "explicar" (opcional)

Si defines `ANTHROPIC_API_KEY` antes de arrancar, cada línea en inglés muestra un
botón que consulta a Claude y devuelve traducción, sentido de la pregunta y el
modismo difícil si lo hay. Va **fuera** de la ruta en vivo, bajo demanda. Sin la
variable el botón no aparece y nada sale de tu máquina.

---

## Seguridad

El túnel de Cloudflare expone el servicio a internet mientras está abierto. Lo
único que lo protege es un token aleatorio que viaja en la URL y se guarda en
`.token`, fuera del repositorio. **Ciérralo cuando termines**:

```bash
python interprete.py detener
```

`logs/` también está fuera del repositorio a propósito: el log del servidor
imprime el token en claro.

Para uso en la misma máquina, `iniciar --local` no abre ningún túnel.

---

## Desarrollo

```bash
# Genera audio de prueba con las voces del sistema (solo Windows)
./scripts/generar-audio-prueba.ps1

# Reproduce un WAV contra el servidor al ritmo real y muestra los tiempos
python interprete.py probar prueba2.wav en-es
python interprete.py probar prueba-es.wav es-es
```

`scripts/medir.py` mide VRAM y velocidad de una configuración concreta; de ahí
salió la tabla de requisitos.

Los aportes son bienvenidos, sobre todo: probarlo en Linux y macOS, otros pares
de idiomas, y mejorar la accesibilidad de la interfaz.

---

## Licencia

GPL-3.0-or-later. Ver [LICENSE](LICENSE).

Si lo modificas y lo distribuyes, tu versión también tiene que ser libre. Es a
propósito: esto nació como una herramienta de accesibilidad y debería seguir
siendo de todos.
