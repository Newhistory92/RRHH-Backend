# PCs compuestas + componentes trazables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir componer una PC (un `Activo` con categoría "PC") a partir de componentes (otros `Activo` de categorías montables), con instalar/quitar/reemplazar auditado, y autocompletar componentes desde el catálogo `PCParts` ya poblado en la DB.

**Architecture:** Extiende el módulo de datos y el router de S2 (ya mergeados) con una columna `Activo.pcPadreId` (composición) y un flag `ActivoCategoria.puedeAlbergarComponentes`; nuevos endpoints de lectura/escritura de componentes bajo el prefijo `/activos`; toda mutación escribe en `ActivoHistorial` (auditoría de S2). El frontend agrega, dentro de la pantalla "Inventario" de S2, una sección de componentes en la ficha de una PC y un autocompletado opcional desde `PCParts` en el formulario de alta.

**Tech Stack:** FastAPI + SQLAlchemy `text()` (SQL Server / pyodbc); Next.js + React + PrimeReact + Tailwind (tokens semánticos "Orgánico Cálido"); `PCParts` (tabla de solo lectura, 71.009 filas ya cargadas).

## Global Constraints

- SQL 100% parametrizado vía SQLAlchemy `text()` con parámetros bindeados — nunca interpolación de entrada de usuario.
- Columnas nuevas idempotentes con el patrón `IF COL_LENGTH('Tabla','col') IS NULL ALTER TABLE ... ADD ...` (mismo estilo que `departments.py`).
- El `ALTER TABLE ADD col` y cualquier `UPDATE` que referencie esa columna nueva **deben ir en llamadas `db.execute` separadas** (batches separados): SQL Server compila el batch completo antes de ejecutar y falla con "Invalid column name" si el `UPDATE` referencia una columna creada en el mismo batch.
- RBAC: lecturas (`GET`) con `require_any_auth`; escrituras (`POST`/`DELETE`) con `require_roles(ROLE_ADMIN)` (alias `require_admin` ya definido en `app/routes/activos.py`).
- Cada mutación (instalar/quitar/reemplazar) escribe en `ActivoHistorial` vía `registrar_historial(...)` **dentro de la misma transacción** que el `UPDATE`, con un único `db.commit()` al final del endpoint. `registrar_historial` NO commitea.
- Rutas estáticas de un solo segmento (`/componentes-libres`, `/pcparts`) DEBEN declararse **antes** de `GET /{activo_id}` en `app/routes/activos.py`, o el path converter de `activo_id: int` las captura y devuelve 422. (Igual que `/buscar` ya está antes de `/{activo_id}`.)
- `PCParts` es **solo lectura**: nunca se hace `INSERT`/`UPDATE`/`DELETE`/`ALTER` sobre ella.
- `GET /activos/pcparts` **siempre** con límite (`TOP (:limit)`), nunca devuelve una categoría entera del dataset.
- Estilo frontend: solo tokens semánticos Tailwind (`bg-card`, `border-border`, `text-foreground`, `text-muted-foreground`, `text-error`, `bg-primary`, etc.), nunca hex crudo. Los diálogos usan el overlay `fixed inset-0 bg-black/50` (mismo patrón que "Cambiar estado" de S2).
- **NO tocar** `prisma/schema.prisma` ni `src/app/util/UiRRHH.tsx` en el repo RRHH (modificaciones locales del usuario, ajenas a este trabajo).
- Backend en repo `Backend_RRHH`, rama `activos-pcs-componentes`. Frontend en repo `RRHH`, rama `activos-pcs-componentes`. No hay suite automatizada: la verificación es compilación + ejecución en vivo de solo lectura contra la DB real (y `tsc --noEmit` en frontend). No levantar servidores localhost (pedido explícito del usuario).

---

### Task 1: Backend — módulo de datos (columnas, mapeo, consultas de componentes)

**Files:**
- Modify: `app/database/activos.py` (S2, ya mergeado — se extiende)

**Interfaces:**
- Consumes: nada nuevo — usa las tablas `Activo`, `ActivoCategoria`, `PCParts` (ya existentes en la DB).
- Produces (lo que Task 2 importará y llamará):
  - `ensure_columns(db: Session) -> None` — agrega `Activo.pcPadreId` y `ActivoCategoria.puedeAlbergarComponentes` idempotentemente y marca la categoría "PC" con el flag; **llamada al final de `ensure_tables`**, así todos los endpoints de S2 la ejecutan automáticamente.
  - `MAPEO_PCPARTS: dict[str, str]` — nombre de `ActivoCategoria` → `PCParts.category`.
  - `listar_componentes_de(db, pc_id: int) -> list[dict]` — componentes instalados en esa PC.
  - `componentes_libres(db, categoria_id: Optional[int] = None) -> list[dict]` — componentes montables sin PC padre.
  - `buscar_pcparts(db, pcparts_category: str, texto: str, limit: int = 20) -> list[dict]` — filas de `PCParts` (id, category, name, image, specs).
  - `_fila_a_dict` ahora incluye además `pcPadreId`, `pcPadreNombre`, `puedeAlbergarComponentes`.

- [ ] **Step 1: Agregar `MAPEO_PCPARTS` a nivel de módulo**

Insertar debajo de la línea `RESPONSABLE_TIPOS = {"empleado", "oficina", "departamento"}` (línea 14):

```python
# Mapeo de nombre de ActivoCategoria (S1) -> category del catalogo PCParts (dataset).
# Las categorias sin entrada aqui simplemente no ofrecen autocompletado.
MAPEO_PCPARTS = {
    "CPU": "cpu",
    "Memoria RAM": "memory",
    "Placas Base": "motherboard",
    "Tarjetas de Video": "video-card",
    "Almacenamiento": "internal-hard-drive",
    "Fuentes de Alimentación": "power-supply",
    "Disipadores CPU": "cpu-cooler",
    "Gabinetes": "case",
    "Unidades Ópticas": "optical-drive",
    "Tarjetas de Sonido": "sound-card",
    "Sistemas Operativos": "os",
    "Adaptadores de Red Cableados": "wired-network-card",
    "Adaptadores de Red Inalámbricos": "wireless-network-card",
    "Monitor": "monitor",
    "Almacenamiento Externo": "external-hard-drive",
    "UPS": "ups",
}
```

- [ ] **Step 2: Agregar `ensure_columns` y llamarla desde `ensure_tables`**

Reemplazar la función `ensure_tables` actual (líneas 65-69):

```python
def ensure_tables(db: Session) -> None:
    """Crea Activo y ActivoHistorial si no existen (idempotente)."""
    db.execute(text(CREATE_ACTIVO_SQL))
    db.execute(text(CREATE_HISTORIAL_SQL))
    db.commit()
```

por:

```python
def ensure_columns(db: Session) -> None:
    """Agrega pcPadreId a Activo y puedeAlbergarComponentes a ActivoCategoria
    (idempotente), y marca la categoria 'PC' con el flag. El ALTER y el UPDATE
    van en batches separados: SQL Server compila el batch completo antes de
    ejecutarlo y fallaria con 'Invalid column name' si el UPDATE referenciara
    la columna recien creada en el mismo batch."""
    db.execute(text("IF COL_LENGTH('Activo','pcPadreId') IS NULL ALTER TABLE Activo ADD pcPadreId INT NULL;"))
    db.execute(text("IF COL_LENGTH('ActivoCategoria','puedeAlbergarComponentes') IS NULL "
                    "ALTER TABLE ActivoCategoria ADD puedeAlbergarComponentes BIT NOT NULL DEFAULT 0;"))
    db.commit()
    db.execute(text("UPDATE ActivoCategoria SET puedeAlbergarComponentes = 1 "
                    "WHERE nombre = 'PC' AND puedeAlbergarComponentes = 0;"))
    db.commit()


def ensure_tables(db: Session) -> None:
    """Crea Activo y ActivoHistorial si no existen (idempotente) y asegura las
    columnas de composicion (S3), asi todo endpoint que ya llamaba ensure_tables
    obtiene tambien las columnas nuevas antes de usar _SELECT_ACTIVO."""
    db.execute(text(CREATE_ACTIVO_SQL))
    db.execute(text(CREATE_HISTORIAL_SQL))
    db.commit()
    ensure_columns(db)
```

- [ ] **Step 3: Extender `_SELECT_ACTIVO` con pcPadre y el flag de categoría**

En el bloque `_SELECT_ACTIVO` (líneas 94-142), agregar tres cosas. Primero, en la lista de columnas del `SELECT`, después de la línea `END AS efectivoOficinaNombre` (línea 130) agregar una coma y las columnas nuevas:

Reemplazar:
```python
        CASE a.responsableTipo
            WHEN 'empleado' THEN reOffice.nombre
            WHEN 'oficina'  THEN ro.nombre
            ELSE NULL
        END AS efectivoOficinaNombre
    FROM Activo a
```
por:
```python
        CASE a.responsableTipo
            WHEN 'empleado' THEN reOffice.nombre
            WHEN 'oficina'  THEN ro.nombre
            ELSE NULL
        END AS efectivoOficinaNombre,
        a.pcPadreId,
        pcp.nombre AS pcPadreNombre,
        c.puedeAlbergarComponentes AS puedeAlbergarComponentes
    FROM Activo a
```

Y en la lista de JOINs, después de la línea `LEFT  JOIN Office reOffice   ON re.officeId = reOffice.id` (línea 140) agregar el self-JOIN a Activo:

Reemplazar:
```python
    LEFT  JOIN Office reOffice   ON re.officeId = reOffice.id
    WHERE a.activo = 1
```
por:
```python
    LEFT  JOIN Office reOffice   ON re.officeId = reOffice.id
    LEFT  JOIN Activo pcp        ON a.pcPadreId = pcp.id
    WHERE a.activo = 1
```

- [ ] **Step 4: Agregar las 3 claves nuevas a `_fila_a_dict`**

En `_fila_a_dict` (líneas 145-164), agregar las 3 claves nuevas junto a las de `efectivoOficinaNombre`. Reemplazar:

```python
        "efectivoOficinaId": r["efectivoOficinaId"],
        "efectivoOficinaNombre": r["efectivoOficinaNombre"],
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
```
por:
```python
        "efectivoOficinaId": r["efectivoOficinaId"],
        "efectivoOficinaNombre": r["efectivoOficinaNombre"],
        "pcPadreId": r["pcPadreId"],
        "pcPadreNombre": r["pcPadreNombre"],
        "puedeAlbergarComponentes": bool(r["puedeAlbergarComponentes"]),
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
```

- [ ] **Step 5: Agregar las tres funciones de consulta de componentes**

Al final del archivo (después de `buscar_por_codigo`, línea 217), agregar:

```python
def listar_componentes_de(db: Session, pc_id: int) -> list[dict]:
    """Componentes vigentes instalados en la PC dada (pcPadreId = pc_id)."""
    rows = db.execute(text(_SELECT_ACTIVO + " AND a.pcPadreId = :pcId ORDER BY c.nombre, a.nombre"),
                      {"pcId": pc_id}).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def componentes_libres(db: Session, categoria_id: Optional[int] = None) -> list[dict]:
    """Activos vigentes montables en PC (categoria montableEnPC=1) que no estan
    instalados en ninguna PC (pcPadreId IS NULL). Filtro opcional por categoria."""
    query = _SELECT_ACTIVO + " AND a.pcPadreId IS NULL AND c.montableEnPC = 1"
    params = {}
    if categoria_id:
        query += " AND a.categoriaId = :catId"
        params["catId"] = categoria_id
    query += " ORDER BY c.nombre, a.nombre"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]


def buscar_pcparts(db: Session, pcparts_category: str, texto: str, limit: int = 20) -> list[dict]:
    """Filas del catalogo PCParts (solo lectura) filtradas por category exacta y
    texto opcional en el nombre. Siempre acotado por TOP."""
    rows = db.execute(text("""
        SELECT TOP (:limit) id, category, name, image, specs
        FROM PCParts
        WHERE category = :cat AND (:texto = '' OR name LIKE :q)
        ORDER BY name
    """), {"limit": limit, "cat": pcparts_category, "texto": texto, "q": f"%{texto}%"}).mappings().all()
    return [{"id": r["id"], "category": r["category"], "name": r["name"],
             "image": r["image"], "specs": r["specs"]} for r in rows]
```

- [ ] **Step 6: Compilar**

Run: `py -m py_compile app/database/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 7: Verificar en vivo (solo lectura) contra la DB real**

Ejecutar un script throwaway (o `py -c "..."`) que use `SessionLocal` (ver `app/routes/activos.py` para el patrón de sesión) y confirme:
- `ensure_columns(db)` corre sin error; `SELECT COL_LENGTH('Activo','pcPadreId')` y `SELECT COL_LENGTH('ActivoCategoria','puedeAlbergarComponentes')` devuelven no-NULL; `SELECT puedeAlbergarComponentes FROM ActivoCategoria WHERE nombre='PC'` devuelve 1.
- `buscar_pcparts(db, 'memory', '', 5)` devuelve 5 filas con las claves id/category/name/image/specs.
- `buscar_pcparts(db, 'cpu', 'Ryzen', 5)` devuelve filas cuyo `name` contiene "Ryzen" (o lista vacía si no hay match — no debe romper).
- `obtener_activo(db, <id de un activo real>)` sigue funcionando e incluye ahora las claves `pcPadreId`, `pcPadreNombre`, `puedeAlbergarComponentes`.
- `componentes_libres(db)` corre sin error (probablemente lista vacía si no hay componentes cargados aún — no bloqueante).

Correr `ensure_columns` dos veces seguidas para confirmar idempotencia (no re-agrega columnas ni falla). No hacer ningún INSERT/UPDATE de prueba sobre datos reales.

- [ ] **Step 8: Commit**

```bash
git add app/database/activos.py
git commit -m "feat: agregar composicion PC-componente y consultas de PCParts (subsistema 3)"
```

---

### Task 2: Backend — endpoints de componentes en el router

**Files:**
- Modify: `app/routes/activos.py` (S2, ya mergeado — se extiende)

**Interfaces:**
- Consumes (de Task 1): `ensure_tables` (ahora también asegura columnas), `MAPEO_PCPARTS`, `listar_componentes_de(db, pc_id)`, `componentes_libres(db, categoria_id=None)`, `buscar_pcparts(db, cat, texto)`, `obtener_activo(db, id)` (ahora devuelve `pcPadreId`/`puedeAlbergarComponentes`), `registrar_historial`.
- Produces (endpoints que consume el frontend, Tasks 4-5):
  - `GET /activos/componentes-libres?categoriaId=` → `{componentes: [...]}`
  - `GET /activos/pcparts?categoria=&texto=` → `{resultados: [...]}`
  - `GET /activos/{id}/componentes` → `{componentes: [...]}`
  - `POST /activos/{id}/componentes` body `{componenteId}` → `{message}`
  - `DELETE /activos/{pcId}/componentes/{componenteId}` → `{message}`
  - `POST /activos/{id}/componentes/reemplazar` body `{saleComponenteId, entraComponenteId, observacion}` → `{message}`

- [ ] **Step 1: Ampliar el import del módulo de datos**

Reemplazar el bloque de import (líneas 14-17):

```python
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
)
```
por:
```python
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
    MAPEO_PCPARTS, listar_componentes_de, componentes_libres, buscar_pcparts,
)
```

- [ ] **Step 2: Agregar los helpers de validación y las mutaciones de composición**

Al final del archivo (después de `_nombre_responsable`, línea 263), agregar:

```python
# ─── Composicion PC / componentes (subsistema 3) ─────────────────────────────
def _validar_es_pc(db: Session, activo_id: int) -> dict:
    """Devuelve el activo si existe, esta vigente y su categoria puede alojar
    componentes. 404 si no existe, 400 si no es una PC."""
    pc = obtener_activo(db, activo_id)
    if not pc:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    if not pc["puedeAlbergarComponentes"]:
        raise HTTPException(status_code=400, detail="Este activo no puede alojar componentes (no es una PC)")
    return pc


def _validar_componente_instalable(db: Session, componente_id, pc_id: int) -> dict:
    """Devuelve el componente si puede instalarse en pc_id. 404/400 si no."""
    if not componente_id:
        raise HTTPException(status_code=400, detail="Falta el id del componente")
    if componente_id == pc_id:
        raise HTTPException(status_code=400, detail="Un activo no puede instalarse en si mismo")
    comp = obtener_activo(db, componente_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Componente no encontrado")
    if comp["puedeAlbergarComponentes"]:
        raise HTTPException(status_code=400, detail="No se puede instalar una PC dentro de otra")
    cat = db.execute(text("SELECT montableEnPC FROM ActivoCategoria WHERE id = :id"),
                     {"id": comp["categoriaId"]}).mappings().first()
    if not cat or not cat["montableEnPC"]:
        raise HTTPException(status_code=400, detail="La categoria de este componente no es montable en una PC")
    if comp["pcPadreId"] is not None:
        raise HTTPException(status_code=400, detail="El componente ya esta instalado en otra PC")
    return comp


def _instalar(db: Session, comp_id: int, pc_id: int, comp: dict, usuario) -> None:
    """Setea pcPadreId y registra historial en el componente y en la PC. NO commitea."""
    db.execute(text("UPDATE Activo SET pcPadreId = :pc, updatedAt = :now WHERE id = :id"),
               {"pc": pc_id, "now": datetime.utcnow(), "id": comp_id})
    registrar_historial(db, comp_id, "instalacion", "pcPadre", None, str(pc_id), usuario)
    registrar_historial(db, pc_id, "componente_agregado", "componente", None, comp["nombre"], usuario)


def _quitar(db: Session, comp_id: int, pc_id: int, comp: dict, usuario) -> None:
    """Pone pcPadreId a NULL y registra historial en el componente y en la PC. NO commitea."""
    db.execute(text("UPDATE Activo SET pcPadreId = NULL, updatedAt = :now WHERE id = :id"),
               {"now": datetime.utcnow(), "id": comp_id})
    registrar_historial(db, comp_id, "desinstalacion", "pcPadre", str(pc_id), None, usuario)
    registrar_historial(db, pc_id, "componente_quitado", "componente", comp["nombre"], None, usuario)
```

- [ ] **Step 3: Agregar los endpoints de LECTURA de componentes ANTES de `GET /{activo_id}`**

Ubicar en el archivo el endpoint `get_por_codigo` (`@router.get("/buscar", ...)`, líneas 112-118) y el `get_activo` (`@router.get("/{activo_id}", ...)`, líneas 121-127). Insertar los dos endpoints estáticos **entre** `get_por_codigo` y `get_activo` (para que queden declarados antes que `/{activo_id}` y no sean capturados por el path converter):

Reemplazar:
```python
@router.get("/{activo_id}", dependencies=[Depends(require_any_auth)])
def get_activo(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = obtener_activo(db, activo_id)
    if not activo:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return activo
```
por:
```python
@router.get("/componentes-libres", dependencies=[Depends(require_any_auth)])
def get_componentes_libres(categoriaId: Optional[int] = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"componentes": componentes_libres(db, categoriaId)}


@router.get("/pcparts", dependencies=[Depends(require_any_auth)])
def get_pcparts(categoria: str, texto: str = "", db: Session = Depends(get_db)):
    ensure_tables(db)
    pcparts_cat = MAPEO_PCPARTS.get(categoria)
    if not pcparts_cat:
        return {"resultados": []}
    return {"resultados": buscar_pcparts(db, pcparts_cat, texto)}


@router.get("/{activo_id}", dependencies=[Depends(require_any_auth)])
def get_activo(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    activo = obtener_activo(db, activo_id)
    if not activo:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return activo


@router.get("/{activo_id}/componentes", dependencies=[Depends(require_any_auth)])
def get_componentes(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"componentes": listar_componentes_de(db, activo_id)}
```

- [ ] **Step 4: Agregar los endpoints de ESCRITURA de componentes al final del archivo**

Después de los helpers `_instalar`/`_quitar` agregados en el Step 2 (al final del archivo), agregar:

```python
@router.post("/{activo_id}/componentes", dependencies=[Depends(require_admin)])
def instalar_componente(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    _validar_es_pc(db, activo_id)
    comp = _validar_componente_instalable(db, data.get("componenteId"), activo_id)
    _instalar(db, comp["id"], activo_id, comp, current_user.get("employeeId"))
    db.commit()
    return {"message": "Componente instalado"}


@router.delete("/{pc_id}/componentes/{componente_id}", dependencies=[Depends(require_admin)])
def quitar_componente(pc_id: int, componente_id: int, db: Session = Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    _validar_es_pc(db, pc_id)
    comp = obtener_activo(db, componente_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Componente no encontrado")
    if comp["pcPadreId"] != pc_id:
        raise HTTPException(status_code=400, detail="Ese componente no esta instalado en esta PC")
    _quitar(db, componente_id, pc_id, comp, current_user.get("employeeId"))
    db.commit()
    return {"message": "Componente quitado"}


@router.post("/{activo_id}/componentes/reemplazar", dependencies=[Depends(require_admin)])
def reemplazar_componente(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    _validar_es_pc(db, activo_id)
    sale_id = data.get("saleComponenteId")
    entra_id = data.get("entraComponenteId")
    observacion = data.get("observacion") or None
    sale = obtener_activo(db, sale_id) if sale_id else None
    if not sale:
        raise HTTPException(status_code=404, detail="El componente que sale no existe")
    if sale["pcPadreId"] != activo_id:
        raise HTTPException(status_code=400, detail="El componente que sale no esta instalado en esta PC")
    entra = _validar_componente_instalable(db, entra_id, activo_id)
    usuario = current_user.get("employeeId")
    _quitar(db, sale_id, activo_id, sale, usuario)
    _instalar(db, entra["id"], activo_id, entra, usuario)
    registrar_historial(db, activo_id, "reemplazo", "componente", str(sale_id), str(entra_id), usuario, observacion)
    db.commit()
    return {"message": "Componente reemplazado"}
```

- [ ] **Step 5: Compilar**

Run: `py -m py_compile app/routes/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 6: Verificar en vivo (solo lectura + escritura de prueba limpiada)**

Con `TestClient` o el patrón de verificación de S2 (crear registros de prueba y limpiarlos con soft-delete/`pcPadreId=NULL` al final, sin dejar basura activa), confirmar contra la DB real:
- `GET /activos/pcparts?categoria=Memoria RAM&texto=` devuelve `{resultados:[...]}` con hasta 20 filas de `memory`; `?categoria=Inexistente` devuelve `{resultados:[]}`.
- `GET /activos/componentes-libres` responde `{componentes:[...]}` sin error, y **no** aparece ninguna PC en la lista.
- `GET /activos/buscar?codigo=...` y `GET /activos/{id}` (rutas de S2) siguen funcionando — confirmar que `/componentes-libres` y `/pcparts` no rompieron el ruteo de `/{activo_id}`.
- Flujo de escritura (con una PC y dos componentes de prueba temporales, creados vía `POST /activos`): instalar un componente en la PC → `GET /activos/{pc}/componentes` lo muestra y su `GET /activos/{comp}` tiene `pcPadreId` = la PC; instalar el mismo de nuevo → 400; instalar la PC en sí misma / una PC en otra / un componente no-montable → 400; reemplazar (sale uno, entra otro) en una llamada → ambos quedan con el `pcPadreId` correcto y hay una fila `reemplazo` en `ActivoHistorial`; quitar → `pcPadreId` NULL. Confirmar filas de historial (`instalacion`/`componente_agregado`/`desinstalacion`/`componente_quitado`/`reemplazo`). Al terminar, dejar los activos de prueba soft-deleted (`activo=0`) y sin `pcPadreId`, sin basura activa.
- RBAC: sin token o con token no-ADMIN, los `POST`/`DELETE` devuelven 401/403.

Si no es posible correr el flujo de escritura con seguridad contra la DB compartida, hacer al menos la verificación de lectura y reportarlo como concern (no bloqueante), igual que en S2.

- [ ] **Step 7: Commit**

```bash
git add app/routes/activos.py
git commit -m "feat: agregar endpoints de instalar/quitar/reemplazar componentes y autocompletado PCParts (subsistema 3)"
```

---

### Task 3: Frontend — tipos

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts` (repo RRHH)

**Interfaces:**
- Consumes: la forma de `_fila_a_dict` extendida (Task 1) y el endpoint `/activos/pcparts` (Task 2).
- Produces: `ActivoListItem` con `pcPadreId`/`pcPadreNombre`/`puedeAlbergarComponentes`; nuevo tipo `PCPart`. (`ActivoDetalle = ActivoListItem` ya existe, no se toca.)

- [ ] **Step 1: Extender `ActivoListItem` y agregar `PCPart`**

En `src/app/Interfas/Interfaces.ts`, dentro de la interfaz `ActivoListItem`, agregar las 3 líneas nuevas junto a los campos `efectivoOficinaNombre` (antes de `createdAt`). Reemplazar:

```ts
  efectivoOficinaId: number | null;
  efectivoOficinaNombre: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

export type ActivoDetalle = ActivoListItem;
```
por:
```ts
  efectivoOficinaId: number | null;
  efectivoOficinaNombre: string | null;
  pcPadreId: number | null;
  pcPadreNombre: string | null;
  puedeAlbergarComponentes: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

export type ActivoDetalle = ActivoListItem;

export interface PCPart {
  id: number;
  category: string;
  name: string;
  image: string | null;
  specs: string | null;
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Interfaces.ts` (los errores preexistentes no relacionados de otros archivos, si aparecen, no cuentan).

- [ ] **Step 3: Confirmar archivos protegidos intactos y commit**

Verificar con `git status` que solo `src/app/Interfas/Interfaces.ts` está modificado por vos y que `prisma/schema.prisma`/`src/app/util/UiRRHH.tsx` no están en tu stage.

```bash
git add src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar tipos de composicion PC y PCPart (subsistema 3)"
```

---

### Task 4: Frontend — autocompletado desde PCParts en el formulario

**Files:**
- Modify: `src/app/Componentes/ActivosInventario/ActivoForm.tsx` (S2, repo RRHH)

**Interfaces:**
- Consumes: `GET /activos/pcparts?categoria=&texto=` (Task 2) → `{resultados: PCPart[]}`; el tipo `PCPart` (Task 3); `categoriaSel.montableEnPC` y `categoriaSel.nombre` (ya disponibles en el componente).
- Produces: nada para otras tasks.

- [ ] **Step 1: Importar `PCPart` y `Package` en `ActivoForm.tsx`**

Reemplazar la línea de import de tipos (línea 5) y la de iconos (línea 6):

```ts
import type { ActivoDetalle, ActivoCategoria, ActivoFabricante, ActivoEstado } from '@/app/Interfas/Interfaces';
import { Search } from 'lucide-react';
```
por:
```ts
import type { ActivoDetalle, ActivoCategoria, ActivoFabricante, ActivoEstado, PCPart } from '@/app/Interfas/Interfaces';
import { Search, Package } from 'lucide-react';
```

- [ ] **Step 2: Agregar estado y efecto de búsqueda con debounce**

En el cuerpo del componente, después de la línea `const [codigoBusqueda, setCodigoBusqueda] = useState('');` (línea 51), agregar:

```ts
  const [pcpartQuery, setPcpartQuery] = useState('');
  const [pcpartResults, setPcpartResults] = useState<PCPart[]>([]);
```

Luego, después del bloque `const categoriaSel = ...; const serieObligatoria = ...;` (líneas 61-62), agregar las primitivas derivadas y el efecto:

```ts
  const montablePC = categoriaSel?.montableEnPC ?? false;
  const nombreCategoria = categoriaSel?.nombre ?? '';

  useEffect(() => {
    if (!montablePC) { setPcpartResults([]); return; }
    const q = pcpartQuery.trim();
    const t = setTimeout(() => {
      apiClient.get<{ resultados: PCPart[] }>(`/activos/pcparts?categoria=${encodeURIComponent(nombreCategoria)}&texto=${encodeURIComponent(q)}`)
        .then((r) => setPcpartResults(r.resultados || []))
        .catch(() => setPcpartResults([]));
    }, 300);
    return () => clearTimeout(t);
  }, [pcpartQuery, montablePC, nombreCategoria]);

  const elegirPcpart = (p: PCPart) => {
    setF((s) => ({
      ...s,
      nombre: p.name,
      imagenReferencial: p.image || s.imagenReferencial,
      observaciones: p.specs || s.observaciones,
    }));
    setPcpartResults([]);
    setPcpartQuery('');
  };
```

- [ ] **Step 3: Renderizar el buscador de catálogo cuando la categoría es montable**

El bloque nuevo va entre el `</div>` que cierra el grid principal y el `<div>` de la sección Responsable. Anclar en la apertura única de la sección Responsable. Reemplazar:

```tsx
      <div className="border-t border-border pt-4">
        <label className="text-sm font-semibold text-foreground">Responsable</label>
```
por (el bloque del buscador seguido de la apertura intacta de Responsable):

```tsx
      {montablePC && (
        <div className="border-t border-border pt-4">
          <label className="text-sm font-semibold text-foreground flex items-center gap-2"><Package size={16} /> Buscar en catálogo (opcional)</label>
          <p className="text-xs text-muted-foreground mb-2">Elegí un modelo de referencia para precargar nombre, imagen y specs. Podés ignorarlo y cargar a mano.</p>
          <input
            value={pcpartQuery}
            onChange={(e) => setPcpartQuery(e.target.value)}
            className={inputCls}
            placeholder={`Buscar en el catálogo de ${nombreCategoria}…`}
          />
          {pcpartResults.length > 0 && (
            <div className="mt-2 max-h-60 overflow-y-auto border border-border rounded-lg divide-y divide-border">
              {pcpartResults.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => elegirPcpart(p)}
                  className="w-full text-left px-3 py-2 text-sm text-foreground hover:bg-muted flex items-center gap-3"
                >
                  {p.image && <img src={p.image} alt="" className="w-8 h-8 object-contain rounded bg-white shrink-0" />}
                  <span className="flex-1">{p.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="border-t border-border pt-4">
        <label className="text-sm font-semibold text-foreground">Responsable</label>
```

Nota: el `bg-white` en la miniatura es intencional (las imágenes de producto suelen tener fondo transparente y necesitan contraste), mismo criterio que `CodigoLabels` de S2 — no es violación del sistema de tokens. La apertura de la sección Responsable queda incluida al final del reemplazo para no duplicarla.

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `ActivoForm.tsx`.

- [ ] **Step 5: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/Componentes/ActivosInventario/ActivoForm.tsx
git commit -m "feat: agregar autocompletado desde PCParts al formulario de activos (subsistema 3)"
```

---

### Task 5: Frontend — sección de componentes en la ficha (agregar/quitar/reemplazar) e "Instalado en"

**Files:**
- Modify: `src/app/screens/ActivosInventario/Screen.tsx` (S2, repo RRHH)

**Interfaces:**
- Consumes: `GET /activos/{id}/componentes`, `GET /activos/componentes-libres`, `POST /activos/{id}/componentes`, `DELETE /activos/{pcId}/componentes/{compId}`, `POST /activos/{id}/componentes/reemplazar` (Task 2); `ActivoListItem`/`ActivoDetalle` con `pcPadreId`/`pcPadreNombre`/`puedeAlbergarComponentes` (Task 3).
- Produces: nada para otras tasks (última task de código).

- [ ] **Step 1: Importar iconos nuevos**

Reemplazar la línea de import de iconos (línea 8):

```ts
import { Plus, ArrowLeft, Pencil } from 'lucide-react';
```
por:
```ts
import { Plus, ArrowLeft, Pencil, Cpu, Trash2, Repeat } from 'lucide-react';
```

- [ ] **Step 2: Agregar estado de componentes y diálogos**

Después de la línea `const [cambioEstado, setCambioEstado] = useState<{ estadoId: string; observacion: string } | null>(null);` (línea 23), agregar:

```ts
  const [componentes, setComponentes] = useState<ActivoListItem[]>([]);
  const [libres, setLibres] = useState<ActivoListItem[]>([]);
  const [agregando, setAgregando] = useState(false);
  const [libreSel, setLibreSel] = useState('');
  const [reemplazando, setReemplazando] = useState(false);
  const [saleSel, setSaleSel] = useState('');
  const [entraSel, setEntraSel] = useState('');
  const [obsReemplazo, setObsReemplazo] = useState('');
```

- [ ] **Step 3: Cargar componentes al abrir la ficha de una PC**

Reemplazar la función `abrirFicha` (líneas 47-53):

```ts
  const abrirFicha = async (id: number) => {
    try {
      const det = await apiClient.get<ActivoDetalle>(`/activos/${id}`);
      setSeleccionado(det);
      setModo('ficha');
    } catch (e) { console.error(e); }
  };
```
por:
```ts
  const cargarComponentes = (pcId: number) => {
    apiClient.get<{ componentes: ActivoListItem[] }>(`/activos/${pcId}/componentes`)
      .then((r) => setComponentes(r.componentes || []))
      .catch(() => setComponentes([]));
  };

  const abrirFicha = async (id: number) => {
    try {
      const det = await apiClient.get<ActivoDetalle>(`/activos/${id}`);
      setSeleccionado(det);
      setModo('ficha');
      if (det.puedeAlbergarComponentes) cargarComponentes(id);
      else setComponentes([]);
    } catch (e) { console.error(e); }
  };
```

- [ ] **Step 4: Agregar los handlers de instalar/quitar/reemplazar**

Después de la función `guardarEstado` (que termina en la línea 66) y antes de `const inputCls = ...` (línea 68), agregar:

```ts
  const abrirAgregar = async () => {
    try {
      const r = await apiClient.get<{ componentes: ActivoListItem[] }>('/activos/componentes-libres');
      setLibres(r.componentes || []); setLibreSel(''); setAgregando(true);
    } catch (e) { alert((e as Error).message); }
  };

  const confirmarAgregar = async () => {
    if (!seleccionado || !libreSel) return;
    try {
      await apiClient.post(`/activos/${seleccionado.id}/componentes`, { componenteId: Number(libreSel) });
      setAgregando(false); cargarComponentes(seleccionado.id);
    } catch (e) { alert((e as Error).message); }
  };

  const quitarComponente = async (compId: number) => {
    if (!seleccionado) return;
    if (!confirm('¿Quitar este componente de la PC?')) return;
    try {
      await apiClient.delete(`/activos/${seleccionado.id}/componentes/${compId}`);
      cargarComponentes(seleccionado.id);
    } catch (e) { alert((e as Error).message); }
  };

  const abrirReemplazar = async () => {
    try {
      const r = await apiClient.get<{ componentes: ActivoListItem[] }>('/activos/componentes-libres');
      setLibres(r.componentes || []); setSaleSel(''); setEntraSel(''); setObsReemplazo(''); setReemplazando(true);
    } catch (e) { alert((e as Error).message); }
  };

  const confirmarReemplazar = async () => {
    if (!seleccionado || !saleSel || !entraSel) return;
    try {
      await apiClient.post(`/activos/${seleccionado.id}/componentes/reemplazar`, {
        saleComponenteId: Number(saleSel), entraComponenteId: Number(entraSel), observacion: obsReemplazo || null,
      });
      setReemplazando(false); cargarComponentes(seleccionado.id);
    } catch (e) { alert((e as Error).message); }
  };
```

- [ ] **Step 5: Insertar "Instalado en" y la sección "Componentes instalados" en la ficha**

En el bloque de la vista `ficha` (dentro de `if (modo === 'ficha' && seleccionado)`), insertar dos cosas después del `<CodigoLabels ... />` (línea 139) y antes del cierre `</div>` del contenedor `max-w-4xl` (línea 140).

Reemplazar:
```tsx
          <CodigoLabels valorQR={a.codigoQR || a.numeroInventario} valorBarras={a.codigoBarras || a.numeroInventario} />
        </div>
```
por:
```tsx
          <CodigoLabels valorQR={a.codigoQR || a.numeroInventario} valorBarras={a.codigoBarras || a.numeroInventario} />

          {a.pcPadreId && (
            <div className="bg-card border border-border rounded-xl shadow-soft p-4 flex items-center gap-2 text-sm">
              <Cpu size={16} className="text-muted-foreground" />
              <span className="text-muted-foreground">Instalado en:</span>
              <button onClick={() => abrirFicha(a.pcPadreId!)} className="text-primary hover:underline">{a.pcPadreNombre ?? `#${a.pcPadreId}`}</button>
            </div>
          )}

          {a.puedeAlbergarComponentes && (
            <div className="bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-heading text-lg font-bold text-foreground flex items-center gap-2"><Cpu size={18} /> Componentes instalados</h2>
                <div className="flex gap-2">
                  <button onClick={abrirAgregar} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90"><Plus size={16} /> Agregar</button>
                  <button onClick={abrirReemplazar} disabled={componentes.length === 0} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-border text-foreground text-sm hover:bg-muted disabled:opacity-50"><Repeat size={16} /> Reemplazar</button>
                </div>
              </div>
              {componentes.length === 0 ? (
                <p className="text-sm text-muted-foreground">Esta PC no tiene componentes instalados.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="text-left font-medium py-2">Componente</th>
                      <th className="text-left font-medium py-2">Categoría</th>
                      <th className="text-left font-medium py-2">N° serie</th>
                      <th className="text-left font-medium py-2">Estado</th>
                      <th className="py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {componentes.map((c) => (
                      <tr key={c.id} className="border-t border-border">
                        <td className="py-2"><button onClick={() => abrirFicha(c.id)} className="text-primary hover:underline">{c.nombre}</button></td>
                        <td className="py-2 text-muted-foreground">{c.categoriaNombre}</td>
                        <td className="py-2 text-muted-foreground">{c.numeroSerie ?? '—'}</td>
                        <td className="py-2 text-muted-foreground">{c.estadoNombre}</td>
                        <td className="py-2 text-right"><button onClick={() => quitarComponente(c.id)} className="inline-flex items-center gap-1 text-error hover:opacity-80 text-xs"><Trash2 size={14} /> Quitar</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
```

- [ ] **Step 6: Insertar los diálogos de "Agregar" y "Reemplazar"**

Los diálogos van dentro del mismo `return` de la vista `ficha`, junto al diálogo `{cambioEstado && (...)}` existente. Insertar después del cierre de ese bloque `)}` (línea 162) y antes del `</div>` que cierra el contenedor raíz de la ficha (línea 163).

Reemplazar:
```tsx
        )}
      </div>
    );
  }

  return (
```
por:
```tsx
        )}

        {agregando && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setAgregando(false)}>
            <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-heading text-lg font-bold text-foreground">Agregar componente</h3>
              <div>
                <label className="text-xs text-muted-foreground">Componente libre</label>
                <select value={libreSel} onChange={(e) => setLibreSel(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                  <option value="">— Elegí un componente —</option>
                  {libres.map((c) => <option key={c.id} value={c.id}>{c.nombre} ({c.categoriaNombre})</option>)}
                </select>
                {libres.length === 0 && <p className="text-xs text-muted-foreground mt-1">No hay componentes libres. Cargá uno desde "Nuevo activo".</p>}
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setAgregando(false)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
                <button onClick={confirmarAgregar} disabled={!libreSel} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">Instalar</button>
              </div>
            </div>
          </div>
        )}

        {reemplazando && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setReemplazando(false)}>
            <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-heading text-lg font-bold text-foreground">Reemplazar componente</h3>
              <div>
                <label className="text-xs text-muted-foreground">Sale (instalado)</label>
                <select value={saleSel} onChange={(e) => setSaleSel(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                  <option value="">— Elegí el que sale —</option>
                  {componentes.map((c) => <option key={c.id} value={c.id}>{c.nombre} ({c.categoriaNombre})</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Entra (libre)</label>
                <select value={entraSel} onChange={(e) => setEntraSel(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                  <option value="">— Elegí el que entra —</option>
                  {libres.map((c) => <option key={c.id} value={c.id}>{c.nombre} ({c.categoriaNombre})</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Motivo / observación</label>
                <textarea value={obsReemplazo} onChange={(e) => setObsReemplazo(e.target.value)} className={`w-full mt-1 ${inputCls}`} rows={2} />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setReemplazando(false)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
                <button onClick={confirmarReemplazar} disabled={!saleSel || !entraSel} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">Reemplazar</button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
```

- [ ] **Step 7: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Screen.tsx`.

- [ ] **Step 8: Confirmar archivos protegidos intactos y commit**

Verificar con `git status` que solo `src/app/screens/ActivosInventario/Screen.tsx` está en tu stage y que `prisma/schema.prisma`/`src/app/util/UiRRHH.tsx` no.

```bash
git add src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: agregar seccion de componentes y reemplazo en la ficha de la PC (subsistema 3)"
```

---

### Task 6: Verificación manual (sin commits)

**Files:** ninguno (checklist para el usuario).

- [ ] **Step 1: Presentar el checklist de verificación manual al usuario**

Los servidores ya corren en el entorno del usuario (no levantar localhost). Checklist:

1. Backend compila; al arrancar, `ensure_columns` agrega `pcPadreId`/`puedeAlbergarComponentes` y marca "PC"; reiniciar no duplica.
2. Autocompletado: en "Nuevo activo", elegir categoría "Memoria RAM" muestra el buscador de catálogo; escribir trae resultados de `memory`; elegir uno precarga nombre/imagen/specs; cargar a mano sigue funcionando; una categoría no-montable (ej. "Silla"/Mobiliario) no muestra el buscador.
3. Crear una PC (categoría "PC") y algunos componentes (RAM, CPU, etc.). En la ficha de la PC aparece "Componentes instalados".
4. Agregar componente → aparece en la tabla; en la ficha del componente aparece "Instalado en: {PC}".
5. Intentar instalar: un componente ya instalado / uno no-montable / una PC dentro de otra → error claro (400).
6. Reemplazar: sale uno, entra otro en un solo diálogo; ambos quedan correctos; el que salió vuelve a estar libre.
7. Quitar un componente → vuelve a estar libre.
8. RBAC: un no-ADMIN ve las secciones (lectura) pero no puede instalar/quitar/reemplazar (403).
9. Dark mode y responsive de la ficha con la sección de componentes y de los diálogos "Agregar"/"Reemplazar".

Esperar el "todo perfecto" (o los ajustes) del usuario antes de la revisión final de rama.

---

## Notas de ejecución

- Tasks 1-2 en `Backend_RRHH` (rama `activos-pcs-componentes`); Tasks 3-5 en `RRHH` (misma rama); Task 6 es verificación manual.
- Orden: 1 → 2 (backend) → 3 → 4 → 5 (frontend; 4 y 5 dependen de 3) → 6.
- Tras las tasks de código: revisión final de rama completa (opus, una por repo, en paralelo), luego merge fast-forward a `main` y push, cada uno con confirmación explícita del usuario.
