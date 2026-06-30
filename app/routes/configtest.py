from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth
from app.database.academic_title_mapping import (
    ensure_table as ensure_academic_title_mapping_table,
    get_active_mappings,
    save_mapping,
    delete_mapping,
)
import json

router = APIRouter(prefix="/configtest", tags=["ConfigTest"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/technical", dependencies=[Depends(require_any_auth)])
def get_technical_config(db: Session = Depends(get_db)):
    """
    Returns the professions and testsByProfession structure as expected by the frontend.
    """
    # 1. Fetch all active technical skills
    skills_rows = db.execute(text("""
        SELECT id, nombre, description, testType, profession
        FROM TechnicalSkill
        WHERE activo = 1
    """)).mappings().all()

    skill_ids = [s["id"] for s in skills_rows]

    # 2. Fetch all questions for active technical skills
    questions_rows = []
    answers_by_question = {}

    if skill_ids:
        skill_ids_str = ",".join(str(i) for i in skill_ids)
        questions_rows = db.execute(text(f"""
            SELECT id, text, technicalSkillId
            FROM Question
            WHERE technicalSkillId IN ({skill_ids_str})
        """)).mappings().all()

        question_ids = [q["id"] for q in questions_rows]

        if question_ids:
            q_ids_str = ",".join(str(i) for i in question_ids)
            answers_rows = db.execute(text(f"""
                SELECT id, text, isCorrect, questionId
                FROM Answer
                WHERE questionId IN ({q_ids_str})
            """)).mappings().all()

            for a in answers_rows:
                answers_by_question.setdefault(a["questionId"], []).append({
                    "id": str(a["id"]),
                    "text": a["text"],
                    "isCorrect": bool(a["isCorrect"])
                })

    # Group questions by skill
    questions_by_skill = {}
    for q in questions_rows:
        q_id = q["id"]
        questions_by_skill.setdefault(q["technicalSkillId"], []).append({
            "id": str(q_id),
            "text": q["text"],
            "answers": answers_by_question.get(q_id, [])
        })

    # Construct professions and testsByProfession mappings
    professions = {}
    tests_by_profession = {}

    for s in skills_rows:
        prof = s["profession"] or "General"
        skill_id = s["id"]
        
        # Add to professions mapping
        professions.setdefault(prof, []).append(skill_id)
        
        # Build test object
        test_type = s["testType"] or "multiple-choice"
        test_obj = {
            "id": str(skill_id),
            "name": s["nombre"],
            "description": s["description"] or "",
            "type": test_type
        }
        
        if test_type == "case-study":
            # Find the scenario (the text of the first question)
            qs = questions_by_skill.get(skill_id, [])
            test_obj["scenario"] = qs[0]["text"] if qs else ""
        else:
            test_obj["questions"] = questions_by_skill.get(skill_id, [])

        tests_by_profession.setdefault(prof, []).append(test_obj)

    # Ensure all default professions keys are present even if empty
    default_professions = ["Abogado", "Contador", "Desarrollador", "Diseñador UX/UI", "Marketing Digital", "Recursos Humanos"]
    for dp in default_professions:
        if dp not in professions:
            professions[dp] = []
        if dp not in tests_by_profession:
            tests_by_profession[dp] = []

    return {
        "professions": professions,
        "testsByProfession": tests_by_profession
    }


@router.post("/technical", dependencies=[Depends(require_admin)])
def save_technical_test(
    profession: str = Query(...),
    data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    Saves (creates or updates) a technical test (TechnicalSkill) and its questions/answers.
    """
    test_id_raw = data.get("id")
    name = data.get("name")
    description = data.get("description")
    test_type = data.get("type", "multiple-choice")

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    # Try to find existing skill
    skill_id = None
    if test_id_raw:
        try:
            skill_id = int(test_id_raw)
        except ValueError:
            pass

    existing_skill = None
    if skill_id is not None:
        existing_skill = db.execute(
            text("SELECT id FROM TechnicalSkill WHERE id = :id"),
            {"id": skill_id}
        ).fetchone()

    if existing_skill:
        # Update existing TechnicalSkill
        db.execute(text("""
            UPDATE TechnicalSkill
            SET nombre = :name, description = :description, testType = :test_type, profession = :profession, activo = 1, updatedAt = GETDATE()
            WHERE id = :id
        """), {
            "name": name,
            "description": description,
            "test_type": test_type,
            "profession": profession,
            "id": skill_id
        })
    else:
        # Check if a technical skill with the same name exists but is inactive
        inactive_skill = db.execute(
            text("SELECT id FROM TechnicalSkill WHERE nombre = :name"),
            {"name": name}
        ).fetchone()

        if inactive_skill:
            skill_id = inactive_skill.id
            db.execute(text("""
                UPDATE TechnicalSkill
                SET description = :description, testType = :test_type, profession = :profession, activo = 1, updatedAt = GETDATE()
                WHERE id = :id
            """), {
                "description": description,
                "test_type": test_type,
                "profession": profession,
                "id": skill_id
            })
        else:
            # Insert new TechnicalSkill
            result = db.execute(text("""
                INSERT INTO TechnicalSkill (nombre, description, testType, profession, activo, createdAt, updatedAt)
                OUTPUT INSERTED.id
                VALUES (:name, :description, :test_type, :profession, 1, GETDATE(), GETDATE())
            """), {
                "name": name,
                "description": description,
                "test_type": test_type,
                "profession": profession
            })
            skill_id = result.fetchone()[0]

    # Delete old questions and answers for this skill
    db.execute(text("""
        DELETE FROM Answer
        WHERE questionId IN (SELECT id FROM Question WHERE technicalSkillId = :skill_id)
    """), {"skill_id": skill_id})
    
    db.execute(text("""
        DELETE FROM Question
        WHERE technicalSkillId = :skill_id
    """), {"skill_id": skill_id})

    # Save new questions and answers
    if test_type == "multiple-choice":
        questions = data.get("questions", [])
        for q in questions:
            q_text = q.get("text")
            if not q_text:
                continue
            
            # Insert Question
            q_result = db.execute(text("""
                INSERT INTO Question (text, technicalSkillId)
                OUTPUT INSERTED.id
                VALUES (:text, :skill_id)
            """), {"text": q_text, "skill_id": skill_id})
            q_id = q_result.fetchone()[0]

            # Insert Answers
            answers = q.get("answers", [])
            for a in answers:
                a_text = a.get("text")
                if not a_text:
                    continue
                db.execute(text("""
                    INSERT INTO Answer (text, isCorrect, questionId)
                    VALUES (:text, :is_correct, :q_id)
                """), {
                    "text": a_text,
                    "is_correct": 1 if a.get("isCorrect") else 0,
                    "q_id": q_id
                })
    elif test_type == "case-study":
        scenario = data.get("scenario")
        if scenario:
            # Insert single question representing the case scenario
            db.execute(text("""
                INSERT INTO Question (text, technicalSkillId)
                VALUES (:text, :skill_id)
            """), {"text": scenario, "skill_id": skill_id})

    db.commit()
    return {"success": True, "id": skill_id}


@router.delete("/technical/{test_id}", dependencies=[Depends(require_admin)])
def delete_technical_test(test_id: str, db: Session = Depends(get_db)):
    """
    Soft-deletes a technical test by setting activo = 0.
    """
    try:
        skill_id = int(test_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid test ID format")

    existing = db.execute(
        text("SELECT id FROM TechnicalSkill WHERE id = :id"),
        {"id": skill_id}
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Test not found")

    db.execute(
        text("UPDATE TechnicalSkill SET activo = 0, updatedAt = GETDATE() WHERE id = :id"),
        {"id": skill_id}
    )
    db.commit()
    return {"success": True}


@router.get("/soft", dependencies=[Depends(require_any_auth)])
def get_soft_skills(db: Session = Depends(get_db)):
    """
    Returns list of active soft skills.
    """
    rows = db.execute(text("""
        SELECT id, nombre, description
        FROM SoftSkill
        WHERE activo = 1
    """)).mappings().all()

    return [
        {
            "id": r["id"],
            "nombre": r["nombre"],
            "descripcion": r["description"] or ""
        }
        for r in rows
    ]


@router.post("/soft", dependencies=[Depends(require_admin)])
def save_soft_skill(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Creates or reactivates a soft skill.
    """
    nombre = data.get("nombre")
    descripcion = data.get("descripcion")

    if not nombre:
        raise HTTPException(status_code=400, detail="Nombre is required")

    # Check if exists (active or inactive)
    existing = db.execute(
        text("SELECT id, activo FROM SoftSkill WHERE nombre = :nombre"),
        {"nombre": nombre}
    ).fetchone()

    if existing:
        db.execute(text("""
            UPDATE SoftSkill
            SET description = :description, activo = 1, updatedAt = GETDATE()
            WHERE id = :id
        """), {
            "description": descripcion,
            "id": existing.id
        })
        skill_id = existing.id
    else:
        result = db.execute(text("""
            INSERT INTO SoftSkill (nombre, description, activo, createdAt, updatedAt)
            OUTPUT INSERTED.id
            VALUES (:nombre, :description, 1, GETDATE(), GETDATE())
        """), {
            "nombre": nombre,
            "description": descripcion
        })
        skill_id = result.fetchone()[0]

    db.commit()
    return {"success": True, "id": skill_id}


@router.delete("/soft/{skill_id}", dependencies=[Depends(require_admin)])
def delete_soft_skill(skill_id: int, db: Session = Depends(get_db)):
    """
    Soft-deletes a soft skill by setting activo = 0.
    """
    existing = db.execute(
        text("SELECT id FROM SoftSkill WHERE id = :id"),
        {"id": skill_id}
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Soft skill not found")

    db.execute(
        text("UPDATE SoftSkill SET activo = 0, updatedAt = GETDATE() WHERE id = :id"),
        {"id": skill_id}
    )
    db.commit()
    return {"success": True}


@router.get("/academic-title-mappings", dependencies=[Depends(require_any_auth)])
def get_academic_title_mappings(db: Session = Depends(get_db)):
    """Lista los mapeos titulo academico -> profesion activos."""
    ensure_academic_title_mapping_table(db)
    try:
        return {"mappings": get_active_mappings(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener mapeos: {str(e)}")


@router.post("/academic-title-mappings", dependencies=[Depends(require_admin)])
def save_academic_title_mapping(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea o actualiza un mapeo titulo academico -> profesion."""
    ensure_academic_title_mapping_table(db)
    titulo = data.get("tituloAcademico")
    profession = data.get("profession")
    mapping_id = data.get("id")

    if not titulo or not profession:
        raise HTTPException(status_code=400, detail="tituloAcademico y profession son requeridos")

    try:
        save_mapping(db, titulo, profession, mapping_id)
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar mapeo: {str(e)}")


@router.delete("/academic-title-mappings/{mapping_id}", dependencies=[Depends(require_admin)])
def delete_academic_title_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """Soft delete de un mapeo titulo academico -> profesion."""
    ensure_academic_title_mapping_table(db)
    try:
        deleted = delete_mapping(db, mapping_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Mapeo no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar mapeo: {str(e)}")
