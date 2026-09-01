"""
Endpoint de la ficha de merito por gerencia.

El handler se invoca directamente, sin servidor HTTP, siguiendo el patron de
tests/test_feedback_endpoints.py.
"""

from app.routes.stats import serie_historica
from tests.fakes import FakeSession

FRAG_HIST = "FROM ScoreHistorico"


def test_la_serie_va_de_la_mas_vieja_a_la_mas_nueva():
    """
    describir_trayectoria compara el primero contra el ultimo, asi que la serie
    tiene que llegarle en orden cronologico. La consulta trae al reves -la mas
    reciente primero- para poder usar TOP.
    """
    db = FakeSession({FRAG_HIST: [
        {"score": 4.2}, {"score": 4.0}, {"score": 3.5},
    ]})
    assert serie_historica(db, 1, 3) == [3.5, 4.0, 4.2]


def test_conserva_los_periodos_sin_medicion():
    """Un None es informacion: hubo corrida y no se la pudo medir."""
    db = FakeSession({FRAG_HIST: [{"score": 4.2}, {"score": None}]})
    assert serie_historica(db, 1, 2) == [None, 4.2]


def test_sin_historial_devuelve_lista_vacia():
    db = FakeSession({FRAG_HIST: []})
    assert serie_historica(db, 1, 5) == []
