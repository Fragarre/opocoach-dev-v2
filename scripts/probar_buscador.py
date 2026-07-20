from pathlib import Path

from temario.estructura import cargar_estructura, obtener_bloques
from temario.rangos import calcular_rangos
from temario.buscador import buscar_por_id, obtener_rangos


estructura = cargar_estructura(
    Path("data_temarios/estructuras/BOE-A-1978-31229.json")
)

bloques = obtener_bloques(estructura)

rangos = calcular_rangos(bloques)

resultado = buscar_por_id(
    rangos,
    "tvi",
    "tix",
)

print()

for bloque in resultado:
    print(
        f'{bloque["titulo"]:<25} {bloque["rango"]}'
    )

print()
print(obtener_rangos(resultado))