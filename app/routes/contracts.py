from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth

router = APIRouter(prefix="/contracts", tags=["Contracts"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/types", dependencies=[Depends(require_any_auth)])
def get_contract_types(db: Session = Depends(get_db)):
    """Get all active contract types."""
    try:
        result = db.execute(text("SELECT id, nombre, [key], descripcion, activo FROM TipoContrato WHERE activo = 1")).mappings().all()
        return {"types": [dict(r) for r in result]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener tipos de contrato: {str(e)}")

@router.post("/types", dependencies=[Depends(require_admin)])
def save_contract_type(data: dict = Body(...), db: Session = Depends(get_db)):
    """Create or update a contract type."""
    nombre = data.get("nombre")
    key = data.get("key")
    descripcion = data.get("descripcion")
    contract_id = data.get("id")

    if not nombre or not key:
        raise HTTPException(status_code=400, detail="Nombre y clave (key) son requeridos")

    try:
        # Check if updating or creating
        if contract_id:
            db.execute(text("""
                UPDATE TipoContrato
                SET nombre = :nombre, [key] = :key, descripcion = :descripcion, activo = 1
                WHERE id = :id
            """), {"nombre": nombre, "key": key, "descripcion": descripcion, "id": contract_id})
        else:
            # Check unique constraint on key
            exists = db.execute(text("SELECT id FROM TipoContrato WHERE [key] = :key"), {"key": key}).fetchone()
            if exists:
                db.execute(text("""
                    UPDATE TipoContrato
                    SET nombre = :nombre, descripcion = :descripcion, activo = 1
                    WHERE [key] = :key
                """), {"nombre": nombre, "descripcion": descripcion, "key": key})
            else:
                db.execute(text("""
                    INSERT INTO TipoContrato (nombre, [key], descripcion, activo)
                    VALUES (:nombre, :key, :descripcion, 1)
                """), {"nombre": nombre, "key": key, "descripcion": descripcion})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar tipo de contrato: {str(e)}")

@router.delete("/types/{contract_id}", dependencies=[Depends(require_admin)])
def delete_contract_type(contract_id: int, db: Session = Depends(get_db)):
    """Soft delete a contract type."""
    try:
        existing = db.execute(text("SELECT id FROM TipoContrato WHERE id = :id"), {"id": contract_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Tipo de contrato no encontrado")

        db.execute(text("UPDATE TipoContrato SET activo = 0 WHERE id = :id"), {"id": contract_id})
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar tipo de contrato: {str(e)}")
