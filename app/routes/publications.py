"""
Router /publications -- nucleo de publicaciones del Portal Institucional
(subsistema 1). Autoria (HR/Admin) + feed filtrado del empleado.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.publications import (
    ensure_table,
    VALID_CATEGORIAS,
    VALID_PRIORIDADES,
    VALID_ESTADOS_MANTENIMIENTO,
    VALID_SCOPES,
    CATEGORIA_AVISO_IMPORTANTE,
    CATEGORIA_MANTENIMIENTO,
)

router = APIRouter(prefix="/publications", tags=["Publications"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _check_self_or_admin(employee_id: int, current_user: dict) -> None:
    """Evita que un empleado lea el feed de otro."""
    if employee_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenes permiso para acceder a esta informacion.")


def _estado_efectivo(pub, ahora: datetime) -> str:
    """Calcula el estado efectivo de una publicacion a partir de sus fechas."""
    if pub["esBorrador"]:
        return "Borrador"
    fp = pub["fechaPublicacion"]
    fe = pub["fechaExpiracion"]
    if fp and fp > ahora:
        return "Programada"
    if fe is None or fe >= ahora:
        return "Publicada"
    return "Archivada"


def _parse_dt(value) -> Optional[datetime]:
    """Convierte un ISO string a datetime; devuelve None si es falsy."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+00:00", ""))


def _validar_payload(data: dict) -> tuple:
    """Valida el body de crear/editar. Devuelve (fecha_pub, fecha_exp, fijada, targets).
    Lanza HTTPException 400 ante cualquier dato invalido."""
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(status_code=400, detail="El titulo es obligatorio")

    categoria = data.get("categoria")
    if categoria not in VALID_CATEGORIAS:
        raise HTTPException(status_code=400, detail=f"categoria debe ser una de: {sorted(VALID_CATEGORIAS)}")

    prioridad = data.get("prioridad") or "Normal"
    if prioridad not in VALID_PRIORIDADES:
        raise HTTPException(status_code=400, detail=f"prioridad debe ser una de: {sorted(VALID_PRIORIDADES)}")

    estado_mant = data.get("estadoMantenimiento")
    if estado_mant is not None:
        if categoria != CATEGORIA_MANTENIMIENTO:
            raise HTTPException(status_code=400, detail="estadoMantenimiento solo aplica a la categoria Mantenimiento y Reparaciones")
        if estado_mant not in VALID_ESTADOS_MANTENIMIENTO:
            raise HTTPException(status_code=400, detail=f"estadoMantenimiento debe ser uno de: {sorted(VALID_ESTADOS_MANTENIMIENTO)}")

    targets = data.get("targets") or []
    if not targets:
        raise HTTPException(status_code=400, detail="Debe indicar al menos un destino")
    for t in targets:
        scope = t.get("scope")
        if scope not in VALID_SCOPES:
            raise HTTPException(status_code=400, detail=f"scope debe ser uno de: {sorted(VALID_SCOPES)}")
        if scope == "departamento" and not t.get("departmentId"):
            raise HTTPException(status_code=400, detail="scope 'departamento' requiere departmentId")
        if scope == "oficina" and not t.get("officeId"):
            raise HTTPException(status_code=400, detail="scope 'oficina' requiere officeId")

    fecha_pub = _parse_dt(data.get("fechaPublicacion"))
    fecha_exp = _parse_dt(data.get("fechaExpiracion"))
    if fecha_pub and fecha_exp and fecha_exp < fecha_pub:
        raise HTTPException(status_code=400, detail="fechaExpiracion no puede ser anterior a fechaPublicacion")

    # Aviso Importante: fijada por defecto True si no viene explicito
    fijada = data.get("fijada")
    if fijada is None:
        fijada = categoria == CATEGORIA_AVISO_IMPORTANTE

    return fecha_pub, fecha_exp, bool(fijada), targets


def _insertar_targets(db: Session, publication_id: int, targets: list) -> None:
    """Inserta las filas de PublicationTarget para una publicacion."""
    for t in targets:
        db.execute(text("""
            INSERT INTO PublicationTarget (publicationId, scope, departmentId, officeId)
            VALUES (:pid, :scope, :departmentId, :officeId)
        """), {
            "pid": publication_id,
            "scope": t.get("scope"),
            "departmentId": t.get("departmentId") if t.get("scope") == "departamento" else None,
            "officeId": t.get("officeId") if t.get("scope") == "oficina" else None,
        })


# ─────────────────────────────────────────────────────────────────────────────
# POST /publications — crear publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_rrhh_auth)])
def create_publication(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea una publicacion con sus destinos, en una transaccion."""
    fecha_pub, fecha_exp, fijada, targets = _validar_payload(data)

    ensure_table(db)

    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO Publication
            (titulo, resumen, contenido, categoria, prioridad, estadoMantenimiento,
             esBorrador, destacada, fijada, fechaPublicacion, fechaExpiracion,
             autorEmployeeId, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES
            (:titulo, :resumen, :contenido, :categoria, :prioridad, :estadoMantenimiento,
             :esBorrador, :destacada, :fijada, :fechaPublicacion, :fechaExpiracion,
             :autorEmployeeId, 1, :now, :now)
    """), {
        "titulo": data.get("titulo").strip(),
        "resumen": data.get("resumen"),
        "contenido": data.get("contenido"),
        "categoria": data.get("categoria"),
        "prioridad": data.get("prioridad") or "Normal",
        "estadoMantenimiento": data.get("estadoMantenimiento"),
        "esBorrador": 1 if data.get("esBorrador", True) else 0,
        "destacada": 1 if data.get("destacada") else 0,
        "fijada": 1 if fijada else 0,
        "fechaPublicacion": fecha_pub,
        "fechaExpiracion": fecha_exp,
        "autorEmployeeId": data.get("autorEmployeeId"),
        "now": now,
    })
    new_id = result.fetchone()[0]

    _insertar_targets(db, new_id, targets)

    db.commit()
    return {"message": "Publicacion creada", "id": new_id}


# ─────────────────────────────────────────────────────────────────────────────
# PUT /publications/{publication_id} — editar publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def update_publication(publication_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Edita una publicacion y reescribe su set de destinos, en una transaccion."""
    fecha_pub, fecha_exp, fijada, targets = _validar_payload(data)

    ensure_table(db)

    existing = db.execute(text("""
        SELECT id FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE Publication
        SET titulo = :titulo, resumen = :resumen, contenido = :contenido,
            categoria = :categoria, prioridad = :prioridad, estadoMantenimiento = :estadoMantenimiento,
            esBorrador = :esBorrador, destacada = :destacada, fijada = :fijada,
            fechaPublicacion = :fechaPublicacion, fechaExpiracion = :fechaExpiracion,
            updatedAt = :now
        WHERE id = :id
    """), {
        "titulo": data.get("titulo").strip(),
        "resumen": data.get("resumen"),
        "contenido": data.get("contenido"),
        "categoria": data.get("categoria"),
        "prioridad": data.get("prioridad") or "Normal",
        "estadoMantenimiento": data.get("estadoMantenimiento"),
        "esBorrador": 1 if data.get("esBorrador", True) else 0,
        "destacada": 1 if data.get("destacada") else 0,
        "fijada": 1 if fijada else 0,
        "fechaPublicacion": fecha_pub,
        "fechaExpiracion": fecha_exp,
        "now": now,
        "id": publication_id,
    })

    db.execute(text("DELETE FROM PublicationTarget WHERE publicationId = :id"), {"id": publication_id})
    _insertar_targets(db, publication_id, targets)

    db.commit()
    return {"message": "Publicacion actualizada", "id": publication_id}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /publications/{publication_id} — soft-delete (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def delete_publication(publication_id: int, db: Session = Depends(get_db)):
    """Baja logica de una publicacion (activo=0)."""
    ensure_table(db)

    existing = db.execute(text("""
        SELECT id FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    db.execute(text("""
        UPDATE Publication SET activo = 0, updatedAt = :now WHERE id = :id
    """), {"now": datetime.utcnow(), "id": publication_id})
    db.commit()
    return {"message": "Publicacion eliminada"}
