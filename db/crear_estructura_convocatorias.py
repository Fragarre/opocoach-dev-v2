"""Crea las tablas de convocatorias sin alterar las existentes."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

SQL_FILE = Path(__file__).with_name("crear_estructura_convocatorias.sql")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crea la estructura de convocatorias en una base SQLite existente."
    )
    parser.add_argument("base_datos", type=Path, help="Ruta del archivo SQLite")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.base_datos.expanduser().resolve()

    if not db_path.exists():
        print(f"ERROR: no existe la base de datos: {db_path}", file=sys.stderr)
        return 1

    try:
        schema = SQL_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR leyendo {SQL_FILE}: {exc}", file=sys.stderr)
        return 2

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(schema)
    except sqlite3.Error as exc:
        print(f"ERROR SQLite: {exc}", file=sys.stderr)
        return 3

    print("=" * 60)
    print("ESTRUCTURA DE CONVOCATORIAS CREADA")
    print("=" * 60)
    print(f"Base de datos: {db_path}")
    print("Tablas creadas o verificadas: 7")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())