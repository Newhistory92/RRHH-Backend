"""
Prueba end-to-end de que el corte del 1 de octubre gobierna de verdad lo
que create_license_request aprueba, sin mockear tipos_disponibles_de.

Todos los tests de test_validacion_saldo.py parchean
app.routes.licenses.tipos_disponibles_de directamente, asi que nada corre la
integracion real entre la validacion de saldo (Tarea 6) y el corte de ciclo
(Tarea 1/4). Este test arma un FakeSession lo bastante realista como para que
tipos_disponibles_de corra su consulta real dentro de create_license_request,
y prueba el mismo pedido dos veces: el 30 de septiembre (rige el ciclo
anterior) y el 1 de octubre (rige el ciclo nuevo), con saldos iniciales
distintos para cada ciclo.
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


def _payload(dias: int) -> dict:
    return {
        "type": "Vacaciones",
        # Dentro de la ventana Oct-Abr en ambos escenarios, para que el
        # chequeo D (ventana Oct-Abr) no interfiera con lo que este test
        # quiere probar.
        "startDate": "2026-11-10T00:00:00",
        "endDate": "2026-11-20T00:00:00",
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


# Saldo inicial cargado para el ciclo 2025 (rige hasta el 30 de septiembre de
# 2026) y para el ciclo 2026 (rige desde el 1 de octubre), bien distintos
# entre si para que el test no pueda pasar por casualidad si el codigo mezcla
# los dos anios.
SALDOS = [
    {"anio": 2025, "categoria": "Vacaciones", "diasPendientes": 5},
    {"anio": 2026, "categoria": "Vacaciones", "diasPendientes": 20},
]


def test_antes_del_corte_rige_el_saldo_del_ciclo_anterior():
    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 30)

        # Justo el limite del ciclo anterior (5 dias): entra.
        resultado = create_license_request(
            data=_payload(5), db=_db(SALDOS),
            current_user={"employeeId": 8, "permisos": set()},
        )
        assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}

        # Un dia mas de lo que el ciclo anterior tiene: no entra, aunque el
        # ciclo nuevo (2026) si tendria de sobra -- la prueba de que rige el
        # anterior y no se cuela el otro.
        with pytest.raises(HTTPException) as e:
            create_license_request(
                data=_payload(6), db=_db(SALDOS),
                current_user={"employeeId": 8, "permisos": set()},
            )
        assert e.value.status_code == 400
        assert "5" in str(e.value.detail)


def test_desde_el_corte_rige_el_saldo_del_ciclo_nuevo():
    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 10, 1)

        # El mismo pedido de 6 dias que el test anterior rechazaba contra el
        # ciclo 2025 ahora entra, porque el ciclo vigente paso a ser 2026
        # (20 dias disponibles).
        resultado = create_license_request(
            data=_payload(6), db=_db(SALDOS),
            current_user={"employeeId": 8, "permisos": set()},
        )
        assert resultado == {"message": "Solicitud creada exitosamente", "id": 101}
