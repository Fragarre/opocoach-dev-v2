"""
===============================================================================
Proyecto : OpoCoach
Tipo     : Consulta de legislación consolidada mediante la API oficial del BOE
Archivo  : boe_api.py
Ubicación:
    scripts/boe_api.py

OBJETIVO
--------
Localizar una norma en la API oficial del BOE y recuperar el texto consolidado
de un artículo concreto.

Este módulo sirve como apoyo para la auditoría jurídica de las preguntas del
banco. No decide si una pregunta es válida y no modifica la base de datos.

USO DESDE LÍNEA DE COMANDOS
---------------------------
Obtener un artículo concreto:

    python scripts/boe_api.py "Ley 39/2015" 47

Ejemplo con una norma autonómica ambigua por número:

    python scripts/boe_api.py "Ley 1/2022" 1

La salida muestra:
    - norma solicitada;
    - identificador BOE;
    - departamento;
    - artículo y bloque;
    - texto consolidado oficial.

USO COMO MÓDULO
---------------
La función principal es:

    obtener_articulo(nombre_norma, articulo) -> ArticuloBOE

También están disponibles:

    buscar_norma(nombre_norma) -> NormaBOE
    limpiar_cache_norma(nombre_norma)
    limpiar_cache_articulo(id_boe, id_bloque)

CRITERIO DE SELECCIÓN DE NORMAS
-------------------------------
Una misma numeración puede corresponder a varias normas estatales o
autonómicas. Para reducir errores, el módulo aplica este criterio:

1. Busca candidatos cuyo título coincida con el tipo, número y año indicados.
2. Obtiene el campo "Departamento" de la ficha oficial de cada candidato.
3. Da prioridad a "Comunitat Valenciana" o denominaciones equivalentes.
4. Si no existe una norma valenciana, da prioridad a "Jefatura del Estado".
5. Si no puede seleccionar una norma con seguridad, produce un error en lugar
   de elegir arbitrariamente.

Este criterio es deliberadamente sencillo. OpoCoach admite que algunas
preguntas queden sin validar cuando la norma o el artículo no pueden
identificarse con suficiente seguridad. Es preferible rechazar una pregunta
dudosa que introducir una clasificación jurídica incorrecta.

CACHÉ
-----
Para evitar consultas repetidas se utiliza:

    cache_boe/normas.json
    cache_boe/<ID_BOE>/metadatos.xml
    cache_boe/<ID_BOE>/indice.xml
    cache_boe/<ID_BOE>/bloque_<ID>.xml

Las entradas antiguas de `normas.json` que no incluyan departamento se ignoran
y se vuelven a consultar.

ALCANCE Y LIMITACIONES
----------------------
- Solo utiliza la API oficial de legislación consolidada del BOE.
- No usa textos legales locales.
- No modifica SQLite ni otros datos del proyecto.
- No intenta adivinar una norma cuando la búsqueda es ambigua.
- Puede devolver error si la norma no está consolidada, el artículo no existe,
  la API no responde o los metadatos no permiten seleccionar con seguridad.
- Esos errores deben ser tratados por el script llamador como preguntas
  omitidas o pendientes de revisión, sin detener necesariamente un lote.

DEPENDENCIAS
------------
    pip install requests

SALIDA Y ERRORES
----------------
Los errores propios del módulo se expresan mediante `BOEError`. Los datos
válidos se devuelven en las estructuras `NormaBOE` y `ArticuloBOE`.
===============================================================================
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import shutil
import sqlite3

import requests


BASE_URL = "https://boe.es/datosabiertos/api/legislacion-consolidada"
TIMEOUT = 30

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CACHE_DIR = RAIZ_PROYECTO / "cache_boe"
_cache_articulos: dict[str, list[ArticuloNorma]] = {}
CACHE_NORMAS = CACHE_DIR / "normas.json"
# Excepciones mínimas para normas cuya búsqueda genérica del BOE
# devuelve de forma reiterada un resultado incorrecto.
ID_NORMAS_CONOCIDAS = {
    "real decreto legislativo 2/2015": "BOE-A-2015-11430",
}
RUTA_DB = RAIZ_PROYECTO / "db" / "oposiciones.sqlite3"
DOCUMENTOS_DIR = RAIZ_PROYECTO / "data" / "documentos"


class BOEError(RuntimeError):
    """Error al consultar o interpretar la API del BOE."""


@dataclass
class NormaBOE:
    nombre_buscado: str
    id_boe: str
    titulo: str
    departamento: str = ""


@dataclass
class ArticuloBOE:
    nombre_norma: str
    id_boe: str
    departamento: str
    articulo: str
    id_bloque: str
    titulo_bloque: str
    texto: str

@dataclass
class ArticuloNorma:
    numero: str
    titulo: str
    texto: str


def preparar_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not CACHE_NORMAS.exists():
        guardar_json(CACHE_NORMAS, {})


def guardar_json(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")

    with temporal.open("w", encoding="utf-8") as fichero:
        json.dump(datos, fichero, ensure_ascii=False, indent=2)

    temporal.replace(ruta)


def cargar_json(ruta: Path, valor_defecto: Any = None) -> Any:
    if not ruta.exists():
        return valor_defecto

    try:
        with ruta.open("r", encoding="utf-8") as fichero:
            return json.load(fichero)
    except (OSError, json.JSONDecodeError) as exc:
        raise BOEError(f"No se pudo leer el archivo de caché: {ruta}") from exc


def normalizar_texto(texto: str | None) -> str:
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter for caracter in texto if not unicodedata.combining(caracter)
    )
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpiar_espacios(texto: str | None) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def obtener_xml(url: str, params: dict[str, Any] | None = None) -> ET.Element:
    try:
        respuesta = requests.get(
            url,
            params=params,
            timeout=TIMEOUT,
            headers={
                "Accept": "application/xml",
                "User-Agent": "OpoCoach/1.0",
            },
            allow_redirects=True,
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise BOEError(f"Error al consultar el BOE: {url}") from exc

    try:
        return ET.fromstring(respuesta.content)
    except ET.ParseError as exc:
        raise BOEError(
            f"El BOE devolvió una respuesta XML no válida: {url}"
        ) from exc


def nombre_etiqueta(elemento: ET.Element) -> str:
    """Elimina el namespace XML de una etiqueta."""
    return elemento.tag.rsplit("}", 1)[-1].lower()


def texto_completo(elemento: ET.Element | None) -> str:
    if elemento is None:
        return ""

    partes = [
        limpiar_espacios(fragmento)
        for fragmento in elemento.itertext()
        if limpiar_espacios(fragmento)
    ]
    return limpiar_espacios(" ".join(partes))


def buscar_primer_texto(elemento: ET.Element, nombres: set[str]) -> str:
    nombres_normalizados = {normalizar_texto(nombre) for nombre in nombres}

    for nodo in elemento.iter():
        etiqueta = normalizar_texto(nombre_etiqueta(nodo))
        if etiqueta in nombres_normalizados:
            valor = texto_completo(nodo)
            if valor:
                return valor

    return ""


def extraer_id_boe(texto: str) -> str:
    coincidencia = re.search(
        r"\bBOE-A-\d{4}-\d+\b",
        texto,
        flags=re.IGNORECASE,
    )
    return coincidencia.group(0).upper() if coincidencia else ""


def ruta_cache_norma(id_boe: str) -> Path:
    return CACHE_DIR / id_boe


def ruta_cache_metadatos(id_boe: str) -> Path:
    return ruta_cache_norma(id_boe) / "metadatos.xml"


def ruta_cache_indice(id_boe: str) -> Path:
    return ruta_cache_norma(id_boe) / "indice.xml"


def ruta_cache_bloque(id_boe: str, id_bloque: str) -> Path:
    nombre_seguro = re.sub(r"[^a-zA-Z0-9_.-]+", "_", id_bloque)
    return ruta_cache_norma(id_boe) / f"bloque_{nombre_seguro}.xml"


def guardar_xml(ruta: Path, contenido: bytes) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_bytes(contenido)
    temporal.replace(ruta)


def cargar_xml_cache(ruta: Path) -> ET.Element | None:
    if not ruta.exists():
        return None

    try:
        return ET.fromstring(ruta.read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise BOEError(f"No se pudo leer el XML almacenado en caché: {ruta}") from exc


def descargar_xml(url: str, ruta_cache: Path) -> ET.Element:
    xml_cache = cargar_xml_cache(ruta_cache)
    if xml_cache is not None:
        return xml_cache

    try:
        respuesta = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "Accept": "application/xml",
                "User-Agent": "OpoCoach/1.0",
            },
            allow_redirects=True,
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        raise BOEError(f"Error al consultar el BOE: {url}") from exc

    try:
        raiz = ET.fromstring(respuesta.content)
    except ET.ParseError as exc:
        raise BOEError(
            f"El BOE devolvió una respuesta XML no válida: {url}"
        ) from exc

    guardar_xml(ruta_cache, respuesta.content)
    return raiz


def obtener_atributo(elemento: ET.Element, nombres: set[str]) -> str:
    nombres_normalizados = {normalizar_texto(nombre) for nombre in nombres}

    for clave, valor in elemento.attrib.items():
        clave_normalizada = normalizar_texto(clave.rsplit("}", 1)[-1])
        if clave_normalizada in nombres_normalizados:
            return limpiar_espacios(valor)

    return ""


def extraer_departamento(raiz: ET.Element) -> str:
    """Extrae el departamento de la ficha completa o de un resultado de búsqueda."""
    nombres = {
        "departamento",
        "departamento_nombre",
        "nombre_departamento",
        "texto_departamento",
    }

    departamento = buscar_primer_texto(raiz, nombres)
    if departamento:
        return limpiar_espacios(departamento)

    # Respaldo para estructuras del tipo <item nombre="departamento">...</item>.
    for elemento in raiz.iter():
        for clave, valor in elemento.attrib.items():
            clave_n = normalizar_texto(clave.rsplit("}", 1)[-1])
            valor_n = normalizar_texto(valor)
            if clave_n in {"nombre", "campo", "clave"} and valor_n == "departamento":
                contenido = texto_completo(elemento)
                if contenido:
                    return contenido

    return ""


def obtener_metadatos_norma(id_boe: str) -> ET.Element:
    id_boe = extraer_id_boe(id_boe)
    if not id_boe:
        raise ValueError("Identificador BOE no válido.")

    url = f"{BASE_URL}/id/{id_boe}"
    return descargar_xml(url, ruta_cache_metadatos(id_boe))


def obtener_departamento(id_boe: str) -> str:
    raiz = obtener_metadatos_norma(id_boe)
    departamento = extraer_departamento(raiz)

    if not departamento:
        raise BOEError(
            f"No se pudo obtener el departamento de la norma {id_boe}."
        )

    return departamento


def extraer_registros_normas(raiz: ET.Element) -> list[NormaBOE]:
    resultados: list[NormaBOE] = []
    ids_vistos: set[str] = set()

    for elemento in raiz.iter():
        contenido = texto_completo(elemento)
        id_boe = extraer_id_boe(contenido)

        if not id_boe:
            id_boe = extraer_id_boe(" ".join(elemento.attrib.values()))

        if not id_boe or id_boe in ids_vistos:
            continue

        titulo = buscar_primer_texto(
            elemento,
            {"titulo", "titulo_oficial", "nombre", "descripcion"},
        )
        if not titulo:
            titulo = contenido

        resultados.append(
            NormaBOE(
                nombre_buscado="",
                id_boe=id_boe,
                titulo=limpiar_espacios(titulo),
                departamento=extraer_departamento(elemento),
            )
        )
        ids_vistos.add(id_boe)

    return resultados


def palabras_significativas(texto: str) -> set[str]:
    palabras = set(re.findall(r"[a-z0-9]+", normalizar_texto(texto)))
    ignoradas = {
        "de", "del", "la", "las", "el", "los", "por", "para", "y",
        "o", "en", "con", "que", "se", "a", "un", "una",
    }
    return {palabra for palabra in palabras if palabra not in ignoradas}

PALABRAS_VACIAS = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del",
    "desde", "durante", "e", "el", "ella", "ellas", "ellos",
    "en", "entre", "es", "esa", "ese", "esta", "este", "ha",
    "la", "las", "lo", "los", "más", "no", "o", "para", "por",
    "que", "se", "según", "ser", "si", "sin", "sobre", "su",
    "sus", "un", "una", "unos", "unas", "y",
}


def puntuacion_norma(nombre_buscado: str, titulo_boe: str) -> int:
    buscado = palabras_significativas(nombre_buscado)
    titulo = palabras_significativas(titulo_boe)

    if not buscado or not titulo:
        return 0

    puntuacion = len(buscado.intersection(titulo)) * 10
    nombre_n = normalizar_texto(nombre_buscado)
    titulo_n = normalizar_texto(titulo_boe)

    if nombre_n in titulo_n:
        puntuacion += 100

    referencia = extraer_referencia_norma(nombre_buscado)
    if referencia and referencia == extraer_referencia_norma(titulo_boe):
        puntuacion += 300

    return puntuacion


def extraer_referencia_norma(texto: str) -> str:
    texto_n = normalizar_texto(texto)
    patrones = [
        r"\breal decreto legislativo\s+\d+/\d{4}\b",
        r"\breal decreto-ley\s+\d+/\d{4}\b",
        r"\breal decreto\s+\d+/\d{4}\b",
        r"\bley organica\s+\d+/\d{4}\b",
        r"\bdecreto legislativo\s+\d+/\d{4}\b",
        r"\bdecreto-ley\s+\d+/\d{4}\b",
        r"\bdecreto\s+\d+/\d{4}\b",
        r"\bley\s+\d+/\d{4}\b",
    ]

    for patron in patrones:
        coincidencia = re.search(patron, texto_n)
        if coincidencia:
            return coincidencia.group(0)

    return ""


def es_departamento_valenciano(departamento: str) -> bool:
    valor = normalizar_texto(departamento)
    return (
        "comunitat valenciana" in valor
        or "comunidad valenciana" in valor
        or "generalitat valenciana" in valor
    )


def es_jefatura_estado(departamento: str) -> bool:
    return "jefatura del estado" in normalizar_texto(departamento)


def completar_departamentos(candidatos: list[NormaBOE]) -> None:
    for candidato in candidatos:
        if candidato.departamento:
            continue
        candidato.departamento = obtener_departamento(candidato.id_boe)


def seleccionar_norma(nombre_norma: str, candidatos: list[NormaBOE]) -> NormaBOE:
    referencia_buscada = extraer_referencia_norma(nombre_norma)

    if referencia_buscada:
        exactos = [
            candidato
            for candidato in candidatos
            if extraer_referencia_norma(candidato.titulo) == referencia_buscada
        ]
        if exactos:
            candidatos = exactos

    completar_departamentos(candidatos)

    valencianos = [
        candidato
        for candidato in candidatos
        if es_departamento_valenciano(candidato.departamento)
    ]
    if valencianos:
        valencianos.sort(
            key=lambda candidato: puntuacion_norma(nombre_norma, candidato.titulo),
            reverse=True,
        )
        return valencianos[0]

    estatales = [
        candidato
        for candidato in candidatos
        if es_jefatura_estado(candidato.departamento)
    ]
    if estatales:
        estatales.sort(
            key=lambda candidato: puntuacion_norma(nombre_norma, candidato.titulo),
            reverse=True,
        )
        return estatales[0]
    
    # Si solo queda un candidato, no existe ambigüedad real,
    # aunque el departamento sea un ministerio u otro organismo estatal.
    if len(candidatos) == 1:
        return candidatos[0]

    resumen = "; ".join(
        f"{c.id_boe} | {c.departamento or 'sin departamento'} | {c.titulo}"
        for c in candidatos
    )
    raise BOEError(
        "No hay ningún candidato de la Comunitat Valenciana ni de la "
        f"Jefatura del Estado para {nombre_norma}. Candidatos: {resumen}"
    )


def cargar_cache_normas() -> dict[str, Any]:
    preparar_cache()
    cache = cargar_json(CACHE_NORMAS, {})

    if not isinstance(cache, dict):
        raise BOEError(f"Formato incorrecto en el archivo {CACHE_NORMAS}")

    return cache


def buscar_norma_en_cache(nombre_norma: str) -> NormaBOE | None:
    cache = cargar_cache_normas()
    datos = cache.get(normalizar_texto(nombre_norma))

    if not isinstance(datos, dict):
        return None

    id_boe = limpiar_espacios(str(datos.get("id_boe", "")))
    titulo = limpiar_espacios(str(datos.get("titulo", "")))
    departamento = limpiar_espacios(str(datos.get("departamento", "")))

    # Las entradas antiguas, creadas antes de guardar el departamento,
    # se descartan para evitar reutilizar una norma ambigua o incorrecta.
    if not id_boe or not departamento:
        return None

    return NormaBOE(
        nombre_buscado=nombre_norma,
        id_boe=id_boe,
        titulo=titulo,
        departamento=departamento,
    )


def guardar_norma_en_cache(norma: NormaBOE) -> None:
    cache = cargar_cache_normas()
    cache[normalizar_texto(norma.nombre_buscado)] = {
        "nombre_buscado": norma.nombre_buscado,
        "id_boe": norma.id_boe,
        "titulo": norma.titulo,
        "departamento": norma.departamento,
    }
    guardar_json(CACHE_NORMAS, cache)


def buscar_norma(nombre_norma: str) -> NormaBOE:
    nombre_norma = limpiar_espacios(nombre_norma)
    if not nombre_norma:
        raise ValueError("Debe indicarse el nombre de la norma.")

    # Resolver primero las pocas normas conocidas cuya búsqueda genérica
    # produce resultados incorrectos. Se hace antes de consultar la caché
    # para ignorar una posible entrada antigua equivocada.
    id_conocido = ID_NORMAS_CONOCIDAS.get(
        normalizar_texto(nombre_norma)
    )

    if id_conocido:
        norma = NormaBOE(
            nombre_buscado=nombre_norma,
            id_boe=id_conocido,
            titulo=nombre_norma,
            departamento=obtener_departamento(id_conocido),
        )
        guardar_norma_en_cache(norma)
        return norma

    norma_cache = buscar_norma_en_cache(nombre_norma)
    
    if norma_cache is not None:
        return norma_cache

    id_directo = extraer_id_boe(nombre_norma)
    if id_directo:
        norma = NormaBOE(
            nombre_buscado=nombre_norma,
            id_boe=id_directo,
            titulo=nombre_norma,
            departamento=obtener_departamento(id_directo),
        )
        guardar_norma_en_cache(norma)
        return norma

    consulta = {
        "query": {
            "query_string": {"query": f'titulo:"{nombre_norma}"'},
            "range": {},
        },
        "sort": [],
    }

    try:
        respuesta = requests.get(
            BASE_URL,
            params={
                "query": json.dumps(
                    consulta,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "limit": 20,
            },
            timeout=TIMEOUT,
            headers={
                "Accept": "application/xml",
                "User-Agent": "OpoCoach/1.0",
            },
            allow_redirects=True,
        )
        respuesta.raise_for_status()
    except requests.RequestException as exc:
        detalle = ""
        respuesta_error = exc.response

        if respuesta_error is not None:
            detalle = (
                f"\nHTTP: {respuesta_error.status_code}"
                f"\nURL: {respuesta_error.url}"
                f"\nRespuesta: {respuesta_error.text[:1000]}"
            )

        raise BOEError(
            f"No se pudo buscar la norma en el BOE: "
            f"{nombre_norma}{detalle}"
        ) from exc

    try:
        raiz = ET.fromstring(respuesta.content)
    except ET.ParseError as exc:
        raise BOEError(
            "La búsqueda del BOE no devolvió un XML válido.\n"
            f"Respuesta: {respuesta.text[:1000]}"
        ) from exc

    candidatos = extraer_registros_normas(raiz)
    if not candidatos:
        raise BOEError(f"No se encontró la norma en el BOE: {nombre_norma}")

    mejor = seleccionar_norma(nombre_norma, candidatos)
    mejor.nombre_buscado = nombre_norma
    guardar_norma_en_cache(mejor)
    return mejor


def obtener_indice(id_boe: str) -> ET.Element:
    id_boe = extraer_id_boe(id_boe)
    if not id_boe:
        raise ValueError("Identificador BOE no válido.")

    return descargar_xml(
        url=f"{BASE_URL}/id/{id_boe}/texto/indice",
        ruta_cache=ruta_cache_indice(id_boe),
    )

def normalizar_numero_articulo(articulo: str) -> str:
    articulo = limpiar_espacios(articulo)
    articulo = re.sub(
        r"^(articulo|art\.?)\s*",
        "",
        articulo,
        flags=re.IGNORECASE,
    )
    return normalizar_texto(articulo.strip(" .ºª"))

def parece_articulo(titulo: str, numero_articulo: str) -> bool:
    titulo_n = normalizar_texto(titulo)
    numero_n = normalizar_numero_articulo(numero_articulo)

    if not numero_n:
        return False

    patron = r"\barticulo\s+" + re.escape(numero_n) + r"(?:\b|[.\s])"
    if re.search(patron, titulo_n):
        return True

    titulo_sin_prefijo = re.sub(
        r"^(articulo|art\.?)\s*",
        "",
        titulo_n,
    ).strip(" .ºª")
    return titulo_sin_prefijo == numero_n

def extraer_bloques_indice(raiz: ET.Element) -> list[dict[str, str]]:
    bloques: list[dict[str, str]] = []

    for elemento in raiz.iter():
        titulo = buscar_primer_texto(
            elemento,
            {"titulo", "texto", "descripcion", "nombre"},
        )
        if not titulo:
            titulo = texto_completo(elemento)

        if "articulo" not in normalizar_texto(titulo):
            continue

        id_bloque = obtener_atributo(
            elemento,
            {"id", "id_bloque", "identificador"},
        )
        if not id_bloque:
            id_bloque = buscar_primer_texto(
                elemento,
                {"id", "id_bloque", "identificador"},
            )
        if not id_bloque:
            continue

        bloques.append(
            {"id_bloque": id_bloque, "titulo": limpiar_espacios(titulo)}
        )

    return bloques

def buscar_bloque_articulo(id_boe: str, articulo: str) -> dict[str, str]:
    bloques = extraer_bloques_indice(obtener_indice(id_boe))
    coincidencias = [
        bloque
        for bloque in bloques
        if parece_articulo(bloque["titulo"], articulo)
    ]

    if not coincidencias:
        raise BOEError(
            f"No se encontró el artículo {articulo} en el índice de {id_boe}."
        )
    if len(coincidencias) == 1:
        return coincidencias[0]

    numero = normalizar_numero_articulo(articulo)
    coincidencias.sort(
        key=lambda bloque: (
            normalizar_texto(bloque["titulo"]) != f"articulo {numero}",
            len(bloque["titulo"]),
        )
    )
    return coincidencias[0]


def obtener_bloque(id_boe: str, id_bloque: str) -> ET.Element:
    id_boe = extraer_id_boe(id_boe)
    if not id_boe:
        raise ValueError("Identificador BOE no válido.")

    id_bloque = limpiar_espacios(id_bloque)
    if not id_bloque:
        raise ValueError("Identificador de bloque no válido.")

    return descargar_xml(
        url=f"{BASE_URL}/id/{id_boe}/texto/bloque/{id_bloque}",
        ruta_cache=ruta_cache_bloque(id_boe, id_bloque),
    )


def extraer_texto_bloque(raiz: ET.Element) -> tuple[str, str]:
    titulo = buscar_primer_texto(raiz, {"titulo", "nombre", "cabecera"})
    candidatos_texto = {"texto", "contenido", "parrafo", "p"}
    partes: list[str] = []

    for elemento in raiz.iter():
        if nombre_etiqueta(elemento) not in candidatos_texto:
            continue
        texto = texto_completo(elemento)
        if texto and texto not in partes:
            partes.append(texto)

    texto = limpiar_espacios(" ".join(partes)) if partes else texto_completo(raiz)
    if titulo and texto.startswith(titulo):
        texto = texto[len(titulo):].strip()

    return limpiar_espacios(titulo), limpiar_espacios(texto)


def obtener_articulo(nombre_norma: str, articulo: str) -> ArticuloBOE:
    norma = buscar_norma(nombre_norma)

    articulo_solicitado = limpiar_espacios(articulo).replace(",", ".")

    # El índice del BOE contiene el artículo completo, no cada apartado.
    # Ejemplo: para "82.2" debemos buscar el bloque del artículo "82".
    articulo_indice = articulo_solicitado.split(".", 1)[0]

    bloque = buscar_bloque_articulo(
        norma.id_boe,
        articulo_indice,
    )

    raiz_bloque = obtener_bloque(
        norma.id_boe,
        bloque["id_bloque"],
    )

    titulo_bloque, texto = extraer_texto_bloque(
        raiz_bloque
    )

    if not texto:
        raise BOEError(
            f"El artículo {articulo_solicitado} "
            f"de {norma.id_boe} no contiene texto."
        )

    return ArticuloBOE(
        nombre_norma=nombre_norma,
        id_boe=norma.id_boe,
        departamento=norma.departamento,
        articulo=articulo_solicitado,
        id_bloque=bloque["id_bloque"],
        titulo_bloque=titulo_bloque or bloque["titulo"],
        texto=texto,
    )

def limpiar_cache_articulo(id_boe: str, id_bloque: str) -> None:
    ruta = ruta_cache_bloque(id_boe, id_bloque)
    if ruta.exists():
        ruta.unlink()


def limpiar_cache_norma(nombre_norma: str) -> None:
    cache = cargar_cache_normas()
    clave = normalizar_texto(nombre_norma)
    if clave in cache:
        del cache[clave]
        guardar_json(CACHE_NORMAS, cache)

def ruta_cache_texto_completo(id_boe: str) -> Path:
    return ruta_cache_norma(id_boe) / "texto_completo.xml"


def obtener_texto_completo_norma(id_boe: str) -> ET.Element:
    id_boe = extraer_id_boe(id_boe)

    if not id_boe:
        raise ValueError("Identificador BOE no válido.")

    return descargar_xml(
        url=f"{BASE_URL}/id/{id_boe}/texto",
        ruta_cache=ruta_cache_texto_completo(id_boe),
    )

def calcular_sha256(ruta: Path) -> str:
    hash_sha256 = hashlib.sha256()

    with ruta.open("rb") as fichero:
        for bloque in iter(lambda: fichero.read(1024 * 1024), b""):
            hash_sha256.update(bloque)

    return hash_sha256.hexdigest()


def guardar_documento_permanente(id_boe: str) -> tuple[Path, str]:
    """
    Guarda una copia permanente del XML consolidado completo.

    Devuelve:
        (ruta_documento, hash_sha256)
    """
    id_boe = extraer_id_boe(id_boe)

    if not id_boe:
        raise ValueError("Identificador BOE no válido.")

    # Descarga el texto si todavía no está en caché.
    obtener_texto_completo_norma(id_boe)

    origen = ruta_cache_texto_completo(id_boe)

    if not origen.exists():
        raise BOEError(
            f"No se encontró el XML descargado de la norma {id_boe}."
        )

    carpeta_destino = DOCUMENTOS_DIR / id_boe
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    destino = carpeta_destino / "documento.xml"

    # Copia atómica para no dejar un archivo incompleto.
    temporal = destino.with_suffix(".xml.tmp")
    shutil.copyfile(origen, temporal)
    temporal.replace(destino)

    return destino, calcular_sha256(destino)

def registrar_documento_fuente(
    norma: NormaBOE,
    identificador_oficial: str,
    ruta_documento: Path,
    hash_documento: str,
) -> None:
    """
    Inserta o actualiza una norma en documentos_fuente.
    """
    if not RUTA_DB.exists():
        raise FileNotFoundError(
            f"No existe la base de datos: {RUTA_DB}"
        )

    ruta_relativa = ruta_documento.relative_to(RAIZ_PROYECTO)
    
    titulo_oficial = norma.titulo
    identificador_guardado = identificador_oficial

    with sqlite3.connect(RUTA_DB) as conexion:
        conexion.execute(
            """
            INSERT INTO documentos_fuente (
                id_boe,
                identificador_oficial,
                titulo_oficial,
                tipo_norma,
                fecha_publicacion,
                fecha_version,
                url_boe,
                ruta_documento,
                ruta_indice,
                hash,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, CURRENT_TIMESTAMP)

            ON CONFLICT(id_boe) DO UPDATE SET
                identificador_oficial = excluded.identificador_oficial,
                titulo_oficial = excluded.titulo_oficial,
                tipo_norma = excluded.tipo_norma,
                fecha_publicacion = excluded.fecha_publicacion,
                fecha_version = excluded.fecha_version,
                url_boe = excluded.url_boe,
                ruta_documento = excluded.ruta_documento,
                hash = excluded.hash
            """,
            (
                norma.id_boe,
                identificador_guardado,
                titulo_oficial,
                None,
                None,
                None,
                f"https://www.boe.es/buscar/act.php?id={norma.id_boe}",
                ruta_relativa.as_posix(),
                hash_documento,
            ),
        )

def importar_norma(nombre_norma):

    norma = buscar_norma(nombre_norma)

    ruta_documento, hash_documento = guardar_documento_permanente(
        norma.id_boe
    )

    registrar_documento_fuente(
        norma=norma,
        identificador_oficial=nombre_norma,
        ruta_documento=ruta_documento,
        hash_documento=hash_documento,
    )

    return ruta_documento

def extraer_numero_y_titulo_articulo(texto: str) -> tuple[str, str]:

    texto = limpiar_espacios(texto)

    coincidencia = re.match(
        r"^Artículo\s+([^.]+)\.\s*(.*?)(?:\.\s|$)",
        texto,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return "", ""

    numero = limpiar_espacios(coincidencia.group(1))
    titulo = limpiar_espacios(coincidencia.group(2))

    return numero, titulo


def extraer_articulos(raiz: ET.Element) -> list[ArticuloNorma]:

    articulos = []

    for bloque in raiz.iter():

        if nombre_etiqueta(bloque) != "bloque":
            continue

        if bloque.attrib.get("tipo") != "precepto":
            continue

        versiones = [
            hijo
            for hijo in list(bloque)
            if nombre_etiqueta(hijo) == "version"
        ]

        if not versiones:
            continue

        versiones.sort(
            key=lambda version: version.attrib.get("fecha_vigencia", "")
        )

        texto = texto_completo(versiones[-1])

        numero, titulo = extraer_numero_y_titulo_articulo(texto)

        if not numero:
            continue

        articulos.append(
            ArticuloNorma(
                numero=numero,
                titulo=titulo,
                texto=texto,
            )
        )

    return articulos

def listar_articulos(nombre_norma: str) -> list[ArticuloNorma]:

    if nombre_norma in _cache_articulos:
        return _cache_articulos[nombre_norma]

    norma = buscar_norma(nombre_norma)

    raiz = obtener_texto_completo_norma(
        norma.id_boe
    )

    articulos = extraer_articulos(raiz)

    _cache_articulos[nombre_norma] = articulos

    return articulos

def _palabras_significativas(texto: str) -> set[str]:

    texto = texto.lower()

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    palabras = re.findall(r"[a-záéíóúüñ0-9]+", texto)

    return {
        palabra
        for palabra in palabras
        if len(palabra) >= 4
        and palabra not in PALABRAS_VACIAS
    }
def _normalizar_busqueda(texto: str) -> str:

    texto = texto.lower()

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = re.sub(r"[^a-z0-9]+", " ", texto)

    return limpiar_espacios(texto)

def buscar_articulos_relevantes(
    nombre_norma: str,
    enunciado: str,
    opciones: list[str],
    limite: int = 5,
) -> list[tuple[ArticuloNorma, float]]:

    articulos = listar_articulos(nombre_norma)

    enunciado_normalizado = _normalizar_busqueda(enunciado)
    palabras_enunciado = _palabras_significativas(enunciado)

    palabras_opciones = _palabras_significativas(
        " ".join(opcion for opcion in opciones if opcion)
    )

    resultados = []

    for articulo in articulos:

        titulo_normalizado = _normalizar_busqueda(articulo.titulo)

        palabras_titulo = _palabras_significativas(articulo.titulo)
        palabras_texto = _palabras_significativas(articulo.texto)

        puntuacion = 0.0

        if (
            titulo_normalizado
            and titulo_normalizado in enunciado_normalizado
        ):
            puntuacion += 20

        puntuacion += len(
            palabras_enunciado & palabras_titulo
        ) * 5

        puntuacion += len(
            palabras_enunciado & palabras_texto
        ) * 3

        puntuacion += len(
            palabras_opciones & palabras_titulo
        ) * 2

        puntuacion += len(
            palabras_opciones & palabras_texto
        ) * 0.5

        if puntuacion > 0:
            resultados.append((articulo, puntuacion))

    resultados.sort(
        key=lambda resultado: resultado[1],
        reverse=True,
    )

    return resultados[:limite]

def prueba_manual() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Obtiene el texto consolidado de un artículo mediante la API "
            "oficial del BOE. Al desempatar, prioriza Comunitat Valenciana "
            "y después Jefatura del Estado."
        )
    )
    parser.add_argument("norma", help='Ejemplo: "Ley 1/2022"')
    parser.add_argument("articulo", help='Ejemplo: "1" o "47 bis"')
    argumentos = parser.parse_args()

    resultado = obtener_articulo(argumentos.norma, argumentos.articulo)

    print()
    print(f"Norma: {resultado.nombre_norma}")
    print(f"BOE: {resultado.id_boe}")
    print(f"Departamento: {resultado.departamento}")
    print(f"Artículo: {resultado.articulo}")
    print(f"Bloque: {resultado.id_bloque}")
    print(f"Título: {resultado.titulo_bloque}")
    print()
    print(resultado.texto)



if __name__ == "__main__":
    prueba_manual()