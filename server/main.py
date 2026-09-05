"""Servidor del Interprete: WebSocket de audio -> subtitulos en espanol."""

import asyncio
import logging
import secrets

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .mt import ClaudeHelper, Translator
from .session import LiveSession
from .stt import WhisperEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
for _noisy in ("httpx", "httpcore", "urllib3", "faster_whisper", "transformers", "filelock"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger("interprete")

TOKEN = config.load_or_create_token()

app = FastAPI(title="Interprete", docs_url=None, redoc_url=None)

state: dict = {"engine": None, "translator": None, "claude": None, "ready": False}


@app.on_event("startup")
async def _startup() -> None:
    def build():
        engine = WhisperEngine()
        translator = Translator()
        engine.warmup()
        translator.warmup()
        return engine, translator

    log.info("Cargando modelos...")
    engine, translator = await asyncio.to_thread(build)
    state["engine"] = engine
    state["translator"] = translator
    state["claude"] = ClaudeHelper()
    state["ready"] = True
    log.info("Listo. STT: %s | MT: %s", engine.description, translator.description)
    log.info("Token de acceso: %s", TOKEN)


def _check_token(value: str | None) -> None:
    if not value or not secrets.compare_digest(value, TOKEN):
        raise HTTPException(status_code=401, detail="token invalido")


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ready": state["ready"]})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/api/info")
async def info(k: str | None = None) -> JSONResponse:
    _check_token(k)
    engine = state["engine"]
    translator = state["translator"]
    claude = state["claude"]
    return JSONResponse({
        "ready": state["ready"],
        "stt": engine.description if engine else None,
        "mt": translator.description if translator else None,
        "claude": bool(claude and claude.enabled),
        "sample_rate": config.SAMPLE_RATE,
    })


@app.post("/api/explain")
async def explain(request: Request) -> JSONResponse:
    payload = await request.json()
    _check_token(payload.get("k"))
    claude: ClaudeHelper = state["claude"]
    if not claude or not claude.enabled:
        raise HTTPException(status_code=503, detail="Claude no configurado")
    text = (payload.get("en") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="falta el texto")
    try:
        answer = await claude.explain(text, (payload.get("context") or "").strip())
    except Exception as exc:
        log.exception("Fallo la explicacion")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JSONResponse({"text": answer})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    if not secrets.compare_digest(ws.query_params.get("k", ""), TOKEN):
        await ws.close(code=4401)
        return
    if not state["ready"]:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Los modelos todavia cargan."})
        await ws.close(code=1013)
        return

    await ws.accept()
    lock = asyncio.Lock()

    async def send(message: dict) -> None:
        async with lock:
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                pass

    session = LiveSession(state["engine"], state["translator"], send)
    await send({
        "type": "status",
        "state": "ready",
        "stt": state["engine"].description,
        "mt": state["translator"].description,
        "claude": bool(state["claude"] and state["claude"].enabled),
    })
    log.info("Cliente conectado desde %s", ws.client.host if ws.client else "?")

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                await session.feed(data)
            elif (text := message.get("text")) is not None:
                if text == "ping":
                    await send({"type": "pong"})
                elif text == "reset":
                    session.reset()
                    await send({"type": "clear"})
                elif text.startswith("mode:"):
                    requested = text.split(":", 1)[1]
                    if session.set_mode(requested):
                        await send({"type": "mode", "mode": session.mode})
                elif text == "pause":
                    session.paused = True
                elif text == "resume":
                    session.paused = False
                    session.reset()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Error en la sesion")
    finally:
        await session.close()
        log.info("Cliente desconectado")


app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")


def run() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="warning",
        ws_max_size=8 * 1024 * 1024,
    )


if __name__ == "__main__":
    run()
