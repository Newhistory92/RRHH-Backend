"""
Puente con la base institucional.

GET  /obrasocial/usuarios  lista los usuarios de la institucion indicando
                           cuales ya estan vinculados a un empleado de RRHH.
POST /obrasocial/importar  da de alta a los seleccionados sin esperar a que
                           entren por primera vez.

Ambos requieren rol ADMIN: exponen datos personales (documento, telefono,
email) de toda la planta.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth_middleware import ROLE_ADMIN, require_roles
from app.database import obrasocial_usuarios as os_db
from app.database import provisioning as prov
from app.database.database import SessionLocal, SessionLocalObraSocial
from app.services.auth_providers.obrasocial import provisionar

router = APIRouter(prefix="/obrasocial", tags=["ObraSocial"])

SOLO_ADMIN = Depends(require_roles(ROLE_ADMIN))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_obrasocial_db():
    db = SessionLocalObraSocial()
    try:
        yield db
    finally:
        db.close()


def fila_usuario(externo: dict, vinculos: dict[str, int]) -> dict:
    """
    La fila que ve el tablero de RRHH. Nunca incluye claveUsuario: el hash de
    la institucion no tiene por que salir de la capa de autenticacion.
    """
    dni = str(externo.get("numeroDocPersona") or "").strip()
    employee_id = vinculos.get(dni)
    return {
        "idUsuario": str(externo["idUsuario"]),
        "nombreUsuario": externo["nombreUsuario"],
        "anulado": bool(externo["anulado"]),
        "nombre": externo.get("nombrePersona"),
        "apellido": externo.get("apellidoPersona"),
        "dni": dni,
        "email": externo.get("emailPersona"),
        "telefono": externo.get("telefonoPersona"),
        "vinculado": employee_id is not None,
        "employeeId": employee_id,
    }


def importar_usuarios(db: Session, db_os: Session, id_usuarios: list[str]) -> dict:
    """
    Provisiona el lote. Un elemento que falla se registra y el resto sigue:
    abortar todo por un documento faltante obligaria a RRHH a depurar la lista
    a mano antes de cada intento.
    """
    if not id_usuarios:
        raise HTTPException(status_code=400, detail="Falta la lista idUsuarios")

    externos = os_db.buscar_por_ids(db_os, [str(i) for i in id_usuarios])
    importados = 0
    ya_existian = 0
    errores = []

    for externo in externos:
        try:
            if prov.buscar_user(db, externo["nombreUsuario"]) is not None:
                ya_existian += 1
                continue
            provisionar(db, externo)
            importados += 1
        except HTTPException as e:
            db.rollback()
            errores.append({"idUsuario": str(externo["idUsuario"]), "motivo": str(e.detail)})
        except Exception as e:
            db.rollback()
            errores.append({"idUsuario": str(externo["idUsuario"]), "motivo": str(e)})

    return {"importados": importados, "ya_existian": ya_existian, "errores": errores}


@router.get("/usuarios", dependencies=[SOLO_ADMIN])
def get_usuarios(db: Session = Depends(get_db),
                 db_os: Session = Depends(get_obrasocial_db)):
    try:
        externos = os_db.listar(db_os)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error al consultar la base institucional: {e}",
        )

    dnis = [
        str(u["numeroDocPersona"]).strip()
        for u in externos
        if u.get("numeroDocPersona")
    ]
    vinculos = prov.employees_por_dni(db, dnis)
    return {"usuarios": [fila_usuario(u, vinculos) for u in externos]}


@router.get("/diagnostico/{nombre_usuario}", dependencies=[SOLO_ADMIN])
def diagnostico(nombre_usuario: str, db_os: Session = Depends(get_obrasocial_db)):
    """
    Por que un usuario no sale en el tablero. Cada clave `pasa_*` en 0 es una
    condicion del filtro que lo esta dejando afuera.
    """
    fila = os_db.diagnosticar(db_os, nombre_usuario)
    if fila is None:
        raise HTTPException(
            status_code=404,
            detail=f"No existe ningún usuario '{nombre_usuario}' en ObraSocial",
        )
    return fila


@router.post("/importar", dependencies=[SOLO_ADMIN])
async def importar(request: Request, db: Session = Depends(get_db),
                   db_os: Session = Depends(get_obrasocial_db)):
    body = await request.json()
    ids = body.get("idUsuarios")
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Falta la lista idUsuarios")
    return importar_usuarios(db, db_os, ids)
