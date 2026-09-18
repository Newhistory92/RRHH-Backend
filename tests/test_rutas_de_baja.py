"""
El dado de baja no puede usar endpoints por URL directa.

El recorte de permisos solo frena a los endpoints con require_permission; los
que piden solo estar logueado (require_auth, o get_current_user directo)
quedaban abiertos. Estos tests pasan por el get_current_user real, con
FakeSession, para probar que el corte vive en el punto comun a todos.
"""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

import app.auth_middleware as auth_middleware
from app.auth_middleware import ruta_permitida_de_baja
from app.routes import employee, licenses
from tests.fakes import FakeSession

SECRETO = "secreto-de-test"
EMPLEADO = 7


def _cliente(monkeypatch, bajas):
    monkeypatch.setattr(auth_middleware, "SECRET_KEY", SECRETO)
    db = _db(bajas)

    app = FastAPI()
    app.include_router(employee.router)
    app.include_router(licenses.router)
    app.dependency_overrides[auth_middleware.get_db] = lambda: db
    app.dependency_overrides[employee.get_db] = lambda: db
    app.dependency_overrides[licenses.get_db] = lambda: db

    token = jwt.encode({"sub": "emi25", "roleId": 2}, SECRETO, algorithm="HS256")
    cliente = TestClient(app)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente, db


def _db(bajas):
    return FakeSession({
        "FROM TokenBlacklist": [],
        # get_current_user lee la fila con atributos (row.employeeId).
        "FROM [User]": [SimpleNamespace(employeeId=EMPLEADO, roleId=2)],
        "FROM AuthRolePermission": [{"code": "licencias.propias"},
                                    {"code": "documentos.propios"}],
        "FROM EmployeeBaja": bajas,
        "FROM EmployeeDocument": [{"id": 1, "tipo": "Recibo", "descripcion": None,
                                   "fileName": "r.pdf", "mimeType": "application/pdf",
                                   "createdAt": "2026-09-01"}],
    })


BAJA_VIGENTE = [{"fechaBaja": date(2020, 1, 1), "fechaReingreso": None}]


def test_de_baja_no_puede_pedir_licencia_por_url_directa(monkeypatch):
    cliente, db = _cliente(monkeypatch, BAJA_VIGENTE)
    resp = cliente.post("/licenses/request", json={"employeeId": EMPLEADO})
    assert resp.status_code == 403
    assert "FROM License" not in db.sql_ejecutado()


def test_de_baja_no_puede_leer_notificaciones(monkeypatch):
    cliente, _ = _cliente(monkeypatch, BAJA_VIGENTE)
    resp = cliente.get(f"/licenses/notificaciones?employee_id={EMPLEADO}")
    assert resp.status_code == 403


def test_de_baja_puede_listar_sus_documentos(monkeypatch):
    cliente, _ = _cliente(monkeypatch, BAJA_VIGENTE)
    resp = cliente.get(f"/employee/{EMPLEADO}/documents")
    assert resp.status_code == 200
    assert resp.json()["documents"][0]["fileName"] == "r.pdf"


def test_de_baja_no_puede_leer_el_legajo_de_otro(monkeypatch):
    cliente, _ = _cliente(monkeypatch, BAJA_VIGENTE)
    assert cliente.get(f"/employee/{EMPLEADO + 1}").status_code == 403


def test_sin_baja_el_corte_no_interviene(monkeypatch):
    """Llega al cuerpo del endpoint: el 400 es su propia validacion."""
    cliente, _ = _cliente(monkeypatch, [])
    resp = cliente.post("/licenses/request", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Datos incompletos"
    assert cliente.get(f"/licenses/notificaciones?employee_id={EMPLEADO}").status_code == 200


def test_baja_programada_todavia_no_corta(monkeypatch):
    cliente, _ = _cliente(monkeypatch, [{"fechaBaja": date(2999, 1, 1),
                                         "fechaReingreso": None}])
    resp = cliente.post("/licenses/request", json={})
    assert resp.status_code == 400


@pytest.mark.parametrize("metodo,ruta,params,esperado", [
    ("GET", "/auth/permisos", {}, True),
    ("GET", "/employee/{employee_id}", {"employee_id": "7"}, True),
    ("GET", "/employee/{employee_id}", {"employee_id": "8"}, False),
    ("GET", "/employee/{employee_id}/documents", {"employee_id": "7"}, True),
    ("GET", "/employee/{employee_id}/documents/{document_id}/download",
     {"employee_id": "7", "document_id": "3"}, True),
    ("PUT", "/employee/{employee_id}", {"employee_id": "7"}, False),
    ("POST", "/licenses/request", {}, False),
    ("GET", None, {}, False),
])
def test_allowlist(metodo, ruta, params, esperado):
    assert ruta_permitida_de_baja(metodo, ruta, params, EMPLEADO) is esperado
