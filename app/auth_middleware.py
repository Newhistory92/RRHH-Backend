"""
Middleware de autorizacion para FastAPI.

Provee tres dependencias reutilizables:
  - get_current_user:  valida el JWT y arma el usuario con sus permisos
  - require_auth:      exige token valido, sin pedir permiso puntual
  - require_permission: exige un codigo de permiso concreto

Los permisos salen de la base en CADA request (ver permisos_efectivos, que
aplica el recorte por baja sobre los del rol). El JWT lleva el roleId solo
como pista: si el admin cambia el rol de alguien, el cambio aplica en el
request siguiente y no queda congelado hasta que expire el token.

Alguien de baja, ademas, solo puede usar las rutas de RUTAS_DE_BAJA: el
corte vive en get_current_user para alcanzar tambien a require_auth.

No hay ids de rol en este modulo: la autorizacion habla de codigos de
permiso, y que rol tiene cuales vive en la tabla RolePermission.
"""

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text
from jose import jwt
import os
from dotenv import load_dotenv
from app.database.database import SessionLocal
from app.database.token_blacklist import is_blacklisted
from app.database.permissions import esta_de_baja, permisos_efectivos
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
# Lo unico que puede usar alguien de baja
# ---------------------------------------------------------------------------
# El recorte de permisos solo frena a los endpoints con require_permission.
# Los que piden solo estar logueado (require_auth, o get_current_user directo)
# no miran permisos, asi que el dado de baja se deniega por defecto aca, en el
# punto comun a todos, y solo pasa lo que figura en esta lista.
#
# Clave: (metodo, plantilla de ruta tal como la registra FastAPI).
# Valor: True si la ruta tiene que ser sobre SU legajo ({employee_id} propio).
RUTAS_DE_BAJA: dict[tuple[str, str], bool] = {
    # El shell rearma el menu al montar con los permisos del servidor.
    ("GET", "/auth/permisos"): False,
    # El shell carga su propio empleado; sin esto la pantalla de Documentos
    # se queda en "Cargando informacion del empleado...". Solo el propio: el
    # permiso que abre legajos ajenos (rrhh.gestionar) ya no lo tiene.
    ("GET", "/employee/{employee_id}"): True,
    # La pantalla de Documentos: listar y abrir los suyos, que es todo lo que
    # la baja le deja.
    ("GET", "/employee/{employee_id}/documents"): True,
    ("GET", "/employee/{employee_id}/documents/{document_id}/download"): True,
}


def ruta_permitida_de_baja(metodo: str, ruta: str | None, path_params: dict,
                           employee_id: int | None) -> bool:
    """
    Si alguien de baja puede usar esta ruta. Chequeo puro, sin base.

    Una ruta desconocida (None) se deniega: el corte es por defecto cerrado.
    """
    solo_propio = RUTAS_DE_BAJA.get((metodo.upper(), ruta or ""))
    if solo_propio is None:
        return False
    if solo_propio:
        return str(path_params.get("employee_id")) == str(employee_id)
    return True


# ---------------------------------------------------------------------------
# Dependencia: usuario autenticado
# ---------------------------------------------------------------------------
def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> dict:
    """
    Dependencia FastAPI que:
      1. Extrae el token Bearer del header Authorization
      2. Verifica que no esté en la blacklist
      3. Decodifica el JWT
      4. Si la persona esta de baja, corta toda ruta fuera de RUTAS_DE_BAJA
      5. Retorna un dict con {usuario, roleId, employeeId, permisos}

    Lanza 401 en cualquier caso de fallo de token, y 403 si esta de baja y
    la ruta no esta permitida.
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

    de_baja = esta_de_baja(db, employee_id)
    if de_baja:
        ruta = getattr(request.scope.get("route"), "path", None)
        if not ruta_permitida_de_baja(request.method, ruta,
                                      request.path_params, employee_id):
            raise HTTPException(
                status_code=403,
                detail="Estás de baja: solo podés consultar tus documentos.",
            )

    return {
        "usuario":    usuario,
        "roleId":     role_id,
        "employeeId": employee_id,
        "permisos":   permisos_efectivos(db, role_id, employee_id,
                                         de_baja=de_baja),
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


def exigir_propio_o_permiso(user: dict, employee_id, *permisos: str) -> dict:
    """
    Chequeo de duenio para recursos de un empleado: pasa si el recurso es del
    que llama, o si tiene alguno de los permisos que gobiernan ese dato.

    Es para los endpoints con require_auth que reciben el employeeId por URL o
    query: sin esto cualquier logueado lee lo de otro cambiando el numero. Se
    compara como texto, igual que ruta_permitida_de_baja, porque el id del
    path llega como int o str segun la ruta; un usuario sin empleado (None)
    nunca es duenio.
    """
    propio = user.get("employeeId")
    if propio is not None and str(propio) == str(employee_id):
        return user
    tiene = user.get("permisos") or set()
    if any(tiene_permiso(tiene, p) for p in permisos):
        return user
    raise HTTPException(
        status_code=403,
        detail="No tenés permiso para acceder a datos de otro empleado.",
    )


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
