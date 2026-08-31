"""
Endpoints de puntaje de feedback.

Los handlers se invocan directamente, sin servidor HTTP, siguiendo el patron
de tests/test_score_exencion_endpoint.py.
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.routes.feedback import (
    _check_self_or_admin,
    _diferencia,
    cargar_respuestas_normalizadas,
    get_received_feedback,
)
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


def test_la_diferencia_necesita_los_dos_periodos():
    """
    Si alguno de los dos periodos no llega al piso de evaluadores su promedio
    es None, y entonces no hay diferencia que informar: un "subio 0.4" contra
    un periodo que nunca se pudo medir seria inventado.
    """
    assert _diferencia(4.5, 4.0) == 0.5
    assert _diferencia(4.0, 4.5) == -0.5
    assert _diferencia(4.0, None) is None
    assert _diferencia(None, 4.0) is None
    assert _diferencia(None, None) is None


def test_la_diferencia_redondea_a_dos_decimales():
    assert _diferencia(4.33, 4.11) == 0.22


def test_received_compara_contra_el_periodo_anterior():
    """
    La evolucion tiene que leer el periodo anterior, no solo el actual: sin
    esa segunda carga el bloque mostraria siempre la misma cifra.
    """
    db = FakeSession({
        FRAG: [],
        "COUNT(*) AS c FROM Pregunta": [{"c": 38}],
        "COUNT(*) AS c FROM FeedbackConfig": [{"c": 1}],
    })
    respuesta = get_received_feedback(
        7, db=db, current_user={"employeeId": 7, "permisos": set()}
    )
    periodos = [
        params["periodo"]
        for sql, params in db.ejecutadas
        if params and "periodo" in params
    ]
    assert len(set(periodos)) == 2, "debe consultar dos periodos distintos"
    assert "evolucion" in respuesta
    assert set(respuesta["evolucion"]) == {
        "periodoActual", "promedioActual",
        "periodoAnterior", "promedioAnterior", "diferencia",
    }


def test_sin_respuestas_devuelve_diccionario_vacio():
    db = FakeSession({FRAG: []})
    assert cargar_respuestas_normalizadas(db, date(2026, 7, 1)) == {}


# ─────────────────────────────────────────────────────────────────────────────
# Seguridad: _check_self_or_admin en GET /feedback/received/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────

def test_empleado_puede_leer_su_propio_feedback():
    """Un empleado que pide su propio feedback (employeeId == employee_id) no debe lanzar excepcion."""
    current_user = {"employeeId": 42, "permisos": set()}
    # No debe lanzar nada
    _check_self_or_admin(42, current_user)


def test_empleado_sin_permiso_no_puede_leer_feedback_ajeno():
    """Un empleado que pide el feedback de otro sin feedback.configurar debe recibir 403."""
    current_user = {"employeeId": 7, "permisos": set()}
    with pytest.raises(HTTPException) as exc_info:
        _check_self_or_admin(99, current_user)
    assert exc_info.value.status_code == 403
