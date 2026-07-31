"""
Router del modulo de asistencia.

GET /asistencia/mi resuelve el empleado desde el token y nunca acepta un
employeeId por parametro: un usuario sin rol de RRHH no puede ver datos ajenos.
"""

from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, get_current_user, require_any_auth, require_roles,
)
from app.database.asistencia import (
    ensure_tables, get_config, get_jornada, jornadas_de, jornadas_incompletas,
    marcar_correccion, saldo_acumulado, tablero, update_config,
)
from app.database.database import SessionLocal
from app.routes.rrhh import ROLE_RRHH
from app.services.asistencia_recalc import recalcular_anio

router = APIRouter(prefix="/asistencia", tags=["Asistencia"])

SOLO_RRHH = Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _rango(desde: str | None, hasta: str | None) -> tuple[date, date]:
    """Sin parametros devuelve el anio en curso."""
    hoy = date.today()
    try:
        d = date.fromisoformat(desde) if desde else date(hoy.year, 1, 1)
        h = date.fromisoformat(hasta) if hasta else hoy
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha invalido, use YYYY-MM-DD")
    if d > h:
        raise HTTPException(status_code=400, detail="'desde' no puede ser posterior a 'hasta'")
    return d, h


@router.get("/tablero", dependencies=[SOLO_RRHH])
def get_tablero(desde: str | None = None, hasta: str | None = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {"desde": d.isoformat(), "hasta": h.isoformat(), "empleados": tablero(db, d, h)}


@router.get("/incompletas", dependencies=[SOLO_RRHH])
def get_incompletas(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"jornadas": jornadas_incompletas(db)}


@router.post("/jornadas/{jornada_id}/correccion", dependencies=[SOLO_RRHH])
def post_correccion_jornada(jornada_id: int, data: dict = Body(...),
                            usuario: dict = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """
    Carga manual de entrada y/o salida. Dispara el recalculo del anio para que
    el saldo del empleado quede al dia sin esperar al job nocturno.
    """
    jornada = get_jornada(db, jornada_id)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")

    def _parsear(clave: str):
        crudo = data.get(clave)
        if crudo in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(crudo))
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"'{clave}' debe ser una fecha-hora ISO valida")

    entrada = _parsear("entrada")
    salida = _parsear("salida")
    if entrada is None and salida is None:
        raise HTTPException(status_code=400,
                            detail="Hay que enviar al menos 'entrada' o 'salida'")
    if entrada is not None and salida is not None and salida <= entrada:
        raise HTTPException(status_code=400,
                            detail="La salida debe ser posterior a la entrada")

    if usuario.get("employeeId") is None:
        raise HTTPException(status_code=403,
                            detail="Tu usuario no tiene legajo vinculado para registrar la correccion")
    corregido_por = int(usuario["employeeId"])
    marcar_correccion(db, jornada_id, entrada, salida,
                      corregido_por, data.get("observacion"))

    fecha = jornada["fecha"]
    anio = fecha.year if isinstance(fecha, date) else fecha.date().year
    recalcular_anio(db, jornada["employeeId"], anio)

    return {"ok": True, "employeeId": jornada["employeeId"], "anio": anio}


@router.get("/empleado/{employee_id}")
def get_empleado(employee_id: int, desde: str | None = None,
                 hasta: str | None = None,
                 usuario: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if usuario["roleId"] not in [ROLE_ADMIN, ROLE_RRHH] and usuario.get("employeeId") != employee_id:
        raise HTTPException(status_code=403, detail="Sin permiso para ver este empleado")
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {
        "employeeId": employee_id,
        "saldoAcumulado": saldo_acumulado(db, employee_id),
        "jornadas": jornadas_de(db, employee_id, d, h),
    }


@router.get("/mi", dependencies=[Depends(require_any_auth)])
def get_mi_asistencia(desde: str | None = None, hasta: str | None = None,
                      usuario: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """
    El empleado solo ve lo propio: el id sale del token, no del request.
    get_current_user devuelve {usuario, roleId, employeeId}; employeeId puede
    ser None si la cuenta no esta vinculada a un legajo.
    """
    ensure_tables(db)
    if usuario.get("employeeId") is None:
        raise HTTPException(status_code=403,
                            detail="Tu usuario no esta vinculado a un legajo")
    fila = db.execute(text(
        "SELECT id FROM Employee WHERE id = :id"
    ), {"id": usuario["employeeId"]}).mappings().first()
    if fila is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    d, h = _rango(desde, hasta)
    employee_id = int(fila["id"])
    return {
        "saldoAcumulado": saldo_acumulado(db, employee_id),
        "jornadas": jornadas_de(db, employee_id, d, h),
    }


@router.get("/config", dependencies=[SOLO_RRHH])
def get_asistencia_config(db: Session = Depends(get_db)):
    ensure_tables(db)
    return get_config(db)


@router.put("/config", dependencies=[SOLO_RRHH])
def put_asistencia_config(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    try:
        tol_entrada = int(data.get("toleranciaEntradaMin"))
        tol_salida = int(data.get("toleranciaSalidaMin"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="toleranciaEntradaMin y toleranciaSalidaMin deben ser enteros")
    if not (0 <= tol_entrada <= 120) or not (0 <= tol_salida <= 120):
        raise HTTPException(status_code=400,
                            detail="Las tolerancias deben estar entre 0 y 120 minutos")
    return update_config(db, tol_entrada, tol_salida)
