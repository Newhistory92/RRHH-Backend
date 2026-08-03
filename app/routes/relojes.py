"""
Router de relojes biometricos: estado de sincronizacion, sync manual, carga
inicial y consulta de marcaciones.

Todas las operaciones contra los equipos son de solo lectura (ver la allowlist
en app/services/isapi_client.py).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, get_current_user, require_admin, require_any_auth,
)
from app.database.database import SessionLocal
from app.database.marcaciones import (
    ensure_tables, estado_relojes, marcaciones_de,
)
from app.services.isapi_client import (
    ISAPIError, buscar_usuario, relojes_configurados,
)
from app.services.reloj_sync import DIAS_CARGA_INICIAL, sincronizar_todos

router = APIRouter(tags=["Relojes biometricos"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/relojes/estado", dependencies=[Depends(require_admin)])
def get_estado(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"configurados": relojes_configurados(), "relojes": estado_relojes(db)}


@router.post("/relojes/sync", dependencies=[Depends(require_admin)])
def post_sync(db: Session = Depends(get_db)):
    """Sincronizacion manual de la ventana normal."""
    return {"resultados": sincronizar_todos(db)}


@router.post("/relojes/carga-inicial", dependencies=[Depends(require_admin)])
def post_carga_inicial(db: Session = Depends(get_db)):
    """
    Trae el ultimo mes. Idempotente por la unicidad (relojIp, serialNo):
    repetirla no duplica marcaciones.
    """
    hasta = datetime.now()
    desde = hasta - timedelta(days=DIAS_CARGA_INICIAL)
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resultados": sincronizar_todos(db, desde=desde, hasta=hasta),
    }


@router.post("/relojes/resincronizar", dependencies=[Depends(require_admin)])
def post_resincronizar(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Re-lee un rango historico iterando de a un dia.

    Sirve para recuperar periodos que la carga inicial trajo truncados: los
    eventos siguen en los equipos y la unicidad (relojIp, serialNo) hace que
    reprocesar sea inofensivo.
    """
    try:
        desde = datetime.fromisoformat(str(data["desde"]))
        hasta = datetime.fromisoformat(str(data["hasta"]))
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Hay que enviar 'desde' y 'hasta' en formato ISO (YYYY-MM-DD)",
        )
    if desde >= hasta:
        raise HTTPException(status_code=400,
                            detail="'desde' debe ser anterior a 'hasta'")
    if (hasta - desde).days > 90:
        raise HTTPException(
            status_code=400,
            detail="El rango no puede superar los 90 dias: partilo en tramos",
        )
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resultados": sincronizar_todos(db, desde=desde, hasta=hasta),
    }


@router.get("/relojes/usuario/{biometrico_id}", dependencies=[Depends(require_admin)])
def get_usuario_reloj(biometrico_id: str):
    """
    Nombre que tienen los relojes cargado para ese employeeNo. Lo usa el perfil
    para que RRHH confirme el ID antes de guardarlo.
    """
    encontrados = []
    errores = []
    for ip in relojes_configurados():
        try:
            u = buscar_usuario(ip, biometrico_id)
            if u:
                encontrados.append({"relojIp": ip, "nombre": u.get("name")})
        except ISAPIError as e:
            errores.append({"relojIp": ip, "error": str(e)})

    return {
        "biometricoId": biometrico_id,
        "encontrado": len(encontrados) > 0,
        "nombre": encontrados[0]["nombre"] if encontrados else None,
        "relojes": encontrados,
        "errores": errores,
    }


@router.get("/marcaciones/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_marcaciones(employee_id: int, desde: str | None = None, hasta: str | None = None,
                    db: Session = Depends(get_db),
                    current_user: dict = Depends(get_current_user)):
    """
    Marcaciones de un empleado. Un ROLE_USER accede solo a las propias.
    """
    if current_user["roleId"] != ROLE_ADMIN and current_user.get("employeeId") != employee_id:
        raise HTTPException(status_code=403, detail="No tenes permiso para ver estas marcaciones")

    ensure_tables(db)
    fila = db.execute(text(
        "SELECT biometricoId FROM Employee WHERE id = :id"
    ), {"id": employee_id}).mappings().first()
    if not fila:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    if not fila["biometricoId"]:
        return {"biometricoId": None, "marcaciones": []}

    hasta_dt = datetime.fromisoformat(hasta) if hasta else datetime.now()
    desde_dt = datetime.fromisoformat(desde) if desde else hasta_dt - timedelta(days=30)

    return {
        "biometricoId": fila["biometricoId"],
        "desde": desde_dt.isoformat(),
        "hasta": hasta_dt.isoformat(),
        "marcaciones": marcaciones_de(db, fila["biometricoId"], desde_dt, hasta_dt),
    }
