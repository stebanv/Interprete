# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba de punta a punta sin navegador.

Reproduce un WAV de 16 kHz mono contra el servidor al mismo ritmo que lo haria
el portatil (trozos de 100 ms en tiempo real) e imprime lo que va llegando.

    .venv\\Scripts\\python.exe scripts\\probar.py logs\\prueba.wav
"""

import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
CHUNK_MS = 100


async def main(wav_path: Path, mode: str = "en-es") -> None:
    token = (ROOT / ".token").read_text(encoding="utf-8").strip()
    url = f"ws://127.0.0.1:8777/ws?k={token}"

    with wave.open(str(wav_path), "rb") as wav:
        assert wav.getframerate() == 16000, "el WAV debe ser de 16 kHz"
        assert wav.getnchannels() == 1, "el WAV debe ser mono"
        pcm = wav.readframes(wav.getnframes())

    frames_per_chunk = 16000 * CHUNK_MS // 1000
    bytes_per_chunk = frames_per_chunk * 2
    total_s = len(pcm) / 32000
    print(f"Audio: {total_s:.1f} s\n")

    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(f"mode:{mode}")
        started = time.monotonic()
        finals = 0

        async def reader():
            nonlocal finals
            async for raw in ws:
                msg = json.loads(raw)
                elapsed = time.monotonic() - started
                if msg["type"] == "partial":
                    print(f"[{elapsed:6.2f}s] ...  {msg['es'] or msg['en']}")
                elif msg["type"] == "final":
                    finals += 1
                    etiqueta = "EN  " if msg["es"] else "TXT "
                    print(f"[{elapsed:6.2f}s] {etiqueta} {msg['en']}")
                    if msg["es"]:
                        print(f"[{elapsed:6.2f}s] ES   {msg['es']}")
                    print(f"          ({msg['latency_ms']} ms de inferencia, "
                          f"{msg['audio_s']} s de audio)\n")
                elif msg["type"] == "error":
                    print(f"[{elapsed:6.2f}s] ERROR {msg['message']}")

        task = asyncio.create_task(reader())

        for offset in range(0, len(pcm), bytes_per_chunk):
            await ws.send(pcm[offset : offset + bytes_per_chunk])
            target = started + (offset + bytes_per_chunk) / 32000
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

        # Cola de silencio para que se cierre la ultima frase
        await ws.send(b"\x00" * bytes_per_chunk * 15)
        await asyncio.sleep(6)
        task.cancel()
        print(f"Frases finales: {finals}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "prueba.wav"
    modo = sys.argv[2] if len(sys.argv) > 2 else "en-es"
    asyncio.run(main(path, modo))
