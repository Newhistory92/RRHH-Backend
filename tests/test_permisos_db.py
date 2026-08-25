"""
Tests de la capa de persistencia de permisos, con FakeSession.

Ninguna base real se toca: FakeSession mapea fragmentos de SQL a filas.
"""

from app.database.permissions import permisos_de_rol
from tests.fakes import FakeSession


def test_permisos_de_rol_devuelve_los_codigos_de_la_base():
    db = FakeSession({
        "FROM RolePermission": [
            {"code": "estadisticas.ver"},
            {"code": "inicio.ver"},
        ],
    })
    assert permisos_de_rol(db, 4) == {"estadisticas.ver", "inicio.ver"}


def test_permisos_de_rol_sin_filas_devuelve_conjunto_vacio():
    db = FakeSession({"FROM RolePermission": []})
    assert permisos_de_rol(db, 99) == set()


def test_permisos_de_rol_sin_role_id_no_consulta_la_base():
    db = FakeSession({"FROM RolePermission": [{"code": "inicio.ver"}]})
    assert permisos_de_rol(db, None) == set()
    assert db.ejecutadas == [], "no deberia haber consultado con role_id None"


def test_permisos_de_rol_pasa_el_role_id_como_bind():
    db = FakeSession({"FROM RolePermission": [{"code": "inicio.ver"}]})
    permisos_de_rol(db, 3)
    _sql, params = db.ejecutadas[0]
    assert params == {"roleId": 3}
