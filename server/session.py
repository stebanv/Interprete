"""Segmentacion en vivo del audio y orquestacion de transcripcion + traduccion.

Estrategia: VAD por energia frame a frame (20 ms). Mientras hay voz se reescribe
una transcripcion provisional cada PARTIAL_INTERVAL segundos; cuando aparece un
silencio de END_SILENCE se cierra la frase y se emite el texto definitivo, que ya
no cambia.
"""

import asyncio
import logging
import time
from collections import deque

import numpy as np

from . import config

log = logging.getLogger("interprete.session")

_FRAME_SECONDS = config.FRAME_MS / 1000.0
_PREROLL_FRAMES = max(1, int(config.PRE_ROLL / _FRAME_SECONDS))

# modo -> (idioma del audio, traducir al espanol)
MODOS: dict[str, tuple[str, bool]] = {
    "en-es": ("en", True),    # entrevista en ingles, se lee en espanol
    "en-en": ("en", False),   # entrevista en ingles, se lee en ingles
    "es-es": ("es", False),   # reunion en espanol, se lee en espanol
    # Nombres viejos: una pestana abierta desde antes sigue funcionando.
    "es": ("en", True),
    "en": ("en", False),
}
MODO_POR_DEFECTO = "en-es"


class LiveSession:
    def __init__(self, engine, translator, send) -> None:
        self.engine = engine
        self.translator = translator
        self.send = send

        # Estado del VAD
        self.noise_floor = 0.004
        self.in_speech = False
        self.silence_s = 0.0
        self.speech_s = 0.0

        # Buffers
        self.residual = np.zeros(0, dtype=np.float32)
        self.preroll: deque[np.ndarray] = deque(maxlen=_PREROLL_FRAMES)
        self.utt: list[np.ndarray] = []
        self.utt_samples = 0

        # Control
        self.utt_id = 0
        self.seq = 0
        self.last_partial = 0.0
        self.last_level = 0.0
        self.peak = 0.0
        self.busy = False
        self.paused = False
        self.mode = MODO_POR_DEFECTO
        self.gpu_lock = asyncio.Lock()
        self.context = ""
        self.tasks: set[asyncio.Task] = set()

    # -- ciclo de vida ------------------------------------------------------
    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    @property
    def language(self) -> str:
        return MODOS.get(self.mode, MODOS[MODO_POR_DEFECTO])[0]

    @property
    def translates(self) -> bool:
        return MODOS.get(self.mode, MODOS[MODO_POR_DEFECTO])[1]

    def set_mode(self, mode: str) -> bool:
        """Cambia de modo. El contexto acumulado se descarta: esta en el idioma
        anterior y sesgaria la transcripcion siguiente."""
        if mode not in MODOS:
            return False
        if mode != self.mode:
            self.mode = mode
            self.context = ""
        return True

    def reset(self) -> None:
        self.in_speech = False
        self.silence_s = 0.0
        self.speech_s = 0.0
        self.utt = []
        self.utt_samples = 0
        self.residual = np.zeros(0, dtype=np.float32)
        self.preroll.clear()
        self.utt_id += 1
        self.context = ""

    # -- entrada de audio ---------------------------------------------------
    async def feed(self, data: bytes) -> None:
        """Recibe PCM int16 mono a 16 kHz."""
        if self.paused or not data:
            return

        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if self.residual.size:
            samples = np.concatenate((self.residual, samples))

        n_frames = samples.size // config.FRAME_SAMPLES
        if n_frames:
            usable = samples[: n_frames * config.FRAME_SAMPLES]
            self.residual = samples[n_frames * config.FRAME_SAMPLES :].copy()
            for frame in np.split(usable, n_frames):
                self._consume_frame(frame)
        else:
            self.residual = samples.copy()

        await self._tick()

    def _consume_frame(self, frame: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(frame * frame)))
        self.peak = max(self.peak, rms)

        multiplier = config.VAD_KEEP_MULT if self.in_speech else config.VAD_START_MULT
        threshold = max(self.noise_floor * multiplier, config.VAD_FLOOR_MIN)
        voiced = rms > threshold

        if not voiced:
            # El piso de ruido solo se aprende durante el silencio.
            self.noise_floor = 0.97 * self.noise_floor + 0.03 * rms

        self.preroll.append(frame)

        if voiced:
            if not self.in_speech:
                self.in_speech = True
                self.speech_s = 0.0
                self.silence_s = 0.0
                self.utt = list(self.preroll)
                self.utt_samples = sum(f.size for f in self.utt)
                self.last_partial = time.monotonic()
            self.silence_s = 0.0
            self.speech_s += _FRAME_SECONDS
            self.utt.append(frame)
            self.utt_samples += frame.size
        elif self.in_speech:
            # La cola de silencio se conserva: Whisper corta mejor las palabras
            # finales si el audio no termina en seco.
            self.utt.append(frame)
            self.utt_samples += frame.size
            self.silence_s += _FRAME_SECONDS

    async def _tick(self) -> None:
        now = time.monotonic()

        if now - self.last_level >= 0.2:
            self.last_level = now
            await self.send({
                "type": "level",
                "rms": round(min(1.0, self.peak * 6), 3),
                "speaking": self.in_speech,
            })
            self.peak = 0.0

        if not self.in_speech:
            return

        duration = self.utt_samples / config.SAMPLE_RATE

        if self.silence_s >= config.END_SILENCE:
            self._cut_and_finalize()
        elif duration >= config.MAX_UTTERANCE:
            self._cut_and_finalize(forced=True)
        elif not self.busy and now - self.last_partial >= config.PARTIAL_INTERVAL:
            self.last_partial = now
            snapshot = np.concatenate(self.utt) if self.utt else None
            if snapshot is not None:
                self._spawn(self._run_partial(snapshot, self.utt_id))

    def _cut_and_finalize(self, forced: bool = False) -> None:
        audio = np.concatenate(self.utt) if self.utt else np.zeros(0, dtype=np.float32)
        speech = self.speech_s
        utt_id = self.utt_id

        self.utt_id += 1
        self.in_speech = False
        self.utt = []
        self.utt_samples = 0
        self.silence_s = 0.0
        self.speech_s = 0.0
        if forced:
            # Arranca la siguiente frase inmediatamente: el hablante sigue hablando.
            self.in_speech = True
            self.utt = list(self.preroll)
            self.utt_samples = sum(f.size for f in self.utt)
            self.last_partial = time.monotonic()

        self._spawn(self._run_final(audio, speech, utt_id))

    # -- inferencia ---------------------------------------------------------
    async def _run_partial(self, audio: np.ndarray, utt_id: int) -> None:
        try:
            async with self.gpu_lock:
                if utt_id != self.utt_id:
                    return  # la frase ya se cerro: el parcial no sirve
                self.busy = True
                try:
                    texto = await asyncio.to_thread(
                        self.engine.transcribe, audio, self.context, False,
                        self.language,
                    )
                finally:
                    self.busy = False
            if not texto or utt_id != self.utt_id:
                return
            spanish = ""
            if self.translates:
                spanish = await asyncio.to_thread(self.translator.translate, texto)
            await self.send({"type": "partial", "en": texto, "es": spanish})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Fallo transcribiendo parcial")
            await self.send({"type": "error", "message": f"parcial: {exc}"})

    async def _run_final(
        self, audio: np.ndarray, speech_s: float, utt_id: int
    ) -> None:
        try:
            if speech_s < config.MIN_SPEECH or audio.size == 0:
                await self.send({"type": "clear"})
                return

            started = time.monotonic()
            async with self.gpu_lock:
                texto = await asyncio.to_thread(
                    self.engine.transcribe, audio, self.context, True, self.language,
                )
            if not texto:
                await self.send({"type": "clear"})
                return

            spanish = ""
            if self.translates:
                spanish = await asyncio.to_thread(self.translator.translate, texto)
            self.context = f"{self.context} {texto}".strip()[-config.MAX_CONTEXT_CHARS:]
            self.seq += 1
            await self.send({
                "type": "final",
                "id": self.seq,
                "en": texto,
                "es": spanish,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "audio_s": round(audio.size / config.SAMPLE_RATE, 2),
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Fallo transcribiendo final")
            await self.send({"type": "error", "message": f"final: {exc}"})
