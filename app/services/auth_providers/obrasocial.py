"""
Proveedor institucional: valida contra la base ObraSocial y provisiona el
usuario local en el primer login.

Tres caminos, segun el estado del usuario en la base de RRHH:

  1. Existe con origen 'local'       -> se valida solo local, ObraSocial ni
                                        se consulta. Es el admin creado a mano.
  2. Existe con origen 'obrasocial'  -> se verifica la baja y se sincroniza el
                                        hash, despues se valida local.
  3. No existe                       -> se valida contra ObraSocial y se
                                        provisiona Employee y [User].

Los dos sistemas hashean con bcrypt en el mismo formato, asi que el hash se
copia tal cual y el usuario nunca resetea su contrasena.

Las dos bases viven en el mismo servidor: si ObraSocial cae, la base de RRHH
cae tambien y no hay login posible por ningun camino. Por eso no hay ningun
fallback ni modo degradado -- seria codigo muerto.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import obrasocial_usuarios as os_db
from app.database import provisioning as prov
from app.database.database import SessionLocalObraSocial
from app.services.auth_providers.base import ResultadoAuth
from app.services.auth_providers.local import verificar_password
from app.services.auth_providers.mapeo import persona_a_employee, placeholder_email

log = logging.getLogger(__name__)


def provisionar(db: Session, externo: dict) -> tuple:
    """
    Crea (o reutiliza) el Employee y crea el [User] para una persona de
    ObraSocial. Retorna (employee_id, user_id).

    employee_id es siempre un int; user_id sigue el tipo de [User].id, que en
    este esquema es un GUID.

    No valida contrasena: el login la valida antes de llamar, y la importacion
    desde RRHH no la necesita.
    """
    nombre_usuario = externo["nombreUsuario"]

    try:
        datos = persona_a_employee(externo, nombre_usuario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    existente = prov.buscar_employee_por_dni(db, datos["dni"])
    if existente is not None:
        employee_id = existente["id"]
        ya_vinculado = prov.user_de_employee(db, employee_id)
        if ya_vinculado is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El DNI {datos['dni']} ya está vinculado al usuario "
                    f"'{ya_vinculado['usuario']}'. Requiere revisión manual."
                ),
            )
    else:
        # Employee.email es unico. Si el de la persona ya lo usa otro empleado
        # se cae al placeholder, que queda visible para que RRHH lo corrija.
        if prov.email_ocupado(db, datos["email"]):
            datos["email"] = placeholder_email(nombre_usuario)
        employee_id = prov.crear_employee(db, datos)

    user_id = prov.crear_user(
        db,
        usuario=nombre_usuario,
        email=datos["email"],
        password_hash=externo["claveUsuario"],
        employee_id=employee_id,
        origen=prov.ORIGEN_OBRASOCIAL,
    )
    return employee_id, user_id


class ObraSocialAuthProvider:
    def __init__(self, session_factory=SessionLocalObraSocial):
        # Inyectable para poder probar sin la base institucional.
        self._session_factory = session_factory

    def autenticar(self, db: Session, usuario: str, password: str) -> ResultadoAuth:
        local = prov.buscar_user(db, usuario)

        if local is not None and local["origen"] == prov.ORIGEN_LOCAL:
            return self._camino_local(local, password)

        db_os = self._session_factory()
        try:
            externo = os_db.buscar_por_nombre(db_os, usuario)
        finally:
            db_os.close()

        if externo is None:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        if externo["anulado"]:
            raise HTTPException(
                status_code=403, detail="Acceso denegado por la institución"
            )

        if local is not None:
            return self._camino_provisionado(db, local, externo, password)
        return self._camino_primer_login(db, externo, password)

    def _camino_local(self, local: dict, password: str) -> ResultadoAuth:
        if not local["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")
        verificar_password(password, local["password"])
        return _a_resultado(local)

    def _camino_provisionado(self, db: Session, local: dict, externo: dict,
                             password: str) -> ResultadoAuth:
        if not local["activo"]:
            raise HTTPException(status_code=403, detail="Usuario inhabilitado")

        # El usuario pudo cambiar su clave en ObraSocial. La consulta de arriba
        # ya trajo el hash vigente, asi que sincronizarlo no cuesta un viaje mas.
        hash_vigente = externo["claveUsuario"]
        if hash_vigente != local["password"]:
            prov.actualizar_password(db, local["id"], hash_vigente)
            local = {**local, "password": hash_vigente}

        verificar_password(password, local["password"])
        return _a_resultado(local)

    def _camino_primer_login(self, db: Session, externo: dict,
                             password: str) -> ResultadoAuth:
        # Validar antes de provisionar: una contrasena incorrecta no debe
        # dejar un Employee huerfano en la base.
        verificar_password(password, externo["claveUsuario"])
        try:
            employee_id, _ = provisionar(db, externo)
        except HTTPException:
            raise
        except Exception as e:
            # Un fallo de la base al dar el alta no es culpa de la credencial.
            # Sin este traductor sale como 500 con stacktrace y el usuario no
            # se entera de que su login estuvo bien y lo que fallo fue el alta.
            db.rollback()
            log.exception("Fallo el alta automatica de '%s'", externo["nombreUsuario"])
            raise HTTPException(
                status_code=500,
                detail=(
                    "Tus credenciales son correctas, pero falló el alta "
                    f"automática de tu usuario en RRHH: {e}"
                ),
            ) from e
        return ResultadoAuth(
            usuario=externo["nombreUsuario"],
            roleId=prov.ROLE_USER,
            employeeId=employee_id,
        )


def _a_resultado(local: dict) -> ResultadoAuth:
    return ResultadoAuth(
        usuario=local["usuario"],
        roleId=local["roleId"],
        employeeId=local["employeeId"],
    )
