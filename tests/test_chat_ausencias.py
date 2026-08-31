"""
_ausencias_recientes: regresion de columna y filtro por empleado.

La tabla Ausencia la crea prisma/schema.prisma (frontend), no este backend;
su columna es "reason". Antes del primer fix, la herramienta ausencias_recientes
del chatbot fallaba en cada llamada con "Invalid column name 'motivo'", que el
chat reportaba como "hubo un error" generico.

Ademas, "ausencias de Emiliano Rojo" no se podia responder: la herramienta
solo devolvia la lista completa de todos los empleados. Ahora acepta un
nombre opcional que la filtra a un empleado, resuelto con el mismo patron
ambiguo-seguro que documentos_empleado y estadisticas_tardanzas.
"""

from tests.fakes import FakeSession

from app.routes import chat as c

FRAG_EMPLEADO_LIKE = "FROM Employee WHERE name LIKE"
FRAG_AUSENCIAS = "FROM Ausencia a"


def test_la_consulta_usa_reason_y_no_motivo():
    db = FakeSession({FRAG_AUSENCIAS: []})
    c._ausencias_recientes(db)
    sql = db.sql_ejecutado()
    assert "a.reason AS motivo" in sql
    assert "a.motivo" not in sql


def test_devuelve_las_filas_con_clave_motivo_en_castellano():
    db = FakeSession({
        FRAG_AUSENCIAS: [
            {"name": "Emiliano Rojo", "fecha": "2026-08-20", "motivo": "Turno medico"},
        ]
    })
    r = c._ausencias_recientes(db)
    assert r[0]["motivo"] == "Turno medico"


# -- Filtro por empleado -------------------------------------------------------

def test_sin_nombre_no_filtra_por_empleado():
    db = FakeSession({FRAG_AUSENCIAS: []})
    c._ausencias_recientes(db)
    sql = db.sql_ejecutado()
    assert "a.employeeId = :emp" not in sql
    assert FRAG_EMPLEADO_LIKE not in sql


def test_con_nombre_filtra_por_el_empleado_resuelto():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_AUSENCIAS: [
            {"name": "Emiliano Rojo", "fecha": "2026-08-20", "motivo": "Turno medico"},
        ],
    })
    r = c._ausencias_recientes(db, nombre="Emiliano Rojo")
    assert r[0]["motivo"] == "Turno medico"
    sql = db.sql_ejecutado()
    assert "a.employeeId = :emp" in sql


def test_nombre_ambiguo_no_elige_por_su_cuenta():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [
            {"id": 13, "name": "Emiliano Rojo"},
            {"id": 21, "name": "Emiliano Rojas"},
        ],
    })
    r = c._ausencias_recientes(db, nombre="Emiliano Ro")
    assert r["ambiguo"] is True
    assert FRAG_AUSENCIAS not in db.sql_ejecutado()


def test_ejecutar_tool_pasa_el_nombre_al_dispatcher():
    db = FakeSession({
        FRAG_EMPLEADO_LIKE: [{"id": 13, "name": "Emiliano Rojo"}],
        FRAG_AUSENCIAS: [],
    })
    r = c.ejecutar_tool(
        "ausencias_recientes", {"nombre": "Emiliano Rojo", "dias": 30}, db,
    )
    assert r == []
