"""
Persistencia de las horas de permiso ya consumidas antes del alta.

Lo que mas importa acá: que la lectura distinga "no hay fila" de "hay una fila
en cero". Son estados distintos -no haber mirado a un empleado, y haber
determinado que no uso ninguna hora- y confundirlos regala el cupo entero.
"""

from app.database.consumo_inicial_permisos import (
    carga_de_empleado, consumo_de_empleado, upsert_consumo,
)
from app.permisos import DESCRIPCIONES, PERMISOS, PERMISOS_POR_ROL
from tests.fakes import FakeSession


def _db(filas):
    return FakeSession({"FROM ConsumoInicialPermiso": filas})


def test_sin_fila_el_consumo_es_none_y_no_cero():
    """None deja que rija el cupo completo; 0 afirma que no uso ninguna."""
    assert consumo_de_empleado(_db([]), 8, 2026) is None


def test_una_fila_en_cero_devuelve_cero_y_no_none():
    db = _db([{"horasConsumidas": 0, "cargadoPor": 3, "cargadoEn": None}])
    assert consumo_de_empleado(db, 8, 2026) == 0.0


def test_devuelve_las_horas_cargadas():
    db = _db([{"horasConsumidas": 5.5, "cargadoPor": 3, "cargadoEn": None}])
    assert consumo_de_empleado(db, 8, 2026) == 5.5


def test_la_lectura_filtra_por_empleado_y_anio():
    """Sin el filtro por anio, la carga de un anio descontaria en el otro."""
    db = _db([{"horasConsumidas": 5.0, "cargadoPor": None, "cargadoEn": None}])
    consumo_de_empleado(db, 8, 2026)
    sql, params = db.ejecutadas[0]
    assert "employeeId = :empId" in sql
    assert "anio = :anio" in sql
    assert params == {"empId": 8, "anio": 2026}


def test_carga_de_empleado_trae_la_trazabilidad():
    """El panel de RRHH muestra quien cargo y cuando."""
    db = _db([{"horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None}])
    fila = carga_de_empleado(db, 8, 2026)
    assert fila["horasConsumidas"] == 5.0
    assert fila["cargadoPor"] == 3


def test_el_upsert_corrige_en_vez_de_duplicar():
    """
    Corregir una carga equivocada es el caso normal, y la clave
    (employeeId, anio) es unica: un INSERT fallaria en el segundo intento.
    """
    db = FakeSession({})
    upsert_consumo(db, 8, 2026, 5.0, cargado_por=3)
    sql = db.sql_ejecutado()
    assert "MERGE ConsumoInicialPermiso" in sql
    # HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    # simultaneas de la misma clave entrando las dos por NOT MATCHED.
    assert "HOLDLOCK" in sql
    assert db.commits >= 1


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
