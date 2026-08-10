"""
Proveedor por defecto: valida contra la tabla [User] de la propia base. Es el
comportamiento historico del sistema, movido detras del contrato sin cambios
de semantica.
"""

import bcrypt
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.auth_providers.base import ResultadoAuth


def verificar_password(plano: str, hash_almacenado: str) -> None:
    """
    Un hash corrupto o vacio en la base hace que bcrypt lance ValueError. Eso
    es una credencial invalida, no un error del servidor: se traduce a 401.
    """
    try:
        valida = bcrypt.checkpw(plano.encode(), (hash_almacenado or "").encode())
    except ValueError:
        valida = False
    if not valida:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")


class LocalAuthProvider:
    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        fila = db.execute(text("""
            SELECT usuario, password, roleId, employeeId, activo
            FROM [User]
            WHERE usuario = :u OR email = :u
        """), {"u": usuario}).mappings().first()

        if fila is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        if not fila["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")

        verificar_password(password, fila["password"])

        return ResultadoAuth(
            usuario=fila["usuario"],
            roleId=fila["roleId"],
            employeeId=fila["employeeId"],
        )
