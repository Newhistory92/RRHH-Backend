"""
Middleware de autorizacion para FastAPI.

Provee tres dependencias reutilizables:
  - get_current_user:  valida el JWT y arma el usuario con sus permisos
  - require_auth:      exige token valido, sin pedir permiso puntual
  - require_permission: exige un codigo de permiso concreto

Los permisos salen de la base en CADA request (ver permisos_de_rol). El JWT
lleva el roleId solo como pista: si el admin cambia el rol de alguien, el
cambio aplica en el request siguiente y no queda congelado hasta que expire
el token.

No hay ids de rol en este modulo: la autorizacion habla de codigos de
permiso, y que rol tiene cuales vive en la tabla RolePermission.
"""

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text
from jose import jwt
import os
from dotenv import load_dotenv
from app.database.database import SessionLocal
from app.database.token_blacklist import is_blacklisted
from app.database.permissions import permisos_de_rol
from app.permisos import tiene_permiso

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM  = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Dependencia: usuario autenticado
# ---------------------------------------------------------------------------
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> dict:
    """
    Dependencia FastAPI que:
      1. Extrae el token Bearer del header Authorization
      2. Verifica que no esté en la blacklist
      3. Decodifica el JWT
      4. Retorna un dict con {usuario, roleId, employeeId}

    Lanza 401 en cualquier caso de fallo.
    """
    credentials_error = HTTPException(
        status_code=401,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if is_blacklisted(db, token):
        raise HTTPException(
            status_code=401,
            detail="Token invalidado (sesión cerrada)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise credentials_error

    usuario = payload.get("sub")
    role_id = payload.get("roleId")

    if not usuario:
        raise credentials_error

    # Si el payload no tiene roleId (tokens emitidos antes de la mejora),
    # lo obtenemos desde la DB como fallback
    if role_id is None:
        row = db.execute(
            text("SELECT roleId, employeeId FROM [User] WHERE usuario = :u"),
            {"u": usuario}
        ).fetchone()
        if row:
            role_id     = row.roleId
            employee_id = row.employeeId
        else:
            raise credentials_error
    else:
        row = db.execute(
            text("SELECT employeeId FROM [User] WHERE usuario = :u"),
            {"u": usuario}
        ).fetchone()
        employee_id = row.employeeId if row else None

    return {
        "usuario":    usuario,
        "roleId":     role_id,
        "employeeId": employee_id,
        "permisos":   permisos_de_rol(db, role_id),
    }


# ---------------------------------------------------------------------------
# Autorizacion por permiso
# ---------------------------------------------------------------------------
def _autorizar(user: dict, requerido: str) -> dict:
    """
    Chequeo puro: devuelve el usuario o lanza 403.

    Separado de la dependencia para poder testearlo sin FastAPI ni base.
    """
    if not tiene_permiso(user.get("permisos") or set(), requerido):
        raise HTTPException(
            status_code=403,
            detail=f"Acceso denegado. Se requiere el permiso: {requerido}",
        )
    return user


def require_permission(code: str):
    """
    Dependencia que exige un codigo de permiso.

    Uso:
        @router.get("/", dependencies=[Depends(require_permission("rrhh.gestionar"))])

    O en la firma si necesitas el usuario:
        def endpoint(user = Depends(require_permission("rrhh.gestionar"))):
            ...
    """
    def _check(user: dict = Depends(get_current_user)) -> dict:
        return _autorizar(user, code)
    return _check


def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """
    Exige token valido, sin permiso puntual.

    Para endpoints que cualquier empleado logueado puede usar y que ya
    filtran por employeeId adentro (por ejemplo /asistencia/mi).
    """
    return user
