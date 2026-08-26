"""
Tests del bloqueo de "solicitud pendiente" en POST /licenses/request.

Regla de negocio: un empleado puede tener a lo sumo una solicitud
PENDIENTE por tipo de licencia. Una Vacaciones pendiente no debe
bloquear pedir un permiso de Matrimonio (tipo distinto); dos Vacaciones
pendientes si se bloquean entre si (mismo tipo).

Como FakeSession resuelve por coincidencia de substring del SQL (no
ejecuta SQL real ni filtra por parámetros), estos tests verifican dos
cosas complementarias para cada escenario:
  1. Que la consulta de bloqueo efectivamente se arma con `type = :type`
     y el parámetro `type` correcto (contrato con la base real).
  2. Que el resultado que la base devolvería para ese filtro (simulado
     via FakeSession) produce el comportamiento esperado en la ruta:
     bloquea con 400 nombrando el tipo, o deja continuar la solicitud.
"""
import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession


EMPLOYEE_ID = 42

CURRENT_USER = {
    "employeeId": EMPLOYEE_ID,
    "permisos": set(),
}

EMP_ROW = {
    "gender": "Femenino",
    "employee_name": "Ana Test",
    "tipoContrato": "Planta Permanente",
    "fechaIngreso": None,
    "roleName": "Empleado",
}


def _data(tipo: str) -> dict:
    return {
        "employeeId": EMPLOYEE_ID,
        "type": tipo,
        "startDate": "2026-01-10T00:00:00",
        "endDate": "2026-01-15T00:00:00",
        "duration": 5,
    }


def test_dos_solicitudes_del_mismo_tipo_se_bloquean():
    """Ya hay una Vacaciones pendiente -> pedir otra Vacaciones bloquea con 400."""
    from app.routes.licenses import create_license_request

    db = FakeSession({
        "SELECT id FROM License": [{"id": 999}],  # simula: la DB encontró una pendiente del mismo tipo
        "FROM Employee e": [EMP_ROW],
    })

    with pytest.raises(HTTPException) as exc:
        create_license_request(_data("Vacaciones"), db, CURRENT_USER)

    assert exc.value.status_code == 400
    assert "Vacaciones" in exc.value.detail
    assert "pendiente" in exc.value.detail

    # La consulta de bloqueo debe filtrar por tipo, no solo por empleado.
    sql_bloqueo, params_bloqueo = db.ejecutadas[0]
    assert "type = :type" in sql_bloqueo
    assert params_bloqueo["type"] == "Vacaciones"
    assert params_bloqueo["empId"] == EMPLOYEE_ID

    # No debe haber llegado a insertar nada.
    assert "INSERT INTO License" not in db.sql_ejecutado()


def test_vacaciones_pendiente_no_bloquea_matrimonio():
    """Una Vacaciones pendiente no debe impedir pedir un permiso de Matrimonio."""
    from app.routes.licenses import create_license_request

    db = FakeSession({
        # La consulta ahora filtra por type = :type -> para "Matrimonio" la
        # DB real no devolvería la Vacaciones pendiente. Lo simulamos
        # devolviendo vacío para la consulta de bloqueo.
        "SELECT id FROM License": [],
        "FROM Employee e": [EMP_ROW],
        "INSERT INTO License": [(101,)],
    })

    resultado = create_license_request(_data("Matrimonio"), db, CURRENT_USER)

    assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}

    # Confirmamos que el filtro de bloqueo se armó con el tipo correcto
    # (Matrimonio), evidencia de que la consulta ya no es "cualquier tipo".
    sql_bloqueo, params_bloqueo = db.ejecutadas[0]
    assert "type = :type" in sql_bloqueo
    assert params_bloqueo["type"] == "Matrimonio"
