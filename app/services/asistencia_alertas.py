"""
Deteccion de uso reiterado de la tolerancia. Funcion pura: recibe los dias ya
leidos de la base y devuelve el resumen, sin tocar SQL.

La racha NO se persiste en ninguna tabla. Es una vista derivada de los flags
que el motor de calculo guarda por dia: guardarla ademas seria estado que se
desincroniza en cuanto cambien los umbrales sin recalcular.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

ESTADO_COMPUTABLE = "ok"


@dataclass(frozen=True)
class DiaAbuso:
    fecha: date
    estado: str
    abuso: bool


@dataclass(frozen=True)
class ResumenAbuso:
    diasAbuso: int
    rachaMaxima: int
    fechasRachaMaxima: tuple[date, ...]
    alerta: bool


def resumir(dias: list[DiaAbuso], dias_alerta: int) -> ResumenAbuso:
    """
    Recorre los dias en orden y devuelve la corrida mas larga de jornadas
    trabajadas consecutivas con abuso.

    Ante empate gana la mas reciente: es la que importa para una conversacion
    hoy. Por eso la comparacion usa >= y no >.
    """
    corriente: list[date] = []
    mejor: list[date] = []
    total = 0

    for d in sorted(dias, key=lambda x: x.fecha):
        if d.estado != ESTADO_COMPUTABLE:
            continue
        if d.abuso:
            total += 1
            corriente.append(d.fecha)
            if len(corriente) >= len(mejor):
                mejor = list(corriente)
        else:
            corriente = []

    return ResumenAbuso(
        diasAbuso=total,
        rachaMaxima=len(mejor),
        fechasRachaMaxima=tuple(mejor),
        alerta=len(mejor) >= dias_alerta,
    )


def validar_umbrales(tol_entrada: int, tol_salida: int,
                     estricta_entrada: Optional[int],
                     estricta_salida: Optional[int],
                     dias_racha: Optional[int]) -> None:
    """
    Verifica la coherencia de la politica de alertas. Lanza ValueError con un
    mensaje listo para mostrar; el traductor a HTTP vive en la capa de rutas.

    Los opcionales en None significan "dejar lo que estaba" y no se validan.

    Una tolerancia estricta por encima de la comun haria que la condicion de
    abuso no se cumpla nunca: las alertas quedarian mudas para siempre sin
    ningun error visible. Se rechaza en vez de aceptar una configuracion que
    no hace nada.
    """
    if estricta_entrada is not None and not (0 <= estricta_entrada <= tol_entrada):
        raise ValueError(
            "toleranciaEstrictaEntradaMin debe estar entre 0 y toleranciaEntradaMin")
    if estricta_salida is not None and not (0 <= estricta_salida <= tol_salida):
        raise ValueError(
            "toleranciaEstrictaSalidaMin debe estar entre 0 y toleranciaSalidaMin")
    if dias_racha is not None and not (1 <= dias_racha <= 30):
        raise ValueError("diasRachaAlerta debe estar entre 1 y 30")
