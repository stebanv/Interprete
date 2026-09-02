"""Glosario tecnico: protege los terminos que el traductor destroza.

El modelo de traduccion es generalista. Traduce muy bien la conversacion normal
de una entrevista, pero convierte "go live" en "ir a vivir" y "CI pipeline" en
"oleoducto de inteligencia".

La solucion no es corregir la salida (imposible: "la transmision" puede ser
cualquier cosa), sino no dejar que los traduzca. Antes de traducir, cada termino
de TERMINOS se reemplaza por un marcador tipo ZQX7 que el modelo copia tal cual
al espanol; despues se restituye por la forma que se usa de verdad en el gremio.

Comprobado contra el modelo: los marcadores sobreviven la traduccion intactos.

Para agregar un termino basta una linea en TERMINOS: (como suena en ingles,
como quieres leerlo en espanol).
"""

import re

# (patron en ingles, como debe quedar en espanol)
# Solo sustantivos y frases nominales. No metas adjetivos sueltos: al
# protegerlos se rompe la concordancia de genero y numero del espanol.
TERMINOS: list[tuple[str, str]] = [
    # Solo van aqui los terminos que se comprobo que el traductor rompe. Los que
    # ya traduce bien (downtime, stakeholders, onboarding, pipeline, dispatcher,
    # performer, workaround, Orchestrator) se dejan sueltos a proposito: al
    # enmascararlos se pierde la concordancia y empeora la frase entera.
    ("go live", "go live"),
    ("go-live", "go live"),
    ("scope creep", "scope creep"),
    ("task mining", "task mining"),
    ("process mining", "process mining"),
    ("process discovery", "process discovery"),
    ("screen scraping", "screen scraping"),
    ("hotfix", "hotfix"),
    ("hotfixes", "hotfixes"),
    ("pull request", "pull request"),
    ("pull requests", "pull requests"),
    ("hypercare", "hypercare"),
    ("backlog", "backlog"),
    ("citizen developer", "citizen developer"),
    ("citizen developers", "citizen developers"),
    ("shadowing", "shadowing"),
]

# Correcciones sobre el espanol ya traducido, para lo que se cuela igual.
CORRECCIONES: list[tuple[str, str]] = [
    ("oleoducto de inteligencia", "pipeline de CI"),
    ("oleoducto", "pipeline"),
    ("peticion de retirada", "pull request"),
    ("petición de retirada", "pull request"),
    ("solicitud de extraccion", "pull request"),
    ("solicitud de extracción", "pull request"),
    ("robots sin vigilancia", "robots desatendidos"),
    ("robots sin atencion", "robots desatendidos"),
    ("robots sin atención", "robots desatendidos"),
    ("sin vigilancia", "desatendido"),
    ("diseno de artista", "diseño de performer"),
    ("diseño de artista", "diseño de performer"),
    ("marco de trabajo", "framework"),
    ("despachador", "dispatcher"),
    ("cartera de pedidos", "backlog"),
    ("trabajo atrasado", "backlog"),
    ("vuelta atras", "rollback"),
    ("vuelta atrás", "rollback"),
]

_MARCA = "ZQX"
_MARCA_RE = re.compile(rf"{_MARCA}(\d+)")


def _compilar_terminos() -> list[tuple[re.Pattern, str]]:
    # Los mas largos primero: "queue items" debe ganarle a "queue item".
    ordenados = sorted(TERMINOS, key=lambda item: len(item[0]), reverse=True)
    return [
        (re.compile(rf"\b{re.escape(ingles)}\b", re.IGNORECASE), espanol)
        for ingles, espanol in ordenados
    ]


def _compilar_correcciones() -> list[tuple[re.Pattern, str]]:
    ordenadas = sorted(CORRECCIONES, key=lambda item: len(item[0]), reverse=True)
    return [
        (re.compile(rf"\b{re.escape(mal)}\b", re.IGNORECASE), bien)
        for mal, bien in ordenadas
    ]


_TERMINOS_RE = _compilar_terminos()
_CORRECCIONES_RE = _compilar_correcciones()


def proteger(ingles: str) -> tuple[str, dict[str, str]]:
    """Cambia los terminos tecnicos por marcadores. Devuelve (texto, mapa)."""
    mapa: dict[str, str] = {}
    texto = ingles

    for patron, espanol in _TERMINOS_RE:
        def _marcar(match: re.Match, valor: str = espanol) -> str:
            marca = f"{_MARCA}{len(mapa)}"
            if match.group(0)[:1].isupper():
                valor = valor[:1].upper() + valor[1:]
            mapa[marca] = valor
            return marca

        texto = patron.sub(_marcar, texto)

    return texto, mapa


def faltan_marcadores(traducido: str, mapa: dict[str, str]) -> bool:
    """True si el traductor se comio algun marcador (hay que reintentar sin proteccion)."""
    return any(marca not in traducido for marca in mapa)


def restaurar(espanol: str, mapa: dict[str, str]) -> str:
    """Devuelve los terminos reales al texto traducido."""
    if not mapa:
        return espanol

    def _reponer(match: re.Match) -> str:
        return mapa.get(match.group(0), match.group(0))

    return _MARCA_RE.sub(_reponer, espanol)


def corregir(texto: str) -> str:
    """Ultimo pase sobre el espanol, conservando la mayuscula inicial."""
    if not texto:
        return texto

    def _sustituir(match: re.Match, reemplazo: str) -> str:
        original = match.group(0)
        if original[:1].isupper():
            return reemplazo[:1].upper() + reemplazo[1:]
        return reemplazo

    for patron, reemplazo in _CORRECCIONES_RE:
        texto = patron.sub(lambda m, r=reemplazo: _sustituir(m, r), texto)
    return texto
