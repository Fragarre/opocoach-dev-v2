from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
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

        rango = (
            str(primero)
            if primero == ultimo
            else f"{primero}-{ultimo}"
        )

        resultado.append(
            {
                "id_bloque": bloque.get("id", ""),
                "titulo": titulo,
                "nivel": nivel,
                "articulo_inicial": primero,
                "articulo_final": ultimo,
                "rango": rango,
            }
        )

    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calcula los rangos de artículos correspondientes "
            "a títulos, capítulos y secciones."
        )
    )

    parser.add_argument(
        "entrada",
        type=Path,
        help="JSON generado por extraer_estructura_norma.py",
    )

    parser.add_argument(
        "--salida",
        type=Path,
        help="Ruta opcional para guardar los rangos en JSON.",
    )

    argumentos = parser.parse_args()

    if not argumentos.entrada.exists():
        print(
            f"No existe el fichero: {argumentos.entrada}",
            file=sys.stderr,
        )
        return 1

    try:
        contenido = json.loads(
            argumentos.entrada.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"No se pudo leer el JSON: {exc}",
            file=sys.stderr,
        )
        return 1

    bloques = contenido.get("bloques")

    if not isinstance(bloques, list):
        print(
            "El JSON no contiene una lista válida de bloques.",
            file=sys.stderr,
        )
        return 1

    rangos = calcular_rangos(bloques)

    print()
    print("RANGOS DE LA NORMA")
    print("=" * 70)

    for elemento in rangos:
        sangria = "  " * (elemento["nivel"] - 1)
        print(
            f'{sangria}{elemento["titulo"]:<30} '
            f'{elemento["rango"]}'
        )

    print("=" * 70)
    print(f"Estructuras encontradas: {len(rangos)}")

    if argumentos.salida:
        salida = {
            "identificador_oficial": contenido.get(
                "identificador_oficial"
            ),
            "rangos": rangos,
        }

        argumentos.salida.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        argumentos.salida.write_text(
            json.dumps(
                salida,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(f"JSON guardado en: {argumentos.salida}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())