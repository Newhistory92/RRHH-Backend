"""
Los endpoints de baja, llamados directo con FakeSession.

No se levanta TestClient: las dependencias de permiso se declaran en el
decorador y no corren cuando se invoca la funcion a mano, que es justo lo que
permite testear la logica del endpoint sin token.
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.routes.rrhh import delete_baja, get_bajas, post_baja, put_reincorporacion
from tests.fakes import FakeSession

USUARIO_RRHH = {"employeeId": 3, "permisos": {"rrhh.gestionar"}}


def _db(extra=None):
    """Empleado existente, no ADMIN, sin bajas previas.

    Los overrides van primero: FakeSession devuelve la primera clave que
    aparezca en el SQL, y la consulta de otros ADMIN contiene un subquery
    FROM EmployeeBaja que si no le ganaria a su fragmento especifico."""
    base = {
        "SELECT id FROM Employee": [{"id": 8}],
        "FROM EmployeeBaja": [],
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 0}],
        "INSERT INTO EmployeeBaja": [(55,)],
    }
    respuestas = dict(extra or {})
    for clave, filas in base.items():
        respuestas.setdefault(clave, filas)
    return FakeSession(respuestas)


def test_registra_la_baja_y_devuelve_el_motivo_y_la_fecha():
    resultado = post_baja(
        8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01",
            "observaciones": "Resolución 120/26"},
        db=_db(), user=USUARIO_RRHH,
    )
    assert resultado["motivo"] == "Renuncia"
    assert resultado["fechaBaja"] == "2026-09-01"
    assert resultado["vigente"] is True


def test_la_respuesta_informa_las_aprobaciones_que_no_se_pudieron_reasignar():
    """El modal avisa cuantas quedaron trabadas si el dado de baja no tiene jefe."""
    db = _db({
        "SELECT managerId FROM Employee": [{"managerId": None}],
        "SELECT COUNT(*) AS n FROM Aprobaciones": [{"n": 4}],
    })
    resultado = post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                          db=db, user=USUARIO_RRHH)
    assert resultado["aprobacionesReasignadas"] == 0
    assert resultado["aprobacionesSinReasignar"] == 4


def test_rechaza_un_motivo_fuera_del_catalogo():
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Se fue nomás", "fechaBaja": "2026-09-01"},
                  db=_db(), user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "motivo" in str(e.value.detail).lower()


def test_rechaza_una_fecha_mal_formada():
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "01/09/2026"},
                  db=_db(), user=USUARIO_RRHH)
    assert e.value.status_code == 400


def test_rechaza_si_el_empleado_no_existe():
    db = _db({"SELECT id FROM Employee": []})
    with pytest.raises(HTTPException) as e:
        post_baja(99, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 404


def test_rechaza_una_segunda_baja_abierta():
    db = _db({"FROM EmployeeBaja": [
        {"motivo": "Renuncia", "fechaBaja": date(2026, 1, 1), "fechaReingreso": None},
    ]})
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "vigente" in str(e.value.detail)


def test_rechaza_otra_baja_si_hay_una_programada_abierta():
    """Una sola baja abierta por persona: la programada tambien cuenta."""
    db = _db({"FROM EmployeeBaja": [
        {"motivo": "Renuncia", "fechaBaja": date(2999, 1, 1), "fechaReingreso": None},
    ]})
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Despido", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "programada" in str(e.value.detail)
    assert "INSERT INTO EmployeeBaja" not in db.sql_ejecutado()


def test_rechaza_la_baja_del_ultimo_admin():
    """Sin esto quedaria un sistema sin nadie que pueda administrarlo ni
    revertir la baja, y habria que arreglarlo a mano en la base."""
    db = _db({
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 1}],
        "u.employeeId <> :id": [{"n": 0}],
    })
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "ADMIN" in str(e.value.detail)


def test_permite_la_baja_de_un_admin_si_queda_otro():
    db = _db({
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 1}],
        "u.employeeId <> :id": [{"n": 2}],
    })
    resultado = post_baja(8, {"motivo": "Jubilación", "fechaBaja": "2026-09-01"},
                          db=db, user=USUARIO_RRHH)
    assert resultado["vigente"] is True


def test_la_baja_registra_quien_la_cargo_desde_el_token():
    """La firma tiene que ser de quien la hizo, no de lo que diga el payload."""
    db = _db()
    post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01",
                  "registradaPor": 999},
              db=db, user=USUARIO_RRHH)
    insert = next(p for sql, p in db.ejecutadas if "INSERT INTO EmployeeBaja" in sql)
    assert insert["por"] == 3


def test_borrar_sin_baja_abierta_da_404():
    db = FakeSession({"DELETE FROM EmployeeBaja": []})
    with pytest.raises(HTTPException) as e:
        delete_baja(8, db=db)
    assert e.value.status_code == 404


def test_reincorporar_rechaza_una_fecha_anterior_a_la_baja():
    db = FakeSession({"FROM EmployeeBaja": [
        {"fechaBaja": date(2026, 9, 1), "fechaReingreso": None},
    ]})
    with pytest.raises(HTTPException) as e:
        put_reincorporacion(8, {"fechaReingreso": "2026-08-01"}, db=db)
    assert e.value.status_code == 400


def test_reincorporar_sin_baja_abierta_da_404():
    db = FakeSession({"FROM EmployeeBaja": []})
    with pytest.raises(HTTPException) as e:
        put_reincorporacion(8, {"fechaReingreso": "2026-10-01"}, db=db)
    assert e.value.status_code == 404


def test_el_tablero_devuelve_las_bajas_el_conteo_y_el_catalogo():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "A", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 1, 1), "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None, "saldoFinal": 0},
        {"id": 2, "employeeId": 9, "name": "B", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 1, 1), "fechaBaja": date(2026, 12, 1),
         "fechaReingreso": None, "saldoFinal": 0},
    ]})
    resultado = get_bajas(db=db)
    assert len(resultado["bajas"]) == 2
    assert resultado["motivos"][0] == "Jubilación"
    # La programada no se cuenta: todavia puede cancelarse.
    assert resultado["porMotivo"]["Renuncia"] == 1


def test_el_conteo_por_motivo_arranca_en_cero_para_todos_los_motivos():
    db = FakeSession({"FROM EmployeeBaja b": []})
    resultado = get_bajas(db=db)
    assert resultado["porMotivo"] == {
        "Jubilación": 0, "Renuncia": 0, "Despido": 0, "Fin de contrato": 0,
        "Fallecimiento": 0, "Traslado a otro organismo": 0,
        "Abandono de cargo": 0,
    }
