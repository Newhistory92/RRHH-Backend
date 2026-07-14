"""
Router /reubicacion -- Solicitud de cambio de oficina/departamento
(subsistema 1 del modulo de Reubicacion Inteligente).
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
import json
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


def _parse_json_list(value) -> list:
    """Parsea un campo NVARCHAR con un JSON array; devuelve [] si es NULL o invalido."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


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
            sr.officeIdSugerido, os.nombre AS officeSugeridoName,
            sr.departmentIdSugerido, ds.nombre AS departmentSugeridoName,
            sr.scoreCompatibilidad, sr.explicacionIA, sr.beneficios, sr.riesgos,
            sr.officeIdDestino, sr.departmentIdDestino,
            sr.createdAt, sr.updatedAt
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        LEFT JOIN Office o ON o.id = sr.officeIdActual
        LEFT JOIN Department d ON d.id = sr.departmentIdActual
        LEFT JOIN Office os ON os.id = sr.officeIdSugerido
        LEFT JOIN Department ds ON ds.id = sr.departmentIdSugerido
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
                "officeIdSugerido": r["officeIdSugerido"],
                "officeSugeridoName": r["officeSugeridoName"],
                "departmentIdSugerido": r["departmentIdSugerido"],
                "departmentSugeridoName": r["departmentSugeridoName"],
                "scoreCompatibilidad": r["scoreCompatibilidad"],
                "explicacionIA": r["explicacionIA"],
                "beneficios": _parse_json_list(r["beneficios"]),
                "riesgos": _parse_json_list(r["riesgos"]),
                "officeIdDestino": r["officeIdDestino"],
                "departmentIdDestino": r["departmentIdDestino"],
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
    office_id_destino = data.get("officeIdDestino")
    department_id_destino = data.get("departmentIdDestino")

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
        SET estado = :estado, observacion = :observacion,
            officeIdDestino = :officeIdDestino, departmentIdDestino = :departmentIdDestino,
            updatedAt = :now
        WHERE id = :id
    """), {
        "estado": estado, "observacion": observacion,
        "officeIdDestino": office_id_destino, "departmentIdDestino": department_id_destino,
        "now": now, "id": solicitud_id,
    })

    msg_text = f"Tu solicitud de reubicación ({solicitud['tipo']}) fue {estado} por RRHH."
    if observacion:
        msg_text += f" Observación: {observacion}"

    db.execute(text("""
        INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
        VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
    """), {"empId": solicitud["employeeId"], "msg": msg_text, "now": now})

    db.commit()

    return {"message": "Solicitud actualizada", "estado": estado}


# ─────────────────────────────────────────────────────────────────────────────
# POST /reubicacion/analizar/iniciar — marca Pendiente/En análisis como
# En análisis y las devuelve para que el orquestador (Next.js) las procese.
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/analizar/iniciar", dependencies=[Depends(require_rrhh_auth)])
def iniciar_analisis(db: Session = Depends(get_db)):
    """Marca las solicitudes Pendiente o En análisis como En análisis y las devuelve."""
    ensure_table(db)

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'En análisis', updatedAt = :now
        WHERE estado IN ('Pendiente', 'En análisis')
    """), {"now": now})
    db.commit()

    rows = db.execute(text("""
        SELECT sr.id, sr.employeeId, e.name AS employeeName, sr.tipo, sr.motivo,
               sr.officeIdActual, sr.departmentIdActual
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        WHERE sr.estado = 'En análisis'
        ORDER BY sr.createdAt ASC
    """)).mappings().all()

    solicitudes = [
        {
            "id": r["id"],
            "employeeId": r["employeeId"],
            "employeeName": r["employeeName"],
            "tipo": r["tipo"],
            "motivo": r["motivo"],
            "officeIdActual": r["officeIdActual"],
            "departmentIdActual": r["departmentIdActual"],
        }
        for r in rows
    ]

    return {"solicitudes": solicitudes, "count": len(solicitudes)}


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/recomendacion — guarda la recomendacion
# del motor de IA y pasa la solicitud a 'Recomendada'.
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/recomendacion", dependencies=[Depends(require_rrhh_auth)])
def guardar_recomendacion(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Guarda la recomendacion de IA (destino, score, explicacion) y pasa a Recomendada."""
    office_id_sugerido = data.get("officeIdSugerido")
    department_id_sugerido = data.get("departmentIdSugerido")
    score = data.get("scoreCompatibilidad")
    explicacion = data.get("explicacionIA")
    beneficios = data.get("beneficios") or []
    riesgos = data.get("riesgos") or []

    if score is None or not isinstance(score, (int, float)):
        raise HTTPException(status_code=400, detail="scoreCompatibilidad es requerido y debe ser numerico")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'Recomendada',
            officeIdSugerido = :officeIdSugerido,
            departmentIdSugerido = :departmentIdSugerido,
            scoreCompatibilidad = :score,
            explicacionIA = :explicacion,
            beneficios = :beneficios,
            riesgos = :riesgos,
            updatedAt = :now
        WHERE id = :id
    """), {
        "officeIdSugerido": office_id_sugerido,
        "departmentIdSugerido": department_id_sugerido,
        "score": int(score),
        "explicacion": explicacion,
        "beneficios": json.dumps(beneficios, ensure_ascii=False),
        "riesgos": json.dumps(riesgos, ensure_ascii=False),
        "now": now,
        "id": solicitud_id,
    })
    db.commit()

    return {"message": "Recomendación guardada", "estado": "Recomendada"}


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/ejecutar — mueve al empleado en el
# organigrama (Employee.officeId/departmentId/managerId) y pasa a 'Ejecutada'.
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/ejecutar", dependencies=[Depends(require_rrhh_auth)])
def ejecutar_solicitud(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Ejecuta una solicitud Aprobada: mueve al empleado en el organigrama y notifica.

    El destino puede ser una oficina (officeId) o directamente un departamento
    (departmentId) cuando ese departamento no tiene oficinas cargadas. Si se
    indica officeId, el departamento y el jefe se derivan de la oficina; si solo
    se indica departmentId, la oficina del empleado queda NULL y el jefe se toma
    del departamento.
    """
    office_id = data.get("officeId")
    department_id = data.get("departmentId")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id, employeeId, estado FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if solicitud["estado"] != "Aprobada":
        raise HTTPException(status_code=400, detail="Solo se pueden ejecutar solicitudes en estado 'Aprobada'")

    if not office_id and not department_id:
        raise HTTPException(status_code=400, detail="Debe indicar la oficina o el departamento destino para ejecutar")

    employee_id = solicitud["employeeId"]

    if office_id:
        # Destino por oficina: departamento y jefe se derivan de la oficina.
        office = db.execute(text("""
            SELECT id, departmentId, jefeId, nombre FROM Office WHERE id = :id
        """), {"id": office_id}).mappings().first()
        if not office:
            raise HTTPException(status_code=404, detail="Oficina no encontrada")
        dest_office_id = office["id"]
        dest_department_id = office["departmentId"]
        jefe_id = office["jefeId"]
        destino_texto = f"Nueva oficina: {office['nombre']}."
    else:
        # Destino por departamento: sin oficina, jefe se toma del departamento.
        department = db.execute(text("""
            SELECT id, jefeId, nombre FROM Department WHERE id = :id
        """), {"id": department_id}).mappings().first()
        if not department:
            raise HTTPException(status_code=404, detail="Departamento no encontrado")
        dest_office_id = None
        dest_department_id = department["id"]
        jefe_id = department["jefeId"]
        destino_texto = f"Nuevo departamento: {department['nombre']}."

    manager_id = jefe_id if jefe_id and jefe_id != employee_id else None

    db.execute(text("""
        UPDATE Employee
        SET officeId = :officeId, departmentId = :departmentId, managerId = :managerId
        WHERE id = :employeeId
    """), {
        "officeId": dest_office_id, "departmentId": dest_department_id,
        "managerId": manager_id, "employeeId": employee_id,
    })

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'Ejecutada', officeIdDestino = :officeId, departmentIdDestino = :departmentId, updatedAt = :now
        WHERE id = :id
    """), {
        "officeId": dest_office_id, "departmentId": dest_department_id,
        "now": now, "id": solicitud_id,
    })

    msg_text = f"Tu reubicación fue ejecutada. {destino_texto}"
    db.execute(text("""
        INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
        VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
    """), {"empId": employee_id, "msg": msg_text, "now": now})

    db.commit()

    return {"message": "Reubicación ejecutada", "estado": "Ejecutada"}
