"""
Importa los PDF de data_examenes/modelo y data_examenes/apoyo
en la tabla existente lote_preguntas.

Los PDF sin capa de texto, o con un formato que no pueda extraerse,
se anotan en logs/importar_examenes.log y se pasa al siguiente archivo.

Dependencia:
    pip install pymupdf
"""

from pathlib import Path
import logging
import re
import sqlite3

import fitz


RAIZ = Path(__file__).resolve().parent.parent
CARPETA_EXAMENES = RAIZ / "data_examenes"
RUTA_DB = RAIZ / "db" / "oposiciones.sqlite3"
RUTA_LOG = RAIZ / "logs" / "importar_examenes.log"


PATRON_ARCHIVO = re.compile(
    r"^Examen_(A1|A2|C1|C2)(?:-\d{2})?_\d+_\d{2,4}\.pdf$",
    re.IGNORECASE,
)

PATRON_PREGUNTA = re.compile(
    r"(?ms)^\s*(\d{1,3})\s*[.\-–—)]\s*(.*?)"
    r"(?=^\s*\d{1,3}\s*[.\-–—)]\s*|\Z)"
)

PATRON_OPCIONES = re.compile(
    r"(?ms)^(.*?)"
    r"^\s*A\s*[\)\.\-:]\s*(.*?)"
    r"^\s*B\s*[\)\.\-:]\s*(.*?)"
    r"^\s*C\s*[\)\.\-:]\s*(.*?)"
    r"^\s*D\s*[\)\.\-:]\s*(.*)$"
)

PATRON_ARTICULO = re.compile(
    r"\bart(?:í|i)culo(?:s)?\s+(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

PATRONES_NORMA = [
    re.compile(r"\bLey\s+Orgánica\s+\d+/\d{4}", re.IGNORECASE),
    re.compile(r"\bLey\s+\d+/\d{4}", re.IGNORECASE),
    re.compile(r"\bReal\s+Decreto(?:-ley|\s+Legislativo)?\s+\d+/\d{4}", re.IGNORECASE),
    re.compile(r"\bDecreto(?:-ley|\s+Legislativo)?\s+\d+/\d{4}", re.IGNORECASE),
    re.compile(r"\bConstitución\s+Española\b", re.IGNORECASE),
]


def configurar_log() -> None:
    RUTA_LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(RUTA_LOG, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def limpiar(texto: str) -> str:
    texto = texto.replace("\u00ad", "")
    texto = re.sub(r"-\s*\n\s*(?=\w)", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def leer_pdf(ruta: Path) -> list[str]:
    with fitz.open(ruta) as pdf:
        paginas = [pagina.get_text("text") for pagina in pdf]

    texto_total = "".join(paginas).strip()

    if len(texto_total) < 100:
        raise ValueError("PDF sin capa de texto suficiente; necesita OCR")

    return paginas


def extraer_respuestas(primera_pagina: str) -> dict[int, str]:
    respuestas: dict[int, str] = {}

    for numero, letra in re.findall(
        r"(?im)(?:^|\s)(\d{1,3})\s*[.\-:)]?\s*([ABCD])(?=\s|$)",
        primera_pagina,
    ):
        respuestas[int(numero)] = letra.upper()

    if not respuestas:
        raise ValueError("No se ha podido leer la tabla de soluciones")

    return respuestas


def extraer_preguntas(
    paginas: list[str],
    respuestas: dict[int, str],
) -> list[tuple]:
    texto = "\n".join(paginas[1:])
    resultado = []

    for coincidencia in PATRON_PREGUNTA.finditer(texto):
        numero = int(coincidencia.group(1))
        contenido = coincidencia.group(2).strip()
        opciones = PATRON_OPCIONES.match(contenido)

        if opciones is None:
            continue

        respuesta = respuestas.get(numero)

        if respuesta not in {"A", "B", "C", "D"}:
            logging.warning("Pregunta %s sin respuesta válida; se omite", numero)
            continue

        resultado.append(
            (
                limpiar(opciones.group(1)),
                limpiar(opciones.group(2)),
                limpiar(opciones.group(3)),
                limpiar(opciones.group(4)),
                limpiar(opciones.group(5)),
                respuesta,
            )
        )

    if not resultado:
        raise ValueError("No se han podido extraer preguntas con cuatro opciones")

    return resultado


def detectar_norma(texto: str) -> tuple[str | None, str | None]:
    for patron in PATRONES_NORMA:
        coincidencia = patron.search(texto)
        if coincidencia:
            nombre = limpiar(coincidencia.group(0))

            if nombre.lower().startswith("ley orgánica"):
                tipo = "LEY_ORGANICA"
            elif nombre.lower().startswith("ley "):
                tipo = "LEY"
            elif nombre.lower().startswith("real decreto"):
                tipo = "REAL_DECRETO"
            elif nombre.lower().startswith("decreto"):
                tipo = "DECRETO"
            else:
                tipo = "CONSTITUCION"

            return tipo, nombre

    return None, None


def clasificar(
    enunciado: str,
    opciones: tuple[str, str, str, str],
) -> tuple[str, str | None, str | None, str | None]:
    texto = " ".join((enunciado, *opciones))

    tipo_norma, nombre_norma = detectar_norma(texto)
    coincidencia_articulo = PATRON_ARTICULO.search(texto)
    articulo = coincidencia_articulo.group(1) if coincidencia_articulo else None

    if nombre_norma and articulo:
        return "JURIDICA", tipo_norma, nombre_norma, articulo

    return "PENDIENTE", tipo_norma, nombre_norma, articulo


def existe_pregunta(
    conexion: sqlite3.Connection,
    datos: tuple,
    origen: str,
    fuente: str,
) -> bool:
    return conexion.execute(
        """
        SELECT 1
        FROM lote_preguntas
        WHERE enunciado = ?
          AND opcion_a = ?
          AND opcion_b = ?
          AND opcion_c = ?
          AND opcion_d = ?
          AND respuesta_correcta = ?
          AND origen_oposicion = ?
          AND tipo_fuente = ?
        LIMIT 1
        """,
        (*datos, origen, fuente),
    ).fetchone() is not None


def importar_pdf(
    conexion: sqlite3.Connection,
    ruta: Path,
) -> tuple[int, int]:
    coincidencia = PATRON_ARCHIVO.match(ruta.name)

    if coincidencia is None:
        raise ValueError("Nombre de archivo no reconocido")

    origen = coincidencia.group(1).upper()
    fuente = ruta.parent.name.lower()

    if fuente not in {"modelo", "apoyo"}:
        raise ValueError("El PDF no está en modelo o apoyo")

    paginas = leer_pdf(ruta)
    respuestas = extraer_respuestas(paginas[0])
    preguntas = extraer_preguntas(paginas, respuestas)

    insertadas = 0
    duplicadas = 0

    for datos in preguntas:
        if existe_pregunta(conexion, datos, origen, fuente):
            duplicadas += 1
            continue

        enunciado, a, b, c, d, correcta = datos
        tipo_clasificacion, tipo_norma, nombre_norma, articulo = clasificar(
            enunciado,
            (a, b, c, d),
        )

        conexion.execute(
            """
            INSERT INTO lote_preguntas (
                enunciado,
                opcion_a,
                opcion_b,
                opcion_c,
                opcion_d,
                respuesta_correcta,
                tipo_clasificacion,
                tipo_norma,
                nombre_norma,
                articulo,
                tema_no_juridico,
                origen_oposicion,
                tipo_fuente
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enunciado,
                a,
                b,
                c,
                d,
                correcta,
                tipo_clasificacion,
                tipo_norma,
                nombre_norma,
                articulo,
                None,
                origen,
                fuente,
            ),
        )

        insertadas += 1

    conexion.commit()
    return insertadas, duplicadas


def main() -> None:
    configurar_log()

    if not RUTA_DB.exists():
        raise FileNotFoundError(f"No existe la base de datos: {RUTA_DB}")

    pdfs = sorted(
        ruta
        for carpeta in ("modelo", "apoyo")
        for ruta in (CARPETA_EXAMENES / carpeta).glob("*.pdf")
    )

    total_insertadas = 0
    total_duplicadas = 0
    total_omitidos = 0

    with sqlite3.connect(RUTA_DB) as conexion:
        for ruta in pdfs:
            logging.info("Procesando: %s", ruta.relative_to(RAIZ))

            try:
                insertadas, duplicadas = importar_pdf(conexion, ruta)
                total_insertadas += insertadas
                total_duplicadas += duplicadas

                logging.info(
                    "%s | insertadas=%d | ya existentes=%d",
                    ruta.name,
                    insertadas,
                    duplicadas,
                )

            except Exception as exc:
                conexion.rollback()
                total_omitidos += 1
                logging.error("%s | OMITIDO | %s", ruta.name, exc)

    print()
    print(f"PDF encontrados: {len(pdfs)}")
    print(f"PDF omitidos: {total_omitidos}")
    print(f"Preguntas insertadas: {total_insertadas}")
    print(f"Preguntas ya existentes: {total_duplicadas}")
    print(f"Log: {RUTA_LOG}")


if __name__ == "__main__":
    main()