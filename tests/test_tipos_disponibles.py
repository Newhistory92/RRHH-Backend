"""
El saldo inicial dentro de /licenses/tipos-disponibles.

Este es el endpoint que realmente limita cuantos dias puede pedir el
empleado (el maxDays del selector de fechas sale de aca, no de /saldos), y
hasta ahora no consultaba SaldoInicialLicencia en absoluto: un saldo cargado
en cero -- "no le queda nada" -- no se hacia respetar donde mas importaba.

Se prueba llamando a la funcion de la ruta directamente con un FakeSession,
siguiendo el mismo patron que tests/test_carga_inicial_endpoints.py: no hay
una pieza pura y aislada que decida el total aca (a diferencia de
armar_balances), asi que el endpoint entero es la unidad minima testeable.
"""

from datetime import date

from app.routes.licenses import get_tipos_disponibles
from tests.fakes import FakeSession

ANIO_ACTUAL = date.today().year

EMP_QUERY_FRAGMENTO = "LEFT JOIN CondicionLaboral cl ON e.id = cl.employeeId"
CONFIG_QUERY_FRAGMENTO = "FROM ConfiguracionLicencias c"
SALDO_INICIAL_FRAGMENTO = "FROM SaldoInicialLicencia"


def _emp_row(**overrides):
    row = {
        "tipoContrato": "permanente",
        "fechaIngreso": None,
        "fechaJubilacion": None,
        "gender": "Masculino",
        "roleName": "user",
    }
    row.update(overrides)
    return row


def test_saldo_inicial_en_cero_capa_disponibles_en_cero():
    """El bug que motivo el fix: sin consultar SaldoInicialLicencia, un cero
    cargado por RRHH no se respetaba y el empleado seguia viendo los 30 dias
    de la configuracion."""
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": ANIO_ACTUAL, "categoria": "Vacaciones", "diasPendientes": 0},
        ],
    })

    resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 0
    assert fila["disponibles"] == 0


def test_sin_saldo_inicial_rige_la_configuracion():
    """Camino normal: sin saldo cargado, el total sale de ConfiguracionLicencias
    (o del calculo de antiguedad para vacaciones, que aca es 0 sin fechaIngreso)."""
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Particular", "diasTotales": 5, "consumidos": 2}],
        SALDO_INICIAL_FRAGMENTO: [],
    })

    resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Particular")
    assert fila["diasTotales"] == 5
    assert fila["disponibles"] == 3


def test_saldo_inicial_positivo_reemplaza_el_total_de_vacaciones():
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 1}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": ANIO_ACTUAL, "categoria": "Vacaciones", "diasPendientes": 12},
        ],
    })

    resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 12
    assert fila["disponibles"] == 11
