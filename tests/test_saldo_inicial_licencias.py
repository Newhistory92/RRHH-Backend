"""
Tests de la capa de datos de SaldoInicialLicencia.

FakeSession no ejecuta SQL: verifica que se emitan las sentencias correctas
con los binds correctos, y que las funciones traduzcan bien las filas.
"""

from app.database.saldo_inicial_licencias import (
    ensure_table,
    saldos_de_empleado,
    upsert_saldos,
)
from tests.fakes import FakeSession


def test_ensure_table_crea_tabla_en_rrhh_no_en_obrasocial():
    """El saldo inicial vive en RRHH: ObraSocial es de solo lectura."""
    db = FakeSession()
    ensure_table(db)
    sql = db.sql_ejecutado()
    assert "SaldoInicialLicencia" in sql
    assert "ObraSocial" not in sql


def test_ensure_table_es_repetible():
    """Se llama en cada request de la carga; no puede fallar la segunda vez."""
    db = FakeSession()
    ensure_table(db)
    assert "IF OBJECT_ID" in db.sql_ejecutado()


def test_saldos_de_empleado_mapea_por_anio_y_categoria():
    db = FakeSession({"FROM SaldoInicialLicencia": [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
        {"anio": 2026, "categoria": "Particular", "diasPendientes": 0},
    ]})
    assert saldos_de_empleado(db, 8) == {
        (2024, "Vacaciones"): 5,
        (2026, "Particular"): 0,
    }


def test_saldos_de_empleado_filtra_por_empleado():
    """Sin este bind, un empleado veria el saldo cargado de otro."""
    db = FakeSession()
    saldos_de_empleado(db, 8)
    _sql, params = db.ejecutadas[-1]
    assert params["empId"] == 8


def test_saldos_de_empleado_conserva_el_cero():
    """Cero es 'no le queda nada', un dato cargado a proposito. Si se
    perdiera, la fila volveria a leerse como 'no se cargo nada' y el sistema
    le otorgaria los dias completos."""
    db = FakeSession({"FROM SaldoInicialLicencia": [
        {"anio": 2026, "categoria": "Particular", "diasPendientes": 0},
    ]})
    assert saldos_de_empleado(db, 8) == {(2026, "Particular"): 0}


def test_upsert_guarda_dias_y_quien_cargo():
    db = FakeSession()
    upsert_saldos(db, 8, [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
    ], cargado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["empId"] == 8
    assert params[0]["anio"] == 2024
    assert params[0]["categoria"] == "Vacaciones"
    assert params[0]["diasPendientes"] == 5
    assert params[0]["cargadoPor"] == 7


def test_upsert_usa_merge_con_holdlock():
    """Sin HOLDLOCK, dos cargas concurrentes de la misma clave pueden entrar
    las dos por la rama NOT MATCHED y violar la unica."""
    db = FakeSession()
    upsert_saldos(db, 8, [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
    ], cargado_por=7)
    sql = db.sql_ejecutado()
    assert "MERGE" in sql
    assert "HOLDLOCK" in sql


def test_upsert_con_lista_vacia_no_toca_la_base():
    db = FakeSession()
    assert upsert_saldos(db, 8, [], cargado_por=7) == 0
    assert db.ejecutadas == []
    assert db.commits == 0
