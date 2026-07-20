from __future__ import annotations

from typing import Any


def buscar_por_id(
    rangos: list[dict[str, Any]],
    *ids: str,
) -> list[dict[str, Any]]:
    """
    Devuelve los bloques cuyo id coincide.
    """

    ids = {
        i.strip().lower()
        for i in ids
    }

    resultado = []

    for bloque in rangos:
        if (
            str(
                bloque.get(
                    "id_bloque",
                    "",
                )
            ).lower()
            in ids
        ):
            resultado.append(bloque)

    return resultado


def buscar_por_titulo(
    rangos: list[dict[str, Any]],
    *titulos: str,
) -> list[dict[str, Any]]:
    """
    Busca por título completo ignorando mayúsculas.
    """

    titulos = {
        t.strip().upper()
        for t in titulos
    }

    resultado = []

    for bloque in rangos:
        if (
            str(
                bloque.get(
                    "titulo",
                    "",
                )
            ).upper()
            in titulos
        ):
            resultado.append(bloque)

    return resultado


def obtener_rangos(
    bloques: list[dict[str, Any]],
) -> list[str]:
    """
    Devuelve únicamente los rangos.
    """

    return [
        bloque["rango"]
        for bloque in bloques
    ]