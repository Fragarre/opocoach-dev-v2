from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests


BASE_URL = (
    "https://www.boe.es/datosabiertos/api/"
    "legislacion-consolidada/id/{boe_id}/texto/indice"
)


def obtener_indice(boe_id: str) -> dict[str, Any]:
    url = BASE_URL.format(boe_id=boe_id)

    try:
        respuesta = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "OpoCoach/1.0",
            },
            timeout=30,
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"No se pudo consultar la API del BOE: {exc}"
        ) from exc

    try:
        return respuesta.json()
    except ValueError as exc:
        raise RuntimeError(
            "La API del BOE no devolvió un JSON válido."
        ) from exc


def extraer_bloques(datos: dict[str, Any]) -> list[dict[str, str]]:
    """
    Busca recursivamente una lista llamada 'bloque' dentro de la
    respuesta JSON de la API del BOE.
    """

    def buscar_bloques(elemento: Any) -> list[dict[str, Any]] | None:
        if isinstance(elemento, dict):
            bloques = elemento.get("bloque")

            if isinstance(bloques, list):
                return bloques

            if isinstance(bloques, dict):
                return [bloques]

            for valor in elemento.values():
                encontrados = buscar_bloques(valor)
                if encontrados is not None:
                    return encontrados

        elif isinstance(elemento, list):
            for valor in elemento:
                encontrados = buscar_bloques(valor)
                if encontrados is not None:
                    return encontrados

        return None

    bloques_originales = buscar_bloques(datos)

    if not bloques_originales:
        return []

    resultado: list[dict[str, str]] = []

    for bloque in bloques_originales:
        if not isinstance(bloque, dict):
            continue

        resultado.append(
            {
                "id": str(bloque.get("id", "")).strip(),
                "titulo": str(bloque.get("titulo", "")).strip(),
                "fecha_actualizacion": str(
                    bloque.get("fecha_actualizacion", "")
                ).strip(),
                "url": str(bloque.get("url", "")).strip(),
            }
        )

    return resultado

def obtener_numero_articulo(titulo: str) -> str | None:
    patron = re.compile(
        r"^Artículo\s+"
        r"(\d+(?:\s*(?:bis|ter|quáter|quinquies|sexies))?)"
        r"(?:\.|$)",
        re.IGNORECASE,
    )

    coincidencia = patron.match(titulo.strip())

    if not coincidencia:
        return None

    return re.sub(r"\s+", " ", coincidencia.group(1)).strip()


def mostrar_bloques(bloques: list[dict[str, str]]) -> None:
    print()
    print("ESTRUCTURA DE LA NORMA")
    print("=" * 70)

    total_articulos = 0

    for bloque in bloques:
        titulo = bloque["titulo"]
        numero = obtener_numero_articulo(titulo)

        if numero is not None:
            total_articulos += 1
            marca = f"ARTÍCULO {numero}"
        else:
            marca = bloque["id"]

        print(f"{marca:<18} {titulo}")

    print("=" * 70)
    print(f"Bloques totales:   {len(bloques)}")
    print(f"Artículos totales: {total_articulos}")


def guardar_json(
    boe_id: str,
    bloques: list[dict[str, str]],
    ruta_salida: Path,
) -> None:
    articulos = []

    for bloque in bloques:
        numero = obtener_numero_articulo(bloque["titulo"])

        if numero is not None:
            articulos.append(
                {
                    "articulo": numero,
                    "id_bloque": bloque["id"],
                    "titulo": bloque["titulo"],
                    "url": bloque["url"],
                }
            )

    contenido = {
        "identificador_oficial": boe_id,
        "bloques": bloques,
        "articulos": articulos,
    }

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    ruta_salida.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nJSON guardado en: {ruta_salida}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Obtiene el índice de una norma consolidada mediante "
            "la API oficial del BOE."
        )
    )

    parser.add_argument(
        "boe_id",
        help="Identificador oficial, por ejemplo BOE-A-1978-31229",
    )

    parser.add_argument(
        "--salida",
        type=Path,
        help="Ruta opcional donde guardar el resultado JSON.",
    )

    argumentos = parser.parse_args()

    boe_id = argumentos.boe_id.strip().upper()

    if not re.fullmatch(r"BOE-[A-Z]-\d{4}-\d+", boe_id):
        print(
            f"Identificador BOE no válido: {boe_id}",
            file=sys.stderr,
        )
        return 1


    try:
        datos = obtener_indice(boe_id)
        bloques = extraer_bloques(datos)
    except RuntimeError as exc:

        if not bloques:
            print("La norma no contiene bloques.", file=sys.stderr)
            return 1

    mostrar_bloques(bloques)

    if argumentos.salida:
        guardar_json(boe_id, bloques, argumentos.salida)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())