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
from unittest.mock import patch

from app.routes.licenses import get_tipos_disponibles
from app.services.saldo_licencias import ciclo_vacaciones
from tests.fakes import FakeSession

# Vacaciones se resuelve contra el ciclo (ver ciclo_vacaciones), no contra el
# anio calendario -- estos tests previos cargan saldo inicial de Vacaciones,
# asi que tienen que apuntar a la misma clave que usa el endpoint.
ANIO_ACTUAL = ciclo_vacaciones(date.today())

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


def test_sin_saldo_inicial_un_tope_fijo_de_vacaciones_no_cero_se_respeta():
    """El caso real de 'contratado': ConfiguracionLicencias tiene Vacaciones
    en 10 dias fijos, no en 0. Sin saldo inicial cargado, ese 10 tiene que
    regir -- el calculo por antiguedad es solo el relleno para cuando la
    config esta en cero, no un reemplazo general. Confundir esto le cambiaria
    el tope real a cualquier "contratado" que no tenga saldo inicial."""
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row(tipoContrato="contratado")],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 10, "consumidos": 2}],
        SALDO_INICIAL_FRAGMENTO: [],
    })

    resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 10
    assert fila["disponibles"] == 8


def test_vacaciones_consulta_el_anio_del_ciclo_no_el_calendario():
    """Antes del 1 de octubre rige el anio anterior. Sin esto, el empleado
    podia pedir las vacaciones del anio nuevo desde el 1 de enero."""
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": 2025, "categoria": "Vacaciones", "diasPendientes": 7},
        ],
    })

    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 30)
        resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 7


def test_despues_del_corte_vacaciones_toma_el_anio_en_curso():
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": 2026, "categoria": "Vacaciones", "diasPendientes": 12},
        ],
    })

    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 10, 1)
        resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 12
