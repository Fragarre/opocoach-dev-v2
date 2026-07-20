"""
Auditoría breve y relevante de la base de datos de OpoCoach.

Uso:
    python scripts/auditar_bd.py
    python scripts/auditar_bd.py --db db/oposiciones.sqlite3

No modifica la base de datos.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable


def localizar_raiz() -> Path:
    """Busca la raíz del proyecto a partir de la ubicación del script."""
    script = Path(__file__).resolve()
    candidatos = [script.parent.parent, Path.cwd().resolve()]

    for candidato in candidatos:
        if (candidato / "db").is_dir():
            return candidato

    return Path.cwd().resolve()


RAIZ = localizar_raiz()
DB_PREDETERMINADA = RAIZ / "db" / "oposiciones.sqlite3"


def normalizar(texto: str | None) -> str:
    """Normalización conservadora para detectar duplicados textuales."""
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKC", texto)
    texto = texto.casefold()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def clave_pregunta(fila: sqlite3.Row) -> tuple[str, str, str, str, str]:
    return (
        normalizar(fila["enunciado"]),
        normalizar(fila["opcion_a"]),
        normalizar(fila["opcion_b"]),
        normalizar(fila["opcion_c"]),
        normalizar(fila["opcion_d"]),
    )


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def imprimir_conteos(filas: Iterable[sqlite3.Row], etiqueta: str, valor: str) -> None:
    encontrados = False
    for fila in filas:
        encontrados = True
        nombre = fila[etiqueta] if fila[etiqueta] not in (None, "") else "(NULL/vacío)"
        print(f"{str(nombre):<32} {fila[valor]:>8}")
    if not encontrados:
        print("Sin datos")


def obtener_tablas(conexion: sqlite3.Connection) -> set[str]:
    filas = conexion.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {fila[0] for fila in filas}


def auditar(db: Path) -> int:
    if not db.exists():
        print(f"ERROR: no existe la base de datos: {db}")
        return 2

    conexion = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row

    try:
        print("=" * 64)
        print("AUDITORÍA BASE DE DATOS OPOCOACH")
        print("=" * 64)
        print(f"Base de datos: {db.resolve()}")

        tablas = obtener_tablas(conexion)
        requeridas = {"lote_preguntas", "importaciones_ficheros"}
        faltantes = sorted(requeridas - tablas)

        titulo("1. ESTRUCTURA E INTEGRIDAD")
        if faltantes:
            print("ERROR: faltan tablas obligatorias:", ", ".join(faltantes))
            return 1

        integridad = conexion.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"Integridad SQLite.............. {integridad}")

        total_preguntas = conexion.execute(
            "SELECT COUNT(*) FROM lote_preguntas"
        ).fetchone()[0]
        total_importaciones = conexion.execute(
            "SELECT COUNT(*) FROM importaciones_ficheros"
        ).fetchone()[0]
        print(f"Preguntas...................... {total_preguntas}")
        print(f"Importaciones.................. {total_importaciones}")

        titulo("2. DISTRIBUCIÓN DE PREGUNTAS")
        print("Por tipo_fuente:")
        imprimir_conteos(
            conexion.execute(
                """
                SELECT tipo_fuente AS nombre, COUNT(*) AS cantidad
                FROM lote_preguntas
                GROUP BY tipo_fuente
                ORDER BY cantidad DESC, nombre
                """
            ),
            "nombre",
            "cantidad",
        )

        print("\nPor tipo_clasificacion:")
        imprimir_conteos(
            conexion.execute(
                """
                SELECT tipo_clasificacion AS nombre, COUNT(*) AS cantidad
                FROM lote_preguntas
                GROUP BY tipo_clasificacion
                ORDER BY cantidad DESC, nombre
                """
            ),
            "nombre",
            "cantidad",
        )

        print("\nRespuestas correctas:")
        imprimir_conteos(
            conexion.execute(
                """
                SELECT respuesta_correcta AS nombre, COUNT(*) AS cantidad
                FROM lote_preguntas
                GROUP BY respuesta_correcta
                ORDER BY nombre
                """
            ),
            "nombre",
            "cantidad",
        )

        titulo("3. IMPORTACIONES")
        imprimir_conteos(
            conexion.execute(
                """
                SELECT estado AS nombre, COUNT(*) AS cantidad
                FROM importaciones_ficheros
                GROUP BY estado
                ORDER BY cantidad DESC, nombre
                """
            ),
            "nombre",
            "cantidad",
        )

        resumen_paginas = conexion.execute(
            """
            SELECT
                COALESCE(SUM(paginas_totales), 0) AS totales,
                COALESCE(SUM(paginas_insertadas), 0) AS insertadas,
                COALESCE(SUM(paginas_omitidas), 0) AS omitidas,
                COALESCE(SUM(paginas_error), 0) AS errores
            FROM importaciones_ficheros
            """
        ).fetchone()
        print(
            "\nPáginas declaradas/insertadas/"
            f"omitidas/error: {resumen_paginas['totales']} / "
            f"{resumen_paginas['insertadas']} / "
            f"{resumen_paginas['omitidas']} / "
            f"{resumen_paginas['errores']}"
        )

        titulo("4. PROBLEMAS OBJETIVOS")

        consultas = [
            (
                "Respuestas fuera de A/B/C/D",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE UPPER(TRIM(respuesta_correcta)) NOT IN ('A','B','C','D')
                """,
            ),
            (
                "Enunciados vacíos",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE TRIM(COALESCE(enunciado, '')) = ''
                """,
            ),
            (
                "Opciones vacías",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE TRIM(COALESCE(opcion_a, '')) = ''
                   OR TRIM(COALESCE(opcion_b, '')) = ''
                   OR TRIM(COALESCE(opcion_c, '')) = ''
                   OR TRIM(COALESCE(opcion_d, '')) = ''
                """,
            ),
            (
                "Sin tipo_clasificacion",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE TRIM(COALESCE(tipo_clasificacion, '')) = ''
                """,
            ),
            (
                "Sin tipo_fuente",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE TRIM(COALESCE(tipo_fuente, '')) = ''
                """,
            ),
            (
                "Con importación inexistente",
                """
                SELECT COUNT(*)
                FROM lote_preguntas lp
                LEFT JOIN importaciones_ficheros i
                  ON i.id = lp.importacion_fichero_id
                WHERE lp.importacion_fichero_id IS NOT NULL
                  AND i.id IS NULL
                """,
            ),
            (
                "Importadas sin página de origen",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE importacion_fichero_id IS NOT NULL
                  AND pagina_origen IS NULL
                """,
            ),
            (
                "Página de origen no positiva",
                """
                SELECT COUNT(*) FROM lote_preguntas
                WHERE pagina_origen IS NOT NULL
                  AND pagina_origen <= 0
                """,
            ),
        ]

        problemas = 0
        for nombre, sql in consultas:
            cantidad = conexion.execute(sql).fetchone()[0]
            problemas += cantidad
            marca = "OK" if cantidad == 0 else "REVISAR"
            print(f"{nombre:<40} {cantidad:>7}  {marca}")

        filas = conexion.execute(
            """
            SELECT id, enunciado, opcion_a, opcion_b, opcion_c, opcion_d,
                   respuesta_correcta, tipo_clasificacion, tema_no_juridico,
                   tipo_fuente
            FROM lote_preguntas
            ORDER BY id
            """
        ).fetchall()

        grupos: dict[tuple[str, str, str, str, str], list[sqlite3.Row]] = {}
        for fila in filas:
            grupos.setdefault(clave_pregunta(fila), []).append(fila)

        duplicados = [grupo for grupo in grupos.values() if len(grupo) > 1]
        respuestas_conflictivas = [
            grupo
            for grupo in duplicados
            if len(
                {
                    normalizar(fila["respuesta_correcta"]).upper()
                    for fila in grupo
                }
            )
            > 1
        ]
        clasificaciones_conflictivas = [
            grupo
            for grupo in duplicados
            if len(
                {
                    (
                        normalizar(fila["tipo_clasificacion"]),
                        normalizar(fila["tema_no_juridico"]),
                    )
                    for fila in grupo
                }
            )
            > 1
        ]

        repetidos_sobrantes = sum(len(grupo) - 1 for grupo in duplicados)
        print(f"{'Duplicados exactos normalizados':<40} {len(duplicados):>7}")
        print(f"{'Registros duplicados sobrantes':<40} {repetidos_sobrantes:>7}")
        print(f"{'Duplicados con respuesta distinta':<40} {len(respuestas_conflictivas):>7}")
        print(f"{'Duplicados con clasificación distinta':<40} {len(clasificaciones_conflictivas):>7}")

        titulo("5. TEMAS NO JURÍDICOS")
        temas = conexion.execute(
            """
            SELECT tema_no_juridico AS nombre, COUNT(*) AS cantidad
            FROM lote_preguntas
            WHERE TRIM(COALESCE(tema_no_juridico, '')) <> ''
            GROUP BY tema_no_juridico
            ORDER BY cantidad DESC, nombre
            """
        ).fetchall()
        imprimir_conteos(temas, "nombre", "cantidad")

        titulo("6. MUESTRAS PARA REVISIÓN")
        if respuestas_conflictivas:
            print("Duplicados con respuestas distintas:")
            for grupo in respuestas_conflictivas[:10]:
                ids = ", ".join(str(fila["id"]) for fila in grupo)
                respuestas = ", ".join(
                    f"{fila['id']}={fila['respuesta_correcta']}" for fila in grupo
                )
                print(f"  IDs {ids} | {respuestas}")
        else:
            print("No hay duplicados con respuestas distintas.")

        importaciones_problematicas = conexion.execute(
            """
            SELECT id, nombre_fichero, estado, paginas_error, ultimo_error
            FROM importaciones_ficheros
            WHERE UPPER(TRIM(estado)) NOT IN ('COMPLETADA', 'COMPLETADO')
               OR COALESCE(paginas_error, 0) > 0
               OR TRIM(COALESCE(ultimo_error, '')) <> ''
            ORDER BY id
            LIMIT 20
            """
        ).fetchall()

        if importaciones_problematicas:
            print("\nImportaciones que requieren revisión:")
            for fila in importaciones_problematicas:
                error = normalizar(fila["ultimo_error"])
                if len(error) > 100:
                    error = error[:97] + "..."
                print(
                    f"  ID {fila['id']} | {fila['nombre_fichero']} | "
                    f"estado={fila['estado']} | errores={fila['paginas_error']} | "
                    f"{error or 'sin detalle'}"
                )
        else:
            print("\nNo hay importaciones problemáticas.")

        titulo("RESULTADO")
        incidencias_criticas = (
            (integridad.lower() != "ok")
            + conexion.execute(consultas[0][1]).fetchone()[0]
            + conexion.execute(consultas[1][1]).fetchone()[0]
            + conexion.execute(consultas[2][1]).fetchone()[0]
            + conexion.execute(consultas[5][1]).fetchone()[0]
            + len(respuestas_conflictivas)
        )

        if incidencias_criticas:
            print(f"REVISAR: se han detectado {incidencias_criticas} incidencias críticas.")
            return 1

        if problemas or duplicados or importaciones_problematicas:
            print("ADVERTENCIA: la base es íntegra, pero hay datos que conviene revisar.")
            return 0

        print("OK: no se han detectado incidencias relevantes.")
        return 0

    finally:
        conexion.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auditoría breve, de solo lectura, de la base de datos de OpoCoach."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PREDETERMINADA,
        help=f"Ruta de la base de datos (por defecto: {DB_PREDETERMINADA})",
    )
    args = parser.parse_args()
    return auditar(args.db.resolve())


if __name__ == "__main__":
    raise SystemExit(main())