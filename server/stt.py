"""Motor de transcripcion (ingles) sobre faster-whisper / CTranslate2."""

import logging
import os
import re
import threading
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger("interprete.stt")


def _register_cuda_dlls() -> None:
    """CTranslate2 necesita cuBLAS y cuDNN 9 en el PATH.

    En Windows no vienen con el wheel: los tomamos de los que instala torch
    (torch/lib) y de los paquetes nvidia-* si estan presentes. Sin esto,
    faster-whisper falla con 'Library cudnn_ops64_9.dll is not found'.
    """
    candidates = []
    try:
        import torch  # noqa: F401

        candidates.append(Path(torch.__file__).resolve().parent / "lib")
    except Exception:
        pass
    try:
        import nvidia  # noqa: F401

        nvidia_base = Path(nvidia.__file__).resolve().parent
        candidates.extend(p for p in nvidia_base.glob("*/bin") if p.is_dir())
        candidates.extend(p for p in nvidia_base.glob("*/lib") if p.is_dir())
    except Exception:
        pass

    for path in candidates:
        if not path.is_dir():
            continue
        try:
            os.add_dll_directory(str(path))
        except (OSError, AttributeError):
            pass
        os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")


# Frases que Whisper inventa cuando le entra silencio o ruido. Son residuos del
# entrenamiento con subtitulos de YouTube.
_HALLUCINATIONS = {
    "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
    "thank you for watching.", "thank you for watching!", "you", "you.",
    "bye.", "bye bye.", "okay.", "ok.", "so.", ".", "!", "?", "...",
    "please subscribe to my channel.", "subscribe to my channel.",
    "subtitles by the amara.org community", "transcription by castingwords",
    "i'm going to go ahead and take a look at the video.",
    "the end.", "music", "applause", "silence",
}
_BRACKETED = re.compile(r"^[\[\(\*♪][^\]\)\*♪]*[\]\)\*♪]$")


def _is_junk(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    low = stripped.lower()
    if low in _HALLUCINATIONS:
        return True
    if _BRACKETED.match(stripped):
        return True
    # "you you you you" y demas bucles de repeticion
    words = low.replace(",", " ").replace(".", " ").split()
    if len(words) >= 4 and len(set(words)) == 1:
        return True
    return False


class WhisperEngine:
    """Envoltura sincrona y thread-safe alrededor de WhisperModel."""

    def __init__(self) -> None:
        _register_cuda_dlls()
        from faster_whisper import WhisperModel

        self.device = config.WHISPER_DEVICE
        self.compute_type = config.WHISPER_COMPUTE
        self.model_name = config.WHISPER_MODEL
        self._lock = threading.Lock()

        try:
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as exc:  # pragma: no cover - depende del hardware
            if self.device != "cuda":
                raise
            log.warning("CUDA no disponible para Whisper (%s). Cayendo a CPU int8.", exc)
            self.device = "cpu"
            self.compute_type = "int8"
            self.model = WhisperModel(
                self.model_name, device="cpu", compute_type="int8"
            )

        log.info(
            "Whisper listo: %s en %s (%s)",
            self.model_name, self.device, self.compute_type,
        )

    @property
    def description(self) -> str:
        return f"{self.model_name} / {self.device} / {self.compute_type}"

    def warmup(self) -> None:
        """Primera inferencia con audio mudo, para que la real no pague el arranque."""
        silence = np.zeros(config.SAMPLE_RATE, dtype=np.float32)
        try:
            self.transcribe(silence, final=False)
        except Exception as exc:  # pragma: no cover
            log.warning("Warmup fallo: %s", exc)

    def transcribe(
        self,
        audio: np.ndarray,
        context: str = "",
        final: bool = False,
    ) -> str:
        """Devuelve el texto en ingles de un bloque de audio float32 a 16 kHz."""
        if audio.size < config.SAMPLE_RATE // 10:
            return ""

        initial_prompt = config.GLOSSARY
        if context:
            initial_prompt = f"{config.GLOSSARY} {context}"

        with self._lock:
            segments, _info = self.model.transcribe(
                audio,
                language="en",
                task="transcribe",
                beam_size=5 if final else 1,
                best_of=5 if final else 1,
                temperature=[0.0, 0.2, 0.4] if final else 0.0,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
                vad_filter=False,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                word_timestamps=False,
            )
            pieces = []
            for seg in segments:
                if seg.no_speech_prob > 0.75 and seg.avg_logprob < -0.55:
                    continue
                if seg.avg_logprob < -1.1:
                    continue
                text = seg.text.strip()
                if _is_junk(text):
                    continue
                pieces.append(text)

        result = " ".join(pieces).strip()
        result = re.sub(r"\s+", " ", result)
        if _is_junk(result):
            return ""
        return result
