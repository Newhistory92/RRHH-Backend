# Modelos de PC de referencia + scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Definir modelos de PC de referencia como umbrales mínimos por categoría, y evaluar cualquier PC del inventario contra un modelo obteniendo un score = porcentaje de requisitos cumplidos.

**Architecture:** Dos tablas nuevas (`ActivoModeloPC`, `ActivoModeloRequisito`) en un módulo de datos y un router propios (`activos_modelos`), separados de `activos.py` que ya es grande. Una columna nueva `Activo.specsJson` persiste el JSON crudo de specs del catálogo `PCParts` al crear un componente — sin eso no hay datos numéricos que comparar. El motor de scoring lee esos JSON, aplica los umbrales y devuelve el detalle por requisito.

**Tech Stack:** FastAPI + SQLAlchemy `text()` (SQL Server); Next.js + React + Tailwind (tokens semánticos "Orgánico Cálido").

## Global Constraints

- SQL 100% parametrizado vía SQLAlchemy `text()` con parámetros bindeados — nunca interpolación de entrada de usuario.
- Tablas nuevas con el patrón idempotente `IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='X' AND xtype='U') BEGIN CREATE TABLE ... END` (igual que `activos_config.py`/`activos.py`).
- Columna nueva con `IF COL_LENGTH('Activo','specsJson') IS NULL ALTER TABLE Activo ADD specsJson NVARCHAR(MAX) NULL;` en su **propia** llamada `db.execute`, seguida de `db.commit()` — SQL Server compila el batch entero antes de ejecutarlo, así que un `UPDATE`/`SELECT` que referencie la columna nueva en el mismo batch falla con "Invalid column name".
- RBAC: lecturas (`GET`) con `require_any_auth`; escrituras (`POST`/`PUT`/`DELETE`) con `require_roles(ROLE_ADMIN)`.
- El router `activos_modelos` se registra en `main.py` **antes** que `activos.router`, para que `/activos/modelos/...` no sea capturado por el path converter `/{activo_id}` de aquel.
- Regla de campos tipo par en las specs de `PCParts` (verificada contra datos reales): para `modules` el valor evaluado es el **producto** de ambos elementos (`[2,16]` → 32 GB totales); para `speed` es el **segundo** elemento (`[5,6000]` → 6000 MHz); para cualquier otro par, el segundo elemento. Los escalares (`core_count`, `capacity`, `wattage`, `memory`, `max_memory`, `memory_slots`, `boost_clock`) se usan tal cual.
- `score = round(cumplidos / (total - sinDatos) * 100)`, o `null` si `total - sinDatos == 0` (nunca división por cero).
- Un componente sin `specsJson`, con JSON corrupto, sin la clave pedida, o con valor no numérico → ese requisito se reporta `sin_datos`, **nunca** `no_cumple`, y nunca lanza excepción.
- **NO tocar** `prisma/schema.prisma` ni `src/app/util/UiRRHH.tsx` en el repo RRHH (modificaciones locales del usuario, ajenas a este trabajo).
- Backend en repo `Backend_RRHH`, rama `activos-modelos-scoring`. Frontend en repo `RRHH`, misma rama. Sin suite automatizada — verificación por compilación + ejecución en vivo contra la DB real (con limpieza de datos de prueba), más `tsc --noEmit` en frontend. No levantar servidores localhost.

---

### Task 1: Backend — módulo de datos de modelos y scoring

**Files:**
- Create: `app/database/activos_modelos.py`

**Interfaces:**
- Consumes: tablas `Activo`, `ActivoCategoria` (ya existentes).
- Produces (lo que Task 2 importará):
  - `ensure_tables(db) -> None`
  - `CAMPOS_SPEC_POR_CATEGORIA: dict[str, list[dict]]`
  - `campos_disponibles(db) -> list[dict]`
  - `listar_modelos(db) -> list[dict]`
  - `obtener_modelo(db, modelo_id) -> Optional[dict]`
  - `crear_modelo(db, nombre, descripcion) -> int`
  - `actualizar_modelo(db, modelo_id, nombre, descripcion) -> None`
  - `baja_modelo(db, modelo_id) -> None`
  - `nombre_duplicado(db, nombre, excluir_id=None) -> bool`
  - `agregar_requisito(db, modelo_id, categoria_id, campo_spec, valor_minimo) -> int`
  - `requisito_duplicado(db, modelo_id, categoria_id, campo_spec) -> bool`
  - `quitar_requisito(db, modelo_id, requisito_id) -> bool`
  - `evaluar_pc(db, pc_id, modelo_id) -> dict`

- [ ] **Step 1: Crear el archivo con las constantes y el DDL**

Crear `app/database/activos_modelos.py` con este contenido inicial:

```python
"""
Modelos de PC de referencia + scoring (subsistema 6). Un modelo es un conjunto
de umbrales minimos por categoria de componente; evaluar una PC contra un modelo
devuelve el porcentaje de requisitos cumplidos y el detalle por requisito.
Lee las specs crudas guardadas en Activo.specsJson al elegir del catalogo PCParts.
"""

import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional


CREATE_MODELO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoModeloPC' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoModeloPC (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        nombre      NVARCHAR(150) NOT NULL,
        descripcion NVARCHAR(500) NULL,
        activo      BIT           NOT NULL DEFAULT 1,
        createdAt   DATETIME2     NOT NULL,
        updatedAt   DATETIME2     NOT NULL
    );
END
"""

CREATE_REQUISITO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoModeloRequisito' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoModeloRequisito (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        modeloId    INT           NOT NULL,
        categoriaId INT           NOT NULL,
        campoSpec   NVARCHAR(50)  NOT NULL,
        valorMinimo FLOAT         NOT NULL,
        createdAt   DATETIME2     NOT NULL
    );
    CREATE INDEX IX_ActivoModeloRequisito_modeloId ON ActivoModeloRequisito (modeloId);
END
"""


# Campos numericos ofrecibles como umbral, por nombre de ActivoCategoria (S1).
# Derivado de las specs reales del catalogo PCParts verificadas contra la DB.
# Las categorias sin entrada aqui no ofrecen umbrales.
CAMPOS_SPEC_POR_CATEGORIA = {
    "CPU": [
        {"campo": "core_count", "etiqueta": "Núcleos", "unidad": ""},
        {"campo": "boost_clock", "etiqueta": "Frecuencia turbo", "unidad": "GHz"},
    ],
    "Memoria RAM": [
        {"campo": "modules", "etiqueta": "Capacidad total", "unidad": "GB"},
        {"campo": "speed", "etiqueta": "Velocidad", "unidad": "MHz"},
    ],
    "Tarjetas de Video": [
        {"campo": "memory", "etiqueta": "Memoria de video", "unidad": "GB"},
    ],
    "Almacenamiento": [
        {"campo": "capacity", "etiqueta": "Capacidad", "unidad": "GB"},
    ],
    "Fuentes de Alimentación": [
        {"campo": "wattage", "etiqueta": "Potencia", "unidad": "W"},
    ],
    "Placas Base": [
        {"campo": "max_memory", "etiqueta": "Memoria máxima", "unidad": "GB"},
        {"campo": "memory_slots", "etiqueta": "Slots de memoria", "unidad": ""},
    ],
}


def ensure_tables(db: Session) -> None:
    """Crea las tablas de modelos/requisitos y asegura Activo.specsJson.
    El ALTER va en su propio batch + commit: SQL Server compila el batch entero
    antes de ejecutarlo y fallaria si un statement posterior referenciara la
    columna recien creada dentro del mismo batch."""
    db.execute(text(CREATE_MODELO_SQL))
    db.execute(text(CREATE_REQUISITO_SQL))
    db.commit()
    db.execute(text("IF COL_LENGTH('Activo','specsJson') IS NULL ALTER TABLE Activo ADD specsJson NVARCHAR(MAX) NULL;"))
    db.commit()
```

- [ ] **Step 2: Agregar el helper de extracción de valores desde el JSON de specs**

Agregar al final del archivo:

```python
def _valor_de_spec(specs_json: Optional[str], campo: str) -> Optional[float]:
    """Extrae el valor numerico de un campo del JSON de specs de PCParts.
    Devuelve None (= 'sin datos') si el JSON falta, esta corrupto, no tiene la
    clave, o el valor no es numerico -- nunca lanza excepcion.

    Campos tipo par (verificado contra datos reales del catalogo):
      - 'modules': [cantidad, capacidad] -> producto (ej. [2,16] = 32 GB totales)
      - cualquier otro par (ej. 'speed': [5,6000]) -> segundo elemento
    """
    if not specs_json:
        return None
    try:
        obj = json.loads(specs_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or campo not in obj:
        return None
    v = obj[campo]
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and len(v) == 2:
        a, b = v[0], v[1]
        if isinstance(a, bool) or isinstance(b, bool):
            return None
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        return float(a) * float(b) if campo == "modules" else float(b)
    return None
```

- [ ] **Step 3: Agregar las consultas de campos disponibles y CRUD de modelos**

Agregar al final del archivo:

```python
def campos_disponibles(db: Session) -> list[dict]:
    """CAMPOS_SPEC_POR_CATEGORIA resuelto con los ids reales de ActivoCategoria,
    para poblar los selects encadenados del frontend. Solo categorias vigentes
    y montables en PC."""
    rows = db.execute(text(
        "SELECT id, nombre FROM ActivoCategoria WHERE activo = 1 AND montableEnPC = 1 ORDER BY nombre"
    )).mappings().all()
    salida = []
    for r in rows:
        campos = CAMPOS_SPEC_POR_CATEGORIA.get(r["nombre"])
        if campos:
            salida.append({"categoriaId": r["id"], "categoriaNombre": r["nombre"], "campos": campos})
    return salida


def nombre_duplicado(db: Session, nombre: str, excluir_id: Optional[int] = None) -> bool:
    q = "SELECT id FROM ActivoModeloPC WHERE activo = 1 AND LOWER(nombre) = LOWER(:n)"
    params = {"n": nombre}
    if excluir_id:
        q += " AND id <> :id"
        params["id"] = excluir_id
    return db.execute(text(q), params).first() is not None


def listar_modelos(db: Session) -> list[dict]:
    """Modelos vigentes con la cantidad de requisitos de cada uno."""
    rows = db.execute(text("""
        SELECT m.id, m.nombre, m.descripcion,
               (SELECT COUNT(*) FROM ActivoModeloRequisito r WHERE r.modeloId = m.id) AS cantidadRequisitos
        FROM ActivoModeloPC m
        WHERE m.activo = 1
        ORDER BY m.nombre
    """)).mappings().all()
    return [{"id": r["id"], "nombre": r["nombre"], "descripcion": r["descripcion"],
             "cantidadRequisitos": r["cantidadRequisitos"]} for r in rows]


def _requisitos_de(db: Session, modelo_id: int) -> list[dict]:
    rows = db.execute(text("""
        SELECT r.id, r.categoriaId, c.nombre AS categoriaNombre, r.campoSpec, r.valorMinimo
        FROM ActivoModeloRequisito r
        INNER JOIN ActivoCategoria c ON r.categoriaId = c.id
        WHERE r.modeloId = :id
        ORDER BY c.nombre, r.campoSpec
    """), {"id": modelo_id}).mappings().all()
    salida = []
    for r in rows:
        meta = next((x for x in CAMPOS_SPEC_POR_CATEGORIA.get(r["categoriaNombre"], [])
                     if x["campo"] == r["campoSpec"]), None)
        salida.append({
            "id": r["id"], "categoriaId": r["categoriaId"], "categoriaNombre": r["categoriaNombre"],
            "campoSpec": r["campoSpec"],
            "etiqueta": meta["etiqueta"] if meta else r["campoSpec"],
            "unidad": meta["unidad"] if meta else "",
            "valorMinimo": float(r["valorMinimo"]),
        })
    return salida


def obtener_modelo(db: Session, modelo_id: int) -> Optional[dict]:
    r = db.execute(text(
        "SELECT id, nombre, descripcion FROM ActivoModeloPC WHERE id = :id AND activo = 1"
    ), {"id": modelo_id}).mappings().first()
    if not r:
        return None
    return {"id": r["id"], "nombre": r["nombre"], "descripcion": r["descripcion"],
            "requisitos": _requisitos_de(db, modelo_id)}


def crear_modelo(db: Session, nombre: str, descripcion: Optional[str]) -> int:
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO ActivoModeloPC (nombre, descripcion, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:nombre, :desc, 1, :now, :now)
    """), {"nombre": nombre, "desc": descripcion, "now": now})
    return result.scalar()


def actualizar_modelo(db: Session, modelo_id: int, nombre: str, descripcion: Optional[str]) -> None:
    db.execute(text("""
        UPDATE ActivoModeloPC SET nombre = :nombre, descripcion = :desc, updatedAt = :now
        WHERE id = :id
    """), {"nombre": nombre, "desc": descripcion, "now": datetime.utcnow(), "id": modelo_id})


def baja_modelo(db: Session, modelo_id: int) -> None:
    db.execute(text("UPDATE ActivoModeloPC SET activo = 0, updatedAt = :now WHERE id = :id"),
               {"now": datetime.utcnow(), "id": modelo_id})
```

- [ ] **Step 4: Agregar el CRUD de requisitos**

Agregar al final del archivo:

```python
def requisito_duplicado(db: Session, modelo_id: int, categoria_id: int, campo_spec: str) -> bool:
    return db.execute(text("""
        SELECT id FROM ActivoModeloRequisito
        WHERE modeloId = :m AND categoriaId = :c AND campoSpec = :campo
    """), {"m": modelo_id, "c": categoria_id, "campo": campo_spec}).first() is not None


def agregar_requisito(db: Session, modelo_id: int, categoria_id: int,
                      campo_spec: str, valor_minimo: float) -> int:
    result = db.execute(text("""
        INSERT INTO ActivoModeloRequisito (modeloId, categoriaId, campoSpec, valorMinimo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:m, :c, :campo, :valor, :now)
    """), {"m": modelo_id, "c": categoria_id, "campo": campo_spec,
           "valor": valor_minimo, "now": datetime.utcnow()})
    return result.scalar()


def quitar_requisito(db: Session, modelo_id: int, requisito_id: int) -> bool:
    """Borra el requisito si pertenece a ese modelo. False si no existe/no coincide."""
    r = db.execute(text("SELECT id FROM ActivoModeloRequisito WHERE id = :id AND modeloId = :m"),
                   {"id": requisito_id, "m": modelo_id}).first()
    if not r:
        return False
    db.execute(text("DELETE FROM ActivoModeloRequisito WHERE id = :id"), {"id": requisito_id})
    return True
```

- [ ] **Step 5: Agregar el motor de scoring `evaluar_pc`**

Agregar al final del archivo:

```python
def evaluar_pc(db: Session, pc_id: int, modelo_id: int) -> dict:
    """Evalua los componentes instalados en pc_id contra los requisitos del modelo.
    Por cada requisito toma el MEJOR valor entre los componentes de esa categoria
    (ej. si hay 2 discos, el de mayor capacidad). Requisitos sin datos evaluables
    se excluyen del denominador del score en vez de contar como incumplidos."""
    requisitos = _requisitos_de(db, modelo_id)
    detalle = []
    cumplidos = 0
    sin_datos = 0
    for req in requisitos:
        comps = db.execute(text("""
            SELECT specsJson FROM Activo
            WHERE activo = 1 AND pcPadreId = :pc AND categoriaId = :cat
        """), {"pc": pc_id, "cat": req["categoriaId"]}).mappings().all()
        valores = [v for v in (_valor_de_spec(c["specsJson"], req["campoSpec"]) for c in comps)
                   if v is not None]
        if not valores:
            estado = "sin_datos"
            valor_real = None
            sin_datos += 1
        else:
            valor_real = max(valores)
            if valor_real >= req["valorMinimo"]:
                estado = "cumple"
                cumplidos += 1
            else:
                estado = "no_cumple"
        detalle.append({**req, "valorReal": valor_real, "estado": estado})

    total = len(requisitos)
    evaluables = total - sin_datos
    score = round(cumplidos / evaluables * 100) if evaluables > 0 else None
    return {"score": score, "total": total, "cumplidos": cumplidos,
            "sinDatos": sin_datos, "requisitos": detalle}
```

- [ ] **Step 6: Compilar**

Run: `py -m py_compile app/database/activos_modelos.py`
Expected: sin salida (exit 0).

- [ ] **Step 7: Verificar en vivo contra la DB real**

Con el patrón de sesión ya usado en este proyecto (`SessionLocal` de `app.database.database`):
- `ensure_tables(db)` corre sin error; correrlo **dos veces** confirma idempotencia. Verificar con
  `SELECT COL_LENGTH('Activo','specsJson')` que la columna quedó creada (no NULL).
- `campos_disponibles(db)` devuelve entradas con `categoriaId` real para CPU/Memoria RAM/Almacenamiento
  (las categorías montables sembradas en S1).
- Probar `_valor_de_spec` con estos casos exactos y confirmar los resultados:
  - `_valor_de_spec('{"core_count":8}', 'core_count')` → `8.0`
  - `_valor_de_spec('{"modules":[2,16]}', 'modules')` → `32.0` (producto)
  - `_valor_de_spec('{"speed":[5,6000]}', 'speed')` → `6000.0` (segundo elemento)
  - `_valor_de_spec('{"capacity":1000}', 'capacity')` → `1000.0`
  - `_valor_de_spec(None, 'core_count')` → `None`
  - `_valor_de_spec('no es json', 'core_count')` → `None`
  - `_valor_de_spec('{"otro":1}', 'core_count')` → `None`
  - `_valor_de_spec('{"cache":null}', 'cache')` → `None`
  - `_valor_de_spec('{"type":"SSD"}', 'type')` → `None`
- Crear un modelo de prueba + un requisito, listarlo, y borrarlo al final (dejar la DB sin basura de
  prueba: baja lógica del modelo y `DELETE` del requisito).

- [ ] **Step 8: Commit**

```bash
git add app/database/activos_modelos.py
git commit -m "feat: agregar modelo de datos de modelos de PC y motor de scoring (subsistema 6)"
```

---

### Task 2: Backend — router de modelos y evaluación

**Files:**
- Create: `app/routes/activos_modelos.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes (de Task 1): todas las funciones de `app.database.activos_modelos`.
- Produces (endpoints que consume el frontend, Tasks 5-6):
  - `GET /activos/modelos` → `{modelos: [...]}`
  - `GET /activos/modelos/campos` → `{categorias: [...]}`
  - `GET /activos/modelos/{id}` → modelo + `requisitos`
  - `POST /activos/modelos` body `{nombre, descripcion}` → `{id}`
  - `PUT /activos/modelos/{id}` body `{nombre, descripcion}` → `{message}`
  - `DELETE /activos/modelos/{id}` → `{message}`
  - `POST /activos/modelos/{id}/requisitos` body `{categoriaId, campoSpec, valorMinimo}` → `{id}`
  - `DELETE /activos/modelos/{id}/requisitos/{reqId}` → `{message}`
  - `GET /activos/modelos/evaluar/{pcId}?modeloId=` → `{score, total, cumplidos, sinDatos, requisitos}`

- [ ] **Step 1: Crear el router con los endpoints de lectura**

Crear `app/routes/activos_modelos.py`:

```python
"""
Router /activos/modelos -- modelos de PC de referencia y scoring (subsistema 6).
Lecturas: cualquier autenticado. Escrituras: solo ADMIN.
Se registra ANTES que activos.router en main.py para que /activos/modelos/... no
sea capturado por el path converter /{activo_id} de aquel.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN
from app.database.activos_modelos import (
    ensure_tables, CAMPOS_SPEC_POR_CATEGORIA, campos_disponibles,
    listar_modelos, obtener_modelo, crear_modelo, actualizar_modelo, baja_modelo,
    nombre_duplicado, agregar_requisito, requisito_duplicado, quitar_requisito,
    evaluar_pc,
)

router = APIRouter(prefix="/activos/modelos", tags=["Activos - Modelos"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_nombre(data: dict) -> str:
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    return nombre


@router.get("", dependencies=[Depends(require_any_auth)])
def get_modelos(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"modelos": listar_modelos(db)}


@router.get("/campos", dependencies=[Depends(require_any_auth)])
def get_campos(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"categorias": campos_disponibles(db)}


@router.get("/evaluar/{pc_id}", dependencies=[Depends(require_any_auth)])
def get_evaluacion(pc_id: int, modeloId: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    pc = db.execute(text("""
        SELECT a.id, c.puedeAlbergarComponentes
        FROM Activo a
        INNER JOIN ActivoCategoria c ON a.categoriaId = c.id
        WHERE a.id = :id AND a.activo = 1
    """), {"id": pc_id}).mappings().first()
    if not pc:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    if not pc["puedeAlbergarComponentes"]:
        raise HTTPException(status_code=400, detail="Este activo no es una PC")
    if not obtener_modelo(db, modeloId):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return evaluar_pc(db, pc_id, modeloId)


@router.get("/{modelo_id}", dependencies=[Depends(require_any_auth)])
def get_modelo(modelo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    modelo = obtener_modelo(db, modelo_id)
    if not modelo:
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    return modelo
```

**Nota de orden de rutas:** `/campos` y `/evaluar/{pc_id}` se declaran **antes** de `/{modelo_id}`,
porque este último es un path converter de un solo segmento que capturaría la palabra literal "campos".

- [ ] **Step 2: Agregar los endpoints de escritura de modelos**

Agregar al final del archivo:

```python
@router.post("", dependencies=[Depends(require_admin)])
def post_modelo(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    nombre = _validar_nombre(data)
    if nombre_duplicado(db, nombre):
        raise HTTPException(status_code=400, detail="Ya existe un modelo con ese nombre")
    new_id = crear_modelo(db, nombre, data.get("descripcion") or None)
    db.commit()
    return {"id": new_id}


@router.put("/{modelo_id}", dependencies=[Depends(require_admin)])
def put_modelo(modelo_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    nombre = _validar_nombre(data)
    if nombre_duplicado(db, nombre, excluir_id=modelo_id):
        raise HTTPException(status_code=400, detail="Ya existe un modelo con ese nombre")
    actualizar_modelo(db, modelo_id, nombre, data.get("descripcion") or None)
    db.commit()
    return {"message": "Modelo actualizado"}


@router.delete("/{modelo_id}", dependencies=[Depends(require_admin)])
def delete_modelo(modelo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    baja_modelo(db, modelo_id)
    db.commit()
    return {"message": "Modelo dado de baja"}
```

- [ ] **Step 3: Agregar los endpoints de requisitos**

Agregar al final del archivo:

```python
@router.post("/{modelo_id}/requisitos", dependencies=[Depends(require_admin)])
def post_requisito(modelo_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    if not obtener_modelo(db, modelo_id):
        raise HTTPException(status_code=404, detail="Modelo no encontrado")

    categoria_id = data.get("categoriaId")
    cat = db.execute(text(
        "SELECT id, nombre, montableEnPC FROM ActivoCategoria WHERE id = :id AND activo = 1"
    ), {"id": categoria_id}).mappings().first() if categoria_id else None
    if not cat:
        raise HTTPException(status_code=400, detail="categoriaId inexistente")
    if not cat["montableEnPC"]:
        raise HTTPException(status_code=400, detail="La categoria debe ser montable en una PC")

    campo = (data.get("campoSpec") or "").strip()
    validos = [c["campo"] for c in CAMPOS_SPEC_POR_CATEGORIA.get(cat["nombre"], [])]
    if campo not in validos:
        raise HTTPException(status_code=400,
                            detail=f"campoSpec invalido para {cat['nombre']}. Validos: {validos}")

    try:
        valor = float(data.get("valorMinimo"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="valorMinimo debe ser numerico")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="valorMinimo debe ser mayor a 0")

    if requisito_duplicado(db, modelo_id, cat["id"], campo):
        raise HTTPException(status_code=400, detail="Ya existe un requisito para esa categoria y campo")

    new_id = agregar_requisito(db, modelo_id, cat["id"], campo, valor)
    db.commit()
    return {"id": new_id}


@router.delete("/{modelo_id}/requisitos/{requisito_id}", dependencies=[Depends(require_admin)])
def delete_requisito(modelo_id: int, requisito_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not quitar_requisito(db, modelo_id, requisito_id):
        raise HTTPException(status_code=404, detail="Requisito no encontrado en ese modelo")
    db.commit()
    return {"message": "Requisito eliminado"}
```

- [ ] **Step 4: Registrar el router en `main.py`**

En `app/main.py`, agregar `activos_modelos` a la lista de imports de routers. Reemplazar:

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos
```

por:

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos
```

Y registrar el router **antes** de `activos.router`. Reemplazar:

```python
app.include_router(activos_config.router)
app.include_router(activos.router)
```

por:

```python
app.include_router(activos_config.router)
app.include_router(activos_modelos.router)
app.include_router(activos.router)
```

No tocar ningún otro router ni línea de `main.py`.

- [ ] **Step 5: Compilar**

Run: `py -m py_compile app/routes/activos_modelos.py app/main.py`
Expected: sin salida (exit 0).

- [ ] **Step 6: Verificar en vivo contra la DB real**

Con `TestClient` (patrón ya usado en tasks anteriores de este proyecto) y datos de prueba temporales
que se limpian al final:
- `GET /activos/modelos/campos` devuelve `{categorias:[...]}` con `categoriaId` reales.
- `POST /activos/modelos` con `{nombre:"TEST-S6 Modelo"}` → `{id}`; repetir el mismo nombre → 400.
- `POST /activos/modelos` con nombre vacío → 400.
- `POST /activos/modelos/{id}/requisitos` con una categoría montable y un `campoSpec` válido → `{id}`;
  repetir el mismo par categoría+campo → 400.
- `POST .../requisitos` con `campoSpec:"inventado"` → 400; con `valorMinimo:0` o `-5` → 400; con
  `valorMinimo:"abc"` → 400; con una `categoriaId` no montable (ej. la categoría "PC" que tiene
  `montableEnPC=0`) → 400.
- `GET /activos/modelos/{id}` devuelve el modelo con sus requisitos (con `etiqueta` y `unidad`
  resueltas); `GET /activos/modelos/999999` → 404.
- `GET /activos/modelos/evaluar/{pcId}?modeloId={id}` sobre una PC real → responde con las claves
  `score`/`total`/`cumplidos`/`sinDatos`/`requisitos`. Con un modelo sin requisitos → `score: null`,
  sin excepción. Sobre un activo que NO es PC → 400. Sobre un id inexistente → 404.
- Confirmar que `GET /activos` y `GET /activos/{id}` (rutas del router de S2) **siguen funcionando** —
  esto valida que registrar `/activos/modelos` antes no rompió el ruteo existente.
- RBAC: sin token, los `POST`/`PUT`/`DELETE` devuelven 401.
- Limpiar: `DELETE` de los requisitos de prueba y baja lógica del modelo de prueba.

- [ ] **Step 7: Commit**

```bash
git add app/routes/activos_modelos.py app/main.py
git commit -m "feat: agregar router de modelos de PC y evaluacion (subsistema 6)"
```

---

### Task 3: Backend — persistir `specsJson` al crear/editar activos

**Files:**
- Modify: `app/routes/activos.py`

**Interfaces:**
- Consumes: la columna `Activo.specsJson` creada por `ensure_tables` de Task 1.
- Produces: `POST /activos` y `PUT /activos/{id}` aceptan un campo opcional `specsJson` en el body
  (string con el JSON crudo del `PCPart`, o `null`), consumido por el frontend en Task 6.

- [ ] **Step 1: Asegurar la columna al arrancar los endpoints de activos**

En `app/routes/activos.py`, ampliar el import del módulo de datos de S6 para poder llamar a su
`ensure_tables`. Reemplazar el bloque de imports de `app.database.activos`:

```python
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
    MAPEO_PCPARTS, listar_componentes_de, componentes_libres, buscar_pcparts,
    historial_de_activo,
)
```

por:

```python
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
    MAPEO_PCPARTS, listar_componentes_de, componentes_libres, buscar_pcparts,
    historial_de_activo,
)
from app.database.activos_modelos import ensure_tables as ensure_tables_modelos
```

- [ ] **Step 2: Persistir `specsJson` en `crear_activo`**

En la función `crear_activo`, reemplazar la línea `ensure_tables(db)` (la primera del cuerpo) por:

```python
    ensure_tables(db)
    ensure_tables_modelos(db)
```

Luego, en el mismo `crear_activo`, reemplazar el `INSERT` completo:

```python
    result = db.execute(text("""
        INSERT INTO Activo (numeroInventario, nombre, categoriaId, fabricanteId, estadoId, fechaAlta, anio,
            observaciones, imagenReferencial, numeroSerie, codigoBarras, codigoQR,
            responsableTipo, responsableEmpleadoId, responsableOficinaId, responsableDepartamentoId,
            activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:numero, :nombre, :catId, :fabId, :estId, :fechaAlta, :anio,
            :obs, :img, :serie, :barras, :qr,
            :rtipo, :remp, :rofi, :rdep, 1, :now, :now)
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "now": now,
    })
```

por (agrega la columna `specsJson` y su parámetro bindeado):

```python
    result = db.execute(text("""
        INSERT INTO Activo (numeroInventario, nombre, categoriaId, fabricanteId, estadoId, fechaAlta, anio,
            observaciones, imagenReferencial, numeroSerie, codigoBarras, codigoQR,
            responsableTipo, responsableEmpleadoId, responsableOficinaId, responsableDepartamentoId,
            specsJson, activo, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES (:numero, :nombre, :catId, :fabId, :estId, :fechaAlta, :anio,
            :obs, :img, :serie, :barras, :qr,
            :rtipo, :remp, :rofi, :rdep, :specs, 1, :now, :now)
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "specs": (data.get("specsJson") or None),
        "now": now,
    })
```

- [ ] **Step 3: Persistir `specsJson` en `actualizar_activo`**

En la función `actualizar_activo`, reemplazar la línea `ensure_tables(db)` (la primera del cuerpo) por:

```python
    ensure_tables(db)
    ensure_tables_modelos(db)
```

Luego, en el mismo `actualizar_activo`, reemplazar el `UPDATE` completo:

```python
    db.execute(text("""
        UPDATE Activo SET numeroInventario = :numero, nombre = :nombre, categoriaId = :catId,
            fabricanteId = :fabId, estadoId = :estId, fechaAlta = :fechaAlta, anio = :anio,
            observaciones = :obs, imagenReferencial = :img, numeroSerie = :serie,
            codigoBarras = :barras, codigoQR = :qr, responsableTipo = :rtipo,
            responsableEmpleadoId = :remp, responsableOficinaId = :rofi, responsableDepartamentoId = :rdep,
            updatedAt = :now
        WHERE id = :id
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "now": now, "id": activo_id,
    })
```

por:

```python
    db.execute(text("""
        UPDATE Activo SET numeroInventario = :numero, nombre = :nombre, categoriaId = :catId,
            fabricanteId = :fabId, estadoId = :estId, fechaAlta = :fechaAlta, anio = :anio,
            observaciones = :obs, imagenReferencial = :img, numeroSerie = :serie,
            codigoBarras = :barras, codigoQR = :qr, responsableTipo = :rtipo,
            responsableEmpleadoId = :remp, responsableOficinaId = :rofi, responsableDepartamentoId = :rdep,
            specsJson = :specs, updatedAt = :now
        WHERE id = :id
    """), {
        "numero": numero, "nombre": (data.get("nombre") or "").strip(), "catId": cat_id,
        "fabId": data.get("fabricanteId"), "estId": estado_id, "fechaAlta": _parse_date(data.get("fechaAlta")),
        "anio": data.get("anio"), "obs": data.get("observaciones"), "img": data.get("imagenReferencial"),
        "serie": (data.get("numeroSerie") or None), "barras": data.get("codigoBarras"), "qr": data.get("codigoQR"),
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"], "rdep": resp["departamento"],
        "specs": (data.get("specsJson") or None),
        "now": now, "id": activo_id,
    })
```

Nota: el `PUT` es de reemplazo total (semántica ya existente de este endpoint), así que omitir
`specsJson` en el body lo deja en `NULL` — consistente con cómo ya se comportan los demás campos
opcionales de este endpoint. El frontend (Task 6) siempre lo envía.

- [ ] **Step 4: Compilar**

Run: `py -m py_compile app/routes/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 5: Verificar en vivo contra la DB real**

Con datos de prueba temporales que se limpian al final:
- `POST /activos` con `specsJson: '{"core_count":8}'` → el activo creado tiene ese valor en la columna
  (`SELECT specsJson FROM Activo WHERE id = ...`).
- `POST /activos` **sin** `specsJson` → la columna queda `NULL`, sin error (retrocompatibilidad).
- `PUT /activos/{id}` con `specsJson` → actualiza el valor.
- Confirmar que el resto del comportamiento de ambos endpoints no cambió (crear/editar siguen validando
  igual y sigue escribiéndose el historial como antes).
- Limpiar: baja lógica de los activos de prueba.

- [ ] **Step 6: Commit**

```bash
git add app/routes/activos.py
git commit -m "feat: persistir specsJson del catalogo al crear y editar activos (subsistema 6)"
```

---

### Task 4: Frontend — tipos de modelos y evaluación

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts` (repo RRHH)

**Interfaces:**
- Consumes: las formas devueltas por los endpoints de Task 2.
- Produces (consumidos por Tasks 5-7): `ModeloPC`, `ModeloRequisito`, `ModeloDetalle`,
  `CampoSpecCategoria`, `EvaluacionResultado`, y `"activos-modelos"` en el union `Page`.

- [ ] **Step 1: Agregar `"activos-modelos"` al union `Page`**

En `src/app/Interfas/Interfaces.ts`, reemplazar:

```ts
  | "activos-config"
  | "activos-inventario";
```

por:

```ts
  | "activos-config"
  | "activos-inventario"
  | "activos-modelos";
```

- [ ] **Step 2: Agregar las interfaces nuevas**

Después de la interfaz `HistorialItem` (o junto a los demás tipos de Activos), agregar:

```ts
export interface ModeloPC {
  id: number;
  nombre: string;
  descripcion: string | null;
  cantidadRequisitos: number;
}

export interface ModeloRequisito {
  id: number;
  categoriaId: number;
  categoriaNombre: string;
  campoSpec: string;
  etiqueta: string;
  unidad: string;
  valorMinimo: number;
}

export interface ModeloDetalle {
  id: number;
  nombre: string;
  descripcion: string | null;
  requisitos: ModeloRequisito[];
}

export interface CampoSpecCategoria {
  categoriaId: number;
  categoriaNombre: string;
  campos: { campo: string; etiqueta: string; unidad: string }[];
}

export interface EvaluacionRequisito extends ModeloRequisito {
  valorReal: number | null;
  estado: 'cumple' | 'no_cumple' | 'sin_datos';
}

export interface EvaluacionResultado {
  score: number | null;
  total: number;
  cumplidos: number;
  sinDatos: number;
  requisitos: EvaluacionRequisito[];
}
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Interfaces.ts`.

- [ ] **Step 4: Confirmar archivos protegidos intactos y commit**

`prisma/schema.prisma` y `src/app/util/UiRRHH.tsx` no deben aparecer agregados por vos.

```bash
git add src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar tipos de modelos de PC y evaluacion (subsistema 6)"
```

---

### Task 5: Frontend — pantalla "Modelos de PC" + ruteo

**Files:**
- Create: `src/app/screens/ActivosModelos/Screen.tsx`
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes (de Task 4): `ModeloPC`, `ModeloDetalle`, `ModeloRequisito`, `CampoSpecCategoria`,
  `"activos-modelos"` en `Page`. Endpoints de Task 2.
- Produces: la pantalla ruteada `activos-modelos`.

- [ ] **Step 1: Crear la pantalla**

Crear `src/app/screens/ActivosModelos/Screen.tsx`:

```tsx
'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import type { ModeloPC, ModeloDetalle, CampoSpecCategoria } from '@/app/Interfas/Interfaces';
import { Plus, ArrowLeft, Trash2, Cpu } from 'lucide-react';

type Modo = 'lista' | 'detalle';

export default function ActivosModelos() {
  const [modo, setModo] = useState<Modo>('lista');
  const [modelos, setModelos] = useState<ModeloPC[]>([]);
  const [detalle, setDetalle] = useState<ModeloDetalle | null>(null);
  const [categorias, setCategorias] = useState<CampoSpecCategoria[]>([]);
  const [error, setError] = useState('');

  const [creando, setCreando] = useState(false);
  const [nuevoNombre, setNuevoNombre] = useState('');
  const [nuevaDescripcion, setNuevaDescripcion] = useState('');
  const [guardando, setGuardando] = useState(false);

  const [reqCategoriaId, setReqCategoriaId] = useState('');
  const [reqCampo, setReqCampo] = useState('');
  const [reqValor, setReqValor] = useState('');
  const [errorReq, setErrorReq] = useState('');

  const inputCls = 'px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm';

  const cargar = useCallback(() => {
    apiClient.get<{ modelos: ModeloPC[] }>('/activos/modelos')
      .then((r) => setModelos(r.modelos || []))
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    cargar();
    apiClient.get<{ categorias: CampoSpecCategoria[] }>('/activos/modelos/campos')
      .then((r) => setCategorias(r.categorias || []))
      .catch(() => {});
  }, [cargar]);

  const abrirDetalle = async (id: number) => {
    try {
      const d = await apiClient.get<ModeloDetalle>(`/activos/modelos/${id}`);
      setDetalle(d);
      setReqCategoriaId(''); setReqCampo(''); setReqValor(''); setErrorReq('');
      setModo('detalle');
    } catch (e) { setError((e as Error).message); }
  };

  const crearModelo = async () => {
    setError('');
    if (!nuevoNombre.trim()) { setError('El nombre es obligatorio.'); return; }
    setGuardando(true);
    try {
      const res = await apiClient.post<{ id: number }>('/activos/modelos', {
        nombre: nuevoNombre.trim(),
        descripcion: nuevaDescripcion.trim() || null,
      });
      setCreando(false); setNuevoNombre(''); setNuevaDescripcion('');
      cargar();
      abrirDetalle(res.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGuardando(false);
    }
  };

  const bajaModelo = async (id: number) => {
    if (!confirm('¿Dar de baja este modelo?')) return;
    try {
      await apiClient.delete(`/activos/modelos/${id}`);
      cargar();
    } catch (e) { setError((e as Error).message); }
  };

  const categoriaSel = categorias.find((c) => String(c.categoriaId) === reqCategoriaId);
  const campoSel = categoriaSel?.campos.find((c) => c.campo === reqCampo);

  const agregarRequisito = async () => {
    if (!detalle) return;
    setErrorReq('');
    if (!reqCategoriaId) { setErrorReq('Elegí una categoría.'); return; }
    if (!reqCampo) { setErrorReq('Elegí un campo.'); return; }
    const valor = Number(reqValor);
    if (!reqValor.trim() || Number.isNaN(valor) || valor <= 0) {
      setErrorReq('El valor mínimo debe ser un número mayor a 0.');
      return;
    }
    try {
      await apiClient.post(`/activos/modelos/${detalle.id}/requisitos`, {
        categoriaId: Number(reqCategoriaId),
        campoSpec: reqCampo,
        valorMinimo: valor,
      });
      setReqCampo(''); setReqValor('');
      abrirDetalle(detalle.id);
      cargar();
    } catch (e) { setErrorReq((e as Error).message); }
  };

  const quitarRequisito = async (reqId: number) => {
    if (!detalle) return;
    try {
      await apiClient.delete(`/activos/modelos/${detalle.id}/requisitos/${reqId}`);
      abrirDetalle(detalle.id);
      cargar();
    } catch (e) { setErrorReq((e as Error).message); }
  };

  if (modo === 'detalle' && detalle) {
    return (
      <div className="bg-background min-h-screen p-4 sm:p-8">
        <div className="max-w-4xl mx-auto space-y-6">
          <button onClick={() => { setModo('lista'); setDetalle(null); }} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft size={16} /> Volver a modelos</button>

          <div>
            <h1 className="font-heading text-2xl font-bold text-foreground">{detalle.nombre}</h1>
            {detalle.descripcion && <p className="text-muted-foreground">{detalle.descripcion}</p>}
          </div>

          <div className="bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6 space-y-4">
            <h2 className="font-heading text-lg font-bold text-foreground">Requisitos</h2>
            {errorReq && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{errorReq}</div>}

            {detalle.requisitos.length === 0 ? (
              <p className="text-sm text-muted-foreground">Este modelo todavía no tiene requisitos. Agregá al menos uno para poder evaluar PCs.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="text-left font-medium py-2">Categoría</th>
                    <th className="text-left font-medium py-2">Campo</th>
                    <th className="text-left font-medium py-2">Mínimo</th>
                    <th className="py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {detalle.requisitos.map((r) => (
                    <tr key={r.id} className="border-t border-border">
                      <td className="py-2 text-foreground">{r.categoriaNombre}</td>
                      <td className="py-2 text-muted-foreground">{r.etiqueta}</td>
                      <td className="py-2 text-muted-foreground">{r.valorMinimo} {r.unidad}</td>
                      <td className="py-2 text-right">
                        <button onClick={() => quitarRequisito(r.id)} className="inline-flex items-center gap-1 text-error hover:opacity-80 text-xs"><Trash2 size={14} /> Quitar</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="border-t border-border pt-4">
              <p className="text-sm font-semibold text-foreground mb-2">Agregar requisito</p>
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
                <div>
                  <label className="text-xs text-muted-foreground">Categoría</label>
                  <select value={reqCategoriaId} onChange={(e) => { setReqCategoriaId(e.target.value); setReqCampo(''); }} className={`w-full mt-1 ${inputCls}`}>
                    <option value="">—</option>
                    {categorias.map((c) => <option key={c.categoriaId} value={c.categoriaId}>{c.categoriaNombre}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Campo</label>
                  <select value={reqCampo} onChange={(e) => setReqCampo(e.target.value)} disabled={!reqCategoriaId} className={`w-full mt-1 ${inputCls} disabled:opacity-50`}>
                    <option value="">—</option>
                    {(categoriaSel?.campos ?? []).map((c) => <option key={c.campo} value={c.campo}>{c.etiqueta}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Valor mínimo {campoSel?.unidad ? `(${campoSel.unidad})` : ''}</label>
                  <input type="number" value={reqValor} onChange={(e) => setReqValor(e.target.value)} className={`w-full mt-1 ${inputCls}`} />
                </div>
                <button onClick={agregarRequisito} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90">Agregar</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen p-4 sm:p-8">
      <div className="max-w-5xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground">Modelos de PC</h1>
            <p className="text-muted-foreground">Perfiles de referencia para evaluar equipos.</p>
          </div>
          <button onClick={() => { setCreando(true); setError(''); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90"><Plus size={18} /> Nuevo modelo</button>
        </header>

        {error && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{error}</div>}

        <div className="bg-card border border-border rounded-xl shadow-soft overflow-x-auto">
          {modelos.length === 0 ? (
            <p className="p-8 text-center text-muted-foreground">No hay modelos definidos todavía.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-background text-muted-foreground">
                <tr>
                  <th className="text-left font-medium px-4 py-3">Nombre</th>
                  <th className="text-left font-medium px-4 py-3">Descripción</th>
                  <th className="text-left font-medium px-4 py-3">Requisitos</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {modelos.map((m) => (
                  <tr key={m.id} className="border-t border-border hover:bg-muted">
                    <td className="px-4 py-3">
                      <button onClick={() => abrirDetalle(m.id)} className="text-primary hover:underline inline-flex items-center gap-2"><Cpu size={14} /> {m.nombre}</button>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{m.descripcion ?? '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">{m.cantidadRequisitos}</td>
                    <td className="px-4 py-3 text-right">
                      <button onClick={() => bajaModelo(m.id)} className="inline-flex items-center gap-1 text-error hover:opacity-80 text-xs"><Trash2 size={14} /> Baja</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {creando && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setCreando(false)}>
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-heading text-lg font-bold text-foreground">Nuevo modelo</h3>
            <div>
              <label className="text-xs text-muted-foreground">Nombre *</label>
              <input value={nuevoNombre} onChange={(e) => setNuevoNombre(e.target.value)} className={`w-full mt-1 ${inputCls}`} placeholder="ej. Oficina Básica" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Descripción</label>
              <textarea value={nuevaDescripcion} onChange={(e) => setNuevaDescripcion(e.target.value)} className={`w-full mt-1 ${inputCls}`} rows={2} />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setCreando(false)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
              <button onClick={crearModelo} disabled={guardando} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">{guardando ? 'Creando…' : 'Crear'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Agregar la entrada a `PAGE_CONFIG`**

En `src/app/util/rbac.ts`, reemplazar:

```ts
  {
    id: "activos-inventario",
    label: "Inventario",
    icon: "Package",
    section: "Activos",
    visibleFor: [ROLE_ID.ADMIN],
    accessibleFor: [ROLE_ID.ADMIN],
  },
```

por:

```ts
  {
    id: "activos-inventario",
    label: "Inventario",
    icon: "Package",
    section: "Activos",
    visibleFor: [ROLE_ID.ADMIN],
    accessibleFor: [ROLE_ID.ADMIN],
  },
  {
    id: "activos-modelos",
    label: "Modelos de PC",
    icon: "Cpu",
    section: "Activos",
    visibleFor: [ROLE_ID.ADMIN],
    accessibleFor: [ROLE_ID.ADMIN],
  },
```

No tocar `SECTION_ORDER` — la sección "Activos" ya existe desde el subsistema 1.

- [ ] **Step 3: Agregar el ícono al sidebar**

En `src/app/Componentes/Shell/AppSidebar.tsx`, agregar `Cpu` al import de `lucide-react` (junto a
`Boxes`/`Package`, que ya están) y agregar `Cpu,` al objeto `ICON_MAP` (junto a las entradas `Boxes,`
y `Package,` ya existentes). No modificar ninguna otra entrada del mapa.

- [ ] **Step 4: Agregar el `case` de ruteo**

En `src/app/page.tsx`, agregar el import junto a los demás de pantallas de activos:

```tsx
import ActivosModelos from '@/app/screens/ActivosModelos/Screen';
```

Y en el `switch(page)`, después del `case 'activos-inventario':`, agregar:

```tsx
      case 'activos-modelos':
        return <ActivosModelos />;
```

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en los 4 archivos tocados.

- [ ] **Step 6: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/screens/ActivosModelos/Screen.tsx src/app/util/rbac.ts src/app/Componentes/Shell/AppSidebar.tsx src/app/page.tsx
git commit -m "feat: agregar pantalla de modelos de PC y su ruteo (subsistema 6)"
```

---

### Task 6: Frontend — enviar `specsJson` al elegir del catálogo

**Files:**
- Modify: `src/app/Componentes/ActivosInventario/ActivoForm.tsx`
- Modify: `src/app/screens/ActivosInventario/Screen.tsx`

**Interfaces:**
- Consumes: `POST /activos` / `PUT /activos/{id}` con el campo `specsJson` (Task 3); el `PCPart.specs`
  que ya llega del catálogo.
- Produces: activos creados desde el catálogo con `specsJson` poblado — el insumo que Task 7 evalúa.

- [ ] **Step 1: Guardar y enviar `specsJson` en `ActivoForm.tsx`**

En `src/app/Componentes/ActivosInventario/ActivoForm.tsx`, agregar el campo al estado inicial `f`.
Reemplazar:

```ts
    responsableDepartamentoId: activo?.responsableDepartamentoId ? String(activo.responsableDepartamentoId) : '',
  });
```

por:

```ts
    responsableDepartamentoId: activo?.responsableDepartamentoId ? String(activo.responsableDepartamentoId) : '',
    specsJson: '',
  });
```

En `elegirPcpart`, guardar el JSON crudo además de lo que ya hace. Reemplazar:

```ts
  const elegirPcpart = (p: PCPart) => {
    setF((s) => ({
      ...s,
      nombre: p.name,
      imagenReferencial: p.image || s.imagenReferencial,
      observaciones: formatearSpecs(p.specs) || s.observaciones,
    }));
  };
```

por:

```ts
  const elegirPcpart = (p: PCPart) => {
    setF((s) => ({
      ...s,
      nombre: p.name,
      imagenReferencial: p.image || s.imagenReferencial,
      observaciones: formatearSpecs(p.specs) || s.observaciones,
      specsJson: p.specs || '',
    }));
  };
```

En `guardar()`, agregar el campo al payload. Reemplazar:

```ts
      responsableDepartamentoId: f.responsableTipo === 'departamento' ? Number(f.responsableDepartamentoId) : null,
    };
```

por:

```ts
      responsableDepartamentoId: f.responsableTipo === 'departamento' ? Number(f.responsableDepartamentoId) : null,
      specsJson: f.specsJson || null,
    };
```

- [ ] **Step 2: Guardar y enviar `specsJson` en el alta rápida de `Screen.tsx`**

En `src/app/screens/ActivosInventario/Screen.tsx`, agregar el estado nuevo. Reemplazar:

```ts
  const [nuevoObservaciones, setNuevoObservaciones] = useState('');
```

por:

```ts
  const [nuevoObservaciones, setNuevoObservaciones] = useState('');
  const [nuevoSpecsJson, setNuevoSpecsJson] = useState('');
```

En `elegirPcpartNuevo`, guardar el JSON crudo. Reemplazar:

```ts
  const elegirPcpartNuevo = (p: PCPart) => {
    setNuevoNombre(p.name);
    if (p.image) setNuevoImagen(p.image);
    const specs = formatearSpecs(p.specs);
    if (specs) setNuevoObservaciones(specs);
  };
```

por:

```ts
  const elegirPcpartNuevo = (p: PCPart) => {
    setNuevoNombre(p.name);
    if (p.image) setNuevoImagen(p.image);
    const specs = formatearSpecs(p.specs);
    if (specs) setNuevoObservaciones(specs);
    setNuevoSpecsJson(p.specs || '');
  };
```

Este archivo tiene **dos** lugares que hacen `POST /activos` con el mismo payload de alta rápida
(`confirmarCrearComponente`, del diálogo "Agregar componente"; y la rama `'nuevo'` de
`confirmarReemplazar`, del diálogo "Reemplazar"). En **ambos**, agregar el campo al payload:
reemplazar cada una de las dos ocurrencias de

```ts
        responsableDepartamentoId: null,
      });
```

por

```ts
        responsableDepartamentoId: null,
        specsJson: nuevoSpecsJson || null,
      });
```

Y en **ambas** funciones de apertura de diálogo (`abrirAgregar` y `abrirReemplazar`), agregar el reseteo
del campo nuevo junto a los que ya se resetean: reemplazar cada una de las dos ocurrencias de

```ts
      setNuevoNumeroSerie(''); setNuevoImagen(''); setNuevoObservaciones(''); setErrorNuevo('');
```

por

```ts
      setNuevoNumeroSerie(''); setNuevoImagen(''); setNuevoObservaciones(''); setNuevoSpecsJson(''); setErrorNuevo('');
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en los dos archivos.

- [ ] **Step 4: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/Componentes/ActivosInventario/ActivoForm.tsx src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: enviar specsJson del catalogo al crear componentes (subsistema 6)"
```

---

### Task 7: Frontend — sección de evaluación en la ficha de la PC

**Files:**
- Modify: `src/app/screens/ActivosInventario/Screen.tsx` (depende de Task 6, mismo archivo)

**Interfaces:**
- Consumes: `GET /activos/modelos` y `GET /activos/modelos/evaluar/{pcId}?modeloId=` (Task 2);
  `ModeloPC`, `EvaluacionResultado` (Task 4).
- Produces: nada — última task de código.

- [ ] **Step 1: Agregar los imports**

Reemplazar la línea de import de tipos:

```ts
import type { ActivoListItem, ActivoDetalle, ActivoCategoria, ActivoEstado, PCPart, HistorialItem } from '@/app/Interfas/Interfaces';
```

por:

```ts
import type { ActivoListItem, ActivoDetalle, ActivoCategoria, ActivoEstado, PCPart, HistorialItem, ModeloPC, EvaluacionResultado } from '@/app/Interfas/Interfaces';
```

- [ ] **Step 2: Agregar el estado de evaluación**

Después de la línea `const [nuevoSpecsJson, setNuevoSpecsJson] = useState('');` (agregada en Task 6),
agregar:

```ts
  const [modelosPC, setModelosPC] = useState<ModeloPC[]>([]);
  const [modeloEvalId, setModeloEvalId] = useState('');
  const [evaluacion, setEvaluacion] = useState<EvaluacionResultado | null>(null);
  const [errorEval, setErrorEval] = useState('');
```

- [ ] **Step 3: Cargar los modelos disponibles**

En el `useEffect` inicial que ya carga categorías/estados/departamentos/empleados, agregar una línea más:

```ts
    apiClient.get<{ modelos: ModeloPC[] }>('/activos/modelos').then((r) => setModelosPC(r.modelos || [])).catch(() => {});
```

- [ ] **Step 4: Agregar el handler de evaluación y limpiar al cambiar de ficha**

Después de la función `cargarHistorial`, agregar:

```ts
  const evaluarContraModelo = async (pcId: number, modeloId: string) => {
    setModeloEvalId(modeloId);
    setErrorEval('');
    if (!modeloId) { setEvaluacion(null); return; }
    try {
      const r = await apiClient.get<EvaluacionResultado>(`/activos/modelos/evaluar/${pcId}?modeloId=${modeloId}`);
      setEvaluacion(r);
    } catch (e) {
      setEvaluacion(null);
      setErrorEval((e as Error).message);
    }
  };
```

En `abrirFicha`, limpiar el estado de evaluación al abrir otra ficha. Reemplazar:

```ts
      if (det.puedeAlbergarComponentes) cargarComponentes(id);
      else setComponentes([]);
      cargarHistorial(id);
```

por:

```ts
      if (det.puedeAlbergarComponentes) cargarComponentes(id);
      else setComponentes([]);
      cargarHistorial(id);
      setModeloEvalId(''); setEvaluacion(null); setErrorEval('');
```

- [ ] **Step 5: Renderizar la sección de evaluación**

Dentro del bloque `{a.puedeAlbergarComponentes && (...)}` de la ficha, agregar la sección de evaluación
al final del contenido de esa tarjeta — justo después del cierre del bloque condicional que renderiza la
tabla de componentes (`)}`) y antes del `</div>` que cierra la tarjeta:

```tsx
              <div className="border-t border-border pt-4 space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="text-sm font-semibold text-foreground">Evaluar contra modelo</label>
                  <select
                    value={modeloEvalId}
                    onChange={(e) => evaluarContraModelo(a.id, e.target.value)}
                    className={inputCls}
                  >
                    <option value="">— Elegí un modelo —</option>
                    {modelosPC.map((m) => <option key={m.id} value={m.id}>{m.nombre}</option>)}
                  </select>
                </div>

                {errorEval && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{errorEval}</div>}

                {evaluacion && (
                  <div className="space-y-3">
                    {evaluacion.score === null ? (
                      <p className="text-sm text-muted-foreground">Este modelo no tiene requisitos evaluables sobre esta PC.</p>
                    ) : (
                      <div>
                        <div className="flex items-baseline gap-2">
                          <span className={`text-3xl font-bold ${evaluacion.score >= 80 ? 'text-success' : evaluacion.score >= 50 ? 'text-warning' : 'text-error'}`}>
                            {evaluacion.score}%
                          </span>
                          <span className="text-sm text-muted-foreground">
                            {evaluacion.cumplidos} de {evaluacion.total - evaluacion.sinDatos} requisitos evaluables
                            {evaluacion.sinDatos > 0 && ` · ${evaluacion.sinDatos} sin datos`}
                          </span>
                        </div>
                        <div className="w-full h-2 bg-muted rounded-full mt-2 overflow-hidden">
                          <div
                            className={`h-full ${evaluacion.score >= 80 ? 'bg-success' : evaluacion.score >= 50 ? 'bg-warning' : 'bg-error'}`}
                            style={{ width: `${evaluacion.score}%` }}
                          />
                        </div>
                      </div>
                    )}

                    <table className="w-full text-sm">
                      <thead className="text-muted-foreground">
                        <tr>
                          <th className="text-left font-medium py-2">Categoría</th>
                          <th className="text-left font-medium py-2">Requisito</th>
                          <th className="text-left font-medium py-2">Mínimo</th>
                          <th className="text-left font-medium py-2">Real</th>
                          <th className="text-left font-medium py-2">Estado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evaluacion.requisitos.map((r) => (
                          <tr key={r.id} className="border-t border-border">
                            <td className="py-2 text-foreground">{r.categoriaNombre}</td>
                            <td className="py-2 text-muted-foreground">{r.etiqueta}</td>
                            <td className="py-2 text-muted-foreground">{r.valorMinimo} {r.unidad}</td>
                            <td className="py-2 text-muted-foreground">{r.valorReal !== null ? `${r.valorReal} ${r.unidad}` : '—'}</td>
                            <td className="py-2">
                              {r.estado === 'cumple' && <span className="text-success">✓ Cumple</span>}
                              {r.estado === 'no_cumple' && <span className="text-error">✗ No cumple</span>}
                              {r.estado === 'sin_datos' && <span className="text-muted-foreground">— Sin datos</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
```

- [ ] **Step 6: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Screen.tsx`.

- [ ] **Step 7: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: agregar evaluacion contra modelo en la ficha de la PC (subsistema 6)"
```

---

### Task 8: Verificación manual (sin commits)

**Files:** ninguno (checklist para el usuario).

- [ ] **Step 1: Presentar el checklist de verificación manual al usuario**

Los servidores ya corren en el entorno del usuario (no levantar localhost). Checklist:

1. Backend compila; al arrancar se crean las 2 tablas nuevas y la columna `specsJson`; reiniciar no duplica.
2. Entrar a "Modelos de PC" (nueva entrada del sidebar, sección Activos) y crear "Oficina Básica".
3. Agregar 3 requisitos: CPU ≥ 4 Núcleos, Memoria RAM ≥ 8 GB (Capacidad total), Almacenamiento ≥ 256 GB.
   Verificar que el select de Campo solo se habilita al elegir Categoría y solo ofrece campos válidos.
4. Intentar agregar un requisito duplicado (misma categoría+campo) → error claro. Valor 0 o negativo → error.
5. Crear una PC y agregarle componentes **eligiéndolos del catálogo** (CPU, RAM, Almacenamiento).
6. En la ficha de esa PC, elegir "Oficina Básica" en "Evaluar contra modelo" → aparece el score, la barra
   y el detalle por requisito con los valores reales. **Verificar especialmente que una RAM de
   `modules:[2,16]` se evalúe como 32 GB** (no 2 ni 16).
7. Agregar un componente **cargado a mano** (sin usar el catálogo) de una categoría con requisito → ese
   requisito aparece "Sin datos" y el score se calcula sobre el resto.
8. Crear un modelo sin requisitos y evaluar contra él → mensaje claro, sin error.
9. Nombre de modelo duplicado → error claro.
10. RBAC: un no-ADMIN no ve "Modelos de PC" en el sidebar; puede ver evaluaciones pero no crear/editar/borrar modelos (403).
11. Dark mode y responsive de la pantalla nueva y de la sección de evaluación.

Esperar el "todo bien" (o los ajustes) del usuario antes de la revisión final de rama.

---

## Notas de ejecución

- Tasks 1-3 en `Backend_RRHH` (rama `activos-modelos-scoring`); Tasks 4-7 en `RRHH` (misma rama);
  Task 8 es verificación manual.
- Orden: 1 → 2 → 3 (backend) → 4 → 5 → 6 → 7 (frontend; 6 y 7 tocan el mismo `Screen.tsx`, secuencial);
  → 8.
- Tras las tasks de código: revisión final de rama completa (opus, una por repo, en paralelo), luego merge
  fast-forward a `main` y push, cada uno con confirmación explícita del usuario.
