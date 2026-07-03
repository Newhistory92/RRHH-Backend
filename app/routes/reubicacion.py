"""
Router /reubicacion -- Solicitud de cambio de oficina/departamento
(subsistema 1 del modulo de Reubicacion Inteligente).
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


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


# ─────────────────────────────────────────────────────────────────────────────
# GET /reubicacion/solicitudes — tablero de RRHH
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/solicitudes", dependencies=[Depends(require_rrhh_auth)])
def get_solicitudes(
    estado: Optional[str] = None,
    officeId: Optional[int] = None,
    departmentId: Optional[int] = None,
    fechaDesde: Optional[str] = None,
    fechaHasta: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Lista todas las solicitudes de reubicacion, con filtros opcionales."""
    ensure_table(db)

    query = """
        SELECT
            sr.id, sr.employeeId, e.name AS employeeName,
            sr.tipo, sr.motivo, sr.estado, sr.observacion,
            sr.officeIdActual, o.nombre AS officeName,
            sr.departmentIdActual, d.nombre AS departmentName,
            sr.createdAt, sr.updatedAt
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        LEFT JOIN Office o ON o.id = sr.officeIdActual
        LEFT JOIN Department d ON d.id = sr.departmentIdActual
        WHERE 1=1
    """
    params = {}
    if estado:
        query += " AND sr.estado = :estado"
        params["estado"] = estado
    if officeId:
        query += " AND sr.officeIdActual = :officeId"
        params["officeId"] = officeId
    if departmentId:
        query += " AND sr.departmentIdActual = :departmentId"
        params["departmentId"] = departmentId
    if fechaDesde:
        query += " AND sr.createdAt >= :fechaDesde"
        params["fechaDesde"] = fechaDesde
    if fechaHasta:
        query += " AND sr.createdAt <= :fechaHasta"
        params["fechaHasta"] = f"{fechaHasta} 23:59:59"

    query += " ORDER BY sr.createdAt DESC"

    rows = db.execute(text(query), params).mappings().all()

    return {
        "solicitudes": [
            {
                "id": r["id"],
                "employeeId": r["employeeId"],
                "employeeName": r["employeeName"],
                "tipo": r["tipo"],
                "motivo": r["motivo"],
                "estado": r["estado"],
                "observacion": r["observacion"],
                "officeIdActual": r["officeIdActual"],
                "officeName": r["officeName"],
                "departmentIdActual": r["departmentIdActual"],
                "departmentName": r["departmentName"],
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
                "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/estado — aprobar/rechazar
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/estado", dependencies=[Depends(require_rrhh_auth)])
def update_estado(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Aprueba o rechaza una solicitud de reubicacion, notificando al empleado."""
    estado = data.get("estado")
    observacion = data.get("observacion")

    if estado not in ("Aprobada", "Rechazada"):
        raise HTTPException(status_code=400, detail="estado debe ser 'Aprobada' o 'Rechazada'")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id, employeeId, tipo FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = :estado, observacion = :observacion, updatedAt = :now
        WHERE id = :id
    """), {"estado": estado, "observacion": observacion, "now": now, "id": solicitud_id})

    msg_text = f"Tu solicitud de reubicación ({solicitud['tipo']}) fue {estado} por RRHH."
    if observacion:
        msg_text += f" Observación: {observacion}"

    db.execute(text("""
        INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
        VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
    """), {"empId": solicitud["employeeId"], "msg": msg_text, "now": now})

    db.commit()

    return {"message": "Solicitud actualizada", "estado": estado}
