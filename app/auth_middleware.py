"""
Middleware de autorización para FastAPI.

Provee dos dependencias reutilizables:
  - get_current_user: extrae y valida el JWT, retorna datos del usuario
  - require_roles:    factory que crea una dependencia que verifica el rol

Roles asumidos (basado en roleId=2 asignado al registrar):
  ROLE_ADMIN = 1
  ROLE_USER  = 2

Si tu tabla Role tiene IDs distintos, actualizar las constantes aquí abajo.
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

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM  = "HS256"

# ---------------------------------------------------------------------------
# Constantes de roles — ajustar según los IDs reales en la tabla Role
# ---------------------------------------------------------------------------
ROLE_ADMIN = 1
ROLE_USER  = 2
# Si existen más roles (ej. RRHH=3) agregalos aquí como constantes

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
    }


# ---------------------------------------------------------------------------
# Factory: require_roles(*roles)
# ---------------------------------------------------------------------------
def require_roles(*allowed_roles: int):
    """
    Retorna una dependencia FastAPI que verifica que el usuario autenticado
    tenga uno de los roles especificados.

    Uso:
        @router.get("/", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])

    O en la firma del endpoint si necesitás el usuario:
        def my_endpoint(user = Depends(require_roles(ROLE_ADMIN))):
            ...

    Lanza 403 si el rol no está permitido.
    """
    def _check(user: dict = Depends(get_current_user)) -> dict:
        if user["roleId"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado. Se requiere uno de los roles: {list(allowed_roles)}",
            )
        return user
    return _check


# ---------------------------------------------------------------------------
# Shorthand preconfigurados para los roles más comunes
# ---------------------------------------------------------------------------
require_admin       = require_roles(ROLE_ADMIN)
require_any_auth    = require_roles(ROLE_ADMIN, ROLE_USER)   # cualquier usuario logueado
