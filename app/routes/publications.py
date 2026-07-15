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


def _notificar_destinatarios(db: Session, publication_id: int, categoria: str, titulo: str, now: datetime) -> None:
    """Inserta un Message para cada empleado alcanzado por los destinos de la publicacion."""
    destinatarios = db.execute(text("""
        SELECT DISTINCT e.id
        FROM Employee e
        INNER JOIN PublicationTarget t ON t.publicationId = :pubId
        WHERE t.scope = 'institucion'
           OR (t.scope = 'departamento' AND t.departmentId = e.departmentId)
           OR (t.scope = 'oficina' AND t.officeId = e.officeId)
    """), {"pubId": publication_id}).mappings().all()

    msg_text = f"Nueva {categoria.lower()}: {titulo}"
    for r in destinatarios:
        db.execute(text("""
            INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
            VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
        """), {"empId": r["id"], "msg": msg_text, "now": now})


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

    es_borrador = 1 if data.get("esBorrador", True) else 0
    if not es_borrador and (fecha_pub is None or fecha_pub <= now):
        _notificar_destinatarios(db, new_id, data.get("categoria"), data.get("titulo").strip(), now)

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


def _targets_de(db: Session, publication_id: int) -> list:
    """Devuelve los destinos de una publicacion."""
    rows = db.execute(text("""
        SELECT scope, departmentId, officeId
        FROM PublicationTarget WHERE publicationId = :id
    """), {"id": publication_id}).mappings().all()
    return [
        {"scope": r["scope"], "departmentId": r["departmentId"], "officeId": r["officeId"]}
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# GET /publications — listado admin (HR/Admin), con filtros opcionales
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", dependencies=[Depends(require_rrhh_auth)])
def list_publications(categoria: Optional[str] = None, estado: Optional[str] = None, db: Session = Depends(get_db)):
    """Lista publicaciones activas con su estado efectivo y sus destinos."""
    ensure_table(db)

    query = "SELECT * FROM Publication WHERE activo = 1"
    params = {}
    if categoria:
        query += " AND categoria = :categoria"
        params["categoria"] = categoria
    query += " ORDER BY createdAt DESC"

    rows = db.execute(text(query), params).mappings().all()
    ahora = datetime.utcnow()

    result = []
    for r in rows:
        est = _estado_efectivo(r, ahora)
        if estado and est != estado:
            continue
        result.append({
            "id": r["id"],
            "titulo": r["titulo"],
            "resumen": r["resumen"],
            "contenido": r["contenido"],
            "categoria": r["categoria"],
            "prioridad": r["prioridad"],
            "estadoMantenimiento": r["estadoMantenimiento"],
            "estado": est,
            "esBorrador": bool(r["esBorrador"]),
            "destacada": bool(r["destacada"]),
            "fijada": bool(r["fijada"]),
            "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
            "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
            "autorEmployeeId": r["autorEmployeeId"],
            "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
            "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            "targets": _targets_de(db, r["id"]),
        })

    return {"publications": result}


# ─────────────────────────────────────────────────────────────────────────────
# GET /publications/feed — feed filtrado del empleado (self-or-admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/feed", dependencies=[Depends(require_any_auth)])
def get_feed(employeeId: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Publicaciones visibles para el empleado: publicadas por fecha y dirigidas
    a el (institucion, su departamento o su oficina)."""
    _check_self_or_admin(employeeId, current_user)

    ensure_table(db)

    empleado = db.execute(text("""
        SELECT departmentId, officeId FROM Employee WHERE id = :id
    """), {"id": employeeId}).mappings().first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    dep_id = empleado["departmentId"]
    off_id = empleado["officeId"]

    now = datetime.utcnow()
    rows = db.execute(text("""
        SELECT DISTINCT p.*
        FROM Publication p
        INNER JOIN PublicationTarget t ON t.publicationId = p.id
        WHERE p.activo = 1
          AND p.esBorrador = 0
          AND (p.fechaPublicacion IS NULL OR p.fechaPublicacion <= :now)
          AND (p.fechaExpiracion IS NULL OR p.fechaExpiracion >= :now)
          AND (
                t.scope = 'institucion'
                OR (t.scope = 'departamento' AND t.departmentId = :depId)
                OR (t.scope = 'oficina' AND t.officeId = :offId)
              )
        ORDER BY p.fijada DESC, p.fechaPublicacion DESC
    """), {"depId": dep_id, "offId": off_id, "now": now}).mappings().all()

    return {
        "publications": [
            {
                "id": r["id"],
                "titulo": r["titulo"],
                "resumen": r["resumen"],
                "contenido": r["contenido"],
                "categoria": r["categoria"],
                "prioridad": r["prioridad"],
                "estadoMantenimiento": r["estadoMantenimiento"],
                "destacada": bool(r["destacada"]),
                "fijada": bool(r["fijada"]),
                "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
                "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /publications/{publication_id} — detalle para edicion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def get_publication(publication_id: int, db: Session = Depends(get_db)):
    """Detalle de una publicacion con sus destinos."""
    ensure_table(db)

    r = db.execute(text("""
        SELECT * FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    return {
        "id": r["id"],
        "titulo": r["titulo"],
        "resumen": r["resumen"],
        "contenido": r["contenido"],
        "categoria": r["categoria"],
        "prioridad": r["prioridad"],
        "estadoMantenimiento": r["estadoMantenimiento"],
        "estado": _estado_efectivo(r, datetime.utcnow()),
        "esBorrador": bool(r["esBorrador"]),
        "destacada": bool(r["destacada"]),
        "fijada": bool(r["fijada"]),
        "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
        "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
        "autorEmployeeId": r["autorEmployeeId"],
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
        "targets": _targets_de(db, r["id"]),
    }
