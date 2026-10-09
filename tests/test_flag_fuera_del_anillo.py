"""
El flag que marca a quien vive fuera del anillo de Circunvalacion.

Lo que mas importa aca es el guard: PUT /employee/{id} deja que el propio
empleado edite su legajo, y este campo otorga un beneficio. Sin el guard,
cualquiera se auto-tilda y se gana la tolerancia extendida.
"""

import pytest
from fastapi import HTTPException

from app.routes import employee as m
from tests.fakes import FakeSession


def _db():
    return FakeSession({"SELECT id FROM Employee": [{"id": 8}]})


def _usuario(employee_id, permisos):
    return {"employeeId": employee_id, "permisos": set(permisos)}


def test_rrhh_puede_tildar_el_flag(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    m.update_employee(
        8, {"fueraAnilloCircunvalacion": True}, db=db,
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    assert "fueraAnilloCircunvalacion" in db.sql_ejecutado()


def test_el_propio_empleado_no_puede_tildarse_el_flag(monkeypatch):
    """
    Sin esto el campo seria autoservicio: el empleado se marca solo y se
    gana la tolerancia extendida que RRHH otorga.
    """
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    with pytest.raises(HTTPException) as e:
        m.update_employee(
            8, {"fueraAnilloCircunvalacion": True}, db=db,
            current_user=_usuario(8, ["perfil.editar"]),
        )
    assert e.value.status_code == 403
    assert "fueraAnilloCircunvalacion" not in db.sql_ejecutado()


def test_el_empleado_sigue_pudiendo_editar_sus_otros_datos(monkeypatch):
    """El guard es solo para este campo, no cierra la edicion del legajo."""
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    m.update_employee(
        8, {"phone": "351-1234567"}, db=db,
        current_user=_usuario(8, ["perfil.editar"]),
    )
    assert "phone" in db.sql_ejecutado()


def test_cambiar_el_flag_recalcula_el_anio_del_empleado(monkeypatch):
    """
    Tildar a alguien despues de un dia con extension deja sus dias ya
    calculados sin el beneficio; destildarlo lo deja aplicado en dias ya
    liquidados. En los dos casos hay que recalcular.
    """
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    m.update_employee(
        8, {"fueraAnilloCircunvalacion": False}, db=_db(),
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    from datetime import date
    assert recalculos == [(8, date.today().year)]


def test_un_put_sin_el_flag_no_recalcula(monkeypatch):
    """Cambiar el telefono no tiene por que recomputar el anio."""
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    m.update_employee(
        8, {"phone": "351-1234567"}, db=_db(),
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    assert recalculos == []
