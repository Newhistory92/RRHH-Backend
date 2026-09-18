"""
Endpoints con require_auth que reciben un employeeId y no miraban de quien era.

Cualquier logueado podia leer el legajo o la campanita de otro cambiando el id
en la URL. La regla: lo propio siempre; lo ajeno, solo con el permiso que
gobierna ese dato.

get_current_user se reemplaza por un usuario fijo: lo que se prueba aca es el
chequeo de duenio, no el token (eso lo cubren test_auth_middleware y
test_rutas_de_baja).
"""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth_middleware as auth_middleware
from app.routes import employee, licenses
from tests.fakes import FakeSession

YO = 7
OTRO = 8

EMPLEADO_COMUN = {"usuario": "emp", "roleId": 2, "employeeId": YO,
                  "permisos": {"licencias.propias", "documentos.propios"}}
RRHH = {"usuario": "rrhh", "roleId": 3, "employeeId": 1,
        "permisos": {"rrhh.gestionar", "licencias.configurar"}}
ESTADISTA = {"usuario": "est", "roleId": 4, "employeeId": 2,
             "permisos": {"estadisticas.ver"}}
ADMIN = {"usuario": "admin", "roleId": 1, "employeeId": 3, "permisos": {"*"}}


class _Fila(dict):
    """Fila con todas las columnas: las que no se dan valen None."""
    def __missing__(self, clave):
        return None


def _cliente(usuario, respuestas=None):
    db = FakeSession(respuestas or {})
    app = FastAPI()
    app.include_router(employee.router)
    app.include_router(licenses.router)
    app.dependency_overrides[auth_middleware.get_current_user] = lambda: usuario
    app.dependency_overrides[employee.get_db] = lambda: db
    app.dependency_overrides[licenses.get_db] = lambda: db
    return TestClient(app), db


# ---------------------------------------------------------------------------
# GET /employee/{employee_id}
# ---------------------------------------------------------------------------
# La consulta principal es la unica con este JOIN.
LEGAJO = {"LEFT JOIN JornadaLaboral j": [_Fila(id=OTRO, name="Otro")]}


def test_legajo_ajeno_sin_permiso_es_403():
    cliente, db = _cliente(EMPLEADO_COMUN, LEGAJO)
    resp = cliente.get(f"/employee/{OTRO}")
    assert resp.status_code == 403
    assert "FROM Employee" not in db.sql_ejecutado()


@pytest.mark.parametrize("usuario", [RRHH, ESTADISTA, ADMIN],
                         ids=["rrhh", "estadista", "admin"])
def test_legajo_ajeno_con_permiso_es_200(usuario):
    """RRHH lo abre desde la tabla de legajos; el estadista desde el detalle
    del panel de Estadisticas."""
    cliente, _ = _cliente(usuario, LEGAJO)
    resp = cliente.get(f"/employee/{OTRO}")
    assert resp.status_code == 200
    assert resp.json()["id"] == OTRO


def test_legajo_propio_es_200():
    """El shell carga el legajo propio al montar."""
    fila = {"LEFT JOIN JornadaLaboral j": [_Fila(id=YO, name="Yo")]}
    cliente, _ = _cliente(EMPLEADO_COMUN, fila)
    resp = cliente.get(f"/employee/{YO}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /licenses/notificaciones?employee_id=
# ---------------------------------------------------------------------------
MENSAJES = {"FROM Message": [{"id": 1, "text": "hola", "createdAt": "2026-09-01",
                              "leida": False}]}


def test_notificaciones_ajenas_sin_permiso_es_403():
    cliente, db = _cliente(EMPLEADO_COMUN, MENSAJES)
    resp = cliente.get(f"/licenses/notificaciones?employee_id={OTRO}")
    assert resp.status_code == 403
    assert "FROM Message" not in db.sql_ejecutado()


def test_notificaciones_propias_es_200():
    """La campanita del header las pide con el employeeId propio."""
    cliente, _ = _cliente(EMPLEADO_COMUN, MENSAJES)
    resp = cliente.get(f"/licenses/notificaciones?employee_id={YO}")
    assert resp.status_code == 200
    assert len(resp.json()["notifications"]) == 1


def test_notificaciones_ajenas_con_licencias_configurar_es_200():
    cliente, _ = _cliente(RRHH, MENSAJES)
    resp = cliente.get(f"/licenses/notificaciones?employee_id={OTRO}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /licenses/request
# ---------------------------------------------------------------------------
SOLICITANTE = {
    "INNER JOIN CondicionLaboral cl": [{"gender": "Femenino", "employee_name": "X",
                                        "tipoContrato": "Planta", "fechaIngreso": None,
                                        "roleName": "USER"}],
    # OUTPUT INSERTED.id: el endpoint lee fetchone()[0].
    "INSERT INTO License": [(99,)],
}


def _solicitud(employee_id, tipo="Estudio"):
    return {"employeeId": employee_id, "type": tipo, "duration": 2,
            "startDate": "2026-11-02T00:00:00", "endDate": "2026-11-03T00:00:00"}


@pytest.fixture
def catalogo(monkeypatch):
    """El saldo tiene su propio test; aca solo tiene que alcanzar."""
    monkeypatch.setattr(licenses, "tipos_disponibles_de",
                        lambda *a, **k: {"tipos": [{"nombre": "Estudio",
                                                    "disponibles": 10}]})


def test_solicitud_a_nombre_de_otro_corta_antes_de_leer_sus_datos():
    """El 403 existia, pero despues de las validaciones de genero y
    antiguedad: pedir 'Nacimiento' a nombre de otro devolvia el 400 que
    delataba su genero antes de llegar al chequeo de duenio."""
    cliente, db = _cliente(EMPLEADO_COMUN, SOLICITANTE)
    resp = cliente.post("/licenses/request", json=_solicitud(OTRO, "Nacimiento"))
    assert resp.status_code == 403
    assert "FROM Employee" not in db.sql_ejecutado()
    assert "FROM License" not in db.sql_ejecutado()


def test_solicitud_propia_es_200(catalogo):
    cliente, db = _cliente(EMPLEADO_COMUN, SOLICITANTE)
    resp = cliente.post("/licenses/request", json=_solicitud(YO))
    assert resp.status_code == 200
    assert db.commits == 1


def test_rrhh_carga_una_solicitud_a_nombre_de_otro(catalogo):
    """El panel de RRHH (DetailTables) carga licencias por el empleado."""
    cliente, db = _cliente(RRHH, SOLICITANTE)
    resp = cliente.post("/licenses/request", json=_solicitud(OTRO))
    assert resp.status_code == 200
    assert db.commits == 1


# ---------------------------------------------------------------------------
# PATCH /licenses/requests/{license_id}/status
# ---------------------------------------------------------------------------
LICENCIA_DE_YO = {"SELECT * FROM License WHERE id": [
    {"id": 5, "employeeId": YO, "type": "Estudio", "status": "Pendiente",
     "duracion": 2, "startDate": date(2026, 11, 2), "endDate": date(2026, 11, 3)}]}
APROBACION_PENDIENTE = {"SELECT 1 FROM Aprobaciones": [{"x": 1}]}


def _resolver(usuario, respuestas, **payload):
    cliente, db = _cliente(usuario, respuestas)
    resp = cliente.patch("/licenses/requests/5/status",
                         json={"status": "Rechazada", **payload})
    return resp, db


def test_sin_supervisor_id_no_se_saltea_el_chequeo():
    """Omitir supervisorId salteaba el chequeo entero: cualquiera podia
    cambiarle el estado a cualquier licencia, la propia incluida."""
    resp, db = _resolver(EMPLEADO_COMUN, LICENCIA_DE_YO)
    assert resp.status_code == 403
    assert "UPDATE License" not in db.sql_ejecutado()


def test_poner_el_propio_id_como_supervisor_no_alcanza():
    """El fallback de Paso B insertaba la aprobacion si no existia: bastaba
    con mandar el propio employeeId para aprobar cualquier licencia."""
    resp, db = _resolver(EMPLEADO_COMUN, LICENCIA_DE_YO, supervisorId=YO)
    assert resp.status_code == 403
    assert "UPDATE License" not in db.sql_ejecutado()


def test_supervisor_con_aprobacion_pendiente_resuelve():
    """El flujo de Gestion de Licencias: manda su employeeId como supervisorId
    y la licencia figura entre sus pendientes."""
    supervisor = {**EMPLEADO_COMUN, "employeeId": OTRO}
    resp, db = _resolver(supervisor, {**APROBACION_PENDIENTE, **LICENCIA_DE_YO},
                         supervisorId=OTRO)
    assert resp.status_code == 200
    assert db.commits == 1


def test_supervisor_no_puede_resolver_en_nombre_de_otro_supervisor():
    supervisor = {**EMPLEADO_COMUN, "employeeId": OTRO}
    resp, _ = _resolver(supervisor, {**APROBACION_PENDIENTE, **LICENCIA_DE_YO},
                        supervisorId=99)
    assert resp.status_code == 403


def test_rrhh_resuelve_sin_supervisor_id():
    resp, db = _resolver(RRHH, LICENCIA_DE_YO)
    assert resp.status_code == 200
    assert db.commits == 1
