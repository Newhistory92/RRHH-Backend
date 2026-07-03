"""
Router /reubicacion -- Solicitud de cambio de oficina/departamento
(subsistema 1 del modulo de Reubicacion Inteligente).
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _check_self_or_admin(employee_id: int, current_user: dict) -> None:
    """Evita que un empleado cree o lea solicitudes en nombre de otro."""
    if employee_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenes permiso para acceder a esta informacion.")


# ─────────────────────────────────────────────────────────────────────────────
# POST /reubicacion/request
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/request", dependencies=[Depends(require_any_auth)])
def create_solicitud(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Crea una solicitud de reubicacion. Nace siempre en estado 'Pendiente'.

    Body:
    {
      "employeeId": 5,
      "tipo": "Cambio de oficina",
      "motivo": "Texto libre explicando el motivo"
    }
    """
    employee_id = data.get("employeeId")
    tipo = data.get("tipo")
    motivo = data.get("motivo")

    if not employee_id or not tipo or not motivo or not str(motivo).strip():
        raise HTTPException(status_code=400, detail="Faltan campos requeridos")

    if tipo not in VALID_TIPOS:
        raise HTTPException(status_code=400, detail=f"tipo debe ser uno de: {VALID_TIPOS}")

    _check_self_or_admin(employee_id, current_user)

    ensure_table(db)

    empleado = db.execute(text("""
        SELECT officeId, departmentId FROM Employee WHERE id = :id
    """), {"id": employee_id}).mappings().first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO SolicitudReubicacion
            (employeeId, tipo, motivo, estado, officeIdActual, departmentIdActual, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES
            (:employeeId, :tipo, :motivo, 'Pendiente', :officeId, :departmentId, :now, :now)
    """), {
        "employeeId": employee_id, "tipo": tipo, "motivo": motivo,
        "officeId": empleado["officeId"], "departmentId": empleado["departmentId"],
        "now": now,
    })
    new_id = result.fetchone()[0]
    db.commit()

    return {"message": "Solicitud creada correctamente", "id": new_id}


# ─────────────────────────────────────────────────────────────────────────────
# GET /reubicacion/mis-solicitudes/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/mis-solicitudes/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_mis_solicitudes(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Historial de solicitudes de reubicacion del empleado, mas recientes primero."""
    _check_self_or_admin(employee_id, current_user)

    ensure_table(db)

    rows = db.execute(text("""
        SELECT id, employeeId, tipo, motivo, estado, officeIdActual, departmentIdActual, createdAt, updatedAt
        FROM SolicitudReubicacion
        WHERE employeeId = :employeeId
        ORDER BY createdAt DESC
    """), {"employeeId": employee_id}).mappings().all()

    return {
        "solicitudes": [
            {
                "id": r["id"],
                "employeeId": r["employeeId"],
                "tipo": r["tipo"],
                "motivo": r["motivo"],
                "estado": r["estado"],
                "officeIdActual": r["officeIdActual"],
                "departmentIdActual": r["departmentIdActual"],
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
                "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            }
            for r in rows
        ]
    }
