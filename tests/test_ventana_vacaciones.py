"""
La ventana Oct-Abr de vacaciones.

La validacion ya existia, pero su HTTPException caia dentro de un
`except Exception: pass` que se la tragaba. El test va contra el endpoint
porque a nivel de funcion interna el defecto no se veia.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession


EMPLOYEE_ID = 8

CURRENT_USER = {
    "employeeId": EMPLOYEE_ID,
    "permisos": set(),
}

EMP_ROW = {
    "gender": "Masculino",
    "employee_name": "Test",
    "tipoContrato": "permanente",
    "fechaIngreso": None,
    "roleName": "user",
}


def _payload(start: str, tipo: str = "Vacaciones") -> dict:
    return {
        "type": tipo,
        "startDate": start,
        "endDate": start,
        "duration": 1,
        "employeeId": EMPLOYEE_ID,
        "supervisorId": 3,
        "mensajeOriginal": "test",
    }


def test_vacaciones_en_junio_se_rechazan():
    """Junio esta fuera de la ventana Oct-Abr."""
    db = FakeSession({
        "SELECT id FROM License": [],  # no pending license
        "FROM Employee e": [EMP_ROW],  # valid employee
    })

    with pytest.raises(HTTPException) as e:
        create_license_request(
            data=_payload("2026-06-15T00:00:00"),
            db=db,
            current_user=CURRENT_USER,
        )
    assert e.value.status_code == 400
    assert "Octubre" in str(e.value.detail)
