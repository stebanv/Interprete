# SPDX-License-Identifier: GPL-3.0-or-later
"""Intérprete — instalar, arrancar, consultar y detener el servicio.

Un solo comando para todo, igual en Windows, Linux y macOS:

    python interprete.py instalar     # entorno, modelos y cloudflared
    python interprete.py iniciar      # servidor + túnel público
    python interprete.py iniciar --local
    python interprete.py estado
    python interprete.py detener

Este archivo se ejecuta con el Python del sistema; se encarga de crear el
entorno virtual y de relanzarse dentro de él cuando hace falta.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VENV = RAIZ / ".venv"
BIN = RAIZ / "bin"
LOGS = RAIZ / "logs"
ARCHIVO_TOKEN = RAIZ / ".token"
ARCHIVO_ESTADO = RAIZ / ".estado.json"
PUERTO = int(os.environ.get("INTERPRETE_PORT", "8777"))

ES_WINDOWS = os.name == "nt"


def _consola_utf8() -> None:
    """Deja la consola de Windows en UTF-8.

    Sin esto, la consola sale en la pagina de codigos heredada (437 u 850) y
    cualquier acento se ve como basura. En Linux y macOS ya viene bien.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass
    if not ES_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for flujo in (sys.stdout, sys.stderr):
        try:
            # line_buffering ademas de UTF-8: sin esto, al redirigir la salida
            # a un archivo Python la acumula y no se ve nada hasta el final.
            flujo.reconfigure(encoding="utf-8", errors="replace",
                              line_buffering=True)
        except (AttributeError, ValueError):
            pass


_consola_utf8()


# --------------------------------------------------------------------------
# Utilidades de consola
# --------------------------------------------------------------------------
def _color(codigo: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return ""
    return codigo


VERDE = _color("\033[32m")
ROJO = _color("\033[31m")
AMARILLO = _color("\033[33m")
GRIS = _color("\033[90m")
FIN = _color("\033[0m")


def info(mensaje: str) -> None:
    print(f"  {mensaje}")


def ok(mensaje: str) -> None:
    print(f"  {VERDE}{mensaje}{FIN}")


def aviso(mensaje: str) -> None:
    print(f"  {AMARILLO}{mensaje}{FIN}")


def error(mensaje: str) -> None:
    print(f"  {ROJO}{mensaje}{FIN}", file=sys.stderr)


def tenue(mensaje: str) -> None:
    print(f"  {GRIS}{mensaje}{FIN}")


# --------------------------------------------------------------------------
# Entorno virtual
# --------------------------------------------------------------------------
def python_del_venv() -> Path:
    if ES_WINDOWS:
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def dentro_del_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == python_del_venv().resolve()
    except OSError:
        return False


def exigir_venv() -> None:
    """Si nos llamaron con el Python del sistema, relanzarse dentro del venv.

    Se relanza con subprocess y no con os.execv: en Windows execv no reemplaza
    el proceso, lanza otro y el original termina de inmediato con codigo 0, de
    modo que se pierden la salida y el codigo de retorno reales.
    """
    if dentro_del_venv():
        return
    destino = python_del_venv()
    if not destino.exists():
        error("No existe el entorno. Corre primero:  python interprete.py instalar")
        sys.exit(1)
    resultado = subprocess.run(
        [str(destino), str(Path(__file__).resolve()), *sys.argv[1:]]
    )
    sys.exit(resultado.returncode)


# --------------------------------------------------------------------------
# Hardware
# --------------------------------------------------------------------------
def hay_nvidia() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        subprocess.run(
            ["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15, check=True,
        )
        return True
    except Exception:
        return False


def nombre_gpu() -> str | None:
    try:
        salida = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader"],
            text=True, timeout=15, stderr=subprocess.DEVNULL,
        )
        return salida.strip().splitlines()[0].strip()
    except Exception:
        return None


# --------------------------------------------------------------------------
# Instalación
# --------------------------------------------------------------------------
URL_CLOUDFLARED = {
    ("Windows", "AMD64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    ("Linux", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("Linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("Darwin", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    ("Darwin", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}


def ruta_cloudflared() -> Path:
    return BIN / ("cloudflared.exe" if ES_WINDOWS else "cloudflared")


def descargar_cloudflared() -> bool:
    destino = ruta_cloudflared()
    if destino.exists():
        return True

    clave = (platform.system(), platform.machine())
    url = URL_CLOUDFLARED.get(clave)
    if url is None:
        aviso(f"No hay binario de cloudflared para {clave[0]}/{clave[1]}.")
        tenue("Instálalo por tu cuenta y déjalo en el PATH, o usa --local.")
        return False

    BIN.mkdir(parents=True, exist_ok=True)
    info(f"Descargando cloudflared para {clave[0]}/{clave[1]}...")
    try:
        if url.endswith(".tgz"):
            import tarfile
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                paquete = Path(tmp) / "cloudflared.tgz"
                urllib.request.urlretrieve(url, paquete)
                with tarfile.open(paquete) as tar:
                    miembro = next(
                        m for m in tar.getmembers() if m.name.endswith("cloudflared")
                    )
                    miembro.name = destino.name
                    tar.extract(miembro, path=destino.parent)
        else:
            urllib.request.urlretrieve(url, destino)
        if not ES_WINDOWS:
            destino.chmod(0o755)
        ok(f"cloudflared listo en {destino.relative_to(RAIZ)}")
        return True
    except (urllib.error.URLError, OSError, StopIteration) as exc:
        error(f"No se pudo descargar cloudflared: {exc}")
        return False


def indice_de_torch(forzar_cpu: bool) -> list[str]:
    """El índice de PyPI del que se baja torch.

    Las ruedas por defecto de PyPI no siempre traen CUDA, y las GPU Blackwell
    (RTX 50xx) necesitan CUDA 12.8 o superior. En macOS no hay CUDA.
    """
    if forzar_cpu or platform.system() == "Darwin" or not hay_nvidia():
        if platform.system() == "Darwin":
            return []  # la rueda normal ya sirve
        return ["--index-url", "https://download.pytorch.org/whl/cpu"]
    return ["--index-url", "https://download.pytorch.org/whl/cu128"]


def instalar(args: argparse.Namespace) -> int:
    if sys.version_info < (3, 10):
        error(f"Se necesita Python 3.10 o superior. Tienes {platform.python_version()}.")
        return 1
    if sys.version_info >= (3, 14):
        aviso(f"Python {platform.python_version()}: puede que torch todavía no "
              "publique ruedas. Si falla, usa Python 3.12.")

    print()
    print(f"  {'Intérprete — instalación'}")
    print(f"  {GRIS}{'-' * 40}{FIN}")

    gpu = nombre_gpu()
    if gpu:
        ok(f"GPU detectada: {gpu}")
    else:
        aviso("Sin GPU NVIDIA. Va a funcionar en CPU, más lento.")
        tenue("Con CPU conviene un modelo pequeño: INTERPRETE_WHISPER_MODEL=small.en")

    if not VENV.exists():
        info(f"Creando entorno virtual en {VENV.name}/ ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)

    pip = [str(python_del_venv()), "-m", "pip"]
    subprocess.run([*pip, "install", "--upgrade", "pip", "--quiet"], check=True)

    indice = indice_de_torch(args.cpu)
    info("Instalando PyTorch" + (" (CUDA 12.8)" if "cu128" in " ".join(indice)
         else " (CPU)") + "... son varios GB, tómate un café.")
    resultado = subprocess.run([*pip, "install", "torch", *indice])
    if resultado.returncode != 0:
        error("Falló la instalación de PyTorch.")
        return 1

    info("Instalando el resto de dependencias...")
    resultado = subprocess.run([*pip, "install", "-r", str(RAIZ / "requirements.txt")])
    if resultado.returncode != 0:
        error("Falló la instalación de dependencias.")
        return 1

    if not args.local:
        descargar_cloudflared()

    info("Descargando los modelos (~3,4 GB la primera vez)...")
    resultado = subprocess.run(
        [str(python_del_venv()), "-c",
         "import sys; sys.path.insert(0, r'%s');"
         "from server.stt import WhisperEngine;"
         "from server.mt import Translator;"
         "WhisperEngine(); Translator();"
         "print('modelos listos')" % str(RAIZ)],
        cwd=str(RAIZ),
    )
    if resultado.returncode != 0:
        error("Falló la descarga de los modelos.")
        return 1

    print()
    ok("Listo. Ahora:  python interprete.py iniciar")
    print()
    return 0


# --------------------------------------------------------------------------
# Supervisión de procesos hijos
# --------------------------------------------------------------------------
class Supervisor:
    """Ata los procesos hijos a la vida de este proceso.

    En Windows se usa un Job Object con KILL_ON_JOB_CLOSE: cuando este proceso
    muere, el sistema operativo termina a los miembros del job, muera como
    muera el padre — incluso si lo matan sin darle oportunidad de limpiar.

    En Linux y macOS no existe un equivalente tan fuerte. Los hijos se ponen en
    su propio grupo de procesos y se matan por grupo desde los manejadores de
    señales; un `kill -9` al lanzador sí deja huérfanos, y para eso está
    `detener`.
    """

    def __init__(self) -> None:
        self.procesos: list[subprocess.Popen] = []
        self._job = None
        if ES_WINDOWS:
            self._crear_job()

    def _crear_job(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class LIMITES_BASICOS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class CONTADORES_IO(ctypes.Structure):
            _fields_ = [(nombre, ctypes.c_uint64) for nombre in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class LIMITES_EXTENDIDOS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", LIMITES_BASICOS),
                ("IoInfo", CONTADORES_IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return

        limites = LIMITES_EXTENDIDOS()
        limites.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(limites), ctypes.sizeof(limites),
        ):
            return

        self._kernel32 = kernel32
        self._job = job

    @property
    def atado(self) -> bool:
        return self._job is not None if ES_WINDOWS else True

    def lanzar(self, orden: list[str], salida: Path, cwd: Path | None = None) -> subprocess.Popen:
        salida.parent.mkdir(parents=True, exist_ok=True)
        destino = salida.open("wb")
        extra: dict = {}
        if not ES_WINDOWS:
            extra["start_new_session"] = True  # su propio grupo, para matarlo entero

        proceso = subprocess.Popen(
            orden, stdout=destino, stderr=subprocess.STDOUT,
            cwd=str(cwd or RAIZ), **extra,
        )
        self.procesos.append(proceso)

        if ES_WINDOWS and self._job is not None:
            import ctypes

            PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
            handle = self._kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proceso.pid,
            )
            if handle:
                self._kernel32.AssignProcessToJobObject(self._job, handle)
                self._kernel32.CloseHandle(handle)
        return proceso

    def detener_todo(self) -> None:
        for proceso in reversed(self.procesos):
            if proceso.poll() is not None:
                continue
            try:
                if ES_WINDOWS:
                    proceso.terminate()
                else:
                    os.killpg(os.getpgid(proceso.pid), signal.SIGTERM)
            except (OSError, PermissionError):
                pass
        for proceso in self.procesos:
            try:
                proceso.wait(timeout=6)
            except subprocess.TimeoutExpired:
                try:
                    proceso.kill()
                except OSError:
                    pass


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------
def esperar_servidor(proceso: subprocess.Popen, segundos: int = 180) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if proceso.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PUERTO}/healthz", timeout=2
            ) as respuesta:
                if json.load(respuesta).get("ready"):
                    return True
        except Exception:
            pass
        time.sleep(0.7)
    return False


PATRON_TUNEL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def esperar_tunel(registro: Path, segundos: int = 45) -> str | None:
    limite = time.time() + segundos
    while time.time() < limite:
        if registro.exists():
            texto = registro.read_text(encoding="utf-8", errors="ignore")
            encontrado = PATRON_TUNEL.search(texto)
            if encontrado:
                return encontrado.group(0)
        time.sleep(0.7)
    return None


def copiar_al_portapapeles(texto: str) -> bool:
    ordenes = {
        "Windows": ["clip"],
        "Darwin": ["pbcopy"],
        "Linux": ["xclip", "-selection", "clipboard"],
    }
    orden = ordenes.get(platform.system())
    if not orden or shutil.which(orden[0]) is None:
        return False
    try:
        subprocess.run(orden, input=texto.encode(), check=True, timeout=5)
        return True
    except Exception:
        return False


def iniciar(args: argparse.Namespace) -> int:
    exigir_venv()

    LOGS.mkdir(parents=True, exist_ok=True)
    log_servidor = LOGS / "servidor.log"
    log_tunel = LOGS / "tunel.log"
    for viejo in (log_servidor, log_tunel):
        viejo.unlink(missing_ok=True)

    supervisor = Supervisor()
    try:
        print()
        print("  Intérprete")
        print(f"  {GRIS}{'-' * 40}{FIN}")
        info("Cargando los modelos en la GPU (la primera vez tarda ~30 s)...")

        servidor = supervisor.lanzar(
            [sys.executable, "-m", "server.main"], log_servidor,
        )
        if not esperar_servidor(servidor):
            error("El servidor no arrancó. Últimas líneas del log:")
            if log_servidor.exists():
                for linea in log_servidor.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()[-25:]:
                    print(f"    {linea}")
            return 1
        ok("Modelos listos.")

        token = ARCHIVO_TOKEN.read_text(encoding="utf-8").strip()

        if args.local:
            url = f"http://127.0.0.1:{PUERTO}/?k={token}"
        else:
            binario = ruta_cloudflared()
            if not binario.exists() and not descargar_cloudflared():
                error("Sin cloudflared no hay túnel. Usa --local, o instálalo.")
                return 1
            info("Abriendo el túnel de Cloudflare...")
            supervisor.lanzar(
                [str(binario), "tunnel", "--no-autoupdate",
                 "--url", f"http://127.0.0.1:{PUERTO}"],
                log_tunel,
            )
            publica = esperar_tunel(log_tunel)
            if not publica:
                error(f"No se pudo abrir el túnel. Revisa {log_tunel}")
                return 1
            url = f"{publica}/?k={token}"

        ARCHIVO_ESTADO.write_text(json.dumps({
            "pid": os.getpid(),
            "url": url,
            "local": bool(args.local),
            "desde": time.time(),
        }), encoding="utf-8")

        print()
        print(f"  {GRIS}{'=' * 64}{FIN}")
        print(f"   {AMARILLO}Abre esta URL en el otro equipo (Chrome o Edge):{FIN}")
        print()
        print(f"   {url}")
        print()
        print(f"  {GRIS}{'=' * 64}{FIN}")
        if copiar_al_portapapeles(url):
            tenue("(copiada al portapapeles)")
        print()
        if supervisor.atado and ES_WINDOWS:
            tenue("Al cerrar esta ventana el servicio se apaga solo.")
        else:
            tenue("Ctrl+C apaga el servicio. Si matas este proceso a la fuerza,")
            tenue("límpialo con: python interprete.py detener")
        print()

        # Espera hasta Ctrl+C o hasta que el servidor se caiga solo.
        while servidor.poll() is None:
            time.sleep(1)
        aviso("El servidor terminó por su cuenta. Revisa logs/servidor.log")
        return 1
    except KeyboardInterrupt:
        print()
        tenue("Apagando...")
        return 0
    finally:
        supervisor.detener_todo()
        ARCHIVO_ESTADO.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Estado y apagado
# --------------------------------------------------------------------------
def responde_el_puerto() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PUERTO}/healthz", timeout=3
        ) as respuesta:
            return bool(json.load(respuesta).get("ready"))
    except Exception:
        return False


def procesos_del_proyecto() -> list[tuple[int, str]]:
    """PIDs cuyo ejecutable vive dentro de esta carpeta.

    Se identifica por la ruta del binario y no por el nombre, para no tocar
    otros Python ni otros cloudflared que el usuario tenga corriendo.
    """
    import psutil

    raiz = str(RAIZ).lower()
    # Este mismo comando corre con el Python del entorno, que vive dentro de la
    # carpeta: sin excluirlo, "estado" se cuenta a si mismo y "detener" se
    # suicidaria antes de apagar el servidor.
    propios = {os.getpid(), os.getppid()}
    encontrados: list[tuple[int, str]] = []
    for proceso in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if proceso.info["pid"] in propios:
                continue
            ruta = proceso.info.get("exe")
            if ruta and ruta.lower().startswith(raiz):
                encontrados.append((proceso.info["pid"], proceso.info["name"] or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return encontrados


def estado(_args: argparse.Namespace) -> int:
    exigir_venv()
    vivos = procesos_del_proyecto()
    listo = responde_el_puerto()
    guardado = {}
    if ARCHIVO_ESTADO.exists():
        try:
            guardado = json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            guardado = {}

    hay_tunel = any("cloudflared" in nombre for _pid, nombre in vivos)
    arriba = listo and bool(vivos)

    print()
    if arriba and (hay_tunel or guardado.get("local")):
        print(f"  {VERDE} ARRIBA {FIN}  el servicio está listo y alcanzable.")
    elif arriba:
        print(f"  {AMARILLO} PARCIAL {FIN}  el servidor corre, pero no hay túnel: "
              "el otro equipo no llega.")
    else:
        print(f"  {ROJO} ABAJO {FIN}  no está corriendo. "
              "Arráncalo con: python interprete.py iniciar")
    print()

    def marca(condicion: bool, texto: str) -> None:
        simbolo = f"{VERDE}[ok]{FIN}" if condicion else f"{GRIS}[--]{FIN}"
        print(f"  {simbolo} {texto if condicion else GRIS + texto + FIN}")

    marca(bool(vivos), f"procesos del proyecto ({len(vivos)})")
    marca(listo, "modelos cargados y puerto respondiendo")
    marca(hay_tunel, "túnel de Cloudflare abierto")

    if arriba and guardado.get("url"):
        print()
        tenue("URL para el otro equipo:")
        print(f"  {guardado['url']}")
    print()
    return 0 if arriba else 1


def detener(_args: argparse.Namespace) -> int:
    exigir_venv()
    vivos = procesos_del_proyecto()
    if not vivos:
        print()
        tenue("No había nada corriendo.")
        print()
        return 0

    for pid, nombre in vivos:
        tenue(f"deteniendo {nombre} (PID {pid})")
        try:
            if ES_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, PermissionError):
            pass

    time.sleep(1.2)
    if not ES_WINDOWS:
        for pid, _nombre in procesos_del_proyecto():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.5)

    ARCHIVO_ESTADO.unlink(missing_ok=True)

    print()
    if responde_el_puerto():
        error(f"El puerto {PUERTO} sigue respondiendo. Algo quedó vivo.")
        print()
        return 1
    ok(f"Servicio detenido ({len(vivos)} proceso(s)). El túnel ya no es alcanzable.")
    print()
    return 0


def probar(args: argparse.Namespace) -> int:
    exigir_venv()
    audio = RAIZ / "logs" / args.audio
    if not audio.exists():
        error(f"No existe {audio}.")
        tenue("Genera los audios de prueba con scripts/generar-audio-prueba.ps1 "
              "(Windows), o pasa la ruta de un WAV mono de 16 kHz.")
        return 1
    return subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "probar.py"), str(audio), args.modo],
        cwd=str(RAIZ),
    ).returncode


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="interprete",
        description="Subtítulos en vivo de una reunión, procesados en tu propia máquina.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("instalar", help="crea el entorno, baja modelos y cloudflared")
    p.add_argument("--cpu", action="store_true",
                   help="instala PyTorch sin CUDA aunque haya GPU NVIDIA")
    p.add_argument("--local", action="store_true",
                   help="no descarga cloudflared (solo uso en esta máquina)")
    p.set_defaults(func=instalar)

    p = sub.add_parser("iniciar", help="levanta el servidor y el túnel público")
    p.add_argument("--local", action="store_true",
                   help="sin túnel: solo accesible desde esta máquina")
    p.set_defaults(func=iniciar)

    p = sub.add_parser("estado", help="dice si está arriba y con qué URL")
    p.set_defaults(func=estado)

    p = sub.add_parser("detener", help="apaga el servidor y el túnel")
    p.set_defaults(func=detener)

    p = sub.add_parser("probar", help="reproduce un WAV contra el servidor")
    p.add_argument("audio", nargs="?", default="prueba2.wav")
    p.add_argument("modo", nargs="?", default="en-es",
                   choices=["en-es", "en-en", "es-es"])
    p.set_defaults(func=probar)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
