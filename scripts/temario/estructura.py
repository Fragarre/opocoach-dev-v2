from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def cargar_estructura(ruta: Path) -> dict[str, Any]:
    """
    Carga el JSON generado por extraer_estructura_norma.py.
    """

    return json.loads(
        ruta.read_text(
            encoding="utf-8"
        )
    )


def obtener_bloques(
    estructura: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Devuelve la lista de bloques de la norma.
    """

    bloques = estructura.get("bloques", [])

    if not isinstance(bloques, list):
        return []

    return bloques


def obtener_identificador(
    estructura: dict[str, Any],
) -> str:
    return estructura.get(
        "identificador_oficial",
        "",
    )