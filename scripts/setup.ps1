# Atajo a `python interprete.py instalar`, para no perder la costumbre.
# La logica vive en el lanzador multiplataforma; aqui no hay nada que mantener.
python (Join-Path (Split-Path -Parent $PSScriptRoot) "interprete.py") instalar @args
