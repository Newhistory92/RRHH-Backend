"""
Router del modulo de asistencia.

GET /asistencia/mi resuelve el empleado desde el token y nunca acepta un
employeeId por parametro: un usuario sin rol de RRHH no puede ver datos ajenos.
"""

from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, ROLE_RRHH, get_current_user, require_any_auth, require_roles,
)
from app.database.asistencia import (
    biometricos_huerfanos, ensure_tables, get_config, get_jornada,
    jornadas_de, jornadas_incompletas, reset_inicio_modulo,
    saldo_acumulado, tablero, update_config,
)
from app.database.asistencia_auditoria import (
    borrar_correccion, incidencias_abiertas, ultimos_recalculos, upsert_correccion,
)
from app.database.database import SessionLocal
from app.services.asistencia_recalc import recalcular_anio, recalcular_todos

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


@router.get("/biometricos-huerfanos", dependencies=[SOLO_RRHH])
def get_biometricos_huerfanos(db: Session = Depends(get_db)):
    """IDs del reloj con marcaciones recientes que no estan vinculados a ningun empleado."""
    ensure_tables(db)
    return {"huerfanos": biometricos_huerfanos(db)}


@router.post("/reset-inicio", dependencies=[SOLO_RRHH])
def post_reset_inicio(db: Session = Depends(get_db)):
    """
    Limpia jornadas anteriores a hoy y mueve fechaInicioModulo al dia de hoy.
    Permite arrancar de cero sin datos historicos incorrectos.
    """
    ensure_tables(db)
    nueva_fecha = reset_inicio_modulo(db)
    return {"ok": True, "fechaInicioModulo": nueva_fecha.isoformat()}


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
    fecha = jornada["fecha"]
    fecha_date = fecha if isinstance(fecha, date) else fecha.date()
    upsert_correccion(db, jornada["employeeId"], fecha_date, entrada, salida,
                      corregido_por, data.get("observacion"))

    anio = fecha_date.year
    recalcular_anio(db, jornada["employeeId"], anio)

    return {"ok": True, "employeeId": jornada["employeeId"], "anio": anio}


@router.delete("/jornadas/{jornada_id}/correccion", dependencies=[SOLO_RRHH])
def delete_correccion_jornada(jornada_id: int, db: Session = Depends(get_db)):
    """
    Elimina la carga manual del dia. El proximo recalculo restaura los
    extremos que marque el reloj.
    """
    ensure_tables(db)
    jornada = get_jornada(db, jornada_id)
    if not jornada:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")
    fecha = jornada["fecha"]
    fecha = fecha if isinstance(fecha, date) else fecha.date()
    existia = borrar_correccion(db, jornada["employeeId"], fecha)
    if not existia:
        raise HTTPException(status_code=404, detail="No hay correccion para esta jornada")
    anio = fecha.year
    recalcular_anio(db, jornada["employeeId"], anio)
    return {"eliminado": True, "jornada_id": jornada_id, "fecha": fecha.isoformat()}


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

    fecha_inicio = None
    crudo = data.get("fechaInicioModulo")
    if crudo not in (None, ""):
        try:
            fecha_inicio = date.fromisoformat(str(crudo))
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="fechaInicioModulo debe ser YYYY-MM-DD")
        if fecha_inicio > date.today():
            raise HTTPException(status_code=400,
                                detail="fechaInicioModulo no puede ser futura")

    return update_config(db, tol_entrada, tol_salida, fecha_inicio)


@router.post("/recalcular", dependencies=[SOLO_RRHH], status_code=202)
def post_recalcular(background_tasks: BackgroundTasks,
                    data: dict = Body(default={}),
                    usuario: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Recalculo manual. Sin cuerpo recalcula todos los empleados del anio en
    curso en segundo plano (202 Accepted); con employeeId, solo ese (sincrono).
    Es el disparador que faltaba: el job nocturno requiere que el servidor
    este vivo a las 3 AM.
    """
    ensure_tables(db)
    anio = data.get("anio")
    try:
        anio = int(anio) if anio is not None else date.today().year
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'anio' debe ser un entero")
    if not (2000 <= anio <= date.today().year + 1):
        raise HTTPException(status_code=400, detail="'anio' fuera de rango")

    disparado_por = usuario.get("employeeId")
    employee_id = data.get("employeeId")
    if employee_id is not None:
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail="'employeeId' debe ser un entero")
        try:
            filas = recalcular_anio(db, employee_id, anio)
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail=f"Error en recalculo de empleado {employee_id}: {e}")
        return {"employeeId": employee_id, "anio": anio,
                "procesados": 1, "filas": filas, "errores": []}

    # mass recalc path — el background task necesita su propia sesion porque
    # la del request se cierra cuando el handler retorna.
    def _recalcular(anio_: int, disparado_por_: int):
        _db = SessionLocal()
        try:
            recalcular_todos(_db, anio_, origen="manual", disparado_por=disparado_por_)
        finally:
            _db.close()

    background_tasks.add_task(_recalcular, anio, disparado_por)
    return {"anio": anio, "status": "en_proceso",
            "mensaje": "El recalculo se ejecuta en segundo plano. Consulta GET /asistencia/recalculos para ver el resultado."}


@router.get("/incidencias", dependencies=[SOLO_RRHH])
def get_incidencias(tipo: str | None = None, desde: str | None = None,
                    hasta: str | None = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {"desde": d.isoformat(), "hasta": h.isoformat(),
            "incidencias": incidencias_abiertas(db, tipo, d, h)}


@router.get("/recalculos", dependencies=[SOLO_RRHH])
def get_recalculos(limite: int = 50, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not (1 <= limite <= 200):
        raise HTTPException(status_code=400,
                            detail="'limite' debe estar entre 1 y 200")
    return {"recalculos": ultimos_recalculos(db, limite)}
