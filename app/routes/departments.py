from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN
from pydantic import BaseModel
from typing import Optional, List, Any
from sqlalchemy.exc import IntegrityError
from datetime import datetime
router = APIRouter(prefix="/departments", tags=["Departments"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_capacity_columns(db: Session) -> None:
    """Agrega capacidadRequerida a Department y Office si no existe (idempotente)."""
    db.execute(text("""
        IF COL_LENGTH('Department', 'capacidadRequerida') IS NULL
            ALTER TABLE Department ADD capacidadRequerida INT NULL;
        IF COL_LENGTH('Office', 'capacidadRequerida') IS NULL
            ALTER TABLE Office ADD capacidadRequerida INT NULL;
    """))
    db.commit()


def validar_tope_departamento(
    db: Session,
    dep_id: int,
    capacidad_depto: Optional[int],
    capacidad_oficina_nueva: int = 0,
    office_id_excluir: Optional[int] = None,
) -> None:
    """Valida que la suma de capacidadRequerida de las oficinas del departamento
    (incluyendo la nueva/editada, excluyendo la propia si se esta editando) no
    supere la capacidad del departamento. Si el departamento no tiene capacidad
    definida (NULL, legacy), no hay tope que validar."""
    if capacidad_depto is None:
        return

    query = """
        SELECT COALESCE(SUM(capacidadRequerida), 0) FROM Office
        WHERE departmentId = :dep_id AND capacidadRequerida IS NOT NULL
    """
    params = {"dep_id": dep_id}
    if office_id_excluir is not None:
        query += " AND id != :office_id_excluir"
        params["office_id_excluir"] = office_id_excluir

    suma_actual = db.execute(text(query), params).scalar() or 0
    suma_total = suma_actual + capacidad_oficina_nueva

    if suma_total > capacidad_depto:
        raise HTTPException(
            status_code=400,
            detail=f"La suma de las oficinas ({suma_total}) supera la capacidad del departamento ({capacidad_depto})"
        )


# 🟢 GET: Traer todos los departamentos con sus oficinas, empleados y habilidades
@router.get("/", dependencies=[Depends(require_any_auth)])
def get_departments_with_employees_and_offices(db: Session = Depends(get_db)):
    """
    Devuelve una lista de departamentos con sus oficinas, empleados y habilidades asignadas.
    Si no existen departamentos, devuelve un array vacío (status 200).
    """
    ensure_capacity_columns(db)

    # 🔹 Traer todos los departamentos
    departments = db.execute(text("""
        SELECT
            d.id,
            d.nombre,
            d.description,
            d.jefeId,
            d.nivelJerarquico,
            d.parentId,
            d.capacidadRequerida,
            d.createdAt,
            d.updatedAt
        FROM Department d
        ORDER BY d.nombre
    """)).fetchall()

    result = []

    for dep in departments:
        # 🔹 Oficinas del departamento
        offices = db.execute(text("""
            SELECT
                o.id,
                o.nombre,
                o.description,
                o.jefeId,
                o.parentDepartmentId,
                o.capacidadRequerida,
                o.createdAt,
                o.updatedAt
            FROM Office o
            WHERE o.departmentId = :dep_id
            ORDER BY o.nombre
        """), {"dep_id": dep.id}).fetchall()

        office_list = []

        for office in offices:
            # 🔹 Habilidades de la oficina
            office_skills = db.execute(text("""
                SELECT 
                    s.id,
                    s.nombre,
                    s.level,
                    s.createdAt
                FROM Skill s
                WHERE s.officeId = :office_id
                ORDER BY s.nombre
            """), {"office_id": office.id}).fetchall()

            # 🔹 Empleados de la oficina
            office_employees = db.execute(text("""
                SELECT 
                    e.id, 
                    e.name,
                    e.dni,
                    e.email,
                    e.phone,
                    e.gender,
                    e.departmentId,
                    e.officeId
                FROM Employee e
                WHERE e.officeId = :office_id
                ORDER BY e.name
            """), {"office_id": office.id}).fetchall()

            office_list.append({
                "id": office.id,
                "nombre": office.nombre,
                "description": office.description,
                "jefeId": office.jefeId,
                "parentDepartmentId": office.parentDepartmentId,
                "capacidadRequerida": office.capacidadRequerida,
                "asignados": len(office_employees),
                "createdAt": office.createdAt,
                "updatedAt": office.updatedAt,
                "habilidades_requeridas": [
                    {
                        "id": s.id,
                        "nombre": s.nombre,
                        "level": s.level,
                        "createdAt": s.createdAt
                    } for s in office_skills
                ],
                "employees": [
                    {
                        "id": emp.id,
                        "name": emp.name,
                        "dni": emp.dni,
                        "email": emp.email,
                        "phone": emp.phone,
                        "gender": emp.gender,
                        "departmentId": emp.departmentId,
                        "officeId": emp.officeId
                    } for emp in office_employees
                ]
            })

        # 🔹 Habilidades del departamento
        dept_skills = db.execute(text("""
            SELECT 
                s.id,
                s.nombre,
                s.level,
                s.createdAt
            FROM Skill s
            WHERE s.departmentId = :dep_id AND s.officeId IS NULL
            ORDER BY s.nombre
        """), {"dep_id": dep.id}).fetchall()

        # 🔹 Empleados del departamento (sin oficina)
        dept_employees = db.execute(text("""
            SELECT
                e.id,
                e.name,
                e.dni,
                e.email,
                e.phone,
                e.gender,
                e.departmentId,
                e.officeId
            FROM Employee e
            WHERE e.departmentId = :dep_id AND e.officeId IS NULL
            ORDER BY e.name
        """), {"dep_id": dep.id}).fetchall()

        # 🔹 Total de asignados al departamento (con o sin oficina)
        dept_total_asignados = db.execute(text("""
            SELECT COUNT(*) FROM Employee WHERE departmentId = :dep_id
        """), {"dep_id": dep.id}).scalar() or 0

        # 🔹 Construir resultado
        result.append({
            "id": dep.id,
            "nombre": dep.nombre,
            "description": dep.description,
            "nivelJerarquico": dep.nivelJerarquico,
            "jefeId": dep.jefeId,
            "parentId": dep.parentId,
            "capacidadRequerida": dep.capacidadRequerida,
            "asignados": dept_total_asignados,
            "createdAt": dep.createdAt,
            "updatedAt": dep.updatedAt,
            "habilidades_requeridas": [
                {
                    "id": s.id,
                    "nombre": s.nombre,
                    "level": s.level,
                    "createdAt": s.createdAt
                } for s in dept_skills
            ],
            "offices": office_list,
            "employees": [
                {
                    "id": emp.id,
                    "name": emp.name,
                    "dni": emp.dni,
                    "email": emp.email,
                    "phone": emp.phone,
                    "gender": emp.gender,
                    "departmentId": emp.departmentId,
                    "officeId": emp.officeId
                } for emp in dept_employees
            ]
        })

    return {
        "departments": result,
        "message": "Departamentos obtenidos correctamente" if result else "No se encontraron departamentos"
    }


# 🟢 POST: Crear un nuevo departamento con habilidades y empleados
@router.post("/", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def create_department(request: Request, db: Session = Depends(get_db)):
    """
    Crea un nuevo departamento, registra sus habilidades (Skill) y asigna empleados.
    """
    ensure_capacity_columns(db)
    data = await request.json()
    print("📦 Datos recibidos para crear departamento:", data)

    nombre = data.get("nombre")
    descripcion = data.get("descripcion")
    nivel_jerarquico = data.get("nivel_jerarquico")
    jefe_id = data.get("jefeId")
    parent_id = data.get("parentId")
    capacidad_requerida = data.get("capacidadRequerida")
    habilidades = data.get("habilidades_requeridas", [])
    empleados_ids = data.get("empleadosIds", [])

    if not nombre:
        raise HTTPException(status_code=400, detail="El campo 'nombre' es obligatorio")

    if (
        capacidad_requerida is None
        or isinstance(capacidad_requerida, bool)
        or not isinstance(capacidad_requerida, (int, float))
        or capacidad_requerida < 0
    ):
        raise HTTPException(status_code=400, detail="La capacidad requerida es obligatoria")

    try:
        # 🔹 Crear el departamento (sin habilidades_requeridas, ya que va en Skill)
        result = db.execute(text("""
            INSERT INTO Department (nombre, description, nivelJerarquico, jefeId, parentId, capacidadRequerida, updatedAt, createdAt)
            OUTPUT INSERTED.id
            VALUES (:nombre, :descripcion, :nivel_jerarquico, :jefe_id, :parent_id, :capacidad_requerida, :updatedAt, :createdAt)
        """), {
            "nombre": nombre,
            "descripcion": descripcion,
            "nivel_jerarquico": nivel_jerarquico,
            "jefe_id": jefe_id,
            "parent_id": parent_id,
            "capacidad_requerida": capacidad_requerida,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }).fetchone()

        department_id = result[0]
        print(f"✅ Departamento creado con ID {department_id}")

        # 🔹 Insertar habilidades (Skill) asociadas al departamento
        if habilidades and isinstance(habilidades, list):
            for skill in habilidades:
                nombre_skill = skill.get("nombre")
                level = skill.get("level", 0)

                if not nombre_skill:
                    print("⚠️ Habilidad sin nombre, se omite:", skill)
                    continue

                db.execute(text("""
                    INSERT INTO Skill (nombre, level, departmentId, createdAt)
                    VALUES (:nombre, :level, :departmentId, :createdAt)
                """), {
                    "nombre": nombre_skill,
                    "level": level,
                    "departmentId": department_id,
                    "createdAt": datetime.utcnow()
                })
            print(f"🧩 Habilidades registradas: {[s.get('nombre') for s in habilidades]}")

        # 🔹 Asignar empleados y fijarles su SUPERIOR (managerId)
        if empleados_ids:
            for emp_id in empleados_ids:
                # Si el empleado no es el propio jefe, le asignamos el jefe como su managerId
                if emp_id != jefe_id:
                    db.execute(text("""
                        UPDATE Employee
                        SET departmentId = :dep_id, managerId = :jefe_id
                        WHERE id = :emp_id
                    """), {"dep_id": department_id, "jefe_id": jefe_id, "emp_id": emp_id})
                else:
                    db.execute(text("""
                        UPDATE Employee
                        SET departmentId = :dep_id
                        WHERE id = :emp_id
                    """), {"dep_id": department_id, "emp_id": emp_id})
            print(f"👥 Empleados asignados (y managerId actualizado): {empleados_ids}")

        # 🔹 Asegurar que el jefe del departamento pertenezca a su propio departamento
        if jefe_id:
            db.execute(text("""
                UPDATE Employee
                SET departmentId = :dep_id
                WHERE id = :jefe_id
            """), {"dep_id": department_id, "jefe_id": jefe_id})

        db.commit()
        return {"message": "Departamento creado correctamente"}

    except IntegrityError as e:
        db.rollback()
        if "Department_jefeId_key" in str(e):
            raise HTTPException(
                status_code=400,
                detail=f"El empleado con ID {data.get('jefeId')} ya es jefe de otro departamento"
            )
        raise HTTPException(status_code=500, detail="Error al crear el departamento")

class UpdateDepartmentRequest(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    nivel_jerarquico: Optional[int] = None
    jefeId: Optional[int] = None
    parentId: Optional[int] = None
    capacidadRequerida: Optional[int] = None
    empleadosIds: Optional[List[int]] = None
    habilidades_requeridas: Optional[List[Any]] = None

# --- PUT: Actualizar un departamento ---
@router.put("/{dep_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def update_department(dep_id: int, payload: UpdateDepartmentRequest, db: Session = Depends(get_db)):
    ensure_capacity_columns(db)
    result = db.execute(text("SELECT id FROM Department WHERE id = :id"), {"id": dep_id}).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")

    if payload.capacidadRequerida is not None:
        validar_tope_departamento(db, dep_id, payload.capacidadRequerida)

    try:
        db.execute(text("""
            UPDATE Department
            SET nombre = COALESCE(:nombre, nombre),
                description = COALESCE(:description, description),
                nivelJerarquico = COALESCE(:nivel_jerarquico, nivelJerarquico),
                jefeId = :jefeId,
                parentId = :parentId,
                capacidadRequerida = COALESCE(:capacidadRequerida, capacidadRequerida),
                updatedAt = CURRENT_TIMESTAMP
            WHERE id = :dep_id
        """), {
            "dep_id": dep_id,
            "nombre": payload.nombre,
            "description": payload.descripcion,
            "nivel_jerarquico": payload.nivel_jerarquico,
            "jefeId": payload.jefeId,
            "parentId": payload.parentId,
            "capacidadRequerida": payload.capacidadRequerida
        })

        # Process Employee assignments: Clean previous associations and link new ones
        if payload.empleadosIds is not None:
            # Quitamos el departamento anterior, pero no el managerId (podria depender de otro lado, o podríamos ponerlo a NULL si lo deseamos)
            db.execute(text("UPDATE Employee SET departmentId = NULL WHERE departmentId = :dep_id"), {"dep_id": dep_id})
            if payload.empleadosIds:
                for emp_id in payload.empleadosIds:
                    # Asignar managerId como jefeId del departamento si el empleado NO es el propio jefe
                    if payload.jefeId and emp_id != payload.jefeId:
                        db.execute(text("UPDATE Employee SET departmentId = :dep_id, managerId = :jefe_id WHERE id = :emp_id"), 
                                   {"dep_id": dep_id, "jefe_id": payload.jefeId, "emp_id": emp_id})
                    else:
                        db.execute(text("UPDATE Employee SET departmentId = :dep_id WHERE id = :emp_id"), 
                                   {"dep_id": dep_id, "emp_id": emp_id})
        
        if payload.jefeId is not None:
            if payload.empleadosIds is None:
                # Si solo cambió el jefeId de este departamento, propagamos el cambio a los empleados del departamento
                db.execute(text("UPDATE Employee SET managerId = :jefe_id WHERE departmentId = :dep_id AND id != :jefe_id"), 
                           {"jefe_id": payload.jefeId, "dep_id": dep_id})
            
            # Garantizar explícitamente que el nuevo jefe quede guardado bajo su departamento
            db.execute(text("UPDATE Employee SET departmentId = :dep_id WHERE id = :jefe_id"), 
                       {"jefe_id": payload.jefeId, "dep_id": dep_id})

        # Process Habilidades assignments
        if payload.habilidades_requeridas is not None:
            db.execute(text("DELETE FROM Skill WHERE departmentId = :dep_id AND officeId IS NULL"), {"dep_id": dep_id})
            for skill in payload.habilidades_requeridas:
                if not isinstance(skill, dict) or not skill.get("nombre"):
                    continue
                db.execute(text("""
                    INSERT INTO Skill (nombre, level, departmentId, createdAt)
                    VALUES (:nombre, :level, :dep_id, GETDATE())
                """), {
                    "nombre": skill.get("nombre"),
                    "level": int(skill.get("level", 0)) if str(skill.get("level", 0)).isdigit() else 0,
                    "dep_id": dep_id
                })

        db.commit()
        return {"message": f"Departamento {dep_id} actualizado correctamente."}
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e)
        if "Department_jefeId_key" in error_msg:
            raise HTTPException(
                status_code=400,
                detail=f"El empleado con ID {payload.jefeId} ya es jefe de otro departamento o registro duplicado."
            )
        raise HTTPException(status_code=500, detail=f"Error al actualizar el departamento: {error_msg}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error inesperado al actualizar el departamento: {str(e)}")




# --- DELETE: Eliminar un departamento ---
@router.delete("/{dep_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def delete_department(dep_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM Department WHERE id = :id"), {"id": dep_id})
    db.commit()
    return {"message": f"Departamento {dep_id} eliminado correctamente."}



# --- POST: Crear una oficina dentro de un departamento ---
@router.post("/{dep_id}/offices", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def create_office(dep_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Crea una nueva oficina dentro de un departamento.
    Además, inserta las habilidades relacionadas en la tabla Skill.
    """
    ensure_capacity_columns(db)
    data = await request.json()
    print("📥 Datos recibidos:", data)

    nombre = data.get("nombre")
    description = data.get("description")
    jefeId = data.get("jefeId")
    parentDepartmentId = data.get("parentDepartmentId")
    capacidad_requerida = data.get("capacidadRequerida")
    habilidades_requeridas = data.get("habilidades_requeridas", [])

    if (
        capacidad_requerida is None
        or isinstance(capacidad_requerida, bool)
        or not isinstance(capacidad_requerida, (int, float))
        or capacidad_requerida < 0
    ):
        raise HTTPException(status_code=400, detail="La capacidad requerida es obligatoria")

    # 🔹 Verificar que exista el departamento
    dep_exists = db.execute(
        text("SELECT id, capacidadRequerida FROM Department WHERE id = :id"),
        {"id": dep_id}
    ).mappings().first()

    if not dep_exists:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")

    validar_tope_departamento(db, dep_id, dep_exists["capacidadRequerida"], capacidad_oficina_nueva=capacidad_requerida)

    # 🔹 Insertar la nueva oficina con parentDepartmentId
    office_result = db.execute(text("""
        INSERT INTO Office (nombre, description, departmentId, jefeId, parentDepartmentId, capacidadRequerida, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :description, :dep_id, :jefeId, :parentDepartmentId, :capacidadRequerida, GETDATE(), GETDATE())
    """), {
        "nombre": nombre,
        "description": description,
        "dep_id": dep_id,
        "jefeId": jefeId,
        "parentDepartmentId": parentDepartmentId,
        "capacidadRequerida": capacidad_requerida
    })

    office_id = office_result.fetchone()[0]

    # 🔹 Insertar las habilidades asociadas
    for skill in habilidades_requeridas:
        db.execute(text("""
            INSERT INTO Skill (nombre, level, departmentId, officeId, createdAt)
            VALUES (:nombre, :level, :dep_id, :office_id, GETDATE())
        """), {
            "nombre": skill.get("nombre"),
            "level": skill.get("level", 0),
            "dep_id": dep_id,
            "office_id": office_id
        })

    db.commit()

    return {
        "message": f"Oficina '{nombre}' creada en el departamento {dep_id}.",
        "office_id": office_id
    }




# --- PUT: Asignar empleado a un departamento ---
@router.put("/{dep_id}/assign-employee/{emp_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def assign_employee_to_department(dep_id: int, emp_id: int, db: Session = Depends(get_db)):
    dep = db.execute(text("SELECT id FROM Department WHERE id = :id"), {"id": dep_id}).fetchone()
    emp = db.execute(text("SELECT id FROM Employee WHERE id = :id"), {"id": emp_id}).fetchone()
    if not dep or not emp:
        raise HTTPException(status_code=404, detail="Departamento o empleado no encontrado")

    db.execute(text("""
        UPDATE Employee SET departmentId = :dep_id WHERE id = :emp_id
    """), {"dep_id": dep_id, "emp_id": emp_id})
    db.commit()
    return {"message": f"Empleado {emp_id} asignado al departamento {dep_id}."}




# --- PUT: Asignar empleado a una oficina ---
@router.put("/office/{office_id}/assign-employee/{emp_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def assign_employee_to_office(office_id: int, emp_id: int, db: Session = Depends(get_db)):
    off = db.execute(text("SELECT id FROM Office WHERE id = :id"), {"id": office_id}).fetchone()
    emp = db.execute(text("SELECT id FROM Employee WHERE id = :id"), {"id": emp_id}).fetchone()
    if not off or not emp:
        raise HTTPException(status_code=404, detail="Oficina o empleado no encontrado")

    db.execute(text("""
        UPDATE Employee SET officeId = :office_id WHERE id = :emp_id
    """), {"office_id": office_id, "emp_id": emp_id})
    db.commit()
    return {"message": f"Empleado {emp_id} asignado a la oficina {office_id}."}


# 🟢 PUT: Actualizar oficina
@router.put("/office/{office_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def update_office(office_id: int, request: Request, db: Session = Depends(get_db)):
    ensure_capacity_columns(db)
    data = await request.json()

    # Verificar existencia
    office = db.execute(text("SELECT id, departmentId, capacidadRequerida FROM Office WHERE id = :id"), {"id": office_id}).fetchone()
    if not office:
        raise HTTPException(status_code=404, detail="Oficina no encontrada")

    nueva_capacidad = data.get("capacidadRequerida")
    if nueva_capacidad is not None:
        dep_row = db.execute(
            text("SELECT capacidadRequerida FROM Department WHERE id = :id"),
            {"id": office["departmentId"]}
        ).mappings().first()
        capacidad_depto = dep_row["capacidadRequerida"] if dep_row else None
        validar_tope_departamento(
            db, office["departmentId"], capacidad_depto,
            capacidad_oficina_nueva=nueva_capacidad, office_id_excluir=office_id
        )

    try:
        db.execute(text("""
            UPDATE Office
            SET nombre = COALESCE(:nombre, nombre),
                description = COALESCE(:description, description),
                jefeId = :jefeId,
                parentDepartmentId = :parentDepartmentId,
                capacidadRequerida = COALESCE(:capacidadRequerida, capacidadRequerida),
                updatedAt = GETDATE()
            WHERE id = :office_id
        """), {
            "office_id": office_id,
            "nombre": data.get("nombre"),
            "description": data.get("descripcion"),
            "jefeId": data.get("jefeId"),
            "parentDepartmentId": data.get("parentDepartmentId"),
            "capacidadRequerida": nueva_capacidad
        })
        
        # Manejar actualización de empleados asignados
        if "empleadosIds" in data:
            db.execute(text("UPDATE Employee SET officeId = NULL WHERE officeId = :office_id"), {"office_id": office_id})
            if data["empleadosIds"]:
                jefe_oficina = data.get("jefeId")
                for emp_id in data["empleadosIds"]:
                    if jefe_oficina and emp_id != jefe_oficina:
                        db.execute(text("UPDATE Employee SET officeId = :office_id, managerId = :jefe_id WHERE id = :emp_id"), 
                                   {"office_id": office_id, "jefe_id": jefe_oficina, "emp_id": emp_id})
                    else:
                        db.execute(text("UPDATE Employee SET officeId = :office_id WHERE id = :emp_id"), 
                                   {"office_id": office_id, "emp_id": emp_id})
        
        if data.get("jefeId") is not None:
            if "empleadosIds" not in data:
                # Propagar cambio de managerId si solo cambió el jefe de oficina y no fue array de asignaciones
                db.execute(text("UPDATE Employee SET managerId = :jefe_id WHERE officeId = :office_id AND id != :jefe_id"), 
                           {"jefe_id": data.get("jefeId"), "office_id": office_id})
            
            # Garantizar que el jefe de área este asignado a su oficina
            db.execute(text("UPDATE Employee SET officeId = :office_id WHERE id = :jefe_id"), 
                       {"jefe_id": data.get("jefeId"), "office_id": office_id})

        # Process Habilidades assignments
        if "habilidades_requeridas" in data:
            habilidades = data["habilidades_requeridas"]
            db.execute(text("DELETE FROM Skill WHERE officeId = :office_id"), {"office_id": office_id})
            
            if habilidades and isinstance(habilidades, list):
                dep_id_for_skill = office[1]
                for skill in habilidades:
                    if not isinstance(skill, dict) or not skill.get("nombre"):
                        continue
                    db.execute(text("""
                        INSERT INTO Skill (nombre, level, departmentId, officeId, createdAt)
                        VALUES (:nombre, :level, :dep_id, :office_id, GETDATE())
                    """), {
                        "nombre": skill.get("nombre"),
                        "level": int(skill.get("level", 0)) if str(skill.get("level", 0)).isdigit() else 0,
                        "dep_id": dep_id_for_skill,
                        "office_id": office_id
                    })
                           
        db.commit()
        return {"message": f"Oficina {office_id} actualizada correctamente."}
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error de integridad al actualizar oficina: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar oficina: {str(e)}")


# 🟢 DELETE: Eliminar oficina
@router.delete("/office/{office_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def delete_office(office_id: int, db: Session = Depends(get_db)):
    # Desvincular empleados antes de borrar
    db.execute(text("UPDATE Employee SET officeId = NULL WHERE officeId = :id"), {"id": office_id})
    # Borrar oficina
    db.execute(text("DELETE FROM Office WHERE id = :id"), {"id": office_id})
    db.commit()
    return {"message": f"Oficina {office_id} eliminada correctamente."}