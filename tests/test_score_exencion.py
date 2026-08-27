"""Tests de la marca de exencion de score, sin base real."""

from app.database.score_exencion import empleados_exentos
from tests.fakes import FakeSession


def test_devuelve_los_empleados_de_un_departamento_exento():
    db = FakeSession({"FROM Employee e": [{"id": 3}, {"id": 7}]})
    assert empleados_exentos(db) == {3, 7}


def test_sin_areas_exentas_devuelve_conjunto_vacio():
    db = FakeSession({"FROM Employee e": []})
    assert empleados_exentos(db) == set()


def test_la_consulta_mira_departamento_y_oficina():
    db = FakeSession({"FROM Employee e": []})
    empleados_exentos(db)
    sql, _ = db.ejecutadas[0]
    assert "scoreExento" in sql
    assert "Department" in sql
    assert "Office" in sql
