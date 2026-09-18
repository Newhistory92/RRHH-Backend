"""
Capa de persistencia de bajas, con FakeSession.

Ninguna base real se toca: FakeSession mapea fragmentos de SQL a filas y
guarda lo que se intento ejecutar.
"""

from datetime import date

from app.database.bajas import (
    aplicar_efectos, bajas_de_empleado, bajas_para_tablero, borrar_baja,
    pendientes_de_aplicar, registrar_baja, reincorporar,
)
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_bajas_de_empleado_devuelve_las_filas_como_dicts():
    db = FakeSession({"FROM EmployeeBaja": [
        {"id": 1, "employeeId": 8, "motivo": "Renuncia",
         "fechaBaja": date(2026, 9, 1), "observaciones": None,
         "fechaReingreso": None, "registradaPor": 3,
         "createdAt": date(2026, 9, 1)},
    ]})
    filas = bajas_de_empleado(db, 8)
    assert len(filas) == 1
    assert filas[0]["motivo"] == "Renuncia"


def test_bajas_de_empleado_pasa_el_id_como_bind():
    db = FakeSession({"FROM EmployeeBaja": []})
    bajas_de_empleado(db, 8)
    _sql, params = db.ejecutadas[0]
    assert params == {"id": 8}


def test_registrar_una_baja_cumplida_aplica_los_efectos():
    db = FakeSession({"INSERT INTO EmployeeBaja": [(55,)]})
    resultado = registrar_baja(db, 8, "Renuncia", date(2026, 9, 1),
                               "Resolucion 120/26", 3, HOY)
    assert resultado["vigente"] is True
    sql = db.sql_ejecutado()
    assert "UPDATE Employee SET status" in sql
    assert "UPDATE License" in sql


def test_registrar_una_baja_futura_no_aplica_efectos_todavia():
    """Se guarda, pero la persona sigue operando hasta que llegue el dia."""
    db = FakeSession({"INSERT INTO EmployeeBaja": [(56,)]})
    resultado = registrar_baja(db, 8, "Renuncia", date(2026, 12, 1),
                               None, 3, HOY)
    assert resultado["vigente"] is False
    assert "UPDATE Employee SET status" not in db.sql_ejecutado()


def test_registrar_nunca_toca_user_activo():
    """El bloqueo de cuenta es del panel de ADMIN y no se mezcla con la baja."""
    db = FakeSession({"INSERT INTO EmployeeBaja": [(57,)]})
    registrar_baja(db, 8, "Despido", date(2026, 9, 1), None, 3, HOY)
    assert "[User]" not in db.sql_ejecutado()


def test_aplicar_efectos_cancela_las_pendientes_y_limpia_la_cola():
    """Sin el UPDATE de Aprobaciones la solicitud sigue en la cola del jefe."""
    db = FakeSession()
    aplicar_efectos(db, 8)
    sql = db.sql_ejecutado()
    assert "UPDATE License" in sql
    assert "'Rechazada'" in sql
    assert "UPDATE Aprobaciones" in sql


def test_aplicar_efectos_reasigna_sus_aprobaciones_pendientes_al_jefe():
    """Si el dado de baja era supervisor, su cola pasa a su propio superior."""
    db = FakeSession({
        "SELECT managerId FROM Employee": [{"managerId": 5}],
        "SET supervisorId = :jefe": [{"id": 1}, {"id": 2}],
    })
    resultado = aplicar_efectos(db, 8, HOY)
    assert resultado == {"reasignadas": 2, "sinReasignar": 0}
    params = next(p for sql, p in db.ejecutadas if "SET supervisorId = :jefe" in sql)
    assert params == {"jefe": 5, "id": 8}


def test_aplicar_efectos_sin_jefe_no_reasigna_y_cuenta_las_pendientes():
    db = FakeSession({
        "SELECT managerId FROM Employee": [{"managerId": None}],
        "SELECT COUNT(*) AS n FROM Aprobaciones": [{"n": 3}],
    })
    resultado = aplicar_efectos(db, 8, HOY)
    assert resultado == {"reasignadas": 0, "sinReasignar": 3}
    assert "SET supervisorId" not in db.sql_ejecutado()


def test_aplicar_efectos_no_reasigna_a_un_jefe_que_tambien_esta_de_baja():
    db = FakeSession({
        "SELECT managerId FROM Employee": [{"managerId": 5}],
        "FROM EmployeeBaja": [{"fechaBaja": date(2026, 1, 1), "fechaReingreso": None}],
        "SELECT COUNT(*) AS n FROM Aprobaciones": [{"n": 2}],
    })
    resultado = aplicar_efectos(db, 8, HOY)
    assert resultado == {"reasignadas": 0, "sinReasignar": 2}
    assert "SET supervisorId" not in db.sql_ejecutado()


def test_borrar_baja_devuelve_true_cuando_borro_algo_y_reactiva():
    db = FakeSession({"DELETE FROM EmployeeBaja": [{"id": 1}]})
    assert borrar_baja(db, 8) is True
    assert "UPDATE Employee SET status" in db.sql_ejecutado()


def test_borrar_baja_sin_fila_abierta_devuelve_false():
    db = FakeSession({"DELETE FROM EmployeeBaja": []})
    assert borrar_baja(db, 8) is False


def test_reincorporar_escribe_la_fecha_y_reactiva():
    db = FakeSession({"UPDATE EmployeeBaja": [{"id": 1}]})
    assert reincorporar(db, 8, date(2026, 10, 1)) is True
    sql = db.sql_ejecutado()
    assert "fechaReingreso" in sql
    assert "UPDATE Employee SET status" in sql


def _estado_escrito(db):
    return next(p["e"] for sql, p in db.ejecutadas
                if "UPDATE Employee SET status" in sql)


def test_corregir_deja_en_licencia_a_quien_tiene_una_aprobada_en_curso():
    """Mismo criterio que _sync_employee_status: no se pisa 'Licencia'."""
    db = FakeSession({"DELETE FROM EmployeeBaja": [{"id": 1}],
                      "status = 'Aprobada'": [{"id": 3}]})
    borrar_baja(db, 8)
    assert _estado_escrito(db) == "Licencia"


def test_reincorporar_deja_en_licencia_a_quien_tiene_una_aprobada_en_curso():
    db = FakeSession({"UPDATE EmployeeBaja": [{"id": 1}],
                      "status = 'Aprobada'": [{"id": 3}]})
    reincorporar(db, 8, date(2026, 10, 1))
    assert _estado_escrito(db) == "Licencia"


def test_reincorporar_sin_licencia_en_curso_deja_activo():
    db = FakeSession({"UPDATE EmployeeBaja": [{"id": 1}]})
    reincorporar(db, 8, date(2026, 10, 1))
    assert _estado_escrito(db) == "Activo"


def test_reincorporar_sin_baja_abierta_devuelve_false():
    db = FakeSession({"UPDATE EmployeeBaja": []})
    assert reincorporar(db, 8, date(2026, 10, 1)) is False


def test_el_tablero_clasifica_los_tres_estados():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "Vigente", "dni": "1", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Renuncia",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2026, 9, 1), "fechaReingreso": None,
         "saldoFinal": 0},
        {"id": 2, "employeeId": 9, "name": "Volvio", "dni": "2", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Renuncia",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2024, 9, 1), "fechaReingreso": date(2025, 1, 1),
         "saldoFinal": 0},
        {"id": 3, "employeeId": 10, "name": "Futura", "dni": "3", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Jubilación",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2026, 12, 1), "fechaReingreso": None,
         "saldoFinal": 0},
    ]})
    filas = bajas_para_tablero(db, HOY)
    assert [f["estado"] for f in filas] == ["vigente", "reincorporada", "programada"]


def test_el_tablero_calcula_la_antiguedad_al_irse():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "X", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 9, 1), "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None, "saldoFinal": 0},
    ]})
    assert bajas_para_tablero(db, HOY)[0]["antiguedadAnios"] == 10.0


def test_pendientes_de_aplicar_devuelve_los_ids():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"employeeId": 8}, {"employeeId": 9},
    ]})
    assert pendientes_de_aplicar(db, HOY) == [8, 9]


def test_pendientes_de_aplicar_no_saltea_a_quien_tiene_status_null():
    """e.status <> 'Baja' es NULL -no verdadero- con status NULL en SQL."""
    db = FakeSession({"FROM EmployeeBaja b": []})
    pendientes_de_aplicar(db, HOY)
    assert "e.status IS NULL OR e.status <> :baja" in db.sql_ejecutado()


def test_reasignar_aprobaciones_solo_filtra_pendiente_no_derivadas():
    """Las filas 'Pendiente Siguiente Aprobación' ya fueron aprobadas por el
    supervisor y derivadas al siguiente: no son trabajo pendiente para el
    supervisor dado de baja. Solo se reasignan las 'Pendiente'."""
    db = FakeSession({
        "SELECT managerId FROM Employee": [{"managerId": 5}],
        "SET supervisorId = :jefe": [{"id": 1}],
    })
    aplicar_efectos(db, 8, HOY)

    # Buscar el UPDATE que reasigna supervisores
    reasignacion_sql = next(sql for sql, _ in db.ejecutadas
                            if "SET supervisorId = :jefe" in sql)
    # Debe filtrar solo por 'Pendiente', no por ambos valores
    assert "accion = 'Pendiente'" in reasignacion_sql
    assert "'Pendiente Siguiente Aprobación'" not in reasignacion_sql
