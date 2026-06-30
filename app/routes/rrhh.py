"""
Router /rrhh — Vista principal de empleados para el módulo RRHH.

OPTIMIZACIÓN N+1 CORREGIDA:
  Antes: 1 query principal + 8 sub-queries POR EMPLEADO = O(N×8)
  Ahora: 1 query principal + 9 queries bulk para TODOS los empleados = O(9)

Las queries secundarias traen todos los registros relacionados en una sola
pasada (WHERE employeeId IN (...)) y se agrupan en Python por employeeId.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN, ROLE_USER
from datetime import datetime
from collections import defaultdict
from app.database.employee_documents import (
    ensure_table as ensure_employee_document_table,
    get_documents as get_employee_documents,
    get_document as get_employee_document,
    save_document as save_employee_document,
    delete_document as delete_employee_document,
)

router = APIRouter(prefix="/rrhh", tags=["Employees"])

# Rol RRHH: por defecto usamos ROLE_ADMIN (1) hasta confirmar IDs reales.
# Si existe un rol "RRHH" separado, agregá su id aquí: ROLE_RRHH = 3
ROLE_RRHH = ROLE_ADMIN


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers de agrupación
# ---------------------------------------------------------------------------

def _null_entry(**kwargs) -> dict:
    """Retorna un dict con todas las claves en None (estructura vacía)."""
    return {k: None for k in kwargs}


def _group_by(rows, key: str) -> dict:
    """Agrupa una lista de mappings por una clave, retornando dict de listas."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(dict(row))
    return grouped


# ---------------------------------------------------------------------------
# GET /rrhh/employees — Lista completa de empleados (O(9) queries)
# ---------------------------------------------------------------------------
@router.get("/employees", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def get_all_employees(db: Session = Depends(get_db)):
    # ── 1. Query principal: empleados con datos de departamento, oficina,
    #       manager, condición laboral, horario y satisfacción ──────────────
    employees_result = db.execute(text("""
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
            e.createdAt,
            e.updatedAt,

            -- Department
            d.nombre AS department_nombre,
            d.nivelJerarquico AS department_nivelJerarquico,

            -- Office
            o.nombre AS office_nombre,

            -- Manager
            m.name AS manager_name,

            -- Condición laboral
            c.tipoContrato AS condicion_tipoContrato,
            c.fechaIngreso AS condicion_fechaIngreso,
            c.fechaPlanta AS condicion_fechaPlanta,
            c.categoria AS condicion_categoria,
            c.position AS condicion_position,
            c.fechaCategoria AS condicion_fechaCategoria,

            -- Horario
            h.horaInicio AS horario_horaInicio,
            h.horaFin AS horario_horaFin,
            h.horasTrabajo AS horario_horasTrabajo,

            -- Satisfacción Métrica
            sm.SatisfaccionGeneral,
            sm.SatisfaccionLaboral,
            sm.SatisfaccionEquipo,
            sm.SatisfaccionLiderazgo,
            sm.SatisfaccionCrecimientoCarrera,
            sm.FechaUltimaEncuesta

        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN Employee m ON e.managerId = m.id
        LEFT JOIN CondicionLaboral c ON e.id = c.employeeId
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN SatisfaccionMetrica sm ON e.id = sm.employeeId
        ORDER BY e.name ASC
    """)).mappings().all()

    if not employees_result:
        raise HTTPException(status_code=404, detail="No se encontraron empleados")

    # Recolectar todos los IDs de empleados para las queries bulk
    employee_ids = [emp["id"] for emp in employees_result]
    ids_param = ",".join(str(i) for i in employee_ids)

    # ── 2. Subordinados bulk ─────────────────────────────────────────────────
    subordinates_bulk = db.execute(text(f"""
        SELECT id, name, email, status, managerId AS employeeId
        FROM Employee
        WHERE managerId IN ({ids_param})
        ORDER BY name ASC
    """)).mappings().all()
    subordinates_by_emp = _group_by(subordinates_bulk, "employeeId")

    # ── 3. Licencias bulk ───────────────────────────────────────────────────
    licenses_bulk = db.execute(text(f"""
        SELECT id, type, startDate, endDate, status, duracion,
               mensajeOriginal, createdAt, updatedAt, employeeId
        FROM License
        WHERE employeeId IN ({ids_param})
        ORDER BY createdAt DESC
    """)).mappings().all()
    licenses_by_emp = _group_by(licenses_bulk, "employeeId")

    # IDs de licencias para sub-queries de configuraciones, consumos y aprobaciones
    license_ids = [lic["id"] for lic in licenses_bulk]

    if license_ids:
        lic_ids_param = ",".join(str(i) for i in license_ids)

        # 3a. Configuraciones de licencias bulk
        configs_bulk = db.execute(text(f"""
            SELECT id, anio, tipo, categoria, diasTotales, createdAt, updatedAt, licenseId
            FROM ConfiguracionLicencias
            WHERE licenseId IN ({lic_ids_param})
            ORDER BY anio DESC
        """)).mappings().all()
        configs_by_lic = _group_by(configs_bulk, "licenseId")

        # 3b. Consumos de licencias bulk
        consumos_bulk = db.execute(text(f"""
            SELECT id, anio, tipo, diasConsumidos, fechaConsumo, createdAt, updatedAt, licenseId
            FROM ConsumoLicencias
            WHERE licenseId IN ({lic_ids_param})
            ORDER BY fechaConsumo DESC
        """)).mappings().all()
        consumos_by_lic = _group_by(consumos_bulk, "licenseId")

        # 3c. Aprobaciones de licencias bulk
        aprobaciones_lic_bulk = db.execute(text(f"""
            SELECT a.id, a.supervisorId, a.fecha, a.accion, a.observacion,
                   a.licenseId, e.name AS supervisor_name
            FROM Aprobaciones a
            LEFT JOIN Employee e ON a.supervisorId = e.id
            WHERE a.licenseId IN ({lic_ids_param})
            ORDER BY a.fecha DESC
        """)).mappings().all()
        aprobaciones_by_lic = _group_by(aprobaciones_lic_bulk, "licenseId")
    else:
        configs_by_lic = {}
        consumos_by_lic = {}
        aprobaciones_by_lic = {}

    # ── 4. Messages bulk ────────────────────────────────────────────────────
    messages_bulk = db.execute(text(f"""
        SELECT id, text, days, startDate, endDate, status, createdAt, employeeId
        FROM Message
        WHERE employeeId IN ({ids_param}) AND status = 'active'
        ORDER BY createdAt DESC
    """)).mappings().all()
    messages_by_emp = _group_by(messages_bulk, "employeeId")

    # ── 5. Permisos bulk ────────────────────────────────────────────────────
    permissions_bulk = db.execute(text(f"""
        SELECT id, date, exitTime, returnTime, hours, employeeId
        FROM Permission
        WHERE employeeId IN ({ids_param})
        ORDER BY date DESC
    """)).mappings().all()
    permissions_by_emp = _group_by(permissions_bulk, "employeeId")

    # ── 6. Quejas bulk ──────────────────────────────────────────────────────
    complaints_bulk = db.execute(text(f"""
        SELECT id, reason, status, createdAt, employeeId
        FROM Complaint
        WHERE employeeId IN ({ids_param})
        ORDER BY createdAt DESC
    """)).mappings().all()
    complaints_by_emp = _group_by(complaints_bulk, "employeeId")

    # ── 7. Tareas bulk ──────────────────────────────────────────────────────
    tasks_bulk = db.execute(text(f"""
        SELECT id, name, productivity, employeeId
        FROM Task
        WHERE employeeId IN ({ids_param})
        ORDER BY name ASC
    """)).mappings().all()
    tasks_by_emp = _group_by(tasks_bulk, "employeeId")

    # ── 8. Ausencias bulk ───────────────────────────────────────────────────
    ausencias_bulk = db.execute(text(f"""
        SELECT id, fecha, reason, createdAt, employeeId
        FROM Ausencia
        WHERE employeeId IN ({ids_param})
        ORDER BY fecha DESC
    """)).mappings().all()
    ausencias_by_emp = _group_by(ausencias_bulk, "employeeId")

    # ── 9. Reseñas de rendimiento bulk ──────────────────────────────────────
    resenas_bulk = db.execute(text(f"""
        SELECT id, period, score, fortaleza, areademejora, createdAt, employeeId
        FROM ResenasDeRendimiento
        WHERE employeeId IN ({ids_param})
        ORDER BY createdAt DESC
    """)).mappings().all()
    resenas_by_emp = _group_by(resenas_bulk, "employeeId")

    # ── 10. Eventos críticos bulk ───────────────────────────────────────────
    events_bulk = db.execute(text(f"""
        SELECT id, type, description, createdAt, employeeId
        FROM CriticalEvents
        WHERE employeeId IN ({ids_param})
        ORDER BY createdAt DESC
    """)).mappings().all()
    events_by_emp = _group_by(events_bulk, "employeeId")

    # ── Ensamblar respuesta final ───────────────────────────────────────────
    NULL_SUBORDINATE = _null_entry(id=None, name=None, email=None, status=None)
    NULL_MESSAGE     = _null_entry(id=None, text=None, days=None, startDate=None, endDate=None, status=None, createdAt=None)
    NULL_PERMISSION  = _null_entry(id=None, date=None, exitTime=None, returnTime=None, hours=None)
    NULL_COMPLAINT   = _null_entry(id=None, reason=None, status=None, createdAt=None)
    NULL_TASK        = _null_entry(id=None, name=None, productivity=None)
    NULL_AUSENCIA    = _null_entry(id=None, fecha=None, reason=None, createdAt=None)
    NULL_RESENA      = _null_entry(id=None, period=None, score=None, fortaleza=None, areademejora=None, createdAt=None)
    NULL_EVENT       = _null_entry(id=None, type=None, description=None, createdAt=None)
    NULL_CONFIG      = _null_entry(id=None, anio=None, tipo=None, categoria=None, diasTotales=None, createdAt=None, updatedAt=None)
    NULL_CONSUMO     = _null_entry(id=None, anio=None, tipo=None, diasConsumidos=None, fechaConsumo=None, createdAt=None, updatedAt=None)
    NULL_APROBACION  = _null_entry(id=None, supervisorId=None, supervisorName=None, fecha=None, accion=None, observacion=None)
    NULL_LICENSE     = {
        "id": None, "type": None, "startDate": None, "endDate": None,
        "status": None, "duracion": None, "mensajeOriginal": None,
        "createdAt": None, "updatedAt": None,
        "configuraciones": [NULL_CONFIG],
        "consumos": [NULL_CONSUMO],
        "aprobaciones": [NULL_APROBACION],
    }

    employees = []

    for emp in employees_result:
        emp_id = emp["id"]

        # --- Armar licencias con sus sub-datos ---
        raw_licenses = licenses_by_emp.get(emp_id, [])
        if raw_licenses:
            licenses_with_details = []
            for lic in raw_licenses:
                lic_id = lic["id"]
                licenses_with_details.append({
                    "id":              lic["id"],
                    "type":            lic["type"],
                    "startDate":       lic["startDate"],
                    "endDate":         lic["endDate"],
                    "status":          lic["status"],
                    "duracion":        lic["duracion"],
                    "mensajeOriginal": lic["mensajeOriginal"],
                    "createdAt":       lic["createdAt"],
                    "updatedAt":       lic["updatedAt"],
                    "configuraciones": [
                        {
                            "id":          c["id"],
                            "anio":        c["anio"],
                            "tipo":        c["tipo"],
                            "categoria":   c["categoria"],
                            "diasTotales": c["diasTotales"],
                            "createdAt":   c["createdAt"],
                            "updatedAt":   c["updatedAt"],
                        } for c in configs_by_lic.get(lic_id, [])
                    ] or [NULL_CONFIG],
                    "consumos": [
                        {
                            "id":            c["id"],
                            "anio":          c["anio"],
                            "tipo":          c["tipo"],
                            "diasConsumidos":c["diasConsumidos"],
                            "fechaConsumo":  c["fechaConsumo"],
                            "createdAt":     c["createdAt"],
                            "updatedAt":     c["updatedAt"],
                        } for c in consumos_by_lic.get(lic_id, [])
                    ] or [NULL_CONSUMO],
                    "aprobaciones": [
                        {
                            "id":             a["id"],
                            "supervisorId":   a["supervisorId"],
                            "supervisorName": a["supervisor_name"],
                            "fecha":          a["fecha"],
                            "accion":         a["accion"],
                            "observacion":    a["observacion"],
                        } for a in aprobaciones_by_lic.get(lic_id, [])
                    ] or [NULL_APROBACION],
                })
        else:
            licenses_with_details = [NULL_LICENSE]

        employee = {
            "id":               emp["id"],
            "dni":              emp["dni"],
            "name":             emp["name"],
            "email":            emp["email"],
            "birthDate":        emp["birthDate"],
            "gender":           emp["gender"],
            "address":          emp["address"],
            "phone":            emp["phone"],
            "photo":            emp["photo"],
            "status":           emp["status"],
            "productivityScore":emp["productivityScore"],
            "horas":            emp["horas"],
            "createdAt":        emp["createdAt"],
            "updatedAt":        emp["updatedAt"],

            "department": {
                "id":               emp["departmentId"],
                "nombre":           emp["department_nombre"],
                "nivelJerarquico":  emp["department_nivelJerarquico"],
            },
            "office": {
                "id":     emp["officeId"],
                "nombre": emp["office_nombre"],
            },
            "manager": {
                "id":   emp["managerId"],
                "name": emp["manager_name"],
            },
            "condicionLaboral": {
                "tipoContrato":   emp["condicion_tipoContrato"],
                "fechaIngreso":   emp["condicion_fechaIngreso"],
                "fechaPlanta":    emp["condicion_fechaPlanta"],
                "categoria":      emp["condicion_categoria"],
                "position":       emp["condicion_position"],
                "fechaCategoria": emp["condicion_fechaCategoria"],
            },
            "horario": {
                "id":           emp["cronogramaId"],
                "horaInicio":   emp["horario_horaInicio"],
                "horaFin":      emp["horario_horaFin"],
                "horasTrabajo": emp["horario_horasTrabajo"],
            },
            "satisfaccionMetrica": {
                "satisfaccionGeneral":           emp["SatisfaccionGeneral"],
                "satisfaccionLaboral":           emp["SatisfaccionLaboral"],
                "satisfaccionEquipo":            emp["SatisfaccionEquipo"],
                "satisfaccionLiderazgo":         emp["SatisfaccionLiderazgo"],
                "satisfaccionCrecimientoCarrera":emp["SatisfaccionCrecimientoCarrera"],
                "fechaUltimaEncuesta":           emp["FechaUltimaEncuesta"],
            },

            "subordinates":       subordinates_by_emp.get(emp_id) or [NULL_SUBORDINATE],
            "licenses":           licenses_with_details,
            "messages":           messages_by_emp.get(emp_id, []),
            "permisos":           permissions_by_emp.get(emp_id) or [NULL_PERMISSION],
            "complaints":         complaints_by_emp.get(emp_id) or [NULL_COMPLAINT],
            "tasks":              tasks_by_emp.get(emp_id) or [NULL_TASK],
            "ausencias":          ausencias_by_emp.get(emp_id) or [NULL_AUSENCIA],
            "resenasDeRendimiento": resenas_by_emp.get(emp_id) or [NULL_RESENA],
            "criticalEvents":     events_by_emp.get(emp_id) or [NULL_EVENT],
        }
        employees.append(employee)

    return {"employees": employees}


# ---------------------------------------------------------------------------
# PUT /rrhh/employee/{id}/condicion-laboral
# ---------------------------------------------------------------------------
@router.put("/employee/{employee_id}/condicion-laboral", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def update_condicion_laboral(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Actualiza la condición laboral del empleado.
    Si no existe un registro, lo crea.
    """
    print("🟢 Datos recibidos para Condición Laboral:", data)

    existing = db.execute(
        text("SELECT id FROM CondicionLaboral WHERE employeeId = :id"),
        {"id": employee_id}
    ).first()

    if existing:
        update_query = text("""
            UPDATE CondicionLaboral
            SET tipoContrato  = :tipoContrato,
                fechaIngreso  = :fechaIngreso,
                fechaPlanta   = :fechaPlanta,
                categoria     = :categoria,
                fechaCategoria= :fechaCategoria,
                position      = :position
            WHERE employeeId = :employeeId
        """)
    else:
        update_query = text("""
            INSERT INTO CondicionLaboral
                (tipoContrato, fechaIngreso, fechaPlanta, categoria, fechaCategoria, position, employeeId)
            VALUES
                (:tipoContrato, :fechaIngreso, :fechaPlanta, :categoria, :fechaCategoria, :position, :employeeId)
        """)

    db.execute(update_query, {
        "tipoContrato":    data.get("tipoContrato"),
        "fechaIngreso":    data.get("fechaIngreso"),
        "fechaPlanta":     data.get("fechaPlanta"),
        "categoria":       data.get("categoria"),
        "fechaCategoria":  data.get("fechaCategoria"),
        "position":        data.get("position"),
        "employeeId":      employee_id,
    })
    db.commit()

    return {"message": "Condición laboral actualizada correctamente"}


def decimal_to_minutes(decimal_hour: float) -> int:
    """Convierte hora decimal (ej. 9.5 → 9:30) a minutos totales."""
    horas = int(decimal_hour)
    minutos = round((decimal_hour - horas) * 60)
    return horas * 60 + minutos


# ---------------------------------------------------------------------------
# PUT /rrhh/employee/{id}/horario
# ---------------------------------------------------------------------------
@router.put("/employee/{employee_id}/horario", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def update_horario(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Actualiza o asigna un horario al empleado. Calcula horasTrabajo automáticamente."""
    print("🟢 Datos recibidos para Horario:", data)

    hora_inicio = data.get("horaInicio")
    hora_fin    = data.get("horaFin")

    if hora_inicio is None or hora_fin is None:
        raise HTTPException(status_code=400, detail="Debe enviar horaInicio y horaFin")

    try:
        minutos_inicio   = decimal_to_minutes(float(hora_inicio))
        minutos_fin      = decimal_to_minutes(float(hora_fin))
        diferencia_min   = minutos_fin - minutos_inicio
        if diferencia_min <= 0:
            raise HTTPException(status_code=400, detail="horaFin debe ser mayor que horaInicio")
        horas_trabajo = round(diferencia_min / 60, 2)
    except ValueError:
        raise HTTPException(status_code=400, detail="horaInicio y horaFin deben ser números")

    emp = db.execute(
        text("SELECT cronogramaId FROM Employee WHERE id = :id"),
        {"id": employee_id}
    ).mappings().first()

    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    cronograma_id = emp["cronogramaId"]

    if cronograma_id:
        db.execute(text("""
            UPDATE Horario
            SET horaInicio   = :horaInicio,
                horaFin      = :horaFin,
                horasTrabajo = :horasTrabajo,
                updatedAt    = GETDATE()
            WHERE id = :id
        """), {"horaInicio": hora_inicio, "horaFin": hora_fin, "horasTrabajo": horas_trabajo, "id": cronograma_id})
        action = "actualizado"
    else:
        result = db.execute(text("""
            INSERT INTO Horario (horaInicio, horaFin, horasTrabajo, updatedAt)
            OUTPUT INSERTED.id
            VALUES (:horaInicio, :horaFin, :horasTrabajo, GETDATE())
        """), {"horaInicio": hora_inicio, "horaFin": hora_fin, "horasTrabajo": horas_trabajo})

        new_horario_id = result.fetchone()[0]
        db.execute(text("""
            UPDATE Employee SET cronogramaId = :cronogramaId WHERE id = :id
        """), {"cronogramaId": new_horario_id, "id": employee_id})
        action = "creado"

    db.commit()
    return {"message": f"Horario {action} correctamente", "horasTrabajo": horas_trabajo}


# ---------------------------------------------------------------------------
# POST /rrhh/employee/{id}/permission
# ---------------------------------------------------------------------------
@router.post("/employee/{employee_id}/permission", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def create_permission(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Registra un permiso de salida/retorno para el empleado."""
    print("🟢 Datos recibidos para Permission:", data)

    exit_time   = data.get("exitTime")
    return_time = data.get("returnTime")

    if exit_time is None or return_time is None:
        raise HTTPException(status_code=400, detail="Debe enviar exitTime y returnTime")

    try:
        exit_time   = float(exit_time)
        return_time = float(return_time)
        hours       = return_time - exit_time
        if hours <= 0:
            raise HTTPException(status_code=400, detail="returnTime debe ser mayor que exitTime")
        date = datetime.now().date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato inválido en exitTime o returnTime")

    emp = db.execute(
        text("SELECT id FROM Employee WHERE id = :id"),
        {"id": employee_id}
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    db.execute(text("""
        INSERT INTO Permission (employeeId, date, exitTime, returnTime, hours)
        VALUES (:employeeId, :date, :exitTime, :returnTime, :hours)
    """), {"employeeId": employee_id, "date": date, "exitTime": exit_time, "returnTime": return_time, "hours": hours})
    db.commit()

    return {
        "message":    "Permiso registrado correctamente",
        "employeeId": employee_id,
        "date":       str(date),
        "exitTime":   exit_time,
        "returnTime": return_time,
        "hours":      hours,
    }


# ---------------------------------------------------------------------------
# GET /rrhh/org-analysis-data — Datos completos para análisis organizacional IA
# ---------------------------------------------------------------------------
@router.get("/org-analysis-data", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def get_org_analysis_data(db: Session = Depends(get_db)):
    """
    Devuelve empleados con sus habilidades blandas/técnicas y departamentos
    con habilidades requeridas para el motor de análisis organizacional con IA.
    """

    # ── 1. Empleados con datos base ──────────────────────────────────────────
    employees_result = db.execute(text("""
        SELECT
            e.id, e.name, e.dni, e.email, e.status,
            e.productivityScore, e.departmentId, e.officeId, e.managerId,
            d.nombre AS department_nombre,
            o.nombre AS office_nombre,
            c.tipoContrato, c.position AS condicion_position, c.fechaIngreso, c.categoria,
            sm.SatisfaccionGeneral, sm.SatisfaccionLaboral,
            sm.SatisfaccionEquipo, sm.SatisfaccionLiderazgo,
            sm.SatisfaccionCrecimientoCarrera, sm.FechaUltimaEncuesta
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON e.id = c.employeeId
        LEFT JOIN SatisfaccionMetrica sm ON e.id = sm.employeeId
        ORDER BY e.name ASC
    """)).mappings().all()

    if not employees_result:
        return {"employees": [], "departments": []}

    employee_ids = [emp["id"] for emp in employees_result]
    ids_param = ",".join(str(i) for i in employee_ids)

    # ── 2. Soft Skills bulk (con nombre del catálogo) ────────────────────────
    soft_skills_bulk = db.execute(text(f"""
        SELECT es.employeeId, ss.nombre, es.level
        FROM EmployeeSoftSkill es
        INNER JOIN SoftSkill ss ON es.softSkillId = ss.id
        WHERE es.employeeId IN ({ids_param})
    """)).mappings().all()
    soft_by_emp = defaultdict(list)
    for s in soft_skills_bulk:
        soft_by_emp[s["employeeId"]].append({"nombre": s["nombre"], "level": s["level"]})

    # ── 3. Technical Skills bulk (con nombre del catálogo) ───────────────────
    tech_skills_bulk = db.execute(text(f"""
        SELECT et.employeeId, ts.nombre, et.level
        FROM EmployeeTechnicalSkill et
        INNER JOIN TechnicalSkill ts ON et.technicalSkillId = ts.id
        WHERE et.employeeId IN ({ids_param})
    """)).mappings().all()
    tech_by_emp = defaultdict(list)
    for t in tech_skills_bulk:
        tech_by_emp[t["employeeId"]].append({"nombre": t["nombre"], "level": t["level"]})

    # ── 4. Licencias agrupadas por año ───────────────────────────────────────
    licenses_bulk = db.execute(text(f"""
        SELECT employeeId, YEAR(startDate) AS anio, COUNT(*) AS total
        FROM License
        WHERE employeeId IN ({ids_param})
        GROUP BY employeeId, YEAR(startDate)
    """)).mappings().all()
    licenses_by_emp = defaultdict(dict)
    for l in licenses_bulk:
        licenses_by_emp[l["employeeId"]][str(l["anio"])] = l["total"]

    # ── 5. Ausencias agrupadas por año ───────────────────────────────────────
    absences_bulk = db.execute(text(f"""
        SELECT employeeId, YEAR(fecha) AS anio, COUNT(*) AS total
        FROM Ausencia
        WHERE employeeId IN ({ids_param})
        GROUP BY employeeId, YEAR(fecha)
    """)).mappings().all()
    absences_by_emp = defaultdict(dict)
    for a in absences_bulk:
        absences_by_emp[a["employeeId"]][str(a["anio"])] = a["total"]

    # ── 6. Departamentos con habilidades requeridas ──────────────────────────
    departments_result = db.execute(text("""
        SELECT id, nombre, description, jefeId, nivelJerarquico, parentId
        FROM Department
        ORDER BY nombre
    """)).mappings().all()

    dept_ids = [d["id"] for d in departments_result]
    dept_skills = {}
    office_data = {}

    if dept_ids:
        dept_ids_param = ",".join(str(i) for i in dept_ids)

        # Skills de departamentos (sin officeId)
        dept_skills_bulk = db.execute(text(f"""
            SELECT departmentId, nombre, level
            FROM Skill
            WHERE departmentId IN ({dept_ids_param}) AND officeId IS NULL
        """)).mappings().all()
        dept_skills = defaultdict(list)
        for s in dept_skills_bulk:
            dept_skills[s["departmentId"]].append({"nombre": s["nombre"], "level": s["level"]})

        # Oficinas con habilidades
        offices_bulk = db.execute(text(f"""
            SELECT o.id, o.nombre, o.departmentId, o.jefeId
            FROM Office o
            WHERE o.departmentId IN ({dept_ids_param})
            ORDER BY o.nombre
        """)).mappings().all()

        office_ids = [o["id"] for o in offices_bulk]
        office_skills_map = defaultdict(list)
        if office_ids:
            off_ids_param = ",".join(str(i) for i in office_ids)
            office_skills_bulk = db.execute(text(f"""
                SELECT officeId, nombre, level
                FROM Skill
                WHERE officeId IN ({off_ids_param})
            """)).mappings().all()
            for s in office_skills_bulk:
                office_skills_map[s["officeId"]].append({"nombre": s["nombre"], "level": s["level"]})

        office_data = defaultdict(list)
        for o in offices_bulk:
            office_data[o["departmentId"]].append({
                "id": o["id"],
                "nombre": o["nombre"],
                "jefeId": o["jefeId"],
                "habilidades_requeridas": office_skills_map.get(o["id"], [])
            })

    # ── Ensamblar empleados ──────────────────────────────────────────────────
    current_year = str(datetime.utcnow().year)
    prev_year = str(int(current_year) - 1)

    employees = []
    for emp in employees_result:
        eid = emp["id"]
        emp_licenses = licenses_by_emp.get(eid, {})
        emp_absences = absences_by_emp.get(eid, {})

        employees.append({
            "id": eid,
            "name": emp["name"],
            "dni": emp["dni"],
            "status": emp["status"],
            "productivityScore": emp["productivityScore"] or 0,
            "departmentId": emp["departmentId"],
            "departmentName": emp["department_nombre"],
            "officeId": emp["officeId"],
            "officeName": emp["office_nombre"],
            "managerId": emp["managerId"],
            "position": emp["condicion_position"],
            "tipoContrato": emp["tipoContrato"],
            "fechaIngreso": str(emp["fechaIngreso"]) if emp["fechaIngreso"] else None,
            "categoria": emp["categoria"],
            "softSkills": soft_by_emp.get(eid, []),
            "technicalSkills": tech_by_emp.get(eid, []),
            "licenses": {
                current_year: emp_licenses.get(current_year, 0),
                prev_year: emp_licenses.get(prev_year, 0),
            },
            "absences": {
                current_year: emp_absences.get(current_year, 0),
                prev_year: emp_absences.get(prev_year, 0),
            },
            "satisfactionMetrics": {
                "overallSatisfaction": emp["SatisfaccionGeneral"] or 0,
                "jobSatisfaction": emp["SatisfaccionLaboral"] or 0,
                "teamSatisfaction": emp["SatisfaccionEquipo"] or 0,
                "leadershipSatisfaction": emp["SatisfaccionLiderazgo"] or 0,
                "careerGrowthSatisfaction": emp["SatisfaccionCrecimientoCarrera"] or 0,
            },
        })

    # ── Ensamblar departamentos ──────────────────────────────────────────────
    departments = []
    for d in departments_result:
        departments.append({
            "id": d["id"],
            "nombre": d["nombre"],
            "description": d["description"],
            "jefeId": d["jefeId"],
            "nivelJerarquico": d["nivelJerarquico"],
            "parentId": d["parentId"],
            "habilidades_requeridas": dept_skills.get(d["id"], []),
            "offices": office_data.get(d["id"], []),
        })

    return {"employees": employees, "departments": departments}


# ---------------------------------------------------------------------------
# Documentos adjuntos del legajo de un empleado
# ---------------------------------------------------------------------------
@router.get("/employee/{employee_id}/documents", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def list_employee_documents(employee_id: int, db: Session = Depends(get_db)):
    """Lista los documentos activos de un empleado (sin fileData)."""
    ensure_employee_document_table(db)
    try:
        return {"documents": get_employee_documents(db, employee_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener documentos: {str(e)}")


@router.post("/employee/{employee_id}/documents", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def upload_employee_document(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Carga un nuevo documento para el empleado."""
    ensure_employee_document_table(db)
    tipo = data.get("tipo")
    file_name = data.get("fileName")
    mime_type = data.get("mimeType")
    file_data = data.get("fileData")
    descripcion = data.get("descripcion")

    if not tipo or not file_name or not mime_type or not file_data:
        raise HTTPException(status_code=400, detail="tipo, fileName, mimeType y fileData son requeridos")

    try:
        new_id = save_employee_document(db, employee_id, tipo, descripcion, file_name, mime_type, file_data)
        return {"success": True, "id": new_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar documento: {str(e)}")


@router.get("/employee/{employee_id}/documents/{document_id}/download", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def download_employee_document(employee_id: int, document_id: int, db: Session = Depends(get_db)):
    """Devuelve un documento completo (incluyendo fileData) para ver/descargar."""
    ensure_employee_document_table(db)
    doc = get_employee_document(db, employee_id, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.delete("/employee/{employee_id}/documents/{document_id}", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def delete_employee_document_endpoint(employee_id: int, document_id: int, db: Session = Depends(get_db)):
    """Soft delete de un documento del empleado."""
    ensure_employee_document_table(db)
    try:
        deleted = delete_employee_document(db, employee_id, document_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar documento: {str(e)}")