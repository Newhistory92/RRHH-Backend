"""
Prueba end-to-end de que el corte del 1 de octubre gobierna de verdad lo
que create_license_request aprueba, sin mockear tipos_disponibles_de.

Todos los tests de test_validacion_saldo.py parchean
app.routes.licenses.tipos_disponibles_de directamente, asi que nada corre la
integracion real entre la validacion de saldo (Tarea 6) y el corte de ciclo
(Tarea 1/4). Este archivo arma un FakeSession lo bastante realista como para
que tipos_disponibles_de corra su consulta real dentro de create_license_request.

El ciclo que rige una solicitud de vacaciones sale de la fecha de inicio DE
ESA SOLICITUD, no de la fecha en la que se hace el pedido -- reservar hoy
unas vacaciones para dentro de unos meses tiene que medirse contra el ciclo
al que esas vacaciones van a pertenecer, no contra el ciclo de hoy. Por eso
estos tests varian startDate y no "hoy": es la fecha de inicio la que decide.
"""

from datetime import date
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession

EMP_QUERY_REQUEST = "INNER JOIN CondicionLaboral cl ON e.id = cl.employeeId"
EMP_QUERY_TIPOS = "LEFT JOIN CondicionLaboral cl ON e.id = cl.employeeId"
CONFIG_QUERY = "FROM ConfiguracionLicencias c"
SALDO_INICIAL = "FROM SaldoInicialLicencia"
PENDIENTE_QUERY = "SELECT id FROM License"


def _payload(dias: int, start_iso: str, end_iso: str) -> dict:
    return {
        "type": "Vacaciones",
        "startDate": start_iso,
        "endDate": end_iso,
        "duration": dias,
        "employeeId": 8,
        "mensajeOriginal": "test",
    }


def _db(saldos_iniciales: list[dict]) -> FakeSession:
    return FakeSession({
        PENDIENTE_QUERY: [],
        EMP_QUERY_REQUEST: [{
            "gender": "Masculino", "employee_name": "Test",
            "tipoContrato": "permanente", "fechaIngreso": None,
            "roleName": "user",
        }],
        EMP_QUERY_TIPOS: [{
            "tipoContrato": "permanente", "fechaIngreso": None,
            "fechaJubilacion": None, "gender": "Masculino",
            "roleName": "user",
        }],
        CONFIG_QUERY: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL: saldos_iniciales,
        "INSERT INTO License": [(101,)],
    })


# Saldo inicial cargado para el ciclo 2025 (Feb 2026 todavia le pertenece,
# porque el ciclo 2025 corre de octubre 2025 a septiembre 2026) y para el
# ciclo 2026 (empieza en octubre 2026), bien distintos entre si para que el
# test no pueda pasar por casualidad si el codigo mezcla los dos anios.
SALDOS = [
    {"anio": 2025, "categoria": "Vacaciones", "diasPendientes": 5},
    {"anio": 2026, "categoria": "Vacaciones", "diasPendientes": 20},
]


def test_una_solicitud_de_febrero_rige_contra_el_ciclo_anterior():
    """Febrero 2026 cae dentro del ciclo 2025 (que corre de oct-2025 a
    sep-2026): tiene que medirse contra sus 5 dias, no contra los 20 del
    ciclo 2026."""
    # Justo el limite del ciclo 2025 (5 dias): entra.
    resultado = create_license_request(
        data=_payload(5, "2026-02-10T00:00:00", "2026-02-15T00:00:00"),
        db=_db(SALDOS),
        current_user={"employeeId": 8, "permisos": set()},
    )
    assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}

    # Un dia mas de lo que el ciclo 2025 tiene: no entra, aunque el ciclo
    # 2026 si tendria de sobra -- la prueba de que rige el ciclo al que la
    # fecha pedida pertenece, y no otro.
    with pytest.raises(HTTPException) as e:
        create_license_request(
            data=_payload(6, "2026-02-10T00:00:00", "2026-02-16T00:00:00"),
            db=_db(SALDOS),
            current_user={"employeeId": 8, "permisos": set()},
        )
    assert e.value.status_code == 400
    assert "5" in str(e.value.detail)


def test_una_solicitud_de_noviembre_rige_contra_el_ciclo_nuevo():
    """Noviembre 2026 ya pertenece al ciclo 2026: el mismo pedido de 6 dias
    que el test anterior rechazaba contra el ciclo 2025 entra aca, porque la
    fecha pedida cae en el ciclo con 20 dias disponibles."""
    resultado = create_license_request(
        data=_payload(6, "2026-11-10T00:00:00", "2026-11-16T00:00:00"),
        db=_db(SALDOS),
        current_user={"employeeId": 8, "permisos": set()},
    )
    assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}


def test_reservar_con_anticipacion_no_deja_gastar_el_ciclo_equivocado():
    """El caso que motivo el fix: hoy es septiembre de 2026 (ciclo vigente
    2025), pero se reserva vacaciones para noviembre (ciclo 2026). Antes del
    fix la validacion media contra el ciclo de HOY (2025, 5 dias) en vez del
    ciclo al que la solicitud realmente pertenece (2026, 20 dias) -- un
    pedido de 20 dias para noviembre se hubiera rechazado por error."""
    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 15)

        resultado = create_license_request(
            data=_payload(20, "2026-11-10T00:00:00", "2026-11-30T00:00:00"),
            db=_db(SALDOS),
            current_user={"employeeId": 8, "permisos": set()},
        )
        assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}
