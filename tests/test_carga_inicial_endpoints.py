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
    db = FakeSession({
        "SELECT e.gender": [{"gender": "Masculino", "roleName": "rrhh"}],
        "DISTINCT categoria": [{"categoria": "Vacaciones"}],
    })
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Vacaciones", diasPendientes=5),
    ])
    guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    _sql, params = db.ejecutadas[-1]
    assert params[0]["cargadoPor"] == 7
    assert params[0]["empId"] == 8


def test_guardar_rechaza_categoria_que_no_le_aplica_al_empleado():
    """Nacimiento no le aplica a una empleada: guardarlo dejaria un dato
    huerfano que el catalogo nunca va a mostrarle."""
    db = FakeSession({
        "SELECT e.gender": [{"gender": "Femenino", "roleName": "user"}],
        "DISTINCT categoria": [{"categoria": "Nacimiento"}],
    })
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Nacimiento", diasPendientes=5),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_acepta_categoria_restringida_para_rol_rrhh():
    db = FakeSession({
        "SELECT e.gender": [{"gender": "Masculino", "roleName": "rrhh"}],
        "DISTINCT categoria": [{"categoria": "Accidente de trabajo"}],
    })
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Accidente de trabajo", diasPendientes=5),
    ])
    guardar_carga_inicial(8, payload, db, {"employeeId": 7})


def test_guardar_rechaza_pares_anio_categoria_duplicados():
    db = FakeSession({
        "SELECT e.gender": [{"gender": "Masculino", "roleName": "user"}],
        "DISTINCT categoria": [{"categoria": "Particular"}],
    })
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Particular", diasPendientes=5),
        SaldoCargado(anio=2026, categoria="Particular", diasPendientes=8),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_rechaza_categoria_no_configurada():
    db = FakeSession({
        "SELECT e.gender": [{"gender": "Masculino", "roleName": "user"}],
        "DISTINCT categoria": [{"categoria": "Particular"}],
    })
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Categoria Inexistente", diasPendientes=5),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_el_payload_no_puede_declarar_quien_cargo():
    """El id de quien carga sale del token. Si el request pudiera declararlo,
    cualquiera podria firmar la carga con el legajo de otro."""
    campos = set(CargaInicialRequest.model_fields) | set(SaldoCargado.model_fields)
    assert "cargadoPor" not in campos
    assert "employeeId" not in campos


# ---------------------------------------------------------------------------
# Tests de endpoint (TestClient): prueban el gate de permiso y el GET, que
# antes no tenian ninguna cobertura a ese nivel.
#
# require_permission("licencias.cargaInicial") se invoca inline en la firma
# de cada ruta, asi que cada invocacion arma un closure _check DISTINTO.
# Overridear app.dependency_overrides con una llamada nueva a
# require_permission(...) no apuntaria al mismo objeto que usa la ruta y el
# override quedaria sin efecto -- el test pasaria por una razon equivocada
# (o ni siquiera se aplicaria). En cambio get_current_user es una funcion de
# modulo estable: overridearla y dejar correr la logica real de
# _autorizar/tiene_permiso prueba el gate de verdad.
# ---------------------------------------------------------------------------

def test_get_carga_inicial_exige_el_permiso():
    """Sin el permiso licencias.cargaInicial, un caller autenticado tiene que
    recibir 403, no ver el catalogo."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth_middleware import get_current_user
    from app.routes.carga_inicial_licencias import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "usuario": "sin_permiso", "roleId": 2, "employeeId": 7, "permisos": set(),
    }
    client = TestClient(app)

    resp = client.get("/licenses/carga-inicial/8")
    assert resp.status_code == 403


def test_get_carga_inicial_permite_a_quien_tiene_el_permiso():
    """Con el permiso, y sin tocar una base real, el catalogo se arma
    normalmente."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth_middleware import get_current_user
    from app.routes.carga_inicial_licencias import router, get_db

    db = FakeSession({
        "SELECT e.gender": [
            {"gender": "Masculino", "roleName": "rrhh", "tipoContrato": "permanente"},
        ],
        "DISTINCT categoria": [{"categoria": "Vacaciones"}, {"categoria": "Particular"}],
        "categoria, diasTotales": [{"categoria": "Particular", "diasTotales": 5}],
        "FROM SaldoInicialLicencia": [],
    })

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {
        "usuario": "con_permiso", "roleId": 3, "employeeId": 7,
        "permisos": {"licencias.cargaInicial"},
    }
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    resp = client.get("/licenses/carga-inicial/8")
    assert resp.status_code == 200
    body = resp.json()
    assert any(f["categoria"] == "Vacaciones" for f in body["acumulables"])
    # El default configurado llega hasta la respuesta, filtrado por el
    # contrato del empleado.
    particular = next(f for f in body["anuales"] if f["categoria"] == "Particular")
    assert particular["diasConfigurados"] == 5


# ---------------------------------------------------------------------------
# diasConfigurados: el valor por defecto del casillero, para que RRHH no
# tenga que tipear las veinte categorias una por una.
# ---------------------------------------------------------------------------

def test_las_anuales_traen_el_tope_configurado_como_default():
    """El caso comun es que la licencia anual este entera: se arranca del tope
    configurado y RRHH baja solo las excepciones."""
    cat = armar_catalogo_carga(
        categorias=["Particular"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
        dias_configurados={"Particular": 5},
    )
    assert cat["anuales"][0]["diasConfigurados"] == 5


def test_vacaciones_no_trae_default_configurado():
    """Para vacaciones el tope sale de la antiguedad, no de la configuracion:
    ofrecer ahi el numero del config seria ofrecer un default equivocado."""
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
        dias_configurados={"Vacaciones": 10},
    )
    assert all(f["diasConfigurados"] is None for f in cat["acumulables"])


def test_lo_ya_cargado_no_lo_pisa_el_default():
    """diasPendientes y diasConfigurados son datos distintos: el primero es lo
    que RRHH ya decidio, el segundo solo el punto de partida sugerido."""
    cat = armar_catalogo_carga(
        categorias=["Particular"], saldos={(2026, "Particular"): 2},
        anio_actual=2026, gender="Masculino", role_name="rrhh",
        dias_configurados={"Particular": 5},
    )
    fila = cat["anuales"][0]
    assert fila["diasPendientes"] == 2
    assert fila["diasConfigurados"] == 5


def test_sin_configuracion_para_esa_categoria_el_default_va_en_none():
    cat = armar_catalogo_carga(
        categorias=["Particular"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
        dias_configurados={},
    )
    assert cat["anuales"][0]["diasConfigurados"] is None
