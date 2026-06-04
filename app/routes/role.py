from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN
from datetime import datetime

router = APIRouter(prefix="/roles", tags=["Roles"])

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 🟢 GET - Obtener todos los roles
@router.get("/", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def get_all_roles(db: Session = Depends(get_db)):
    query = text("SELECT * FROM Role ORDER BY id ASC")
    result = db.execute(query).fetchall()
    roles = [dict(row._mapping) for row in result]
    return {"roles": roles}


# 🟡 POST - Crear nuevo rol
@router.post("/", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def create_role(role_data: dict, db: Session = Depends(get_db)):
    name = role_data.get("name")
    description = role_data.get("description", "")

    if not name:
        raise HTTPException(status_code=400, detail="El campo 'name' es obligatorio.")

    # Validar que no exista un rol con el mismo nombre
    check_query = text("SELECT * FROM Role WHERE name = :name")
    existing = db.execute(check_query, {"name": name}).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="El rol ya existe.")

    query = text("""
        INSERT INTO Role (name, description, createdAt, updatedAt)
        VALUES (:name, :description, :createdAt, :updatedAt)
    """)
    db.execute(query, {
        "name": name,
        "description": description,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    })
    db.commit()
    return {"message": "Rol creado correctamente", "role": {"name": name, "description": description}}


# 🟠 PUT - Actualizar un rol existente
@router.put("/{role_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def update_role(role_id: int, role_data: dict, db: Session = Depends(get_db)):
    name = role_data.get("name")
    description = role_data.get("description")

    # Verificar que el rol exista
    check_query = text("SELECT * FROM Role WHERE id = :id")
    existing = db.execute(check_query, {"id": role_id}).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Rol no encontrado")

    # Actualizar los campos
    query = text("""
        UPDATE Role
        SET name = COALESCE(:name, name),
            description = COALESCE(:description, description),
            updatedAt = :updatedAt
        WHERE id = :id
    """)
    db.execute(query, {
        "id": role_id,
        "name": name,
        "description": description,
        "updatedAt": datetime.utcnow(),
    })
    db.commit()

    return {"message": "Rol actualizado correctamente", "id": role_id}
