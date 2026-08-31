"""
Progreso del ciclo de Feedback 360.

Regresion del 850%: el progreso calculaba el total con los evaluables de HOY y
las completadas con TODAS las respuestas del periodo. Un evaluador que habia
respondido sobre companeros que despues cambiaron de area quedaba con
68 respuestas sobre un total de 8 -las de ambiente general, lo unico que le
quedaba aplicable- y la barra marcaba 850%.

pares_aplicables es ahora la definicion unica del universo del ciclo, asi que
completadas <= total se cumple por construccion.
"""

from app.routes.feedback import pares_aplicables


def _pregunta(id_, ambiente=False, liderazgo=False):
    return {"id": id_, "esAmbienteGeneral": ambiente, "soloLiderazgo": liderazgo}


def _evaluable(id_, jerarquico=False):
    return {"id": id_, "esJerarquico": jerarquico}


# -- Composicion del universo --------------------------------------------------

def test_las_preguntas_de_ambiente_general_no_apuntan_a_nadie():
    pares = pares_aplicables([], [_pregunta(1, ambiente=True)])
    assert pares == {(1, None)}


def test_una_pregunta_de_par_se_multiplica_por_cada_evaluable():
    pares = pares_aplicables(
        [_evaluable(3), _evaluable(9)], [_pregunta(1)],
    )
    assert pares == {(1, 3), (1, 9)}


def test_las_preguntas_de_liderazgo_solo_aplican_a_jerarquicos():
    pares = pares_aplicables(
        [_evaluable(3, jerarquico=True), _evaluable(9, jerarquico=False)],
        [_pregunta(1, liderazgo=True)],
    )
    assert pares == {(1, 3)}


def test_sin_evaluables_solo_quedan_las_de_ambiente_general():
    """El caso real: un empleado solo en su departamento."""
    preguntas = [_pregunta(1), _pregunta(2), _pregunta(3, ambiente=True)]
    pares = pares_aplicables([], preguntas)
    assert pares == {(3, None)}


# -- La regresion del 850% -----------------------------------------------------

def test_las_respuestas_sobre_alguien_que_ya_no_es_evaluable_no_cuentan():
    """
    Escenario exacto del bug: el evaluador respondio 30 preguntas sobre el
    empleado 3 y 30 sobre el 9, y despues quedo solo en su area. Esas 60
    respuestas ya no pertenecen a su ciclo.
    """
    preguntas = [_pregunta(i) for i in range(1, 31)] + [_pregunta(100, ambiente=True)]
    pares = pares_aplicables([], preguntas)

    respondidas = (
        [(i, 3) for i in range(1, 31)]
        + [(i, 9) for i in range(1, 31)]
        + [(100, None)]
    )
    completadas = sum(1 for r in respondidas if r in pares)

    assert len(pares) == 1
    assert completadas == 1
    assert completadas <= len(pares), "el progreso nunca puede pasar el 100%"


def test_el_progreso_nunca_supera_el_total():
    preguntas = [_pregunta(1), _pregunta(2, ambiente=True)]
    evaluables = [_evaluable(3)]
    pares = pares_aplicables(evaluables, preguntas)

    # Respuestas que incluyen a un evaluado que ya no esta en el area (id 99).
    respondidas = [(1, 3), (2, None), (1, 99), (2, 99)]
    completadas = sum(1 for r in respondidas if r in pares)

    assert completadas == 2
    assert len(pares) == 2
    assert completadas / len(pares) <= 1.0


def test_ciclo_completo_da_exactamente_cien_por_ciento():
    preguntas = [_pregunta(1), _pregunta(2, ambiente=True)]
    evaluables = [_evaluable(3), _evaluable(9)]
    pares = pares_aplicables(evaluables, preguntas)

    completadas = sum(1 for r in pares if r in pares)
    assert completadas == len(pares) == 3
