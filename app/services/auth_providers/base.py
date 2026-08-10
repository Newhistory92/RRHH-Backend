"""
Contrato de los proveedores de autenticacion.

El endpoint de login no sabe contra que se valida: pide el proveedor
configurado y le delega usuario y contrasena. Eso es lo que permite que la
version comercial y la institucional convivan en la misma base de codigo.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ResultadoAuth:
    """Lo minimo que el endpoint necesita para emitir el JWT."""

    usuario: str
    roleId: int
    employeeId: Optional[int]


class AuthProvider(Protocol):
    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        """
        Retorna el resultado si las credenciales son validas.

        Lanza HTTPException con el codigo que corresponda si no lo son: el
        proveedor decide el codigo porque conoce el motivo real del rechazo.
        """
        ...
