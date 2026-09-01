"""
Armado de la ficha de merito por persona.

Funciones puras: reciben las dimensiones ya calculadas y deciden que se
muestra y que se marca como sin datos. No componen un promedio a proposito -un
ascenso se decide entre dos y cinco candidatos, y ahi un numero unico no agrega
informacion: esconde la que hay-.
"""

from app.database.asistencia_merito import Cumplimiento
from app.services.feedback_score import PuntajeFeedback
from app.services.merito import (
    DIMENSIONES_TOTALES,
    armar_ficha,
    describir_trayectoria,
)
from app.services.turnero_client import MetricaTurnero


def _cumpl(dias=60, abusos=3):
    return Cumplimiento(diasTrabajados=dias, diasConAbuso=abusos,
                        tasaAbuso=round(abusos / dias, 2) if dias else None)


def _turnero(validas=100, atendidos=120):
    return MetricaTurnero(
        dniInstitucional="30111222", atendidos=atendidos, validas=validas,
        breves=15, anomalias=5, promedioSegundos=480.0,
        desvioContraMedianaSegundos=-30.0, horasBox=140.0,
    )


# -- Que se muestra y que no ---------------------------------------------------

def test_una_dimension_sin_dato_se_marca_no_medida():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position="Analista",
        cumplimiento=None, actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=1, suficiente=False),
        historial=[],
    )
    assert f.cumplimiento.medida is False
    assert f.cumplimiento.valor is None
    assert f.feedback.medida is False


def test_la_ficha_no_devuelve_un_promedio_compuesto():
    """
    El ascenso se decide entre pocos candidatos leyendo la evidencia. Un numero
    unico no agrega informacion, esconde de donde sale.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(), actividad=4.2, turnero=_turnero(),
        feedback=PuntajeFeedback(promedio=8.0, evaluadores=5, suficiente=True),
        historial=[4.0, 4.1, 4.2],
    )
    assert not hasattr(f, "total")
    assert not hasattr(f, "promedio")
    assert not hasattr(f, "scoreFinal")


def test_la_cobertura_cuenta_las_dimensiones_medidas():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(), actividad=4.2, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=2, suficiente=False),
        historial=[],
    )
    assert f.cobertura == 2
    assert f.dimensionesTotales == DIMENSIONES_TOTALES


def test_el_feedback_insuficiente_no_expone_el_promedio():
    """
    Con menos de 3 evaluadores el motor devuelve promedio None; la ficha no
    debe inventarlo ni mostrar el conteo como si fuera un puntaje.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=None, actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=2, suficiente=False),
        historial=[],
    )
    assert f.feedback.valor is None
    assert "2" in f.feedback.detalle


def test_el_cumplimiento_informa_la_recurrencia_no_los_minutos():
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=_cumpl(dias=60, abusos=15), actividad=None, turnero=None,
        feedback=PuntajeFeedback(promedio=None, evaluadores=0, suficiente=False),
        historial=[],
    )
    assert f.cumplimiento.valor == 0.25
    assert "15" in f.cumplimiento.detalle and "60" in f.cumplimiento.detalle


def test_el_operativo_usa_las_validas_no_los_atendidos():
    """
    `atendidos` incluye breves y anomalias, que son justamente las atenciones
    de plausibilidad dudosa. La dimension se apoya en las validas.
    """
    f = armar_ficha(
        employee_id=1, nombre="Ana", position=None,
        cumplimiento=None, actividad=None, turnero=_turnero(validas=100, atendidos=120),
        feedback=PuntajeFeedback(promedio=None, evaluadores=0, suficiente=False),
        historial=[],
    )
    assert f.operativo.valor == 100
    assert "120" in f.operativo.detalle


# -- Trayectoria ---------------------------------------------------------------

def test_sin_historial_suficiente_no_se_describe_tendencia():
    assert describir_trayectoria([]) == "sin historial"
    assert describir_trayectoria([4.0]) == "sin historial"


def test_una_subida_sostenida_se_describe_como_mejora():
    assert describir_trayectoria([3.0, 3.5, 4.2]) == "mejorando"


def test_una_caida_sostenida_se_describe_como_baja():
    assert describir_trayectoria([4.2, 3.5, 3.0]) == "bajando"


def test_una_variacion_chica_se_considera_estable():
    assert describir_trayectoria([4.0, 4.05, 3.98]) == "sostenida"


def test_los_periodos_sin_medicion_no_cuentan_como_caida():
    """
    Un None en el historial es "no se lo midio", no un cero. Tratarlo como cero
    dibujaria una caida que nunca ocurrio.
    """
    assert describir_trayectoria([4.0, None, 4.1]) == "sostenida"
