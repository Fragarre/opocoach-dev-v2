from __future__ import annotations

import re
from typing import Any


def obtener_numero_articulo(titulo: str) -> int | None:
    coincidencia = re.match(
        r"^Artículo\s+(\d+)(?:\.|$)",
        titulo.strip(),
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return None

    return int(coincidencia.group(1))


def obtener_nivel(titulo: str) -> int | None:
    texto = titulo.strip().upper()

    if texto == "TÍTULO PRELIMINAR" or texto.startswith("TÍTULO "):
        return 1

    if texto.startswith("CAPÍTULO "):
        return 2

    if texto.startswith("SECCIÓN "):
        return 3

    return None


def calcular_rangos(
    bloques: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []

    for indice, bloque in enumerate(bloques):
        titulo = str(bloque.get("titulo", "")).strip()
        nivel = obtener_nivel(titulo)

        if nivel is None:
            continue

        articulos: list[int] = []

        for siguiente in bloques[indice + 1 :]:
            titulo_siguiente = str(
                siguiente.get("titulo", "")
            ).strip()

            nivel_siguiente = obtener_nivel(titulo_siguiente)

            if (
                nivel_siguiente is not None
                and nivel_siguiente <= nivel
            ):
                break

            numero = obtener_numero_articulo(titulo_siguiente)

            if numero is not None:
                articulos.append(numero)

        if not articulos:
            continue

        primero = min(articulos)
        ultimo = max(articulos)

        resultado.append(
            {
                "id_bloque": str(bloque.get("id", "")).strip(),
                "titulo": titulo,
                "nivel": nivel,
                "articulo_inicial": primero,
                "articulo_final": ultimo,
                "rango": (
                    str(primero)
                    if primero == ultimo
                    else f"{primero}-{ultimo}"
                ),
            }
        )

    return resultado