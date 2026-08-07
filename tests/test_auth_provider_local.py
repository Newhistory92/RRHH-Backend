import os

import pytest
from fastapi import HTTPException

from tests.fakes import FakeSession, hash_bcrypt


HASH_SECRETO = hash_bcrypt("secreto")

USUARIO_ACTIVO = {
    "id": 7,
    "usuario": "erojo",
    "email": "erojo@rrhh.local",
    "password": HASH_SECRETO,
    "roleId": 1,
    "employeeId": 264,
    "activo": True,
    "origen": "local",
}


def _sesion(user_row=None):
    return FakeSession({"FROM [User]": [user_row] if user_row else []})


# -- LocalAuthProvider --------------------------------------------------------

def test_credenciales_validas_devuelven_el_resultado():
    from app.services.auth_providers.local import LocalAuthProvider

    resultado = LocalAuthProvider().autenticar(_sesion(USUARIO_ACTIVO), "erojo", "secreto")

    assert resultado.usuario == "erojo"
    assert resultado.roleId == 1
    assert resultado.employeeId == 264


def test_usuario_inexistente_da_401():
    from app.services.auth_providers.local import LocalAuthProvider

    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(None), "fantasma", "secreto")
    assert e.value.status_code == 401


def test_password_incorrecta_da_401():
    from app.services.auth_providers.local import LocalAuthProvider

    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(USUARIO_ACTIVO), "erojo", "otra")
    assert e.value.status_code == 401


def test_usuario_inhabilitado_da_403():
    from app.services.auth_providers.local import LocalAuthProvider

    inactivo = {**USUARIO_ACTIVO, "activo": False}
    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(inactivo), "erojo", "secreto")
    assert e.value.status_code == 403


def test_hash_corrupto_da_401_y_no_revienta():
    from app.services.auth_providers.local import LocalAuthProvider

    corrupto = {**USUARIO_ACTIVO, "password": "no-es-un-hash"}
    with pytest.raises(HTTPException) as e:
        LocalAuthProvider().autenticar(_sesion(corrupto), "erojo", "secreto")
    assert e.value.status_code == 401


def test_empleado_sin_vincular_devuelve_employee_id_nulo():
    from app.services.auth_providers.local import LocalAuthProvider

    sin_empleado = {**USUARIO_ACTIVO, "employeeId": None}
    resultado = LocalAuthProvider().autenticar(_sesion(sin_empleado), "erojo", "secreto")
    assert resultado.employeeId is None


# -- Seleccion del proveedor --------------------------------------------------

def test_sin_variable_de_entorno_el_proveedor_es_local(monkeypatch):
    from app.services import auth_providers

    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    assert auth_providers.nombre_proveedor() == "local"


def test_el_valor_se_normaliza(monkeypatch):
    from app.services import auth_providers

    monkeypatch.setenv("AUTH_PROVIDER", "  LOCAL  ")
    assert auth_providers.nombre_proveedor() == "local"


def test_valor_invalido_falla_al_arrancar(monkeypatch):
    from app.services import auth_providers

    monkeypatch.setenv("AUTH_PROVIDER", "ldap")
    with pytest.raises(RuntimeError, match="AUTH_PROVIDER"):
        auth_providers.nombre_proveedor()


def test_get_provider_devuelve_la_instancia_local(monkeypatch):
    from app.services import auth_providers
    from app.services.auth_providers.local import LocalAuthProvider

    monkeypatch.setenv("AUTH_PROVIDER", "local")
    assert isinstance(auth_providers.get_provider(), LocalAuthProvider)
