# Fix: Persistencia del guardado de CV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar `PUT /employee/{employee_id}` para que persista las 4 secciones del CV que hoy descarta silenciosamente (`workExperience`, `languages`, `certifications`, `technicalSkills`, `softSkillsArray`), y permitir que un empleado edite su propio CV (no solo un admin).

**Architecture:** Una sola función (`update_employee` en `app/routes/employee.py`) se extiende: cambio de dependencia de permisos + chequeo inline self-or-admin, y 5 bloques nuevos de DELETE+INSERT (uno por sección), siguiendo exactamente el patrón ya usado para `AcademicFormation` en el mismo handler. Todo dentro de la misma transacción/`try` ya existente.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server vía pyodbc.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-26-fix-cv-save-persistence-design.md`
- Cada sección solo se borra+reinserta si la clave está presente en el body (`data.get(...)` truthy) — igual que el comportamiento actual de `AcademicFormation`. No tocar lo que el frontend no envió.
- Una sola transacción: todo dentro del `try/except` existente con un único `db.commit()` al final; si algo falla, rollback de todo.
- No se crean endpoints nuevos ni se cambia la firma de la función (`employee_id: int, data: dict = Body(...), db: Session`).
- No se toca el flujo de validación de habilidades con IA (`TestModal`/`SkillTest`, `/tests/skills/*`).
- No hay test suite automatizado en este repo — verificación manual vía `curl`/frontend.

---

### Task 1: Cambiar permisos a self-or-admin

**Files:**
- Modify: `app/routes/employee.py:5, 602-603`

**Interfaces:**
- Consumes: `get_current_user` (ya existe en `app/auth_middleware.py`, retorna `{usuario, roleId, employeeId}`), `require_any_auth` (ya existe, ya importado en este archivo).
- Produces: nada nuevo — `update_employee` sigue teniendo la misma firma pública (mismo path, mismo método).

- [ ] **Step 1: Importar `get_current_user` y `ROLE_ADMIN` ya están disponibles**

Antes (línea 5):
```python
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN
```

Después (sin cambios — ya importa todo lo necesario; `get_current_user` se importa además):
```python
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN, get_current_user
```

- [ ] **Step 2: Cambiar la dependencia del endpoint y agregar el chequeo inline**

Antes (líneas 602-604):
```python
@router.put("/{employee_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def update_employee(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    print("🟢 Datos recibidos para actualizar empleado:", {k: v for k, v in data.items() if k != "photo"})
```

Después:
```python
@router.put("/{employee_id}", dependencies=[Depends(require_any_auth)])
def update_employee(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    if current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenés permiso para editar este empleado")

    print("🟢 Datos recibidos para actualizar empleado:", {k: v for k, v in data.items() if k != "photo"})
```

- [ ] **Step 3: Verificar que el servidor levanta sin errores**

Run: `python -c "import app.routes.employee"`
Expected: sin `ImportError`/`SyntaxError` (la salida del comando es vacía si no hay errores).

- [ ] **Step 4: Commit**

```bash
git add app/routes/employee.py
git commit -m "fix: permitir que un empleado edite su propio CV en PUT /employee/{id}"
```

---

### Task 2: Persistir las 5 secciones faltantes del CV

**Files:**
- Modify: `app/routes/employee.py:634-668` (bloque de persistencia, justo después del UPDATE de campos básicos y antes de `db.commit()`)

**Interfaces:**
- Consumes: el chequeo de permisos de la Task 1 (ya aplicado antes de llegar a este bloque).
- Produces: nada nuevo — el endpoint sigue devolviendo `{"message": "Empleado y formaciones actualizados correctamente"}`.

- [ ] **Step 1: Agregar persistencia de `workExperience`, `languages` y `certifications` después del bloque de `AcademicFormation`**

Antes (líneas 634-659, el bloque completo de `AcademicFormation` hasta el `db.commit()`):
```python
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

        db.commit()
```

Después:
```python
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
                    INSERT INTO WorkExperience (employeeId, position, company, industry, location, startDate, endDate, isCurrent, activo, contractType)
                    VALUES (:employeeId, :position, :company, :industry, :location, :startDate, :endDate, :isCurrent, :activo, :contractType)
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
                })

        # 🔹 4️⃣ Actualizar Idiomas (Language)
        languages_data = data.get("languages", [])
        if languages_data:
            print(f"🗣️ Actualizando {len(languages_data)} idiomas...")
            db.execute(text("DELETE FROM Language WHERE employeeId = :id"), {"id": employee_id})

            for record in languages_data:
                db.execute(text("""
                    INSERT INTO Language (employeeId, language, level, certification, activo, attachment)
                    VALUES (:employeeId, :language, :level, :certification, :activo, :attachment)
                """), {
                    "employeeId":   employee_id,
                    "language":     record.get("language"),
                    "level":        record.get("level"),
                    "certification": record.get("certification"),
                    "activo":       1,
                    "attachment":   record.get("attachment"),
                })

        # 🔹 5️⃣ Actualizar Certificaciones (Certification)
        certifications_data = data.get("certifications", [])
        if certifications_data:
            print(f"📜 Actualizando {len(certifications_data)} certificaciones...")
            db.execute(text("DELETE FROM Certification WHERE employeeId = :id"), {"id": employee_id})

            for record in certifications_data:
                db.execute(text("""
                    INSERT INTO Certification (employeeId, name, institution, issueDate, validUntil, activo, attachment)
                    VALUES (:employeeId, :name, :institution, :issueDate, :validUntil, :activo, :attachment)
                """), {
                    "employeeId":  employee_id,
                    "name":        record.get("name"),
                    "institution": record.get("institution"),
                    "issueDate":   record.get("date"),
                    "validUntil":  record.get("validUntil") or None,
                    "activo":      1,
                    "attachment":  record.get("attachment"),
                })

        # 🔹 6️⃣ Actualizar Habilidades Técnicas (EmployeeTechnicalSkill)
        technical_skills_data = data.get("technicalSkills", [])
        if technical_skills_data:
            print(f"🛠️ Actualizando {len(technical_skills_data)} habilidades técnicas...")
            db.execute(text("DELETE FROM EmployeeTechnicalSkill WHERE employeeId = :id"), {"id": employee_id})

            for record in technical_skills_data:
                db.execute(text("""
                    INSERT INTO EmployeeTechnicalSkill (employeeId, technicalSkillId, level, certified)
                    VALUES (:employeeId, :technicalSkillId, :level, :certified)
                """), {
                    "employeeId":       employee_id,
                    "technicalSkillId": record.get("technicalSkillId"),
                    "level":            record.get("level"),
                    "certified":        bool(record.get("certified")),
                })

        # 🔹 7️⃣ Actualizar Habilidades Blandas seleccionadas (EmployeeSoftSkill)
        soft_skills_array = data.get("softSkillsArray", [])
        if soft_skills_array:
            print(f"🤝 Actualizando {len(soft_skills_array)} habilidades blandas seleccionadas...")
            db.execute(text("DELETE FROM EmployeeSoftSkill WHERE employeeId = :id"), {"id": employee_id})

            for soft_skill_id in soft_skills_array:
                db.execute(text("""
                    INSERT INTO EmployeeSoftSkill (employeeId, softSkillId, level, skillStatusId)
                    VALUES (:employeeId, :softSkillId, NULL, NULL)
                """), {
                    "employeeId":  employee_id,
                    "softSkillId": soft_skill_id,
                })

        db.commit()
```

- [ ] **Step 2: Verificar que el servidor levanta sin errores de sintaxis**

Run: `python -c "import app.routes.employee"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 3: Verificación manual end-to-end (requiere servidor corriendo y datos de prueba)**

Esto no es automatizable sin test suite — se documenta como guía de verificación manual, no como step de CI:

1. Levantar el backend (`uvicorn app.main:app --reload` o el comando habitual del proyecto).
2. Loguearse como un empleado no-admin, abrir su CV en el frontend, activar modo edición.
3. Agregar una experiencia laboral, un idioma y una certificación; seleccionar al menos una habilidad blanda nueva; guardar.
4. Recargar la página (F5) y confirmar que las 4 secciones muestran los datos recién agregados (antes del fix, desaparecían).
5. Repetir el guardado con un usuario admin editando el CV de otro empleado — debe funcionar igual.
6. Con un empleado no-admin, intentar (vía `curl` o herramienta similar) un `PUT /employee/{otro_id}` con un `id` que no es el suyo — debe devolver 403.

- [ ] **Step 4: Commit**

```bash
git add app/routes/employee.py
git commit -m "fix: persistir workExperience, languages, certifications, technicalSkills y softSkillsArray al guardar el CV"
```
