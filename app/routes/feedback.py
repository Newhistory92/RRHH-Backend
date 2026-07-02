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
import random
from app.database.feedback_preguntas import ensure_table as ensure_preguntas_table, get_preguntas
from app.database.feedback_config import (
    ensure_table as ensure_config_table,
    get_periodicidad,
    set_periodicidad,
    get_periodo_actual,
    get_periodo_anterior,
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


def _check_self_or_admin(employee_id: int, current_user: dict) -> None:
    """Evita que un empleado actue (o lea el estado) en nombre de otro."""
    if employee_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenes permiso para acceder a esta informacion.")


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/peers/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/peers/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_evaluable_peers(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Devuelve el pool de personas que el empleado puede evaluar: companeros
    del mismo departamento/oficina + su superior directo (managerId), cada
    uno con el flag esJerarquico (determina si se le muestran preguntas de
    liderazgo).
    """
    _check_self_or_admin(employee_id, current_user)

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
# GET /feedback/siguiente/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/siguiente/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_siguiente_pregunta(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Elige al azar un par (evaluado, pregunta) pendiente del ciclo activo
    para que este empleado evalue. Devuelve pregunta null si no quedan
    pendientes.
    """
    _check_self_or_admin(employee_id, current_user)

    ensure_preguntas_table(db)
    ensure_config_table(db)

    peers_response = get_evaluable_peers(employee_id, db, current_user)
    evaluables = peers_response["evaluables"]
    preguntas = get_preguntas(db)
    periodo = get_periodo_actual(db)

    ya_respondidas = db.execute(text("""
        SELECT preguntaId, evaluadoEmployeeId
        FROM RespuestaFeedback
        WHERE evaluadorEmployeeId = :emp AND periodo = :periodo
    """), {"emp": employee_id, "periodo": periodo}).mappings().all()
    respondidas_set = {(r["preguntaId"], r["evaluadoEmployeeId"]) for r in ya_respondidas}

    candidatos = []
    for pregunta in preguntas:
        if pregunta["esAmbienteGeneral"]:
            if (pregunta["id"], None) not in respondidas_set:
                candidatos.append({"evaluado": None, "pregunta": pregunta})
            continue
        for ev in evaluables:
            if pregunta["soloLiderazgo"] and not ev["esJerarquico"]:
                continue
            if (pregunta["id"], ev["id"]) in respondidas_set:
                continue
            candidatos.append({"evaluado": ev, "pregunta": pregunta})

    if not candidatos:
        return {"evaluado": None, "pregunta": None}

    elegido = random.choice(candidatos)
    evaluado_out = (
        {"id": elegido["evaluado"]["id"], "name": elegido["evaluado"]["name"]}
        if elegido["evaluado"] else None
    )
    pregunta_out = {
        "id": elegido["pregunta"]["id"],
        "texto": elegido["pregunta"]["texto"],
        "tipo": elegido["pregunta"]["tipo"],
        "opcionesEscala": elegido["pregunta"]["opcionesEscala"],
    }
    return {"evaluado": evaluado_out, "pregunta": pregunta_out}


# ─────────────────────────────────────────────────────────────────────────────
# POST /feedback/submit
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/submit", dependencies=[Depends(require_any_auth)])
def submit_feedback(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Guarda una respuesta individual en RespuestaFeedback (escala 1-5 o
    texto libre segun el tipo de la pregunta).

    Body:
    {
      "evaluadorId": 5,
      "evaluadoId":  12,        ← null para preguntas de ambiente general
      "preguntaId":  7,
      "valorEscala": 4,         ← requerido si la pregunta es de tipo 'escala'
      "textoLibre":  null       ← requerido si la pregunta es de tipo 'texto_libre'
    }
    """
    evaluador_id = data.get("evaluadorId")
    evaluado_id = data.get("evaluadoId")
    pregunta_id = data.get("preguntaId")
    valor_escala = data.get("valorEscala")
    texto_libre = data.get("textoLibre")

    if not evaluador_id or not pregunta_id:
        raise HTTPException(status_code=400, detail="Faltan campos requeridos")

    _check_self_or_admin(evaluador_id, current_user)

    ensure_preguntas_table(db)
    ensure_config_table(db)

    pregunta = db.execute(text("""
        SELECT id, tipo, soloLiderazgo FROM Pregunta WHERE id = :id AND activo = 1
    """), {"id": pregunta_id}).mappings().first()
    if not pregunta:
        raise HTTPException(status_code=404, detail="Pregunta no encontrada")

    if pregunta["tipo"] == "escala":
        if valor_escala is None or not (1 <= int(valor_escala) <= 5):
            raise HTTPException(status_code=400, detail="valorEscala debe estar entre 1 y 5")
    else:
        if not texto_libre or not str(texto_libre).strip():
            raise HTTPException(status_code=400, detail="textoLibre no puede estar vacio")

    if pregunta["soloLiderazgo"]:
        if not evaluado_id or not _is_jerarquico(db, evaluado_id):
            raise HTTPException(status_code=403, detail="Esta pregunta solo aplica a evaluados con cargo jerarquico")

    if evaluado_id:
        valid_ids = {ev["id"] for ev in get_evaluable_peers(evaluador_id, db, current_user)["evaluables"]}
        if evaluado_id not in valid_ids:
            raise HTTPException(status_code=403, detail="Solo podes evaluar companeros de tu area o tu superior directo")

    periodo = get_periodo_actual(db)

    ya_existe = db.execute(text("""
        SELECT id FROM RespuestaFeedback
        WHERE evaluadorEmployeeId = :ev
          AND preguntaId = :pregunta
          AND periodo = :periodo
          AND (
            (:evaluado IS NULL AND evaluadoEmployeeId IS NULL)
            OR evaluadoEmployeeId = :evaluado
          )
    """), {"ev": evaluador_id, "pregunta": pregunta_id, "periodo": periodo, "evaluado": evaluado_id}).first()
    if ya_existe:
        raise HTTPException(status_code=409, detail="Ya respondiste esta pregunta en el periodo actual")

    office_id = None
    department_id = None
    if evaluado_id:
        snap = db.execute(text("""
            SELECT officeId, departmentId FROM Employee WHERE id = :id
        """), {"id": evaluado_id}).mappings().first()
        if snap:
            office_id = snap["officeId"]
            department_id = snap["departmentId"]

    db.execute(text("""
        INSERT INTO RespuestaFeedback
            (preguntaId, evaluadorEmployeeId, evaluadoEmployeeId, officeId, departmentId, periodo, valorEscala, textoLibre, createdAt)
        VALUES
            (:pregunta, :evaluador, :evaluado, :office, :department, :periodo, :valor, :texto, :now)
    """), {
        "pregunta": pregunta_id, "evaluador": evaluador_id, "evaluado": evaluado_id,
        "office": office_id, "department": department_id, "periodo": periodo,
        "valor": int(valor_escala) if valor_escala is not None else None,
        "texto": texto_libre, "now": datetime.utcnow(),
    })
    db.commit()

    return {"message": "Respuesta registrada correctamente"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/status/{employee_id}  — progreso del evaluador
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/status/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_feedback_status(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Progreso del ciclo activo: pares totales aplicables vs. respondidos."""
    _check_self_or_admin(employee_id, current_user)

    ensure_preguntas_table(db)
    ensure_config_table(db)

    evaluables = get_evaluable_peers(employee_id, db, current_user)["evaluables"]
    preguntas = get_preguntas(db)
    periodo = get_periodo_actual(db)

    total = 0
    for pregunta in preguntas:
        if pregunta["esAmbienteGeneral"]:
            total += 1
            continue
        for ev in evaluables:
            if pregunta["soloLiderazgo"] and not ev["esJerarquico"]:
                continue
            total += 1

    completadas_row = db.execute(text("""
        SELECT COUNT(*) AS c FROM RespuestaFeedback
        WHERE evaluadorEmployeeId = :emp AND periodo = :periodo
    """), {"emp": employee_id, "periodo": periodo}).mappings().first()

    return {
        "evaluatorId": employee_id,
        "periodo": periodo.isoformat(),
        "total": total,
        "completadas": completadas_row["c"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/received/{employee_id} — indicadores para RRHH
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/received/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_received_feedback(employee_id: int, db: Session = Depends(get_db)):
    """
    Indicadores de Feedback 360 recibidos por el empleado: fortalezas y
    debilidades Top 5 por categoria (promedio historico de valorEscala),
    y evolucion del promedio general entre el periodo actual y el anterior.
    """
    ensure_config_table(db)

    categorias = db.execute(text("""
        SELECT p.categoria, AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE rf.evaluadoEmployeeId = :emp
          AND p.tipo = 'escala'
          AND p.esAmbienteGeneral = 0
        GROUP BY p.categoria
        ORDER BY promedio DESC
    """), {"emp": employee_id}).mappings().all()

    ranking = [{"categoria": c["categoria"], "promedio": round(c["promedio"], 2)} for c in categorias]
    fortalezas = ranking[:5]
    debilidades = list(reversed(ranking))[:5]

    periodo_actual = get_periodo_actual(db)
    periodo_anterior = get_periodo_anterior(db)

    def promedio_periodo(periodo):
        row = db.execute(text("""
            SELECT AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio
            FROM RespuestaFeedback rf
            INNER JOIN Pregunta p ON p.id = rf.preguntaId
            WHERE rf.evaluadoEmployeeId = :emp
              AND p.tipo = 'escala'
              AND p.esAmbienteGeneral = 0
              AND rf.periodo = :periodo
        """), {"emp": employee_id, "periodo": periodo}).mappings().first()
        return round(row["promedio"], 2) if row and row["promedio"] is not None else None

    promedio_actual = promedio_periodo(periodo_actual)
    promedio_anterior = promedio_periodo(periodo_anterior)
    diferencia = (
        round(promedio_actual - promedio_anterior, 2)
        if promedio_actual is not None and promedio_anterior is not None
        else None
    )

    return {
        "employeeId": employee_id,
        "fortalezas": fortalezas,
        "debilidades": debilidades,
        "evolucion": {
            "periodoActual": periodo_actual.isoformat(),
            "promedioActual": promedio_actual,
            "periodoAnterior": periodo_anterior.isoformat(),
            "promedioAnterior": promedio_anterior,
            "diferencia": diferencia,
        },
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


# ─────────────────────────────────────────────────────────────────────────────
# POST /feedback/verificar — Boton temporal "Verificar Evaluacion de Equipo"
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/verificar", dependencies=[Depends(require_rrhh_auth)])
def verificar_reglas(db: Session = Depends(get_db)):
    """Corre chequeos de reglas de negocio sobre los datos reales de RespuestaFeedback."""
    ensure_preguntas_table(db)
    ensure_config_table(db)
    periodo = get_periodo_actual(db)

    duplicados = db.execute(text("""
        SELECT preguntaId, evaluadorEmployeeId, evaluadoEmployeeId, COUNT(*) AS c
        FROM RespuestaFeedback
        WHERE periodo = :periodo
        GROUP BY preguntaId, evaluadorEmployeeId, evaluadoEmployeeId
        HAVING COUNT(*) > 1
    """), {"periodo": periodo}).mappings().all()

    reglas = [{
        "regla": "Sin repeticion de pregunta/evaluador/evaluado en el periodo activo",
        "cumple": len(duplicados) == 0,
        "detalle": f"{len(duplicados)} duplicados encontrados",
    }]

    liderazgo_rows = db.execute(text("""
        SELECT DISTINCT rf.evaluadoEmployeeId
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE p.soloLiderazgo = 1 AND rf.periodo = :periodo AND rf.evaluadoEmployeeId IS NOT NULL
    """), {"periodo": periodo}).mappings().all()

    invalidos = [r["evaluadoEmployeeId"] for r in liderazgo_rows if not _is_jerarquico(db, r["evaluadoEmployeeId"])]

    reglas.append({
        "regla": "Preguntas de liderazgo solo a evaluados jerarquicos",
        "cumple": len(invalidos) == 0,
        "detalle": (
            f"{len(invalidos)} respuestas de liderazgo sobre evaluados sin cargo jerarquico (ids {invalidos})"
            if invalidos else "0 infracciones encontradas"
        ),
    })

    return {"reglas": reglas}


# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/estadisticas-globales — radar y rankings por departamento
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/estadisticas-globales", dependencies=[Depends(require_any_auth)])
def get_estadisticas_globales(departmentId: int, db: Session = Depends(get_db)):
    """
    Radar de habilidades (promedio del departamento seleccionado vs.
    promedio institucional, por categoria) y ranking de fortalezas/
    debilidades del departamento seleccionado.
    """
    rows = db.execute(text("""
        SELECT
            p.categoria,
            AVG(CASE WHEN rf.departmentId = :deptId THEN CAST(rf.valorEscala AS FLOAT) END) AS promedio_area,
            AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio_institucional
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE p.tipo = 'escala' AND p.esAmbienteGeneral = 0
        GROUP BY p.categoria
        ORDER BY p.categoria ASC
    """), {"deptId": departmentId}).mappings().all()

    radar = []
    ranking_area = []
    for r in rows:
        promedio_area = round(r["promedio_area"], 2) if r["promedio_area"] is not None else None
        promedio_institucional = round(r["promedio_institucional"], 2) if r["promedio_institucional"] is not None else None
        radar.append({
            "categoria": r["categoria"],
            "promedioArea": promedio_area,
            "promedioInstitucional": promedio_institucional,
        })
        if promedio_area is not None:
            ranking_area.append({"categoria": r["categoria"], "promedio": promedio_area})

    ranking_area_desc = sorted(ranking_area, key=lambda x: x["promedio"], reverse=True)
    fortalezas_area = ranking_area_desc[:5]
    debilidades_area = list(reversed(ranking_area_desc))[:5]

    return {
        "departmentId": departmentId,
        "radar": radar,
        "fortalezasArea": fortalezas_area,
        "debilidadesArea": debilidades_area,
    }
