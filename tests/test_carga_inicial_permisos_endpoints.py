"""
Los dos endpoints de carga inicial de horas de permiso.

Se invocan las funciones directo con un FakeSession, que es el patron de la
suite: no hay TestClient porque las dependencias de FastAPI (auth y sesion) se
resuelven por inyeccion y aca se pasan a mano.
"""

import pytest
from fastapi import HTTPException

from app.routes import carga_inicial_permisos as m
from tests.fakes import FakeSession


def _db(carga=None, cupo=12.0):
    return FakeSession({
        "FROM ConsumoInicialPermiso": (
            [] if carga is None
            else [{"horasConsumidas": carga, "cargadoPor": 3,
                   "cargadoEn": None}]
        ),
        "FROM Employee e": [{"cupo": cupo}],
    })


# -- Validacion ----------------------------------------------------------------

@pytest.mark.parametrize("valor", [0, 5, 12.5, 2000])
def test_las_horas_razonables_pasan(valor):
    assert m._validar_horas(valor) == float(valor)


def test_rechaza_horas_negativas():
    with pytest.raises(HTTPException) as e:
        m._validar_horas(-1)
    assert e.value.status_code == 400


def test_rechaza_el_error_de_tipeo():
    """Mismo atajo que el cupo: 2000 h es mas que un anio laboral completo."""
    with pytest.raises(HTTPException) as e:
        m._validar_horas(2001)
    assert e.value.status_code == 400


def test_rechaza_lo_que_no_es_numero():
    with pytest.raises(HTTPException) as e:
        m._validar_horas("mucho")
    assert e.value.status_code == 400


def test_no_hay_tope_contra_el_cupo_del_empleado():
    """
    Alguien pudo haber usado mas horas de las que su cupo cubre, y eso tiene
    que poder cargarse: el banco queda en 0 y el resto del anio es deuda.
    """
    assert m._validar_horas(50) == 50.0


# -- GET -----------------------------------------------------------------------

def test_el_get_devuelve_null_cuando_no_hay_carga():
    """null y 0 son estados distintos y el panel los muestra distinto."""
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=None))
    assert r["horasConsumidas"] is None
    assert r["cupoAnual"] == 12.0


def test_el_get_devuelve_cero_cuando_la_carga_es_cero():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=0))
    assert r["horasConsumidas"] == 0.0


def test_el_get_trae_la_trazabilidad():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=5.0))
    assert r["horasConsumidas"] == 5.0
    assert r["cargadoPor"] == 3


# -- PUT -----------------------------------------------------------------------

def test_el_put_guarda_y_recalcula(monkeypatch):
    """
    El recalculo va sincrono: es un solo empleado, a diferencia del cambio de
    cupo de una jornada, que toca a toda su nomina.
    """
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db(carga=None)
    r = m.put_carga_inicial_permisos(
        8, {"horasConsumidas": 5}, user={"employeeId": 3}, db=db,
    )

    assert r["ok"] is True
    assert r["horasConsumidas"] == 5.0
    assert recalculos == [(8, r["anio"])]
    assert "MERGE ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_put_rechaza_un_valor_invalido_antes_de_escribir(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db(carga=None)
    with pytest.raises(HTTPException):
        m.put_carga_inicial_permisos(
            8, {"horasConsumidas": -1}, user={"employeeId": 3}, db=db,
        )
    assert "MERGE" not in db.sql_ejecutado()
