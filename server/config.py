"""Configuracion central del Interprete.

Todo se puede sobreescribir con variables de entorno con prefijo INTERPRETE_.
"""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
TOKEN_FILE = ROOT / ".token"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# --- Red -------------------------------------------------------------------
HOST = _env("INTERPRETE_HOST", "127.0.0.1")
PORT = int(_env("INTERPRETE_PORT", "8777"))

# --- Modelos ---------------------------------------------------------------
# large-v3 rinde en tiempo real en una RTX 5070. Si alguna vez hay que bajarle,
# "distil-large-v3" o "medium.en" son los siguientes escalones.
WHISPER_MODEL = _env("INTERPRETE_WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = _env("INTERPRETE_DEVICE", "cuda")
WHISPER_COMPUTE = _env("INTERPRETE_COMPUTE", "float16")
MT_MODEL = _env("INTERPRETE_MT_MODEL", "Helsinki-NLP/opus-mt-tc-big-en-es")
MT_DEVICE = _env("INTERPRETE_MT_DEVICE", WHISPER_DEVICE)

# Modelo de Claude para el boton "explicar" (opcional, requiere ANTHROPIC_API_KEY)
CLAUDE_MODEL = _env("INTERPRETE_CLAUDE_MODEL", "claude-opus-5")

# --- Audio -----------------------------------------------------------------
SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320 muestras por frame

# --- Segmentacion en vivo --------------------------------------------------
PARTIAL_INTERVAL = 0.7   # cada cuanto se reescribe la transcripcion provisional
END_SILENCE = 0.60       # silencio que cierra una frase y dispara el texto final
MIN_SPEECH = 0.25        # voz minima para que un segmento cuente
MAX_UTTERANCE = 12.0     # corte forzado si alguien habla sin pausas
PRE_ROLL = 0.32          # audio previo al inicio de voz que se conserva

# VAD por energia con histeresis. El audio de pestana viene limpio, asi que
# alcanza de sobra y evita una dependencia mas en la ruta critica.
VAD_START_MULT = 3.5     # cuanto sobre el piso de ruido para declarar voz
VAD_KEEP_MULT = 1.8      # umbral mas bajo para sostener la voz ya empezada
VAD_FLOOR_MIN = 0.0016   # piso absoluto: nada por debajo es voz

# --- Contexto para Whisper -------------------------------------------------
# Sesga el modelo hacia el vocabulario que va a aparecer en una entrevista RPA.
GLOSSARY = (
    "This is a job interview for a Robotic Process Automation developer position. "
    "Terms that may appear: RPA, UiPath, Automation Anywhere, Blue Prism, Power Automate, "
    "Orchestrator, REFramework, dispatcher, performer, queue, transaction, selector, "
    "attended, unattended, bot, workflow, activity, exception handling, retry, SLA, "
    "SAP, Citrix, OCR, API, SQL, Python, VBA, Excel, Active Directory, "
    "stakeholder, scalability, deployment, code review, sprint, backlog."
)

MAX_CONTEXT_CHARS = 220  # cuanto texto previo se le pasa como initial_prompt


def load_or_create_token() -> str:
    """Token estable entre reinicios; viaja en la URL como ?k=..."""
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(18)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token
