# Atajo a `python interprete.py estado`, para no perder la costumbre.
# La logica vive en el lanzador multiplataforma; aqui no hay nada que mantener.
python (Join-Path (Split-Path -Parent $PSScriptRoot) "interprete.py") estado @args
