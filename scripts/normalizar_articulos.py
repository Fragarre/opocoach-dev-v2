"""
===============================================================================
Proyecto : OpoCoach
Tipo     : Normalización del campo articulo
Archivo  : normalizar_articulos.py
Ubicación:
    scripts/normalizar_articulos.py

OBJETIVO
--------
Normalizar el contenido del campo `articulo` de todas las preguntas
jurídicas.

FORMATO RESULTANTE
------------------
Se admiten exclusivamente formatos como:

    35
    35.1
    35.1.b

Los valores no normalizables se sustituyen por NULL.

PROCEDIMIENTO
-------------
1. Recorre únicamente las preguntas jurídicas.
2. Normaliza el campo articulo.
3. Actualiza únicamente los registros modificados.
4. Solo crea copia de seguridad cuando realmente existen cambios.

IDEMPOTENCIA
------------
Puede ejecutarse repetidamente.
Si todos los artículos ya están normalizados no modifica la base de datos.

BASE DE DATOS
-------------
Requiere la tabla:

    lote_preguntas

No crea ni modifica tablas.

===============================================================================
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
RUTA_DB = RAIZ / "db" / "oposiciones.sqlite3"
CARPETA_COPIAS = RAIZ / "db" / "copias_seguridad"


def normalizar_articulo(valor: str | None) -> str | None:
    if valor is None:
        return None

    texto = " ".join(valor.strip().split())

    if not texto:
        return None

    if re.search(
        r"\bart[ií]culos?\s+\d+\s+y\s+\d+\b",
        texto,
        re.IGNORECASE,
    ):
        return None

    patron = re.compile(
        r"""
        ^
        (?:
            art(?:\.|[ií]culo)?
            \s*
        )?
        (
            \d+
            (?:\.\d+)*
            (?:\.[a-z])?
        )
        (?:\)?\.?)?
        (?:
            \s+de\b.*
        )?
        $
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    coincidencia = patron.fullmatch(texto)

    if coincidencia is None:
        return None

    numero = coincidencia.group(1).rstrip(".")

    if numero.split(".")[0] == "0":
        return None

    return numero.lower()


def crear_copia_seguridad() -> Path:
    CARPETA_COPIAS.mkdir(parents=True, exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = CARPETA_COPIAS / f"oposiciones_antes_articulos_{fecha}.sqlite3"
    shutil.copy2(RUTA_DB, destino)
    return destino


def main() -> int:
    if not RUTA_DB.is_file():
        print(f"No existe la base de datos: {RUTA_DB}")
        return 1

    with sqlite3.connect(RUTA_DB) as conexion:
        conexion.row_factory = sqlite3.Row

        filas = conexion.execute(
            """
            SELECT id, articulo
            FROM lote_preguntas
            WHERE tipo_clasificacion = 'JURIDICA'
            ORDER BY id
            """
        ).fetchall()

        cambios = []
        normalizados = 0
        puestos_a_null = 0
        sin_cambios = 0

        for fila in filas:
            anterior = fila["articulo"]
            nuevo = normalizar_articulo(anterior)

            if nuevo == anterior:
                sin_cambios += 1
                continue

            cambios.append((nuevo, fila["id"], anterior))

            if nuevo is None:
                puestos_a_null += 1
            else:
                normalizados += 1

        copia = None

        if cambios:
            copia = crear_copia_seguridad()

            try:
                conexion.executemany(
                    """
                    UPDATE lote_preguntas
                    SET articulo = ?
                    WHERE id = ?
                    """,
                    [(nuevo, registro_id) for nuevo, registro_id, _ in cambios],
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise

    print()
    print("=" * 65)
    print("NORMALIZACIÓN DEL CAMPO ARTICULO")
    print("=" * 65)
    print(f"Registros jurídicos analizados: {len(filas)}")
    print(f"Normalizados:                  {normalizados}")
    print(f"Puestos a NULL:                {puestos_a_null}")
    print(f"Sin cambios:                   {sin_cambios}")
    print(f"Total modificados:             {len(cambios)}")
    print(
        "Copia de seguridad:            "
        + ("no necesaria" if copia is None else str(copia.relative_to(RAIZ)))
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())