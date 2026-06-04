from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import json
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN, require_any_auth

router = APIRouter(prefix="/records", tags=["Records"])

CONFIG_FILE = "app/records_config.json"

def get_config():
    if not os.path.exists(CONFIG_FILE):
        return {table: True for table in ALLOWED_TABLES}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Tablas permitidas para este endpoint
ALLOWED_TABLES = [
    "Feedback",
    "SoftSkill",
    "TechnicalSkill",
    "AcademicRecord",
    "WorkExperience",
    "Language",
    "Certification"
]

@router.get("/status", dependencies=[Depends(require_any_auth)])
async def get_tables_status(db: Session = Depends(get_db)):
    # Usar cache del JSON File en vez de depender de tablas con rows vacías
    return get_config()

@router.put("/{table_name}/toggle", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def toggle_table_active(table_name: str, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    new_status = body.get("activo")

    if new_status not in [True, False]:
        raise HTTPException(status_code=400, detail="El valor de 'activo' debe ser true o false")

    if table_name not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail="Tabla no permitida")

    # Guardar en archivo persistente global
    config = get_config()
    config[table_name] = new_status
    save_config(config)

    # También actualizar base de datos existente
    query = text(f"UPDATE {table_name} SET activo = :activo")
    db.execute(query, {"activo": new_status})
    db.commit()

    return {
        "message": f"Campo 'activo' actualizado correctamente en {table_name}",
        "activo": new_status
    }