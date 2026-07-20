from __future__ import annotations

from typing import Any

from temario.buscador import buscar_por_id, obtener_rangos
from temario.rangos import calcular_rangos


def crear_referencia_juridica(
    estructura: dict[str, Any],
    nombre_norma: str,
    *ids_bloque: str,
) -> dict[str, Any]:
    bloques = estructura.get("bloques", [])
    rangos = calcular_rangos(bloques)

    seleccionados = buscar_por_id(
        rangos,
        *ids_bloque,
    )

    return {
        "nombre_norma": nombre_norma,
        "identificador_oficial": estructura.get(
            "identificador_oficial",
            "",
        ),
        "articulos": obtener_rangos(seleccionados),
    }