# Sistema de Activos — Activos base + ubicación + estados (Subsistema 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la entidad `Activo` (el inventario), su ubicación en el organigrama, la máquina de estados auditada, y la pantalla de inventario con ficha, formulario y generación de QR/código de barras.

**Architecture:** Backend FastAPI con 2 tablas nuevas (`Activo`, `ActivoHistorial`) creadas idempotentemente, un helper de auditoría que escribe en cada mutación dentro de la misma transacción, y un router CRUD. Frontend Next.js con una pantalla de tres modos (lista/ficha/formulario), un componente de códigos (QR + barra) y un formulario con selector de responsable polimórfico.

**Tech Stack:** FastAPI + SQLAlchemy `text()` + SQL Server (pyodbc) · Next.js App Router + React + Tailwind · `qrcode.react` + `react-barcode` · lucide-react.

## Global Constraints

- **Prefijo `Activo`** para las tablas del módulo: `Activo`, `ActivoHistorial`. Consume las de S1 (`ActivoCategoria`, `ActivoFabricante`, `ActivoEstado`).
- **Un único responsable** por activo: `responsableTipo` ∈ `{empleado, oficina, departamento}` (o NULL) + las 3 columnas nullable `responsableEmpleadoId`/`responsableOficinaId`/`responsableDepartamentoId` (a lo sumo una seteada).
- **Auditoría en cada mutación**: `ActivoHistorial` se escribe (INSERT) en la MISMA transacción que la mutación. Nunca UPDATE/DELETE sobre historial. `usuarioEmpleadoId` del token.
- **RBAC**: lecturas con `require_any_auth`; escrituras (`POST`/`PUT`/`PATCH`/`DELETE`) solo `require_roles(ROLE_ADMIN)`.
- **Estado default "Disponible"** al crear si no se especifica (resuelto por `codigo='disponible'`).
- **`numeroSerie` obligatorio** si la categoría elegida tiene `requiereSerie=1`.
- **`numeroInventario` único** entre activos vigentes (`activo=1`).
- **`imagenReferencial`** es una URL de texto; S2 NO sube ni almacena imágenes.
- **SQL parametrizado**: valores bindeados, sin concatenación de valores de usuario.
- **Tokens "Orgánico Cálido"** en frontend (`bg-card`, `bg-background`, `border-border`, `shadow-soft`, `text-foreground`, `text-muted-foreground`, `text-primary`, `text-error`), sin hex crudo. Dark mode por tokens.
- **Inventario = solo ADMIN** en el frontend (visible/accesible).
- **Sin suite de tests automatizada** (patrón del proyecto): verificación por tarea = compilación (`py -m py_compile` / `npx tsc --noEmit`) + chequeo manual.
- **Estados válidos** (por `codigo`): `disponible, asignado, en_reparacion, danado, en_deposito, prestado, en_garantia, dado_de_baja, extraviado, robado`.
- **Organigrama**: `Employee` usa columna `name`; `Department` y `Office` usan `nombre`. Endpoints: `/rrhh/employees` → `{employees:[{id,name}]}`, `/departments/` → `{departments:[{id,nombre,offices:[{id,nombre}]}]}`.

---

## File Structure

**Backend_RRHH:**
- Create: `app/database/activos.py` — tablas `Activo`/`ActivoHistorial` (`ensure_tables`), `_registrar_historial`, helpers de lectura con joins.
- Create: `app/routes/activos.py` — router CRUD (7 endpoints).
- Modify: `app/main.py` — registrar el router.

**RRHH:**
- Modify: `package.json` — dependencias `qrcode.react`, `react-barcode`.
- Modify: `src/app/Interfas/Interfaces.ts` — `"activos-inventario"` en `Page` + interfaces `ActivoListItem`, `ActivoDetalle`.
- Create: `src/app/Componentes/ActivosInventario/CodigoLabels.tsx` — QR + código de barras imprimibles.
- Create: `src/app/Componentes/ActivosInventario/ActivoForm.tsx` — formulario crear/editar (con selector de responsable).
- Create: `src/app/screens/ActivosInventario/Screen.tsx` — lista + ficha + orquestación + diálogo cambiar estado.
- Modify: `src/app/util/rbac.ts` — entrada `activos-inventario`.
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx` — ícono `Package`.
- Modify: `src/app/page.tsx` — `case 'activos-inventario'`.

---

## Task 1: Backend — módulo de datos `activos.py`

**Files:**
- Create: `app/database/activos.py`

**Interfaces:**
- Consumes: nada nuevo (referencia lógica a tablas de S1).
- Produces: `ensure_tables(db)`, `RESPONSABLE_TIPOS`, `registrar_historial(db, activo_id, accion, campo, valor_anterior, valor_nuevo, usuario_id, observacion)`, `listar_activos(db, filtros)`, `obtener_activo(db, id)`, `buscar_por_codigo(db, codigo)`, `estado_disponible_id(db)`.

- [ ] **Step 1: Crear el módulo con las 2 tablas y helpers**

```python
"""
Activos del Sistema de Gestion de Activos (subsistema 2). Entidad principal
Activo (inventario) + ActivoHistorial (auditoria inmutable, se escribe en cada
mutacion). Consume la config de S1 (ActivoCategoria/ActivoFabricante/ActivoEstado)
y el organigrama existente (Employee/Office/Department).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional


RESPONSABLE_TIPOS = {"empleado", "oficina", "departamento"}


CREATE_ACTIVO_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'Activo' AND xtype = 'U')
BEGIN
    CREATE TABLE Activo (
        id                        INT IDENTITY(1,1) PRIMARY KEY,
        numeroInventario          NVARCHAR(100)  NOT NULL,
        nombre                    NVARCHAR(300)  NOT NULL,
        categoriaId               INT            NOT NULL,
        fabricanteId              INT            NULL,
        estadoId                  INT            NOT NULL,
        fechaAlta                 DATE           NOT NULL,
        anio                      INT            NULL,
        observaciones             NVARCHAR(MAX)  NULL,
        imagenReferencial         NVARCHAR(1000) NULL,
        numeroSerie               NVARCHAR(200)  NULL,
        codigoBarras              NVARCHAR(200)  NULL,
        codigoQR                  NVARCHAR(500)  NULL,
        responsableTipo           NVARCHAR(20)   NULL,
        responsableEmpleadoId     INT            NULL,
        responsableOficinaId      INT            NULL,
        responsableDepartamentoId INT            NULL,
        activo                    BIT            NOT NULL DEFAULT 1,
        createdAt                 DATETIME2      NOT NULL,
        updatedAt                 DATETIME2      NOT NULL
    );
    CREATE INDEX IX_Activo_numeroInventario ON Activo (numeroInventario);
END
"""

CREATE_HISTORIAL_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'ActivoHistorial' AND xtype = 'U')
BEGIN
    CREATE TABLE ActivoHistorial (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        activoId          INT           NOT NULL,
        accion            NVARCHAR(30)  NOT NULL,
        campo             NVARCHAR(50)  NULL,
        valorAnterior     NVARCHAR(MAX) NULL,
        valorNuevo        NVARCHAR(MAX) NULL,
        usuarioEmpleadoId INT           NULL,
        observacion       NVARCHAR(500) NULL,
        createdAt         DATETIME2     NOT NULL
    );
    CREATE INDEX IX_ActivoHistorial_activoId ON ActivoHistorial (activoId);
END
"""


def ensure_tables(db: Session) -> None:
    """Crea Activo y ActivoHistorial si no existen (idempotente)."""
    db.execute(text(CREATE_ACTIVO_SQL))
    db.execute(text(CREATE_HISTORIAL_SQL))
    db.commit()


def registrar_historial(db: Session, activo_id: int, accion: str, campo: Optional[str],
                        valor_anterior: Optional[str], valor_nuevo: Optional[str],
                        usuario_id: Optional[int], observacion: Optional[str] = None) -> None:
    """Inserta una fila de historial. NO commitea -- corre dentro de la
    transaccion de la mutacion que lo llama."""
    db.execute(text("""
        INSERT INTO ActivoHistorial (activoId, accion, campo, valorAnterior, valorNuevo, usuarioEmpleadoId, observacion, createdAt)
        VALUES (:activoId, :accion, :campo, :valorAnterior, :valorNuevo, :usuarioId, :observacion, :now)
    """), {
        "activoId": activo_id, "accion": accion, "campo": campo,
        "valorAnterior": valor_anterior, "valorNuevo": valor_nuevo,
        "usuarioId": usuario_id, "observacion": observacion, "now": datetime.utcnow(),
    })


def estado_disponible_id(db: Session) -> Optional[int]:
    """Id del estado 'Disponible' (codigo='disponible'), para el default al crear."""
    r = db.execute(text("SELECT id FROM ActivoEstado WHERE codigo = 'disponible' AND activo = 1")).mappings().first()
    return r["id"] if r else None


# Fragmento de SELECT reutilizado por listado y detalle: resuelve nombres.
_SELECT_ACTIVO = """
    SELECT
        a.id, a.numeroInventario, a.nombre, a.categoriaId, a.fabricanteId, a.estadoId,
        a.fechaAlta, a.anio, a.observaciones, a.imagenReferencial, a.numeroSerie,
        a.codigoBarras, a.codigoQR, a.responsableTipo, a.responsableEmpleadoId,
        a.responsableOficinaId, a.responsableDepartamentoId, a.createdAt, a.updatedAt,
        c.nombre AS categoriaNombre, c.grupo AS grupo, c.requiereSerie AS requiereSerie,
        e.nombre AS estadoNombre, e.codigo AS estadoCodigo,
        f.nombre AS fabricanteNombre,
        CASE a.responsableTipo
            WHEN 'empleado'     THEN re.name
            WHEN 'oficina'      THEN ro.nombre
            WHEN 'departamento' THEN rd.nombre
            ELSE NULL
        END AS responsableNombre
    FROM Activo a
    INNER JOIN ActivoCategoria c ON a.categoriaId = c.id
    INNER JOIN ActivoEstado e    ON a.estadoId = e.id
    LEFT  JOIN ActivoFabricante f ON a.fabricanteId = f.id
    LEFT  JOIN Employee re   ON a.responsableEmpleadoId = re.id
    LEFT  JOIN Office ro     ON a.responsableOficinaId = ro.id
    LEFT  JOIN Department rd ON a.responsableDepartamentoId = rd.id
    WHERE a.activo = 1
"""


def _fila_a_dict(r) -> dict:
    return {
        "id": r["id"], "numeroInventario": r["numeroInventario"], "nombre": r["nombre"],
        "categoriaId": r["categoriaId"], "categoriaNombre": r["categoriaNombre"], "grupo": r["grupo"],
        "requiereSerie": bool(r["requiereSerie"]),
        "fabricanteId": r["fabricanteId"], "fabricanteNombre": r["fabricanteNombre"],
        "estadoId": r["estadoId"], "estadoNombre": r["estadoNombre"], "estadoCodigo": r["estadoCodigo"],
        "fechaAlta": r["fechaAlta"].isoformat() if r["fechaAlta"] else None,
        "anio": r["anio"], "observaciones": r["observaciones"], "imagenReferencial": r["imagenReferencial"],
        "numeroSerie": r["numeroSerie"], "codigoBarras": r["codigoBarras"], "codigoQR": r["codigoQR"],
        "responsableTipo": r["responsableTipo"], "responsableNombre": r["responsableNombre"],
        "responsableEmpleadoId": r["responsableEmpleadoId"], "responsableOficinaId": r["responsableOficinaId"],
        "responsableDepartamentoId": r["responsableDepartamentoId"],
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
        "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
    }


def listar_activos(db: Session, categoria_id: Optional[int] = None, grupo: Optional[str] = None,
                   estado_id: Optional[int] = None, texto: Optional[str] = None) -> list[dict]:
    """Activos vigentes con nombres resueltos, con filtros opcionales."""
    query = _SELECT_ACTIVO
    params = {}
    if categoria_id:
        query += " AND a.categoriaId = :catId"
        params["catId"] = categoria_id
    if grupo:
        query += " AND c.grupo = :grupo"
        params["grupo"] = grupo
    if estado_id:
        query += " AND a.estadoId = :estId"
        params["estId"] = estado_id
    if texto:
        query += " AND (a.nombre LIKE :q OR a.numeroInventario LIKE :q OR a.numeroSerie LIKE :q)"
        params["q"] = f"%{texto}%"
    query += " ORDER BY a.createdAt DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def obtener_activo(db: Session, activo_id: int) -> Optional[dict]:
    """Detalle de un activo vigente con nombres resueltos, o None."""
    r = db.execute(text(_SELECT_ACTIVO + " AND a.id = :id"), {"id": activo_id}).mappings().first()
    return _fila_a_dict(r) if r else None


def buscar_por_codigo(db: Session, codigo: str) -> Optional[dict]:
    """Busca un activo vigente cuyo numeroInventario/codigoBarras/codigoQR/numeroSerie
    coincida exactamente con el codigo dado."""
    r = db.execute(text(_SELECT_ACTIVO + """
        AND (a.numeroInventario = :cod OR a.codigoBarras = :cod OR a.codigoQR = :cod OR a.numeroSerie = :cod)
    """), {"cod": codigo}).mappings().first()
    return _fila_a_dict(r) if r else None
```

- [ ] **Step 2: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/database/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/database/activos.py
git commit -m "feat: agregar modelo de datos de activos e historial"
```

---

## Task 2: Backend — router CRUD `activos.py` + registro

**Files:**
- Create: `app/routes/activos.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: helpers de Task 1; `require_any_auth`, `require_roles`, `ROLE_ADMIN`, `get_current_user`, `SessionLocal`.
- Produces: `GET /activos`, `GET /activos/{id}`, `GET /activos/buscar`, `POST /activos`, `PUT /activos/{id}`, `PATCH /activos/{id}/estado`, `DELETE /activos/{id}`.

- [ ] **Step 1: Crear el router**

```python
"""
Router /activos -- CRUD del inventario (subsistema 2). Lecturas: cualquier
autenticado. Escrituras: solo ADMIN. Cada mutacion escribe en ActivoHistorial
dentro de la misma transaccion.
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
)

router = APIRouter(prefix="/activos", tags=["Activos"])

require_admin = require_roles(ROLE_ADMIN)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return value[:10]  # 'YYYY-MM-DD' -- SQL Server DATE lo acepta bindeado
    return value


def _validar_responsable(data: dict) -> dict:
    """Devuelve dict con tipo + los 3 ids (los no aplicables en None). 400 si es inconsistente."""
    tipo = data.get("responsableTipo")
    if tipo is None or tipo == "":
        return {"tipo": None, "empleado": None, "oficina": None, "departamento": None}
    if tipo not in RESPONSABLE_TIPOS:
        raise HTTPException(status_code=400, detail=f"responsableTipo debe ser uno de: {sorted(RESPONSABLE_TIPOS)}")
    ids = {
        "empleado": data.get("responsableEmpleadoId") if tipo == "empleado" else None,
        "oficina": data.get("responsableOficinaId") if tipo == "oficina" else None,
        "departamento": data.get("responsableDepartamentoId") if tipo == "departamento" else None,
    }
    if not ids[tipo]:
        raise HTTPException(status_code=400, detail=f"Falta el id del responsable para el tipo '{tipo}'")
    return {"tipo": tipo, **ids}


def _resolver_estado(db: Session, estado_id: Optional[int]) -> int:
    if estado_id:
        r = db.execute(text("SELECT id FROM ActivoEstado WHERE id = :id AND activo = 1"), {"id": estado_id}).first()
        if not r:
            raise HTTPException(status_code=400, detail="estadoId inexistente")
        return estado_id
    default_id = estado_disponible_id(db)
    if not default_id:
        raise HTTPException(status_code=400, detail="No existe el estado 'Disponible'; verifique la configuracion")
    return default_id


def _validar_comunes(db: Session, data: dict) -> tuple:
    """Valida obligatorios/FK/serie. Devuelve (nombre, categoria, requiereSerie)."""
    numero = (data.get("numeroInventario") or "").strip()
    if not numero:
        raise HTTPException(status_code=400, detail="El numero de inventario es obligatorio")
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if not data.get("fechaAlta"):
        raise HTTPException(status_code=400, detail="La fecha de alta es obligatoria")
    cat = db.execute(text("SELECT id, requiereSerie FROM ActivoCategoria WHERE id = :id AND activo = 1"),
                     {"id": data.get("categoriaId")}).mappings().first()
    if not cat:
        raise HTTPException(status_code=400, detail="categoriaId inexistente")
    if data.get("fabricanteId"):
        fab = db.execute(text("SELECT id FROM ActivoFabricante WHERE id = :id AND activo = 1"),
                         {"id": data.get("fabricanteId")}).first()
        if not fab:
            raise HTTPException(status_code=400, detail="fabricanteId inexistente")
    if cat["requiereSerie"] and not (data.get("numeroSerie") or "").strip():
        raise HTTPException(status_code=400, detail="Esta categoria requiere numero de serie")
    return numero, cat["id"], bool(cat["requiereSerie"])


# ─── Lectura ─────────────────────────────────────────────────────────────────
@router.get("", dependencies=[Depends(require_any_auth)])
def get_activos(categoriaId: Optional[int] = None, grupo: Optional[str] = None,
                estadoId: Optional[int] = None, texto: Optional[str] = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"activos": listar_activos(db, categoriaId, grupo, estadoId, texto)}


@router.get("/buscar", dependencies=[Depends(require_any_auth)])
def get_por_codigo(codigo: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = buscar_por_codigo(db, codigo)
    if not activo:
        raise HTTPException(status_code=404, detail="No se encontro un activo con ese codigo")
    return activo


@router.get("/{activo_id}", dependencies=[Depends(require_any_auth)])
def get_activo(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = obtener_activo(db, activo_id)
    if not activo:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return activo


# ─── Escritura ───────────────────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_admin)])
def crear_activo(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    numero, cat_id, _ = _validar_comunes(db, data)
    dup = db.execute(text("SELECT id FROM Activo WHERE activo = 1 AND numeroInventario = :n"), {"n": numero}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe un activo con ese numero de inventario")
    estado_id = _resolver_estado(db, data.get("estadoId"))
    resp = _validar_responsable(data)
    now = datetime.utcnow()
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
    new_id = result.scalar()
    registrar_historial(db, new_id, "creacion", None, None, numero, current_user.get("employeeId"))
    db.commit()
    return {"id": new_id}


@router.put("/{activo_id}", dependencies=[Depends(require_admin)])
def actualizar_activo(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    numero, cat_id, _ = _validar_comunes(db, data)
    dup = db.execute(text("SELECT id FROM Activo WHERE activo = 1 AND numeroInventario = :n AND id <> :id"),
                     {"n": numero, "id": activo_id}).first()
    if dup:
        raise HTTPException(status_code=400, detail="Ya existe un activo con ese numero de inventario")
    estado_id = _resolver_estado(db, data.get("estadoId"))
    resp = _validar_responsable(data)
    usuario = current_user.get("employeeId")

    # Historial de cambios relevantes
    if estado_id != actual["estadoId"]:
        nuevo_est = db.execute(text("SELECT nombre FROM ActivoEstado WHERE id = :id"), {"id": estado_id}).mappings().first()
        registrar_historial(db, activo_id, "cambio_estado", "estado", actual["estadoNombre"],
                            nuevo_est["nombre"] if nuevo_est else str(estado_id), usuario)
    resp_cambio = (resp["tipo"] != actual["responsableTipo"] or
                   resp["empleado"] != actual["responsableEmpleadoId"] or
                   resp["oficina"] != actual["responsableOficinaId"] or
                   resp["departamento"] != actual["responsableDepartamentoId"])
    if resp_cambio:
        registrar_historial(db, activo_id, "cambio_responsable", "responsable",
                            actual["responsableNombre"], _nombre_responsable(db, resp), usuario)
    otros_cambio = (numero != actual["numeroInventario"] or (data.get("nombre") or "").strip() != actual["nombre"]
                    or cat_id != actual["categoriaId"])
    if otros_cambio:
        registrar_historial(db, activo_id, "modificacion", "datos", None, None, usuario)

    now = datetime.utcnow()
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
    db.commit()
    return {"message": "Activo actualizado"}


@router.patch("/{activo_id}/estado", dependencies=[Depends(require_admin)])
def cambiar_estado(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                   current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    nuevo_id = data.get("estadoId")
    nuevo = db.execute(text("SELECT id, nombre FROM ActivoEstado WHERE id = :id AND activo = 1"),
                       {"id": nuevo_id}).mappings().first()
    if not nuevo:
        raise HTTPException(status_code=400, detail="estadoId inexistente")
    if nuevo["id"] != actual["estadoId"]:
        registrar_historial(db, activo_id, "cambio_estado", "estado", actual["estadoNombre"], nuevo["nombre"],
                            current_user.get("employeeId"), (data.get("observacion") or None))
    db.execute(text("UPDATE Activo SET estadoId = :est, updatedAt = :now WHERE id = :id"),
               {"est": nuevo["id"], "now": datetime.utcnow(), "id": activo_id})
    db.commit()
    return {"message": "Estado actualizado"}


@router.delete("/{activo_id}", dependencies=[Depends(require_admin)])
def baja_activo(activo_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    registrar_historial(db, activo_id, "baja", None, actual["numeroInventario"], None, current_user.get("employeeId"))
    db.execute(text("UPDATE Activo SET activo = 0, updatedAt = :now WHERE id = :id"),
               {"now": datetime.utcnow(), "id": activo_id})
    db.commit()
    return {"message": "Activo dado de baja"}


def _nombre_responsable(db: Session, resp: dict) -> Optional[str]:
    """Resuelve el nombre legible del nuevo responsable para el historial."""
    if resp["tipo"] == "empleado" and resp["empleado"]:
        r = db.execute(text("SELECT name AS n FROM Employee WHERE id = :id"), {"id": resp["empleado"]}).mappings().first()
        return r["n"] if r else None
    if resp["tipo"] == "oficina" and resp["oficina"]:
        r = db.execute(text("SELECT nombre AS n FROM Office WHERE id = :id"), {"id": resp["oficina"]}).mappings().first()
        return r["n"] if r else None
    if resp["tipo"] == "departamento" and resp["departamento"]:
        r = db.execute(text("SELECT nombre AS n FROM Department WHERE id = :id"), {"id": resp["departamento"]}).mappings().first()
        return r["n"] if r else None
    return None
```

Nota: `_nombre_responsable` se define al final del archivo pero se referencia dentro de `actualizar_activo`; en Python esto funciona porque la función se resuelve en tiempo de llamada, no de definición. Alternativamente, moverla arriba de `actualizar_activo` — cualquiera de las dos ubicaciones es válida.

- [ ] **Step 2: Registrar el router en `main.py`**

En `app/main.py`, agregar `activos` a la línea de import de routers (junto a `activos_config`) y agregar tras `app.include_router(activos_config.router)`:
```python
app.include_router(activos.router)
```

- [ ] **Step 3: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/routes/activos.py app/main.py`
Expected: sin salida (exit 0).

- [ ] **Step 4: Verificación manual (recomendada)**

Con el server corriendo y token ADMIN: `POST /activos` con `{numeroInventario, nombre, categoriaId, fechaAlta}` → `{id}` y estado default Disponible; `GET /activos` → lo lista con nombres resueltos; `POST` con nº duplicado → 400; una categoría con `requiereSerie=1` sin serie → 400; `PATCH /activos/{id}/estado` con `{estadoId, observacion}` → cambia y registra historial; `GET /activos/buscar?codigo=<numeroInventario>` → devuelve el activo. Con token no-ADMIN, `POST` → 403, `GET` → 200.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/routes/activos.py app/main.py
git commit -m "feat: agregar router CRUD de activos con auditoria"
```

---

## Task 3: Frontend — dependencias y tipos

**Files:**
- Modify: `package.json` (vía `npm install`)
- Modify: `src/app/Interfas/Interfaces.ts`

**Interfaces:**
- Produces: `"activos-inventario"` en `Page`; interfaces `ActivoListItem`, `ActivoDetalle`.

- [ ] **Step 1: Instalar dependencias**

Run:
```bash
cd "C:\Users\Emiliano\Documents\RRHH"
npm install qrcode.react react-barcode
```
Expected: `added N packages`. Verifica que `package.json` liste `qrcode.react` y `react-barcode`.

- [ ] **Step 2: Agregar tipos en `Interfaces.ts`**

(a) Agregar `"activos-inventario"` al union type `Page`.

(b) Agregar:
```typescript
export interface ActivoListItem {
  id: number;
  numeroInventario: string;
  nombre: string;
  categoriaId: number;
  categoriaNombre: string;
  grupo: string;
  requiereSerie: boolean;
  fabricanteId: number | null;
  fabricanteNombre: string | null;
  estadoId: number;
  estadoNombre: string;
  estadoCodigo: string;
  fechaAlta: string | null;
  anio: number | null;
  observaciones: string | null;
  imagenReferencial: string | null;
  numeroSerie: string | null;
  codigoBarras: string | null;
  codigoQR: string | null;
  responsableTipo: string | null;
  responsableNombre: string | null;
  responsableEmpleadoId: number | null;
  responsableOficinaId: number | null;
  responsableDepartamentoId: number | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export type ActivoDetalle = ActivoListItem;
```

- [ ] **Step 3: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Interfaces"`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add package.json package-lock.json src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar dependencias de codigos y tipos de activos"
```

---

## Task 4: Frontend — componente `CodigoLabels`

**Files:**
- Create: `src/app/Componentes/ActivosInventario/CodigoLabels.tsx`

**Interfaces:**
- Consumes: `qrcode.react`, `react-barcode`.
- Produces: `CodigoLabels({ valorQR, valorBarras })` — renderiza un QR y un código de barras imprimibles.

- [ ] **Step 1: Crear el componente**

```tsx
'use client';

import React from 'react';
import { QRCodeSVG } from 'qrcode.react';
import Barcode from 'react-barcode';

interface CodigoLabelsProps {
  valorQR: string;
  valorBarras: string;
}

export function CodigoLabels({ valorQR, valorBarras }: CodigoLabelsProps) {
  return (
    <div className="flex flex-wrap items-center gap-6 bg-card border border-border rounded-xl p-4 shadow-soft">
      {valorQR && (
        <div className="flex flex-col items-center gap-1">
          <div className="bg-white p-2 rounded-lg">
            <QRCodeSVG value={valorQR} size={96} />
          </div>
          <span className="text-xs text-muted-foreground">QR</span>
        </div>
      )}
      {valorBarras && (
        <div className="flex flex-col items-center gap-1">
          <div className="bg-white p-2 rounded-lg">
            <Barcode value={valorBarras} height={48} fontSize={12} margin={0} />
          </div>
          <span className="text-xs text-muted-foreground">Código de barras</span>
        </div>
      )}
    </div>
  );
}
```

Nota: el fondo blanco (`bg-white`) en los contenedores del QR/barra es intencional y correcto: los códigos deben tener alto contraste para ser escaneables, independientemente del tema claro/oscuro de la app. No es una violación de los tokens semánticos — es un requisito funcional de legibilidad de códigos.

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "CodigoLabels"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/ActivosInventario/CodigoLabels.tsx
git commit -m "feat: agregar componente de QR y codigo de barras"
```

---

## Task 5: Frontend — formulario `ActivoForm`

**Files:**
- Create: `src/app/Componentes/ActivosInventario/ActivoForm.tsx`

**Interfaces:**
- Consumes: `apiClient`, tipos `ActivoDetalle`, `ActivoCategoria`/`ActivoFabricante`/`ActivoEstado` (S1).
- Produces: `ActivoForm({ activo, onGuardado, onCancelar })` — `activo: ActivoDetalle | null` (null = alta). Llama `POST`/`PUT /activos` y avisa al padre.

- [ ] **Step 1: Crear el componente**

```tsx
'use client';

import React, { useEffect, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import type { ActivoDetalle, ActivoCategoria, ActivoFabricante, ActivoEstado } from '@/app/Interfas/Interfaces';
import { Search } from 'lucide-react';

interface DeptOption { id: number; nombre: string; offices: { id: number; nombre: string }[]; }
interface EmpOption { id: number; name: string; }

interface ActivoFormProps {
  activo: ActivoDetalle | null;
  onGuardado: () => void;
  onCancelar: () => void;
}

const RESP_TIPOS = [
  { value: '', label: 'Sin asignar' },
  { value: 'empleado', label: 'Empleado' },
  { value: 'oficina', label: 'Oficina' },
  { value: 'departamento', label: 'Departamento' },
];

export function ActivoForm({ activo, onGuardado, onCancelar }: ActivoFormProps) {
  const [categorias, setCategorias] = useState<ActivoCategoria[]>([]);
  const [fabricantes, setFabricantes] = useState<ActivoFabricante[]>([]);
  const [estados, setEstados] = useState<ActivoEstado[]>([]);
  const [depts, setDepts] = useState<DeptOption[]>([]);
  const [empleados, setEmpleados] = useState<EmpOption[]>([]);

  const [f, setF] = useState({
    numeroInventario: activo?.numeroInventario ?? '',
    nombre: activo?.nombre ?? '',
    categoriaId: activo?.categoriaId ? String(activo.categoriaId) : '',
    fabricanteId: activo?.fabricanteId ? String(activo.fabricanteId) : '',
    estadoId: activo?.estadoId ? String(activo.estadoId) : '',
    fechaAlta: activo?.fechaAlta ? activo.fechaAlta.slice(0, 10) : '',
    anio: activo?.anio != null ? String(activo.anio) : '',
    observaciones: activo?.observaciones ?? '',
    imagenReferencial: activo?.imagenReferencial ?? '',
    numeroSerie: activo?.numeroSerie ?? '',
    codigoBarras: activo?.codigoBarras ?? '',
    codigoQR: activo?.codigoQR ?? '',
    responsableTipo: activo?.responsableTipo ?? '',
    responsableEmpleadoId: activo?.responsableEmpleadoId ? String(activo.responsableEmpleadoId) : '',
    responsableOficinaId: activo?.responsableOficinaId ? String(activo.responsableOficinaId) : '',
    responsableDepartamentoId: activo?.responsableDepartamentoId ? String(activo.responsableDepartamentoId) : '',
  });
  const [error, setError] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [codigoBusqueda, setCodigoBusqueda] = useState('');

  useEffect(() => {
    apiClient.get<{ categorias: ActivoCategoria[] }>('/activos/config/categorias').then((r) => setCategorias(r.categorias || [])).catch(() => {});
    apiClient.get<{ fabricantes: ActivoFabricante[] }>('/activos/config/fabricantes').then((r) => setFabricantes(r.fabricantes || [])).catch(() => {});
    apiClient.get<{ estados: ActivoEstado[] }>('/activos/config/estados').then((r) => setEstados(r.estados || [])).catch(() => {});
    apiClient.get<{ departments: DeptOption[] }>('/departments/').then((r) => setDepts(r.departments || [])).catch(() => {});
    apiClient.get<{ employees: EmpOption[] }>('/rrhh/employees').then((r) => setEmpleados(r.employees || [])).catch(() => {});
  }, []);

  const categoriaSel = categorias.find((c) => String(c.id) === f.categoriaId);
  const serieObligatoria = categoriaSel?.requiereSerie ?? false;

  const buscarCodigo = async () => {
    if (!codigoBusqueda.trim()) return;
    try {
      const existente = await apiClient.get<ActivoDetalle>(`/activos/buscar?codigo=${encodeURIComponent(codigoBusqueda.trim())}`);
      if (confirm(`Ya existe el activo "${existente.nombre}" (${existente.numeroInventario}) con ese código. ¿Precargar sus datos?`)) {
        setF((s) => ({ ...s, numeroInventario: existente.numeroInventario, nombre: existente.nombre }));
      }
    } catch {
      setF((s) => ({ ...s, codigoBarras: codigoBusqueda.trim() }));
    }
  };

  const guardar = async () => {
    setError('');
    if (!f.numeroInventario.trim()) { setError('El número de inventario es obligatorio.'); return; }
    if (!f.nombre.trim()) { setError('El nombre es obligatorio.'); return; }
    if (!f.categoriaId) { setError('La categoría es obligatoria.'); return; }
    if (!f.fechaAlta) { setError('La fecha de alta es obligatoria.'); return; }
    if (serieObligatoria && !f.numeroSerie.trim()) { setError('Esta categoría requiere número de serie.'); return; }
    if (f.responsableTipo === 'empleado' && !f.responsableEmpleadoId) { setError('Elegí el empleado responsable.'); return; }
    if (f.responsableTipo === 'oficina' && !f.responsableOficinaId) { setError('Elegí la oficina responsable.'); return; }
    if (f.responsableTipo === 'departamento' && !f.responsableDepartamentoId) { setError('Elegí el departamento responsable.'); return; }

    const payload = {
      numeroInventario: f.numeroInventario.trim(),
      nombre: f.nombre.trim(),
      categoriaId: Number(f.categoriaId),
      fabricanteId: f.fabricanteId ? Number(f.fabricanteId) : null,
      estadoId: f.estadoId ? Number(f.estadoId) : null,
      fechaAlta: f.fechaAlta,
      anio: f.anio ? Number(f.anio) : null,
      observaciones: f.observaciones || null,
      imagenReferencial: f.imagenReferencial || null,
      numeroSerie: f.numeroSerie || null,
      codigoBarras: f.codigoBarras || null,
      codigoQR: f.codigoQR || null,
      responsableTipo: f.responsableTipo || null,
      responsableEmpleadoId: f.responsableTipo === 'empleado' ? Number(f.responsableEmpleadoId) : null,
      responsableOficinaId: f.responsableTipo === 'oficina' ? Number(f.responsableOficinaId) : null,
      responsableDepartamentoId: f.responsableTipo === 'departamento' ? Number(f.responsableDepartamentoId) : null,
    };
    setGuardando(true);
    try {
      if (activo) await apiClient.put(`/activos/${activo.id}`, payload);
      else await apiClient.post('/activos', payload);
      onGuardado();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGuardando(false);
    }
  };

  const oficinas = depts.flatMap((d) => d.offices.map((o) => ({ id: o.id, nombre: `${d.nombre} / ${o.nombre}` })));
  const inputCls = 'w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm';

  return (
    <div className="space-y-4 bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6">
      <h2 className="font-heading text-xl font-bold text-foreground">{activo ? 'Editar activo' : 'Nuevo activo'}</h2>
      {error && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{error}</div>}

      {!activo && (
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="text-xs text-muted-foreground">Buscar por código (inventario/barras/QR/serie)</label>
            <input value={codigoBusqueda} onChange={(e) => setCodigoBusqueda(e.target.value)} className={inputCls} placeholder="Escaneá o escribí un código…" />
          </div>
          <button type="button" onClick={buscarCodigo} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted"><Search size={16} /> Buscar</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div><label className="text-xs text-muted-foreground">N° de inventario *</label><input value={f.numeroInventario} onChange={(e) => setF({ ...f, numeroInventario: e.target.value })} className={inputCls} /></div>
        <div><label className="text-xs text-muted-foreground">Nombre / especificación *</label><input value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} className={inputCls} /></div>
        <div>
          <label className="text-xs text-muted-foreground">Categoría *</label>
          <select value={f.categoriaId} onChange={(e) => setF({ ...f, categoriaId: e.target.value })} className={inputCls}>
            <option value="">—</option>
            {categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre} ({c.grupo})</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Fabricante</label>
          <select value={f.fabricanteId} onChange={(e) => setF({ ...f, fabricanteId: e.target.value })} className={inputCls}>
            <option value="">—</option>
            {fabricantes.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Estado</label>
          <select value={f.estadoId} onChange={(e) => setF({ ...f, estadoId: e.target.value })} className={inputCls}>
            <option value="">Disponible (default)</option>
            {estados.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
          </select>
        </div>
        <div><label className="text-xs text-muted-foreground">Fecha de alta *</label><input type="date" value={f.fechaAlta} onChange={(e) => setF({ ...f, fechaAlta: e.target.value })} className={inputCls} /></div>
        <div><label className="text-xs text-muted-foreground">Año</label><input type="number" value={f.anio} onChange={(e) => setF({ ...f, anio: e.target.value })} className={inputCls} /></div>
        <div><label className="text-xs text-muted-foreground">N° de serie {serieObligatoria && <span className="text-error">*</span>}</label><input value={f.numeroSerie} onChange={(e) => setF({ ...f, numeroSerie: e.target.value })} className={inputCls} /></div>
        <div><label className="text-xs text-muted-foreground">Código de barras</label><input value={f.codigoBarras} onChange={(e) => setF({ ...f, codigoBarras: e.target.value })} className={inputCls} /></div>
        <div><label className="text-xs text-muted-foreground">Código QR</label><input value={f.codigoQR} onChange={(e) => setF({ ...f, codigoQR: e.target.value })} className={inputCls} /></div>
        <div className="sm:col-span-2"><label className="text-xs text-muted-foreground">Imagen referencial (URL)</label><input value={f.imagenReferencial} onChange={(e) => setF({ ...f, imagenReferencial: e.target.value })} className={inputCls} /></div>
        <div className="sm:col-span-2"><label className="text-xs text-muted-foreground">Observaciones</label><textarea value={f.observaciones} onChange={(e) => setF({ ...f, observaciones: e.target.value })} className={inputCls} rows={2} /></div>
      </div>

      <div className="border-t border-border pt-4">
        <label className="text-sm font-semibold text-foreground">Responsable</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2">
          <select value={f.responsableTipo} onChange={(e) => setF({ ...f, responsableTipo: e.target.value, responsableEmpleadoId: '', responsableOficinaId: '', responsableDepartamentoId: '' })} className={inputCls}>
            {RESP_TIPOS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          {f.responsableTipo === 'empleado' && (
            <select value={f.responsableEmpleadoId} onChange={(e) => setF({ ...f, responsableEmpleadoId: e.target.value })} className={inputCls}>
              <option value="">— Elegí empleado —</option>
              {empleados.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          )}
          {f.responsableTipo === 'oficina' && (
            <select value={f.responsableOficinaId} onChange={(e) => setF({ ...f, responsableOficinaId: e.target.value })} className={inputCls}>
              <option value="">— Elegí oficina —</option>
              {oficinas.map((o) => <option key={o.id} value={o.id}>{o.nombre}</option>)}
            </select>
          )}
          {f.responsableTipo === 'departamento' && (
            <select value={f.responsableDepartamentoId} onChange={(e) => setF({ ...f, responsableDepartamentoId: e.target.value })} className={inputCls}>
              <option value="">— Elegí departamento —</option>
              {depts.map((d) => <option key={d.id} value={d.id}>{d.nombre}</option>)}
            </select>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        <button onClick={onCancelar} className="px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted">Cancelar</button>
        <button onClick={guardar} disabled={guardando} className="px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">{guardando ? 'Guardando…' : 'Guardar'}</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "ActivoForm"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/ActivosInventario/ActivoForm.tsx
git commit -m "feat: agregar formulario de alta y edicion de activos"
```

---

## Task 6: Frontend — pantalla `ActivosInventario/Screen.tsx`

**Files:**
- Create: `src/app/screens/ActivosInventario/Screen.tsx`

**Interfaces:**
- Consumes: `apiClient`, `ActivoForm` (Task 5), `CodigoLabels` (Task 4), tipos `ActivoListItem`/`ActivoDetalle`/`ActivoCategoria`/`ActivoEstado`.
- Produces: componente `ActivosInventario` (default export, sin props).

- [ ] **Step 1: Crear la pantalla**

```tsx
'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { ActivoForm } from '@/app/Componentes/ActivosInventario/ActivoForm';
import { CodigoLabels } from '@/app/Componentes/ActivosInventario/CodigoLabels';
import type { ActivoListItem, ActivoDetalle, ActivoCategoria, ActivoEstado } from '@/app/Interfas/Interfaces';
import { Plus, ArrowLeft, Pencil } from 'lucide-react';

type Modo = 'lista' | 'ficha' | 'form';

export default function ActivosInventario() {
  const [modo, setModo] = useState<Modo>('lista');
  const [rows, setRows] = useState<ActivoListItem[]>([]);
  const [seleccionado, setSeleccionado] = useState<ActivoDetalle | null>(null);
  const [editando, setEditando] = useState<ActivoDetalle | null>(null);
  const [categorias, setCategorias] = useState<ActivoCategoria[]>([]);
  const [estados, setEstados] = useState<ActivoEstado[]>([]);
  const [filtros, setFiltros] = useState({ categoriaId: '', grupo: '', estadoId: '', texto: '' });
  const [cambioEstado, setCambioEstado] = useState<{ estadoId: string; observacion: string } | null>(null);

  const cargar = useCallback(() => {
    const params = new URLSearchParams();
    if (filtros.categoriaId) params.set('categoriaId', filtros.categoriaId);
    if (filtros.grupo) params.set('grupo', filtros.grupo);
    if (filtros.estadoId) params.set('estadoId', filtros.estadoId);
    if (filtros.texto.trim()) params.set('texto', filtros.texto.trim());
    const qs = params.toString();
    apiClient.get<{ activos: ActivoListItem[] }>(`/activos${qs ? `?${qs}` : ''}`)
      .then((r) => setRows(r.activos || []))
      .catch((e) => console.error('Error al listar activos:', e));
  }, [filtros]);

  useEffect(() => {
    apiClient.get<{ categorias: ActivoCategoria[] }>('/activos/config/categorias').then((r) => setCategorias(r.categorias || [])).catch(() => {});
    apiClient.get<{ estados: ActivoEstado[] }>('/activos/config/estados').then((r) => setEstados(r.estados || [])).catch(() => {});
  }, []);

  useEffect(() => { if (modo === 'lista') cargar(); }, [modo, cargar]);

  const abrirFicha = async (id: number) => {
    try {
      const det = await apiClient.get<ActivoDetalle>(`/activos/${id}`);
      setSeleccionado(det);
      setModo('ficha');
    } catch (e) { console.error(e); }
  };

  const guardarEstado = async () => {
    if (!seleccionado || !cambioEstado) return;
    try {
      await apiClient.patch(`/activos/${seleccionado.id}/estado`, {
        estadoId: Number(cambioEstado.estadoId),
        observacion: cambioEstado.observacion || null,
      });
      setCambioEstado(null);
      const det = await apiClient.get<ActivoDetalle>(`/activos/${seleccionado.id}`);
      setSeleccionado(det);
    } catch (e) { alert((e as Error).message); }
  };

  const inputCls = 'px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm';

  if (modo === 'form') {
    return (
      <div className="bg-background min-h-screen p-4 sm:p-8">
        <div className="max-w-4xl mx-auto space-y-4">
          <button onClick={() => setModo(editando ? 'ficha' : 'lista')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft size={16} /> Volver</button>
          <ActivoForm
            activo={editando}
            onCancelar={() => setModo(editando ? 'ficha' : 'lista')}
            onGuardado={() => { setModo('lista'); setEditando(null); }}
          />
        </div>
      </div>
    );
  }

  if (modo === 'ficha' && seleccionado) {
    const a = seleccionado;
    const dato = (label: string, valor: React.ReactNode) => (
      <div><p className="text-xs text-muted-foreground">{label}</p><p className="text-sm text-foreground">{valor ?? '—'}</p></div>
    );
    return (
      <div className="bg-background min-h-screen p-4 sm:p-8">
        <div className="max-w-4xl mx-auto space-y-6">
          <button onClick={() => setModo('lista')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft size={16} /> Volver al inventario</button>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="font-heading text-2xl font-bold text-foreground">{a.nombre}</h1>
              <p className="text-muted-foreground">{a.numeroInventario} · {a.categoriaNombre} ({a.grupo})</p>
            </div>
            <div className="flex gap-2">
              <button onClick={() => { setEditando(a); setModo('form'); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><Pencil size={16} /> Editar</button>
              <button onClick={() => setCambioEstado({ estadoId: String(a.estadoId), observacion: '' })} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90">Cambiar estado</button>
            </div>
          </div>

          <div className="bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6 grid grid-cols-2 sm:grid-cols-3 gap-4">
            {dato('Estado', a.estadoNombre)}
            {dato('Fabricante', a.fabricanteNombre)}
            {dato('Fecha de alta', a.fechaAlta ? new Date(a.fechaAlta).toLocaleDateString('es-AR') : '—')}
            {dato('Año', a.anio)}
            {dato('N° de serie', a.numeroSerie)}
            {dato('Responsable', a.responsableNombre ? `${a.responsableNombre} (${a.responsableTipo})` : 'Sin asignar')}
            {dato('Código de barras', a.codigoBarras)}
            {dato('Código QR', a.codigoQR)}
            <div className="col-span-2 sm:col-span-3">{dato('Observaciones', a.observaciones)}</div>
          </div>

          {a.imagenReferencial && (
            <img src={a.imagenReferencial} alt={a.nombre} className="max-w-xs rounded-xl border border-border" />
          )}

          <CodigoLabels valorQR={a.codigoQR || a.numeroInventario} valorBarras={a.codigoBarras || a.numeroInventario} />
        </div>

        {cambioEstado && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setCambioEstado(null)}>
            <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-heading text-lg font-bold text-foreground">Cambiar estado</h3>
              <div>
                <label className="text-xs text-muted-foreground">Nuevo estado</label>
                <select value={cambioEstado.estadoId} onChange={(e) => setCambioEstado({ ...cambioEstado, estadoId: e.target.value })} className={`w-full mt-1 ${inputCls}`}>
                  {estados.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Motivo / observación</label>
                <textarea value={cambioEstado.observacion} onChange={(e) => setCambioEstado({ ...cambioEstado, observacion: e.target.value })} className={`w-full mt-1 ${inputCls}`} rows={2} />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setCambioEstado(null)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
                <button onClick={guardarEstado} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90">Guardar</button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen p-4 sm:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground">Inventario</h1>
            <p className="text-muted-foreground">Equipos, componentes, accesorios y mobiliario.</p>
          </div>
          <button onClick={() => { setEditando(null); setModo('form'); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90"><Plus size={18} /> Nuevo activo</button>
        </header>

        <div className="bg-card border border-border rounded-xl p-3 shadow-soft flex flex-wrap items-center gap-3">
          <input value={filtros.texto} onChange={(e) => setFiltros({ ...filtros, texto: e.target.value })} placeholder="Buscar por nombre/inventario/serie…" className={`flex-1 min-w-[200px] ${inputCls}`} />
          <select value={filtros.categoriaId} onChange={(e) => setFiltros({ ...filtros, categoriaId: e.target.value })} className={inputCls}>
            <option value="">Todas las categorías</option>
            {categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
          <select value={filtros.grupo} onChange={(e) => setFiltros({ ...filtros, grupo: e.target.value })} className={inputCls}>
            <option value="">Todos los grupos</option>
            {['Equipo', 'Componente', 'Accesorio', 'Mobiliario'].map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
          <select value={filtros.estadoId} onChange={(e) => setFiltros({ ...filtros, estadoId: e.target.value })} className={inputCls}>
            <option value="">Todos los estados</option>
            {estados.map((x) => <option key={x.id} value={x.id}>{x.nombre}</option>)}
          </select>
        </div>

        <div className="bg-card border border-border rounded-xl shadow-soft overflow-x-auto">
          {rows.length === 0 ? (
            <p className="p-8 text-center text-muted-foreground">No hay activos con esos filtros.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-background text-muted-foreground">
                <tr>
                  <th className="text-left font-medium px-4 py-3">N° inventario</th>
                  <th className="text-left font-medium px-4 py-3">Nombre</th>
                  <th className="text-left font-medium px-4 py-3">Categoría</th>
                  <th className="text-left font-medium px-4 py-3">Estado</th>
                  <th className="text-left font-medium px-4 py-3">Responsable</th>
                  <th className="text-left font-medium px-4 py-3">Fecha alta</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} onClick={() => abrirFicha(r.id)} className="border-t border-border hover:bg-muted cursor-pointer">
                    <td className="px-4 py-3 text-foreground">{r.numeroInventario}</td>
                    <td className="px-4 py-3 text-foreground">{r.nombre}</td>
                    <td className="px-4 py-3 text-muted-foreground">{r.categoriaNombre}</td>
                    <td className="px-4 py-3 text-muted-foreground">{r.estadoNombre}</td>
                    <td className="px-4 py-3 text-muted-foreground">{r.responsableNombre ?? '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">{r.fechaAlta ? new Date(r.fechaAlta).toLocaleDateString('es-AR') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "ActivosInventario/Screen"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: agregar pantalla de inventario de activos"
```

---

## Task 7: Frontend — ruteo y RBAC

**Files:**
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `ActivosInventario` (Task 6).
- Produces: página `"activos-inventario"` en la sección "Activos", solo ADMIN.

- [ ] **Step 1: `rbac.ts` — entrada en `PAGE_CONFIG`**

Agregar a `PAGE_CONFIG` (por ejemplo justo después de la entrada `activos-config`), en la misma sección `"Activos"`:
```typescript
  {
    id: "activos-inventario",
    label: "Inventario",
    icon: "Package",
    section: "Activos",
    visibleFor: [ROLE_ID.ADMIN],
    accessibleFor: [ROLE_ID.ADMIN],
  },
```
(La sección `"Activos"` y su presencia en `SECTION_ORDER` ya existen desde el subsistema 1 — no hace falta tocarlos.)

- [ ] **Step 2: `AppSidebar.tsx` — ícono `Package`**

Agregar `Package` al import de `lucide-react` y a `ICON_MAP` (mismo patrón que `Boxes`). Leé el archivo para ubicar las dos posiciones.

- [ ] **Step 3: `page.tsx` — case**

Agregar el import:
```tsx
import ActivosInventario from '@/app/screens/ActivosInventario/Screen';
```
Y el case (por ejemplo después de `case 'activos-config'`):
```tsx
      case 'activos-inventario':
        return <ActivosInventario />;
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "rbac|AppSidebar|page\.tsx"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/util/rbac.ts src/app/Componentes/Shell/AppSidebar.tsx src/app/page.tsx
git commit -m "feat: enganchar el inventario de activos en el ruteo"
```

---

## Task 8: Verificación manual (sin commits)

Requiere backend + DB + browser reales; no automatizable.

- [ ] Backend compila (`py -m py_compile app/routes/activos.py app/database/activos.py app/main.py`).
- [ ] Primer arranque: `Activo` y `ActivoHistorial` se crean. Crear un activo → aparece en la lista, estado default "Disponible", una fila `creacion` en `ActivoHistorial`.
- [ ] Crear un activo de una categoría con `requiereSerie=1` sin nº de serie → 400; con serie → OK.
- [ ] Nº inventario duplicado (entre vigentes) → 400.
- [ ] Editar cambiando estado y responsable → filas de historial `cambio_estado` y `cambio_responsable` con valores legibles.
- [ ] `PATCH .../estado` desde el diálogo con motivo → historial `cambio_estado` con la observación; la ficha refleja el nuevo estado.
- [ ] Buscar por código en el alta: código existente → ofrece precargar; inexistente → lo usa como código de barras.
- [ ] Ficha: QR y código de barras se generan y se ven; imagen referencial (URL) se muestra si está.
- [ ] Responsable: asignar a empleado / oficina / departamento y ver el nombre resuelto en lista y ficha.
- [ ] Un no-ADMIN no ve "Inventario"; por API puede `GET` pero `POST/PUT/PATCH/DELETE` → 403.
- [ ] Dark mode y responsive.

---

## Notas para el ejecutor

- **Sin pytest/jest**: la "prueba" de cada task es la compilación + verificación manual. No agregar frameworks de test.
- **Orden**: Task 1→2 (backend) independientes de 3→7 (frontend). En frontend: Task 3 (deps+tipos) primero; Task 4 (CodigoLabels) y Task 5 (ActivoForm) antes de Task 6 (Screen que los usa); Task 7 (ruteo) después de Task 6.
- **El archivo `UiRRHH.tsx` y `prisma/schema.prisma`** tienen cambios locales no relacionados en el working tree del repo RRHH: NO incluirlos en ningún commit de este plan.
