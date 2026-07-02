from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth

router = APIRouter(prefix="/schedules", tags=["Schedules"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/regimes", dependencies=[Depends(require_any_auth)])
def get_schedules_regimes(db: Session = Depends(get_db)):
    """Get all work regimes (jornadas and horarios)."""
    try:
        jornadas = db.execute(text("SELECT id, nombre, horasDia FROM JornadaLaboral")).mappings().all()
        horarios = db.execute(text("SELECT id, horaInicio, horaFin, horasTrabajo FROM Horario")).mappings().all()
        return {
            "jornadas": [dict(j) for j in jornadas],
            "horarios": [dict(h) for h in horarios]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener regímenes horarios: {str(e)}")

@router.post("/jornadas", dependencies=[Depends(require_admin)])
def save_jornada(data: dict = Body(...), db: Session = Depends(get_db)):
    """Create or update a JornadaLaboral."""
    nombre = data.get("nombre")
    horas_dia = data.get("horasDia")
    jornada_id = data.get("id")

    if not nombre or horas_dia is None:
        raise HTTPException(status_code=400, detail="Nombre y horas al día son requeridos")

    try:
        if jornada_id:
            db.execute(text("""
                UPDATE JornadaLaboral
                SET nombre = :nombre, horasDia = :horasDia
                WHERE id = :id
            """), {"nombre": nombre, "horasDia": float(horas_dia), "id": jornada_id})
        else:
            db.execute(text("""
                INSERT INTO JornadaLaboral (nombre, horasDia)
                VALUES (:nombre, :horasDia)
            """), {"nombre": nombre, "horasDia": float(horas_dia)})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar jornada laboral: {str(e)}")

@router.delete("/jornadas/{jornada_id}", dependencies=[Depends(require_admin)])
def delete_jornada(jornada_id: int, db: Session = Depends(get_db)):
    """Delete a JornadaLaboral."""
    try:
        db.execute(text("DELETE FROM JornadaLaboral WHERE id = :id"), {"id": jornada_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar jornada laboral: {str(e)}")

@router.post("/horarios", dependencies=[Depends(require_admin)])
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

@router.delete("/horarios/{horario_id}", dependencies=[Depends(require_admin)])
def delete_horario(horario_id: int, db: Session = Depends(get_db)):
    """Delete a Horario template."""
    try:
        db.execute(text("DELETE FROM Horario WHERE id = :id"), {"id": horario_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar horario: {str(e)}")
