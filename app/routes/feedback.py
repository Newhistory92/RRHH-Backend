"""
Router /feedback — Evaluación entre pares (Feedback 360°).

Endpoints:
  GET  /feedback/peers/{employee_id}     → compañeros del mismo dept/oficina evaluables
  POST /feedback/submit                  → guarda una evaluación anónima
  GET  /feedback/received/{employee_id}  → feedback recibido por el empleado
  GET  /feedback/status/{employee_id}    → estado del ciclo de evaluación del evaluador

Reglas implementadas:
  - Solo se pueden evaluar compañeros del mismo Department u Office
  - El resultado (malo/bueno/excelente) actualiza el modelo Respuesta sin revelar evaluador
  - Un evaluador no puede reevaluar la misma habilidad del mismo compañero
    hasta que se reinicia el ciclo (todas las evaluaciones completadas)
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from datetime import datetime, timezone
from app.database.feedback_preguntas import ensure_table as ensure_preguntas_table, get_preguntas
from app.database.feedback_config import (
    ensure_table as ensure_config_table,
    get_periodicidad,
    set_periodicidad,
    get_periodo_actual,
)

router = APIRouter(prefix="/feedback", tags=["Feedback"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_jerarquico(db: Session, employee_id: int) -> bool:
    """True si el empleado es jefe de algun departamento o tiene reportes directos."""
    row = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM Department WHERE jefeId = :id) AS deptos_a_cargo,
            (SELECT COUNT(*) FROM Employee WHERE managerId = :id) AS reportes_directos
    """), {"id": employee_id}).mappings().first()
    return bool(row and (row["deptos_a_cargo"] > 0 or row["reportes_directos"] > 0))


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/peers/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/peers/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_evaluable_peers(employee_id: int, db: Session = Depends(get_db)):
    """
    Devuelve el pool de personas que el empleado puede evaluar: companeros
    del mismo departamento/oficina + su superior directo (managerId), cada
    uno con el flag esJerarquico (determina si se le muestran preguntas de
    liderazgo).
    """
    evaluator = db.execute(text("""
        SELECT e.id, e.name, e.departmentId, e.officeId, e.managerId, d.nombre AS deptName
        FROM Employee e
        LEFT JOIN Department d ON d.id = e.departmentId
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()

    if not evaluator:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    dept_id = evaluator["departmentId"]
    office_id = evaluator["officeId"]
    manager_id = evaluator["managerId"]

    peers = db.execute(text("""
        SELECT DISTINCT e.id, e.name, d.nombre AS department, o.nombre AS office
        FROM Employee e
        LEFT JOIN Department d ON d.id = e.departmentId
        LEFT JOIN Office o ON o.id = e.officeId
        WHERE e.id != :emp_id
          AND (
            (:dept_id IS NOT NULL AND e.departmentId = :dept_id)
            OR (:office_id IS NOT NULL AND e.officeId = :office_id)
          )
        ORDER BY e.name ASC
    """), {
        "emp_id": employee_id,
        "dept_id": dept_id,
        "office_id": office_id
    }).mappings().all()

    evaluables_by_id: dict[int, dict] = {}
    for p in peers:
        evaluables_by_id[p["id"]] = {
            "id": p["id"], "name": p["name"],
            "department": p["department"], "office": p["office"],
        }

    if manager_id and manager_id not in evaluables_by_id:
        manager = db.execute(text("""
            SELECT e.id, e.name, d.nombre AS department, o.nombre AS office
            FROM Employee e
            LEFT JOIN Department d ON d.id = e.departmentId
            LEFT JOIN Office o ON o.id = e.officeId
            WHERE e.id = :id
        """), {"id": manager_id}).mappings().first()
        if manager:
            evaluables_by_id[manager["id"]] = {
                "id": manager["id"], "name": manager["name"],
                "department": manager["department"], "office": manager["office"],
            }

    evaluables = []
    for ev in evaluables_by_id.values():
        ev["esJerarquico"] = _is_jerarquico(db, ev["id"])
        evaluables.append(ev)

    return {
        "evaluatorId": employee_id,
        "department": evaluator["deptName"],
        "evaluables": evaluables,
    }

# ─────────────────────────────────────────────────────────────────────────────
# POST /feedback/submit
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/submit", dependencies=[Depends(require_any_auth)])
def submit_feedback(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Guarda una evaluación de habilidad blanda.

    Body:
    {
      "evaluatorId":   1,       ← quien evalúa (sus datos NO se guardan vinculados al resultado)
      "evaluatedId":   2,       ← quien es evaluado
      "softSkillId":   5,       ← habilidad evaluada
      "result":        "Bueno"  ← "Malo" | "Bueno" | "Excelente"
    }

    El resultado incremente el conteo (malo/bueno/excelente) en la tabla Respuesta,
    que es el campo que impacta en las estadísticas internas.
    La FeedbackEvaluacion solo guarda que evaluatorId evaluó a evaluatedId+skillId (sin ligar result).
    """
    evaluator_id  = data.get("evaluatorId")
    evaluated_id  = data.get("evaluatedId")
    soft_skill_id = data.get("softSkillId")
    result        = data.get("result")

    if not all([evaluator_id, evaluated_id, soft_skill_id, result]):
        raise HTTPException(status_code=400, detail="Faltan campos requeridos")

    valid_results = {"Malo", "Bueno", "Excelente"}
    if result not in valid_results:
        raise HTTPException(status_code=400, detail=f"result debe ser uno de: {valid_results}")

    # Verificar que evaluado y evaluador son compañeros del mismo área
    same_area = db.execute(text("""
        SELECT 1
        FROM Employee e1, Employee e2
        WHERE e1.id = :ev AND e2.id = :ed
          AND (e1.departmentId = e2.departmentId OR e1.officeId = e2.officeId)
          AND e1.id != e2.id
    """), {"ev": evaluator_id, "ed": evaluated_id}).first()

    if not same_area:
        raise HTTPException(status_code=403, detail="Solo podés evaluar compañeros de tu mismo departamento u oficina")

    # Determinar ciclo actual (fecha de inicio del ciclo — usamos el mes/año actual)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cycle_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Verificar si ya evaluó esta habilidad de este compañero en el ciclo actual
    already = db.execute(text("""
        SELECT id FROM FeedbackEvaluacion
        WHERE evaluatorEmployeeId = :ev
          AND evaluatedEmployeeId = :ed
          AND softSkillId = :sk
          AND cycleStart = :cycle
    """), {"ev": evaluator_id, "ed": evaluated_id, "sk": soft_skill_id, "cycle": cycle_start}).first()

    if already:
        raise HTTPException(status_code=409, detail="Ya evaluaste esta habilidad de este compañero en el ciclo actual")

    # Buscar o crear Feedback + Respuesta para el evaluado+habilidad en este ciclo
    feedback_row = db.execute(text("""
        SELECT f.id
        FROM Feedback f
        WHERE f.userId = :evaluated_id AND f.skillId = :skill_id
          AND f.cycleStart = :cycle
    """), {"evaluated_id": evaluated_id, "skill_id": soft_skill_id, "cycle": cycle_start}).first()

    if not feedback_row:
        # Crear feedback para este ciclo
        feedback_result = db.execute(text("""
            INSERT INTO Feedback (userId, skillId, cycleStart, createdAt, activo)
            OUTPUT INSERTED.id
            VALUES (:user_id, :skill_id, :cycle, :now, 1)
        """), {"user_id": evaluated_id, "skill_id": soft_skill_id, "cycle": cycle_start, "now": now})
        feedback_id = feedback_result.fetchone()[0]

        # Crear Respuesta con conteos en 0
        db.execute(text("""
            INSERT INTO Respuesta (feedbackId, malo, bueno, excelente)
            VALUES (:fid, 0, 0, 0)
        """), {"fid": feedback_id})
    else:
        feedback_id = feedback_row[0]

    # Incrementar el contador correspondiente en Respuesta
    column_map = {"Malo": "malo", "Bueno": "bueno", "Excelente": "excelente"}
    col = column_map[result]
    db.execute(text(f"""
        UPDATE Respuesta SET {col} = {col} + 1
        WHERE feedbackId = :fid
    """), {"fid": feedback_id})

    # Registrar que el evaluador completó esta evaluación (para progreso y anti-repetición)
    db.execute(text("""
        INSERT INTO FeedbackEvaluacion
            (evaluatorEmployeeId, evaluatedEmployeeId, softSkillId, cycleStart, createdAt)
        VALUES (:ev, :ed, :sk, :cycle, :now)
    """), {"ev": evaluator_id, "ed": evaluated_id, "sk": soft_skill_id, "cycle": cycle_start, "now": now})

    db.commit()

    return {"message": "Feedback registrado correctamente", "feedbackId": feedback_id}


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/status/{employee_id}  — progreso del evaluador
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/status/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_feedback_status(employee_id: int, db: Session = Depends(get_db)):
    """Estado del ciclo actual del evaluador: cuántas evaluaciones completó vs. total."""
    now         = datetime.now(timezone.utc).replace(tzinfo=None)
    cycle_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    completed = db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM FeedbackEvaluacion
        WHERE evaluatorEmployeeId = :emp AND cycleStart = :cycle
    """), {"emp": employee_id, "cycle": cycle_start}).mappings().first()

    return {
        "evaluatorId":       employee_id,
        "cycleStart":        cycle_start.isoformat(),
        "completedEvaluations": completed["cnt"] if completed else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/received/{employee_id} — resultados recibidos por el empleado
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/received/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_received_feedback(employee_id: int, db: Session = Depends(get_db)):
    """Retorna el feedback recibido con conteos agregados por habilidad blanda."""
    rows = db.execute(text("""
        SELECT
            f.id AS feedbackId,
            f.cycleStart,
            ss.id   AS skillId,
            ss.nombre AS skillName,
            r.malo, r.bueno, r.excelente
        FROM Feedback f
        INNER JOIN SoftSkill ss ON ss.id = f.skillId
        LEFT JOIN Respuesta r ON r.feedbackId = f.id
        WHERE f.userId = :emp
        ORDER BY f.cycleStart DESC, ss.nombre ASC
    """), {"emp": employee_id}).mappings().all()

    return {
        "employeeId": employee_id,
        "feedback": [
            {
                "feedbackId":  r["feedbackId"],
                "cycleStart":  r["cycleStart"],
                "skillId":     r["skillId"],
                "skillName":   r["skillName"],
                "results": {
                    "malo":      r["malo"] or 0,
                    "bueno":     r["bueno"] or 0,
                    "excelente": r["excelente"] or 0,
                }
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/preguntas — Banco de preguntas de Feedback 360
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/preguntas", dependencies=[Depends(require_any_auth)])
def list_preguntas(
    soloLiderazgo: bool | None = None,
    esAmbienteGeneral: bool | None = None,
    db: Session = Depends(get_db),
):
    """Lista el banco de preguntas activas, con filtros opcionales."""
    ensure_preguntas_table(db)
    preguntas = get_preguntas(db, solo_liderazgo=soloLiderazgo, es_ambiente_general=esAmbienteGeneral)
    return {"preguntas": preguntas}


# ─────────────────────────────────────────────────────────────────────────────
# GET / PUT /feedback/config — Periodicidad del ciclo de evaluacion
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/config", dependencies=[Depends(require_any_auth)])
def get_feedback_config(db: Session = Depends(get_db)):
    ensure_config_table(db)
    periodicidad = get_periodicidad(db)
    periodo = get_periodo_actual(db)
    return {"periodicidad": periodicidad, "periodoActual": periodo.isoformat()}


@router.put("/config", dependencies=[Depends(require_rrhh_auth)])
def update_feedback_config(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_config_table(db)
    periodicidad = data.get("periodicidad")
    try:
        set_periodicidad(db, periodicidad)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"periodicidad": periodicidad}
