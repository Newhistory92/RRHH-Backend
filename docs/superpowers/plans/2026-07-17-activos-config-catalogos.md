# Sistema de Activos — Configuración + catálogos (Subsistema 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la fundación de configuración del Sistema de Activos: cuatro tablas de metadata (categorías/taxonomía, fabricantes, proveedores, estados) con CRUD admin y una pantalla de configuración.

**Architecture:** Backend FastAPI con cuatro tablas creadas + sembradas idempotentemente (`ensure_tables`), helpers de consulta en el módulo de datos, y un router CRUD (`require_any_auth` para leer, `require_roles(ADMIN)` para escribir). Frontend Next.js con un componente CRUD genérico reutilizable y una pantalla de config con 4 pestañas.

**Tech Stack:** FastAPI + SQLAlchemy `text()` + SQL Server (pyodbc) · Next.js App Router + React + Tailwind · lucide-react.

## Global Constraints

- **Prefijo `Activo`** para todas las tablas del módulo: `ActivoCategoria`, `ActivoFabricante`, `ActivoProveedor`, `ActivoEstado`.
- **Taxonomía unificada**: una sola `ActivoCategoria` con `grupo` ∈ `{Equipo, Componente, Accesorio, Mobiliario}`. No hay tablas separadas para componentes/mobiliario.
- **RBAC grueso**: lecturas con `require_any_auth` (selectores para S2+); escrituras solo `require_roles(ADMIN)`. El RBAC fino es un subsistema posterior.
- **Seed idempotente**: solo siembra cuando la tabla está vacía; reinicios nunca duplican.
- **Estados núcleo (`esCore=1`)**: los 10 del enunciado no se eliminan (400 en DELETE); los custom sí.
- **SQL parametrizado**: valores bindeados, sin concatenación de strings de usuario.
- **Tokens "Orgánico Cálido"** en frontend (`bg-card`, `bg-background`, `border-border`, `shadow-soft`, `text-foreground`, `text-muted-foreground`, `text-primary`, `bg-primary/10`), sin hex crudo. Dark mode por tokens.
- **Sin suite de tests automatizada** (patrón del proyecto): verificación por tarea = compilación (`py -m py_compile` / `npx tsc --noEmit`) + chequeo manual.
- **Grupos válidos**: `Equipo, Componente, Accesorio, Mobiliario`. Prioridad de categorías por grupo, sin duplicar nombre dentro del mismo grupo (case-insensitive).

---

## File Structure

**Backend_RRHH:**
- Create: `app/database/activos_config.py` — las 4 tablas (`ensure_tables`), seed idempotente, `VALID_GRUPOS`, helpers de listado.
- Create: `app/routes/activos_config.py` — router CRUD de las 4 entidades.
- Modify: `app/main.py` — importar y registrar el router.

**RRHH:**
- Modify: `src/app/Interfas/Interfaces.ts` — `"activos-config"` en `Page` + interfaces de las 4 entidades.
- Create: `src/app/Componentes/ActivosConfig/ConfigCrudSection.tsx` — componente CRUD genérico reutilizable.
- Create: `src/app/screens/ActivosConfig/Screen.tsx` — pantalla con 4 pestañas.
- Modify: `src/app/util/rbac.ts` — sección `"Activos"` + entrada `activos-config`.
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx` — ícono `Boxes`.
- Modify: `src/app/page.tsx` — `case 'activos-config'`.

---

## Task 1: Backend — módulo de datos `activos_config.py`

**Files:**
- Create: `app/database/activos_config.py`

**Interfaces:**
- Consumes: nada (módulo base).
- Produces: `ensure_tables(db)`, `VALID_GRUPOS`, `listar_categorias(db, grupo=None)`, `listar_fabricantes(db)`, `listar_proveedores(db)`, `listar_estados(db)`, `estado_es_core(db, id)`.

- [ ] **Step 1: Crear el módulo con las 4 tablas, seed y helpers**

```python
"""
Configuracion y catalogos del Sistema de Activos (subsistema 1).
Cuatro tablas de metadata que el resto del modulo referencia:
ActivoCategoria (taxonomia unificada), ActivoFabricante, ActivoProveedor,
ActivoEstado. Creacion + seed idempotente via ensure_tables.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


VALID_GRUPOS = {"Equipo", "Componente", "Accesorio", "Mobiliario"}


CREATE_CATEGORIA_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoCategoria' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoCategoria (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        nombre        NVARCHAR(150) NOT NULL,
        grupo         NVARCHAR(20)  NOT NULL,
        montableEnPC  BIT           NOT NULL DEFAULT 0,
        requiereSerie BIT           NOT NULL DEFAULT 0,
        vidaUtilAnios INT           NULL,
        activo        BIT           NOT NULL DEFAULT 1,
        createdAt     DATETIME2     NOT NULL,
        updatedAt     DATETIME2     NOT NULL
    );
END
"""

CREATE_FABRICANTE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoFabricante' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoFabricante (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(150) NOT NULL,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

CREATE_PROVEEDOR_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoProveedor' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoProveedor (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(150) NOT NULL,
        contacto  NVARCHAR(300) NULL,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

CREATE_ESTADO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoEstado' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoEstado (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        nombre    NVARCHAR(50)  NOT NULL,
        codigo    NVARCHAR(30)  NOT NULL,
        orden     INT           NOT NULL DEFAULT 0,
        esCore    BIT           NOT NULL DEFAULT 0,
        activo    BIT           NOT NULL DEFAULT 1,
        createdAt DATETIME2     NOT NULL,
        updatedAt DATETIME2     NOT NULL
    );
END
"""

# (nombre, grupo, montableEnPC)
_SEED_CATEGORIAS = [
    ("CPU", "Componente", 1),
    ("Disipadores CPU", "Componente", 1),
    ("Placas Base", "Componente", 1),
    ("Memoria RAM", "Componente", 1),
    ("Almacenamiento", "Componente", 1),
    ("Tarjetas de Video", "Componente", 1),
    ("Gabinetes", "Componente", 1),
    ("Fuentes de Alimentación", "Componente", 1),
    ("Unidades Ópticas", "Componente", 1),
    ("Sistemas Operativos", "Componente", 1),
    ("Almacenamiento Externo", "Componente", 0),
    ("Tarjetas de Sonido", "Componente", 1),
    ("Adaptadores de Red Cableados", "Componente", 1),
    ("Adaptadores de Red Inalámbricos", "Componente", 1),
    ("PC", "Equipo", 0),
    ("Monitor", "Equipo", 0),
    ("UPS", "Accesorio", 0),
    ("Impresoras", "Accesorio", 0),
    ("Escáneres", "Accesorio", 0),
    ("Fotocopiadoras", "Accesorio", 0),
]

# (nombre, codigo)
_SEED_ESTADOS = [
    ("Disponible", "disponible"),
    ("Asignado", "asignado"),
    ("En reparación", "en_reparacion"),
    ("Dañado", "danado"),
    ("En depósito", "en_deposito"),
    ("Prestado", "prestado"),
    ("En garantía", "en_garantia"),
    ("Dado de baja", "dado_de_baja"),
    ("Extraviado", "extraviado"),
    ("Robado", "robado"),
]


def ensure_tables(db: Session) -> None:
    """Crea las 4 tablas de config si no existen y las siembra si estan vacias."""
    db.execute(text(CREATE_CATEGORIA_SQL))
    db.execute(text(CREATE_FABRICANTE_SQL))
    db.execute(text(CREATE_PROVEEDOR_SQL))
    db.execute(text(CREATE_ESTADO_SQL))
    db.commit()

    now = datetime.utcnow()

    cat_count = db.execute(text("SELECT COUNT(*) FROM ActivoCategoria")).scalar()
    if cat_count == 0:
        for nombre, grupo, montable in _SEED_CATEGORIAS:
            db.execute(text("""
                INSERT INTO ActivoCategoria (nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios, activo, createdAt, updatedAt)
                VALUES (:nombre, :grupo, :montable, 0, NULL, 1, :now, :now)
            """), {"nombre": nombre, "grupo": grupo, "montable": montable, "now": now})

    est_count = db.execute(text("SELECT COUNT(*) FROM ActivoEstado")).scalar()
    if est_count == 0:
        for i, (nombre, codigo) in enumerate(_SEED_ESTADOS):
            db.execute(text("""
                INSERT INTO ActivoEstado (nombre, codigo, orden, esCore, activo, createdAt, updatedAt)
                VALUES (:nombre, :codigo, :orden, 1, 1, :now, :now)
            """), {"nombre": nombre, "codigo": codigo, "orden": i, "now": now})

    db.commit()


def listar_categorias(db: Session, grupo: str | None = None) -> list[dict]:
    """Categorias activas, opcionalmente filtradas por grupo, ordenadas por grupo y nombre."""
    query = "SELECT id, nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios FROM ActivoCategoria WHERE activo = 1"
    params = {}
    if grupo:
        query += " AND grupo = :grupo"
        params["grupo"] = grupo
    query += " ORDER BY grupo, nombre"
    rows = db.execute(text(query), params).mappings().all()
    return [
        {
            "id": r["id"], "nombre": r["nombre"], "grupo": r["grupo"],
            "montableEnPC": bool(r["montableEnPC"]), "requiereSerie": bool(r["requiereSerie"]),
            "vidaUtilAnios": r["vidaUtilAnios"],
        }
        for r in rows
    ]


def listar_fabricantes(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre FROM ActivoFabricante WHERE activo = 1 ORDER BY nombre")).mappings().all()
    return [dict(r) for r in rows]


def listar_proveedores(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre, contacto FROM ActivoProveedor WHERE activo = 1 ORDER BY nombre")).mappings().all()
    return [dict(r) for r in rows]


def listar_estados(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id, nombre, codigo, orden, esCore FROM ActivoEstado WHERE activo = 1 ORDER BY orden, nombre")).mappings().all()
    return [
        {"id": r["id"], "nombre": r["nombre"], "codigo": r["codigo"], "orden": r["orden"], "esCore": bool(r["esCore"])}
        for r in rows
    ]


def estado_es_core(db: Session, estado_id: int) -> bool:
    r = db.execute(text("SELECT esCore FROM ActivoEstado WHERE id = :id"), {"id": estado_id}).mappings().first()
    return bool(r["esCore"]) if r else False
```

- [ ] **Step 2: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/database/activos_config.py`
Expected: sin salida (exit 0).

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/database/activos_config.py
git commit -m "feat: agregar modelo de datos de configuracion del sistema de activos"
```

---

## Task 2: Backend — router CRUD `activos_config.py` + registro

**Files:**
- Create: `app/routes/activos_config.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ensure_tables`, `VALID_GRUPOS`, `listar_*`, `estado_es_core` (Task 1); `require_any_auth`, `require_roles`, `ROLE_ADMIN`, `SessionLocal`.
- Produces: `GET/POST/PUT/DELETE /activos/config/{categorias|fabricantes|proveedores|estados}`.

- [ ] **Step 1: Crear el router**

```python
"""
Router /activos/config -- CRUD de la configuracion del Sistema de Activos
(subsistema 1). Lecturas: cualquier autenticado (selectores). Escrituras:
solo ADMIN.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN
from app.database.activos_config import (
    ensure_tables, VALID_GRUPOS,
    listar_categorias, listar_fabricantes, listar_proveedores, listar_estados,
    estado_es_core,
)

router = APIRouter(prefix="/activos/config", tags=["Activos Config"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _nombre_valido(data: dict) -> str:
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    return nombre


# ─── Categorias ──────────────────────────────────────────────────────────────
@router.get("/categorias", dependencies=[Depends(require_any_auth)])
def get_categorias(grupo: Optional[str] = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"categorias": listar_categorias(db, grupo)}


@router.post("/categorias", dependencies=[Depends(require_admin)])
def crear_categoria(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    grupo = data.get("grupo")
    if grupo not in VALID_GRUPOS:
        raise HTTPException(status_code=400, detail=f"grupo debe ser uno de: {sorted(VALID_GRUPOS)}")
    dup = db.execute(text("""
        SELECT id FROM ActivoCategoria WHERE activo = 1 AND grupo = :grupo AND LOWER(nombre) = LOWER(:nombre)
    """), {"grupo": grupo, "nombre": nombre}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe una categoria con ese nombre en el grupo")
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoCategoria (nombre, grupo, montableEnPC, requiereSerie, vidaUtilAnios, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :grupo, :montable, :serie, :vida, 1, :now, :now)
    """), {
        "nombre": nombre, "grupo": grupo,
        "montable": 1 if data.get("montableEnPC") else 0,
        "serie": 1 if data.get("requiereSerie") else 0,
        "vida": data.get("vidaUtilAnios"),
        "now": now,
    })
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/categorias/{cat_id}", dependencies=[Depends(require_admin)])
def actualizar_categoria(cat_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    grupo = data.get("grupo")
    if grupo not in VALID_GRUPOS:
        raise HTTPException(status_code=400, detail=f"grupo debe ser uno de: {sorted(VALID_GRUPOS)}")
    existing = db.execute(text("SELECT id FROM ActivoCategoria WHERE id = :id AND activo = 1"), {"id": cat_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    dup = db.execute(text("""
        SELECT id FROM ActivoCategoria WHERE activo = 1 AND grupo = :grupo AND LOWER(nombre) = LOWER(:nombre) AND id <> :id
    """), {"grupo": grupo, "nombre": nombre, "id": cat_id}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe una categoria con ese nombre en el grupo")
    db.execute(text("""
        UPDATE ActivoCategoria SET nombre = :nombre, grupo = :grupo, montableEnPC = :montable,
            requiereSerie = :serie, vidaUtilAnios = :vida, updatedAt = :now WHERE id = :id
    """), {
        "nombre": nombre, "grupo": grupo,
        "montable": 1 if data.get("montableEnPC") else 0,
        "serie": 1 if data.get("requiereSerie") else 0,
        "vida": data.get("vidaUtilAnios"),
        "now": datetime.utcnow(), "id": cat_id,
    })
    db.commit()
    return {"message": "Categoria actualizada"}


@router.delete("/categorias/{cat_id}", dependencies=[Depends(require_admin)])
def baja_categoria(cat_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoCategoria WHERE id = :id AND activo = 1"), {"id": cat_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    db.execute(text("UPDATE ActivoCategoria SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": cat_id})
    db.commit()
    return {"message": "Categoria eliminada"}


# ─── Fabricantes ─────────────────────────────────────────────────────────────
@router.get("/fabricantes", dependencies=[Depends(require_any_auth)])
def get_fabricantes(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"fabricantes": listar_fabricantes(db)}


@router.post("/fabricantes", dependencies=[Depends(require_admin)])
def crear_fabricante(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoFabricante (nombre, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, 1, :now, :now)
    """), {"nombre": nombre, "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/fabricantes/{fab_id}", dependencies=[Depends(require_admin)])
def actualizar_fabricante(fab_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    existing = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"), {"id": fab_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Fabricante no encontrado")
    db.execute(text("UPDATE ActivoFabricante SET nombre = :nombre, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "now": datetime.utcnow(), "id": fab_id})
    db.commit()
    return {"message": "Fabricante actualizado"}


@router.delete("/fabricantes/{fab_id}", dependencies=[Depends(require_admin)])
def baja_fabricante(fab_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"), {"id": fab_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Fabricante no encontrado")
    db.execute(text("UPDATE ActivoFabricante SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": fab_id})
    db.commit()
    return {"message": "Fabricante eliminado"}


# ─── Proveedores ─────────────────────────────────────────────────────────────
@router.get("/proveedores", dependencies=[Depends(require_any_auth)])
def get_proveedores(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"proveedores": listar_proveedores(db)}


@router.post("/proveedores", dependencies=[Depends(require_admin)])
def crear_proveedor(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoProveedor (nombre, contacto, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, :contacto, 1, :now, :now)
    """), {"nombre": nombre, "contacto": data.get("contacto"), "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/proveedores/{prov_id}", dependencies=[Depends(require_admin)])
def actualizar_proveedor(prov_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    existing = db.execute(text("SELECT id FROM ActivoProveedor WHERE id = :id AND activo = 1"), {"id": prov_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.execute(text("UPDATE ActivoProveedor SET nombre = :nombre, contacto = :contacto, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "contacto": data.get("contacto"), "now": datetime.utcnow(), "id": prov_id})
    db.commit()
    return {"message": "Proveedor actualizado"}


@router.delete("/proveedores/{prov_id}", dependencies=[Depends(require_admin)])
def baja_proveedor(prov_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoProveedor WHERE id = :id AND activo = 1"), {"id": prov_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.execute(text("UPDATE ActivoProveedor SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": prov_id})
    db.commit()
    return {"message": "Proveedor eliminado"}


# ─── Estados ─────────────────────────────────────────────────────────────────
@router.get("/estados", dependencies=[Depends(require_any_auth)])
def get_estados(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"estados": listar_estados(db)}


@router.post("/estados", dependencies=[Depends(require_admin)])
def crear_estado(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    codigo = (data.get("codigo") or "").strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El codigo es obligatorio")
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoEstado (nombre, codigo, orden, esCore, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id VALUES (:nombre, :codigo, :orden, 0, 1, :now, :now)
    """), {"nombre": nombre, "codigo": codigo, "orden": data.get("orden") or 0, "now": now})
    new_id = result.scalar()
    db.commit()
    return {"id": new_id}


@router.put("/estados/{est_id}", dependencies=[Depends(require_admin)])
def actualizar_estado(est_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _nombre_valido(data)
    codigo = (data.get("codigo") or "").strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El codigo es obligatorio")
    existing = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": est_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    db.execute(text("UPDATE ActivoEstado SET nombre = :nombre, codigo = :codigo, orden = :orden, updatedAt = :now WHERE id = :id"),
               {"nombre": nombre, "codigo": codigo, "orden": data.get("orden") or 0, "now": datetime.utcnow(), "id": est_id})
    db.commit()
    return {"message": "Estado actualizado"}


@router.delete("/estados/{est_id}", dependencies=[Depends(require_admin)])
def baja_estado(est_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    existing = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": est_id}).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    if estado_es_core(db, est_id):
        raise HTTPException(status_code=400, detail="Los estados nucleo no se pueden eliminar")
    db.execute(text("UPDATE ActivoEstado SET activo = 0, updatedAt = :now WHERE id = :id"), {"now": datetime.utcnow(), "id": est_id})
    db.commit()
    return {"message": "Estado eliminado"}
```

- [ ] **Step 2: Registrar el router en `main.py`**

En `app/main.py`, agregar `activos_config` a la línea de import de routers (hoy `from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications`) sumando `, activos_config` al final. Y agregar tras `app.include_router(publications.router)`:
```python
app.include_router(activos_config.router)
```

- [ ] **Step 3: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/routes/activos_config.py app/main.py`
Expected: sin salida (exit 0).

- [ ] **Step 4: Verificación manual (recomendada)**

Arrancar el server, y con un token ADMIN: `GET /activos/config/categorias` → 200 con los ~20 sembrados; `GET /activos/config/estados` → los 10 con `esCore=true`; `POST /activos/config/fabricantes` `{"nombre":"HP"}` → `{id}`; `DELETE` de un estado core → 400; con token no-ADMIN, `POST` → 403 y `GET` → 200.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/routes/activos_config.py app/main.py
git commit -m "feat: agregar router CRUD de configuracion del sistema de activos"
```

---

## Task 3: Frontend — tipos en `Interfaces.ts`

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts`

**Interfaces:**
- Produces: `"activos-config"` en `Page`; interfaces `ActivoCategoria`, `ActivoFabricante`, `ActivoProveedor`, `ActivoEstado`.

- [ ] **Step 1: Agregar el valor de Page y las interfaces**

En `src/app/Interfas/Interfaces.ts`:

(a) Agregar `"activos-config"` al union type `Page` (junto a los demás valores).

(b) Agregar estas interfaces:
```typescript
export interface ActivoCategoria {
  id: number;
  nombre: string;
  grupo: string;
  montableEnPC: boolean;
  requiereSerie: boolean;
  vidaUtilAnios: number | null;
}

export interface ActivoFabricante {
  id: number;
  nombre: string;
}

export interface ActivoProveedor {
  id: number;
  nombre: string;
  contacto: string | null;
}

export interface ActivoEstado {
  id: number;
  nombre: string;
  codigo: string;
  orden: number;
  esCore: boolean;
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Interfaces"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar tipos de configuracion del sistema de activos"
```

---

## Task 4: Frontend — componente CRUD genérico `ConfigCrudSection`

**Files:**
- Create: `src/app/Componentes/ActivosConfig/ConfigCrudSection.tsx`

**Interfaces:**
- Consumes: `apiClient`.
- Produces: `ConfigCrudSection` (default export) + tipos `FieldDef`, `ColumnDef`. Props: `{ endpoint, columns, fields, emptyRow, respuestaKey, canDelete?, filterField? }`.

- [ ] **Step 1: Crear el componente**

```tsx
'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { Plus, Pencil, Trash2, X } from 'lucide-react';

export type FieldType = 'text' | 'number' | 'select' | 'checkbox';

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  options?: { value: string; label: string }[];
  required?: boolean;
}

export interface ColumnDef {
  key: string;
  label: string;
  render?: (row: Record<string, unknown>) => React.ReactNode;
}

interface ConfigCrudSectionProps {
  endpoint: string;                 // ej. '/activos/config/fabricantes'
  respuestaKey: string;             // clave del array en la respuesta, ej. 'fabricantes'
  columns: ColumnDef[];
  fields: FieldDef[];
  emptyRow: Record<string, unknown>;
  canDelete?: (row: Record<string, unknown>) => boolean;
  filterField?: { key: string; label: string; options: { value: string; label: string }[] };
}

type Row = Record<string, unknown> & { id: number };

export default function ConfigCrudSection({
  endpoint, respuestaKey, columns, fields, emptyRow, canDelete, filterField,
}: ConfigCrudSectionProps) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editando, setEditando] = useState<Row | null>(null);
  const [form, setForm] = useState<Record<string, unknown>>(emptyRow);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [formError, setFormError] = useState('');
  const [filtro, setFiltro] = useState('');

  const cargar = useCallback(() => {
    setLoading(true);
    apiClient
      .get<Record<string, Row[]>>(endpoint)
      .then((res) => { setRows(res[respuestaKey] || []); setError(false); })
      .catch((e) => { console.error('Error al listar:', e); setError(true); })
      .finally(() => setLoading(false));
  }, [endpoint, respuestaKey]);

  useEffect(() => { cargar(); }, [cargar]);

  const abrirNuevo = () => { setEditando(null); setForm({ ...emptyRow }); setFormError(''); setMostrarForm(true); };
  const abrirEditar = (row: Row) => { setEditando(row); setForm({ ...row }); setFormError(''); setMostrarForm(true); };
  const cerrar = () => { setMostrarForm(false); setEditando(null); setFormError(''); };

  const guardar = async () => {
    setFormError('');
    const payload: Record<string, unknown> = {};
    for (const f of fields) {
      let v = form[f.key];
      if (f.type === 'number') v = v === '' || v == null ? null : Number(v);
      if (f.type === 'text' || f.type === 'select') v = typeof v === 'string' ? v.trim() : v;
      if (f.required && (v === '' || v == null)) { setFormError(`${f.label} es obligatorio.`); return; }
      payload[f.key] = v;
    }
    setGuardando(true);
    try {
      if (editando) await apiClient.put(`${endpoint}/${editando.id}`, payload);
      else await apiClient.post(endpoint, payload);
      cerrar();
      cargar();
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setGuardando(false);
    }
  };

  const eliminar = async (row: Row) => {
    if (!confirm(`¿Eliminar "${String(row.nombre ?? '')}"?`)) return;
    try {
      await apiClient.delete(`${endpoint}/${row.id}`);
      cargar();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const visibles = filterField && filtro
    ? rows.filter((r) => String(r[filterField.key]) === filtro)
    : rows;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {filterField ? (
          <select value={filtro} onChange={(e) => setFiltro(e.target.value)} className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm">
            <option value="">Todos: {filterField.label}</option>
            {filterField.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        ) : <div />}
        <button onClick={abrirNuevo} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-opacity duration-150 text-sm">
          <Plus size={16} /> Nuevo
        </button>
      </div>

      {mostrarForm && (
        <div className="bg-background border border-border rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-foreground">{editando ? 'Editar' : 'Nuevo'}</h4>
            <button onClick={cerrar} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
          </div>
          {formError && <p className="text-sm text-error">{formError}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fields.map((f) => (
              <div key={f.key} className={f.type === 'checkbox' ? 'flex items-center gap-2' : ''}>
                {f.type === 'checkbox' ? (
                  <label className="flex items-center gap-2 text-sm text-foreground">
                    <input type="checkbox" checked={Boolean(form[f.key])} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.checked }))} />
                    {f.label}
                  </label>
                ) : (
                  <>
                    <label className="text-xs text-muted-foreground">{f.label}</label>
                    {f.type === 'select' ? (
                      <select value={String(form[f.key] ?? '')} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm">
                        <option value="">—</option>
                        {(f.options || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    ) : (
                      <input
                        type={f.type === 'number' ? 'number' : 'text'}
                        value={String(form[f.key] ?? '')}
                        onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm"
                      />
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={cerrar} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
            <button onClick={guardar} disabled={guardando} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">
              {guardando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </div>
      )}

      <div className="bg-card border border-border rounded-xl shadow-soft overflow-x-auto">
        {loading ? (
          <p className="p-6 text-center text-muted-foreground text-sm">Cargando…</p>
        ) : error ? (
          <p className="p-6 text-center text-error text-sm">Error al cargar.</p>
        ) : visibles.length === 0 ? (
          <p className="p-6 text-center text-muted-foreground text-sm">Sin registros.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-background text-muted-foreground">
              <tr>
                {columns.map((c) => <th key={c.key} className="text-left font-medium px-4 py-3">{c.label}</th>)}
                <th className="px-4 py-3 w-24" />
              </tr>
            </thead>
            <tbody>
              {visibles.map((row) => (
                <tr key={row.id} className="border-t border-border">
                  {columns.map((c) => (
                    <td key={c.key} className="px-4 py-3 text-foreground">
                      {c.render ? c.render(row) : String(row[c.key] ?? '')}
                    </td>
                  ))}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 justify-end">
                      <button onClick={() => abrirEditar(row)} className="text-muted-foreground hover:text-foreground" title="Editar"><Pencil size={16} /></button>
                      {(!canDelete || canDelete(row)) && (
                        <button onClick={() => eliminar(row)} className="text-muted-foreground hover:text-error" title="Eliminar"><Trash2 size={16} /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "ConfigCrudSection"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/ActivosConfig/ConfigCrudSection.tsx
git commit -m "feat: agregar componente CRUD generico de configuracion"
```

---

## Task 5: Frontend — pantalla `ActivosConfig/Screen.tsx`

**Files:**
- Create: `src/app/screens/ActivosConfig/Screen.tsx`

**Interfaces:**
- Consumes: `ConfigCrudSection` + tipos `FieldDef`/`ColumnDef` (Task 4).
- Produces: componente `ActivosConfig` (default export, sin props).

- [ ] **Step 1: Crear la pantalla**

```tsx
'use client';

import React, { useState } from 'react';
import { Boxes, Factory, Truck, Activity } from 'lucide-react';
import ConfigCrudSection, { type FieldDef, type ColumnDef } from '@/app/Componentes/ActivosConfig/ConfigCrudSection';

type TabId = 'categorias' | 'fabricantes' | 'proveedores' | 'estados';

const GRUPOS = [
  { value: 'Equipo', label: 'Equipo' },
  { value: 'Componente', label: 'Componente' },
  { value: 'Accesorio', label: 'Accesorio' },
  { value: 'Mobiliario', label: 'Mobiliario' },
];

const siNo = (v: unknown) => (v ? 'Sí' : 'No');

const CAT_COLUMNS: ColumnDef[] = [
  { key: 'nombre', label: 'Nombre' },
  { key: 'grupo', label: 'Grupo' },
  { key: 'montableEnPC', label: 'Montable', render: (r) => siNo(r.montableEnPC) },
  { key: 'requiereSerie', label: 'Req. serie', render: (r) => siNo(r.requiereSerie) },
  { key: 'vidaUtilAnios', label: 'Vida útil', render: (r) => (r.vidaUtilAnios != null ? `${r.vidaUtilAnios} años` : '—') },
];
const CAT_FIELDS: FieldDef[] = [
  { key: 'nombre', label: 'Nombre', type: 'text', required: true },
  { key: 'grupo', label: 'Grupo', type: 'select', options: GRUPOS, required: true },
  { key: 'montableEnPC', label: 'Montable en PC', type: 'checkbox' },
  { key: 'requiereSerie', label: 'Requiere número de serie', type: 'checkbox' },
  { key: 'vidaUtilAnios', label: 'Vida útil (años)', type: 'number' },
];

const PROV_COLUMNS: ColumnDef[] = [
  { key: 'nombre', label: 'Nombre' },
  { key: 'contacto', label: 'Contacto', render: (r) => (r.contacto ? String(r.contacto) : '—') },
];
const ESTADO_COLUMNS: ColumnDef[] = [
  { key: 'nombre', label: 'Nombre' },
  { key: 'codigo', label: 'Código' },
  { key: 'orden', label: 'Orden' },
  { key: 'esCore', label: 'Núcleo', render: (r) => siNo(r.esCore) },
];

export default function ActivosConfig() {
  const [tab, setTab] = useState<TabId>('categorias');

  const TabButton = ({ id, label, icon: Icon }: { id: TabId; label: string; icon: React.ElementType }) => (
    <button
      onClick={() => setTab(id)}
      className={`flex items-center gap-2 whitespace-nowrap py-3 px-4 border-b-2 font-medium text-sm transition-colors ${
        tab === id ? 'border-primary text-primary bg-primary/10' : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
      }`}
    >
      <Icon size={16} /> {label}
    </button>
  );

  return (
    <div className="bg-background min-h-screen p-4 sm:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <header>
          <h1 className="font-heading text-3xl font-bold text-foreground">Configuración de Activos</h1>
          <p className="text-muted-foreground">Categorías, fabricantes, proveedores y estados del inventario.</p>
        </header>

        <div className="flex flex-wrap border-b border-border">
          <TabButton id="categorias" label="Categorías" icon={Boxes} />
          <TabButton id="fabricantes" label="Fabricantes" icon={Factory} />
          <TabButton id="proveedores" label="Proveedores" icon={Truck} />
          <TabButton id="estados" label="Estados" icon={Activity} />
        </div>

        {tab === 'categorias' && (
          <ConfigCrudSection
            endpoint="/activos/config/categorias"
            respuestaKey="categorias"
            columns={CAT_COLUMNS}
            fields={CAT_FIELDS}
            emptyRow={{ nombre: '', grupo: 'Componente', montableEnPC: false, requiereSerie: false, vidaUtilAnios: '' }}
            filterField={{ key: 'grupo', label: 'Grupo', options: GRUPOS }}
          />
        )}
        {tab === 'fabricantes' && (
          <ConfigCrudSection
            endpoint="/activos/config/fabricantes"
            respuestaKey="fabricantes"
            columns={[{ key: 'nombre', label: 'Nombre' }]}
            fields={[{ key: 'nombre', label: 'Nombre', type: 'text', required: true }]}
            emptyRow={{ nombre: '' }}
          />
        )}
        {tab === 'proveedores' && (
          <ConfigCrudSection
            endpoint="/activos/config/proveedores"
            respuestaKey="proveedores"
            columns={PROV_COLUMNS}
            fields={[
              { key: 'nombre', label: 'Nombre', type: 'text', required: true },
              { key: 'contacto', label: 'Contacto (opcional)', type: 'text' },
            ]}
            emptyRow={{ nombre: '', contacto: '' }}
          />
        )}
        {tab === 'estados' && (
          <ConfigCrudSection
            endpoint="/activos/config/estados"
            respuestaKey="estados"
            columns={ESTADO_COLUMNS}
            fields={[
              { key: 'nombre', label: 'Nombre', type: 'text', required: true },
              { key: 'codigo', label: 'Código', type: 'text', required: true },
              { key: 'orden', label: 'Orden', type: 'number' },
            ]}
            emptyRow={{ nombre: '', codigo: '', orden: 0 }}
            canDelete={(r) => !r.esCore}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "ActivosConfig/Screen"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/screens/ActivosConfig/Screen.tsx
git commit -m "feat: agregar pantalla de configuracion de activos con pestanas"
```

---

## Task 6: Frontend — ruteo y RBAC

**Files:**
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `ActivosConfig` (Task 5).
- Produces: página `"activos-config"` en la sección "Activos", solo ADMIN.

- [ ] **Step 1: `rbac.ts` — sección "Activos" + entrada**

En `src/app/util/rbac.ts`:

(a) En la interfaz `PageConfig`, el campo `section` es un union type — agregar `"Activos"`:
```typescript
  section: "General" | "Gente" | "Organización" | "Aprendizaje" | "IA" | "Sistema" | "Activos";
```

(b) Agregar `"Activos"` al array `SECTION_ORDER` (por ejemplo antes de `"Sistema"`):
```typescript
const SECTION_ORDER: PageConfig["section"][] = [
  "General", "Gente", "Organización", "Aprendizaje", "IA", "Activos", "Sistema",
];
```

(c) Agregar la entrada a `PAGE_CONFIG` (por ejemplo antes de la entrada `admin`):
```typescript
  {
    id: "activos-config",
    label: "Configuración de Activos",
    icon: "Boxes",
    section: "Activos",
    visibleFor: [ROLE_ID.ADMIN],
    accessibleFor: [ROLE_ID.ADMIN],
  },
```

- [ ] **Step 2: `AppSidebar.tsx` — ícono `Boxes`**

En `src/app/Componentes/Shell/AppSidebar.tsx`, agregar `Boxes` al import de `lucide-react` y a `ICON_MAP`:
```tsx
  Boxes,
```
(Leé el archivo real para ubicar las dos posiciones — el patrón es idéntico al usado para `Newspaper`.)

- [ ] **Step 3: `page.tsx` — case**

En `src/app/page.tsx`, agregar el import:
```tsx
import ActivosConfig from '@/app/screens/ActivosConfig/Screen';
```
Y el `case` en el switch (por ejemplo antes de `case 'admin'`):
```tsx
      case 'activos-config':
        return <ActivosConfig />;
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "rbac|AppSidebar|page\.tsx"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/util/rbac.ts src/app/Componentes/Shell/AppSidebar.tsx src/app/page.tsx
git commit -m "feat: enganchar la configuracion de activos en el ruteo"
```

---

## Task 7: Verificación manual (sin commits)

Requiere backend + DB + browser reales; no automatizable.

- [ ] Backend compila: `py -m py_compile app/routes/activos_config.py app/database/activos_config.py app/main.py`.
- [ ] Primer arranque del server: las 4 tablas se crean y se siembran — `GET /activos/config/categorias` devuelve los 20 (14 Componente, 2 Equipo, 4 Accesorio), `GET /activos/config/estados` los 10 con `esCore=true`. Reiniciar el server no duplica.
- [ ] Loguearse como ADMIN → sidebar muestra la sección "Activos" con "Configuración de Activos"; la pantalla abre con 4 pestañas.
- [ ] CRUD en cada pestaña: crear/editar/eliminar un fabricante, un proveedor (con y sin contacto), una categoría (con grupo/flags/años) y un estado custom; el listado refleja los cambios; el filtro por grupo en Categorías funciona.
- [ ] Un estado `esCore` no muestra botón de eliminar; intentar `DELETE` por API → 400.
- [ ] Categoría con nombre duplicado en el mismo grupo → 400 (mensaje en el form).
- [ ] Un no-ADMIN no ve la sección "Activos" ni puede navegar a ella; por API puede `GET` los config pero `POST/PUT/DELETE` → 403.
- [ ] Dark mode y responsive de la pantalla.

---

## Notas para el ejecutor

- **Sin pytest/jest**: la "prueba" de cada task es la compilación + verificación manual. No agregar frameworks de test.
- **Orden**: Task 1→2 (backend) independientes de 3→6 (frontend); dentro de frontend, Task 4 (componente) antes de Task 5 (pantalla que lo usa), y Task 6 (ruteo) después de Task 5.
- **`nh3` ya está instalado** en el venv del backend (de un subsistema anterior); este subsistema no agrega dependencias nuevas.
- **El archivo `UiRRHH.tsx`** puede tener un cambio local no relacionado en el working tree del repo RRHH: NO incluirlo en ningún commit de este plan.
