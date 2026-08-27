"""
Tests de los endpoints PUT /departments/{dep_id}/score-exento
y PUT /departments/office/{office_id}/score-exento.

Los handlers se invocan directamente (sin servidor HTTP) siguiendo el patron
de tests existente en este proyecto. FakeSession simula la base de datos.
"""

import pytest
from fastapi import HTTPException

from app.routes.departments import (
    ScoreExentoRequest,
    update_department_score_exento,
    update_office_score_exento,
)
from tests.fakes import FakeSession


# ---------------------------------------------------------------------------
# Departamento — casos felices
# ---------------------------------------------------------------------------

def test_dep_score_exento_true_devuelve_success():
    db = FakeSession({"SELECT id FROM Department": [{"id": 1}]})
    result = update_department_score_exento(
        dep_id=1, payload=ScoreExentoRequest(exento=True), db=db
    )
    assert result == {"success": True, "exento": True}


def test_dep_score_exento_false_devuelve_success():
    db = FakeSession({"SELECT id FROM Department": [{"id": 1}]})
    result = update_department_score_exento(
        dep_id=1, payload=ScoreExentoRequest(exento=False), db=db
    )
    assert result == {"success": True, "exento": False}


def test_dep_score_exento_ejecuta_update_en_department_con_scoreExento():
    db = FakeSession({"SELECT id FROM Department": [{"id": 2}]})
    update_department_score_exento(
        dep_id=2, payload=ScoreExentoRequest(exento=True), db=db
    )
    sqls = [s for s, _ in db.ejecutadas]
    assert any(
        "UPDATE Department" in s and "scoreExento" in s for s in sqls
    ), "se esperaba un UPDATE Department ... scoreExento"


def test_dep_score_exento_pasa_el_valor_correcto_como_bind():
    db = FakeSession({"SELECT id FROM Department": [{"id": 3}]})
    update_department_score_exento(
        dep_id=3, payload=ScoreExentoRequest(exento=False), db=db
    )
    update_sqls = [
        (s, p) for s, p in db.ejecutadas if "UPDATE Department" in s
    ]
    assert update_sqls, "debe haber al menos un UPDATE Department"
    _sql, params = update_sqls[0]
    assert params.get("exento") is False


# ---------------------------------------------------------------------------
# Departamento — 404
# ---------------------------------------------------------------------------

def test_dep_score_exento_404_si_no_existe():
    db = FakeSession({"SELECT id FROM Department": []})
    with pytest.raises(HTTPException) as exc_info:
        update_department_score_exento(
            dep_id=99, payload=ScoreExentoRequest(exento=True), db=db
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Departamento — 400
# ---------------------------------------------------------------------------

def test_dep_score_exento_400_si_campo_ausente():
    db = FakeSession({})
    with pytest.raises(HTTPException) as exc_info:
        update_department_score_exento(
            dep_id=1, payload=ScoreExentoRequest(exento=None), db=db
        )
    assert exc_info.value.status_code == 400


def test_dep_score_exento_400_si_valor_no_es_bool():
    db = FakeSession({})
    with pytest.raises(HTTPException) as exc_info:
        update_department_score_exento(
            dep_id=1, payload=ScoreExentoRequest(exento="si"), db=db
        )
    assert exc_info.value.status_code == 400


def test_dep_score_exento_400_si_valor_es_entero():
    db = FakeSession({})
    with pytest.raises(HTTPException) as exc_info:
        update_department_score_exento(
            dep_id=1, payload=ScoreExentoRequest(exento=1), db=db
        )
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Oficina — casos felices
# ---------------------------------------------------------------------------

def test_office_score_exento_true_devuelve_success():
    db = FakeSession({"SELECT id FROM Office": [{"id": 5}]})
    result = update_office_score_exento(
        office_id=5, payload=ScoreExentoRequest(exento=True), db=db
    )
    assert result == {"success": True, "exento": True}


def test_office_score_exento_false_devuelve_success():
    db = FakeSession({"SELECT id FROM Office": [{"id": 5}]})
    result = update_office_score_exento(
        office_id=5, payload=ScoreExentoRequest(exento=False), db=db
    )
    assert result == {"success": True, "exento": False}


def test_office_score_exento_ejecuta_update_en_office_con_scoreExento():
    db = FakeSession({"SELECT id FROM Office": [{"id": 7}]})
    update_office_score_exento(
        office_id=7, payload=ScoreExentoRequest(exento=True), db=db
    )
    sqls = [s for s, _ in db.ejecutadas]
    assert any(
        "UPDATE Office" in s and "scoreExento" in s for s in sqls
    ), "se esperaba un UPDATE Office ... scoreExento"


def test_office_score_exento_pasa_el_valor_correcto_como_bind():
    db = FakeSession({"SELECT id FROM Office": [{"id": 8}]})
    update_office_score_exento(
        office_id=8, payload=ScoreExentoRequest(exento=False), db=db
    )
    update_sqls = [
        (s, p) for s, p in db.ejecutadas if "UPDATE Office" in s
    ]
    assert update_sqls
    _sql, params = update_sqls[0]
    assert params.get("exento") is False


# ---------------------------------------------------------------------------
# Oficina — 404
# ---------------------------------------------------------------------------

def test_office_score_exento_404_si_no_existe():
    db = FakeSession({"SELECT id FROM Office": []})
    with pytest.raises(HTTPException) as exc_info:
        update_office_score_exento(
            office_id=99, payload=ScoreExentoRequest(exento=True), db=db
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Oficina — 400
# ---------------------------------------------------------------------------

def test_office_score_exento_400_si_campo_ausente():
    db = FakeSession({})
    with pytest.raises(HTTPException) as exc_info:
        update_office_score_exento(
            office_id=5, payload=ScoreExentoRequest(exento=None), db=db
        )
    assert exc_info.value.status_code == 400


def test_office_score_exento_400_si_valor_no_es_bool():
    db = FakeSession({})
    with pytest.raises(HTTPException) as exc_info:
        update_office_score_exento(
            office_id=5, payload=ScoreExentoRequest(exento="no"), db=db
        )
    assert exc_info.value.status_code == 400
