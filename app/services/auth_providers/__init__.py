"""
Seleccion del proveedor de autenticacion segun AUTH_PROVIDER del .env.

    AUTH_PROVIDER=local        version comercial (default)
    AUTH_PROVIDER=obrasocial   version institucional

Una sola base de codigo cubre las dos variantes. No hay ramas divergentes:
cambiar de modo es cambiar una linea del .env.
"""

import os

from app.services.auth_providers.base import AuthProvider, ResultadoAuth
from app.services.auth_providers.local import LocalAuthProvider
from app.services.auth_providers.obrasocial import ObraSocialAuthProvider

PROVEEDOR_DEFAULT = "local"

_PROVEEDORES = {
    "local": LocalAuthProvider,
    "obrasocial": ObraSocialAuthProvider,
}


def nombre_proveedor() -> str:
    """
    El valor configurado, normalizado. Un valor desconocido es un error de
    configuracion y tiene que explotar fuerte: caer silenciosamente al modo
    local dejaria una institucion entera sin su autenticacion real.
    """
    crudo = (os.getenv("AUTH_PROVIDER") or PROVEEDOR_DEFAULT).strip().lower()
    if crudo not in _PROVEEDORES:
        raise RuntimeError(
            f"AUTH_PROVIDER='{crudo}' no es un proveedor valido. "
            f"Opciones: {', '.join(sorted(_PROVEEDORES))}"
        )
    return crudo


def get_provider() -> AuthProvider:
    return _PROVEEDORES[nombre_proveedor()]()


__all__ = ["AuthProvider", "ResultadoAuth", "get_provider", "nombre_proveedor"]
