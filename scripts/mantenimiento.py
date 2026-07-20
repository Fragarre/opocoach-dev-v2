"""
===============================================================================
Proyecto : OpoCoach
Tipo     : Orquestador de mantenimiento con resumen final
Archivo  : mantenimiento.py
Ubicación:
    scripts/mantenimiento.py

OBJETIVO
--------
Ejecutar secuencialmente los procesos periódicos de mantenimiento y mostrar
al final un resumen único de los cambios realizados.

PROCESO
-------
1. Importar exámenes.
2. Importar tests en formato imagen.
3. Importar preguntas de informática.
4. Eliminar preguntas duplicadas.
5. Normalizar artículos.
6. Auditar la base de datos.

El resumen se calcula directamente comparando el estado de la base de datos
antes y después de cada proceso.

===============================================================================
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
CARPETA_SCRIPTS = RAIZ / "scripts"
RUTA_DB = RAIZ / "db" / "oposiciones.sqlite3"


def contar_preguntas() -> int:
    with sqlite3.connect(RUTA_DB) as conexion:
        return conexion.execute(
            "SELECT COUNT(*) FROM lote_preguntas"
        ).fetchone()[0]


def leer_articulos() -> dict[int, str | None]:
    with sqlite3.connect(RUTA_DB) as conexion:
        return dict(
            conexion.execute(
                """
                SELECT id, articulo
                FROM lote_preguntas
                WHERE tipo_clasificacion = 'JURIDICA'
                """
            ).fetchall()
        )


def ejecutar_paso(nombre: str, script: str) -> bool:
    ruta_script = CARPETA_SCRIPTS / script

    if not ruta_script.is_file():
        print(f"\nERROR: no existe {ruta_script}")
        return False

    print()
    print("=" * 78)
    print(nombre.upper())
    print("=" * 78)

    resultado = subprocess.run(
        [sys.executable, str(ruta_script)],
        cwd=RAIZ,
        check=False,
    )

    if resultado.returncode != 0:
        print(f"\nERROR en {script}. Código de salida: {resultado.returncode}")
        return False

    return True


def mostrar_resumen(
    nuevas_examenes: int,
    nuevas_tests: int,
    nuevas_informatica: int,
    duplicados_eliminados: int,
    articulos_normalizados: int,
    articulos_a_null: int,
    total_preguntas: int,
    inicio: datetime,
    fin: datetime,
) -> None:
    print()
    print("=" * 78)
    print("RESUMEN DEL MANTENIMIENTO")
    print("=" * 78)
    print(f"Preguntas de exámenes añadidas...... {nuevas_examenes}")
    print(f"Preguntas de tests añadidas......... {nuevas_tests}")
    print(f"Preguntas de informática añadidas... {nuevas_informatica}")
    print()
    print(f"Duplicados eliminados............... {duplicados_eliminados}")
    print(f"Artículos normalizados.............. {articulos_normalizados}")
    print(f"Artículos puestos a NULL............ {articulos_a_null}")
    print()
    print(f"Preguntas totales................... {total_preguntas}")
    print(f"Duración............................ {fin - inicio}")
    print("Estado.............................. OK")
    print("=" * 78)


def main() -> int:
    inicio = datetime.now()

    if not RUTA_DB.is_file():
        print(f"No existe la base de datos: {RUTA_DB}")
        return 1

    print("=" * 78)
    print("MANTENIMIENTO OPOCOACH")
    print("=" * 78)
    print(f"Inicio: {inicio:%Y-%m-%d %H:%M:%S}")

    antes = contar_preguntas()
    if not ejecutar_paso("Importar exámenes", "importar_examenes.py"):
        return 1
    despues = contar_preguntas()
    nuevas_examenes = max(0, despues - antes)

    antes = despues
    if not ejecutar_paso("Importar tests en imagen", "importar_tests_imagen.py"):
        return 1
    despues = contar_preguntas()
    nuevas_tests = max(0, despues - antes)

    antes = despues
    if not ejecutar_paso(
        "Importar preguntas de informática",
        "importar_preguntas_informatica.py",
    ):
        return 1
    despues = contar_preguntas()
    nuevas_informatica = max(0, despues - antes)

    antes_depuracion = despues
    if not ejecutar_paso(
        "Eliminar preguntas duplicadas",
        "depurar_preguntas.py",
    ):
        return 1
    despues_depuracion = contar_preguntas()
    duplicados_eliminados = max(
        0,
        antes_depuracion - despues_depuracion,
    )

    articulos_antes = leer_articulos()
    if not ejecutar_paso(
        "Normalizar artículos",
        "normalizar_articulos.py",
    ):
        return 1
    articulos_despues = leer_articulos()

    articulos_normalizados = 0
    articulos_a_null = 0

    for registro_id, valor_antes in articulos_antes.items():
        if registro_id not in articulos_despues:
            continue

        valor_despues = articulos_despues[registro_id]

        if valor_antes == valor_despues:
            continue

        if valor_despues is None:
            articulos_a_null += 1
        else:
            articulos_normalizados += 1

    if not ejecutar_paso(
        "Auditar base de datos",
        "auditar_bd.py",
    ):
        return 1

    fin = datetime.now()
    total_preguntas = contar_preguntas()

    mostrar_resumen(
        nuevas_examenes=nuevas_examenes,
        nuevas_tests=nuevas_tests,
        nuevas_informatica=nuevas_informatica,
        duplicados_eliminados=duplicados_eliminados,
        articulos_normalizados=articulos_normalizados,
        articulos_a_null=articulos_a_null,
        total_preguntas=total_preguntas,
        inicio=inicio,
        fin=fin,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())