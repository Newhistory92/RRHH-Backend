"""
Endpoints de puntaje de feedback.

Los handlers se invocan directamente, sin servidor HTTP, siguiendo el patron
de tests/test_score_exencion_endpoint.py.
"""

from datetime import date

from app.routes.feedback import cargar_respuestas_normalizadas
from tests.fakes import FakeSession

FRAG = "FROM RespuestaFeedback rf"


def _fila(evaluado, evaluador, valor, categoria, inversa, texto="¿Cumple?"):
    return {
        "evaluadoEmployeeId": evaluado, "evaluadorEmployeeId": evaluador,
        "valorEscala": valor, "categoria": categoria,
        "esInversa": inversa, "texto": texto,
    }


def test_agrupa_las_respuestas_por_evaluado():
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Responsabilidad", False),
        _fila(9, 1, 4, "Responsabilidad", False),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert set(r.keys()) == {3, 9}


def test_aplica_la_polaridad_al_cargar():
    """Una inversa con 5 crudo tiene que llegar al motor como 1."""
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Responsabilidad", True, "¿Genera conflictos innecesarios?"),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert r[3][0].valor == 1


def test_marca_las_categorias_de_riesgo():
    db = FakeSession({FRAG: [
        _fila(3, 1, 5, "Conductas de riesgo", False),
        _fila(3, 1, 5, "Responsabilidad", False),
    ]})
    r = cargar_respuestas_normalizadas(db, date(2026, 7, 1))
    assert [x.esRiesgo for x in r[3]] == [True, False]


def test_sin_respuestas_devuelve_diccionario_vacio():
    db = FakeSession({FRAG: []})
    assert cargar_respuestas_normalizadas(db, date(2026, 7, 1)) == {}
