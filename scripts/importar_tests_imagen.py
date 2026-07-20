"""
===============================================================================
Proyecto : OpoCoach
Tipo     : Importación de preguntas desde PDF-imagen
Archivo  : importar_tests_imagen.py
Ubicación:
    scripts/importar_tests_imagen.py

OBJETIVO
--------
Importar en `lote_preguntas` las preguntas contenidas en PDF de
`data_preguntas`, manteniendo trazabilidad de cada fichero mediante
`importaciones_ficheros`.

MODOS DE EJECUCIÓN
------------------
1. Importar todos los PDF de `data_preguntas`:

       python scripts/importar_tests_imagen.py

2. Importar únicamente un PDF concreto:

       python scripts/importar_tests_imagen.py --pdf C2_4.pdf

   También se admite una ruta relativa o absoluta:

       python scripts/importar_tests_imagen.py --pdf data_preguntas/C2_4.pdf

3. Forzar la reimportación de un PDF ya registrado:

       python scripts/importar_tests_imagen.py --pdf C2_4.pdf --forzar

   `--forzar` solo se admite junto con `--pdf`.

TRAZABILIDAD E IDEMPOTENCIA
---------------------------
1. Antes de abrir o enviar páginas a la IA se calcula el SHA-256 del PDF.

2. Cada PDF queda registrado en `importaciones_ficheros` con:
   - ruta relativa;
   - nombre;
   - hash SHA-256;
   - tipo de fuente;
   - estado;
   - páginas totales, insertadas, omitidas y con error;
   - fechas de inicio y fin;
   - último error.

3. Un fichero con el mismo hash y estado `COMPLETADO` se salta por completo:
   no se abre, no se recorren sus páginas y no se llama a la IA.

4. Un fichero se vuelve a procesar cuando:
   - se usa `--forzar`;
   - su fila tiene `reimportar = 1`;
   - no está completado;
   - o su contenido ha cambiado y, por tanto, tiene otro hash.

5. Al forzar una importación ya trazada:
   - se eliminan únicamente las preguntas vinculadas a esa importación;
   - se reutiliza la fila de `importaciones_ficheros`;
   - se procesan de nuevo todas sus páginas;
   - `reimportar` vuelve a 0 al finalizar.

6. Cada pregunta nueva guarda:
   - `importacion_fichero_id`;
   - `pagina_origen`.

7. La comprobación de pregunta duplicada se mantiene para evitar duplicar en
   el banco una pregunta idéntica que ya aparezca en otro fichero.

CRITERIOS DE IMPORTACIÓN
------------------------
1. Cada página se trata como una pregunta independiente.

2. `origen_oposicion` se obtiene de los dos primeros caracteres del fichero:
   A1, A2, C1 o C2.

3. `tipo_fuente` es siempre `tests`.

4. Preguntas jurídicas:
   - solo se importan si el pie identifica expresamente norma y
     artículo/apartado;
   - no se deducen datos jurídicos ausentes.

5. Preguntas de informática:
   - si el pie contiene clasificación, se usa;
   - si no hay pie, se clasifica por el tema informático;
   - se importan sin tipo de norma, nombre de norma ni artículo.

6. Otras preguntas no jurídicas no se importan.

7. La respuesta correcta se obtiene exclusivamente del recuadro verde.

8. Un error en una página no detiene las demás páginas ni los demás PDF.

9. La IA se llama mediante la utilidad existente `openai_api.py`.

10. El coste se registra en:
        registros/coste_ia.csv

11. El script exige que ya existan:
    - `lote_preguntas`;
    - `importaciones_ficheros`;
    - las columnas `importacion_fichero_id` y `pagina_origen`.

    El script no crea ni altera tablas.

DEPENDENCIAS
------------
    pip install pymupdf openai python-dotenv

===============================================================================
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


# =============================================================================
# RUTAS Y CONSTANTES
# =============================================================================

RUTA_SCRIPT = Path(__file__).resolve()
RAIZ = RUTA_SCRIPT.parent.parent

CARPETA_PDF = RAIZ / "data_preguntas"
RUTA_DB = RAIZ / "db" / "oposiciones.sqlite3"
RUTA_LOG = RAIZ / "logs" / "importar_tests_imagen.log"
RUTA_COSTES = RAIZ / "registros" / "coste_ia.csv"

TIPO_FUENTE = "tests"
MODELO = "gpt-5.4-mini"
OPERACION_IA = "importar_test_imagen"

VERSION_SCRIPT = "2026-07-19-idempotencia-v4"

COLUMNAS_LOTE_ESPERADAS = {
    "id",
    "enunciado",
    "opcion_a",
    "opcion_b",
    "opcion_c",
    "opcion_d",
    "respuesta_correcta",
    "tipo_clasificacion",
    "tipo_norma",
    "nombre_norma",
    "articulo",
    "tema_no_juridico",
    "origen_oposicion",
    "tipo_fuente",
    "importacion_fichero_id",
    "pagina_origen",
}

COLUMNAS_IMPORTACION_ESPERADAS = {
    "id",
    "ruta_relativa",
    "nombre_fichero",
    "hash_sha256",
    "tipo_fuente",
    "estado",
    "paginas_totales",
    "paginas_insertadas",
    "paginas_omitidas",
    "paginas_error",
    "fecha_inicio",
    "fecha_fin",
    "reimportar",
    "ultimo_error",
}


# =============================================================================
# ARGUMENTOS Y CONFIGURACIÓN
# =============================================================================

def leer_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importa un PDF concreto o todos los PDF de data_preguntas."
        )
    )
    parser.add_argument(
        "--pdf",
        help=(
            "Nombre o ruta del único PDF que se desea procesar. "
            "Si se omite, se procesa toda la carpeta data_preguntas."
        ),
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help=(
            "Reimporta el PDF aunque ya figure como completado. "
            "Solo puede usarse junto con --pdf."
        ),
    )

    args = parser.parse_args()

    if args.forzar and not args.pdf:
        parser.error("--forzar requiere indicar también --pdf.")

    return args


def configurar_logging() -> None:
    RUTA_LOG.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(RUTA_LOG, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def cargar_utilidad_openai():
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))

    errores: list[str] = []

    for modulo in ("core.openai_api", "scripts.openai_api"):
        try:
            utilidad = importlib.import_module(modulo)
            utilidad.LOG_COSTES = RUTA_COSTES
            RUTA_COSTES.parent.mkdir(parents=True, exist_ok=True)
            return utilidad
        except ModuleNotFoundError as exc:
            errores.append(f"{modulo}: {exc}")

    raise ImportError(
        "No se encuentra openai_api.py en core ni en scripts.\n"
        + "\n".join(errores)
    )


# =============================================================================
# SELECCIÓN EXACTA DE PDF
# =============================================================================

def resolver_pdf_indicado(valor: str) -> Path:
    """
    Resuelve exactamente el fichero indicado.

    Orden:
    1. ruta absoluta;
    2. ruta relativa a la raíz del proyecto;
    3. nombre relativo a data_preguntas.
    """
    entrada = Path(valor).expanduser()

    candidatos: list[Path] = []

    if entrada.is_absolute():
        candidatos.append(entrada)
    else:
        candidatos.append(RAIZ / entrada)
        candidatos.append(CARPETA_PDF / entrada)

    vistos: set[Path] = set()

    for candidato in candidatos:
        resuelto = candidato.resolve()

        if resuelto in vistos:
            continue
        vistos.add(resuelto)

        if resuelto.is_file():
            if resuelto.suffix.lower() != ".pdf":
                raise ValueError(
                    f"El archivo indicado no es un PDF: {resuelto}"
                )
            return resuelto

    rutas = "\n".join(f"  - {ruta.resolve()}" for ruta in candidatos)
    raise FileNotFoundError(
        f"No se encuentra el PDF indicado: {valor}\n"
        f"Rutas comprobadas:\n{rutas}"
    )


def obtener_pdfs(pdf_indicado: str | None) -> list[Path]:
    if pdf_indicado:
        return [resolver_pdf_indicado(pdf_indicado)]

    if not CARPETA_PDF.is_dir():
        raise FileNotFoundError(
            f"No existe la carpeta de entrada: {CARPETA_PDF}"
        )

    pdfs = sorted(
        (
            ruta.resolve()
            for ruta in CARPETA_PDF.iterdir()
            if ruta.is_file() and ruta.suffix.lower() == ".pdf"
        ),
        key=lambda ruta: ruta.name.casefold(),
    )

    if not pdfs:
        raise FileNotFoundError(
            f"No hay archivos PDF en: {CARPETA_PDF}"
        )

    return pdfs


# =============================================================================
# VALIDACIÓN DE BASE DE DATOS
# =============================================================================

def columnas_tabla(
    conexion: sqlite3.Connection,
    tabla: str,
) -> set[str]:
    return {
        fila[1]
        for fila in conexion.execute(f"PRAGMA table_info({tabla})")
    }


def validar_base_datos(conexion: sqlite3.Connection) -> None:
    tablas = {
        fila[0]
        for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    for tabla in ("lote_preguntas", "importaciones_ficheros"):
        if tabla not in tablas:
            raise RuntimeError(f"No existe la tabla {tabla}.")

    faltantes_lote = (
        COLUMNAS_LOTE_ESPERADAS
        - columnas_tabla(conexion, "lote_preguntas")
    )
    faltantes_importacion = (
        COLUMNAS_IMPORTACION_ESPERADAS
        - columnas_tabla(conexion, "importaciones_ficheros")
    )

    if faltantes_lote:
        raise RuntimeError(
            "Faltan columnas en lote_preguntas: "
            + ", ".join(sorted(faltantes_lote))
        )

    if faltantes_importacion:
        raise RuntimeError(
            "Faltan columnas en importaciones_ficheros: "
            + ", ".join(sorted(faltantes_importacion))
        )


# =============================================================================
# IDENTIFICACIÓN DEL FICHERO
# =============================================================================

def obtener_origen(nombre_pdf: str) -> str:
    coincidencia = re.match(
        r"^(A1|A2|C1|C2)",
        nombre_pdf,
        re.IGNORECASE,
    )

    if coincidencia is None:
        raise ValueError(
            "El nombre del PDF no empieza por A1, A2, C1 o C2: "
            f"{nombre_pdf}"
        )

    return coincidencia.group(1).upper()


def calcular_sha256(ruta: Path) -> str:
    digest = hashlib.sha256()

    with ruta.open("rb") as fichero:
        while bloque := fichero.read(1024 * 1024):
            digest.update(bloque)

    return digest.hexdigest()


def ruta_relativa_proyecto(ruta: Path) -> str:
    try:
        return ruta.resolve().relative_to(RAIZ.resolve()).as_posix()
    except ValueError:
        return str(ruta.resolve())


def ahora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# =============================================================================
# TRAZABILIDAD DE IMPORTACIONES
# =============================================================================

def buscar_importacion(
    conexion: sqlite3.Connection,
    hash_sha256: str,
) -> sqlite3.Row | None:
    return conexion.execute(
        """
        SELECT *
        FROM importaciones_ficheros
        WHERE hash_sha256 = ?
          AND tipo_fuente = ?
        LIMIT 1
        """,
        (hash_sha256, TIPO_FUENTE),
    ).fetchone()


def crear_importacion(
    conexion: sqlite3.Connection,
    ruta_pdf: Path,
    hash_sha256: str,
    paginas_totales: int,
) -> int:
    cursor = conexion.execute(
        """
        INSERT INTO importaciones_ficheros (
            ruta_relativa,
            nombre_fichero,
            hash_sha256,
            tipo_fuente,
            estado,
            paginas_totales,
            paginas_insertadas,
            paginas_omitidas,
            paginas_error,
            fecha_inicio,
            fecha_fin,
            reimportar,
            ultimo_error
        )
        VALUES (?, ?, ?, ?, 'EN_PROCESO', ?, 0, 0, 0, ?, NULL, 0, NULL)
        """,
        (
            ruta_relativa_proyecto(ruta_pdf),
            ruta_pdf.name,
            hash_sha256,
            TIPO_FUENTE,
            paginas_totales,
            ahora_iso(),
        ),
    )
    conexion.commit()
    return int(cursor.lastrowid)


def preparar_reimportacion(
    conexion: sqlite3.Connection,
    importacion_id: int,
    ruta_pdf: Path,
    paginas_totales: int,
) -> None:
    """
    Elimina únicamente las preguntas cuya procedencia es esa importación.
    No toca preguntas iguales procedentes de otros ficheros.
    """
    conexion.execute(
        """
        DELETE FROM lote_preguntas
        WHERE importacion_fichero_id = ?
        """,
        (importacion_id,),
    )

    conexion.execute(
        """
        UPDATE importaciones_ficheros
        SET ruta_relativa = ?,
            nombre_fichero = ?,
            estado = 'EN_PROCESO',
            paginas_totales = ?,
            paginas_insertadas = 0,
            paginas_omitidas = 0,
            paginas_error = 0,
            fecha_inicio = ?,
            fecha_fin = NULL,
            reimportar = 0,
            ultimo_error = NULL
        WHERE id = ?
        """,
        (
            ruta_relativa_proyecto(ruta_pdf),
            ruta_pdf.name,
            paginas_totales,
            ahora_iso(),
            importacion_id,
        ),
    )
    conexion.commit()


def finalizar_importacion(
    conexion: sqlite3.Connection,
    importacion_id: int,
    totales: dict[str, int],
) -> None:
    estado = "COMPLETADO" if totales["errores"] == 0 else "COMPLETADO_CON_ERRORES"

    conexion.execute(
        """
        UPDATE importaciones_ficheros
        SET estado = ?,
            paginas_insertadas = ?,
            paginas_omitidas = ?,
            paginas_error = ?,
            fecha_fin = ?,
            reimportar = 0,
            ultimo_error = NULL
        WHERE id = ?
        """,
        (
            estado,
            totales["insertadas"],
            totales["omitidas"],
            totales["errores"],
            ahora_iso(),
            importacion_id,
        ),
    )
    conexion.commit()


def registrar_error_fichero(
    conexion: sqlite3.Connection,
    importacion_id: int,
    mensaje: str,
) -> None:
    conexion.execute(
        """
        UPDATE importaciones_ficheros
        SET estado = 'ERROR',
            fecha_fin = ?,
            ultimo_error = ?
        WHERE id = ?
        """,
        (ahora_iso(), mensaje[:4000], importacion_id),
    )
    conexion.commit()


# =============================================================================
# IMAGEN Y LLAMADA A IA
# =============================================================================

def renderizar_pagina(pagina: fitz.Page) -> bytes:
    matriz = fitz.Matrix(2.0, 2.0)
    pixmap = pagina.get_pixmap(matrix=matriz, alpha=False)
    return pixmap.tobytes("png")


def construir_entrada_ia(
    imagen_png: bytes,
    numero_pagina: int,
) -> list[dict]:
    imagen_b64 = base64.b64encode(imagen_png).decode("ascii")

    instrucciones = f"""
Analiza la imagen de la página {numero_pagina} de un test.

Debes transcribir únicamente lo que se ve. No completes, no deduzcas y no
corrijas contenidos jurídicos.

Devuelve exclusivamente un objeto JSON válido, sin Markdown y con estas claves:

{{
  "valida": true,
  "motivo": "",
  "numero_visible": "",
  "enunciado": "",
  "opcion_a": "",
  "opcion_b": "",
  "opcion_c": "",
  "opcion_d": "",
  "respuesta_correcta": "A",
  "clase": "JURIDICA",
  "pie_literal": "",
  "tipo_norma": "",
  "nombre_norma": "",
  "articulo_apartado": "",
  "tema_informatica": ""
}}

Reglas obligatorias:

1. "respuesta_correcta" debe ser la letra cuyo recuadro está relleno de verde.
   No resuelvas la pregunta por conocimientos propios.

2. "clase" solo puede ser:
   - "JURIDICA"
   - "INFORMATICA"
   - "OTRA"

3. Para una pregunta jurídica:
   - copia en "pie_literal" el texto del pie;
   - "nombre_norma" y "articulo_apartado" solo pueden proceder del pie;
   - no uses el enunciado ni las opciones para suplir datos ausentes;
   - "tipo_norma" debe recoger el tipo que aparece en el pie;
   - si el pie no contiene expresamente norma y artículo/apartado, conserva
     vacío el dato que falte.

4. Para informática:
   - si hay pie, usa su clasificación en "tema_informatica";
   - si no hay pie, indica el tema informático tratado;
   - no rellenes tipo_norma, nombre_norma ni articulo_apartado.

5. Para cualquier otra materia no jurídica:
   - usa "clase": "OTRA".

6. "valida" será false cuando no puedan leerse con seguridad el enunciado,
   las cuatro opciones o el recuadro verde de la respuesta correcta.
   Explica la causa en "motivo".

7. No incluyas texto ajeno a la pregunta, como botones de la interfaz.
""".strip()

    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": instrucciones},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{imagen_b64}",
                },
            ],
        }
    ]


def limpiar_json_respuesta(texto: str) -> dict[str, Any]:
    texto = texto.strip()

    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

    datos = json.loads(texto)

    if not isinstance(datos, dict):
        raise ValueError("La IA no devolvió un objeto JSON.")

    return datos


def analizar_pagina(
    utilidad_openai,
    imagen_png: bytes,
    numero_pagina: int,
) -> dict[str, Any]:
    entrada = construir_entrada_ia(imagen_png, numero_pagina)

    respuesta, _ = utilidad_openai.llamar_responses(
        input_api=entrada,
        modelo=MODELO,
        operacion=OPERACION_IA,
    )

    return limpiar_json_respuesta(respuesta.output_text)


# =============================================================================
# NORMALIZACIÓN Y DECISIÓN DE IMPORTACIÓN
# =============================================================================

def texto_limpio(valor: Any) -> str:
    if valor is None:
        return ""

    return re.sub(r"\s+", " ", str(valor).strip())


def normalizar_tipo_norma(valor: str) -> str | None:
    valor = texto_limpio(valor)

    if not valor:
        return None

    valor = valor.upper()
    valor = re.sub(r"[^A-ZÁÉÍÓÚÜÑ0-9]+", "_", valor)
    return valor.strip("_") or None


def validar_extraccion(datos: dict[str, Any]) -> dict[str, Any]:
    campos_texto = (
        "enunciado",
        "opcion_a",
        "opcion_b",
        "opcion_c",
        "opcion_d",
        "respuesta_correcta",
        "clase",
        "pie_literal",
        "tipo_norma",
        "nombre_norma",
        "articulo_apartado",
        "tema_informatica",
        "motivo",
    )

    resultado = {
        campo: texto_limpio(datos.get(campo))
        for campo in campos_texto
    }

    resultado["valida"] = datos.get("valida") is True
    resultado["respuesta_correcta"] = resultado["respuesta_correcta"].upper()
    resultado["clase"] = resultado["clase"].upper()

    if not resultado["valida"]:
        raise ValueError(
            resultado["motivo"] or "La IA marcó la página como no válida."
        )

    for campo in (
        "enunciado",
        "opcion_a",
        "opcion_b",
        "opcion_c",
        "opcion_d",
    ):
        if not resultado[campo]:
            raise ValueError(f"Falta el campo {campo}.")

    if resultado["respuesta_correcta"] not in {"A", "B", "C", "D"}:
        raise ValueError("No se identificó una respuesta correcta válida.")

    if resultado["clase"] not in {"JURIDICA", "INFORMATICA", "OTRA"}:
        raise ValueError(
            f"Clase no reconocida: {resultado['clase']!r}"
        )

    return resultado


def preparar_registro(
    datos: dict[str, Any],
    origen: str,
    importacion_id: int,
    pagina_origen: int,
) -> tuple[dict[str, Any] | None, str]:
    clase = datos["clase"]

    comunes = {
        "enunciado": datos["enunciado"],
        "opcion_a": datos["opcion_a"],
        "opcion_b": datos["opcion_b"],
        "opcion_c": datos["opcion_c"],
        "opcion_d": datos["opcion_d"],
        "respuesta_correcta": datos["respuesta_correcta"],
        "origen_oposicion": origen,
        "tipo_fuente": TIPO_FUENTE,
        "importacion_fichero_id": importacion_id,
        "pagina_origen": pagina_origen,
    }

    if clase == "JURIDICA":
        norma = datos["nombre_norma"]
        articulo = datos["articulo_apartado"]

        if not norma or not articulo:
            return None, (
                "Pregunta jurídica sin norma y artículo/apartado "
                "expresos en el pie"
            )

        return {
            **comunes,
            "tipo_clasificacion": "JURIDICA",
            "tipo_norma": normalizar_tipo_norma(datos["tipo_norma"]),
            "nombre_norma": norma,
            "articulo": articulo,
            "tema_no_juridico": None,
        }, ""

    if clase == "INFORMATICA":
        tema = datos["tema_informatica"]

        if not tema:
            return None, (
                "Pregunta de informática sin clasificación ni tema legible"
            )

        return {
            **comunes,
            "tipo_clasificacion": "INFORMATICA",
            "tipo_norma": None,
            "nombre_norma": None,
            "articulo": None,
            "tema_no_juridico": tema,
        }, ""

    return None, "Pregunta no jurídica y no informática"


# =============================================================================
# PREGUNTAS: DUPLICADOS E INSERCIÓN
# =============================================================================

def buscar_pregunta_duplicada(
    conexion: sqlite3.Connection,
    registro: dict[str, Any],
) -> sqlite3.Row | None:
    return conexion.execute(
        """
        SELECT
            id,
            importacion_fichero_id,
            pagina_origen
        FROM lote_preguntas
        WHERE enunciado = :enunciado
          AND opcion_a = :opcion_a
          AND opcion_b = :opcion_b
          AND opcion_c = :opcion_c
          AND opcion_d = :opcion_d
          AND respuesta_correcta = :respuesta_correcta
          AND origen_oposicion = :origen_oposicion
          AND tipo_fuente = :tipo_fuente
        LIMIT 1
        """,
        registro,
    ).fetchone()


def insertar_registro(
    conexion: sqlite3.Connection,
    registro: dict[str, Any],
) -> int:
    cursor = conexion.execute(
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
            tipo_fuente,
            importacion_fichero_id,
            pagina_origen
        )
        VALUES (
            :enunciado,
            :opcion_a,
            :opcion_b,
            :opcion_c,
            :opcion_d,
            :respuesta_correcta,
            :tipo_clasificacion,
            :tipo_norma,
            :nombre_norma,
            :articulo,
            :tema_no_juridico,
            :origen_oposicion,
            :tipo_fuente,
            :importacion_fichero_id,
            :pagina_origen
        )
        """,
        registro,
    )
    return int(cursor.lastrowid)


# =============================================================================
# PROCESAMIENTO DE UN PDF
# =============================================================================

def procesar_pdf(
    ruta_pdf: Path,
    conexion: sqlite3.Connection,
    utilidad_openai,
    forzar: bool,
) -> tuple[str, dict[str, int]]:
    hash_sha256 = calcular_sha256(ruta_pdf)
    importacion = buscar_importacion(conexion, hash_sha256)

    totales = {
        "paginas": 0,
        "insertadas": 0,
        "duplicadas": 0,
        "omitidas": 0,
        "errores": 0,
    }

    marcado_reimportar = bool(
        importacion is not None and int(importacion["reimportar"] or 0) == 1
    )

    estado_registrado = ""
    if importacion is not None:
        estado_registrado = str(importacion["estado"] or "").strip().upper()

    logging.info(
        (
            "CONTROL IDEMPOTENCIA | archivo=%s | hash=%s | "
            "registro=%s | estado=%r | reimportar=%s | forzar=%s"
        ),
        ruta_pdf.name,
        hash_sha256[:12],
        None if importacion is None else importacion["id"],
        estado_registrado,
        marcado_reimportar,
        forzar,
    )

    # Regla conservadora:
    # si el mismo hash ya tiene una fila de trazabilidad, no se vuelve a abrir
    # ni a enviar a la IA salvo petición expresa (--forzar) o reimportar=1.
    #
    # Esto incluye registros antiguos que quedaron EN_PROCESO por una ejecución
    # interrumpida, pero cuyas preguntas ya estaban previamente en el banco.
    if (
        importacion is not None
        and not forzar
        and not marcado_reimportar
    ):
        logging.info(
            (
                "FICHERO OMITIDO SIN ABRIR | %s | id=%s | "
                "estado=%s | hash=%s"
            ),
            ruta_pdf.name,
            importacion["id"],
            estado_registrado or "(VACÍO)",
            hash_sha256[:12],
        )
        return "SALTADO", totales

    # Solo se abre cuando es nuevo o se ha solicitado reimportarlo.
    documento = fitz.open(ruta_pdf)

    try:
        paginas_totales = documento.page_count

        if importacion is None:
            importacion_id = crear_importacion(
                conexion,
                ruta_pdf,
                hash_sha256,
                paginas_totales,
            )
        else:
            importacion_id = int(importacion["id"])
            preparar_reimportacion(
                conexion,
                importacion_id,
                ruta_pdf,
                paginas_totales,
            )

        origen = obtener_origen(ruta_pdf.name)

        logging.info(
            (
                "INICIO PDF | archivo=%s | ruta=%s | páginas=%d | "
                "origen=%s | importacion_id=%d | forzar=%s"
            ),
            ruta_pdf.name,
            ruta_pdf,
            paginas_totales,
            origen,
            importacion_id,
            forzar or marcado_reimportar,
        )

        for indice in range(paginas_totales):
            numero_pagina = indice + 1
            totales["paginas"] += 1

            try:
                pagina = documento.load_page(indice)
                imagen = renderizar_pagina(pagina)

                datos_brutos = analizar_pagina(
                    utilidad_openai,
                    imagen,
                    numero_pagina,
                )
                datos = validar_extraccion(datos_brutos)

                registro, motivo = preparar_registro(
                    datos,
                    origen,
                    importacion_id,
                    numero_pagina,
                )

                if registro is None:
                    totales["omitidas"] += 1
                    logging.warning(
                        "%s | página %d | OMITIDA | %s",
                        ruta_pdf.name,
                        numero_pagina,
                        motivo,
                    )
                    continue

                duplicada = buscar_pregunta_duplicada(
                    conexion,
                    registro,
                )

                if duplicada is not None:
                    totales["duplicadas"] += 1
                    logging.info(
                        (
                            "%s | página %d | PREGUNTA DUPLICADA | "
                            "lote_id=%s | importacion_anterior=%s | "
                            "pagina_anterior=%s"
                        ),
                        ruta_pdf.name,
                        numero_pagina,
                        duplicada["id"],
                        duplicada["importacion_fichero_id"],
                        duplicada["pagina_origen"],
                    )
                    continue

                pregunta_id = insertar_registro(conexion, registro)
                conexion.commit()

                totales["insertadas"] += 1
                logging.info(
                    (
                        "%s | página %d | INSERTADA | "
                        "pregunta_id=%d | clase=%s"
                    ),
                    ruta_pdf.name,
                    numero_pagina,
                    pregunta_id,
                    registro["tipo_clasificacion"],
                )

            except Exception as exc:
                conexion.rollback()
                totales["errores"] += 1
                logging.exception(
                    "%s | página %d | ERROR | %s",
                    ruta_pdf.name,
                    numero_pagina,
                    exc,
                )

        finalizar_importacion(conexion, importacion_id, totales)

        logging.info(
            (
                "FIN PDF | archivo=%s | importacion_id=%d | "
                "páginas=%d | insertadas=%d | duplicadas=%d | "
                "omitidas=%d | errores=%d"
            ),
            ruta_pdf.name,
            importacion_id,
            totales["paginas"],
            totales["insertadas"],
            totales["duplicadas"],
            totales["omitidas"],
            totales["errores"],
        )

        return "PROCESADO", totales

    except Exception as exc:
        if "importacion_id" in locals():
            registrar_error_fichero(
                conexion,
                importacion_id,
                str(exc),
            )
        raise

    finally:
        documento.close()


# =============================================================================
# PROCESO PRINCIPAL
# =============================================================================

def main() -> int:
    configurar_logging()
    logging.info("VERSIÓN SCRIPT | %s | archivo=%s", VERSION_SCRIPT, RUTA_SCRIPT)
    args = leer_argumentos()

    if not RUTA_DB.is_file():
        logging.error("No existe la base de datos: %s", RUTA_DB)
        return 1

    try:
        rutas_pdf = obtener_pdfs(args.pdf)
        utilidad_openai = cargar_utilidad_openai()
    except Exception as exc:
        logging.exception("Error de configuración: %s", exc)
        return 1

    globales = {
        "pdf_encontrados": len(rutas_pdf),
        "pdf_procesados": 0,
        "pdf_saltados": 0,
        "pdf_error": 0,
        "paginas": 0,
        "insertadas": 0,
        "duplicadas": 0,
        "omitidas": 0,
        "errores": 0,
    }

    modo = "PDF CONCRETO" if args.pdf else "CARPETA COMPLETA"

    logging.info(
        "INICIO IMPORTACIÓN | modo=%s | archivos=%d | forzar=%s",
        modo,
        len(rutas_pdf),
        args.forzar,
    )

    try:
        with sqlite3.connect(RUTA_DB) as conexion:
            conexion.row_factory = sqlite3.Row
            validar_base_datos(conexion)

            for ruta_pdf in rutas_pdf:
                try:
                    resultado, totales = procesar_pdf(
                        ruta_pdf,
                        conexion,
                        utilidad_openai,
                        args.forzar,
                    )

                    if resultado == "SALTADO":
                        globales["pdf_saltados"] += 1
                    else:
                        globales["pdf_procesados"] += 1

                    for clave in (
                        "paginas",
                        "insertadas",
                        "duplicadas",
                        "omitidas",
                        "errores",
                    ):
                        globales[clave] += totales[clave]

                except Exception as exc:
                    globales["pdf_error"] += 1
                    logging.exception(
                        "ERROR DE FICHERO | %s | %s",
                        ruta_pdf,
                        exc,
                    )

    except Exception as exc:
        logging.exception("Error general: %s", exc)
        return 1

    print()
    print("=" * 76)
    print("RESUMEN GENERAL")
    print("=" * 76)
    print(f"Modo:                   {modo}")
    if args.pdf:
        print(f"PDF solicitado:         {rutas_pdf[0]}")
    print(f"PDF encontrados:        {globales['pdf_encontrados']}")
    print(f"PDF procesados:         {globales['pdf_procesados']}")
    print(f"PDF ya importados:      {globales['pdf_saltados']}")
    print(f"PDF con error general:  {globales['pdf_error']}")
    print(f"Páginas procesadas:     {globales['paginas']}")
    print(f"Preguntas insertadas:   {globales['insertadas']}")
    print(f"Preguntas duplicadas:   {globales['duplicadas']}")
    print(f"Páginas omitidas:       {globales['omitidas']}")
    print(f"Errores de página:      {globales['errores']}")
    print(f"Log:                    {RUTA_LOG}")
    print(f"Costes IA:              {RUTA_COSTES}")

    return 1 if globales["pdf_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())