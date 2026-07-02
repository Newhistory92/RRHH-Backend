from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth

router = APIRouter(prefix="/professions", tags=["Professions"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", dependencies=[Depends(require_any_auth)])
def get_professions(db: Session = Depends(get_db)):
    """Get all active professions."""
    try:
        result = db.execute(text("SELECT id, nombre, descripcion, activo FROM Profession WHERE activo = 1")).mappings().all()
        return {"professions": [dict(r) for r in result]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener profesiones: {str(e)}")

@router.post("", dependencies=[Depends(require_admin)])
def save_profession(data: dict = Body(...), db: Session = Depends(get_db)):
    """Create or update a profession."""
    nombre = data.get("nombre")
    descripcion = data.get("descripcion")
    profession_id = data.get("id")

    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre de la profesión es requerido")

    try:
        if profession_id:
            db.execute(text("""
                UPDATE Profession
                SET nombre = :nombre, descripcion = :descripcion, activo = 1
                WHERE id = :id
            """), {"nombre": nombre, "descripcion": descripcion, "id": profession_id})
        else:
            exists = db.execute(text("SELECT id FROM Profession WHERE nombre = :nombre"), {"nombre": nombre}).fetchone()
            if exists:
                db.execute(text("""
                    UPDATE Profession
                    SET descripcion = :descripcion, activo = 1
                    WHERE nombre = :nombre
                """), {"nombre": nombre, "descripcion": descripcion})
            else:
                db.execute(text("""
                    INSERT INTO Profession (nombre, descripcion, activo)
                    VALUES (:nombre, :descripcion, 1)
                """), {"nombre": nombre, "descripcion": descripcion})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar profesión: {str(e)}")

@router.delete("/{profession_id}", dependencies=[Depends(require_admin)])
def delete_profession(profession_id: int, db: Session = Depends(get_db)):
    """Soft delete a profession."""
    try:
        existing = db.execute(text("SELECT id FROM Profession WHERE id = :id"), {"id": profession_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Profesión no encontrada")

        db.execute(text("UPDATE Profession SET activo = 0 WHERE id = :id"), {"id": profession_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar profesión: {str(e)}")
