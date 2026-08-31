"""
Motor de puntaje de Feedback 360 y alertas de conducta.

Funciones puras: reciben respuestas ya normalizadas y devuelven el puntaje y
las banderas. Sin base de datos, para que las reglas delicadas -piso de
evaluadores, exclusion de categorias de riesgo- se prueben sin fixtures.
"""

from app.services.feedback_score import (
    MIN_EVALUADORES,
    UMBRAL_ALERTA,
    RespuestaNorm,
    detectar_alertas,
    puntaje_feedback,
)


def _r(evaluador, valor, categoria="Responsabilidad", riesgo=False, texto="¿Cumple?"):
    return RespuestaNorm(
        evaluadorId=evaluador, categoria=categoria, valor=valor,
        esRiesgo=riesgo, preguntaTexto=texto,
    )


# -- Piso de evaluadores -------------------------------------------------------

def test_con_dos_evaluadores_no_hay_puntaje():
    r = puntaje_feedback([_r(1, 5), _r(2, 5)])
    assert r.promedio is None
    assert r.suficiente is False
    assert r.evaluadores == 2
    assert r.porCategoria == {}


def test_con_tres_evaluadores_si_hay_puntaje():
    r = puntaje_feedback([_r(1, 4), _r(2, 4), _r(3, 4)])
    assert r.suficiente is True
    assert r.promedio == 4.0
    assert r.evaluadores == 3


def test_un_evaluador_que_responde_muchas_preguntas_cuenta_como_uno():
    respuestas = [_r(1, 5) for _ in range(30)]
    r = puntaje_feedback(respuestas)
    assert r.evaluadores == 1
    assert r.suficiente is False


def test_sin_respuestas_no_hay_puntaje():
    r = puntaje_feedback([])
    assert r.promedio is None
    assert r.evaluadores == 0


# -- Que entra al promedio -----------------------------------------------------

def test_las_categorias_de_riesgo_no_entran_al_promedio():
    """
    Un 1 en conducta no debe bajar el promedio de desempeno: se informa como
    alerta aparte, para que no se diluya ni se compense con puntualidad.
    """
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True),
    ]
    r = puntaje_feedback(respuestas)
    assert r.promedio == 5.0


def test_el_promedio_se_desglosa_por_categoria():
    respuestas = [
        _r(1, 5, categoria="Comunicación"), _r(2, 5, categoria="Comunicación"),
        _r(3, 5, categoria="Comunicación"),
        _r(1, 3, categoria="Responsabilidad"), _r(2, 3, categoria="Responsabilidad"),
        _r(3, 3, categoria="Responsabilidad"),
    ]
    r = puntaje_feedback(respuestas)
    assert r.porCategoria["Comunicación"] == 5.0
    assert r.porCategoria["Responsabilidad"] == 3.0
    assert r.promedio == 4.0


def test_un_valor_invertido_baja_el_promedio():
    """
    Regresion del bug: "genera conflictos = Siempre" llega aca ya normalizado
    a 1 y tiene que bajar el promedio, no subirlo.
    """
    buenos = [_r(1, 5), _r(2, 5), _r(3, 5)]
    con_malo = buenos + [_r(1, 1, texto="¿Genera conflictos innecesarios?")]
    assert puntaje_feedback(con_malo).promedio < puntaje_feedback(buenos).promedio


# -- Alertas -------------------------------------------------------------------

def test_sin_el_piso_de_evaluadores_no_se_devuelven_alertas():
    respuestas = [_r(1, 1, categoria="Conductas de riesgo", riesgo=True)]
    assert detectar_alertas(respuestas) == []


def test_con_el_piso_alcanzado_un_solo_reporte_ya_alerta():
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
    ]
    alertas = detectar_alertas(respuestas)
    assert len(alertas) == 1
    assert alertas[0].preguntaTexto == "¿Discrimina?"
    assert alertas[0].reportan == 1
    assert alertas[0].evaluadores == 3


def test_el_umbral_marca_las_dos_peores_respuestas():
    base = [_r(1, 5), _r(2, 5), _r(3, 5)]
    riesgo = dict(categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?")

    assert len(detectar_alertas(base + [_r(1, 3, **riesgo)])) == 0
    assert len(detectar_alertas(base + [_r(1, 2, **riesgo)])) == 1
    assert len(detectar_alertas(base + [_r(1, 1, **riesgo)])) == 1
    assert UMBRAL_ALERTA == 2


def test_las_categorias_de_desempeno_nunca_generan_alertas():
    respuestas = [_r(1, 1), _r(2, 1), _r(3, 1)]
    assert detectar_alertas(respuestas) == []


def test_varios_reportes_de_la_misma_pregunta_se_agrupan():
    respuestas = [
        _r(1, 5), _r(2, 5), _r(3, 5),
        _r(1, 1, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
        _r(2, 2, categoria="Conductas de riesgo", riesgo=True, texto="¿Discrimina?"),
    ]
    alertas = detectar_alertas(respuestas)
    assert len(alertas) == 1
    assert alertas[0].reportan == 2
    assert alertas[0].evaluadores == 3


def test_el_piso_cuenta_evaluadores_de_riesgo_tambien():
    """
    El piso mide participacion del grupo -cuanta gente evaluo a la persona-,
    que es lo que protege el anonimato, no cuantas respuestas alimentan el
    promedio.
    """
    riesgo = dict(categoria="Riesgos laborales", riesgo=True, texto="¿Lo evitas?")
    respuestas = [_r(1, 5), _r(2, 5), _r(3, 1, **riesgo)]
    r = puntaje_feedback(respuestas)
    assert r.evaluadores == 3
    assert r.suficiente is True
    assert MIN_EVALUADORES == 3
