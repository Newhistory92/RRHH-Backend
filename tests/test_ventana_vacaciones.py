"""
La ventana Oct-Abr de vacaciones.

La validacion ya existia, pero su HTTPException caia dentro de un
`except Exception: pass` que se la tragaba. El test va contra el endpoint
porque a nivel de funcion interna el defecto no se veia.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession


EMPLOYEE_ID = 8

CURRENT_USER = {
    "employeeId": EMPLOYEE_ID,
    "permisos": set(),
}

RRHH_USER = {
    "employeeId": 99,
    "permisos": {"licencias.configurar"},
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


DISPONIBLES_VACACIONES = {"tipos": [{"nombre": "Vacaciones", "diasTotales": 10,
                                      "consumidos": 0, "disponibles": 10}]}


def test_carga_manual_de_rrhh_no_respeta_la_ventana():
    """RRHH puede registrar vacaciones ya tomadas (o acordadas) fuera de la
    ventana Oct-Abr -- esa ventana existe para el autogestionado del
    empleado, no para la carga manual. El saldo (test de abajo) sigue
    limitando de todas formas."""
    db = FakeSession({
        "SELECT id FROM License": [],
        "FROM Employee e": [EMP_ROW],
        "INSERT INTO License": [(101,)],
    })

    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_VACACIONES):
        resultado = create_license_request(
            data=_payload("2026-06-15T00:00:00"),
            db=db,
            current_user=RRHH_USER,
        )
    assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}


def test_carga_manual_de_rrhh_sin_ventana_igual_respeta_el_saldo():
    """Sin ventana no significa sin limite: RRHH tampoco puede cargar mas
    dias de vacaciones de los que el empleado realmente tiene."""
    db = FakeSession({
        "SELECT id FROM License": [],
        "FROM Employee e": [EMP_ROW],
    })

    payload = _payload("2026-06-15T00:00:00")
    payload["duration"] = 20

    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_VACACIONES):
        with pytest.raises(HTTPException) as e:
            create_license_request(data=payload, db=db, current_user=RRHH_USER)
    assert e.value.status_code == 400
    assert "10" in str(e.value.detail)
