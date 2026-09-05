# SPDX-License-Identifier: GPL-3.0-or-later
"""Mide VRAM y velocidad real de una configuracion de modelos.

Corre en un proceso aparte por configuracion, porque la VRAM solo se libera de
verdad cuando el proceso muere.

    python scripts/medir.py <modelo_whisper> <compute_type> [--sin-traductor]

Ejemplos:
    python scripts/medir.py large-v3 float16
    python scripts/medir.py large-v3 int8_float16
    python scripts/medir.py medium.en int8_float16
"""

import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def vram_mb() -> int:
    """VRAM ocupada en la GPU, en MB.

    En Windows nvidia-smi devuelve [N/A] para la memoria por proceso (modo
    WDDM), asi que se lee el total libre del driver. Como aqui no hay nada mas
    usando la GPU, la diferencia es lo que ocupa el Interprete — y a diferencia
    de torch.cuda.memory_allocated, esto si ve lo que reserva CTranslate2, que
    no pasa por el asignador de torch.
    """
    import torch

    if not torch.cuda.is_available():
        return 0
    libre, total = torch.cuda.mem_get_info()
    return (total - libre) // (1024 * 1024)


def vram_total_mb() -> int:
    import torch

    if not torch.cuda.is_available():
        return 0
    return torch.cuda.mem_get_info()[1] // (1024 * 1024)


def cargar_audio(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        crudo = wav.readframes(wav.getnframes())
    return np.frombuffer(crudo, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    modelo = sys.argv[1] if len(sys.argv) > 1 else "large-v3"
    compute = sys.argv[2] if len(sys.argv) > 2 else "float16"
    con_traductor = "--sin-traductor" not in sys.argv

    os.environ["INTERPRETE_WHISPER_MODEL"] = modelo
    os.environ["INTERPRETE_COMPUTE"] = compute

    from server.stt import WhisperEngine
    from server.mt import Translator

    import torch

    torch.zeros(1, device="cuda")  # fuerza el contexto CUDA antes de medir
    contexto = vram_mb()

    inicio = time.time()
    motor = WhisperEngine()
    motor.warmup()
    carga_stt = time.time() - inicio
    vram_stt = vram_mb()

    vram_total = vram_stt
    traductor = None
    if con_traductor:
        traductor = Translator()
        traductor.warmup()
        vram_total = vram_mb()

    audio = cargar_audio(ROOT / "logs" / "prueba2.wav")
    duracion = audio.size / 16000

    # Se mide una frase suelta, que es como llegan en vivo, no el archivo entero.
    trozo = audio[: 16000 * 6]
    tiempos = []
    for _ in range(3):
        t0 = time.time()
        texto = motor.transcribe(trozo, final=True)
        tiempos.append(time.time() - t0)
    mediana = sorted(tiempos)[1]

    t0 = time.time()
    completo = motor.transcribe(audio, final=True)
    total = time.time() - t0

    es = ""
    if traductor:
        t0 = time.time()
        es = traductor.translate(completo[:200])
        ms_mt = (time.time() - t0) * 1000
    else:
        ms_mt = 0.0

    pico = vram_mb()

    print("RESULTADO", "|".join([
        modelo,
        compute,
        "con-mt" if con_traductor else "solo-stt",
        str(max(0, vram_stt - contexto)),
        str(max(0, vram_total - contexto)),
        str(contexto),
        str(pico),
        f"{carga_stt:.1f}",
        f"{mediana:.2f}",
        f"{6 / mediana:.1f}",
        f"{duracion / total:.1f}",
        f"{ms_mt:.0f}",
    ]))
    print("TEXTO", completo[:110])
    if es:
        print("TRAD ", es[:110])


if __name__ == "__main__":
    main()
