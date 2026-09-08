"""
Catalogo y guardado de la carga inicial de saldos.

El catalogo es funcion pura: recibe las categorias configuradas y lo ya
cargado, y decide que se le ofrece a ese empleado.
"""

import pytest
from fastapi import HTTPException

from app.routes.carga_inicial_licencias import (
    SaldoCargado,
    CargaInicialRequest,
    armar_catalogo_carga,
    guardar_carga_inicial,
)
from tests.fakes import FakeSession

CATEGORIAS = ["Vacaciones", "Particular", "Nacimiento", "Accidente de trabajo"]


def test_vacaciones_va_a_acumulables_con_tres_anios():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert [f["anio"] for f in cat["acumulables"]] == [2026, 2025, 2024]
    assert all(f["categoria"] == "Vacaciones" for f in cat["acumulables"])


def test_las_demas_van_a_anuales_solo_con_el_anio_actual():
    cat = armar_catalogo_carga(
        categorias=["Particular"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert [f["anio"] for f in cat["anuales"]] == [2026]
    assert cat["acumulables"] == []


def test_devuelve_el_valor_ya_cargado():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={(2024, "Vacaciones"): 5},
        anio_actual=2026, gender="Masculino", role_name="rrhh",
    )
    fila = next(f for f in cat["acumulables"] if f["anio"] == 2024)
    assert fila["diasPendientes"] == 5


def test_lo_no_cargado_viene_en_none_y_no_en_cero():
    """None es 'no se cargo'; cero es 'no le queda nada'. La pantalla los
    muestra distinto y el backend no puede aplastarlos."""
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert all(f["diasPendientes"] is None for f in cat["acumulables"])


def test_el_cero_cargado_se_conserva():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={(2026, "Vacaciones"): 0},
        anio_actual=2026, gender="Masculino", role_name="rrhh",
    )
    fila = next(f for f in cat["acumulables"] if f["anio"] == 2026)
    assert fila["diasPendientes"] == 0


def test_no_ofrece_nacimiento_a_una_empleada():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Femenino", role_name="rrhh",
    )
    assert all(f["categoria"] != "Nacimiento" for f in cat["anuales"])


def test_no_ofrece_restringidas_a_un_rol_comun():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Masculino", role_name="user",
    )
    assert all(f["categoria"] != "Accidente de trabajo" for f in cat["anuales"])


def test_ofrece_restringidas_a_rrhh():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert any(f["categoria"] == "Accidente de trabajo" for f in cat["anuales"])


def test_guardar_rechaza_dias_negativos():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Vacaciones", diasPendientes=-1),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_rechaza_un_anio_fuera_de_la_ventana():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2019, categoria="Vacaciones", diasPendientes=5),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_registra_quien_cargo():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Vacaciones", diasPendientes=5),
    ])
    guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    _sql, params = db.ejecutadas[-1]
    assert params[0]["cargadoPor"] == 7
    assert params[0]["empId"] == 8


def test_el_payload_no_puede_declarar_quien_cargo():
    """El id de quien carga sale del token. Si el request pudiera declararlo,
    cualquiera podria firmar la carga con el legajo de otro."""
    campos = set(CargaInicialRequest.model_fields) | set(SaldoCargado.model_fields)
    assert "cargadoPor" not in campos
    assert "employeeId" not in campos
