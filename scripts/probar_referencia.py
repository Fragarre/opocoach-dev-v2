from pathlib import Path

from temario.estructura import cargar_estructura
from temario.referencias import crear_referencia_juridica


estructura = cargar_estructura(
    Path("data_temarios/estructuras/BOE-A-1978-31229.json")
)

referencia = crear_referencia_juridica(
    estructura,
    "Constitución Española",
    "tvi",
    "tix",
)

print(referencia)