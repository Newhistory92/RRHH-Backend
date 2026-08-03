"""
Interpretacion de marcaciones crudas: de las fichadas del dia a los dos extremos
confiables de la jornada, mas las incidencias que quedaron abiertas.

Funcion pura: no toca la base de datos ni los relojes. Es el modulo de mas bajo
nivel del calculo de asistencia; asistencia_calc importa de aca, nunca al reves.

Interpretar marcaciones y calcular saldo son responsabilidades distintas: la
primera decide QUE paso, la segunda CUANTO vale. Separarlas deja las dos
testeables con fixtures triviales.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

VENTANA_REBOTE_MIN = 5

INCIDENCIA_FALTA_SALIDA = "falta_salida"
INCIDENCIA_FALTA_ENTRADA = "falta_entrada"
INCIDENCIA_SIN_CRONOGRAMA = "sin_cronograma"
INCIDENCIA_REBOTE = "rebote_descartado"


@dataclass(frozen=True)
class HorarioDia:
    """horaInicio y horaFin son decimales: 8.5 es las 08:30."""
    horaInicio: float
    horaFin: float
    horasTrabajo: float


@dataclass(frozen=True)
class Correccion:
    """Carga manual de RRHH. Cualquiera de los dos extremos puede venir vacio."""
    entrada: Optional[datetime] = None
    salida: Optional[datetime] = None


@dataclass(frozen=True)
class ExtremosDia:
    entrada: Optional[datetime]
    salida: Optional[datetime]
    incidencias: tuple[str, ...]
    descartadas: int
    entrada_manual: bool
    salida_manual: bool


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def deduplicar(marcaciones: list[datetime],
               ventana_min: int = VENTANA_REBOTE_MIN) -> list[datetime]:
    """
    Colapsa marcas separadas por menos de la ventana, conservando la primera de
    cada grupo.

    La comparacion es contra la ultima marca CONSERVADA, no contra la anterior
    cruda: de lo contrario una rafaga de marcas de a dos minutos se encadenaria
    indefinidamente y terminaria fusionando una jornada entera.

    No distingue el reloj de origen a proposito, y por eso la firma no recibe la
    IP del equipo. Hay dos relojes y un empleado puede fichar en ambos al
    llegar; si se deduplicara por equipo esas dos marcas sobrevivirian y el
    motor las leeria como entrada y salida de una jornada de tres minutos.
    """
    if not marcaciones:
        return []
    ventana = timedelta(minutes=ventana_min)
    ordenadas = sorted(marcaciones)
    conservadas = [ordenadas[0]]
    for m in ordenadas[1:]:
        if m - conservadas[-1] >= ventana:
            conservadas.append(m)
    return conservadas


def normalizar(marcaciones: list[datetime],
               horario: Optional[HorarioDia],
               correccion: Optional[Correccion] = None,
               ventana_min: int = VENTANA_REBOTE_MIN) -> ExtremosDia:
    """
    Marcaciones crudas del dia -> extremos confiables mas sus incidencias.

    La correccion de RRHH pisa lo que diga el reloj y limpia la incidencia del
    extremo que aporta. sin_cronograma sobrevive: la correccion completa los
    horarios de un dia, no le asigna un cronograma al empleado.
    """
    limpias = deduplicar(marcaciones, ventana_min)
    descartadas = len(marcaciones) - len(limpias)
    incidencias: list[str] = []
    if descartadas:
        incidencias.append(INCIDENCIA_REBOTE)

    entrada: Optional[datetime] = None
    salida: Optional[datetime] = None

    if horario is None:
        # Sin horario no hay contra que comparar: se toman los extremos crudos
        # y el dia se resuelve como sin_horario aguas abajo.
        incidencias.append(INCIDENCIA_SIN_CRONOGRAMA)
        if limpias:
            entrada = limpias[0]
            if len(limpias) >= 2:
                salida = limpias[-1]
    elif len(limpias) >= 2:
        entrada = limpias[0]
        salida = limpias[-1]
    elif len(limpias) == 1:
        marca = limpias[0]
        h = _hora_decimal(marca)
        # El empate se resuelve hacia salida: los datos del periodo observado
        # muestran mas marcas unicas vespertinas que matutinas.
        if abs(h - horario.horaInicio) < abs(h - horario.horaFin):
            entrada = marca
            incidencias.append(INCIDENCIA_FALTA_SALIDA)
        else:
            salida = marca
            incidencias.append(INCIDENCIA_FALTA_ENTRADA)

    c = correccion or Correccion()
    entrada_manual = c.entrada is not None
    salida_manual = c.salida is not None
    if entrada_manual:
        entrada = c.entrada
        incidencias = [i for i in incidencias if i != INCIDENCIA_FALTA_ENTRADA]
    if salida_manual:
        salida = c.salida
        incidencias = [i for i in incidencias if i != INCIDENCIA_FALTA_SALIDA]

    return ExtremosDia(
        entrada=entrada,
        salida=salida,
        incidencias=tuple(incidencias),
        descartadas=descartadas,
        entrada_manual=entrada_manual,
        salida_manual=salida_manual,
    )
