import csv
import re
import sqlite3
from collections import Counter
from pathlib import Path

RUTA_DB = Path("db/oposiciones.sqlite3")
RUTA_CSV = Path("registros/auditoria_articulos.csv")


def clasificar_articulo(valor: str | None) -> str:
    if valor is None or not valor.strip():
        return "VACIO"

    texto = " ".join(valor.strip().split())

    if re.fullmatch(r"0", texto):
        return "ARTICULO_CERO"

    if re.fullmatch(r"\d+", texto):
        return "NUMERO_SIMPLE"

    if re.fullmatch(r"\d+(?:\.\d+)+(?:\.[a-z]\)?)?", texto, re.IGNORECASE):
        return "NUMERO_CON_APARTADO"

    if re.fullmatch(r"art[ií]culo\s+\d+", texto, re.IGNORECASE):
        return "ARTICULO_SIMPLE"

    if re.fullmatch(
        r"(?:art\.?|art[ií]culo)\s+\d+(?:\.\d+)+(?:\.[a-z]\)?)?\.?",
        texto,
        re.IGNORECASE,
    ):
        return "ARTICULO_CON_APARTADO"

    if re.search(
        r"\bart[ií]culos?\s+\d+\s+y\s+\d+\b",
        texto,
        re.IGNORECASE,
    ):
        return "VARIOS_ARTICULOS"

    if re.search(
        r"\b(?:t[ií]tulo|cap[ií]tulo|libro|parte|pre[aá]mbulo|disposici[oó]n)\b",
        texto,
        re.IGNORECASE,
    ):
        return "CON_REFERENCIA_ESTRUCTURAL"

    return "FORMATO_DESCONOCIDO"


def main():

    if not RUTA_DB.exists():
        raise SystemExit(f"No existe la base de datos: {RUTA_DB}")

    conexion = sqlite3.connect(RUTA_DB)
    conexion.row_factory = sqlite3.Row

    filas = conexion.execute(
        """
        SELECT
            id,
            nombre_norma,
            articulo,
            enunciado,
            importacion_fichero_id,
            pagina_origen
        FROM lote_preguntas
        WHERE tipo_clasificacion='JURIDICA'
        ORDER BY id
        """
    ).fetchall()

    conexion.close()

    contador = Counter()
    detalle = []

    for fila in filas:

        categoria = clasificar_articulo(fila["articulo"])
        contador[categoria] += 1

        detalle.append(
            {
                "id": fila["id"],
                "categoria": categoria,
                "nombre_norma": fila["nombre_norma"],
                "articulo": fila["articulo"],
                "enunciado": fila["enunciado"],
                "importacion_fichero_id": fila["importacion_fichero_id"],
                "pagina_origen": fila["pagina_origen"],
            }
        )

    RUTA_CSV.parent.mkdir(parents=True, exist_ok=True)

    with RUTA_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "categoria",
                "nombre_norma",
                "articulo",
                "enunciado",
                "importacion_fichero_id",
                "pagina_origen",
            ],
        )

        writer.writeheader()
        writer.writerows(detalle)

    print()
    print("=" * 60)
    print(f"Preguntas jurídicas analizadas: {len(filas)}")
    print("=" * 60)
    print()

    total = len(filas)

    for categoria, cantidad in contador.most_common():

        porcentaje = cantidad * 100 / total

        print(
            f"{categoria:30}"
            f"{cantidad:6}"
            f" ({porcentaje:5.1f}%)"
        )

    problematicos = (
        contador["VACIO"]
        + contador["ARTICULO_CERO"]
        + contador["VARIOS_ARTICULOS"]
        + contador["CON_REFERENCIA_ESTRUCTURAL"]
        + contador["FORMATO_DESCONOCIDO"]
    )

    print()
    print("-" * 60)
    print(f"Casos potencialmente problemáticos: {problematicos}")
    print(f"Informe CSV: {RUTA_CSV}")
    print("-" * 60)


if __name__ == "__main__":
    main()