# Atajo a `python interprete.py detener`, para no perder la costumbre.
# La logica vive en el lanzador multiplataforma; aqui no hay nada que mantener.
python (Join-Path (Split-Path -Parent $PSScriptRoot) "interprete.py") detener @args
