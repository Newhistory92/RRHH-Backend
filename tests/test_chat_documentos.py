"""
documentos_empleado ahora resuelve por nombre, no solo por ID numerico. Antes
el usuario tenia que conocer el ID del legajo para preguntar "que
documentacion tiene cargada Fulano" -en la practica, nadie lo sabe de memoria.
"""

from tests.fakes import FakeSession

from app.routes import chat as c

FRAG_EMPLEADO_LIKE = "FROM Employee WHERE name LIKE"
FRAG_EMPLEADO_ID = "FROM Employee WHERE id = :id"
FRAG_DOCS = "FROM EmployeeDocument"


def test_busca_por_nombre_cuando_no_hay_id():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_DOCS: [{"tipo": "DNI", "descripcion": "Copia DNI",
                     "fileName": "dni.pdf", "createdAt": "2026-01-01"}],
    })
    r = c._documentos_empleado(db, nombre="Emiliano Rojo")
    assert r["empleado"]["id"] == 13
    assert len(r["documentos"]) == 1


def test_nombre_ambiguo_no_elige_por_su_cuenta():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [
            {"id": 13, "name": "Emiliano Rojo"},
            {"id": 21, "name": "Emiliano Rojas"},
        ],
    })
    r = c._documentos_empleado(db, nombre="Emiliano Ro")
    assert r["ambiguo"] is True
    assert FRAG_DOCS not in db.sql_ejecutado()


def test_id_directo_sigue_funcionando():
    db = FakeSession({
        FRAG_EMPLEADO_ID: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_DOCS: [],
    })
    r = c._documentos_empleado(db, empleado_id=13)
    assert r["empleado"]["id"] == 13
    assert FRAG_EMPLEADO_LIKE not in db.sql_ejecutado()


def test_sin_nombre_ni_id_devuelve_error_claro():
    r = c._documentos_empleado(FakeSession({}))
    assert "error" in r


def test_ejecutar_tool_pasa_el_nombre_al_dispatcher():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_DOCS: [],
    })
    r = c.ejecutar_tool("documentos_empleado", {"nombre": "Emiliano Rojo"}, db)
    assert r["empleado"]["id"] == 13
