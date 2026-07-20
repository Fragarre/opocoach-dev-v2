"""
==============================================================================
Proyecto : OpoCoach
Estado   : OK

Archivo : openai_api.py
Ruta    :scripts/openai_api.py

Objetivo:
    Centralizar las llamadas a la API de OpenAI y registrar su coste.

Entradas:
    - Prompt.
    - Modelo.
    - Parámetros de respuesta.

Salidas:
    - Respuesta estructurada y métricas de uso.

Modifica BD:
    No

Tablas afectadas:
    - Ninguna.

Utiliza:
    - Ninguna.

Flujo:
    1. Carga credenciales.
    2. Ejecuta la solicitud.
    3. Registra tokens y coste.

Observaciones:
    - Ninguna.

==============================================================================
"""
import csv
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

cliente = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY_OPOCOACH")
)


PRECIOS = {
    "gpt-5-mini": {
        "input": 0.75,
        "output": 4.50,
    },
    "gpt-5.4": {
        "input": 2.50,
        "output": 15.00,
    },
    "gpt-5.4-mini": {
        "input": 0.75,
        "output": 4.50,
    },
}


ROOT = Path(__file__).resolve().parents[1]

LOG_COSTES = (
    ROOT
    / "logs"
    / "costes_ia.csv"
)


def registrar_coste(
    modelo,
    operacion,
    tiempo,
    input_tokens,
    cached_tokens,
    output_tokens,
    coste,
):

    LOG_COSTES.parent.mkdir(exist_ok=True)

    existe = LOG_COSTES.exists()

    with LOG_COSTES.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.writer(f)

        if not existe:
            writer.writerow([
                "fecha",
                "hora",
                "modelo",
                "operacion",
                "tiempo",
                "input",
                "cached_input",
                "output",
                "coste",
            ])

        ahora = datetime.now()

        writer.writerow([
            ahora.strftime("%Y-%m-%d"),
            ahora.strftime("%H:%M:%S"),
            modelo,
            operacion,
            f"{tiempo:.2f}",
            input_tokens,
            cached_tokens,
            output_tokens,
            f"{coste:.6f}",
        ])

def llamar_responses(
    input_api,
    modelo="gpt-5.4-mini",
    operacion="general",
):

    if modelo not in PRECIOS:

        raise ValueError(
            f"No existen precios configurados "
            f"para el modelo {modelo!r}."
        )

    t0 = time.perf_counter()

    respuesta = cliente.responses.create(
        model=modelo,
        input=input_api,
    )

    tiempo = time.perf_counter() - t0

    uso = respuesta.usage

    entrada = uso.input_tokens
    salida = uso.output_tokens

    cached = 0

    try:

        cached = (
            uso
            .input_tokens_details
            .cached_tokens
        )

    except Exception:

        pass

    precio = PRECIOS[
        modelo
    ]

    coste = (
        entrada
        * precio["input"]
        / 1_000_000
        +
        salida
        * precio["output"]
        / 1_000_000
    )

    registrar_coste(
        modelo=modelo,
        operacion=operacion,
        tiempo=tiempo,
        input_tokens=entrada,
        cached_tokens=cached,
        output_tokens=salida,
        coste=coste,
    )

    print()
    print("=" * 60)
    print("IA")
    print("=" * 60)
    print(f"Modelo............. {modelo}")
    print(f"Operación.......... {operacion}")
    print(f"Tiempo............. {tiempo:.2f} s")
    print(f"Input.............. {entrada}")
    print(f"Cached............. {cached}")
    print(f"Output............. {salida}")
    print(f"Coste.............. ${coste:.6f}")
    print()

    return respuesta, tiempo

def seleccionar_fragmento(
    prompt,
    modelo="gpt-5.4-mini",
    operacion="general",
):

    respuesta, _ = llamar_responses(
        input_api=prompt,
        modelo=modelo,
        operacion=operacion,
    )

    return respuesta.output_text

def seleccionar_fragmento_json(
    prompt,
    modelo="gpt-5.4-mini",
    operacion="general",
):

    import json

    respuesta = seleccionar_fragmento(
        prompt=prompt,
        modelo=modelo,
        operacion=operacion,
    )
    
    return json.loads(respuesta)

def generar_explicacion_ia(
    prompt,
    modelo="gpt-5.4-mini",
):

    return seleccionar_fragmento_json(
        prompt=prompt,
        modelo=modelo,
        operacion="explicacion",
    )