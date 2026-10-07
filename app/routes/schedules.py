from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.database.asistencia import ensure_tables as ensure_asistencia
from app.services.asistencia_recalc import recalcular_jornada
from app.auth_middleware import require_auth, require_permission

import logging

log = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["Schedules"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# El tope no es una regla de negocio sino el atajo contra el error de tipeo,
# que aca cuesta caro: cargar 120 en vez de 12 regala diez veces el cupo y no
# lo nota nadie. 2000 h es mas que un anio laboral completo.
CUPO_PERMISO_MAX_HORAS = 2000.0


def _validar_cupo(valor) -> float:
    """Normaliza horasPermisoAnual a float, o 400 si no tiene sentido."""
    if valor is None:
        return 0.0
    try:
        cupo = float(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="horasPermisoAnual debe ser un numero")
    if cupo < 0:
        raise HTTPException(status_code=400,
                            detail="horasPermisoAnual no puede ser negativo")
    if cupo > CUPO_PERMISO_MAX_HORAS:
        raise HTTPException(
            status_code=400,
            detail=f"horasPermisoAnual no puede superar {int(CUPO_PERMISO_MAX_HORAS)} horas")
    return cupo

@router.get("/regimes", dependencies=[Depends(require_auth)])
def get_schedules_regimes(db: Session = Depends(get_db)):
    """Get all work regimes (jornadas and horarios)."""
    # La columna del cupo la crea ensure_tables del modulo de asistencia: este
    # router puede ser el primero que la toque en una base recien migrada.
    ensure_asistencia(db)
    try:
        jornadas = db.execute(text(
            "SELECT id, nombre, horasDia, horasPermisoAnual FROM JornadaLaboral"
        )).mappings().all()
        horarios = db.execute(text("SELECT id, horaInicio, horaFin, horasTrabajo FROM Horario")).mappings().all()
        return {
            "jornadas": [
                {**dict(j), "horasPermisoAnual": float(j["horasPermisoAnual"] or 0)}
                for j in jornadas
            ],
            "horarios": [dict(h) for h in horarios]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener regímenes horarios: {str(e)}")

@router.post("/jornadas", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def save_jornada(background_tasks: BackgroundTasks, data: dict = Body(...),
                 db: Session = Depends(get_db)):
    """
    Create or update a JornadaLaboral.

    Cambiar el cupo de permisos obliga a recalcular el anio de todos los
    empleados de esta jornada, porque el banco se consume en orden
    cronologico. Va en segundo plano: el cupo se edita rara vez y la pantalla
    de configuracion no puede quedarse colgada esperando a la nomina entera.
    """
    ensure_asistencia(db)
    nombre = data.get("nombre")
    horas_dia = data.get("horasDia")
    jornada_id = data.get("id")

    if not nombre or horas_dia is None:
        raise HTTPException(status_code=400, detail="Nombre y horas al día son requeridos")

    cupo = _validar_cupo(data.get("horasPermisoAnual"))

    try:
        if jornada_id:
            # Se lee el cupo anterior antes de escribir: si no cambio, no hay
            # nada que recalcular y un renombre no dispara una pasada masiva
            # al vacio.
            previo = db.execute(text(
                "SELECT horasPermisoAnual FROM JornadaLaboral WHERE id = :id"
            ), {"id": jornada_id}).mappings().first()
            cupo_previo = float(previo["horasPermisoAnual"] or 0) if previo else None

            db.execute(text("""
                UPDATE JornadaLaboral
                SET nombre = :nombre, horasDia = :horasDia,
                    horasPermisoAnual = :cupo
                WHERE id = :id
            """), {"nombre": nombre, "horasDia": float(horas_dia),
                   "cupo": cupo, "id": jornada_id})
            db.commit()

            if cupo_previo is not None and cupo_previo != cupo:
                # El background task necesita su propia sesion porque la del
                # request se cierra cuando el handler retorna.
                def _recalcular(jornada_: int, anio_: int):
                    _db = SessionLocal()
                    try:
                        recalcular_jornada(_db, jornada_, anio_)
                    except Exception as e:
                        log.warning("Recalculo por cambio de cupo fallido en jornada %s: %s",
                                    jornada_, e)
                    finally:
                        _db.close()

                from datetime import date as _date
                background_tasks.add_task(_recalcular, int(jornada_id), _date.today().year)
                return {"success": True, "recalculo": "en_proceso"}
        else:
            # Una jornada nueva todavia no tiene empleados asignados: no hay
            # nada que recalcular.
            db.execute(text("""
                INSERT INTO JornadaLaboral (nombre, horasDia, horasPermisoAnual)
                VALUES (:nombre, :horasDia, :cupo)
            """), {"nombre": nombre, "horasDia": float(horas_dia), "cupo": cupo})
            db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar jornada laboral: {str(e)}")

@router.delete("/jornadas/{jornada_id}", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def delete_jornada(jornada_id: int, db: Session = Depends(get_db)):
    """Delete a JornadaLaboral."""
    try:
        db.execute(text("DELETE FROM JornadaLaboral WHERE id = :id"), {"id": jornada_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar jornada laboral: {str(e)}")

@router.post("/horarios", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def save_horario(data: dict = Body(...), db: Session = Depends(get_db)):
    """Create or update a Horario template."""
    hora_inicio = data.get("horaInicio")
    hora_fin = data.get("horaFin")
    horario_id = data.get("id")

    if hora_inicio is None or hora_fin is None:
        raise HTTPException(status_code=400, detail="Hora de inicio y fin son requeridas")

    try:
        hora_inicio = float(hora_inicio)
        hora_fin = float(hora_fin)
        horas_trabajo = hora_fin - hora_inicio

        if horas_trabajo <= 0:
            raise HTTPException(status_code=400, detail="Hora de fin debe ser mayor a hora de inicio")

        if horario_id:
            db.execute(text("""
                UPDATE Horario
                SET horaInicio = :horaInicio, horaFin = :horaFin, horasTrabajo = :horasTrabajo, updatedAt = GETDATE()
                WHERE id = :id
            """), {"horaInicio": hora_inicio, "horaFin": hora_fin, "horasTrabajo": horas_trabajo, "id": horario_id})
        else:
            db.execute(text("""
                INSERT INTO Horario (horaInicio, horaFin, horasTrabajo, createdAt, updatedAt)
                VALUES (:horaInicio, :horaFin, :horasTrabajo, GETDATE(), GETDATE())
            """), {"horaInicio": hora_inicio, "horaFin": hora_fin, "horasTrabajo": horas_trabajo})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar horario: {str(e)}")

@router.delete("/horarios/{horario_id}", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def delete_horario(horario_id: int, db: Session = Depends(get_db)):
    """Delete a Horario template."""
    try:
        db.execute(text("DELETE FROM Horario WHERE id = :id"), {"id": horario_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar horario: {str(e)}")
