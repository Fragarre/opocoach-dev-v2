"""
OpoCoach - Crear una convocatoria a partir del PDF oficial del temario.

Primera versión orientada al formato DOGV de la convocatoria C1-01 58/26.
No utiliza IA ni consulta todavía el BOE.

Crea:
    - convocatorias
    - partes_convocatoria
    - temas_convocatoria
    - requisitos_examen

Uso recomendado:
    python scripts/crear_convocatoria.py \
        --pdf "data_convocatorias/convocatoria 58_26_temario.pdf"

Opciones:
    --reemplazar
        Elimina y vuelve a crear la convocatoria si ya existe.
        Gracias a ON DELETE CASCADE también elimina sus partes, temas,
        requisitos, corpus y banco de preguntas de convocatoria.

Dependencia:
    pip install pymupdf
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz


RUTA_SCRIPT = Path(__file__).resolve()
RAIZ = RUTA_SCRIPT.parent.parent
RUTA_DB_PREDETERMINADA = RAIZ / "db" / "oposiciones.sqlite3"

CODIGO_CONVOCATORIA = "C1-01_58_26"
CUERPO = "C1-01"
NUMERO_CONVOCATORIA = 58
ANIO = 2026
NOMBRE_CONVOCATORIA = "Convocatoria 58/26 - C1-01 Cuerpo administrativo"
EXAMEN_MODELO = "C1-01_58_26"

TOTAL_PREGUNTAS = 110
TIEMPO_MINUTOS = None

VALOR_ACIERTO = 1.0
VALOR_ERROR = -0.333
VALOR_BLANCO = 0.0

NOTA_MAXIMA = 10.0
PUNTOS_MAXIMOS = 40.0
PUNTOS_APROBADO = 20.0

PARTES = {
    "GENERAL": {
        "nombre": "Parte general",
        "orden": 1,
        "numero_preguntas": 30,
    },
    "ESPECIAL": {
        "nombre": "Parte especial",
        "orden": 2,
        "numero_preguntas": 80,
    },
}

REQUISITOS = (
    {
        "tipo_requisito": "ATRIBUTO",
        "referencia": "TEORICO_PRACTICA",
        "cantidad": 15,
        "descripcion": "Preguntas de carácter teórico-práctico.",
    },
    {
        "tipo_requisito": "BLOQUE",
        "referencia": "INFORMATICA",
        "cantidad": 15,
        "descripcion": "Preguntas de informática básica y ofimática.",
    },
)

ENCABEZADOS_IGNORADOS = (
    "Núm.",
    "CVE:",
    "Anexo ",
    "Convocatoria ",
    "C1-01.",
)

RE_PARTE = re.compile(
    r"^TEMARIO\s+PARTE\s+(GENERAL|ESPECIAL)\s*$",
    re.IGNORECASE,
)

RE_BLOQUE = re.compile(
    r"^(?P<romano>[IVXLCDM]+)\.\s+(?P<nombre>[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9 /(),.-]+)$"
)

RE_TEMA = re.compile(
    r"^(?P<numero>\d+)\.\s+(?P<descripcion>.+)$"
)


@dataclass(frozen=True)
class TemaExtraido:
    parte_codigo: str
    numero_tema: int
    bloque: str | None
    titulo: str
    descripcion_oficial: str
    orden_global: int


def leer_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crea la convocatoria 58/26 desde su PDF oficial."
    )
    parser.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Ruta del PDF oficial del temario.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=RUTA_DB_PREDETERMINADA,
        help=f"Base SQLite. Por defecto: {RUTA_DB_PREDETERMINADA}",
    )
    parser.add_argument(
        "--reemplazar",
        action="store_true",
        help="Borra y vuelve a crear la convocatoria si ya existe.",
    )
    return parser.parse_args()


def limpiar_linea(linea: str) -> str:
    return re.sub(r"\s+", " ", linea).strip()


def extraer_texto_pdf(ruta_pdf: Path) -> str:
    if not ruta_pdf.is_file():
        raise FileNotFoundError(f"No existe el PDF: {ruta_pdf}")

    with fitz.open(ruta_pdf) as documento:
        paginas = [pagina.get_text("text") for pagina in documento]

    texto = "\n".join(paginas).strip()
    if not texto:
        raise RuntimeError("El PDF no contiene texto extraíble.")

    return texto


def es_linea_ignorada(linea: str) -> bool:
    if not linea:
        return True

    if any(linea.startswith(prefijo) for prefijo in ENCABEZADOS_IGNORADOS):
        return True

    if re.fullmatch(r"\d+\s*/\s*\d+", linea):
        return True

    return False


def preparar_lineas(texto: str) -> list[str]:
    lineas: list[str] = []

    for linea_bruta in texto.splitlines():
        linea = limpiar_linea(linea_bruta)
        if es_linea_ignorada(linea):
            continue
        lineas.append(linea)

    return lineas


def titulo_desde_descripcion(descripcion: str) -> str:
    """
    Título breve y determinista, sin IA.
    Toma el texto anterior a los primeros dos puntos o, si no existen,
    limita la descripción a 160 caracteres.
    """
    candidato = descripcion.split(":", 1)[0].strip()
    if len(candidato) < 8:
        candidato = descripcion.strip()

    if len(candidato) > 160:
        candidato = candidato[:157].rstrip() + "..."

    return candidato


def extraer_temas(texto: str) -> list[TemaExtraido]:
    lineas = preparar_lineas(texto)

    parte_actual: str | None = None
    bloque_actual: str | None = None

    temas: list[TemaExtraido] = []
    tema_numero: int | None = None
    tema_partes: list[str] = []
    tema_parte: str | None = None
    tema_bloque: str | None = None
    orden_global = 0

    def cerrar_tema() -> None:
        nonlocal tema_numero, tema_partes, tema_parte, tema_bloque, orden_global

        if tema_numero is None:
            return

        descripcion = limpiar_linea(" ".join(tema_partes))
        if not descripcion:
            raise RuntimeError(
                f"El tema {tema_numero} de {tema_parte} no tiene descripción."
            )

        orden_global += 1
        temas.append(
            TemaExtraido(
                parte_codigo=tema_parte or "",
                numero_tema=tema_numero,
                bloque=tema_bloque,
                titulo=titulo_desde_descripcion(descripcion),
                descripcion_oficial=descripcion,
                orden_global=orden_global,
            )
        )

        tema_numero = None
        tema_partes = []
        tema_parte = None
        tema_bloque = None

    for linea in lineas:
        coincidencia_parte = RE_PARTE.match(linea)
        if coincidencia_parte:
            cerrar_tema()
            parte_actual = coincidencia_parte.group(1).upper()
            bloque_actual = None
            continue

        if parte_actual is None:
            continue

        coincidencia_bloque = RE_BLOQUE.match(linea)
        if coincidencia_bloque:
            cerrar_tema()
            bloque_actual = coincidencia_bloque.group("nombre").strip()
            continue

        coincidencia_tema = RE_TEMA.match(linea)
        if coincidencia_tema:
            cerrar_tema()
            tema_numero = int(coincidencia_tema.group("numero"))
            tema_partes = [coincidencia_tema.group("descripcion")]
            tema_parte = parte_actual
            tema_bloque = bloque_actual
            continue

        if tema_numero is not None:
            tema_partes.append(linea)

    cerrar_tema()

    if not temas:
        raise RuntimeError("No se ha encontrado ningún tema en el PDF.")

    validar_temas_extraidos(temas)
    return temas


def validar_temas_extraidos(temas: list[TemaExtraido]) -> None:
    por_parte: dict[str, list[int]] = {"GENERAL": [], "ESPECIAL": []}

    for tema in temas:
        if tema.parte_codigo not in por_parte:
            raise RuntimeError(f"Parte desconocida: {tema.parte_codigo}")
        por_parte[tema.parte_codigo].append(tema.numero_tema)

    esperados = {
        "GENERAL": list(range(1, 13)),
        "ESPECIAL": list(range(1, 24)),
    }

    for parte, numeros_esperados in esperados.items():
        encontrados = por_parte[parte]
        if encontrados != numeros_esperados:
            raise RuntimeError(
                f"Temas incorrectos en {parte}. "
                f"Esperados: {numeros_esperados}. "
                f"Encontrados: {encontrados}."
            )


def validar_esquema(conexion: sqlite3.Connection) -> None:
    tablas_necesarias = {
        "convocatorias",
        "partes_convocatoria",
        "temas_convocatoria",
        "requisitos_examen",
    }
    existentes = {
        fila[0]
        for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    faltantes = tablas_necesarias - existentes
    if faltantes:
        raise RuntimeError(
            "Faltan tablas de convocatorias: "
            + ", ".join(sorted(faltantes))
        )


def obtener_convocatoria_existente(
    conexion: sqlite3.Connection,
) -> sqlite3.Row | None:
    return conexion.execute(
        "SELECT * FROM convocatorias WHERE codigo = ?",
        (CODIGO_CONVOCATORIA,),
    ).fetchone()


def eliminar_convocatoria(
    conexion: sqlite3.Connection,
    convocatoria_id: int,
) -> None:
    conexion.execute(
        "DELETE FROM convocatorias WHERE id = ?",
        (convocatoria_id,),
    )


def insertar_convocatoria(conexion: sqlite3.Connection) -> int:
    cursor = conexion.execute(
        """
        INSERT INTO convocatorias (
            codigo,
            cuerpo,
            numero,
            anio,
            nombre,
            examen_modelo,
            total_preguntas,
            tiempo_minutos,
            valor_acierto,
            valor_error,
            valor_blanco,
            nota_maxima,
            puntos_maximos,
            puntos_aprobado,
            estado
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BORRADOR')
        """,
        (
            CODIGO_CONVOCATORIA,
            CUERPO,
            NUMERO_CONVOCATORIA,
            ANIO,
            NOMBRE_CONVOCATORIA,
            EXAMEN_MODELO,
            TOTAL_PREGUNTAS,
            TIEMPO_MINUTOS,
            VALOR_ACIERTO,
            VALOR_ERROR,
            VALOR_BLANCO,
            NOTA_MAXIMA,
            PUNTOS_MAXIMOS,
            PUNTOS_APROBADO,
        ),
    )
    return int(cursor.lastrowid)


def insertar_partes(
    conexion: sqlite3.Connection,
    convocatoria_id: int,
) -> dict[str, int]:
    ids: dict[str, int] = {}

    for codigo, datos in PARTES.items():
        cursor = conexion.execute(
            """
            INSERT INTO partes_convocatoria (
                convocatoria_id,
                codigo,
                nombre,
                orden,
                numero_preguntas
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                convocatoria_id,
                codigo,
                datos["nombre"],
                datos["orden"],
                datos["numero_preguntas"],
            ),
        )
        ids[codigo] = int(cursor.lastrowid)

    return ids


def insertar_temas(
    conexion: sqlite3.Connection,
    convocatoria_id: int,
    partes_ids: dict[str, int],
    temas: list[TemaExtraido],
) -> None:
    for tema in temas:
        conexion.execute(
            """
            INSERT INTO temas_convocatoria (
                convocatoria_id,
                parte_id,
                numero_tema,
                bloque,
                titulo,
                descripcion_oficial,
                preguntas_modelo,
                orden
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                convocatoria_id,
                partes_ids[tema.parte_codigo],
                tema.numero_tema,
                tema.bloque,
                tema.titulo,
                tema.descripcion_oficial,
                tema.orden_global,
            ),
        )


def insertar_requisitos(
    conexion: sqlite3.Connection,
    convocatoria_id: int,
) -> None:
    for requisito in REQUISITOS:
        conexion.execute(
            """
            INSERT INTO requisitos_examen (
                convocatoria_id,
                tipo_requisito,
                referencia,
                cantidad,
                descripcion
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                convocatoria_id,
                requisito["tipo_requisito"],
                requisito["referencia"],
                requisito["cantidad"],
                requisito["descripcion"],
            ),
        )


def imprimir_resumen(temas: list[TemaExtraido]) -> None:
    general = [t for t in temas if t.parte_codigo == "GENERAL"]
    especial = [t for t in temas if t.parte_codigo == "ESPECIAL"]

    print()
    print("=" * 72)
    print("CONVOCATORIA CREADA")
    print("=" * 72)
    print(f"Código:                   {CODIGO_CONVOCATORIA}")
    print(f"Nombre:                   {NOMBRE_CONVOCATORIA}")
    print(f"Preguntas totales:        {TOTAL_PREGUNTAS}")
    print(f"Parte general:            {PARTES['GENERAL']['numero_preguntas']}")
    print(f"Parte especial:           {PARTES['ESPECIAL']['numero_preguntas']}")
    print(f"Temas parte general:      {len(general)}")
    print(f"Temas parte especial:     {len(especial)}")
    print(f"Teórico-prácticas:        15")
    print(f"Informática:              15")
    print(f"Penalización por error:   {VALOR_ERROR}")
    print(f"Puntuación máxima:        {PUNTOS_MAXIMOS}")
    print(f"Puntuación de aprobado:   {PUNTOS_APROBADO}")
    print()
    print("Todavía no se ha creado el corpus ni se han validado preguntas.")


def main() -> int:
    args = leer_argumentos()

    ruta_pdf = args.pdf.expanduser().resolve()
    ruta_db = args.db.expanduser().resolve()

    if not ruta_db.is_file():
        print(f"ERROR: no existe la base de datos: {ruta_db}", file=sys.stderr)
        return 1

    try:
        texto = extraer_texto_pdf(ruta_pdf)
        temas = extraer_temas(texto)

        with sqlite3.connect(ruta_db) as conexion:
            conexion.row_factory = sqlite3.Row
            conexion.execute("PRAGMA foreign_keys = ON")
            validar_esquema(conexion)

            existente = obtener_convocatoria_existente(conexion)

            if existente is not None and not args.reemplazar:
                print(
                    "La convocatoria ya existe. No se ha modificado nada.\n"
                    f"  código: {CODIGO_CONVOCATORIA}\n"
                    f"  id: {existente['id']}\n\n"
                    "Para recrearla expresamente usa --reemplazar."
                )
                return 0

            conexion.execute("BEGIN")

            if existente is not None:
                eliminar_convocatoria(conexion, int(existente["id"]))

            convocatoria_id = insertar_convocatoria(conexion)
            partes_ids = insertar_partes(conexion, convocatoria_id)
            insertar_temas(
                conexion,
                convocatoria_id,
                partes_ids,
                temas,
            )
            insertar_requisitos(conexion, convocatoria_id)

            conexion.commit()

        imprimir_resumen(temas)
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())