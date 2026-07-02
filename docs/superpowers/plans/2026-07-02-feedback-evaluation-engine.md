# Motor de evaluación de Feedback 360° Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescribir el flujo real de evaluación de Feedback 360° (`app/routes/feedback.py`) para usar el banco de preguntas del subsistema 1 — compañeros + superior directo, preguntas de liderazgo condicionales, periodicidad configurable, y un botón de verificación de reglas para RRHH.

**Architecture:** Un módulo nuevo `app/database/feedback_config.py` (periodicidad, mismo patrón fila-única que `academic_title_mapping.py`) + reescritura in-place de los endpoints existentes en `app/routes/feedback.py` (mismo archivo, misma convención de SQL inline que ya usa ese router). En el frontend, `FeedbackTab.tsx` se vuelve un componente presentacional puro (recibe la pregunta actual y el progreso por props) y `Feedback/Screen.tsx` orquesta las llamadas a los 3 endpoints nuevos. Se agrega una pestaña nueva "Verificar Evaluación de Equipo" en `ConfiguracionLicencias/Screen.tsx` (pantalla ya restringida a ADMIN/RRHH vía RBAC).

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- Las tablas `Feedback`, `Respuesta`, `FeedbackEvaluacion` NO se tocan ni se leen/escriben desde este código — quedan sin usar (decisión del subsistema 1).
- `app/main.py` NO se modifica (el router `feedback` ya está registrado).
- `GET /feedback/received/{employee_id}` queda fuera de alcance — no se toca en este plan.
- Escala 1-5: valores enteros, 5 = mejor. Escala estándar de labels es `["Siempre","Casi siempre","Algunas veces","Rara vez","Nunca"]` → 5,4,3,2,1 (ya sembrada en el subsistema 1; el mapeo label→valor lo hace el frontend por posición en el array `opcionesEscala`, no el backend).
- `esJerarquico(employee_id)` = `true` si el empleado es `jefeId` de algún `Department` **o** existe algún `Employee` con `managerId = employee_id`.
- El "período activo" (`periodo`) se calcula truncando la fecha de hoy a la periodicidad configurada: trimestral → inicio del trimestre (meses 1,4,7,10), semestral → inicio del semestre (meses 1,7), anual → 1 de enero.
- El botón "Verificar Evaluación de Equipo" vive en `ConfiguracionLicencias/Screen.tsx` (pantalla ya restringida a ADMIN/RRHH vía RBAC — no se necesita chequeo de rol adicional en el componente).

---

### Task 1: Configuración de periodicidad (`FeedbackConfig`)

**Files:**
- Create: `app/database/feedback_config.py`

**Interfaces:**
- Produces: `ensure_table(db: Session) -> None`, `get_periodicidad(db: Session) -> str`, `set_periodicidad(db: Session, periodicidad: str) -> None` (lanza `ValueError` si el valor no es válido), `get_periodo_actual(db: Session) -> date`.

- [ ] **Step 1: Crear el archivo con la tabla, el seed default y las funciones de lectura/escritura**

```python
"""
Configuracion de periodicidad del ciclo de evaluaciones de Feedback 360.
Fila unica activa, mismo patron que app/database/academic_title_mapping.py.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'FeedbackConfig' AND xtype = 'U'
)
BEGIN
    CREATE TABLE FeedbackConfig (
        id           INT IDENTITY(1,1) PRIMARY KEY,
        periodicidad NVARCHAR(20)  NOT NULL DEFAULT 'trimestral',
        updatedAt    DATETIME2     NOT NULL
    );
END
"""

VALID_PERIODICIDADES = {"trimestral", "semestral", "anual"}


def ensure_table(db: Session) -> None:
    """Crea FeedbackConfig si no existe y siembra la fila default (trimestral) si esta vacia."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM FeedbackConfig")).mappings().first()
    if count["c"] == 0:
        db.execute(text("""
            INSERT INTO FeedbackConfig (periodicidad, updatedAt)
            VALUES ('trimestral', :now)
        """), {"now": datetime.utcnow()})
        db.commit()


def get_periodicidad(db: Session) -> str:
    """Devuelve la periodicidad activa ('trimestral' | 'semestral' | 'anual')."""
    row = db.execute(text("SELECT TOP 1 periodicidad FROM FeedbackConfig ORDER BY id ASC")).mappings().first()
    return row["periodicidad"] if row else "trimestral"


def set_periodicidad(db: Session, periodicidad: str) -> None:
    """Actualiza la periodicidad de la unica fila de configuracion."""
    if periodicidad not in VALID_PERIODICIDADES:
        raise ValueError(f"periodicidad debe ser uno de: {VALID_PERIODICIDADES}")
    row = db.execute(text("SELECT TOP 1 id FROM FeedbackConfig ORDER BY id ASC")).mappings().first()
    db.execute(text("""
        UPDATE FeedbackConfig SET periodicidad = :periodicidad, updatedAt = :now
        WHERE id = :id
    """), {"periodicidad": periodicidad, "now": datetime.utcnow(), "id": row["id"]})
    db.commit()


def get_periodo_actual(db: Session) -> date:
    """Calcula el inicio del ciclo activo segun la periodicidad configurada.
    trimestral: primer dia del trimestre en curso (meses 1,4,7,10).
    semestral: primer dia del semestre en curso (meses 1,7).
    anual: 1 de enero del anio en curso.
    """
    periodicidad = get_periodicidad(db)
    today = date.today()

    if periodicidad == "anual":
        return date(today.year, 1, 1)
    if periodicidad == "semestral":
        mes = 1 if today.month < 7 else 7
        return date(today.year, mes, 1)
    mes = ((today.month - 1) // 3) * 3 + 1
    return date(today.year, mes, 1)
```

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/database/feedback_config.py`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
git add app/database/feedback_config.py
git commit -m "feat: agregar configuracion de periodicidad para el ciclo de Feedback 360"
```

---

### Task 2: Endpoints de configuración + pool de evaluables (`GET/PUT /feedback/config`, `GET /feedback/peers`)

**Files:**
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Consumes: `ensure_table`, `get_periodicidad`, `set_periodicidad`, `get_periodo_actual` de `app.database.feedback_config` (Task 1).
- Produces: helper `_is_jerarquico(db: Session, employee_id: int) -> bool` (usado por las Tasks 3 y 4). Endpoint `GET /feedback/peers/{employee_id}` devuelve `{"evaluatorId": int, "department": str, "evaluables": [{id, name, department, office, esJerarquico}]}` — este shape lo consume `get_evaluable_peers` (llamada directamente como función Python desde las Tasks 3 y 4, pasando `db` explícito).

- [ ] **Step 1: Agregar imports necesarios**

Al principio de `app/routes/feedback.py`, agregar debajo de `from datetime import datetime, timezone`:

```python
from app.database.feedback_config import (
    ensure_table as ensure_config_table,
    get_periodicidad,
    set_periodicidad,
    get_periodo_actual,
)
```

- [ ] **Step 2: Agregar el helper `_is_jerarquico`**

Agregar antes del primer `@router.get`, después de la definición de `get_db()`:

```python
def _is_jerarquico(db: Session, employee_id: int) -> bool:
    """True si el empleado es jefe de algun departamento o tiene reportes directos."""
    row = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM Department WHERE jefeId = :id) AS deptos_a_cargo,
            (SELECT COUNT(*) FROM Employee WHERE managerId = :id) AS reportes_directos
    """), {"id": employee_id}).mappings().first()
    return bool(row and (row["deptos_a_cargo"] > 0 or row["reportes_directos"] > 0))
```

- [ ] **Step 3: Reemplazar por completo el endpoint `GET /feedback/peers/{employee_id}`**

Buscar el bloque que empieza en:
```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/peers/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

@router.get("/peers/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_evaluable_peers(employee_id: int, db: Session = Depends(get_db)):
```
y termina justo antes de:
```python
# ─────────────────────────────────────────────────────────────────────────────
# POST /feedback/submit
```

Reemplazar todo ese bloque (incluye los imports duplicados que había al principio, que se eliminan) por:

```python
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
```

- [ ] **Step 4: Agregar los endpoints `GET`/`PUT /feedback/config`**

Agregar al final del archivo (después del último endpoint que exista en ese momento):

```python
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
```

Este último endpoint usa `require_rrhh_auth`, que **no existe todavía** en este archivo — agregarlo también en este Step, junto a los demás imports del principio del archivo (debajo de `from app.auth_middleware import require_any_auth, get_current_user`):

```python
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
```

Y debajo de `router = APIRouter(prefix="/feedback", tags=["Feedback"])`:

```python
ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)
```

(Mismo patrón exacto que ya usa `app/routes/licenses.py:22-23`.)

- [ ] **Step 5: Verificar que compila**

Run: `py -m py_compile app/routes/feedback.py`
Expected: sin salida.

- [ ] **Step 6: Commit**

```bash
git add app/routes/feedback.py
git commit -m "feat: reescribir GET /feedback/peers y agregar GET/PUT /feedback/config"
```

---

### Task 3: Rotación de preguntas y envío de respuestas (`GET /feedback/siguiente`, `POST /feedback/submit`)

**Files:**
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Consumes: `get_evaluable_peers(employee_id, db)` y `_is_jerarquico(db, employee_id)` (Task 2), `get_periodo_actual(db)` (Task 1), `get_preguntas(db, solo_liderazgo=None, es_ambiente_general=None)` (ya importado en este archivo desde el subsistema 1 — `from app.database.feedback_preguntas import ensure_table as ensure_preguntas_table, get_preguntas`).
- Produces: `GET /feedback/siguiente/{employee_id}` → `{"evaluado": {id, name} | null, "pregunta": {id, texto, tipo, opcionesEscala} | null}`.

- [ ] **Step 1: Agregar `import random` al principio del archivo**

Debajo de `from datetime import datetime, timezone`:

```python
import random
```

- [ ] **Step 2: Agregar el endpoint `GET /feedback/siguiente/{employee_id}`**

Agregar justo antes de `POST /feedback/submit`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/siguiente/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/siguiente/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_siguiente_pregunta(employee_id: int, db: Session = Depends(get_db)):
    """
    Elige al azar un par (evaluado, pregunta) pendiente del ciclo activo
    para que este empleado evalue. Devuelve pregunta null si no quedan
    pendientes.
    """
    ensure_preguntas_table(db)
    ensure_config_table(db)

    peers_response = get_evaluable_peers(employee_id, db)
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
```

- [ ] **Step 3: Reemplazar por completo el endpoint `POST /feedback/submit`**

Buscar el bloque que empieza en `@router.post("/submit", dependencies=[Depends(require_any_auth)])` y termina justo antes de:
```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/status/{employee_id}  — progreso del evaluador
```

Reemplazarlo por:

```python
@router.post("/submit", dependencies=[Depends(require_any_auth)])
def submit_feedback(data: dict = Body(...), db: Session = Depends(get_db)):
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
        valid_ids = {ev["id"] for ev in get_evaluable_peers(evaluador_id, db)["evaluables"]}
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
```

- [ ] **Step 4: Verificar que compila**

Run: `py -m py_compile app/routes/feedback.py`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
git add app/routes/feedback.py
git commit -m "feat: agregar GET /feedback/siguiente y reescribir POST /feedback/submit con el banco de preguntas"
```

---

### Task 4: Progreso y verificación de reglas (`GET /feedback/status`, `POST /feedback/verificar`)

**Files:**
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Consumes: `get_evaluable_peers`, `_is_jerarquico` (Task 2), `get_periodo_actual` (Task 1), `get_preguntas` (subsistema 1).
- Produces: `GET /feedback/status/{employee_id}` → `{"evaluatorId", "periodo", "total", "completadas"}`. `POST /feedback/verificar` → `{"reglas": [{"regla", "cumple", "detalle"}]}`.

- [ ] **Step 1: Reemplazar por completo el endpoint `GET /feedback/status/{employee_id}`**

Buscar el bloque que empieza en `@router.get("/status/{employee_id}", dependencies=[Depends(require_any_auth)])` y termina justo antes de:
```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/received/{employee_id} — resultados recibidos por el empleado
```

Reemplazarlo por:

```python
@router.get("/status/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_feedback_status(employee_id: int, db: Session = Depends(get_db)):
    """Progreso del ciclo activo: pares totales aplicables vs. respondidos."""
    ensure_preguntas_table(db)
    ensure_config_table(db)

    evaluables = get_evaluable_peers(employee_id, db)["evaluables"]
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
```

**IMPORTANTE:** `GET /feedback/received/{employee_id}` (el endpoint que queda justo después) NO se modifica en este task — sigue usando el modelo viejo (`Feedback`/`Respuesta`), fuera de alcance de este plan.

- [ ] **Step 2: Agregar el endpoint `POST /feedback/verificar` al final del archivo**

Agregar después del endpoint `PUT /feedback/config` (agregado en la Task 2):

```python
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
```

- [ ] **Step 3: Verificar que compila**

Run: `py -m py_compile app/routes/feedback.py`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
git add app/routes/feedback.py
git commit -m "feat: reescribir GET /feedback/status y agregar POST /feedback/verificar"
```

---

### Task 5: Frontend — flujo de evaluación (`FeedbackTab.tsx` + `Feedback/Screen.tsx`)

**Files:**
- Modify: `src/app/Componentes/Encuesta/FeedbackTab.tsx` (reescritura completa)
- Modify: `src/app/screens/Feedback/Screen.tsx` (reescritura completa)

**Interfaces:**
- Produces (exportado desde `FeedbackTab.tsx`, consumido por `Screen.tsx`): `PreguntaFeedback { id: number; texto: string; categoria?: string; tipo: 'escala' | 'texto_libre'; opcionesEscala: string[] | null; }`, `SiguienteFeedback { evaluado: { id: number; name: string } | null; pregunta: PreguntaFeedback | null; }`, `FeedbackStatus { total: number; completadas: number; }`.
- Consumes (backend, Tasks 2-4): `GET /feedback/siguiente/{employeeId}` → `SiguienteFeedback`, `GET /feedback/status/{employeeId}` → `{evaluatorId, periodo, total, completadas}`, `POST /feedback/submit` con body `{evaluadorId, evaluadoId, preguntaId, valorEscala, textoLibre}`.

- [ ] **Step 1: Reemplazar el contenido completo de `src/app/Componentes/Encuesta/FeedbackTab.tsx`**

```tsx
import { MessageSquare } from 'lucide-react';
import React, { useState, useEffect } from 'react';
import { Card } from 'primereact/card';
import { SelectButton } from 'primereact/selectbutton';
import { InputTextarea } from 'primereact/inputtextarea';
import { Button } from 'primereact/button';
import { ProgressBar } from 'primereact/progressbar';

export interface PreguntaFeedback {
  id: number;
  texto: string;
  categoria?: string;
  tipo: 'escala' | 'texto_libre';
  opcionesEscala: string[] | null;
}

export interface SiguienteFeedback {
  evaluado: { id: number; name: string } | null;
  pregunta: PreguntaFeedback | null;
}

export interface FeedbackStatus {
  total: number;
  completadas: number;
}

interface FeedbackTabProps {
  siguiente: SiguienteFeedback | null;
  status: FeedbackStatus | null;
  loading: boolean;
  onSubmit: (valorEscala: number | null, textoLibre: string | null) => void;
}

export const FeedbackTab: React.FC<FeedbackTabProps> = ({ siguiente, status, loading, onSubmit }) => {
  const [valorEscala, setValorEscala] = useState<number | null>(null);
  const [textoLibre, setTextoLibre] = useState('');

  useEffect(() => {
    setValorEscala(null);
    setTextoLibre('');
  }, [siguiente?.pregunta?.id, siguiente?.evaluado?.id]);

  const cardTitle = (
    <div className="flex items-center">
      <MessageSquare className="mr-3 text-primary" />
      <span className="font-heading text-2xl font-bold text-foreground">Evaluación del Equipo de Trabajo</span>
    </div>
  );

  const pregunta = siguiente?.pregunta ?? null;
  const evaluado = siguiente?.evaluado ?? null;

  const escalaOptions = pregunta?.opcionesEscala
    ? pregunta.opcionesEscala.map((label, idx) => ({ label, value: 5 - idx }))
    : [];

  const canSubmit = pregunta
    ? (pregunta.tipo === 'escala' ? valorEscala !== null : textoLibre.trim().length > 0)
    : false;

  const handleSubmit = () => {
    if (!pregunta) return;
    onSubmit(pregunta.tipo === 'escala' ? valorEscala : null, pregunta.tipo === 'texto_libre' ? textoLibre : null);
  };

  const progressPercentage = status && status.total > 0 ? (status.completadas / status.total) * 100 : 0;

  return (
    <Card title={cardTitle}>
      <span className="text-base font-bold text-muted-foreground sm:ml-2">
        Tu Opinión es Totalmente Anónima
      </span>
      <div className="mt-4">
        <div className="flex justify-between items-center mb-3">
          <span className="text-sm font-semibold text-foreground">Progreso de Evaluaciones</span>
        </div>
        <ProgressBar
          value={progressPercentage}
          displayValueTemplate={() => status ? `${status.completadas}/${status.total}` : '0/0'}
        />
        <div className="mt-2 mb-5 text-xs text-muted-foreground">
          {status && status.total > 0
            ? `${Math.round(progressPercentage)}% completado`
            : 'Sin evaluaciones disponibles'}
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-muted-foreground">Cargando...</div>
      ) : pregunta ? (
        <div className="space-y-6">
          <Card className="p-1 rounded-lg border border-primary/30">
            {evaluado ? (
              <p className="text-lg text-foreground mb-3">
                Sobre tu compañero/a{' '}
                <span className="font-bold text-primary">{evaluado.name}</span>:
              </p>
            ) : (
              <p className="text-lg text-foreground mb-3">Sobre el ambiente laboral:</p>
            )}
            <p className="text-xl font-semibold text-primary">
              {pregunta.texto}
            </p>
          </Card>

          {pregunta.tipo === 'escala' ? (
            <div className="flex justify-center">
              <SelectButton
                value={valorEscala}
                onChange={(e) => setValorEscala(e.value)}
                options={escalaOptions}
              />
            </div>
          ) : (
            <InputTextarea
              value={textoLibre}
              onChange={(e) => setTextoLibre(e.target.value)}
              rows={4}
              className="w-full"
              placeholder="Escribí tu respuesta..."
            />
          )}

          <Button
            label="Enviar Feedback"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="w-full py-3 text-lg"
          />
        </div>
      ) : (
        <div className="text-center py-8">
          <div className="bg-muted p-6 rounded-lg border border-border">
            <MessageSquare className="mx-auto mb-4 text-muted-foreground" size={48} />
            <p className="text-muted-foreground mb-4">
              Ya completaste todas las evaluaciones disponibles de este período. Volvé más adelante para el próximo ciclo.
            </p>
          </div>
        </div>
      )}
    </Card>
  );
};
```

- [ ] **Step 2: Reemplazar el contenido completo de `src/app/screens/Feedback/Screen.tsx`**

```tsx
"use client"
import { BarChart, User, RefreshCw } from 'lucide-react';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Card } from 'primereact/card';
import { Toast } from 'primereact/toast';
import { apiClient } from '@/app/util/apiClient';
import { FeedbackTab, SiguienteFeedback, FeedbackStatus } from '@/app/Componentes/Encuesta/FeedbackTab';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8000';

function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)token=([^;]*)/);
  if (match) return decodeURIComponent(match[1]);
  return sessionStorage.getItem('token') || localStorage.getItem('token');
}

export default function FeedbackPage() {
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [siguiente, setSiguiente] = useState<SiguienteFeedback | null>(null);
  const [status, setStatus] = useState<FeedbackStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toast = useRef<Toast>(null);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      setError('No hay sesión activa. Iniciá sesión primero.');
      setLoading(false);
      return;
    }
    fetch(`${BACKEND_URL}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((data) => {
        if (data.employeeId) {
          setEmployeeId(data.employeeId);
        } else {
          setError('Tu usuario no tiene un empleado asociado.');
          setLoading(false);
        }
      })
      .catch(() => {
        setError('No se pudo obtener la sesión. Recargá la página.');
        setLoading(false);
      });
  }, []);

  const cargarDatos = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    setError(null);
    try {
      const [siguienteRes, statusRes] = await Promise.all([
        apiClient.get<SiguienteFeedback>(`/feedback/siguiente/${employeeId}`),
        apiClient.get<{ evaluatorId: number; periodo: string; total: number; completadas: number }>(`/feedback/status/${employeeId}`),
      ]);
      setSiguiente(siguienteRes);
      setStatus({ total: statusRes.total, completadas: statusRes.completadas });
    } catch (e) {
      setError('No se pudieron cargar las evaluaciones pendientes. Intentá nuevamente.');
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const handleSubmit = async (valorEscala: number | null, textoLibre: string | null) => {
    if (!employeeId || !siguiente?.pregunta) return;
    try {
      await apiClient.post('/feedback/submit', {
        evaluadorId: employeeId,
        evaluadoId: siguiente.evaluado?.id ?? null,
        preguntaId: siguiente.pregunta.id,
        valorEscala,
        textoLibre,
      });
      toast.current?.show({ severity: 'success', summary: 'Enviado', detail: 'Feedback registrado correctamente', life: 3000 });
      await cargarDatos();
    } catch (e) {
      console.error(e);
      toast.current?.show({ severity: 'error', summary: 'Error', detail: 'No se pudo guardar el feedback', life: 4000 });
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <RefreshCw className="mx-auto mb-4 text-primary animate-spin" size={48} />
          <p className="text-muted-foreground text-lg">Cargando evaluaciones pendientes...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center bg-card p-8 rounded-xl shadow-md max-w-md">
          <User className="mx-auto mb-4 text-error" size={48} />
          <p className="text-error font-semibold text-lg mb-4">{error}</p>
          <button
            onClick={cargarDatos}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 transition-colors"
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen font-sans text-foreground p-4 sm:p-8">
      <Toast ref={toast} />
      <div className="max-w-7xl mx-auto">
        <header className="mb-8 text-center">
          <h1 className="font-heading text-4xl font-bold text-foreground mb-2">Sistema de Feedback 360°</h1>
          <p className="text-lg text-muted-foreground">
            Evaluá a tus compañeros y a tu superior directo de forma anónima.
          </p>
        </header>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          <div className="xl:col-span-2">
            <FeedbackTab
              siguiente={siguiente}
              status={status}
              loading={loading}
              onSubmit={handleSubmit}
            />
          </div>

          <div className="space-y-6">
            <Card title={
              <div className="flex items-center">
                <BarChart className="mr-2 text-primary" />
                <span>Tu progreso</span>
              </div>
            }>
              <div className="space-y-3">
                <div className="text-sm text-muted-foreground italic">
                  Las evaluaciones son anónimas. Solo el sistema registra los conteos generales.
                </div>
                <button
                  onClick={cargarDatos}
                  className="w-full mt-2 flex items-center justify-center gap-2 px-3 py-2 text-sm bg-primary/15 text-primary rounded-lg hover:bg-primary/20 transition-colors border border-primary/30"
                >
                  <RefreshCw size={14} />
                  Recargar
                </button>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "Encuesta/FeedbackTab|screens/Feedback/Screen"`
Expected: sin salida (sin errores nuevos en estos 2 archivos).

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/Encuesta/FeedbackTab.tsx src/app/screens/Feedback/Screen.tsx
git commit -m "feat: reescribir flujo de evaluacion de Feedback 360 con el banco de preguntas"
```

---

### Task 6: Frontend — pestaña "Verificar Evaluación de Equipo" en `ConfiguracionLicencias`

**Files:**
- Modify: `src/app/screens/ConfiguracionLicencias/Screen.tsx`

**Interfaces:**
- Consumes: `POST /feedback/verificar` → `{"reglas": [{regla: string, cumple: boolean, detalle: string}]}`. `GET /feedback/siguiente/{employeeId}` → mismo shape que en Task 5 (`SiguienteFeedback`, se consume acá sin importar el tipo, solo el shape plano).

- [ ] **Step 1: Agregar el ícono `ShieldCheck` al import de `lucide-react`**

Ubicar la línea de import de `lucide-react` (línea 3-20 del archivo actual) y agregar `ShieldCheck` a la lista de íconos importados.

- [ ] **Step 2: Extender el tipo `TabId` y agregar el estado nuevo**

Cambiar:
```typescript
type TabId = 'licencias' | 'contratos' | 'profesiones' | 'habilidades' | 'horarios' | 'feriados';
```
por:
```typescript
type TabId = 'licencias' | 'contratos' | 'profesiones' | 'habilidades' | 'horarios' | 'feriados' | 'verificacionFeedback';

interface ReglaVerificacion {
    regla: string;
    cumple: boolean;
    detalle: string;
}

interface SiguienteFeedbackDemo {
    evaluado: { id: number; name: string } | null;
    pregunta: { id: number; texto: string; tipo: string; opcionesEscala: string[] | null } | null;
}
```

Agregar, junto a los demás `useState` del componente (cerca de `const [feriados, setFeriados] = useState<Feriado[]>([]);`):

```typescript
const [reporteReglas, setReporteReglas] = useState<ReglaVerificacion[] | null>(null);
const [demoSiguiente, setDemoSiguiente] = useState<SiguienteFeedbackDemo | null>(null);
const [verificando, setVerificando] = useState(false);
```

- [ ] **Step 3: Agregar el handler de verificación**

Agregar junto a los demás handlers (cerca de `handleDeleteFeriado`):

```typescript
const handleVerificarFeedback = async () => {
    setVerificando(true);
    setReporteReglas(null);
    setDemoSiguiente(null);
    try {
        const reglasRes = await apiClient.post<{ reglas: ReglaVerificacion[] }>('/feedback/verificar');
        setReporteReglas(reglasRes.reglas);

        const empId = Number(localStorage.getItem('employeeId'));
        if (empId) {
            const demoRes = await apiClient.get<SiguienteFeedbackDemo>(`/feedback/siguiente/${empId}`);
            setDemoSiguiente(demoRes);
        }
    } catch (err) {
        console.error('Error al verificar evaluacion de equipo:', err);
    } finally {
        setVerificando(false);
    }
};
```

- [ ] **Step 4: Agregar el `TabButton` nuevo**

Ubicar el bloque de navegación de tabs (donde están los `<TabButton .../>`) y agregar, después de `<TabButton id="feriados" label="Feriados" icon={Settings} />`:

```tsx
<TabButton id="verificacionFeedback" label="Verificar Evaluación de Equipo" icon={ShieldCheck} />
```

- [ ] **Step 5: Agregar el contenido de la pestaña nueva**

Ubicar el cierre del bloque `{activeTab === 'feriados' && ( ... )}` (justo antes del `</div>` que cierra el contenedor principal de tabs) y agregar el bloque nuevo a continuación:

```tsx
{/* ── TAB 7: VERIFICAR EVALUACIÓN DE EQUIPO (temporal) ────────────── */}
{activeTab === 'verificacionFeedback' && (
    <div>
        <h2 className="font-heading text-lg font-bold text-foreground mb-2">Verificar Evaluación de Equipo</h2>
        <p className="text-sm text-muted-foreground mb-4">
            Herramienta temporal para validar las reglas de negocio del módulo de Feedback 360°: chequea los datos reales en busca de repeticiones indebidas y de preguntas de liderazgo mal asignadas, y muestra una ronda de ejemplo de la rotación.
        </p>

        <button
            onClick={handleVerificarFeedback}
            disabled={verificando}
            className="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 font-semibold disabled:opacity-50"
        >
            {verificando ? 'Verificando...' : 'Ejecutar verificación'}
        </button>

        {reporteReglas && (
            <div className="mt-6 space-y-3">
                <h3 className="font-semibold text-foreground">Reglas de negocio</h3>
                {reporteReglas.map((r, idx) => (
                    <div
                        key={idx}
                        className={`p-3 rounded-lg border ${r.cumple ? 'border-success bg-success-soft' : 'border-error bg-error-soft'}`}
                    >
                        <p className="font-semibold text-foreground">
                            {r.cumple ? '✅' : '❌'} {r.regla}
                        </p>
                        <p className="text-sm text-muted-foreground">{r.detalle}</p>
                    </div>
                ))}
            </div>
        )}

        {demoSiguiente && (
            <div className="mt-6">
                <h3 className="font-semibold text-foreground mb-2">Ronda de ejemplo (rotación)</h3>
                {demoSiguiente.pregunta ? (
                    <div className="p-3 rounded-lg border border-border bg-muted">
                        <p className="text-sm text-muted-foreground">
                            {demoSiguiente.evaluado ? `Evaluado: ${demoSiguiente.evaluado.name}` : 'Pregunta de ambiente laboral general'}
                        </p>
                        <p className="text-foreground font-medium mt-1">{demoSiguiente.pregunta.texto}</p>
                    </div>
                ) : (
                    <p className="text-muted-foreground italic">No hay pares pendientes para tu propio usuario en este período.</p>
                )}
            </div>
        )}
    </div>
)}
```

- [ ] **Step 6: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "ConfiguracionLicencias/Screen"`
Expected: solo los 2 errores preexistentes de `SoftSkill.id` en las líneas 316/319 (ya conocidos, fuera de alcance de este plan) — ningún error nuevo.

- [ ] **Step 7: Commit**

```bash
git add src/app/screens/ConfiguracionLicencias/Screen.tsx
git commit -m "feat: agregar pestana Verificar Evaluacion de Equipo en ConfiguracionLicencias"
```

---

### Task 7: Verificación manual

No hay test suite automatizado en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `GET /feedback/config` devuelve `{"periodicidad": "trimestral", ...}` por default.
- [ ] **Step 3:** Como usuario RRHH, `PUT /feedback/config {"periodicidad": "semestral"}` cambia la periodicidad; como usuario no-RRHH, el mismo `PUT` devuelve 403.
- [ ] **Step 4:** `GET /feedback/peers/{id}` de un empleado con `managerId` asignado incluye a ese superior en `evaluables`, con `esJerarquico` reflejando si tiene reportes/departamento a cargo.
- [ ] **Step 5:** `GET /feedback/siguiente/{id}` nunca devuelve una pregunta con evaluado que tenga `esJerarquico: false` si esa pregunta es de la categoría Liderazgo (verificar cruzando con `GET /feedback/preguntas?soloLiderazgo=true`).
- [ ] **Step 6:** Responder la misma pregunta+evaluado dos veces con `POST /feedback/submit` en el mismo período → la segunda vez devuelve 409.
- [ ] **Step 7:** Cambiar la periodicidad (Step 3) y confirmar que `GET /feedback/config` devuelve un `periodoActual` distinto si corresponde al nuevo cálculo.
- [ ] **Step 8:** Como RRHH, `POST /feedback/verificar` devuelve el reporte de 2 reglas; como usuario no-RRHH, devuelve 403.
- [ ] **Step 9:** En el frontend, abrir el módulo de Feedback como un empleado normal — confirmar que aparece una pregunta a la vez (escala o texto libre según corresponda), se puede responder, y el progreso se actualiza.
- [ ] **Step 10:** En el frontend, como RRHH, abrir `ConfiguracionLicencias` → pestaña "Verificar Evaluación de Equipo" → ejecutar la verificación y confirmar que se muestra el reporte de reglas y la ronda de ejemplo.
