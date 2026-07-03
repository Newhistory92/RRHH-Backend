# Reubicación — Solicitud del empleado Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Primer subsistema del módulo de Reubicación Inteligente: tabla `SolicitudReubicacion`, endpoints de creación y listado propio, y una pantalla nueva accesible para cualquier empleado desde el menú del header.

**Architecture:** Un módulo `app/database/reubicacion.py` con `ensure_table()` idempotente (mismo patrón que `feedback_config.py`/`feriados.py`), un router nuevo `app/routes/reubicacion.py` registrado en `app/main.py`. En el frontend, una pantalla nueva `screens/Reubicacion/Screen.tsx` (mismo patrón que `MisDocumentos/Screen.tsx`), enganchada vía `Header.tsx` (menú de perfil), `rbac.ts` (`PAGE_CONFIG`), `Interfaces.ts` (`Page` type) y `page.tsx` (switch + import).

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- `tipo` debe ser uno de exactamente estos 6 valores: `"Cambio de oficina"`, `"Cambio de departamento"`, `"Reubicación por desarrollo profesional"`, `"Reubicación por clima laboral"`, `"Reubicación por razones personales"`, `"Otra"`.
- Toda solicitud nueva nace en `estado = "Pendiente"`. No hay campo de oficina/departamento destino — eso lo determina un subsistema futuro (motor de IA).
- Self-or-admin: un empleado solo puede crear/leer sus propias solicitudes, salvo que quien llame sea Admin (`roleId == ROLE_ADMIN`) — mismo patrón que `licenses.py`/`feedback.py`.
- No se toca ningún archivo de los módulos de Licencias/Feedback ya existentes.
- `app/main.py` ya está limpio de WIP no relacionado (commit `5be432a`) — se puede modificar con normalidad para registrar el router nuevo.

---

### Task 1: Backend — tabla, endpoints y registro del router

**Files:**
- Create: `app/database/reubicacion.py`
- Create: `app/routes/reubicacion.py`
- Modify: `app/main.py`

**Interfaces:**
- Produces: `ensure_table(db: Session) -> None` en `app/database/reubicacion.py`. `POST /reubicacion/request` → `{"message": str, "id": int}`. `GET /reubicacion/mis-solicitudes/{employee_id}` → `{"solicitudes": [{id, employeeId, tipo, motivo, estado, officeIdActual, departmentIdActual, createdAt, updatedAt}]}`.

- [ ] **Step 1: Crear `app/database/reubicacion.py` con la tabla**

```python
"""
Modulo de Reubicacion Inteligente -- solicitud del empleado (subsistema 1).
Sin campo de oficina/departamento destino: lo determina un subsistema
futuro (motor de matching por IA). Toda solicitud nace en 'Pendiente'.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'SolicitudReubicacion' AND xtype = 'U'
)
BEGIN
    CREATE TABLE SolicitudReubicacion (
        id                  INT IDENTITY(1,1) PRIMARY KEY,
        employeeId          INT            NOT NULL,
        tipo                NVARCHAR(50)   NOT NULL,
        motivo              NVARCHAR(MAX)  NOT NULL,
        estado              NVARCHAR(20)   NOT NULL DEFAULT 'Pendiente',
        officeIdActual      INT            NULL,
        departmentIdActual  INT            NULL,
        createdAt           DATETIME2      NOT NULL,
        updatedAt           DATETIME2      NOT NULL
    );
    CREATE INDEX IX_SolicitudReubicacion_employeeId ON SolicitudReubicacion (employeeId);
END
"""

VALID_TIPOS = {
    "Cambio de oficina",
    "Cambio de departamento",
    "Reubicación por desarrollo profesional",
    "Reubicación por clima laboral",
    "Reubicación por razones personales",
    "Otra",
}


def ensure_table(db: Session) -> None:
    """Crea SolicitudReubicacion si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()
```

- [ ] **Step 2: Crear `app/routes/reubicacion.py`**

```python
"""
Router /reubicacion -- Solicitud de cambio de oficina/departamento
(subsistema 1 del modulo de Reubicacion Inteligente).
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _check_self_or_admin(employee_id: int, current_user: dict) -> None:
    """Evita que un empleado cree o lea solicitudes en nombre de otro."""
    if employee_id != current_user.get("employeeId") and current_user.get("roleId") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenes permiso para acceder a esta informacion.")


# ─────────────────────────────────────────────────────────────────────────────
# POST /reubicacion/request
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/request", dependencies=[Depends(require_any_auth)])
def create_solicitud(data: dict = Body(...), db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Crea una solicitud de reubicacion. Nace siempre en estado 'Pendiente'.

    Body:
    {
      "employeeId": 5,
      "tipo": "Cambio de oficina",
      "motivo": "Texto libre explicando el motivo"
    }
    """
    employee_id = data.get("employeeId")
    tipo = data.get("tipo")
    motivo = data.get("motivo")

    if not employee_id or not tipo or not motivo or not str(motivo).strip():
        raise HTTPException(status_code=400, detail="Faltan campos requeridos")

    if tipo not in VALID_TIPOS:
        raise HTTPException(status_code=400, detail=f"tipo debe ser uno de: {VALID_TIPOS}")

    _check_self_or_admin(employee_id, current_user)

    ensure_table(db)

    empleado = db.execute(text("""
        SELECT officeId, departmentId FROM Employee WHERE id = :id
    """), {"id": employee_id}).mappings().first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO SolicitudReubicacion
            (employeeId, tipo, motivo, estado, officeIdActual, departmentIdActual, createdAt, updatedAt)
        OUTPUT INSERTED.id
        VALUES
            (:employeeId, :tipo, :motivo, 'Pendiente', :officeId, :departmentId, :now, :now)
    """), {
        "employeeId": employee_id, "tipo": tipo, "motivo": motivo,
        "officeId": empleado["officeId"], "departmentId": empleado["departmentId"],
        "now": now,
    })
    new_id = result.fetchone()[0]
    db.commit()

    return {"message": "Solicitud creada correctamente", "id": new_id}


# ─────────────────────────────────────────────────────────────────────────────
# GET /reubicacion/mis-solicitudes/{employee_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/mis-solicitudes/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_mis_solicitudes(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Historial de solicitudes de reubicacion del empleado, mas recientes primero."""
    _check_self_or_admin(employee_id, current_user)

    ensure_table(db)

    rows = db.execute(text("""
        SELECT id, employeeId, tipo, motivo, estado, officeIdActual, departmentIdActual, createdAt, updatedAt
        FROM SolicitudReubicacion
        WHERE employeeId = :employeeId
        ORDER BY createdAt DESC
    """), {"employeeId": employee_id}).mappings().all()

    return {
        "solicitudes": [
            {
                "id": r["id"],
                "employeeId": r["employeeId"],
                "tipo": r["tipo"],
                "motivo": r["motivo"],
                "estado": r["estado"],
                "officeIdActual": r["officeIdActual"],
                "departmentIdActual": r["departmentIdActual"],
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
                "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            }
            for r in rows
        ]
    }
```

- [ ] **Step 3: Registrar el router en `app/main.py`**

Cambiar la línea de import de routers:
```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules
```
por:
```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion
```

Y agregar, después de `app.include_router(schedules.router)`:
```python
app.include_router(reubicacion.router)
```

- [ ] **Step 4: Verificar que compila**

Run: `py -m py_compile app/database/reubicacion.py app/routes/reubicacion.py app/main.py`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
git add app/database/reubicacion.py app/routes/reubicacion.py app/main.py
git commit -m "feat: agregar solicitud de reubicacion (tabla, endpoints y registro del router)"
```

---

### Task 2: Frontend — pantalla "Solicitudes de Reubicación"

**Files:**
- Create: `src/app/screens/Reubicacion/Screen.tsx`
- Modify: `src/app/Interfas/Interfaces.ts`
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Navbar/Header.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `POST /reubicacion/request` (Task 1), `GET /reubicacion/mis-solicitudes/{employeeId}` (Task 1).
- Produces: componente `Reubicacion` (export default) con prop `{ employeeData: Employee | null }`, mismo shape que `MisDocumentos`.

- [ ] **Step 1: Extender el tipo `Page` en `Interfaces.ts`**

Ubicar:
```typescript
export type Page =
  | "estadisticas"
  | "recursos-humanos"
  | "configuracion-licencias"
  | "ia"
  | "organigrama"
  | "editar-perfil"
  | "feedback"
  | "licencias"
  | "documentos"
  | "test"
  | "admin";
```
y reemplazarlo por:
```typescript
export type Page =
  | "estadisticas"
  | "recursos-humanos"
  | "configuracion-licencias"
  | "ia"
  | "organigrama"
  | "editar-perfil"
  | "feedback"
  | "licencias"
  | "documentos"
  | "reubicacion"
  | "test"
  | "admin";
```

- [ ] **Step 2: Crear `src/app/screens/Reubicacion/Screen.tsx`**

```tsx
"use client";

import React, { useEffect, useState } from 'react';
import { ArrowLeftRight } from 'lucide-react';
import { Dropdown } from 'primereact/dropdown';
import { InputTextarea } from 'primereact/inputtextarea';
import { Button } from 'primereact/button';
import { Toast } from 'primereact/toast';
import { useRef } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { Employee } from '@/app/Interfas/Interfaces';

const TIPOS_SOLICITUD = [
  "Cambio de oficina",
  "Cambio de departamento",
  "Reubicación por desarrollo profesional",
  "Reubicación por clima laboral",
  "Reubicación por razones personales",
  "Otra",
];

interface SolicitudReubicacion {
  id: number;
  employeeId: number;
  tipo: string;
  motivo: string;
  estado: string;
  officeIdActual: number | null;
  departmentIdActual: number | null;
  createdAt: string;
  updatedAt: string;
}

interface ReubicacionProps {
  employeeData: Employee | null;
}

const ESTADO_CLASES: Record<string, string> = {
  'Pendiente': 'bg-warning-soft text-warning-soft-foreground border-warning',
  'En análisis': 'bg-primary/15 text-primary border-primary/30',
  'Recomendada': 'bg-primary/15 text-primary border-primary/30',
  'Aprobada': 'bg-success-soft text-success-soft-foreground border-success',
  'Rechazada': 'bg-error-soft text-error-soft-foreground border-error',
  'Ejecutada': 'bg-success-soft text-success-soft-foreground border-success',
};

const formatDate = (iso: string) => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
};

export default function Reubicacion({ employeeData }: ReubicacionProps) {
  const [solicitudes, setSolicitudes] = useState<SolicitudReubicacion[]>([]);
  const [loading, setLoading] = useState(true);
  const [tipo, setTipo] = useState<string | null>(null);
  const [motivo, setMotivo] = useState('');
  const [enviando, setEnviando] = useState(false);
  const toast = useRef<Toast>(null);

  const cargarSolicitudes = async () => {
    if (!employeeData?.id) return;
    setLoading(true);
    try {
      const res = await apiClient.get<{ solicitudes: SolicitudReubicacion[] }>(
        `/reubicacion/mis-solicitudes/${employeeData.id}`
      );
      setSolicitudes(res.solicitudes);
    } catch (err) {
      console.error('Error al cargar solicitudes de reubicacion:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    cargarSolicitudes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeData?.id]);

  const handleSubmit = async () => {
    if (!employeeData?.id || !tipo || !motivo.trim()) {
      toast.current?.show({ severity: 'warn', summary: 'Campos incompletos', detail: 'Seleccioná un tipo y escribí el motivo.', life: 3000 });
      return;
    }
    setEnviando(true);
    try {
      await apiClient.post('/reubicacion/request', {
        employeeId: employeeData.id,
        tipo,
        motivo: motivo.trim(),
      });
      toast.current?.show({ severity: 'success', summary: 'Enviado', detail: 'Solicitud de reubicación creada correctamente', life: 3000 });
      setTipo(null);
      setMotivo('');
      await cargarSolicitudes();
    } catch (err) {
      console.error('Error al crear solicitud de reubicacion:', err);
      toast.current?.show({ severity: 'error', summary: 'Error', detail: 'No se pudo crear la solicitud', life: 4000 });
    } finally {
      setEnviando(false);
    }
  };

  if (!employeeData) {
    return (
      <div className="bg-background font-sans min-h-screen flex items-center justify-center">
        <p className="text-muted-foreground">Cargando datos del empleado...</p>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen font-sans text-foreground p-4 sm:p-8">
      <Toast ref={toast} />
      <div className="max-w-3xl mx-auto space-y-6">
        <header className="mb-4 text-center">
          <h1 className="font-heading text-3xl font-bold text-foreground mb-2 flex items-center justify-center gap-2">
            <ArrowLeftRight className="text-primary" />
            Solicitudes de Reubicación
          </h1>
          <p className="text-muted-foreground">
            Solicitá un cambio de oficina, departamento, o una reubicación por otro motivo.
          </p>
        </header>

        <div className="bg-card rounded-xl border border-border shadow-sm p-6 space-y-4">
          <h2 className="font-heading text-lg font-semibold text-foreground">Nueva Solicitud</h2>
          <div>
            <label className="block text-sm font-semibold text-foreground mb-1">Tipo de solicitud</label>
            <Dropdown
              value={tipo}
              options={TIPOS_SOLICITUD}
              onChange={(e) => setTipo(e.value)}
              placeholder="Seleccioná un tipo"
              className="w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-foreground mb-1">Motivo</label>
            <InputTextarea
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              rows={4}
              className="w-full"
              placeholder="Contanos el motivo de tu solicitud..."
            />
          </div>
          <Button
            label="Enviar Solicitud"
            icon="pi pi-send"
            onClick={handleSubmit}
            disabled={enviando || !tipo || !motivo.trim()}
            className="w-full py-3"
          />
        </div>

        <div className="bg-card rounded-xl border border-border shadow-sm p-6">
          <h2 className="font-heading text-lg font-semibold text-foreground mb-4">Mis Solicitudes</h2>
          {loading ? (
            <p className="text-muted-foreground text-sm">Cargando...</p>
          ) : solicitudes.length === 0 ? (
            <p className="text-muted-foreground text-sm italic">Todavía no creaste ninguna solicitud de reubicación.</p>
          ) : (
            <ul className="space-y-3">
              {solicitudes.map((s) => (
                <li key={s.id} className="p-3 border border-border rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-semibold text-foreground text-sm">{s.tipo}</span>
                    <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full border ${ESTADO_CLASES[s.estado] ?? 'bg-muted text-muted-foreground border-border'}`}>
                      {s.estado}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{s.motivo}</p>
                  <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Agregar la entrada en `rbac.ts`**

Ubicar la entrada `id: "feedback"` en `PAGE_CONFIG` y agregar, justo después de su bloque de cierre `},`:

```typescript
  {
    id: "reubicacion",
    label: "Reubicación",
    icon: "ArrowLeftRight",
    section: "Gente",
    visibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH],
    accessibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH, ROLE_ID.USER],
  },
```

- [ ] **Step 4: Agregar la entrada en el menú de `Header.tsx`**

Ubicar el bloque:
```tsx
    {
      label: "Encuesta",
      icon: "pi pi-file-edit",
      className: "hover:bg-cyan-50",
      command: () => setPage("feedback"),
    },
    { separator: true },
```
y reemplazarlo por:
```tsx
    {
      label: "Encuesta",
      icon: "pi pi-file-edit",
      className: "hover:bg-cyan-50",
      command: () => setPage("feedback"),
    },
    {
      label: "Reubicación",
      icon: "pi pi-arrows-h",
      className: "hover:bg-cyan-50",
      command: () => setPage("reubicacion"),
    },
    { separator: true },
```

- [ ] **Step 5: Enganchar en `page.tsx`**

Agregar el import, junto a los demás imports de `screens/`:
```tsx
import Reubicacion from '@/app/screens/Reubicacion/Screen';
```

Agregar el case, después de `case 'documentos':`:
```tsx
      case 'documentos':
        return <MisDocumentos employeeData={employeeData} />;
      case 'reubicacion':
        return <Reubicacion employeeData={employeeData} />;
```

- [ ] **Step 6: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "screens/Reubicacion/Screen|Componentes/Navbar/Header|app/page\.tsx|util/rbac"`
Expected: sin salida (sin errores nuevos en estos archivos).

- [ ] **Step 7: Commit**

```bash
git add src/app/screens/Reubicacion/Screen.tsx src/app/Interfas/Interfaces.ts src/app/util/rbac.ts src/app/Componentes/Navbar/Header.tsx src/app/page.tsx
git commit -m "feat: agregar pantalla de Solicitudes de Reubicacion para el empleado"
```

---

### Task 3: Verificación manual

No hay test suite automatizado en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error (el router nuevo se registró correctamente).
- [ ] **Step 2:** `POST /reubicacion/request` con un `tipo` fuera de los 6 valores válidos devuelve 400.
- [ ] **Step 3:** `POST /reubicacion/request` con `motivo` vacío devuelve 400.
- [ ] **Step 4:** `POST /reubicacion/request` válido crea la fila con `estado='Pendiente'` y los snapshots de oficina/departamento correctos (comparar con `Employee.officeId`/`departmentId` de ese empleado).
- [ ] **Step 5:** Un empleado no puede crear una solicitud con `employeeId` de otro (403), salvo que sea Admin.
- [ ] **Step 6:** `GET /reubicacion/mis-solicitudes/{id}` devuelve solo las solicitudes de ese empleado, ordenadas por fecha descendente.
- [ ] **Step 7:** En el frontend, abrir el menú del header (ícono de perfil) y confirmar que aparece "Reubicación" para cualquier rol, incluido un empleado (USER).
- [ ] **Step 8:** Crear una solicitud desde la pantalla y confirmar que aparece en "Mis Solicitudes" con estado "Pendiente".
