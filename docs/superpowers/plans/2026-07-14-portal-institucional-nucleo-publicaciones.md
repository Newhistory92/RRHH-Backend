# Portal Institucional — Núcleo de Publicaciones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Primer subsistema del Portal de Comunicación Institucional: el backend completo de publicaciones (modelo de datos, targeting por organigrama, CRUD de autoría para HR/Admin, y el endpoint de feed filtrado del empleado), testeable de punta a punta por API.

**Architecture:** Dos tablas nuevas (`Publication` y su hija `PublicationTarget`) creadas idempotentemente con el patrón `ensure_table` del proyecto, en un módulo de datos `app/database/publications.py`. Un router nuevo `app/routes/publications.py` con 5 endpoints de autoría (`require_roles(ADMIN, RRHH)`) + 1 endpoint de feed del empleado (`require_any_auth`, self-or-admin). El estado efectivo (Programada/Publicada/Archivada) se calcula por fecha, sin cron. Todo SQL parametrizado, transacciones por endpoint.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc). Sin frontend (subsistema 2), sin adjuntos ni WYSIWYG (subsistema 3), sin búsqueda avanzada (subsistema 4).

## Global Constraints

- HR y Admin comparten permiso de publicar: todos los endpoints de autoría usan `require_roles(ROLE_ADMIN, ROLE_RRHH)` donde `ROLE_RRHH = ROLE_ADMIN` (patrón ya usado en `reubicacion.py`/`licenses.py`).
- Las 9 categorías son un set fijo validado en código: `Noticia Institucional`, `Circular`, `Resolución`, `Mantenimiento y Reparaciones`, `Aviso Importante`, `Evento Institucional`, `Oportunidad Interna`, `Beneficio para Empleados`, `Comunicación de RRHH`.
- Prioridades válidas: `Baja`, `Normal`, `Alta`, `Urgente`. Estados de mantenimiento válidos: `Programado`, `En curso`, `Completado`, `Suspendido`, `Reprogramado`.
- `estadoMantenimiento` solo se acepta cuando `categoria == "Mantenimiento y Reparaciones"`; en cualquier otra categoría con ese campo presente → 400.
- Al crear con `categoria == "Aviso Importante"` y sin `fijada` explícito, `fijada` se setea a `true`.
- Targeting con herencia depto→oficina: sale gratis del modelo (un empleado de oficina también lleva su `departmentId`). No requiere lógica especial en la query.
- Target explícito obligatorio: `targets` vacío → 400 (`"Debe indicar al menos un destino"`). No hay default a institución.
- Estado efectivo calculado por fecha (sin cron): solo se persiste `esBorrador`; Programada/Publicada/Archivada se derivan de `fechaPublicacion`/`fechaExpiracion`.
- Soft-delete: `DELETE` setea `activo=0` (patrón `EmployeeDocument`); nunca borra físicamente.
- Feed self-or-admin: un empleado solo pide su propio feed; Admin puede pedir cualquiera (patrón `_check_self_or_admin` de `reubicacion.py`).
- Sin suite automatizada en el repo — verificación por `py_compile` más pruebas manuales por API.

---

### Task 1: Modelo de datos — `app/database/publications.py`

**Files:**
- Create: `app/database/publications.py`

**Interfaces:**
- Produces: `ensure_table(db: Session) -> None`; constantes `VALID_CATEGORIAS: set[str]`, `VALID_PRIORIDADES: set[str]`, `VALID_ESTADOS_MANTENIMIENTO: set[str]`, `CATEGORIA_AVISO_IMPORTANTE: str`, `CATEGORIA_MANTENIMIENTO: str`.

- [ ] **Step 1: Crear `app/database/publications.py`**

```python
"""
Portal de Comunicacion Institucional -- nucleo de publicaciones (subsistema 1).
Modelo de datos: Publication (tabla principal) + PublicationTarget (destinos,
1:N). Estado efectivo (Programada/Publicada/Archivada) se calcula por fecha;
solo se persiste esBorrador. Creacion idempotente via ensure_table.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text


CATEGORIA_AVISO_IMPORTANTE = "Aviso Importante"
CATEGORIA_MANTENIMIENTO = "Mantenimiento y Reparaciones"

VALID_CATEGORIAS = {
    "Noticia Institucional",
    "Circular",
    "Resolución",
    CATEGORIA_MANTENIMIENTO,
    CATEGORIA_AVISO_IMPORTANTE,
    "Evento Institucional",
    "Oportunidad Interna",
    "Beneficio para Empleados",
    "Comunicación de RRHH",
}

VALID_PRIORIDADES = {"Baja", "Normal", "Alta", "Urgente"}

VALID_ESTADOS_MANTENIMIENTO = {
    "Programado",
    "En curso",
    "Completado",
    "Suspendido",
    "Reprogramado",
}

VALID_SCOPES = {"institucion", "departamento", "oficina"}


CREATE_PUBLICATION_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'Publication' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Publication (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        titulo              NVARCHAR(300)  NOT NULL,
        resumen             NVARCHAR(MAX)  NULL,
        contenido           NVARCHAR(MAX)  NULL,
        categoria           NVARCHAR(50)   NOT NULL,
        prioridad           NVARCHAR(20)   NOT NULL DEFAULT 'Normal',
        estadoMantenimiento NVARCHAR(20)   NULL,
        esBorrador          BIT            NOT NULL DEFAULT 1,
        destacada           BIT            NOT NULL DEFAULT 0,
        fijada              BIT            NOT NULL DEFAULT 0,
        fechaPublicacion    DATETIME2      NULL,
        fechaExpiracion     DATETIME2      NULL,
        autorEmployeeId     INT            NULL,
        activo              BIT            NOT NULL DEFAULT 1,
        createdAt           DATETIME2      NOT NULL,
        updatedAt           DATETIME2      NOT NULL
    );
END
"""

CREATE_TARGET_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'PublicationTarget' AND xtype = 'U'
)
BEGIN
    CREATE TABLE PublicationTarget (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        publicationId INT           NOT NULL,
        scope         NVARCHAR(20)  NOT NULL,
        departmentId  INT           NULL,
        officeId      INT           NULL
    );
    CREATE INDEX IX_PublicationTarget_publicationId ON PublicationTarget (publicationId);
END
"""


def ensure_table(db: Session) -> None:
    """Crea Publication y PublicationTarget si no existen (idempotente)."""
    db.execute(text(CREATE_PUBLICATION_SQL))
    db.execute(text(CREATE_TARGET_SQL))
    db.commit()
```

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/database/publications.py`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
git add app/database/publications.py
git commit -m "feat: agregar modelo de datos de publicaciones del portal institucional"
```

---

### Task 2: Router — helpers, autoría (POST/PUT/DELETE) y registro

**Files:**
- Create: `app/routes/publications.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ensure_table`, `VALID_CATEGORIAS`, `VALID_PRIORIDADES`, `VALID_ESTADOS_MANTENIMIENTO`, `VALID_SCOPES`, `CATEGORIA_AVISO_IMPORTANTE`, `CATEGORIA_MANTENIMIENTO` (Task 1).
- Produces: `POST /publications`, `PUT /publications/{id}`, `DELETE /publications/{id}` (`require_rrhh_auth`). Helpers `get_db`, `_check_self_or_admin`, `_estado_efectivo`, `_validar_payload`, `_insertar_targets`.

- [ ] **Step 1: Crear `app/routes/publications.py` con helpers y validación**

```python
"""
Router /publications -- nucleo de publicaciones del Portal Institucional
(subsistema 1). Autoria (HR/Admin) + feed filtrado del empleado.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.publications import (
    ensure_table,
    VALID_CATEGORIAS,
    VALID_PRIORIDADES,
    VALID_ESTADOS_MANTENIMIENTO,
    VALID_SCOPES,
    CATEGORIA_AVISO_IMPORTANTE,
    CATEGORIA_MANTENIMIENTO,
)

router = APIRouter(prefix="/publications", tags=["Publications"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _check_self_or_admin(employee_id: int, current_user: dict) -> None:
    """Evita que un empleado lea el feed de otro."""
    if employee_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenes permiso para acceder a esta informacion.")


def _estado_efectivo(pub, ahora: datetime) -> str:
    """Calcula el estado efectivo de una publicacion a partir de sus fechas."""
    if pub["esBorrador"]:
        return "Borrador"
    fp = pub["fechaPublicacion"]
    fe = pub["fechaExpiracion"]
    if fp and fp > ahora:
        return "Programada"
    if fe is None or fe >= ahora:
        return "Publicada"
    return "Archivada"


def _parse_dt(value) -> Optional[datetime]:
    """Convierte un ISO string a datetime; devuelve None si es falsy."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("+00:00", ""))


def _validar_payload(data: dict) -> tuple:
    """Valida el body de crear/editar. Devuelve (fecha_pub, fecha_exp, fijada, targets).
    Lanza HTTPException 400 ante cualquier dato invalido."""
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(status_code=400, detail="El titulo es obligatorio")

    categoria = data.get("categoria")
    if categoria not in VALID_CATEGORIAS:
        raise HTTPException(status_code=400, detail=f"categoria debe ser una de: {sorted(VALID_CATEGORIAS)}")

    prioridad = data.get("prioridad") or "Normal"
    if prioridad not in VALID_PRIORIDADES:
        raise HTTPException(status_code=400, detail=f"prioridad debe ser una de: {sorted(VALID_PRIORIDADES)}")

    estado_mant = data.get("estadoMantenimiento")
    if estado_mant is not None:
        if categoria != CATEGORIA_MANTENIMIENTO:
            raise HTTPException(status_code=400, detail="estadoMantenimiento solo aplica a la categoria Mantenimiento y Reparaciones")
        if estado_mant not in VALID_ESTADOS_MANTENIMIENTO:
            raise HTTPException(status_code=400, detail=f"estadoMantenimiento debe ser uno de: {sorted(VALID_ESTADOS_MANTENIMIENTO)}")

    targets = data.get("targets") or []
    if not targets:
        raise HTTPException(status_code=400, detail="Debe indicar al menos un destino")
    for t in targets:
        scope = t.get("scope")
        if scope not in VALID_SCOPES:
            raise HTTPException(status_code=400, detail=f"scope debe ser uno de: {sorted(VALID_SCOPES)}")
        if scope == "departamento" and not t.get("departmentId"):
            raise HTTPException(status_code=400, detail="scope 'departamento' requiere departmentId")
        if scope == "oficina" and not t.get("officeId"):
            raise HTTPException(status_code=400, detail="scope 'oficina' requiere officeId")

    fecha_pub = _parse_dt(data.get("fechaPublicacion"))
    fecha_exp = _parse_dt(data.get("fechaExpiracion"))
    if fecha_pub and fecha_exp and fecha_exp < fecha_pub:
        raise HTTPException(status_code=400, detail="fechaExpiracion no puede ser anterior a fechaPublicacion")

    # Aviso Importante: fijada por defecto True si no viene explicito
    fijada = data.get("fijada")
    if fijada is None:
        fijada = categoria == CATEGORIA_AVISO_IMPORTANTE

    return fecha_pub, fecha_exp, bool(fijada), targets


def _insertar_targets(db: Session, publication_id: int, targets: list) -> None:
    """Inserta las filas de PublicationTarget para una publicacion."""
    for t in targets:
        db.execute(text("""
            INSERT INTO PublicationTarget (publicationId, scope, departmentId, officeId)
            VALUES (:pid, :scope, :departmentId, :officeId)
        """), {
            "pid": publication_id,
            "scope": t.get("scope"),
            "departmentId": t.get("departmentId") if t.get("scope") == "departamento" else None,
            "officeId": t.get("officeId") if t.get("scope") == "oficina" else None,
        })
```

- [ ] **Step 2: Agregar `POST /publications` al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# POST /publications — crear publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_rrhh_auth)])
def create_publication(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea una publicacion con sus destinos, en una transaccion."""
    fecha_pub, fecha_exp, fijada, targets = _validar_payload(data)

    ensure_table(db)

    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO Publication
            (titulo, resumen, contenido, categoria, prioridad, estadoMantenimiento,
             esBorrador, destacada, fijada, fechaPublicacion, fechaExpiracion,
             autorEmployeeId, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES
            (:titulo, :resumen, :contenido, :categoria, :prioridad, :estadoMantenimiento,
             :esBorrador, :destacada, :fijada, :fechaPublicacion, :fechaExpiracion,
             :autorEmployeeId, 1, :now, :now)
    """), {
        "titulo": data.get("titulo").strip(),
        "resumen": data.get("resumen"),
        "contenido": data.get("contenido"),
        "categoria": data.get("categoria"),
        "prioridad": data.get("prioridad") or "Normal",
        "estadoMantenimiento": data.get("estadoMantenimiento"),
        "esBorrador": 1 if data.get("esBorrador", True) else 0,
        "destacada": 1 if data.get("destacada") else 0,
        "fijada": 1 if fijada else 0,
        "fechaPublicacion": fecha_pub,
        "fechaExpiracion": fecha_exp,
        "autorEmployeeId": data.get("autorEmployeeId"),
        "now": now,
    })
    new_id = result.fetchone()[0]

    _insertar_targets(db, new_id, targets)

    db.commit()
    return {"message": "Publicacion creada", "id": new_id}
```

- [ ] **Step 3: Agregar `PUT /publications/{id}` al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# PUT /publications/{publication_id} — editar publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def update_publication(publication_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Edita una publicacion y reescribe su set de destinos, en una transaccion."""
    fecha_pub, fecha_exp, fijada, targets = _validar_payload(data)

    ensure_table(db)

    existing = db.execute(text("""
        SELECT id FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE Publication
        SET titulo = :titulo, resumen = :resumen, contenido = :contenido,
            categoria = :categoria, prioridad = :prioridad, estadoMantenimiento = :estadoMantenimiento,
            esBorrador = :esBorrador, destacada = :destacada, fijada = :fijada,
            fechaPublicacion = :fechaPublicacion, fechaExpiracion = :fechaExpiracion,
            updatedAt = :now
        WHERE id = :id
    """), {
        "titulo": data.get("titulo").strip(),
        "resumen": data.get("resumen"),
        "contenido": data.get("contenido"),
        "categoria": data.get("categoria"),
        "prioridad": data.get("prioridad") or "Normal",
        "estadoMantenimiento": data.get("estadoMantenimiento"),
        "esBorrador": 1 if data.get("esBorrador", True) else 0,
        "destacada": 1 if data.get("destacada") else 0,
        "fijada": 1 if fijada else 0,
        "fechaPublicacion": fecha_pub,
        "fechaExpiracion": fecha_exp,
        "now": now,
        "id": publication_id,
    })

    db.execute(text("DELETE FROM PublicationTarget WHERE publicationId = :id"), {"id": publication_id})
    _insertar_targets(db, publication_id, targets)

    db.commit()
    return {"message": "Publicacion actualizada", "id": publication_id}
```

- [ ] **Step 4: Agregar `DELETE /publications/{id}` al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# DELETE /publications/{publication_id} — soft-delete (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def delete_publication(publication_id: int, db: Session = Depends(get_db)):
    """Baja logica de una publicacion (activo=0)."""
    ensure_table(db)

    existing = db.execute(text("""
        SELECT id FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    db.execute(text("""
        UPDATE Publication SET activo = 0, updatedAt = :now WHERE id = :id
    """), {"now": datetime.utcnow(), "id": publication_id})
    db.commit()
    return {"message": "Publicacion eliminada"}
```

- [ ] **Step 5: Registrar el router en `app/main.py`**

Reemplazar la línea de import:
```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion
```
por:
```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications
```

Reemplazar:
```python
app.include_router(reubicacion.router)
```
por:
```python
app.include_router(reubicacion.router)
app.include_router(publications.router)
```

- [ ] **Step 6: Verificar que compila**

Run: `py -m py_compile app/routes/publications.py app/main.py`
Expected: sin salida.

- [ ] **Step 7: Commit**

```bash
git add app/routes/publications.py app/main.py
git commit -m "feat: agregar autoria de publicaciones (crear/editar/borrar) y registrar router"
```

---

### Task 3: Router — lectura (GET listado admin, GET detalle, GET feed del empleado)

**Files:**
- Modify: `app/routes/publications.py`

**Interfaces:**
- Consumes: `get_db`, `_check_self_or_admin`, `_estado_efectivo`, `require_rrhh_auth`, `require_any_auth`, `get_current_user`, `ensure_table` (Tasks 1-2).
- Produces: `GET /publications` (`require_rrhh_auth`), `GET /publications/{id}` (`require_rrhh_auth`), `GET /publications/feed` (`require_any_auth`).

- [ ] **Step 1: Agregar un helper para leer los targets de una publicación**

Al final del archivo `app/routes/publications.py`:

```python
def _targets_de(db: Session, publication_id: int) -> list:
    """Devuelve los destinos de una publicacion."""
    rows = db.execute(text("""
        SELECT scope, departmentId, officeId
        FROM PublicationTarget WHERE publicationId = :id
    """), {"id": publication_id}).mappings().all()
    return [
        {"scope": r["scope"], "departmentId": r["departmentId"], "officeId": r["officeId"]}
        for r in rows
    ]
```

- [ ] **Step 2: Agregar `GET /publications` (listado admin) al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /publications — listado admin (HR/Admin), con filtros opcionales
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", dependencies=[Depends(require_rrhh_auth)])
def list_publications(categoria: Optional[str] = None, estado: Optional[str] = None, db: Session = Depends(get_db)):
    """Lista publicaciones activas con su estado efectivo y sus destinos."""
    ensure_table(db)

    query = "SELECT * FROM Publication WHERE activo = 1"
    params = {}
    if categoria:
        query += " AND categoria = :categoria"
        params["categoria"] = categoria
    query += " ORDER BY createdAt DESC"

    rows = db.execute(text(query), params).mappings().all()
    ahora = datetime.utcnow()

    result = []
    for r in rows:
        est = _estado_efectivo(r, ahora)
        if estado and est != estado:
            continue
        result.append({
            "id": r["id"],
            "titulo": r["titulo"],
            "resumen": r["resumen"],
            "contenido": r["contenido"],
            "categoria": r["categoria"],
            "prioridad": r["prioridad"],
            "estadoMantenimiento": r["estadoMantenimiento"],
            "estado": est,
            "esBorrador": bool(r["esBorrador"]),
            "destacada": bool(r["destacada"]),
            "fijada": bool(r["fijada"]),
            "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
            "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
            "autorEmployeeId": r["autorEmployeeId"],
            "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
            "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            "targets": _targets_de(db, r["id"]),
        })

    return {"publications": result}
```

- [ ] **Step 3: Agregar `GET /publications/feed` al final del archivo**

Nota: se define ANTES de `GET /publications/{id}` para que FastAPI matchee la ruta literal `/feed` y no la capture el parámetro `{publication_id}`.

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /publications/feed — feed filtrado del empleado (self-or-admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/feed", dependencies=[Depends(require_any_auth)])
def get_feed(employeeId: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Publicaciones visibles para el empleado: publicadas por fecha y dirigidas
    a el (institucion, su departamento o su oficina)."""
    _check_self_or_admin(employeeId, current_user)

    ensure_table(db)

    empleado = db.execute(text("""
        SELECT departmentId, officeId FROM Employee WHERE id = :id
    """), {"id": employeeId}).mappings().first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    dep_id = empleado["departmentId"]
    off_id = empleado["officeId"]

    rows = db.execute(text("""
        SELECT DISTINCT p.*
        FROM Publication p
        INNER JOIN PublicationTarget t ON t.publicationId = p.id
        WHERE p.activo = 1
          AND p.esBorrador = 0
          AND (p.fechaPublicacion IS NULL OR p.fechaPublicacion <= GETDATE())
          AND (p.fechaExpiracion IS NULL OR p.fechaExpiracion >= GETDATE())
          AND (
                t.scope = 'institucion'
                OR (t.scope = 'departamento' AND t.departmentId = :depId)
                OR (t.scope = 'oficina' AND t.officeId = :offId)
              )
        ORDER BY p.fijada DESC, p.fechaPublicacion DESC
    """), {"depId": dep_id, "offId": off_id}).mappings().all()

    return {
        "publications": [
            {
                "id": r["id"],
                "titulo": r["titulo"],
                "resumen": r["resumen"],
                "contenido": r["contenido"],
                "categoria": r["categoria"],
                "prioridad": r["prioridad"],
                "estadoMantenimiento": r["estadoMantenimiento"],
                "destacada": bool(r["destacada"]),
                "fijada": bool(r["fijada"]),
                "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
                "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
            }
            for r in rows
        ]
    }
```

- [ ] **Step 4: Agregar `GET /publications/{id}` (detalle) al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /publications/{publication_id} — detalle para edicion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{publication_id}", dependencies=[Depends(require_rrhh_auth)])
def get_publication(publication_id: int, db: Session = Depends(get_db)):
    """Detalle de una publicacion con sus destinos."""
    ensure_table(db)

    r = db.execute(text("""
        SELECT * FROM Publication WHERE id = :id AND activo = 1
    """), {"id": publication_id}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="Publicacion no encontrada")

    return {
        "id": r["id"],
        "titulo": r["titulo"],
        "resumen": r["resumen"],
        "contenido": r["contenido"],
        "categoria": r["categoria"],
        "prioridad": r["prioridad"],
        "estadoMantenimiento": r["estadoMantenimiento"],
        "estado": _estado_efectivo(r, datetime.utcnow()),
        "esBorrador": bool(r["esBorrador"]),
        "destacada": bool(r["destacada"]),
        "fijada": bool(r["fijada"]),
        "fechaPublicacion": r["fechaPublicacion"].isoformat() if r["fechaPublicacion"] else None,
        "fechaExpiracion": r["fechaExpiracion"].isoformat() if r["fechaExpiracion"] else None,
        "autorEmployeeId": r["autorEmployeeId"],
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
        "targets": _targets_de(db, r["id"]),
    }
```

- [ ] **Step 5: Verificar que compila**

Run: `py -m py_compile app/routes/publications.py`
Expected: sin salida.

- [ ] **Step 6: Commit**

```bash
git add app/routes/publications.py
git commit -m "feat: agregar lectura de publicaciones (listado admin, detalle, feed del empleado)"
```

---

### Task 4: Verificación manual

No hay test suite automatizada en el repo — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error (las tablas `Publication`/`PublicationTarget` se crean en el primer request vía `ensure_table`).
- [ ] **Step 2:** `POST /publications` (como Admin/RRHH) sin `titulo`, con `categoria` inválida, con `prioridad` inválida, o con `targets` vacío → 400 en cada caso.
- [ ] **Step 3:** `POST /publications` con `estadoMantenimiento` en una categoría distinta de "Mantenimiento y Reparaciones" → 400; en Mantenimiento con un valor válido → crea OK.
- [ ] **Step 4:** `POST /publications` con `categoria="Aviso Importante"` sin enviar `fijada` → la publicación queda con `fijada=true` (verificable con `GET /publications/{id}`).
- [ ] **Step 5:** `POST /publications` con `fechaExpiracion` anterior a `fechaPublicacion` → 400.
- [ ] **Step 6:** `GET /publications` (admin) devuelve el `estado` efectivo correcto: una con `fechaPublicacion` futura sale "Programada"; una con `fechaExpiracion` pasada sale "Archivada"; una con `esBorrador=true` sale "Borrador"; una vigente sale "Publicada".
- [ ] **Step 7:** Targeting end-to-end: crear tres publicaciones finalizadas y vigentes — una a `scope=institucion`, una a `scope=departamento` (Depto D), una a `scope=oficina` (Oficina O de D). `GET /publications/feed?employeeId=X` como: un empleado de otra área (ve solo la de institución); un empleado directo de D sin oficina (ve institución + D); un empleado de la Oficina O (ve las tres — confirma herencia depto→oficina).
- [ ] **Step 8:** Una publicación con `fechaPublicacion` futura NO aparece en el feed; simulando que llegó su fecha (crear una con fecha pasada) SÍ aparece; una con `fechaExpiracion` pasada NO aparece.
- [ ] **Step 9:** `DELETE /publications/{id}` → la publicación deja de aparecer en `GET /publications` y en el feed, pero sigue en la DB con `activo=0`.
- [ ] **Step 10:** `GET /publications/feed?employeeId=Y` pidiendo el feed de OTRO empleado siendo un USER (rol 2) → 403; siendo Admin → OK.
- [ ] **Step 11:** Un USER (rol 2) intentando `POST`/`PUT`/`DELETE /publications` → 403; solo Admin/RRHH pueden.
