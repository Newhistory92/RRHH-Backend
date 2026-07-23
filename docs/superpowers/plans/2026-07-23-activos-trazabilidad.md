# Trazabilidad, transferencias y daños Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exponer el historial de auditoría ya escrito desde S2/S3 (`ActivoHistorial`), agregar un flujo
dedicado de transferencia de responsable, y un flujo de reporte de daños con evidencia fotográfica.

**Architecture:** Extiende los módulos de datos/router de S2-S3 (`app/database/activos.py`,
`app/routes/activos.py`) con funciones/endpoints de solo-lectura sobre `ActivoHistorial` y dos mutaciones
nuevas (`PATCH .../responsable`, `POST .../danos`). El frontend agrega un filtro, dos diálogos y una
sección de timeline dentro de la pantalla "Inventario" ya existente — sin pantallas ni rutas nuevas.

**Tech Stack:** FastAPI + SQLAlchemy `text()` (SQL Server); multipart file upload (`fastapi.File`/`Form`),
reusando el patrón de subida a disco de Portal Institucional; Next.js + React + Tailwind (tokens
semánticos "Orgánico Cálido").

## Global Constraints

- SQL 100% parametrizado vía SQLAlchemy `text()` con parámetros bindeados — nunca interpolación de
  entrada de usuario.
- RBAC: lecturas (`GET`) con `require_any_auth`; escrituras (`PATCH`/`POST`) con `require_roles(ROLE_ADMIN)`
  (alias `require_admin` ya definido en `app/routes/activos.py`).
- Sin tablas nuevas, sin columnas nuevas — todo se apoya en `Activo`/`ActivoHistorial`/`ActivoEstado` ya
  existentes.
- Foto de "Reportar daño": extensiones permitidas `jpg`/`jpeg`/`png`/`webp`/`gif`, tamaño máximo 5 MB
  (`5 * 1024 * 1024` bytes), validado ANTES de escribir nada a disco. Se guarda en
  `uploads/activos_danos/` (carpeta nueva; `StaticFiles` ya sirve toda `uploads/` genéricamente desde
  `main.py`, no hace falta tocar el mount).
- Mapeo de columnas para la fila de historial de un daño reportado (todas en la MISMA fila,
  `accion='dano_reportado'`): `campo='dano'`, `valorAnterior`=nombre del estado previo,
  `valorNuevo`=URL de la foto o `NULL` si no se adjuntó, `observacion`=descripción del daño.
- Filtro "por persona" = responsable actual directo (`Activo.responsableEmpleadoId`), NO tenencia
  histórica — ver spec, Decisión 1.
- **NO tocar** `prisma/schema.prisma` ni `src/app/util/UiRRHH.tsx` en el repo RRHH (modificaciones locales
  del usuario, ajenas a este trabajo).
- Backend en repo `Backend_RRHH`, rama `activos-trazabilidad`. Frontend en repo `RRHH`, misma rama. Sin
  suite automatizada — verificación por compilación + ejecución en vivo de solo lectura (y escritura con
  limpieza) contra la DB real, más `tsc --noEmit` en frontend. No levantar servidores localhost.

---

### Task 1: Backend — módulo de datos (historial + filtro por empleado)

**Files:**
- Modify: `app/database/activos.py` (S2/S3, ya mergeado — se extiende)

**Interfaces:**
- Consumes: nada nuevo — usa `ActivoHistorial`/`Employee` ya existentes.
- Produces (lo que Task 2 importará y llamará):
  - `historial_de_activo(db: Session, activo_id: int) -> list[dict]` — filas de `ActivoHistorial` de ese
    activo, más recientes primero, con `usuarioNombre` resuelto.
  - `listar_activos(...)` gana un parámetro más: `empleado_id: Optional[int] = None` (al final de la firma,
    después de `oficina_id`, manteniendo compatibilidad posicional con las llamadas existentes).

- [ ] **Step 1: Agregar `historial_de_activo` al final del archivo**

Después de la función `buscar_pcparts` (la última del archivo), agregar:

```python
def historial_de_activo(db: Session, activo_id: int) -> list[dict]:
    """Historial completo de un activo (cualquier accion registrada), mas
    recientes primero, con el nombre del usuario que hizo cada cambio resuelto."""
    rows = db.execute(text("""
        SELECT h.id, h.activoId, h.accion, h.campo, h.valorAnterior, h.valorNuevo,
               h.usuarioEmpleadoId, emp.name AS usuarioNombre, h.observacion, h.createdAt
        FROM ActivoHistorial h
        LEFT JOIN Employee emp ON h.usuarioEmpleadoId = emp.id
        WHERE h.activoId = :id
        ORDER BY h.createdAt DESC, h.id DESC
    """), {"id": activo_id}).mappings().all()
    return [{
        "id": r["id"], "activoId": r["activoId"], "accion": r["accion"], "campo": r["campo"],
        "valorAnterior": r["valorAnterior"], "valorNuevo": r["valorNuevo"],
        "usuarioEmpleadoId": r["usuarioEmpleadoId"], "usuarioNombre": r["usuarioNombre"],
        "observacion": r["observacion"],
        "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
    } for r in rows]
```

- [ ] **Step 2: Agregar el filtro `empleado_id` a `listar_activos`**

Reemplazar la firma y el bloque de filtros de `listar_activos`:

```python
def listar_activos(db: Session, categoria_id: Optional[int] = None, grupo: Optional[str] = None,
                   estado_id: Optional[int] = None, texto: Optional[str] = None,
                   departamento_id: Optional[int] = None, oficina_id: Optional[int] = None) -> list[dict]:
    """Activos vigentes con nombres resueltos, con filtros opcionales. Excluye
    componentes ya instalados en una PC (pcPadreId no nulo): esos se listan
    dentro de la ficha de su PC (listar_componentes_de), no en el inventario
    general -- evita duplicados y evita que aparezcan sin responsable propio
    en el agrupamiento por departamento/oficina."""
    query = _SELECT_ACTIVO + " AND a.pcPadreId IS NULL"
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
    if departamento_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado'     THEN re.departmentId
                WHEN 'oficina'      THEN ro.departmentId
                WHEN 'departamento' THEN a.responsableDepartamentoId
                ELSE NULL
            END) = :deptId"""
        params["deptId"] = departamento_id
    if oficina_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado' THEN re.officeId
                WHEN 'oficina'  THEN a.responsableOficinaId
                ELSE NULL
            END) = :ofiId"""
        params["ofiId"] = oficina_id
    query += " ORDER BY a.createdAt DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]
```

por (agrega el parámetro `empleado_id` y su bloque de filtro, justo antes del `ORDER BY`):

```python
def listar_activos(db: Session, categoria_id: Optional[int] = None, grupo: Optional[str] = None,
                   estado_id: Optional[int] = None, texto: Optional[str] = None,
                   departamento_id: Optional[int] = None, oficina_id: Optional[int] = None,
                   empleado_id: Optional[int] = None) -> list[dict]:
    """Activos vigentes con nombres resueltos, con filtros opcionales. Excluye
    componentes ya instalados en una PC (pcPadreId no nulo): esos se listan
    dentro de la ficha de su PC (listar_componentes_de), no en el inventario
    general -- evita duplicados y evita que aparezcan sin responsable propio
    en el agrupamiento por departamento/oficina."""
    query = _SELECT_ACTIVO + " AND a.pcPadreId IS NULL"
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
    if departamento_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado'     THEN re.departmentId
                WHEN 'oficina'      THEN ro.departmentId
                WHEN 'departamento' THEN a.responsableDepartamentoId
                ELSE NULL
            END) = :deptId"""
        params["deptId"] = departamento_id
    if oficina_id:
        query += """ AND (CASE a.responsableTipo
                WHEN 'empleado' THEN re.officeId
                WHEN 'oficina'  THEN a.responsableOficinaId
                ELSE NULL
            END) = :ofiId"""
        params["ofiId"] = oficina_id
    if empleado_id:
        query += " AND a.responsableTipo = 'empleado' AND a.responsableEmpleadoId = :empId"
        params["empId"] = empleado_id
    query += " ORDER BY a.createdAt DESC"
    rows = db.execute(text(query), params).mappings().all()
    return [_fila_a_dict(r) for r in rows]
```

- [ ] **Step 3: Compilar**

Run: `py -m py_compile app/database/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 4: Verificar en vivo (solo lectura) contra la DB real**

Usar el patrón de sesión ya establecido (`SessionLocal`, ver cualquier verificación previa de este mismo
archivo). Confirmar:
- `historial_de_activo(db, <id de un activo real con historial>)` devuelve una lista no vacía, ordenada
  con el `createdAt` más reciente primero, y que al menos una fila tiene `usuarioNombre` resuelto (no
  `None`) si `usuarioEmpleadoId` no es `None`.
- `listar_activos(db, empleado_id=<id de un empleado que sea responsable directo de algo>)` devuelve solo
  activos con ese responsable — si no hay datos de prueba con responsable tipo empleado en la DB real,
  dejarlo como concern (no bloqueante), igual que en tasks anteriores de este archivo.
- Confirmar que `listar_activos()` sin `empleado_id` (llamada posicional u otras combinaciones de filtros
  ya usadas por endpoints existentes) sigue devolviendo los mismos resultados que antes de este cambio —
  no debe haber regresión en el comportamiento ya existente.

- [ ] **Step 5: Commit**

```bash
git add app/database/activos.py
git commit -m "feat: agregar consulta de historial y filtro por empleado (subsistema 4)"
```

---

### Task 2: Backend — endpoints de historial, transferencia y daños

**Files:**
- Modify: `app/routes/activos.py` (S2/S3, ya mergeado — se extiende)

**Interfaces:**
- Consumes (de Task 1): `historial_de_activo(db, activo_id)`, `listar_activos(..., empleado_id=None)`.
- Produces (endpoints que consume el frontend, Tasks 5-6):
  - `GET /activos/{id}/historial` → `{historial: [...]}`
  - `PATCH /activos/{id}/responsable` body `{responsableTipo, responsableEmpleadoId?, responsableOficinaId?, responsableDepartamentoId?, observacion?}` → `{message}`
  - `POST /activos/{id}/danos` multipart (`descripcion: Form`, `foto: File` opcional) → `{message}`
  - `GET /activos?...&empleadoId=` → `{activos: [...]}` (extensión del endpoint ya existente)

- [ ] **Step 1: Ampliar los imports**

Reemplazar el bloque de imports del principio del archivo:

```python
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
    MAPEO_PCPARTS, listar_componentes_de, componentes_libres, buscar_pcparts,
)
```

por:

```python
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, Body, File, Form, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from app.database.activos import (
    ensure_tables, RESPONSABLE_TIPOS, registrar_historial, estado_disponible_id,
    listar_activos, obtener_activo, buscar_por_codigo,
    MAPEO_PCPARTS, listar_componentes_de, componentes_libres, buscar_pcparts,
    historial_de_activo,
)
```

- [ ] **Step 2: Extender `get_activos` con el filtro `empleadoId`**

Reemplazar:

```python
@router.get("", dependencies=[Depends(require_any_auth)])
def get_activos(categoriaId: Optional[int] = None, grupo: Optional[str] = None,
                estadoId: Optional[int] = None, texto: Optional[str] = None,
                departamentoId: Optional[int] = None, oficinaId: Optional[int] = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"activos": listar_activos(db, categoriaId, grupo, estadoId, texto,
                                       departamento_id=departamentoId, oficina_id=oficinaId)}
```

por:

```python
@router.get("", dependencies=[Depends(require_any_auth)])
def get_activos(categoriaId: Optional[int] = None, grupo: Optional[str] = None,
                estadoId: Optional[int] = None, texto: Optional[str] = None,
                departamentoId: Optional[int] = None, oficinaId: Optional[int] = None,
                empleadoId: Optional[int] = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"activos": listar_activos(db, categoriaId, grupo, estadoId, texto,
                                       departamento_id=departamentoId, oficina_id=oficinaId,
                                       empleado_id=empleadoId)}
```

- [ ] **Step 3: Agregar `GET /{activo_id}/historial`**

Ubicar el endpoint `get_componentes` (`@router.get("/{activo_id}/componentes", ...)`) — es el último
endpoint de lectura antes de la sección `# ─── Escritura ───`. Insertar el nuevo endpoint justo después:

```python
@router.get("/{activo_id}/componentes", dependencies=[Depends(require_any_auth)])
def get_componentes(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"componentes": listar_componentes_de(db, activo_id)}


@router.get("/{activo_id}/historial", dependencies=[Depends(require_any_auth)])
def get_historial(activo_id: int, db: Session = Depends(get_db)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    return {"historial": historial_de_activo(db, activo_id)}
```

- [ ] **Step 4: Agregar `PATCH /{activo_id}/responsable` (transferencia dedicada)**

Al final del archivo (después de `reemplazar_componente`, el último endpoint), agregar:

```python
# ─── Trazabilidad: historial, transferencia y danos (subsistema 4) ───────────
@router.patch("/{activo_id}/responsable", dependencies=[Depends(require_admin)])
def transferir_responsable(activo_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                           current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    resp = _validar_responsable(db, data)
    usuario = current_user.get("employeeId")
    observacion = data.get("observacion") or None
    resp_cambio = (resp["tipo"] != actual["responsableTipo"] or
                   resp["empleado"] != actual["responsableEmpleadoId"] or
                   resp["oficina"] != actual["responsableOficinaId"] or
                   resp["departamento"] != actual["responsableDepartamentoId"])
    if resp_cambio:
        registrar_historial(db, activo_id, "cambio_responsable", "responsable",
                            actual["responsableNombre"], _nombre_responsable(db, resp), usuario, observacion)
    db.execute(text("""
        UPDATE Activo SET responsableTipo = :rtipo, responsableEmpleadoId = :remp,
            responsableOficinaId = :rofi, responsableDepartamentoId = :rdep, updatedAt = :now
        WHERE id = :id
    """), {
        "rtipo": resp["tipo"], "remp": resp["empleado"], "rofi": resp["oficina"],
        "rdep": resp["departamento"], "now": datetime.utcnow(), "id": activo_id,
    })
    db.commit()
    return {"message": "Responsable actualizado"}
```

Nota: `_validar_responsable` y `_nombre_responsable` ya existen en este archivo (funciones definidas más
arriba) — no hace falta reimplementarlas, solo reusarlas. `_validar_responsable` acepta
`responsableTipo` vacío/`None` como "sin responsable" (limpia los 4 campos), así que "Transferir a nadie"
también funciona con este mismo endpoint sin lógica especial.

- [ ] **Step 5: Agregar `POST /{activo_id}/danos` (reporte de daño con evidencia)**

Después del endpoint del Step 4, agregar:

```python
DANOS_UPLOAD_DIR = "uploads/activos_danos"
DANOS_EXT_VALIDAS = {"jpg", "jpeg", "png", "webp", "gif"}
DANOS_TAMANO_MAX = 5 * 1024 * 1024  # 5 MB


@router.post("/{activo_id}/danos", dependencies=[Depends(require_admin)])
async def reportar_dano(activo_id: int, descripcion: str = Form(...), foto: Optional[UploadFile] = File(None),
                        db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    ensure_tables(db)
    actual = obtener_activo(db, activo_id)
    if not actual:
        raise HTTPException(status_code=404, detail="Activo no encontrado")
    descripcion = descripcion.strip()
    if not descripcion:
        raise HTTPException(status_code=400, detail="La descripcion del dano es obligatoria")
    dano_estado = db.execute(
        text("SELECT id, nombre FROM ActivoEstado WHERE codigo = 'danado' AND activo = 1")
    ).mappings().first()
    if not dano_estado:
        raise HTTPException(status_code=400, detail="No existe el estado 'Dañado'; verifique la configuracion")

    foto_url = None
    if foto is not None:
        original = foto.filename or ""
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if ext not in DANOS_EXT_VALIDAS:
            raise HTTPException(status_code=400, detail=f"Tipo de imagen no permitido (.{ext})")
        contenido = await foto.read()
        if len(contenido) > DANOS_TAMANO_MAX:
            raise HTTPException(status_code=400, detail="La foto excede el limite de 5 MB")
        os.makedirs(DANOS_UPLOAD_DIR, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(DANOS_UPLOAD_DIR, stored_name), "wb") as f:
            f.write(contenido)
        foto_url = f"/uploads/activos_danos/{stored_name}"

    usuario = current_user.get("employeeId")
    registrar_historial(db, activo_id, "dano_reportado", "dano", actual["estadoNombre"], foto_url,
                        usuario, descripcion)
    db.execute(text("UPDATE Activo SET estadoId = :est, updatedAt = :now WHERE id = :id"),
               {"est": dano_estado["id"], "now": datetime.utcnow(), "id": activo_id})
    db.commit()
    return {"message": "Dano reportado"}
```

Nota sobre el mapeo de columnas (igual que en el spec): `accion='dano_reportado'`, `campo='dano'`,
`valorAnterior`=nombre del estado previo (para contexto), `valorNuevo`=URL de la foto o `None`,
`observacion`=descripción. Todo en una sola fila de historial, no dos.

- [ ] **Step 6: Compilar**

Run: `py -m py_compile app/routes/activos.py`
Expected: sin salida (exit 0).

- [ ] **Step 7: Verificar en vivo contra la DB real**

Con el patrón de verificación ya establecido en este archivo (crear datos de prueba temporales, limpiar al
final):
- `GET /activos/{id}/historial` sobre un activo real con historial → devuelve `{historial:[...]}` no
  vacío, más reciente primero.
- `GET /activos/{id}/historial` sobre un id inexistente → 404.
- `PATCH /activos/{id}/responsable` sobre un activo de prueba, cambiando a un responsable distinto (tipo
  empleado, oficina, o departamento — cualquiera con datos reales) → confirma que el activo refleja el
  nuevo responsable y que `ActivoHistorial` tiene una fila `cambio_responsable` con el nombre nuevo
  correctamente resuelto (no `None`).
- `POST /activos/{id}/danos` con `descripcion` y sin foto → el activo pasa a estado "Dañado"; hay una fila
  `dano_reportado` con `valorNuevo=NULL` y la `observacion` correcta.
- `POST /activos/{id}/danos` con `descripcion` y una imagen real pequeña (crear un archivo de prueba
  temporal, ej. un PNG mínimo) → el archivo aparece en `uploads/activos_danos/`, la fila de historial tiene
  `valorNuevo` con la URL `/uploads/activos_danos/{nombre}.png`.
- `POST /activos/{id}/danos` con una extensión no permitida (ej. `.txt` renombrado) → 400, y confirmar que
  NO se creó ningún archivo en `uploads/activos_danos/` (fail-fast antes de escribir a disco).
- RBAC: sin token, `PATCH /responsable` y `POST /danos` devuelven 401.
- Limpiar: soft-delete de cualquier activo de prueba creado, y borrar cualquier archivo de prueba dejado en
  `uploads/activos_danos/`, sin basura activa.

Si no es posible correr todo el flujo de escritura con seguridad contra la DB compartida, hacer al menos
la verificación de lectura y reportarlo como concern (no bloqueante), igual que en subsistemas anteriores.

- [ ] **Step 8: Commit**

```bash
git add app/routes/activos.py
git commit -m "feat: agregar historial, transferencia de responsable y reporte de danos (subsistema 4)"
```

---

### Task 3: Frontend — tipo `HistorialItem`

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts` (repo RRHH)

**Interfaces:**
- Consumes: la forma de `historial_de_activo` (Task 1) / `GET /activos/{id}/historial` (Task 2).
- Produces: `HistorialItem`, consumido por Task 6.

- [ ] **Step 1: Agregar la interfaz `HistorialItem`**

En `src/app/Interfas/Interfaces.ts`, después del bloque de `PCPart` (o en cualquier posición cercana a los
demás tipos de Activos), agregar:

```ts
export interface HistorialItem {
  id: number;
  activoId: number;
  accion: string;
  campo: string | null;
  valorAnterior: string | null;
  valorNuevo: string | null;
  usuarioEmpleadoId: number | null;
  usuarioNombre: string | null;
  observacion: string | null;
  createdAt: string | null;
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Interfaces.ts`.

- [ ] **Step 3: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar tipo HistorialItem (subsistema 4)"
```

---

### Task 4: Frontend — subida de evidencia de daño (`reportarDano`)

**Files:**
- Modify: `src/app/util/uploadClient.ts` (repo RRHH)

**Interfaces:**
- Consumes: `POST /activos/{id}/danos` (Task 2, multipart).
- Produces: `reportarDano(activoId: number, descripcion: string, foto: File | null): Promise<{message: string}>`, consumido por Task 6.

- [ ] **Step 1: Agregar `reportarDano` reusando el patrón fetch+FormData de `uploadAttachment`**

Al final de `src/app/util/uploadClient.ts`, agregar:

```ts
export async function reportarDano(
  activoId: number,
  descripcion: string,
  foto: File | null
): Promise<{ message: string }> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const form = new FormData();
  form.append('descripcion', descripcion);
  if (foto) form.append('foto', foto);

  const res = await fetch(`${BACKEND_URL}/activos/${activoId}/danos`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `Error al reportar el daño (${res.status})`);
  }
  return res.json();
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `uploadClient.ts`.

- [ ] **Step 3: Confirmar archivos protegidos intactos y commit**

```bash
git add src/app/util/uploadClient.ts
git commit -m "feat: agregar reportarDano al uploadClient (subsistema 4)"
```

---

### Task 5: Frontend — filtro Empleado + diálogo "Transferir responsable"

**Files:**
- Modify: `src/app/screens/ActivosInventario/Screen.tsx` (repo RRHH)

**Interfaces:**
- Consumes: `GET /activos?...&empleadoId=` (Task 2), `PATCH /activos/{id}/responsable` (Task 2),
  `GET /rrhh/employees` → `{employees:[{id,name}]}` (ya usado en `ActivoForm.tsx`, mismo shape).
- Produces: nada para otras tasks — Task 6 reutiliza el mismo archivo pero no depende de nombres nuevos de
  esta task salvo el estado `empleados`/tipo `EmpOption` (ya definidos acá).

- [ ] **Step 1: Agregar el tipo local `EmpOption` y la constante `RESP_TIPOS`**

Después de la interfaz `DeptOption` (línea ~12), agregar:

```ts
interface EmpOption { id: number; name: string; }
```

Después de la constante `ESTADOS_PROBLEMA` (y su comentario), agregar:

```ts
const RESP_TIPOS = [
  { value: '', label: 'Sin asignar' },
  { value: 'empleado', label: 'Empleado' },
  { value: 'oficina', label: 'Oficina' },
  { value: 'departamento', label: 'Departamento' },
];
```

- [ ] **Step 2: Agregar el estado nuevo**

Después de la línea `const [mostrarProblema, setMostrarProblema] = useState(false);`, agregar:

```ts
  const [empleados, setEmpleados] = useState<EmpOption[]>([]);
  const [transfiriendo, setTransfiriendo] = useState(false);
  const [transferTipo, setTransferTipo] = useState('');
  const [transferEmpleadoId, setTransferEmpleadoId] = useState('');
  const [transferOficinaId, setTransferOficinaId] = useState('');
  const [transferDepartamentoId, setTransferDepartamentoId] = useState('');
  const [transferObs, setTransferObs] = useState('');
  const [transferError, setTransferError] = useState('');
  const [transfiriendoGuardando, setTransfiriendoGuardando] = useState(false);
```

- [ ] **Step 3: Agregar `empleadoId` al estado de filtros y a la query string, y cargar los empleados**

Reemplazar:

```ts
  const [filtros, setFiltros] = useState({ categoriaId: '', grupo: '', estadoId: '', texto: '', departamentoId: '', oficinaId: '' });
```

por:

```ts
  const [filtros, setFiltros] = useState({ categoriaId: '', grupo: '', estadoId: '', texto: '', departamentoId: '', oficinaId: '', empleadoId: '' });
```

En `cargar()`, agregar el parámetro nuevo junto a los existentes (antes de `const qs = ...`):

```ts
    if (filtros.empleadoId) params.set('empleadoId', filtros.empleadoId);
```

En el `useEffect` inicial que carga categorías/estados/departamentos, agregar la carga de empleados:

```ts
  useEffect(() => {
    apiClient.get<{ categorias: ActivoCategoria[] }>('/activos/config/categorias').then((r) => setCategorias(r.categorias || [])).catch(() => {});
    apiClient.get<{ estados: ActivoEstado[] }>('/activos/config/estados').then((r) => setEstados(r.estados || [])).catch(() => {});
    apiClient.get<{ departments: DeptOption[] }>('/departments/').then((r) => setDepts(r.departments || [])).catch(() => {});
    apiClient.get<{ employees: EmpOption[] }>('/rrhh/employees').then((r) => setEmpleados(r.employees || [])).catch(() => {});
  }, []);
```

- [ ] **Step 4: Agregar el select de Empleado a la barra de filtros**

En la barra de filtros, después del select de Oficina (el que tiene `<option value="">Todas las
oficinas</option>`), agregar:

```tsx
          <select
            value={filtros.empleadoId}
            onChange={(e) => setFiltros({ ...filtros, empleadoId: e.target.value })}
            className={inputCls}
          >
            <option value="">Todos los empleados</option>
            {empleados.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
```

- [ ] **Step 5: Agregar los handlers de "Transferir"**

Después de la función `guardarEstado` (y antes de `abrirAgregar`), agregar:

```ts
  const abrirTransferir = () => {
    if (!seleccionado) return;
    setTransferTipo(seleccionado.responsableTipo ?? '');
    setTransferEmpleadoId(seleccionado.responsableEmpleadoId ? String(seleccionado.responsableEmpleadoId) : '');
    setTransferOficinaId(seleccionado.responsableOficinaId ? String(seleccionado.responsableOficinaId) : '');
    setTransferDepartamentoId(seleccionado.responsableDepartamentoId ? String(seleccionado.responsableDepartamentoId) : '');
    setTransferObs('');
    setTransferError('');
    setTransfiriendo(true);
  };

  const confirmarTransferir = async () => {
    if (!seleccionado) return;
    setTransferError('');
    if (transferTipo === 'empleado' && !transferEmpleadoId) { setTransferError('Elegí el empleado.'); return; }
    if (transferTipo === 'oficina' && !transferOficinaId) { setTransferError('Elegí la oficina.'); return; }
    if (transferTipo === 'departamento' && !transferDepartamentoId) { setTransferError('Elegí el departamento.'); return; }
    setTransfiriendoGuardando(true);
    try {
      await apiClient.patch(`/activos/${seleccionado.id}/responsable`, {
        responsableTipo: transferTipo || null,
        responsableEmpleadoId: transferTipo === 'empleado' ? Number(transferEmpleadoId) : null,
        responsableOficinaId: transferTipo === 'oficina' ? Number(transferOficinaId) : null,
        responsableDepartamentoId: transferTipo === 'departamento' ? Number(transferDepartamentoId) : null,
        observacion: transferObs || null,
      });
      setTransfiriendo(false);
      const det = await apiClient.get<ActivoDetalle>(`/activos/${seleccionado.id}`);
      setSeleccionado(det);
    } catch (e) {
      setTransferError((e as Error).message);
    } finally {
      setTransfiriendoGuardando(false);
    }
  };
```

- [ ] **Step 6: Agregar el botón "Transferir" en la ficha e importar el ícono**

Reemplazar la línea de import de íconos:

```ts
import { Plus, ArrowLeft, Pencil, Cpu, Trash2, Repeat, ChevronDown } from 'lucide-react';
```

por:

```ts
import { Plus, ArrowLeft, Pencil, Cpu, Trash2, Repeat, ChevronDown, UserCog } from 'lucide-react';
```

En el header de la ficha, reemplazar:

```tsx
            <div className="flex gap-2">
              <button onClick={() => { setEditando(a); setModo('form'); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><Pencil size={16} /> Editar</button>
              <button onClick={() => setCambioEstado({ estadoId: String(a.estadoId), observacion: '' })} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90">Cambiar estado</button>
            </div>
```

por:

```tsx
            <div className="flex gap-2 flex-wrap">
              <button onClick={() => { setEditando(a); setModo('form'); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><Pencil size={16} /> Editar</button>
              <button onClick={() => setCambioEstado({ estadoId: String(a.estadoId), observacion: '' })} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90">Cambiar estado</button>
              <button onClick={abrirTransferir} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><UserCog size={16} /> Transferir</button>
            </div>
```

- [ ] **Step 7: Agregar el diálogo "Transferir responsable"**

Insertar el diálogo nuevo justo después del diálogo `{cambioEstado && (...)}` (después de su `)}` de
cierre) y antes de `{agregando && (...)}`:

```tsx
        {transfiriendo && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setTransfiriendo(false)}>
            <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-heading text-lg font-bold text-foreground">Transferir responsable</h3>
              {transferError && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{transferError}</div>}
              <div>
                <label className="text-xs text-muted-foreground">Tipo</label>
                <select
                  value={transferTipo}
                  onChange={(e) => { setTransferTipo(e.target.value); setTransferEmpleadoId(''); setTransferOficinaId(''); setTransferDepartamentoId(''); }}
                  className={`w-full mt-1 ${inputCls}`}
                >
                  {RESP_TIPOS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              {transferTipo === 'empleado' && (
                <div>
                  <label className="text-xs text-muted-foreground">Empleado</label>
                  <select value={transferEmpleadoId} onChange={(e) => setTransferEmpleadoId(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                    <option value="">— Elegí empleado —</option>
                    {empleados.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </select>
                </div>
              )}
              {transferTipo === 'oficina' && (
                <div>
                  <label className="text-xs text-muted-foreground">Oficina</label>
                  <select value={transferOficinaId} onChange={(e) => setTransferOficinaId(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                    <option value="">— Elegí oficina —</option>
                    {depts.flatMap((d) => d.offices.map((o) => ({ id: o.id, nombre: `${d.nombre} / ${o.nombre}` }))).map((o) => (
                      <option key={o.id} value={o.id}>{o.nombre}</option>
                    ))}
                  </select>
                </div>
              )}
              {transferTipo === 'departamento' && (
                <div>
                  <label className="text-xs text-muted-foreground">Departamento</label>
                  <select value={transferDepartamentoId} onChange={(e) => setTransferDepartamentoId(e.target.value)} className={`w-full mt-1 ${inputCls}`}>
                    <option value="">— Elegí departamento —</option>
                    {depts.map((d) => <option key={d.id} value={d.id}>{d.nombre}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label className="text-xs text-muted-foreground">Motivo / observación</label>
                <textarea value={transferObs} onChange={(e) => setTransferObs(e.target.value)} className={`w-full mt-1 ${inputCls}`} rows={2} />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setTransfiriendo(false)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
                <button onClick={confirmarTransferir} disabled={transfiriendoGuardando} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">{transfiriendoGuardando ? 'Guardando…' : 'Transferir'}</button>
              </div>
            </div>
          </div>
        )}
```

- [ ] **Step 8: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Screen.tsx`.

- [ ] **Step 9: No tocar servidores locales; confirmar archivos protegidos intactos y commit**

No inicies ningún dev server ni navegues a `localhost`. `prisma/schema.prisma` y
`src/app/util/UiRRHH.tsx` no deben aparecer agregados por vos.

```bash
git add src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: agregar filtro por empleado y dialogo de transferencia de responsable (subsistema 4)"
```

---

### Task 6: Frontend — diálogo "Reportar daño" + sección "Historial"

**Files:**
- Modify: `src/app/screens/ActivosInventario/Screen.tsx` (repo RRHH — depende de Task 5, mismo archivo)

**Interfaces:**
- Consumes: `reportarDano` (Task 4), `HistorialItem` (Task 3), `GET /activos/{id}/historial` (Task 2),
  `resolveAttachmentUrl` (ya existe en `src/app/util/uploadClient.ts`, usado por Portal Institucional).
- Produces: nada — última task de código de esta rama.

- [ ] **Step 1: Agregar los imports nuevos**

Reemplazar:

```ts
import { formatearSpecs } from '@/app/util/pcparts';
import type { ActivoListItem, ActivoDetalle, ActivoCategoria, ActivoEstado, PCPart } from '@/app/Interfas/Interfaces';
import { Plus, ArrowLeft, Pencil, Cpu, Trash2, Repeat, ChevronDown, UserCog } from 'lucide-react';
```

por:

```ts
import { formatearSpecs } from '@/app/util/pcparts';
import { reportarDano, resolveAttachmentUrl } from '@/app/util/uploadClient';
import type { ActivoListItem, ActivoDetalle, ActivoCategoria, ActivoEstado, PCPart, HistorialItem } from '@/app/Interfas/Interfaces';
import { Plus, ArrowLeft, Pencil, Cpu, Trash2, Repeat, ChevronDown, UserCog, AlertTriangle, RefreshCw } from 'lucide-react';
```

- [ ] **Step 2: Agregar el mapeo acción→etiqueta y el lookup de íconos, a nivel de módulo**

Después de la función `agruparPorDeptoOficina` (y antes de `type Modo = ...`), agregar:

```ts
function etiquetaHistorial(h: HistorialItem): { icono: string; texto: string } {
  switch (h.accion) {
    case 'creacion':
      return { icono: 'creacion', texto: 'Activo creado' };
    case 'cambio_estado':
      return { icono: 'estado', texto: `Cambio de estado: ${h.valorAnterior ?? '—'} → ${h.valorNuevo ?? '—'}` };
    case 'cambio_responsable':
      return { icono: 'responsable', texto: `Cambio de responsable: ${h.valorAnterior ?? 'Sin asignar'} → ${h.valorNuevo ?? 'Sin asignar'}` };
    case 'modificacion':
      return { icono: 'otro', texto: 'Datos modificados' };
    case 'baja':
      return { icono: 'baja', texto: 'Dado de baja' };
    case 'instalacion':
      return { icono: 'componente', texto: 'Instalado en una PC' };
    case 'desinstalacion':
      return { icono: 'componente', texto: 'Desinstalado de una PC' };
    case 'componente_agregado':
      return { icono: 'componente', texto: `Componente agregado: ${h.valorNuevo ?? '—'}` };
    case 'componente_quitado':
      return { icono: 'componente', texto: `Componente quitado: ${h.valorAnterior ?? '—'}` };
    case 'reemplazo':
      return { icono: 'componente', texto: 'Componente reemplazado' };
    case 'dano_reportado':
      return { icono: 'dano', texto: `Daño reportado${h.valorAnterior ? ` (estaba: ${h.valorAnterior})` : ''}` };
    default:
      return { icono: 'otro', texto: h.accion };
  }
}
```

- [ ] **Step 3: Agregar el estado nuevo**

Después de la línea `const [transfiriendoGuardando, setTransfiriendoGuardando] = useState(false);`
(agregada en Task 5), agregar:

```ts
  const [historial, setHistorial] = useState<HistorialItem[]>([]);
  const [reportandoDano, setReportandoDano] = useState(false);
  const [danoDescripcion, setDanoDescripcion] = useState('');
  const [danoFoto, setDanoFoto] = useState<File | null>(null);
  const [danoError, setDanoError] = useState('');
  const [danoGuardando, setDanoGuardando] = useState(false);
```

- [ ] **Step 4: Cargar el historial al abrir la ficha**

Después de la función `cargarComponentes`, agregar:

```ts
  const cargarHistorial = (id: number) => {
    apiClient.get<{ historial: HistorialItem[] }>(`/activos/${id}/historial`)
      .then((r) => setHistorial(r.historial || []))
      .catch(() => setHistorial([]));
  };
```

Reemplazar la función `abrirFicha`:

```ts
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

por:

```ts
  const abrirFicha = async (id: number) => {
    try {
      const det = await apiClient.get<ActivoDetalle>(`/activos/${id}`);
      setSeleccionado(det);
      setModo('ficha');
      if (det.puedeAlbergarComponentes) cargarComponentes(id);
      else setComponentes([]);
      cargarHistorial(id);
    } catch (e) { console.error(e); }
  };
```

- [ ] **Step 5: Agregar los handlers de "Reportar daño"**

Después de la función `confirmarTransferir` (agregada en Task 5), agregar:

```ts
  const abrirReportarDano = () => {
    setDanoDescripcion(''); setDanoFoto(null); setDanoError(''); setReportandoDano(true);
  };

  const confirmarReportarDano = async () => {
    if (!seleccionado) return;
    setDanoError('');
    if (!danoDescripcion.trim()) { setDanoError('La descripción es obligatoria.'); return; }
    setDanoGuardando(true);
    try {
      await reportarDano(seleccionado.id, danoDescripcion.trim(), danoFoto);
      setReportandoDano(false);
      const det = await apiClient.get<ActivoDetalle>(`/activos/${seleccionado.id}`);
      setSeleccionado(det);
      cargarHistorial(seleccionado.id);
    } catch (e) {
      setDanoError((e as Error).message);
    } finally {
      setDanoGuardando(false);
    }
  };
```

- [ ] **Step 6: Agregar el botón "Reportar daño" en la ficha**

En el header de la ficha (el `<div className="flex gap-2 flex-wrap">` agregado en Task 5), agregar el
botón después de "Transferir":

```tsx
            <div className="flex gap-2 flex-wrap">
              <button onClick={() => { setEditando(a); setModo('form'); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><Pencil size={16} /> Editar</button>
              <button onClick={() => setCambioEstado({ estadoId: String(a.estadoId), observacion: '' })} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90">Cambiar estado</button>
              <button onClick={abrirTransferir} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted"><UserCog size={16} /> Transferir</button>
              <button onClick={abrirReportarDano} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-error text-error hover:bg-error-soft"><AlertTriangle size={16} /> Reportar daño</button>
            </div>
```

- [ ] **Step 7: Agregar la sección "Historial" en la ficha**

Insertar la sección nueva justo después del bloque `{a.puedeAlbergarComponentes && (...)}` (después de su
`)}` de cierre) y antes del `</div>` que cierra el contenedor `max-w-4xl`:

```tsx
          <div className="bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6 space-y-3">
            <h2 className="font-heading text-lg font-bold text-foreground flex items-center gap-2"><RefreshCw size={18} /> Historial</h2>
            {historial.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin movimientos registrados.</p>
            ) : (
              <ul className="space-y-3">
                {historial.map((h) => {
                  const { texto } = etiquetaHistorial(h);
                  return (
                    <li key={h.id} className="flex items-start gap-3 border-t border-border pt-3 first:border-t-0 first:pt-0">
                      <RefreshCw size={16} className="text-muted-foreground mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-foreground">{texto}</p>
                        {h.accion === 'dano_reportado' && h.observacion && (
                          <p className="text-xs text-muted-foreground mt-0.5">{h.observacion}</p>
                        )}
                        {h.accion === 'dano_reportado' && h.valorNuevo && (
                          <a href={resolveAttachmentUrl(h.valorNuevo)} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">Ver foto</a>
                        )}
                        {h.accion !== 'dano_reportado' && h.observacion && (
                          <p className="text-xs text-muted-foreground mt-0.5">{h.observacion}</p>
                        )}
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {h.createdAt ? new Date(h.createdAt).toLocaleString('es-AR') : ''}
                          {h.usuarioNombre ? ` · ${h.usuarioNombre}` : ''}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
```

Nota: este Step usa una sola importación de ícono (`RefreshCw`) para todas las filas por simplicidad —
está bien, no hace falta un ícono distinto por tipo de acción para que la sección sea útil; `etiquetaHistorial` ya distingue el texto por tipo.

- [ ] **Step 8: Agregar el diálogo "Reportar daño"**

Insertar el diálogo nuevo justo después del diálogo `{transfiriendo && (...)}` (agregado en Task 5,
después de su `)}` de cierre) y antes de `{agregando && (...)}`:

```tsx
        {reportandoDano && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" onClick={() => setReportandoDano(false)}>
            <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
              <h3 className="font-heading text-lg font-bold text-foreground">Reportar daño</h3>
              {danoError && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{danoError}</div>}
              <div>
                <label className="text-xs text-muted-foreground">Descripción *</label>
                <textarea value={danoDescripcion} onChange={(e) => setDanoDescripcion(e.target.value)} className={`w-full mt-1 ${inputCls}`} rows={3} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Foto (opcional)</label>
                <input type="file" accept="image/*" onChange={(e) => setDanoFoto(e.target.files?.[0] ?? null)} className={`w-full mt-1 ${inputCls}`} />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setReportandoDano(false)} className="px-3 py-2 rounded-lg border border-border text-sm text-foreground hover:bg-muted">Cancelar</button>
                <button onClick={confirmarReportarDano} disabled={danoGuardando} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50">{danoGuardando ? 'Guardando…' : 'Reportar'}</button>
              </div>
            </div>
          </div>
        )}
```

- [ ] **Step 9: Typecheck**

Run: `npx tsc --noEmit`
Expected: sin errores nuevos en `Screen.tsx`.

- [ ] **Step 10: No tocar servidores locales; confirmar archivos protegidos intactos y commit**

```bash
git add src/app/screens/ActivosInventario/Screen.tsx
git commit -m "feat: agregar reporte de danos con evidencia y seccion de historial (subsistema 4)"
```

---

### Task 7: Verificación manual (sin commits)

**Files:** ninguno (checklist para el usuario).

- [ ] **Step 1: Presentar el checklist de verificación manual al usuario**

Los servidores ya corren en el entorno del usuario (no levantar localhost). Checklist:

1. Backend compila; endpoints nuevos responden.
2. Abrir la ficha de un activo con historial previo (de S2/S3) → la sección "Historial" muestra sus
   movimientos pasados, más recientes primero, con fecha y usuario.
3. "Transferir" un activo a un empleado/oficina/departamento distinto → la ficha refleja el nuevo
   responsable; el historial muestra `Cambio de responsable: X → Y` con nombres reales (no vacío).
4. "Reportar daño" con foto → el estado pasa a "Dañado"; el historial muestra "Daño reportado" con la
   descripción y un link "Ver foto" que abre la imagen subida.
5. "Reportar daño" sin foto → funciona igual, sin link.
6. Intentar reportar un daño con un archivo no-imagen o demasiado grande → error claro, sin romper nada.
7. Filtrar el listado principal por Empleado → solo aparecen sus activos actuales.
8. RBAC: un no-ADMIN ve el historial pero no puede transferir ni reportar daños (403).
9. Dark mode y responsive de los dos diálogos nuevos y de la sección "Historial".

Esperar el "todo perfecto" (o los ajustes) del usuario antes de la revisión final de rama.

---

## Notas de ejecución

- Tasks 1-2 en `Backend_RRHH` (rama `activos-trazabilidad`); Tasks 3-6 en `RRHH` (misma rama); Task 7 es
  verificación manual.
- Orden: 1 → 2 (backend) → 3 → 4 (independientes entre sí, pueden ir en cualquier orden) → 5 → 6 (mismo
  archivo `Screen.tsx`, secuencial) → 7.
- Tras las tasks de código: revisión final de rama completa (opus, una por repo, en paralelo), luego merge
  fast-forward a `main` y push, cada uno con confirmación explícita del usuario.
