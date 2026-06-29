from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN, get_current_user
from datetime import datetime
router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(prefix="/employee", tags=["Employee"])


# ===============================================
# GET: Obtener información completa de un empleado
# ===============================================
@router.get("/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_employee_details(employee_id: int, db: Session = Depends(get_db)):
    print(employee_id)
    
    # Consulta principal del empleado
    query = text("""
        SELECT
            e.id,
            e.dni,
            e.name,
            e.email,
            e.birthDate,
            e.gender,
            e.address,
            e.phone,
            e.photo,
            e.status,
            e.productivityScore,
            e.horas,
            e.departmentId,
            e.officeId,
            e.managerId,
            e.cronogramaId,
            e.jornadaId,

            -- Manager (jefe directo)
            m.name AS manager_name,

            -- Department
            d.nombre AS department_nombre,
            d.nivelJerarquico AS department_nivelJerarquico,

            -- Office
            o.nombre AS office_nombre,

            -- Última licencia activa
            l.type AS licencia_type,
            l.startDate AS licencia_startDate,
            l.endDate AS licencia_endDate,
            l.status AS licencia_status,
            l.mensajeOriginal AS licencia_mensajeOriginal,
            
            -- Condicion Laboral
            c.tipoContrato,
            c.fechaIngreso,
            c.fechaPlanta,
            c.categoria,
            c.fechaCategoria,
            c.position AS condicion_position,

            -- Horario
            h.horaInicio,
            h.horaFin,
            h.horasTrabajo,

            -- Jornada Laboral
            j.nombre AS jornada_nombre,
            j.horasDia AS jornada_horasDia

        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON e.id = c.employeeId
        LEFT JOIN License l ON e.id = l.employeeId AND l.status = 'Activa'
        LEFT JOIN Employee m ON e.managerId = m.id
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        WHERE e.id = :id
    """)
    result = db.execute(query, {"id": employee_id}).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Technical Skills
    technical_skills_query = text("""
        SELECT 
            id,
            technicalSkillId,
            level,
            certified,
            createdAt
        FROM EmployeeTechnicalSkill
        WHERE employeeId = :id
        ORDER BY createdAt DESC
    """)
    technical_skills = db.execute(technical_skills_query, {"id": employee_id}).mappings().all()

    # Soft Skills
    soft_skills_query = text("""
        SELECT 
            es.id,
            es.softSkillId,
            es.level,
            es.skillStatusId,
            es.createdAt,
            s.nombre
        FROM EmployeeSoftSkill es
        JOIN SoftSkill s ON es.softSkillId = s.id
        WHERE es.employeeId = :id
        ORDER BY es.createdAt DESC
    """)
    soft_skills = db.execute(soft_skills_query, {"id": employee_id}).mappings().all()

    # Certifications
    certifications_query = text("""
        SELECT 
            id,
            name,
            institution,
            issueDate,
            validUntil,
            activo,
            attachment
        FROM Certification
        WHERE employeeId = :id AND activo = 1
        ORDER BY issueDate DESC
    """)
    certifications = db.execute(certifications_query, {"id": employee_id}).mappings().all()

    # Academic Records
    academic_records_query = text("""
        SELECT 
            id,
            profession,
            title,
            institution,
            level,
            status,
            startDate,
            endDate,
            activo AS academic_activo,
            attachment,
            isVerified
        FROM AcademicRecord
        WHERE employeeId = :id AND activo = 1
        ORDER BY startDate DESC
    """)
    academic_records = db.execute(academic_records_query, {"id": employee_id}).mappings().all()

    # Work Experience
    work_experience_query = text("""
        SELECT 
            id,
            position,
            company,
            industry,
            location,
            startDate,
            endDate,
            isCurrent,
            activo AS work_activo,
            contractType
        FROM WorkExperience
        WHERE employeeId = :id AND activo = 1
        ORDER BY startDate DESC
    """)
    work_experience = db.execute(work_experience_query, {"id": employee_id}).mappings().all()

    # Languages
    languages_query = text("""
        SELECT 
            id,
            language,
            level,
            certification,
            activo AS lang_activo,
            attachment
        FROM Language
        WHERE employeeId = :id AND activo = 1
        ORDER BY createdAt DESC
    """)
    languages = db.execute(languages_query, {"id": employee_id}).mappings().all()

    # Feedbacks Given
    feedbacks_given_query = text("""
        SELECT 
            f.id,
            f.evaluatedId,
            e.name AS evaluated_name,
            f.softSkillId,
            f.activo AS feedback_activo,
            f.createdAt
        FROM Feedback f
        LEFT JOIN Employee e ON f.evaluatedId = e.id
        WHERE f.evaluatorId = :id AND f.activo = 1
        ORDER BY f.createdAt DESC
    """)
    feedbacks_given = db.execute(feedbacks_given_query, {"id": employee_id}).mappings().all()

    # Feedbacks Received
    feedbacks_received_query = text("""
        SELECT 
            f.id,
            f.evaluatorId,
            e.name AS evaluator_name,
            f.softSkillId,
            f.createdAt
        FROM Feedback f
        INNER JOIN Employee e ON f.evaluatorId = e.id
        WHERE f.evaluatedId = :id AND f.activo = 1
        ORDER BY f.createdAt DESC
    """)
    feedbacks_received = db.execute(feedbacks_received_query, {"id": employee_id}).mappings().all()

    # Aprobaciones (como supervisor)
    aprobaciones_query = text("""
        SELECT 
            a.id,
            a.licenseId,
            a.fecha,
            a.accion,
            a.observacion,
            l.type AS license_type,
            l.employeeId AS license_employeeId,
            e.name AS license_employee_name
        FROM Aprobaciones a
        INNER JOIN License l ON a.licenseId = l.id
        INNER JOIN Employee e ON l.employeeId = e.id
        WHERE a.supervisorId = :id
        ORDER BY a.fecha DESC
    """)
    aprobaciones = db.execute(aprobaciones_query, {"id": employee_id}).mappings().all()

    # Reseñas de Rendimiento
    resenas_query = text("""
        SELECT
            id,
            period,
            score,
            fortaleza,
            areademejora,
            createdAt
        FROM ResenasDeRendimiento
        WHERE employeeId = :id
        ORDER BY createdAt DESC
    """)
    resenas = db.execute(resenas_query, {"id": employee_id}).mappings().all()

    # Satisfacción Métrica
    satisfaccion_query = text("""
        SELECT
            SatisfaccionGeneral,
            SatisfaccionLaboral,
            SatisfaccionEquipo,
            SatisfaccionLiderazgo,
            SatisfaccionCrecimientoCarrera,
            FechaUltimaEncuesta
        FROM SatisfaccionMetrica
        WHERE employeeId = :id
    """)
    satisfaccion = db.execute(satisfaccion_query, {"id": employee_id}).mappings().first()

    # Critical Events
    critical_events_query = text("""
        SELECT
            id,
            type,
            description,
            createdAt
        FROM CriticalEvents
        WHERE employeeId = :id
        ORDER BY createdAt DESC
    """)
    critical_events = db.execute(critical_events_query, {"id": employee_id}).mappings().all()

    # Test Attempts
    test_attempts_query = text("""
        SELECT
            ta.id,
            ta.technicalSkillId,
            ta.academicRecordId,
            ta.score,
            ta.correctPct,
            ta.takenAt,
            ts.nombre AS technicalSkill_nombre
        FROM TestAttempt ta
        LEFT JOIN TechnicalSkill ts ON ta.technicalSkillId = ts.id
        WHERE ta.employeeId = :id
        ORDER BY ta.takenAt DESC
    """)
    test_attempts = db.execute(test_attempts_query, {"id": employee_id}).mappings().all()

    # Area Change Requests
    area_change_requests_query = text("""
        SELECT
            id,
            targetDeptId,
            targetOffId,
            reason,
            status,
            aiSuggestion,
            createdAt
        FROM AreaChangeRequest
        WHERE employeeId = :id
        ORDER BY createdAt DESC
    """)
    area_change_requests = db.execute(area_change_requests_query, {"id": employee_id}).mappings().all()

    # Tasks
    tasks_query = text("""
        SELECT id, name, productivity
        FROM Task
        WHERE employeeId = :id
    """)
    tasks = db.execute(tasks_query, {"id": employee_id}).mappings().all()

    # Licenses
    licenses_query = text("""
        SELECT id, employeeId, startDate, duracion
        FROM License
        WHERE employeeId = :id
        ORDER BY startDate DESC
    """)
    licenses_rows = [dict(r) for r in db.execute(licenses_query, {"id": employee_id}).mappings().all()]

    # Absences
    absences_query = text("""
        SELECT id, employeeId, fecha
        FROM Ausencia
        WHERE employeeId = :id
    """)
    absences_rows = [dict(r) for r in db.execute(absences_query, {"id": employee_id}).mappings().all()]

    # Complaints
    complaints_query = text("""
        SELECT id, reason, status
        FROM Complaint
        WHERE employeeId = :id
    """)
    complaints = [dict(r) for r in db.execute(complaints_query, {"id": employee_id}).mappings().all()]

    # Helpers
    def build_license_map(licenses_list: list) -> dict:
        res = {}
        for lic in licenses_list:
            start_date = lic.get("startDate")
            if start_date:
                year = (
                    str(start_date.year)
                    if hasattr(start_date, "year")
                    else str(datetime.fromisoformat(str(start_date)).year)
                )
                duration = lic.get("duracion") or 0
                res[year] = res.get(year, 0) + duration
        return res

    def build_absences_map(ausencias_list: list) -> dict:
        res = {}
        for absence in ausencias_list:
            fecha = absence.get("fecha")
            if fecha:
                year = (
                    str(fecha.year)
                    if hasattr(fecha, "year")
                    else str(datetime.fromisoformat(str(fecha)).year)
                )
                res[year] = res.get(year, 0) + 1
        return res

    # Estructura final del JSON
    employee = {
        "id": result["id"],
        "dni": result["dni"],
        "name": result["name"],
        "email": result["email"],
        "birthDate": result["birthDate"],
        "gender": result["gender"],
        "address": result["address"],
        "phone": result["phone"],
        "photo": result["photo"],
        "status": result["status"],
        "productivityScore": result["productivityScore"],
        "horas": result["horas"],
        "managerId": result["managerId"],
        "manager": {
            "name": result["manager_name"]
        } if result["managerId"] else None,
        "department": {
            "nombre": result["department_nombre"],
            "nivelJerarquico": result["department_nivelJerarquico"],
        },
        "office": {
            "nombre": result["office_nombre"],
        },
        "horario": {
            "horaInicio": result["horaInicio"],
            "horaFin": result["horaFin"],
            "horasTrabajo": result["horasTrabajo"],
        } if result["cronogramaId"] else None,
        "jornada": {
            "nombre": result["jornada_nombre"],
            "horasDia": result["jornada_horasDia"],
        } if result["jornadaId"] else None,
        "licenciaActiva": {
            "type": result["licencia_type"],
            "startDate": result["licencia_startDate"],
            "endDate": result["licencia_endDate"],
            "status": result["licencia_status"],
            "mensajeOriginal": result["licencia_mensajeOriginal"],
        },
        "condicionLaboral": {
            "tipoContrato": result["tipoContrato"],
            "fechaIngreso": result["fechaIngreso"],
            "fechaPlanta": result["fechaPlanta"],
            "categoria": result["categoria"],
            "fechaCategoria": result["fechaCategoria"],
            "position": result["condicion_position"],
        },
        "technicalSkills": [
            {
                "id": skill["id"],
                "technicalSkillId": skill["technicalSkillId"],
                "level": skill["level"],
                "certified": skill["certified"],
                "createdAt": skill["createdAt"],
            } for skill in technical_skills
        ],
        "softSkills": [
            {
                "id": skill["id"],
                "softSkillId": skill["softSkillId"],
                "level": skill["level"],
                "skillStatusId": skill["skillStatusId"],
                "createdAt": skill["createdAt"],
                "nombre": skill["nombre"],
            } for skill in soft_skills
        ],
        "certifications": [
            {
                "id": cert["id"],
                "name": cert["name"],
                "institution": cert["institution"],
                "issueDate": cert["issueDate"],
                "validUntil": cert["validUntil"],
                "activo": cert["activo"],
                "attachment": cert["attachment"],
            } for cert in certifications
        ],
        "AcademicFormation": [
            {
                "id": record["id"],
                "profession": record["profession"],
                "title": record["title"],
                "institution": record["institution"],
                "level": record["level"],
                "status": record["status"],
                "startDate": record["startDate"],
                "endDate": record["endDate"],
                "activo": record["academic_activo"],
                "attachment": record["attachment"],
                "isVerified": record["isVerified"],
            } for record in academic_records
        ],
        "workExperience": [
            {
                "id": exp["id"],
                "position": exp["position"],
                "company": exp["company"],
                "industry": exp["industry"],
                "location": exp["location"],
                "startDate": exp["startDate"],
                "endDate": exp["endDate"],
                "isCurrent": exp["isCurrent"],
                "activo": exp["work_activo"],
                "contractType": exp["contractType"],
            } for exp in work_experience
        ],
        "languages": [
            {
                "id": lang["id"],
                "language": lang["language"],
                "level": lang["level"],
                "certification": lang["certification"],
                "activo": lang["lang_activo"],
                "attachment": lang["attachment"],
            } for lang in languages
        ],
        "feedbacksGiven": [
            {
                "id": fb["id"],
                "evaluatedId": fb["evaluatedId"],
                "evaluatedName": fb["evaluated_name"],
                "softSkillId": fb["softSkillId"],
                "activo": fb["feedback_activo"],
                "createdAt": fb["createdAt"],
            } for fb in feedbacks_given
        ],
        "feedbacksReceived": [
            {
                "id": fb["id"],
                "evaluatorId": fb["evaluatorId"],
                "evaluatorName": fb["evaluator_name"],
                "softSkillId": fb["softSkillId"],
                "createdAt": fb["createdAt"],
            } for fb in feedbacks_received
        ],
        "aprobaciones": [
            {
                "id": apr["id"],
                "licenseId": apr["licenseId"],
                "licenseType": apr["license_type"],
                "employeeId": apr["license_employeeId"],
                "employeeName": apr["license_employee_name"],
                "fecha": apr["fecha"],
                "accion": apr["accion"],
                "observacion": apr["observacion"],
            } for apr in aprobaciones
        ],
        "resenasDeRendimiento": [
            {
                "id": r["id"],
                "period": r["period"],
                "score": r["score"],
                "fortaleza": r["fortaleza"],
                "areademejora": r["areademejora"],
                "createdAt": r["createdAt"],
            } for r in resenas
        ],
        "satisfaccionMetrica": {
            "satisfaccionGeneral": satisfaccion["SatisfaccionGeneral"],
            "satisfaccionLaboral": satisfaccion["SatisfaccionLaboral"],
            "satisfaccionEquipo": satisfaccion["SatisfaccionEquipo"],
            "satisfaccionLiderazgo": satisfaccion["SatisfaccionLiderazgo"],
            "satisfaccionCrecimientoCarrera": satisfaccion["SatisfaccionCrecimientoCarrera"],
            "fechaUltimaEncuesta": satisfaccion["FechaUltimaEncuesta"],
        } if satisfaccion else None,
        "criticalEvents": [
            {
                "id": ev["id"],
                "type": ev["type"],
                "description": ev["description"],
                "createdAt": ev["createdAt"],
            } for ev in critical_events
        ],
        "testAttempts": [
            {
                "id": ta["id"],
                "technicalSkillId": ta["technicalSkillId"],
                "technicalSkillNombre": ta["technicalSkill_nombre"],
                "academicRecordId": ta["academicRecordId"],
                "score": ta["score"],
                "correctPct": ta["correctPct"],
                "takenAt": ta["takenAt"],
            } for ta in test_attempts
        ],
        "areaChangeRequests": [
            {
                "id": req["id"],
                "targetDeptId": req["targetDeptId"],
                "targetOffId": req["targetOffId"],
                "reason": req["reason"],
                "status": req["status"],
                "aiSuggestion": req["aiSuggestion"],
                "createdAt": req["createdAt"],
            } for req in area_change_requests
        ],
        "tasks": [
            {
                "id": task["id"],
                "name": task["name"],
                "productivity": task["productivity"],
            } for task in tasks
        ],
        "licenses": build_license_map(licenses_rows),
        "absences": build_absences_map(absences_rows),
        "complaints": [
            {
                "id": c["id"],
                "reason": c["reason"],
                "status": c["status"],
            } for c in complaints
        ],
    }

    return employee




@router.put("/{employee_id}", dependencies=[Depends(require_any_auth)])
def update_employee(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    if current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenés permiso para editar este empleado")

    print("🟢 Datos recibidos para actualizar empleado:", {k: v for k, v in data.items() if k != "photo"})

    # Verificar existencia del empleado
    existing = db.execute(
        text("SELECT id FROM Employee WHERE id = :id"),
        {"id": employee_id}
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # 🔹 1️⃣ Actualizar datos básicos del empleado
    employee_fields = ["name", "email", "birthDate", "address", "phone", "photo", "horas", "departmentId", "officeId"]
    set_clauses = []
    params = {"id": employee_id}

    for key, value in data.items():
        if key in employee_fields:
            # Conversión de fecha
            if key == "birthDate" and isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Formato de fecha inválido (usa YYYY-MM-DD)")
            set_clauses.append(f"{key} = :{key}")
            params[key] = value

    try:
        if set_clauses:
            db.execute(text(f"UPDATE Employee SET {', '.join(set_clauses)} WHERE id = :id"), params)

        # 🔹 2️⃣ Actualizar registros relacionados (AcademicFormation)
        academic_data = data.get("AcademicFormation", [])
        if academic_data:
            print(f"📘 Actualizando {len(academic_data)} formaciones académicas...")
            db.execute(text("DELETE FROM AcademicRecord WHERE employeeId = :id"), {"id": employee_id})

            for record in academic_data:
                record_query = text("""
                    INSERT INTO AcademicRecord (employeeId, profession, title, institution, level, status, startDate, endDate, activo, attachment, updatedAt)
                    VALUES (:employeeId, :profession, :title, :institution, :level, :status, :startDate, :endDate, :activo, :attachment, :updatedAt)
                """)
                db.execute(record_query, {
                    "employeeId": employee_id,
                    "profession": record.get("profession"),
                    "title":      record.get("title"),
                    "institution":record.get("institution"),
                    "level":      record.get("level"),
                    "status":     record.get("status"),
                    "startDate":  record.get("startDate"),
                    "endDate":    record.get("endDate") or None,
                    "activo":     1,
                    "attachment": record.get("attachment"),
                    "updatedAt":  datetime.utcnow(),
                })

        # 🔹 3️⃣ Actualizar Experiencia Laboral (WorkExperience)
        work_experience_data = data.get("workExperience", [])
        if work_experience_data:
            print(f"💼 Actualizando {len(work_experience_data)} experiencias laborales...")
            db.execute(text("DELETE FROM WorkExperience WHERE employeeId = :id"), {"id": employee_id})

            for record in work_experience_data:
                db.execute(text("""
                    INSERT INTO WorkExperience (employeeId, position, company, industry, location, startDate, endDate, isCurrent, activo, contractType, createdAt, updatedAt)
                    VALUES (:employeeId, :position, :company, :industry, :location, :startDate, :endDate, :isCurrent, :activo, :contractType, :createdAt, :updatedAt)
                """), {
                    "employeeId":   employee_id,
                    "position":     record.get("position"),
                    "company":      record.get("company"),
                    "industry":     record.get("industry"),
                    "location":     record.get("location"),
                    "startDate":    record.get("startDate"),
                    "endDate":      record.get("endDate") or None,
                    "isCurrent":    bool(record.get("isCurrent")),
                    "activo":       1,
                    "contractType": record.get("contractType"),
                    "createdAt":    datetime.utcnow(),
                    "updatedAt":    datetime.utcnow(),
                })

        # 🔹 4️⃣ Actualizar Idiomas (Language)
        languages_data = data.get("languages", [])
        if languages_data:
            print(f"🗣️ Actualizando {len(languages_data)} idiomas...")
            db.execute(text("DELETE FROM Language WHERE employeeId = :id"), {"id": employee_id})

            for record in languages_data:
                db.execute(text("""
                    INSERT INTO Language (employeeId, language, level, certification, activo, attachment, createdAt, updatedAt)
                    VALUES (:employeeId, :language, :level, :certification, :activo, :attachment, :createdAt, :updatedAt)
                """), {
                    "employeeId":   employee_id,
                    "language":     record.get("language"),
                    "level":        record.get("level"),
                    "certification": record.get("certification"),
                    "activo":       1,
                    "attachment":   record.get("attachment"),
                    "createdAt":    datetime.utcnow(),
                    "updatedAt":    datetime.utcnow(),
                })

        # 🔹 5️⃣ Actualizar Certificaciones (Certification)
        certifications_data = data.get("certifications", [])
        if certifications_data:
            print(f"📜 Actualizando {len(certifications_data)} certificaciones...")
            db.execute(text("DELETE FROM Certification WHERE employeeId = :id"), {"id": employee_id})

            for record in certifications_data:
                db.execute(text("""
                    INSERT INTO Certification (employeeId, name, institution, issueDate, validUntil, activo, attachment, createdAt, updatedAt)
                    VALUES (:employeeId, :name, :institution, :issueDate, :validUntil, :activo, :attachment, :createdAt, :updatedAt)
                """), {
                    "employeeId":  employee_id,
                    "name":        record.get("name"),
                    "institution": record.get("institution"),
                    "issueDate":   record.get("date"),
                    "validUntil":  record.get("validUntil") or None,
                    "activo":      1,
                    "attachment":  record.get("attachment"),
                    "createdAt":   datetime.utcnow(),
                    "updatedAt":   datetime.utcnow(),
                })

        # 🔹 6️⃣ Actualizar Habilidades Técnicas (EmployeeTechnicalSkill)
        technical_skills_data = data.get("technicalSkills", [])
        if technical_skills_data:
            print(f"🛠️ Actualizando {len(technical_skills_data)} habilidades técnicas...")
            db.execute(text("DELETE FROM EmployeeTechnicalSkill WHERE employeeId = :id"), {"id": employee_id})

            for record in technical_skills_data:
                db.execute(text("""
                    INSERT INTO EmployeeTechnicalSkill (employeeId, technicalSkillId, level, certified, createdAt, updatedAt)
                    VALUES (:employeeId, :technicalSkillId, :level, :certified, :createdAt, :updatedAt)
                """), {
                    "employeeId":       employee_id,
                    "technicalSkillId": record.get("technicalSkillId"),
                    "level":            record.get("level"),
                    "certified":        bool(record.get("certified")),
                    "createdAt":        datetime.utcnow(),
                    "updatedAt":        datetime.utcnow(),
                })

        # 🔹 7️⃣ Actualizar Habilidades Blandas seleccionadas (EmployeeSoftSkill)
        soft_skills_array = data.get("softSkillsArray", [])
        if soft_skills_array:
            print(f"🤝 Actualizando {len(soft_skills_array)} habilidades blandas seleccionadas...")
            db.execute(text("DELETE FROM EmployeeSoftSkill WHERE employeeId = :id"), {"id": employee_id})

            for soft_skill_id in soft_skills_array:
                db.execute(text("""
                    INSERT INTO EmployeeSoftSkill (employeeId, softSkillId, level, skillStatusId, createdAt, updatedAt)
                    VALUES (:employeeId, :softSkillId, NULL, NULL, :createdAt, :updatedAt)
                """), {
                    "employeeId":  employee_id,
                    "softSkillId": soft_skill_id,
                    "createdAt":   datetime.utcnow(),
                    "updatedAt":   datetime.utcnow(),
                })

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"❌ Error al actualizar empleado {employee_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al actualizar el empleado. Los datos no fueron modificados: {e}"
        )

    return {"message": "Empleado y formaciones actualizados correctamente"}


@router.delete("/Academic/{record_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def delete_academic_record(record_id: int, db: Session = Depends(get_db)):
    """
    Elimina un registro académico (AcademicRecord) por su ID.
    """

    # Verificar si existe
    record = db.execute(
        text("SELECT id FROM AcademicRecord WHERE id = :id"),
        {"id": record_id}
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Registro académico no encontrado")

    # Eliminar registro
    db.execute(
        text("DELETE FROM AcademicRecord WHERE id = :id"),
        {"id": record_id}
    )
    db.commit()

    print(f"🗑️ Registro académico eliminado correctamente (ID: {record_id})")

    return {"message": "Registro académico eliminado correctamente", "id": record_id}


