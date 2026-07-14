# Organigrama — Capacidad Requerida por Unidad Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una capacidad requerida (número base configurable) a departamentos y oficinas del organigrama, con feedback visual "asignados/requeridos" (ej. "2/4"), validación de tope (suma de oficinas ≤ capacidad del departamento), y usarla como un tercer factor ponderado en el motor de matching de reubicación.

**Architecture:** Se agrega `capacidadRequerida INT NULL` a `Department` y `Office` (columnas nuevas, idempotentes). El "asignados" nunca se persiste — se calcula con `COUNT`/`len` sobre `Employee` en cada lectura. El backend (`app/routes/departments.py`, `app/routes/rrhh.py`) expone ambos campos en `GET /departments/` y `GET /rrhh/org-analysis-data`, y valida la capacidad al crear/editar. El frontend agrega un `InputNumber` a los formularios de edición, un badge de color en el organigrama, y un tercer factor en `reubicacion-matching-engine.ts`.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- `capacidadRequerida` es `INT NULL` en `Department` y `Office`, agregada idempotentemente por `ensure_capacity_columns(db)` (helper nuevo en `app/routes/departments.py`, importado también en `app/routes/rrhh.py`).
- El numerador ("asignados") **nunca se persiste**: para un departamento es el `COUNT` de **todos** los `Employee` con ese `departmentId` (con o sin oficina); para una oficina, el `COUNT`/`len` de `Employee` con ese `officeId`.
- **Regla del tope**: `SUM(capacidadRequerida de las oficinas del depto, ignorando NULL) ≤ capacidadRequerida del departamento`. Se valida **solo** si el departamento tiene capacidad definida (NULL = legacy, sin tope). Si se viola → 400 con el mensaje exacto `"La suma de las oficinas (N) supera la capacidad del departamento (M)"`.
- **Crear** (`POST`) un departamento o una oficina **exige** `capacidadRequerida` (400 si falta, no es numérico, es `bool`, o es negativo). **Editar** (`PUT`) la acepta opcional — si no viene, no se pisa el valor existente (`COALESCE`).
- Motor de matching (`src/app/lib/reubicacion-matching-engine.ts`): pesos `SKILL_MATCH_WEIGHT = 0.55`, `DEFICIT_WEIGHT = 0.20`, `CAPACITY_WEIGHT = 0.25`. Si la oficina candidata no tiene `capacidadRequerida` (o es `0`), el peso de capacidad se redistribuye proporcionalmente entre skill match y déficit; el score sigue siendo 0-100 vía `Math.round`.
- Sin test suite automatizada en ninguno de los dos repos — verificación por `py_compile`/`tsc --noEmit` filtrado y verificación manual final.

---

### Task 1: Backend — columnas, validación de tope, y endpoints de `departments.py`

**Files:**
- Modify: `app/routes/departments.py`

**Interfaces:**
- Produces: `ensure_capacity_columns(db: Session) -> None` y `validar_tope_departamento(db: Session, dep_id: int, capacidad_depto: Optional[int], capacidad_oficina_nueva: int = 0, office_id_excluir: Optional[int] = None) -> None` (lanza `HTTPException(400, ...)` si se viola el tope; no hace nada si `capacidad_depto is None`). `GET /departments/` devuelve en cada departamento y oficina los campos `capacidadRequerida` (int o `null`) y `asignados` (int). `POST /departments/`, `POST /departments/{dep_id}/offices` exigen `capacidadRequerida` en el body. `PUT /departments/{dep_id}`, `PUT /departments/office/{office_id}` la aceptan opcional.

- [ ] **Step 1: Agregar los helpers `ensure_capacity_columns` y `validar_tope_departamento`**

Ubicar:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
y agregar debajo:
```python
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
```

- [ ] **Step 2: Extender `GET /departments/` con `capacidadRequerida` y `asignados`**

Reemplazar:
```python
@router.get("/", dependencies=[Depends(require_any_auth)])
def get_departments_with_employees_and_offices(db: Session = Depends(get_db)):
    """
    Devuelve una lista de departamentos con sus oficinas, empleados y habilidades asignadas.
    Si no existen departamentos, devuelve un array vacío (status 200).
    """

    # 🔹 Traer todos los departamentos
    departments = db.execute(text("""
        SELECT 
            d.id, 
            d.nombre, 
            d.description, 
            d.jefeId, 
            d.nivelJerarquico,
            d.parentId,
            d.createdAt, 
            d.updatedAt
        FROM Department d
        ORDER BY d.nombre
    """)).fetchall()
```
por:
```python
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
```

Reemplazar:
```python
        offices = db.execute(text("""
            SELECT 
                o.id,
                o.nombre,
                o.description,
                o.jefeId,
                o.parentDepartmentId,
                o.createdAt,
                o.updatedAt
            FROM Office o
            WHERE o.departmentId = :dep_id
            ORDER BY o.nombre
        """), {"dep_id": dep.id}).fetchall()
```
por:
```python
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
```

Reemplazar:
```python
            office_list.append({
                "id": office.id,
                "nombre": office.nombre,
                "description": office.description,
                "jefeId": office.jefeId,
                "parentDepartmentId": office.parentDepartmentId,
                "createdAt": office.createdAt,
                "updatedAt": office.updatedAt,
                "habilidades_requeridas": [
```
por:
```python
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
```

Reemplazar:
```python
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

        # 🔹 Construir resultado
        result.append({
            "id": dep.id,
            "nombre": dep.nombre,
            "description": dep.description,
            "nivelJerarquico": dep.nivelJerarquico,
            "jefeId": dep.jefeId,
            "parentId": dep.parentId,
            "createdAt": dep.createdAt,
            "updatedAt": dep.updatedAt,
            "habilidades_requeridas": [
```
por:
```python
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
```

- [ ] **Step 3: Exigir `capacidadRequerida` en `POST /departments/` (crear departamento)**

Reemplazar:
```python
@router.post("/", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def create_department(request: Request, db: Session = Depends(get_db)):
    """
    Crea un nuevo departamento, registra sus habilidades (Skill) y asigna empleados.
    """
    data = await request.json()
    print("📦 Datos recibidos para crear departamento:", data)

    nombre = data.get("nombre")
    descripcion = data.get("descripcion")
    nivel_jerarquico = data.get("nivel_jerarquico")
    jefe_id = data.get("jefeId")
    parent_id = data.get("parentId")
    habilidades = data.get("habilidades_requeridas", [])
    empleados_ids = data.get("empleadosIds", [])

    if not nombre:
        raise HTTPException(status_code=400, detail="El campo 'nombre' es obligatorio")

    try:
        # 🔹 Crear el departamento (sin habilidades_requeridas, ya que va en Skill)
        result = db.execute(text("""
            INSERT INTO Department (nombre, description, nivelJerarquico, jefeId, parentId, updatedAt, createdAt)
            OUTPUT INSERTED.id
            VALUES (:nombre, :descripcion, :nivel_jerarquico, :jefe_id, :parent_id, :updatedAt, :createdAt)
        """), {
            "nombre": nombre,
            "descripcion": descripcion,
            "nivel_jerarquico": nivel_jerarquico,
            "jefe_id": jefe_id,
            "parent_id": parent_id,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }).fetchone()
```
por:
```python
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
```

- [ ] **Step 4: Aceptar `capacidadRequerida` (opcional, con validación de tope) en `PUT /departments/{dep_id}`**

Reemplazar:
```python
class UpdateDepartmentRequest(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    nivel_jerarquico: Optional[int] = None
    jefeId: Optional[int] = None
    parentId: Optional[int] = None
    empleadosIds: Optional[List[int]] = None
    habilidades_requeridas: Optional[List[Any]] = None

# --- PUT: Actualizar un departamento ---
@router.put("/{dep_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
def update_department(dep_id: int, payload: UpdateDepartmentRequest, db: Session = Depends(get_db)):
    result = db.execute(text("SELECT id FROM Department WHERE id = :id"), {"id": dep_id}).fetchone()
    if not result:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")

    try:
        db.execute(text("""
            UPDATE Department
            SET nombre = COALESCE(:nombre, nombre),
                description = COALESCE(:description, description),
                nivelJerarquico = COALESCE(:nivel_jerarquico, nivelJerarquico),
                jefeId = :jefeId,
                parentId = :parentId,
                updatedAt = CURRENT_TIMESTAMP
            WHERE id = :dep_id
        """), {
            "dep_id": dep_id,
            "nombre": payload.nombre,
            "description": payload.descripcion,
            "nivel_jerarquico": payload.nivel_jerarquico,
            "jefeId": payload.jefeId,
            "parentId": payload.parentId
        })
```
por:
```python
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
```

- [ ] **Step 5: Exigir `capacidadRequerida` y validar el tope en `POST /departments/{dep_id}/offices` (crear oficina)**

Reemplazar:
```python
@router.post("/{dep_id}/offices", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def create_office(dep_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Crea una nueva oficina dentro de un departamento.
    Además, inserta las habilidades relacionadas en la tabla Skill.
    """
    data = await request.json()
    print("📥 Datos recibidos:", data)

    nombre = data.get("nombre")
    description = data.get("description")
    jefeId = data.get("jefeId")
    parentDepartmentId = data.get("parentDepartmentId")
    habilidades_requeridas = data.get("habilidades_requeridas", [])

    # 🔹 Verificar que exista el departamento
    dep_exists = db.execute(
        text("SELECT id FROM Department WHERE id = :id"),
        {"id": dep_id}
    ).fetchone()

    if not dep_exists:
        raise HTTPException(status_code=404, detail="Departamento no encontrado")

    # 🔹 Insertar la nueva oficina con parentDepartmentId
    office_result = db.execute(text("""
        INSERT INTO Office (nombre, description, departmentId, jefeId, parentDepartmentId, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :description, :dep_id, :jefeId, :parentDepartmentId, GETDATE(), GETDATE())
    """), {
        "nombre": nombre,
        "description": description,
        "dep_id": dep_id,
        "jefeId": jefeId,
        "parentDepartmentId": parentDepartmentId
    })
```
por:
```python
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
```

- [ ] **Step 6: Aceptar `capacidadRequerida` (opcional, con validación de tope) en `PUT /departments/office/{office_id}`**

Reemplazar:
```python
@router.put("/office/{office_id}", dependencies=[Depends(require_roles(ROLE_ADMIN))])
async def update_office(office_id: int, request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    # Verificar existencia
    office = db.execute(text("SELECT id, departmentId FROM Office WHERE id = :id"), {"id": office_id}).fetchone()
    if not office:
        raise HTTPException(status_code=404, detail="Oficina no encontrada")
        
    try:
        db.execute(text("""
            UPDATE Office
            SET nombre = COALESCE(:nombre, nombre),
                description = COALESCE(:description, description),
                jefeId = :jefeId,
                parentDepartmentId = :parentDepartmentId,
                updatedAt = GETDATE()
            WHERE id = :office_id
        """), {
            "office_id": office_id,
            "nombre": data.get("nombre"),
            "description": data.get("descripcion"),
            "jefeId": data.get("jefeId"),
            "parentDepartmentId": data.get("parentDepartmentId")
        })
```
por:
```python
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
```

- [ ] **Step 7: Verificar que compila**

Run: `py -m py_compile app/routes/departments.py`
Expected: sin salida.

- [ ] **Step 8: Commit**

```bash
git add app/routes/departments.py
git commit -m "feat: agregar capacidad requerida y validacion de tope al organigrama"
```

---

### Task 2: Backend — extender `GET /rrhh/org-analysis-data` con capacidad y asignados

**Files:**
- Modify: `app/routes/rrhh.py`

**Interfaces:**
- Consumes: `ensure_capacity_columns` (Task 1, `app/routes/departments.py`).
- Produces: `GET /rrhh/org-analysis-data` agrega `capacidadRequerida` y `asignados` a cada departamento y a cada oficina de la respuesta.

- [ ] **Step 1: Importar `ensure_capacity_columns`**

Ubicar:
```python
from app.auth_middleware import require_roles, ROLE_ADMIN, ROLE_USER
from datetime import datetime
from collections import defaultdict
```
y reemplazar por:
```python
from app.auth_middleware import require_roles, ROLE_ADMIN, ROLE_USER
from app.routes.departments import ensure_capacity_columns
from datetime import datetime
from collections import defaultdict
```

- [ ] **Step 2: Llamar `ensure_capacity_columns` y agregar el conteo de asignados**

Reemplazar:
```python
    absences_by_emp = defaultdict(dict)
    for a in absences_bulk:
        absences_by_emp[a["employeeId"]][str(a["anio"])] = a["total"]

    # ── 6. Departamentos con habilidades requeridas ──────────────────────────
    departments_result = db.execute(text("""
        SELECT id, nombre, description, jefeId, nivelJerarquico, parentId
        FROM Department
        ORDER BY nombre
    """)).mappings().all()
```
por:
```python
    absences_by_emp = defaultdict(dict)
    for a in absences_bulk:
        absences_by_emp[a["employeeId"]][str(a["anio"])] = a["total"]

    # ── Conteo de asignados por departamento/oficina (para capacidad) ────────
    ensure_capacity_columns(db)
    dept_employee_count = defaultdict(int)
    office_employee_count = defaultdict(int)
    for emp in employees_result:
        if emp["departmentId"]:
            dept_employee_count[emp["departmentId"]] += 1
        if emp["officeId"]:
            office_employee_count[emp["officeId"]] += 1

    # ── 6. Departamentos con habilidades requeridas ──────────────────────────
    departments_result = db.execute(text("""
        SELECT id, nombre, description, jefeId, nivelJerarquico, parentId, capacidadRequerida
        FROM Department
        ORDER BY nombre
    """)).mappings().all()
```

- [ ] **Step 3: Agregar `capacidadRequerida` al SELECT de oficinas**

Reemplazar:
```python
        # Oficinas con habilidades
        offices_bulk = db.execute(text(f"""
            SELECT o.id, o.nombre, o.departmentId, o.jefeId
            FROM Office o
            WHERE o.departmentId IN ({dept_ids_param})
            ORDER BY o.nombre
        """)).mappings().all()
```
por:
```python
        # Oficinas con habilidades
        offices_bulk = db.execute(text(f"""
            SELECT o.id, o.nombre, o.departmentId, o.jefeId, o.capacidadRequerida
            FROM Office o
            WHERE o.departmentId IN ({dept_ids_param})
            ORDER BY o.nombre
        """)).mappings().all()
```

- [ ] **Step 4: Incluir `capacidadRequerida`/`asignados` en el `office_data` ensamblado**

Reemplazar:
```python
        office_data = defaultdict(list)
        for o in offices_bulk:
            office_data[o["departmentId"]].append({
                "id": o["id"],
                "nombre": o["nombre"],
                "jefeId": o["jefeId"],
                "habilidades_requeridas": office_skills_map.get(o["id"], [])
            })
```
por:
```python
        office_data = defaultdict(list)
        for o in offices_bulk:
            office_data[o["departmentId"]].append({
                "id": o["id"],
                "nombre": o["nombre"],
                "jefeId": o["jefeId"],
                "capacidadRequerida": o["capacidadRequerida"],
                "asignados": office_employee_count.get(o["id"], 0),
                "habilidades_requeridas": office_skills_map.get(o["id"], [])
            })
```

- [ ] **Step 5: Incluir `capacidadRequerida`/`asignados` en cada departamento ensamblado**

Reemplazar:
```python
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
```
por:
```python
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
            "capacidadRequerida": d["capacidadRequerida"],
            "asignados": dept_employee_count.get(d["id"], 0),
            "habilidades_requeridas": dept_skills.get(d["id"], []),
            "offices": office_data.get(d["id"], []),
        })
```

- [ ] **Step 6: Verificar que compila**

Run: `py -m py_compile app/routes/rrhh.py app/routes/departments.py`
Expected: sin salida.

- [ ] **Step 7: Commit**

```bash
git add app/routes/rrhh.py
git commit -m "feat: exponer capacidad y asignados en org-analysis-data"
```

---

### Task 3: Frontend — tipos TS (Interfaces.ts, useFormDataOrg.ts)

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts`
- Modify: `src/app/util/useFormDataOrg.ts`

**Interfaces:**
- Produces: `Department`, `Office`, `OrgAnalysisDepartment`, `EntityFormData` con `capacidadRequerida`/`asignados` — consumidos por Tasks 4 y 5.

- [ ] **Step 1: Extender `Department` en `Interfaces.ts`**

Reemplazar:
```typescript
export interface Department {
  id: number;
  nombre: string;
  descripcion: string;
  nivel_jerarquico: number;
  jefeId?: number | null;
  parentId?: number | null;
  habilidades_requeridas?: TechnicalSkill[];
  offices: Office[];
  employees?: Employee[];
}
```
por:
```typescript
export interface Department {
  id: number;
  nombre: string;
  descripcion: string;
  nivel_jerarquico: number;
  jefeId?: number | null;
  parentId?: number | null;
  capacidadRequerida?: number | null;
  asignados?: number;
  habilidades_requeridas?: TechnicalSkill[];
  offices: Office[];
  employees?: Employee[];
}
```

- [ ] **Step 2: Extender `Office` en `Interfaces.ts`**

Reemplazar:
```typescript
export interface Office {
  id: number;
  nombre: string;
  descripcion: string;
  jefeId?: number | null;
  empleadosIds?: number[];
  departmentId: number;
  parentDepartmentId?: number | null; // Nuevo campo para jerarquía
  habilidades_requeridas?: TechnicalSkill[];
}
```
por:
```typescript
export interface Office {
  id: number;
  nombre: string;
  descripcion: string;
  jefeId?: number | null;
  empleadosIds?: number[];
  departmentId: number;
  parentDepartmentId?: number | null; // Nuevo campo para jerarquía
  capacidadRequerida?: number | null;
  asignados?: number;
  habilidades_requeridas?: TechnicalSkill[];
}
```

- [ ] **Step 3: Extender `EntityFormData` en `Interfaces.ts`**

Reemplazar:
```typescript
export interface EntityFormData {
  // Campos comunes
  id?: number;
  nombre: string;
  descripcion: string;
  jefeId: number | null;
  habilidades_requeridas: TechnicalSkill[];
  // Campos específicos de Department
  nivel_jerarquico?: number;
  parentId?: number | null;
  // Campos específicos de Office
  empleadosIds?: number[];
  parentDepartmentId?: number | null; // Nuevo campo para jerarquía de oficina
}
```
por:
```typescript
export interface EntityFormData {
  // Campos comunes
  id?: number;
  nombre: string;
  descripcion: string;
  jefeId: number | null;
  capacidadRequerida?: number | null;
  habilidades_requeridas: TechnicalSkill[];
  // Campos específicos de Department
  nivel_jerarquico?: number;
  parentId?: number | null;
  // Campos específicos de Office
  empleadosIds?: number[];
  parentDepartmentId?: number | null; // Nuevo campo para jerarquía de oficina
}
```

- [ ] **Step 4: Extender `OrgAnalysisDepartment` en `Interfaces.ts`**

Reemplazar:
```typescript
export interface OrgAnalysisDepartment {
  id: number;
  nombre: string;
  description: string | null;
  jefeId: number | null;
  nivelJerarquico: number | null;
  parentId: number | null;
  habilidades_requeridas: { nombre: string; level: number }[];
  offices: {
    id: number;
    nombre: string;
    jefeId: number | null;
    habilidades_requeridas: { nombre: string; level: number }[];
  }[];
}
```
por:
```typescript
export interface OrgAnalysisDepartment {
  id: number;
  nombre: string;
  description: string | null;
  jefeId: number | null;
  nivelJerarquico: number | null;
  parentId: number | null;
  capacidadRequerida: number | null;
  asignados: number;
  habilidades_requeridas: { nombre: string; level: number }[];
  offices: {
    id: number;
    nombre: string;
    jefeId: number | null;
    capacidadRequerida: number | null;
    asignados: number;
    habilidades_requeridas: { nombre: string; level: number }[];
  }[];
}
```

- [ ] **Step 5: Inicializar `capacidadRequerida` en `useFormDataOrg.ts`**

Reemplazar:
```typescript
  const [formData, setFormData] = useState<EntityFormData>({
    nombre: '',
    descripcion: '',
    jefeId: null,
    habilidades_requeridas: [],
    nivel_jerarquico: 1,
    parentId: null,
    empleadosIds: []
  });

  useEffect(() => {
    
    if (!data) {
      if (type === "department") {
        setFormData({
          nombre: "",
          descripcion: "",
          nivel_jerarquico: 2,
          parentId: null,
          jefeId: null,
          habilidades_requeridas: [],
          empleadosIds: []
        });
      } else if (type === "office") {
        setFormData({
          nombre: "",
          descripcion: "",
          jefeId: null,
          empleadosIds: [],
          habilidades_requeridas: [],
        });
      }
    } else {
      const entityData: EntityFormData = {
        id: data.id, // CRÍTICO: Preservar el ID para filtrado de auto-referencia
        nombre: data.nombre || '',
        descripcion: data.descripcion || '',
        jefeId: data.jefeId || null,
        habilidades_requeridas: data.habilidades_requeridas || [],
        nivel_jerarquico: (data as Department).nivel_jerarquico || (data as any).nivelJerarquico || 1,
        parentId: (data as Department).parentId || null,
        parentDepartmentId: (data as Office).parentDepartmentId || null,
        empleadosIds: (data as any).employees?.map((e: any) => e.id) || (data as Office)?.empleadosIds || []
      };
      setFormData(entityData);
    }
  }, [data, type, employees]);
```
por:
```typescript
  const [formData, setFormData] = useState<EntityFormData>({
    nombre: '',
    descripcion: '',
    jefeId: null,
    capacidadRequerida: null,
    habilidades_requeridas: [],
    nivel_jerarquico: 1,
    parentId: null,
    empleadosIds: []
  });

  useEffect(() => {
    
    if (!data) {
      if (type === "department") {
        setFormData({
          nombre: "",
          descripcion: "",
          nivel_jerarquico: 2,
          parentId: null,
          jefeId: null,
          capacidadRequerida: null,
          habilidades_requeridas: [],
          empleadosIds: []
        });
      } else if (type === "office") {
        setFormData({
          nombre: "",
          descripcion: "",
          jefeId: null,
          capacidadRequerida: null,
          empleadosIds: [],
          habilidades_requeridas: [],
        });
      }
    } else {
      const entityData: EntityFormData = {
        id: data.id, // CRÍTICO: Preservar el ID para filtrado de auto-referencia
        nombre: data.nombre || '',
        descripcion: data.descripcion || '',
        jefeId: data.jefeId || null,
        capacidadRequerida: (data as Department | Office).capacidadRequerida ?? null,
        habilidades_requeridas: data.habilidades_requeridas || [],
        nivel_jerarquico: (data as Department).nivel_jerarquico || (data as any).nivelJerarquico || 1,
        parentId: (data as Department).parentId || null,
        parentDepartmentId: (data as Office).parentDepartmentId || null,
        empleadosIds: (data as any).employees?.map((e: any) => e.id) || (data as Office)?.empleadosIds || []
      };
      setFormData(entityData);
    }
  }, [data, type, employees]);
```

- [ ] **Step 6: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Interfas/Interfaces|util/useFormDataOrg"`
Expected: sin salida (sin errores nuevos en estos 2 archivos).

- [ ] **Step 7: Commit**

```bash
git add src/app/Interfas/Interfaces.ts src/app/util/useFormDataOrg.ts
git commit -m "feat: agregar capacidadRequerida/asignados a los tipos del organigrama"
```

---

### Task 4: Frontend — formularios, badge visual, y manejo de errores en Organigrama

**Files:**
- Create: `src/app/Componentes/Orgamograma/CapacityBadge.tsx`
- Modify: `src/app/Componentes/Orgamograma/Componente/DepartmentFields.tsx`
- Modify: `src/app/Componentes/Orgamograma/Componente/OfficeFields.tsx`
- Modify: `src/app/Componentes/Orgamograma/DepartmentHeader.tsx`
- Modify: `src/app/Componentes/Orgamograma/OfficeCard.tsx`
- Modify: `src/app/screens/Organigrama/Screen.tsx`

**Interfaces:**
- Consumes: `Department`, `Office`, `EntityFormData` (Task 3).
- Produces: componente `CapacityBadge` (export nombrado, props `{ asignados?: number; capacidadRequerida?: number | null }`), sin otros consumidores externos.

- [ ] **Step 1: Crear `src/app/Componentes/Orgamograma/CapacityBadge.tsx`**

```tsx
import React from 'react';

interface CapacityBadgeProps {
  asignados?: number;
  capacidadRequerida?: number | null;
}

export const CapacityBadge: React.FC<CapacityBadgeProps> = ({ asignados = 0, capacidadRequerida }) => {
  if (capacidadRequerida == null) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground border border-border">
        {asignados}
      </span>
    );
  }

  const claseColor =
    asignados > capacidadRequerida
      ? 'bg-error-soft text-error-soft-foreground border-error'
      : asignados === capacidadRequerida
      ? 'bg-warning-soft text-warning-soft-foreground border-warning'
      : 'bg-success-soft text-success-soft-foreground border-success';

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${claseColor}`}>
      {asignados}/{capacidadRequerida}
    </span>
  );
};
```

- [ ] **Step 2: Agregar el `InputNumber` de capacidad a `DepartmentFields.tsx`**

Reemplazar:
```tsx
      {/* Nivel Jerárquico */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Nivel Jerárquico
        </label>
        <InputNumber 
          value={formData.nivel_jerarquico} 
          onValueChange={(e: InputNumberValueChangeEvent) => 
            setFormData(prev => ({ ...prev, nivel_jerarquico: e.value || 1 }))
          }
          mode="decimal" 
          showButtons 
          min={1} 
          max={5} 
          className="w-full"
        />
      </div>
```
por:
```tsx
      {/* Nivel Jerárquico */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Nivel Jerárquico
        </label>
        <InputNumber 
          value={formData.nivel_jerarquico} 
          onValueChange={(e: InputNumberValueChangeEvent) => 
            setFormData(prev => ({ ...prev, nivel_jerarquico: e.value || 1 }))
          }
          mode="decimal" 
          showButtons 
          min={1} 
          max={5} 
          className="w-full"
        />
      </div>

      {/* Capacidad Requerida */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Capacidad requerida (personas) *
        </label>
        <InputNumber
          value={formData.capacidadRequerida ?? null}
          onValueChange={(e: InputNumberValueChangeEvent) =>
            setFormData(prev => ({ ...prev, capacidadRequerida: e.value ?? null }))
          }
          mode="decimal"
          showButtons
          min={0}
          className="w-full"
          placeholder="Ej: 20"
        />
      </div>
```

- [ ] **Step 3: Agregar el `InputNumber` de capacidad a `OfficeFields.tsx`**

Reemplazar:
```tsx
import React from 'react';
import { Dropdown, DropdownChangeEvent } from 'primereact/dropdown';
import { MultiSelect, MultiSelectChangeEvent } from 'primereact/multiselect';
import { Avatar } from 'primereact/avatar';
import { AvatarGroup } from 'primereact/avatargroup';
import { useEmployeeTemplates } from './EmployeeTemplates';
import { FormFieldProps } from '@/app/Interfas/Interfaces';
```
por:
```tsx
import React from 'react';
import { Dropdown, DropdownChangeEvent } from 'primereact/dropdown';
import { MultiSelect, MultiSelectChangeEvent } from 'primereact/multiselect';
import { InputNumber, InputNumberValueChangeEvent } from 'primereact/inputnumber';
import { Avatar } from 'primereact/avatar';
import { AvatarGroup } from 'primereact/avatargroup';
import { useEmployeeTemplates } from './EmployeeTemplates';
import { FormFieldProps } from '@/app/Interfas/Interfaces';
```

Reemplazar:
```tsx
  return (
    <>
      {/* Departamento Padre (Jerarquía) */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Depende de (Dpto. Padre)
        </label>
```
por:
```tsx
  return (
    <>
      {/* Capacidad Requerida */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Capacidad requerida (personas) *
        </label>
        <InputNumber
          value={formData.capacidadRequerida ?? null}
          onValueChange={(e: InputNumberValueChangeEvent) =>
            setFormData(prev => ({ ...prev, capacidadRequerida: e.value ?? null }))
          }
          mode="decimal"
          showButtons
          min={0}
          className="w-full"
          placeholder="Ej: 4"
        />
      </div>

      {/* Departamento Padre (Jerarquía) */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Depende de (Dpto. Padre)
        </label>
```

- [ ] **Step 4: Mostrar el badge en `DepartmentHeader.tsx`**

Reemplazar:
```tsx
import React from 'react';
import { Building2, Pencil } from 'lucide-react';
import { Button } from 'primereact/button';
import { Tag } from 'primereact/tag';
import type { Department, Office,ModalContext } from '@/app/Interfas/Interfaces';
```
por:
```tsx
import React from 'react';
import { Building2, Pencil } from 'lucide-react';
import { Button } from 'primereact/button';
import { Tag } from 'primereact/tag';
import { CapacityBadge } from './CapacityBadge';
import type { Department, Office,ModalContext } from '@/app/Interfas/Interfaces';
```

Reemplazar:
```tsx
      <div>
        <h2 className="font-heading text-3xl font-extrabold text-foreground flex items-center">
          <Building2 className="w-8 h-8 mr-3 text-primary" />
          {department.nombre}
        </h2>
        <Tag 
          value={`Nivel Jerárquico: ${department.nivel_jerarquico}`}
          severity="secondary"
          className="mt-2"
        />
      </div>
```
por:
```tsx
      <div>
        <h2 className="font-heading text-3xl font-extrabold text-foreground flex items-center">
          <Building2 className="w-8 h-8 mr-3 text-primary" />
          {department.nombre}
        </h2>
        <div className="flex items-center gap-2 mt-2">
          <Tag 
            value={`Nivel Jerárquico: ${department.nivel_jerarquico}`}
            severity="secondary"
          />
          <CapacityBadge asignados={department.asignados} capacidadRequerida={department.capacidadRequerida} />
        </div>
      </div>
```

- [ ] **Step 5: Mostrar el badge en `OfficeCard.tsx`**

Reemplazar:
```tsx

import React from 'react';
import { Briefcase, Pencil } from 'lucide-react';
import Image from 'next/image';
import { EmployeeAvatar } from '../../util/UiRRHH';
import type { Office, Employee } from '@/app/Interfas/Interfaces';
```
por:
```tsx

import React from 'react';
import { Briefcase, Pencil } from 'lucide-react';
import Image from 'next/image';
import { EmployeeAvatar } from '../../util/UiRRHH';
import { CapacityBadge } from './CapacityBadge';
import type { Office, Employee } from '@/app/Interfas/Interfaces';
```

Reemplazar:
```tsx
        <div>
          <h4 className="font-bold text-lg text-foreground flex items-center">
            <Briefcase className="w-5 h-5 mr-2 text-primary" />
            {office.nombre}
          </h4>
          <p className="text-sm text-muted-foreground mt-1">{office.descripcion}</p>
        </div>
```
por:
```tsx
        <div>
          <h4 className="font-bold text-lg text-foreground flex items-center gap-2">
            <Briefcase className="w-5 h-5 mr-2 text-primary" />
            {office.nombre}
            <CapacityBadge asignados={office.asignados} capacidadRequerida={office.capacidadRequerida} />
          </h4>
          <p className="text-sm text-muted-foreground mt-1">{office.descripcion}</p>
        </div>
```

- [ ] **Step 6: Mostrar el error del backend en un `Toast` sin cerrar el modal, en `Organigrama/Screen.tsx`**

Reemplazar:
```tsx
"use client"
import React, { useEffect, useState, useCallback } from 'react';
import {  Sparkles, LayoutGrid,  } from 'lucide-react';
import { OrgChart } from '@/app/Componentes/OrganigramaGraf/OrgChart';
import { DepartmentManagementView } from '@/app/Componentes/Orgamograma/Departamento';
import { EntityFormModal } from '@/app/Componentes/Orgamograma/Componente/EntityFormModal';
import {ModalConfig, Department, Office, EntityFormData,Employee, OrgData  } from '@/app/Interfas/Interfaces';
import { departmentApi } from '@/app/Componentes/Orgamograma/departmentApi';
import { apiClient } from '@/app/util/apiClient';
```
por:
```tsx
"use client"
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {  Sparkles, LayoutGrid,  } from 'lucide-react';
import { Toast } from 'primereact/toast';
import { OrgChart } from '@/app/Componentes/OrganigramaGraf/OrgChart';
import { DepartmentManagementView } from '@/app/Componentes/Orgamograma/Departamento';
import { EntityFormModal } from '@/app/Componentes/Orgamograma/Componente/EntityFormModal';
import {ModalConfig, Department, Office, EntityFormData,Employee, OrgData  } from '@/app/Interfas/Interfaces';
import { departmentApi } from '@/app/Componentes/Orgamograma/departmentApi';
import { apiClient } from '@/app/util/apiClient';
```

Reemplazar:
```tsx
  const [modalConfig, setModalConfig] = useState<ModalConfig>({type: "department", data: undefined, context: {},});
  const [activeTab, setActiveTab] = useState("gestion");
 
```
por:
```tsx
  const [modalConfig, setModalConfig] = useState<ModalConfig>({type: "department", data: undefined, context: {},});
  const [activeTab, setActiveTab] = useState("gestion");
  const toast = useRef<Toast>(null);
 
```

Reemplazar:
```tsx
    // Re-validar estado: recargar datos del servidor inmediatamente
    await refreshDepartments();
    
    handleCloseModal();
  } catch (err) {
    console.error('Error al guardar:', err);
  }
};
```
por:
```tsx
    // Re-validar estado: recargar datos del servidor inmediatamente
    await refreshDepartments();
    
    handleCloseModal();
  } catch (err) {
    console.error('Error al guardar:', err);
    toast.current?.show({
      severity: 'error',
      summary: 'Error',
      detail: err instanceof Error ? err.message : 'No se pudo guardar',
      life: 5000,
    });
  }
};
```

Reemplazar:
```tsx
  return (
    <div className="bg-background font-sans min-h-screen">
      <div className="container mx-auto p-4 md:p-8">
        <header className="mb-8">
```
por:
```tsx
  return (
    <div className="bg-background font-sans min-h-screen">
      <Toast ref={toast} />
      <div className="container mx-auto p-4 md:p-8">
        <header className="mb-8">
```

- [ ] **Step 7: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Orgamograma/CapacityBadge|Orgamograma/Componente/DepartmentFields|Orgamograma/Componente/OfficeFields|Orgamograma/DepartmentHeader|Orgamograma/OfficeCard|screens/Organigrama/Screen"`
Expected: sin salida (sin errores nuevos en estos 6 archivos).

- [ ] **Step 8: Commit**

```bash
git add src/app/Componentes/Orgamograma/CapacityBadge.tsx src/app/Componentes/Orgamograma/Componente/DepartmentFields.tsx src/app/Componentes/Orgamograma/Componente/OfficeFields.tsx src/app/Componentes/Orgamograma/DepartmentHeader.tsx src/app/Componentes/Orgamograma/OfficeCard.tsx src/app/screens/Organigrama/Screen.tsx
git commit -m "feat: agregar formulario, badge visual y manejo de errores de capacidad en Organigrama"
```

---

### Task 5: Frontend — capacidad como tercer factor en el motor de matching

**Files:**
- Modify: `src/app/lib/reubicacion-matching-engine.ts`
- Modify: `src/app/lib/reubicacion-recomendacion-prompt.ts`

**Interfaces:**
- Consumes: `OrgAnalysisDepartment` extendido (Task 3).
- Produces: `MatchResult` extendido con `vacantes: number | null` y `capacidad: number | null` — consumido por `reubicacion-recomendacion-prompt.ts` y ya reenviado tal cual por `src/app/api/reubicacion-analysis/route.ts` (sin cambios, spreadea `match` y `recomendacion` por separado, no requiere tocarse).

- [ ] **Step 1: Actualizar los pesos y el comentario del archivo**

Reemplazar:
```typescript
/**
 * Motor de Matching para Reubicacion Inteligente (subsistema 3).
 *
 * Determina, para un empleado que solicito reubicacion, cual es la mejor
 * oficina destino (excluyendo la actual) en base a:
 * - Skill match (70%): que porcentaje de las habilidades requeridas de la
 *   oficina candidata posee el empleado.
 * - Deficit de personal (30%): que porcentaje de esas habilidades requeridas
 *   NO esta cubierto por la dotacion actual de esa oficina (prioriza mandar
 *   gente a donde falta cobertura).
 */

import type { OrgAnalysisEmployee, OrgAnalysisDepartment } from "@/app/Interfas/Interfaces";

const SKILL_MATCH_WEIGHT = 0.7;
const DEFICIT_WEIGHT = 0.3;

interface CandidateOffice {
  officeId: number;
  officeNombre: string;
  departmentId: number;
  departmentNombre: string;
  habilidadesRequeridas: { nombre: string; level: number }[];
}

export interface MatchResult {
  officeIdSugerido: number | null;
  officeNombreSugerido: string | null;
  departmentIdSugerido: number | null;
  departmentNombreSugerido: string | null;
  scoreCompatibilidad: number;
  matchedSkills: string[];
  missingSkills: string[];
  deficitSkills: string[];
}
```
por:
```typescript
/**
 * Motor de Matching para Reubicacion Inteligente (subsistema 3).
 *
 * Determina, para un empleado que solicito reubicacion, cual es la mejor
 * oficina destino (excluyendo la actual) en base a:
 * - Skill match (55%): que porcentaje de las habilidades requeridas de la
 *   oficina candidata posee el empleado.
 * - Deficit de personal por skills (20%): que porcentaje de esas habilidades
 *   requeridas NO esta cubierto por la dotacion actual de esa oficina
 *   (prioriza mandar gente a donde falta cobertura).
 * - Vacantes por capacidad (25%): que tan lejos esta la oficina de su
 *   capacidad requerida (capacidadRequerida - asignados). Si la oficina no
 *   tiene capacidad configurada (o es 0), este peso se redistribuye entre
 *   los otros dos factores.
 */

import type { OrgAnalysisEmployee, OrgAnalysisDepartment } from "@/app/Interfas/Interfaces";

const SKILL_MATCH_WEIGHT = 0.55;
const DEFICIT_WEIGHT = 0.20;
const CAPACITY_WEIGHT = 0.25;

interface CandidateOffice {
  officeId: number;
  officeNombre: string;
  departmentId: number;
  departmentNombre: string;
  habilidadesRequeridas: { nombre: string; level: number }[];
  capacidadRequerida: number | null;
  asignados: number;
}

export interface MatchResult {
  officeIdSugerido: number | null;
  officeNombreSugerido: string | null;
  departmentIdSugerido: number | null;
  departmentNombreSugerido: string | null;
  scoreCompatibilidad: number;
  matchedSkills: string[];
  missingSkills: string[];
  deficitSkills: string[];
  vacantes: number | null;
  capacidad: number | null;
}
```

- [ ] **Step 2: Propagar capacidad en `listCandidateOffices`**

Reemplazar:
```typescript
function listCandidateOffices(
  departments: OrgAnalysisDepartment[],
  excludeOfficeId: number | null
): CandidateOffice[] {
  const candidates: CandidateOffice[] = [];
  for (const dept of departments) {
    for (const office of dept.offices) {
      if (office.id === excludeOfficeId) continue;
      candidates.push({
        officeId: office.id,
        officeNombre: office.nombre,
        departmentId: dept.id,
        departmentNombre: dept.nombre,
        habilidadesRequeridas: office.habilidades_requeridas,
      });
    }
  }
  return candidates;
}
```
por:
```typescript
function listCandidateOffices(
  departments: OrgAnalysisDepartment[],
  excludeOfficeId: number | null
): CandidateOffice[] {
  const candidates: CandidateOffice[] = [];
  for (const dept of departments) {
    for (const office of dept.offices) {
      if (office.id === excludeOfficeId) continue;
      candidates.push({
        officeId: office.id,
        officeNombre: office.nombre,
        departmentId: dept.id,
        departmentNombre: dept.nombre,
        habilidadesRequeridas: office.habilidades_requeridas,
        capacidadRequerida: office.capacidadRequerida,
        asignados: office.asignados,
      });
    }
  }
  return candidates;
}
```

- [ ] **Step 3: Calcular el factor de capacidad en `scoreCandidate`**

Reemplazar:
```typescript
type ScoreDetails = Pick<
  MatchResult,
  "scoreCompatibilidad" | "matchedSkills" | "missingSkills" | "deficitSkills"
>;

function scoreCandidate(
  candidate: CandidateOffice,
  empSkillNames: Set<string>,
  allEmployees: OrgAnalysisEmployee[]
): ScoreDetails {
  const required = candidate.habilidadesRequeridas;

  if (required.length === 0) {
    // Sin requisitos definidos para esta oficina: no se puede evaluar match
    // ni deficit, se usa un score neutral para no penalizar ni favorecer.
    return { scoreCompatibilidad: 50, matchedSkills: [], missingSkills: [], deficitSkills: [] };
  }

  const matchedSkills = required.filter((r) => empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const missingSkills = required.filter((r) => !empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const skillMatchRatio = matchedSkills.length / required.length;

  const staffSkillNames = new Set<string>();
  for (const emp of allEmployees) {
    if (emp.officeId !== candidate.officeId) continue;
    for (const s of emp.softSkills) staffSkillNames.add(s.nombre.toLowerCase());
    for (const t of emp.technicalSkills) staffSkillNames.add(t.nombre.toLowerCase());
  }
  const deficitSkills = required.filter((r) => !staffSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const deficitRatio = deficitSkills.length / required.length;

  const scoreCompatibilidad = Math.round(
    skillMatchRatio * SKILL_MATCH_WEIGHT * 100 + deficitRatio * DEFICIT_WEIGHT * 100
  );

  return { scoreCompatibilidad, matchedSkills, missingSkills, deficitSkills };
}
```
por:
```typescript
type ScoreDetails = Pick<
  MatchResult,
  "scoreCompatibilidad" | "matchedSkills" | "missingSkills" | "deficitSkills" | "vacantes" | "capacidad"
>;

function scoreCandidate(
  candidate: CandidateOffice,
  empSkillNames: Set<string>,
  allEmployees: OrgAnalysisEmployee[]
): ScoreDetails {
  const required = candidate.habilidadesRequeridas;
  const vacantes =
    candidate.capacidadRequerida != null ? Math.max(candidate.capacidadRequerida - candidate.asignados, 0) : null;

  if (required.length === 0) {
    // Sin requisitos definidos para esta oficina: no se puede evaluar match
    // ni deficit, se usa un score neutral para no penalizar ni favorecer.
    return {
      scoreCompatibilidad: 50,
      matchedSkills: [],
      missingSkills: [],
      deficitSkills: [],
      vacantes,
      capacidad: candidate.capacidadRequerida,
    };
  }

  const matchedSkills = required.filter((r) => empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const missingSkills = required.filter((r) => !empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const skillMatchRatio = matchedSkills.length / required.length;

  const staffSkillNames = new Set<string>();
  for (const emp of allEmployees) {
    if (emp.officeId !== candidate.officeId) continue;
    for (const s of emp.softSkills) staffSkillNames.add(s.nombre.toLowerCase());
    for (const t of emp.technicalSkills) staffSkillNames.add(t.nombre.toLowerCase());
  }
  const deficitSkills = required.filter((r) => !staffSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const deficitRatio = deficitSkills.length / required.length;

  let skillWeight = SKILL_MATCH_WEIGHT;
  let deficitWeight = DEFICIT_WEIGHT;
  let capacityWeight = CAPACITY_WEIGHT;
  let capacityRatio = 0;

  const capacidadValida = candidate.capacidadRequerida != null && candidate.capacidadRequerida > 0;
  if (capacidadValida) {
    capacityRatio = Math.min(
      Math.max((candidate.capacidadRequerida! - candidate.asignados) / candidate.capacidadRequerida!, 0),
      1
    );
  } else {
    // Sin capacidad configurada (o en 0): se redistribuye su peso
    // proporcionalmente entre skill match y deficit, para no penalizar ni
    // favorecer a esta oficina.
    const remaining = SKILL_MATCH_WEIGHT + DEFICIT_WEIGHT;
    skillWeight = SKILL_MATCH_WEIGHT + (SKILL_MATCH_WEIGHT / remaining) * CAPACITY_WEIGHT;
    deficitWeight = DEFICIT_WEIGHT + (DEFICIT_WEIGHT / remaining) * CAPACITY_WEIGHT;
    capacityWeight = 0;
  }

  const scoreCompatibilidad = Math.round(
    skillMatchRatio * skillWeight * 100 + deficitRatio * deficitWeight * 100 + capacityRatio * capacityWeight * 100
  );

  return { scoreCompatibilidad, matchedSkills, missingSkills, deficitSkills, vacantes, capacidad: candidate.capacidadRequerida };
}
```

- [ ] **Step 4: Incluir `vacantes`/`capacidad` en el resultado por defecto de `findBestRelocationMatch`**

Reemplazar:
```typescript
  return (
    best ?? {
      officeIdSugerido: null,
      officeNombreSugerido: null,
      departmentIdSugerido: null,
      departmentNombreSugerido: null,
      scoreCompatibilidad: 0,
      matchedSkills: [],
      missingSkills: [],
      deficitSkills: [],
    }
  );
```
por:
```typescript
  return (
    best ?? {
      officeIdSugerido: null,
      officeNombreSugerido: null,
      departmentIdSugerido: null,
      departmentNombreSugerido: null,
      scoreCompatibilidad: 0,
      matchedSkills: [],
      missingSkills: [],
      deficitSkills: [],
      vacantes: null,
      capacidad: null,
    }
  );
```

- [ ] **Step 5: Verificar tipos del motor**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "reubicacion-matching-engine"`
Expected: sin salida.

- [ ] **Step 6: Mencionar la capacidad en el prompt de Gemini y en el fallback**

Reemplazar:
```typescript
Empleado: ${employee.name}
Motivo de la solicitud: ${motivo}
Oficina actual: ${employee.officeName ?? "sin oficina asignada"} (${employee.departmentName})
Oficina destino sugerida: ${match.officeNombreSugerido ?? "ninguna disponible"} (${match.departmentNombreSugerido ?? "-"})
Score de compatibilidad: ${match.scoreCompatibilidad}%
Habilidades que coinciden: ${match.matchedSkills.join(", ") || "ninguna"}
Habilidades que le faltan: ${match.missingSkills.join(", ") || "ninguna"}
Habilidades con déficit de personal en el destino: ${match.deficitSkills.join(", ") || "ninguna"}

Responde ESTRICTAMENTE con este JSON:
```
por:
```typescript
Empleado: ${employee.name}
Motivo de la solicitud: ${motivo}
Oficina actual: ${employee.officeName ?? "sin oficina asignada"} (${employee.departmentName})
Oficina destino sugerida: ${match.officeNombreSugerido ?? "ninguna disponible"} (${match.departmentNombreSugerido ?? "-"})
Score de compatibilidad: ${match.scoreCompatibilidad}%
Habilidades que coinciden: ${match.matchedSkills.join(", ") || "ninguna"}
Habilidades que le faltan: ${match.missingSkills.join(", ") || "ninguna"}
Habilidades con déficit de personal en el destino: ${match.deficitSkills.join(", ") || "ninguna"}
${match.capacidad != null ? `Vacantes disponibles en el destino: ${match.vacantes} de ${match.capacidad} (capacidad requerida configurada).` : "Capacidad requerida del destino: no configurada (dato no disponible)."}

Responde ESTRICTAMENTE con este JSON:
```

Reemplazar:
```typescript
  const explicacion =
    match.scoreCompatibilidad >= 70
      ? `Se recomienda trasladar al empleado a ${destino} debido a que posee un ${match.scoreCompatibilidad}% de compatibilidad con las competencias requeridas${
          match.deficitSkills.length > 0
            ? " y actualmente existe un déficit de personal especializado en esa oficina"
            : ""
        }.`
      : `La compatibilidad con ${destino} es baja (${match.scoreCompatibilidad}%): se recomienda evaluar con cautela antes de aprobar este traslado.`;

  return {
    explicacion,
    beneficios: ["Mejor aprovechamiento del talento", "Cobertura de vacantes", "Mayor productividad"],
    riesgos: ["Pérdida de conocimiento en la oficina actual", "Necesidad de reemplazo", "Impacto operativo temporal"],
  };
}
```
por:
```typescript
  const vacantesTexto =
    match.capacidad != null && match.vacantes != null && match.vacantes > 0
      ? ` Además, tiene ${match.vacantes} vacante${match.vacantes === 1 ? "" : "s"} disponible${
          match.vacantes === 1 ? "" : "s"
        } sobre una capacidad de ${match.capacidad}.`
      : "";

  const explicacion =
    match.scoreCompatibilidad >= 70
      ? `Se recomienda trasladar al empleado a ${destino} debido a que posee un ${match.scoreCompatibilidad}% de compatibilidad con las competencias requeridas${
          match.deficitSkills.length > 0
            ? " y actualmente existe un déficit de personal especializado en esa oficina"
            : ""
        }.${vacantesTexto}`
      : `La compatibilidad con ${destino} es baja (${match.scoreCompatibilidad}%): se recomienda evaluar con cautela antes de aprobar este traslado.${vacantesTexto}`;

  return {
    explicacion,
    beneficios: ["Mejor aprovechamiento del talento", "Cobertura de vacantes", "Mayor productividad"],
    riesgos: ["Pérdida de conocimiento en la oficina actual", "Necesidad de reemplazo", "Impacto operativo temporal"],
  };
}
```

- [ ] **Step 7: Verificar tipos del prompt**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "reubicacion-recomendacion-prompt"`
Expected: sin salida.

- [ ] **Step 8: Commit**

```bash
git add src/app/lib/reubicacion-matching-engine.ts src/app/lib/reubicacion-recomendacion-prompt.ts
git commit -m "feat: sumar capacidad como tercer factor del motor de matching de reubicacion"
```

---

### Task 6: Verificación manual

No hay test suite automatizada en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `POST /departments/` sin `capacidadRequerida` → 400; con `capacidadRequerida` válida → crea OK y aparece en `GET /departments/` con `asignados: 0`.
- [ ] **Step 3:** `POST /departments/{dep_id}/offices` sin `capacidadRequerida` → 400; cargar dos oficinas cuya suma (ej. 15 + 8 = 23) supere la capacidad del depto (ej. 20) → 400 en la segunda; dentro del tope (15 + 5 = 20) → ambas OK.
- [ ] **Step 4:** `PUT /departments/{dep_id}` bajando la capacidad del depto por debajo de la suma ya cargada de sus oficinas → 400.
- [ ] **Step 5:** Asignar empleados a un departamento y a una oficina; confirmar que `GET /departments/` devuelve `asignados` correcto en ambos niveles (el empleado de una oficina cuenta también en el total del departamento).
- [ ] **Step 6:** `GET /rrhh/org-analysis-data` incluye `capacidadRequerida`/`asignados` por departamento y oficina.
- [ ] **Step 7:** En el frontend, crear un departamento/oficina sin cargar capacidad: el backend rechaza y aparece el toast de error en la pantalla de Organigrama, sin cerrar el modal.
- [ ] **Step 8:** El badge "X/Y" se ve verde con cupo, ámbar exactamente completo, rojo sobre-asignado; una unidad sin capacidad (legacy) muestra solo el número sin denominador, en gris.
- [ ] **Step 9:** En Reubicación, correr "Analizar Solicitudes": una oficina con vacantes debe rankear más alto que una llena a igual match de skills (compará dos oficinas con habilidades similares pero distinta ocupación); la explicación de la IA puede mencionar las vacantes.
