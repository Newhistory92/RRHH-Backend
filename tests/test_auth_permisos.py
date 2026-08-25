"""Tests de la autorizacion por permiso, sin base real."""

import pytest
from fastapi import HTTPException

from app.auth_middleware import _autorizar
from app.permisos import COMODIN


def test_autorizar_deja_pasar_con_el_permiso_exacto():
    user = {"usuario": "emi25", "roleId": 4, "permisos": {"estadisticas.ver"}}
    assert _autorizar(user, "estadisticas.ver") is user


def test_autorizar_deja_pasar_al_comodin():
    user = {"usuario": "admin", "roleId": 1, "permisos": {COMODIN}}
    assert _autorizar(user, "admin.gestionar") is user


def test_autorizar_rechaza_sin_el_permiso():
    user = {"usuario": "emi25", "roleId": 4, "permisos": {"estadisticas.ver"}}
    with pytest.raises(HTTPException) as exc:
        _autorizar(user, "rrhh.gestionar")
    assert exc.value.status_code == 403


def test_el_403_nombra_el_permiso_faltante_no_ids_de_rol():
    user = {"usuario": "emi25", "roleId": 4, "permisos": set()}
    with pytest.raises(HTTPException) as exc:
        _autorizar(user, "rrhh.gestionar")
    assert "rrhh.gestionar" in exc.value.detail
    assert "[1, 2]" not in exc.value.detail
