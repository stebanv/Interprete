# SPDX-License-Identifier: GPL-3.0-or-later
"""Traduccion ingles -> espanol.

Ruta principal: MarianMT (opus-mt-tc-big-en-es) local en GPU. Son ~30 ms
por frase, asi que cabe dentro de la ruta critica de los subtitulos en vivo.

Ruta opcional: Claude, solo bajo demanda desde el boton "explicar". Nunca en la
ruta critica, porque una llamada de red arruinaria la latencia.
"""

import logging
import os
import re
import threading
from collections import OrderedDict

from . import config
from .glosario import corregir, faltan_marcadores, proteger, restaurar

log = logging.getLogger("interprete.mt")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str, limit: int = 380) -> list[str]:
    """Marian rinde mejor frase por frase que con parrafos largos."""
    chunks: list[str] = []
    for sentence in _SENT_SPLIT.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


class Translator:
    """MarianMT con cache LRU: los parciales repiten prefijos todo el tiempo."""

    def __init__(self) -> None:
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        self.torch = torch
        self.device = config.MT_DEVICE
        if self.device == "cuda" and not torch.cuda.is_available():
            log.warning("CUDA no disponible para el traductor. Usando CPU.")
            self.device = "cpu"

        self.tokenizer = MarianTokenizer.from_pretrained(config.MT_MODEL)
        model = MarianMTModel.from_pretrained(config.MT_MODEL)
        if self.device == "cuda":
            model = model.half()
        self.model = model.to(self.device).eval()

        self._lock = threading.Lock()
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_limit = 2000
        log.info("Traductor listo: %s en %s", config.MT_MODEL, self.device)

    @property
    def description(self) -> str:
        return f"{config.MT_MODEL} / {self.device}"

    def warmup(self) -> None:
        try:
            self.translate("Tell me about yourself.")
        except Exception as exc:  # pragma: no cover
            log.warning("Warmup del traductor fallo: %s", exc)

    def _cache_get(self, key: str) -> str | None:
        value = self._cache.get(key)
        if value is not None:
            self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: str, value: str) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)

    def _generate(self, sources: list[str]) -> list[str]:
        with self._lock:
            batch = self.tokenizer(
                sources, return_tensors="pt", padding=True, truncation=True,
                max_length=512,
            ).to(self.device)
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **batch, num_beams=1, max_new_tokens=384,
                )
            return self.tokenizer.batch_decode(generated, skip_special_tokens=True)

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""

        cached = self._cache_get(text)
        if cached is not None:
            return cached

        sentences = _split_sentences(text)
        if not sentences:
            return ""

        pending = [s for s in sentences if self._cache_get(s) is None]
        if pending:
            marked, maps = [], []
            for source in pending:
                protegido, mapa = proteger(source)
                marked.append(protegido)
                maps.append(mapa)

            decoded = self._generate(marked)

            # Si el traductor se comio algun marcador, esa frase se rehace sin
            # proteccion: mejor un termino mal traducido que una palabra perdida.
            perdidas = [
                i for i, (out, mapa) in enumerate(zip(decoded, maps))
                if faltan_marcadores(out, mapa)
            ]
            if perdidas:
                rehechas = self._generate([pending[i] for i in perdidas])
                for index, out in zip(perdidas, rehechas):
                    decoded[index] = out
                    maps[index] = {}

            for source, out, mapa in zip(pending, decoded, maps):
                self._cache_put(source, corregir(restaurar(out.strip(), mapa)))

        result = " ".join(self._cache_get(s) or "" for s in sentences).strip()
        self._cache_put(text, result)
        return result


class ClaudeHelper:
    """Explicacion bajo demanda de una frase concreta. Opcional."""

    def __init__(self) -> None:
        self.enabled = False
        self.client = None
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.info("Sin ANTHROPIC_API_KEY: el boton 'explicar' queda apagado.")
            return
        try:
            import anthropic

            self.client = anthropic.AsyncAnthropic()
            self.enabled = True
            log.info("Claude disponible para explicaciones (%s).", config.CLAUDE_MODEL)
        except Exception as exc:  # pragma: no cover
            log.warning("No se pudo iniciar el cliente de Claude: %s", exc)

    async def explain(self, english: str, context: str = "") -> str:
        if not self.enabled or self.client is None:
            raise RuntimeError("Claude no esta configurado (falta ANTHROPIC_API_KEY).")

        system = (
            "Eres un interprete de ingles a espanol colombiano para un desarrollador "
            "RPA que esta en una entrevista de trabajo en vivo. Te llega una frase que "
            "dijo el entrevistador y necesitas que la entienda rapido.\n\n"
            "Responde SIEMPRE en espanol y en este formato exacto, sin nada mas:\n"
            "TRADUCCION: <traduccion natural y fiel de la frase>\n"
            "SENTIDO: <una linea con lo que realmente esta pidiendo o preguntando>\n"
            "OJO: <solo si hay un modismo, phrasal verb o termino tecnico dificil; "
            "explicalo en una linea. Si no hay nada dificil, escribe 'nada'>\n\n"
            "Se breve. La persona esta leyendo esto en medio de una conversacion."
        )
        user = english if not context else f"Contexto previo:\n{context}\n\nFrase:\n{english}"

        message = await self.client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=700,
            system=system,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in message.content
            if getattr(block, "type", "") == "text"
        ).strip()
