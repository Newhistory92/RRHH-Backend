"""
Ficha de merito por persona.

Un ascenso se decide entre dos y cinco candidatos, unas pocas veces al ano, y
es caro de errar. En ese regimen un numero compuesto no agrega informacion:
con cinco filas la autoridad puede leer la evidencia directamente, y el
promedio unico solo esconde de donde sale.

Por eso esta ficha NO devuelve un total. Devuelve cada dimension por separado,
cada una con su detalle en palabras y con si esta medida o no, mas cuantas de
las cuatro tienen dato. Que una persona destaque con cobertura 2 de 4 es
informacion que la autoridad necesita, no un defecto a esconder.

Funciones puras: no tocan la base ni la red.
"""

from dataclasses import dataclass

from app.database.asistencia_merito import Cumplimiento
from app.services.feedback_score import PuntajeFeedback
from app.services.turnero_client import MetricaTurnero

# Cumplimiento, actividad en el sistema, volumen operativo y feedback.
DIMENSIONES_TOTALES = 4

# Cuanto tiene que moverse la trayectoria para no considerarse estable. Por
# debajo de esto la variacion es ruido de medicion, no un cambio real.
UMBRAL_TENDENCIA = 0.15


@dataclass(frozen=True)
class DimensionMerito:
    """Una dimension de la ficha. `medida` distingue el cero del sin dato."""
    valor: float | None
    detalle: str
    medida: bool


@dataclass(frozen=True)
class FichaMerito:
    employeeId: int
    nombre: str
    position: str | None
    cumplimiento: DimensionMerito
    actividad: DimensionMerito
    operativo: DimensionMerito
    feedback: DimensionMerito
    trayectoria: str
    cobertura: int
    dimensionesTotales: int


_SIN_DATO = "sin datos"


def describir_trayectoria(historial: list[float | None]) -> str:
    """
    Como viene evolucionando la persona respecto de si misma.

    Es la unica comparacion que se sostiene con pocos datos: no depende de que
    haya companeros comparables ni de que el grupo tenga masa estadistica, asi
    que sirve igual para quien esta solo en su funcion.

    Los None se descartan: son periodos sin medicion, y tratarlos como cero
    dibujaria una caida que nunca ocurrio.
    """
    medidos = [v for v in historial if v is not None]
    if len(medidos) < 2:
        return "sin historial"

    delta = medidos[-1] - medidos[0]
    if delta > UMBRAL_TENDENCIA:
        return "mejorando"
    if delta < -UMBRAL_TENDENCIA:
        return "bajando"
    return "sostenida"


def _dim_cumplimiento(c: Cumplimiento | None) -> DimensionMerito:
    if c is None or c.tasaAbuso is None:
        return DimensionMerito(None, _SIN_DATO, False)
    return DimensionMerito(
        valor=c.tasaAbuso,
        detalle=f"{c.diasConAbuso} de {c.diasTrabajados} días con abuso de tolerancia",
        medida=True,
    )


def _dim_actividad(score: float | None) -> DimensionMerito:
    if score is None:
        return DimensionMerito(None, _SIN_DATO, False)
    return DimensionMerito(
        valor=score,
        detalle=f"{score} eventos por hora trabajada",
        medida=True,
    )


def _dim_operativo(m: MetricaTurnero | None) -> DimensionMerito:
    if m is None:
        return DimensionMerito(None, _SIN_DATO, False)
    # Se informan las validas y no los atendidos: `atendidos` incluye las
    # breves y las anomalias, que son las atenciones de plausibilidad dudosa.
    return DimensionMerito(
        valor=float(m.validas),
        detalle=f"{m.validas} atenciones válidas de {m.atendidos}, {m.horasBox} h de box",
        medida=True,
    )


def _dim_feedback(p: PuntajeFeedback) -> DimensionMerito:
    if not p.suficiente or p.promedio is None:
        return DimensionMerito(
            valor=None,
            detalle=f"{p.evaluadores} evaluadores, hacen falta 3",
            medida=False,
        )
    return DimensionMerito(
        valor=p.promedio,
        detalle=f"{p.promedio} sobre 5, {p.evaluadores} evaluadores",
        medida=True,
    )


def armar_ficha(
    employee_id: int,
    nombre: str,
    position: str | None,
    cumplimiento: Cumplimiento | None,
    actividad: float | None,
    turnero: MetricaTurnero | None,
    feedback: PuntajeFeedback,
    historial: list[float | None],
) -> FichaMerito:
    """Arma la ficha de una persona. No compone ningun total."""
    dims = (
        _dim_cumplimiento(cumplimiento),
        _dim_actividad(actividad),
        _dim_operativo(turnero),
        _dim_feedback(feedback),
    )
    return FichaMerito(
        employeeId=employee_id,
        nombre=nombre,
        position=position,
        cumplimiento=dims[0],
        actividad=dims[1],
        operativo=dims[2],
        feedback=dims[3],
        trayectoria=describir_trayectoria(historial),
        cobertura=sum(1 for d in dims if d.medida),
        dimensionesTotales=DIMENSIONES_TOTALES,
    )
