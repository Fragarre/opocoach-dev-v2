"""
===============================================================================
Nombre del script:
    crear_base_datos_una_tabla.py

Ubicación:
    scripts/crear_base_datos_una_tabla.py

Descripción:
    Crea una base de datos SQLite nueva con una única tabla:
    lote_preguntas.

    El script no modifica una base existente. Si el archivo
    db/oposiciones.sqlite3 ya existe, se detiene para evitar conservar
    tablas anteriores.

Dependencias:
    - Python 3
    - sqlite3
    - pathlib

    Todas las dependencias pertenecen a la biblioteca estándar de Python.
===============================================================================
"""

from pathlib import Path
import sqlite3


RUTA_SCRIPT = Path(__file__).resolve()
RAIZ_PROYECTO = RUTA_SCRIPT.parent.parent
CARPETA_DB = RAIZ_PROYECTO / "db"
RUTA_DB = CARPETA_DB / "oposiciones.sqlite3"


def crear_base_datos() -> None:
    """
    Crea db/oposiciones.sqlite3 con una sola tabla: lote_preguntas.
    """

    CARPETA_DB.mkdir(parents=True, exist_ok=True)

    if RUTA_DB.exists():
        raise FileExistsError(
            f"La base de datos ya existe: {RUTA_DB}\n"
            "Elimínala antes de ejecutar este script."
        )

    try:
        with sqlite3.connect(RUTA_DB) as conexion:
            conexion.execute(
                """
                CREATE TABLE lote_preguntas (
                    id INTEGER PRIMARY KEY,

                    enunciado TEXT NOT NULL,

                    opcion_a TEXT NOT NULL,
                    opcion_b TEXT NOT NULL,
                    opcion_c TEXT NOT NULL,
                    opcion_d TEXT NOT NULL,

                    respuesta_correcta TEXT NOT NULL,

                    tipo_clasificacion TEXT NOT NULL,

                    tipo_norma TEXT,
                    nombre_norma TEXT,
                    articulo TEXT,

                    tema_no_juridico TEXT,

                    origen_oposicion TEXT NOT NULL,

                    tipo_fuente TEXT NOT NULL
                )
                """
            )

            tablas = [
                fila[0]
                for fila in conexion.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    ORDER BY name
                    """
                )
            ]

            if tablas != ["lote_preguntas"]:
                raise RuntimeError(
                    "La base no contiene exactamente una tabla. "
                    f"Tablas encontradas: {tablas}"
                )

            conexion.commit()

    except Exception:
        if RUTA_DB.exists():
            RUTA_DB.unlink()
        raise

    print(f"Base de datos creada: {RUTA_DB}")
    print("Tablas creadas: lote_preguntas")


if __name__ == "__main__":
    crear_base_datos()