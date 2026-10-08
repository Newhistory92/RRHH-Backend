"""
Persistencia de las horas de permiso ya consumidas antes del alta.

Lo que mas importa acá: que la lectura distinga "no hay fila" de "hay una fila
en cero". Son estados distintos -no haber mirado a un empleado, y haber
determinado que no uso ninguna hora- y confundirlos regala el cupo entero.
"""

from app.database.consumo_inicial_permisos import (
    agregar_asiento, asientos_de_empleado, borrar_asiento, total_de_empleado,
)
from app.permisos import DESCRIPCIONES, PERMISOS, PERMISOS_POR_ROL
from tests.fakes import FakeSession


def _db(filas):
    return FakeSession({"FROM ConsumoInicialPermiso": filas})


def test_sin_asientos_el_total_es_none_y_no_cero():
    """None deja que rija el cupo completo; 0 afirma que no uso ninguna."""
    assert total_de_empleado(_db([{"total": None}]), 8, 2026) is None


def test_asientos_que_suman_cero_devuelven_cero_y_no_none():
    assert total_de_empleado(_db([{"total": 0}]), 8, 2026) == 0.0


def test_el_total_es_la_suma_de_los_asientos():
    """Es el cambio que motiva esta tarea: 5 y despues 10 dan 15, no 10."""
    assert total_de_empleado(_db([{"total": 15.0}]), 8, 2026) == 15.0


def test_el_total_suma_en_sql_y_no_en_python():
    """
    Si sumara en Python, traeria todas las filas para descartarlas: el SUM
    tiene que estar en la consulta.
    """
    db = _db([{"total": 15.0}])
    total_de_empleado(db, 8, 2026)
    sql = db.sql_ejecutado()
    assert "SUM(horasConsumidas)" in sql
    assert "employeeId = :empId" in sql
    assert "anio = :anio" in sql


def test_los_asientos_se_listan_con_su_id_y_trazabilidad():
    """El id es lo que el panel necesita para poder borrar uno puntual."""
    filas = [
        {"id": 2, "horasConsumidas": 10.0, "cargadoPor": 3, "cargadoEn": None},
        {"id": 1, "horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None},
    ]
    asientos = asientos_de_empleado(_db(filas), 8, 2026)
    assert [a["id"] for a in asientos] == [2, 1]
    assert asientos[0]["horasConsumidas"] == 10.0
    assert asientos[0]["cargadoPor"] == 3


def test_agregar_un_asiento_inserta_y_no_pisa():
    """
    INSERT y no MERGE: la segunda carga del mismo (empleado, anio) es un
    asiento mas, legitimo, no una correccion de la primera.
    """
    db = FakeSession({})
    agregar_asiento(db, 8, 2026, 5.0, cargado_por=3)
    sql = db.sql_ejecutado()
    assert "INSERT INTO ConsumoInicialPermiso" in sql
    assert "MERGE" not in sql
    assert db.commits >= 1


def test_borrar_un_asiento_exige_que_sea_del_empleado():
    """
    Sin el filtro por employeeId, el id de la URL alcanzaria para borrarle
    un asiento a cualquier otra persona.
    """
    db = FakeSession({"DELETE FROM ConsumoInicialPermiso": [{"id": 1}]})
    assert borrar_asiento(db, 8, 1) is True
    sql, params = db.ejecutadas[0]
    assert "employeeId = :empId" in sql
    assert params == {"empId": 8, "asientoId": 1}


def test_borrar_un_asiento_que_no_es_del_empleado_devuelve_false():
    """rowcount 0: el DELETE no encontro nada que borrar."""
    db = FakeSession({"DELETE FROM ConsumoInicialPermiso": []})
    assert borrar_asiento(db, 8, 1) is False


# -- El permiso ----------------------------------------------------------------

def test_el_permiso_esta_en_el_catalogo_y_tiene_descripcion():
    assert "asistencia.cargaInicialPermisos" in PERMISOS
    assert DESCRIPCIONES["asistencia.cargaInicialPermisos"]


def test_el_permiso_no_se_siembra_en_ningun_rol():
    """
    Es transitorio: se otorga a mano desde la UI de roles y se revoca cuando
    termina la migracion. Sembrarlo lo volveria permanente de hecho.
    """
    for codigos in PERMISOS_POR_ROL.values():
        assert "asistencia.cargaInicialPermisos" not in codigos


# -- La tabla se crea sin depender del panel -----------------------------------

def test_asistencia_ensure_tables_crea_tambien_consumo_inicial_permiso():
    """
    recalcular_anio y mis_permisos leen ConsumoInicialPermiso siempre, no solo
    cuando alguien con el permiso transitorio abrio el panel de carga. Si
    ensure_tables del modulo de asistencia no la crea, el primer SELECT de
    esos dos caminos falla contra una base recien migrada.
    """
    import app.database.asistencia as asistencia_module

    asistencia_module._tablas_listas = False
    db = FakeSession({})
    asistencia_module.ensure_tables(db)
    assert "ConsumoInicialPermiso" in db.sql_ejecutado()
