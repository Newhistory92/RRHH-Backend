"""
Regla de la jubilacion que no toca la base.

Vive aparte del SQL para poder testear la condicion sin base ni TestClient,
igual que jubilacion_cumplida se usa tanto al guardar como en el job diario:
una sola definicion de "ya esta jubilado" para los dos caminos.
"""

from datetime import date
from typing import Optional


def jubilacion_cumplida(fecha: Optional[date], hoy: date) -> bool:
    """
    Si la fecha de jubilacion ya corresponde.

    None es "no jubilado". Una fecha futura tampoco jubila: RRHH carga la fecha
    cuando la sabe y la persona sigue trabajando hasta ese dia.
    """
    return fecha is not None and fecha <= hoy
