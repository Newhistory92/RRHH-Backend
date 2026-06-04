"""
Router /tests — Módulo de tests técnicos para empleados.

Endpoints:
  GET  /tests/{skill_id}/questions     → preguntas aleatorias para el test
  GET  /tests/{skill_id}/cooldown/{employee_id} → verifica si puede rendir
  POST /tests/{skill_id}/submit/{employee_id}   → evalúa y registra resultado
  GET  /tests/history/{employee_id}             → historial de intentos

Escala estándar (P3): "Malo" | "Bueno" | "Excelente"
  - < 50% correctas  → Malo
  - 50%–79%          → Bueno
  - ≥ 80%            → Excelente

Restricción: 1 test cada 3 meses por habilidad (P2).
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from datetime import datetime, timedelta, timezone
import json
import random

router = APIRouter(prefix="/tests", tags=["Tests"])

# ── Escala estándar (P3) ─────────────────────────────────────────────────────
SCORE_MALO      = "Malo"
SCORE_BUENO     = "Bueno"
SCORE_EXCELENTE = "Excelente"

COOLDOWN_MONTHS = 3      # meses de espera entre tests
MIN_QUESTIONS   = 5      # preguntas por test
MAX_QUESTIONS   = 10


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _pct_to_score(correct_pct: float) -> str:
    """Convierte porcentaje de aciertos a la escala estándar."""
    if correct_pct < 50:
        return SCORE_MALO
    elif correct_pct < 80:
        return SCORE_BUENO
    else:
        return SCORE_EXCELENTE


def _in_cooldown(db: Session, employee_id: int, skill_id: int) -> dict | None:
    """
    Devuelve info del último intento si está dentro del período de cooldown,
    None si puede rendir.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=COOLDOWN_MONTHS * 30)).replace(tzinfo=None)
    row = db.execute(text("""
        SELECT TOP 1 id, score, takenAt
        FROM TestAttempt
        WHERE employeeId = :emp AND technicalSkillId = :skill
          AND takenAt >= :cutoff
        ORDER BY takenAt DESC
    """), {"emp": employee_id, "skill": skill_id, "cutoff": cutoff}).mappings().first()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# GET /tests/{skill_id}/cooldown/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/cooldown/{skill_id}/{employee_id}", dependencies=[Depends(require_any_auth)])
def check_cooldown(skill_id: int, employee_id: int, db: Session = Depends(get_db)):
    """
    Verifica si el empleado puede rendir el test de la habilidad.
    Retorna:
      - can_take: bool
      - last_attempt: info del último intento (si existe)
      - available_from: fecha desde la que puede rendir de nuevo
    """
    last = _in_cooldown(db, employee_id, skill_id)
    if not last:
        return {"can_take": True, "last_attempt": None, "available_from": None}

    taken_at = last["takenAt"]
    if isinstance(taken_at, str):
        taken_at = datetime.fromisoformat(taken_at)
    available_from = taken_at + timedelta(days=COOLDOWN_MONTHS * 30)

    return {
        "can_take": False,
        "last_attempt": {
            "score":    last["score"],
            "takenAt":  last["takenAt"],
        },
        "available_from": available_from.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /tests/{skill_id}/questions?employee_id=X
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{skill_id}/questions", dependencies=[Depends(require_any_auth)])
def get_test_questions(skill_id: int, employee_id: int, db: Session = Depends(get_db)):
    """
    Retorna preguntas aleatorias para que el empleado rinda el test.
    - Verifica cooldown de 3 meses.
    - Evita repetir las preguntas del último intento (anti-repetición).
    - Si hay < 10 preguntas en total, retorna todas las disponibles.
    """
    # Verificar cooldown
    last = _in_cooldown(db, employee_id, skill_id)
    if last:
        taken_at = last["takenAt"]
        if isinstance(taken_at, str):
            taken_at = datetime.fromisoformat(taken_at)
        available_from = taken_at + timedelta(days=COOLDOWN_MONTHS * 30)
        raise HTTPException(
            status_code=429,
            detail={
                "message": f"Ya realizaste este test. Podés volver a rendirlo a partir del {available_from.strftime('%d/%m/%Y')}",
                "score":          last["score"],
                "available_from": available_from.isoformat(),
            }
        )

    # Verificar que la habilidad existe
    skill = db.execute(
        text("SELECT id, nombre, testType FROM TechnicalSkill WHERE id = :id AND activo = 1"),
        {"id": skill_id}
    ).mappings().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Habilidad técnica no encontrada o inactiva")

    # Traer todas las preguntas con sus respuestas
    questions_raw = db.execute(text("""
        SELECT q.id, q.text
        FROM Question q
        WHERE q.technicalSkillId = :skill_id
    """), {"skill_id": skill_id}).mappings().all()

    if not questions_raw:
        raise HTTPException(status_code=404, detail="Esta habilidad no tiene preguntas cargadas aún")

    # Recuperar IDs del último intento para anti-repetición
    last_attempt = db.execute(text("""
        SELECT TOP 1 questionsUsed
        FROM TestAttempt
        WHERE employeeId = :emp AND technicalSkillId = :skill
        ORDER BY takenAt DESC
    """), {"emp": employee_id, "skill": skill_id}).mappings().first()

    used_ids = set()
    if last_attempt and last_attempt["questionsUsed"]:
        try:
            used_ids = set(json.loads(last_attempt["questionsUsed"]))
        except Exception:
            used_ids = set()

    # Preferir preguntas no usadas en el último intento
    all_ids    = [q["id"] for q in questions_raw]
    fresh_ids  = [i for i in all_ids if i not in used_ids]
    pool       = fresh_ids if len(fresh_ids) >= MIN_QUESTIONS else all_ids

    n = min(MAX_QUESTIONS, len(pool))
    selected_ids = random.sample(pool, n)

    # Traer respuestas para las preguntas seleccionadas
    ids_str = ",".join(str(i) for i in selected_ids)
    answers_raw = db.execute(text(f"""
        SELECT id, text, isCorrect, questionId
        FROM Answer
        WHERE questionId IN ({ids_str})
    """)).mappings().all()

    answers_by_q: dict = {}
    for a in answers_raw:
        answers_by_q.setdefault(a["questionId"], []).append({
            "id":   a["id"],
            "text": a["text"],
            # NO incluir isCorrect en la respuesta al cliente
        })

    # Ensamblar preguntas con respuestas barajadas
    selected_questions = []
    questions_map = {q["id"]: q for q in questions_raw}
    for qid in selected_ids:
        q = questions_map[qid]
        opts = answers_by_q.get(qid, [])
        random.shuffle(opts)
        selected_questions.append({
            "id":      q["id"],
            "text":    q["text"],
            "answers": opts,
        })

    return {
        "skillId":    skill_id,
        "skillName":  skill["nombre"],
        "testType":   skill["testType"],
        "employeeId": employee_id,
        "questions":  selected_questions,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /tests/{skill_id}/submit/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{skill_id}/submit/{employee_id}", dependencies=[Depends(require_any_auth)])
def submit_test(
    skill_id: int,
    employee_id: int,
    data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    Recibe las respuestas del empleado, evalúa el test y registra el resultado.

    Body esperado:
    {
      "answers": [
        { "questionId": 1, "answerId": 3 },
        ...
      ]
    }

    Retorna:
    {
      "score": "Bueno",
      "correctPct": 72.5,
      "correct": 5,
      "total": 6,
      "levelUpdated": true
    }
    """
    # Verificar cooldown nuevamente (protección doble ante race conditions)
    last = _in_cooldown(db, employee_id, skill_id)
    if last:
        taken_at = last["takenAt"]
        if isinstance(taken_at, str):
            taken_at = datetime.fromisoformat(taken_at)
        available_from = taken_at + timedelta(days=COOLDOWN_MONTHS * 30)
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown activo. Podés rendir de nuevo a partir del {available_from.strftime('%d/%m/%Y')}"
        )

    submitted_answers: list[dict] = data.get("answers", [])
    if not submitted_answers:
        raise HTTPException(status_code=400, detail="Debes enviar al menos una respuesta")

    # Obtener las respuestas correctas de las preguntas enviadas
    question_ids = list({a["questionId"] for a in submitted_answers})
    ids_str = ",".join(str(i) for i in question_ids)

    correct_map = db.execute(text(f"""
        SELECT id, questionId, isCorrect
        FROM Answer
        WHERE questionId IN ({ids_str})
    """)).mappings().all()

    # Mapear answerId → isCorrect
    answer_correctness: dict[int, bool] = {
        row["id"]: bool(row["isCorrect"]) for row in correct_map
    }

    # Evaluar respuestas del empleado
    correct_count = 0
    for ans in submitted_answers:
        answer_id = ans.get("answerId")
        if answer_id and answer_correctness.get(answer_id, False):
            correct_count += 1

    total = len(submitted_answers)
    correct_pct = round((correct_count / total) * 100, 2) if total > 0 else 0.0
    score = _pct_to_score(correct_pct)

    # Registrar intento en TestAttempt
    questions_used_json = json.dumps(question_ids)
    db.execute(text("""
        INSERT INTO TestAttempt (employeeId, technicalSkillId, score, correctPct, questionsUsed, takenAt)
        VALUES (:emp, :skill, :score, :pct, :q_used, :taken_at)
    """), {
        "emp":      employee_id,
        "skill":    skill_id,
        "score":    score,
        "pct":      correct_pct,
        "q_used":   questions_used_json,
        "taken_at": datetime.now(timezone.utc).replace(tzinfo=None),
    })

    # (P3) Actualizar EmployeeTechnicalSkill.level con la escala unificada
    existing_skill = db.execute(text("""
        SELECT id FROM EmployeeTechnicalSkill
        WHERE employeeId = :emp AND technicalSkillId = :skill
    """), {"emp": employee_id, "skill": skill_id}).first()

    level_updated = False
    if existing_skill:
        db.execute(text("""
            UPDATE EmployeeTechnicalSkill
            SET level = :score, certified = :certified, updatedAt = :now
            WHERE employeeId = :emp AND technicalSkillId = :skill
        """), {
            "score":    score,
            "certified": 1 if score == SCORE_EXCELENTE else 0,
            "now":      datetime.now(timezone.utc).replace(tzinfo=None),
            "emp":      employee_id,
            "skill":    skill_id,
        })
        level_updated = True
    else:
        # Si el empleado no tenía la skill registrada, la creamos
        db.execute(text("""
            INSERT INTO EmployeeTechnicalSkill (employeeId, technicalSkillId, level, certified, updatedAt)
            VALUES (:emp, :skill, :score, :certified, :now)
        """), {
            "emp":      employee_id,
            "skill":    skill_id,
            "score":    score,
            "certified": 1 if score == SCORE_EXCELENTE else 0,
            "now":      datetime.now(timezone.utc).replace(tzinfo=None),
        })
        level_updated = True

    db.commit()

    return {
        "score":        score,
        "correctPct":   correct_pct,
        "correct":      correct_count,
        "total":        total,
        "levelUpdated": level_updated,
        "message":      f"Resultado: {score} ({correct_count}/{total} correctas, {correct_pct}%)",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /tests/history/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/history/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_test_history(employee_id: int, db: Session = Depends(get_db)):
    """Retorna el historial de tests de un empleado, con nombre de habilidad."""
    rows = db.execute(text("""
        SELECT
            ta.id,
            ta.technicalSkillId,
            ts.nombre AS skillName,
            ta.score,
            ta.correctPct,
            ta.takenAt
        FROM TestAttempt ta
        INNER JOIN TechnicalSkill ts ON ts.id = ta.technicalSkillId
        WHERE ta.employeeId = :emp
        ORDER BY ta.takenAt DESC
    """), {"emp": employee_id}).mappings().all()

    history = [
        {
            "id":              r["id"],
            "technicalSkillId":r["technicalSkillId"],
            "skillName":       r["skillName"],
            "score":           r["score"],
            "correctPct":      r["correctPct"],
            "takenAt":         r["takenAt"],
        }
        for r in rows
    ]

    return {"employeeId": employee_id, "history": history}


# ─────────────────────────────────────────────────────────────────────────────
# GET /tests/skills/{employee_id} — habilidades disponibles para rendir
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/skills/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_available_skills(employee_id: int, db: Session = Depends(get_db)):
    """
    Retorna todas las habilidades técnicas activas con:
    - Cantidad de preguntas disponibles
    - Último intento del empleado
    - Si puede rendir (cooldown check)
    """
    skills = db.execute(text("""
        SELECT
            ts.id,
            ts.nombre,
            ts.description,
            ts.testType,
            ts.profession,
            (SELECT COUNT(*) FROM Question q WHERE q.technicalSkillId = ts.id) AS questionCount,
            ets.level AS currentLevel,
            ets.certified
        FROM TechnicalSkill ts
        LEFT JOIN EmployeeTechnicalSkill ets
          ON ets.technicalSkillId = ts.id AND ets.employeeId = :emp
        WHERE ts.activo = 1
        ORDER BY ts.nombre ASC
    """), {"emp": employee_id}).mappings().all()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=COOLDOWN_MONTHS * 30)).replace(tzinfo=None)

    # Últimos intentos del empleado en las últimas 3 meses
    attempts = db.execute(text("""
        SELECT technicalSkillId, score, takenAt
        FROM TestAttempt
        WHERE employeeId = :emp AND takenAt >= :cutoff
    """), {"emp": employee_id, "cutoff": cutoff}).mappings().all()

    in_cooldown_skills = {a["technicalSkillId"]: a for a in attempts}

    result = []
    for s in skills:
        sid = s["id"]
        cooldown_info = in_cooldown_skills.get(sid)
        can_take = cooldown_info is None

        available_from = None
        if cooldown_info:
            taken_at = cooldown_info["takenAt"]
            if isinstance(taken_at, str):
                taken_at = datetime.fromisoformat(taken_at)
            available_from = (taken_at + timedelta(days=COOLDOWN_MONTHS * 30)).isoformat()

        result.append({
            "id":            sid,
            "nombre":        s["nombre"],
            "description":   s["description"],
            "testType":      s["testType"],
            "profession":    s["profession"],
            "questionCount": s["questionCount"],
            "currentLevel":  s["currentLevel"],
            "certified":     bool(s["certified"]) if s["certified"] is not None else False,
            "canTake":       can_take,
            "availableFrom": available_from,
        })

    return {"employeeId": employee_id, "skills": result}
