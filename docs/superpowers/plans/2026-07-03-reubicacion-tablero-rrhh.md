# Reubicación — Tablero de RRHH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Segundo subsistema del módulo de Reubicación Inteligente: tablero de RRHH (lista filtrable de todas las solicitudes) con acciones Aprobar/Rechazar que notifican al empleado.

**Architecture:** Se agrega una columna `observacion` a `SolicitudReubicacion` (idempotente vía `ensure_table`), 2 endpoints nuevos en `app/routes/reubicacion.py` (mismo archivo del subsistema 1), y en el frontend una pantalla nueva `screens/ReubicacionTablero/Screen.tsx` enganchada por rol en el mismo `case 'reubicacion'` de `page.tsx` que ya usa la pantalla del empleado.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- En este subsistema, RRHH solo puede setear `estado` a `"Aprobada"` o `"Rechazada"`. Los estados `"Pendiente"` (subsistema 1), `"En análisis"`/`"Recomendada"` (subsistema 3, IA) y `"Ejecutada"` (subsistema 4, organigrama) no se tocan aquí.
- Al aprobar/rechazar se inserta un `Message` activo para el empleado, mismo patrón que `licenses.py` (`INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt) VALUES (..., 'active', GETDATE())`).
- `require_rrhh_auth` para los 2 endpoints nuevos (mismo patrón que `licenses.py`: `ROLE_RRHH = ROLE_ADMIN`, `require_roles(ROLE_ADMIN, ROLE_RRHH)`).
- Filtros del subsistema: `estado`, `officeId`, `departmentId`, `fechaDesde`/`fechaHasta`. Antigüedad y Profesión quedan fuera de alcance.
- No se modifica ningún otro endpoint de `reubicacion.py` (`/request`, `/mis-solicitudes/{id}`).

---

### Task 1: Backend — columna `observacion`, filtros y aprobar/rechazar

**Files:**
- Modify: `app/database/reubicacion.py`
- Modify: `app/routes/reubicacion.py`

**Interfaces:**
- Produces: `GET /reubicacion/solicitudes` (`require_rrhh_auth`) → `{"solicitudes": [{id, employeeId, employeeName, tipo, motivo, estado, observacion, officeIdActual, officeName, departmentIdActual, departmentName, createdAt, updatedAt}]}`. `PATCH /reubicacion/{solicitud_id}/estado` (`require_rrhh_auth`) → `{"message": str, "estado": str}`.

- [ ] **Step 1: Agregar la columna `observacion` en `ensure_table` (`app/database/reubicacion.py`)**

Reemplazar:
```python
def ensure_table(db: Session) -> None:
    """Crea SolicitudReubicacion si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()
```
por:
```python
def ensure_table(db: Session) -> None:
    """Crea SolicitudReubicacion si no existe, y agrega la columna
    observacion si la tabla ya existia sin ella (idempotente)."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text("""
        IF COL_LENGTH('SolicitudReubicacion', 'observacion') IS NULL
            ALTER TABLE SolicitudReubicacion ADD observacion NVARCHAR(MAX) NULL;
    """))
    db.commit()
```

- [ ] **Step 2: Agregar imports y `require_rrhh_auth` en `app/routes/reubicacion.py`**

Reemplazar:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])
```
por:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)
```

- [ ] **Step 3: Agregar `GET /reubicacion/solicitudes` al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /reubicacion/solicitudes — tablero de RRHH
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/solicitudes", dependencies=[Depends(require_rrhh_auth)])
def get_solicitudes(
    estado: Optional[str] = None,
    officeId: Optional[int] = None,
    departmentId: Optional[int] = None,
    fechaDesde: Optional[str] = None,
    fechaHasta: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Lista todas las solicitudes de reubicacion, con filtros opcionales."""
    ensure_table(db)

    query = """
        SELECT
            sr.id, sr.employeeId, e.name AS employeeName,
            sr.tipo, sr.motivo, sr.estado, sr.observacion,
            sr.officeIdActual, o.nombre AS officeName,
            sr.departmentIdActual, d.nombre AS departmentName,
            sr.createdAt, sr.updatedAt
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        LEFT JOIN Office o ON o.id = sr.officeIdActual
        LEFT JOIN Department d ON d.id = sr.departmentIdActual
        WHERE 1=1
    """
    params = {}
    if estado:
        query += " AND sr.estado = :estado"
        params["estado"] = estado
    if officeId:
        query += " AND sr.officeIdActual = :officeId"
        params["officeId"] = officeId
    if departmentId:
        query += " AND sr.departmentIdActual = :departmentId"
        params["departmentId"] = departmentId
    if fechaDesde:
        query += " AND sr.createdAt >= :fechaDesde"
        params["fechaDesde"] = fechaDesde
    if fechaHasta:
        query += " AND sr.createdAt <= :fechaHasta"
        params["fechaHasta"] = f"{fechaHasta} 23:59:59"

    query += " ORDER BY sr.createdAt DESC"

    rows = db.execute(text(query), params).mappings().all()

    return {
        "solicitudes": [
            {
                "id": r["id"],
                "employeeId": r["employeeId"],
                "employeeName": r["employeeName"],
                "tipo": r["tipo"],
                "motivo": r["motivo"],
                "estado": r["estado"],
                "observacion": r["observacion"],
                "officeIdActual": r["officeIdActual"],
                "officeName": r["officeName"],
                "departmentIdActual": r["departmentIdActual"],
                "departmentName": r["departmentName"],
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
                "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/estado — aprobar/rechazar
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/estado", dependencies=[Depends(require_rrhh_auth)])
def update_estado(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Aprueba o rechaza una solicitud de reubicacion, notificando al empleado."""
    estado = data.get("estado")
    observacion = data.get("observacion")

    if estado not in ("Aprobada", "Rechazada"):
        raise HTTPException(status_code=400, detail="estado debe ser 'Aprobada' o 'Rechazada'")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id, employeeId, tipo FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = :estado, observacion = :observacion, updatedAt = :now
        WHERE id = :id
    """), {"estado": estado, "observacion": observacion, "now": now, "id": solicitud_id})

    msg_text = f"Tu solicitud de reubicación ({solicitud['tipo']}) fue {estado} por RRHH."
    if observacion:
        msg_text += f" Observación: {observacion}"

    db.execute(text("""
        INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
        VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
    """), {"empId": solicitud["employeeId"], "msg": msg_text, "now": now})

    db.commit()

    return {"message": "Solicitud actualizada", "estado": estado}
```

- [ ] **Step 4: Verificar que compila**

Run: `py -m py_compile app/database/reubicacion.py app/routes/reubicacion.py`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
git add app/database/reubicacion.py app/routes/reubicacion.py
git commit -m "feat: agregar tablero de RRHH para reubicacion (listado con filtros y aprobar/rechazar)"
```

---

### Task 2: Frontend — pantalla del tablero + ruteo por rol

**Files:**
- Create: `src/app/screens/ReubicacionTablero/Screen.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `GET /reubicacion/solicitudes` (con query params `estado`, `officeId`, `departmentId`, `fechaDesde`, `fechaHasta`), `PATCH /reubicacion/{id}/estado` (Task 1). `GET /departments/` (ya existe, devuelve `{"departments": [{id, nombre, offices: [{id, nombre, ...}], ...}], "message": ...}`).
- Produces: componente `ReubicacionTablero` (export default), sin props (autocontenido).

- [ ] **Step 1: Crear `src/app/screens/ReubicacionTablero/Screen.tsx`**

```tsx
"use client";

import React, { useEffect, useState, useCallback } from 'react';
import { Dropdown } from 'primereact/dropdown';
import { Dialog } from 'primereact/dialog';
import { InputTextarea } from 'primereact/inputtextarea';
import { Button } from 'primereact/button';
import { Toast } from 'primereact/toast';
import { useRef } from 'react';
import { LayoutGrid, List } from 'lucide-react';
import { apiClient } from '@/app/util/apiClient';

const ESTADOS = ['Pendiente', 'En análisis', 'Recomendada', 'Aprobada', 'Rechazada', 'Ejecutada'];

const ESTADO_CLASES: Record<string, string> = {
  'Pendiente': 'bg-warning-soft text-warning-soft-foreground border-warning',
  'En análisis': 'bg-primary/15 text-primary border-primary/30',
  'Recomendada': 'bg-primary/15 text-primary border-primary/30',
  'Aprobada': 'bg-success-soft text-success-soft-foreground border-success',
  'Rechazada': 'bg-error-soft text-error-soft-foreground border-error',
  'Ejecutada': 'bg-success-soft text-success-soft-foreground border-success',
};

interface SolicitudRRHH {
  id: number;
  employeeId: number;
  employeeName: string;
  tipo: string;
  motivo: string;
  estado: string;
  observacion: string | null;
  officeIdActual: number | null;
  officeName: string | null;
  departmentIdActual: number | null;
  departmentName: string | null;
  createdAt: string;
  updatedAt: string;
}

interface DepartmentOption {
  id: number;
  nombre: string;
  offices: { id: number; nombre: string }[];
}

const formatDate = (iso: string) => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
};

export default function ReubicacionTablero() {
  const [solicitudes, setSolicitudes] = useState<SolicitudRRHH[]>([]);
  const [departments, setDepartments] = useState<DepartmentOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [vista, setVista] = useState<'kanban' | 'tabla'>('kanban');

  const [filtroEstado, setFiltroEstado] = useState<string | null>(null);
  const [filtroOffice, setFiltroOffice] = useState<number | null>(null);
  const [filtroDepartment, setFiltroDepartment] = useState<number | null>(null);
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');

  const [seleccionada, setSeleccionada] = useState<{ solicitud: SolicitudRRHH; accion: 'Aprobada' | 'Rechazada' } | null>(null);
  const [observacion, setObservacion] = useState('');
  const [guardando, setGuardando] = useState(false);
  const toast = useRef<Toast>(null);

  useEffect(() => {
    apiClient
      .get<{ departments: DepartmentOption[] }>('/departments/')
      .then((res) => setDepartments(res.departments))
      .catch((err) => console.error('Error al cargar departamentos:', err));
  }, []);

  const officeOptions = departments.flatMap((d) => d.offices.map((o) => ({ label: o.nombre, value: o.id })));
  const departmentOptions = departments.map((d) => ({ label: d.nombre, value: d.id }));

  const cargarSolicitudes = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filtroEstado) params.set('estado', filtroEstado);
      if (filtroOffice) params.set('officeId', String(filtroOffice));
      if (filtroDepartment) params.set('departmentId', String(filtroDepartment));
      if (fechaDesde) params.set('fechaDesde', fechaDesde);
      if (fechaHasta) params.set('fechaHasta', fechaHasta);

      const query = params.toString();
      const res = await apiClient.get<{ solicitudes: SolicitudRRHH[] }>(
        `/reubicacion/solicitudes${query ? `?${query}` : ''}`
      );
      setSolicitudes(res.solicitudes);
    } catch (err) {
      console.error('Error al cargar solicitudes de reubicacion:', err);
    } finally {
      setLoading(false);
    }
  }, [filtroEstado, filtroOffice, filtroDepartment, fechaDesde, fechaHasta]);

  useEffect(() => {
    cargarSolicitudes();
  }, [cargarSolicitudes]);

  const abrirAccion = (solicitud: SolicitudRRHH, accion: 'Aprobada' | 'Rechazada') => {
    setSeleccionada({ solicitud, accion });
    setObservacion('');
  };

  const confirmarAccion = async () => {
    if (!seleccionada) return;
    setGuardando(true);
    try {
      await apiClient.patch(`/reubicacion/${seleccionada.solicitud.id}/estado`, {
        estado: seleccionada.accion,
        observacion: observacion.trim() || null,
      });
      toast.current?.show({ severity: 'success', summary: 'Actualizado', detail: `Solicitud ${seleccionada.accion.toLowerCase()}`, life: 3000 });
      setSeleccionada(null);
      await cargarSolicitudes();
    } catch (err) {
      console.error('Error al actualizar solicitud:', err);
      toast.current?.show({ severity: 'error', summary: 'Error', detail: 'No se pudo actualizar la solicitud', life: 4000 });
    } finally {
      setGuardando(false);
    }
  };

  const puedeAccionar = (estado: string) => estado === 'Pendiente' || estado === 'Recomendada';

  const AccionesSolicitud = ({ s }: { s: SolicitudRRHH }) => (
    puedeAccionar(s.estado) ? (
      <div className="flex gap-2 mt-2">
        <Button label="Aprobar" icon="pi pi-check" severity="success" size="small" onClick={() => abrirAccion(s, 'Aprobada')} />
        <Button label="Rechazar" icon="pi pi-times" severity="danger" size="small" onClick={() => abrirAccion(s, 'Rechazada')} />
      </div>
    ) : null
  );

  return (
    <div className="bg-background min-h-screen font-sans text-foreground p-4 sm:p-8">
      <Toast ref={toast} />
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground mb-1">Solicitudes de Reubicación</h1>
            <p className="text-muted-foreground">Tablero de RRHH para gestionar la movilidad interna.</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setVista('kanban')}
              className={`p-2 rounded-lg border ${vista === 'kanban' ? 'bg-primary/15 border-primary text-primary' : 'border-border text-muted-foreground'}`}
              title="Vista Kanban"
            >
              <LayoutGrid size={18} />
            </button>
            <button
              onClick={() => setVista('tabla')}
              className={`p-2 rounded-lg border ${vista === 'tabla' ? 'bg-primary/15 border-primary text-primary' : 'border-border text-muted-foreground'}`}
              title="Vista Tabla"
            >
              <List size={18} />
            </button>
          </div>
        </header>

        <div className="bg-card border border-border rounded-xl p-4 flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Estado</label>
            <Dropdown
              value={filtroEstado}
              options={ESTADOS.map((e) => ({ label: e, value: e }))}
              onChange={(e) => setFiltroEstado(e.value)}
              showClear
              placeholder="Todos"
              className="w-48"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Departamento</label>
            <Dropdown
              value={filtroDepartment}
              options={departmentOptions}
              onChange={(e) => setFiltroDepartment(e.value)}
              showClear
              placeholder="Todos"
              className="w-48"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Oficina</label>
            <Dropdown
              value={filtroOffice}
              options={officeOptions}
              onChange={(e) => setFiltroOffice(e.value)}
              showClear
              placeholder="Todas"
              className="w-48"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Desde</label>
            <input type="date" value={fechaDesde} onChange={(e) => setFechaDesde(e.target.value)} className="px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1">Hasta</label>
            <input type="date" value={fechaHasta} onChange={(e) => setFechaHasta(e.target.value)} className="px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm" />
          </div>
        </div>

        {loading ? (
          <p className="text-muted-foreground text-center py-8">Cargando...</p>
        ) : vista === 'kanban' ? (
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
            {ESTADOS.map((estado) => (
              <div key={estado} className="bg-card border border-border rounded-xl p-3 space-y-3 min-h-[200px]">
                <h3 className="font-heading text-sm font-semibold text-foreground">{estado}</h3>
                {solicitudes.filter((s) => s.estado === estado).map((s) => (
                  <div key={s.id} className="p-3 border border-border rounded-lg bg-background">
                    <p className="font-semibold text-sm text-foreground">{s.employeeName}</p>
                    <p className="text-xs text-muted-foreground">{s.tipo}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{s.motivo}</p>
                    <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                    <AccionesSolicitud s={s} />
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-2 px-3">Empleado</th>
                  <th className="py-2 px-3">Tipo</th>
                  <th className="py-2 px-3">Motivo</th>
                  <th className="py-2 px-3">Oficina / Depto</th>
                  <th className="py-2 px-3">Estado</th>
                  <th className="py-2 px-3">Fecha</th>
                  <th className="py-2 px-3">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {solicitudes.map((s) => (
                  <tr key={s.id} className="border-b border-border">
                    <td className="py-2 px-3 text-foreground">{s.employeeName}</td>
                    <td className="py-2 px-3 text-foreground">{s.tipo}</td>
                    <td className="py-2 px-3 text-muted-foreground max-w-xs truncate">{s.motivo}</td>
                    <td className="py-2 px-3 text-muted-foreground">{s.officeName ?? '—'} / {s.departmentName ?? '—'}</td>
                    <td className="py-2 px-3">
                      <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full border ${ESTADO_CLASES[s.estado] ?? 'bg-muted text-muted-foreground border-border'}`}>
                        {s.estado}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-muted-foreground">{formatDate(s.createdAt)}</td>
                    <td className="py-2 px-3"><AccionesSolicitud s={s} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {solicitudes.length === 0 && (
              <p className="text-center text-muted-foreground py-8">No hay solicitudes con estos filtros.</p>
            )}
          </div>
        )}
      </div>

      <Dialog
        header={seleccionada ? `${seleccionada.accion === 'Aprobada' ? 'Aprobar' : 'Rechazar'} solicitud de ${seleccionada.solicitud.employeeName}` : ''}
        visible={!!seleccionada}
        onHide={() => setSeleccionada(null)}
        style={{ width: '30rem' }}
        modal
      >
        <div className="space-y-3">
          <label className="block text-sm font-semibold text-foreground">Observación (opcional)</label>
          <InputTextarea value={observacion} onChange={(e) => setObservacion(e.target.value)} rows={4} className="w-full" />
          <div className="flex justify-end gap-2 pt-2">
            <Button label="Cancelar" className="p-button-text" onClick={() => setSeleccionada(null)} />
            <Button
              label="Confirmar"
              severity={seleccionada?.accion === 'Aprobada' ? 'success' : 'danger'}
              loading={guardando}
              onClick={confirmarAccion}
            />
          </div>
        </div>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 2: Enganchar el ruteo por rol en `page.tsx`**

Ubicar la línea de import:
```tsx
import Reubicacion from '@/app/screens/Reubicacion/Screen';
```
y agregar debajo:
```tsx
import ReubicacionTablero from '@/app/screens/ReubicacionTablero/Screen';
```

Ubicar el bloque:
```tsx
      case 'reubicacion':
        return <Reubicacion employeeData={employeeData} />;
```
y reemplazarlo por:
```tsx
      case 'reubicacion':
        return roleId === ROLE_ID.ADMIN || roleId === ROLE_ID.RRHH
          ? <ReubicacionTablero />
          : <Reubicacion employeeData={employeeData} />;
```

- [ ] **Step 3: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "screens/ReubicacionTablero/Screen|app/page\.tsx"`
Expected: sin salida (sin errores nuevos en estos 2 archivos).

- [ ] **Step 4: Commit**

```bash
git add src/app/screens/ReubicacionTablero/Screen.tsx src/app/page.tsx
git commit -m "feat: agregar tablero de RRHH para gestionar solicitudes de reubicacion"
```

---

### Task 3: Verificación manual

No hay test suite automatizado en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `GET /reubicacion/solicitudes` (como RRHH/Admin) devuelve todas las solicitudes con `employeeName`/`officeName`/`departmentName`; un usuario USER recibe 403.
- [ ] **Step 3:** Los filtros `estado`, `officeId`, `departmentId`, `fechaDesde`/`fechaHasta` acotan el resultado, individualmente y combinados.
- [ ] **Step 4:** `PATCH /reubicacion/{id}/estado` con un `estado` distinto de Aprobada/Rechazada devuelve 400; con un `id` inexistente devuelve 404.
- [ ] **Step 5:** `PATCH` válido cambia el estado, guarda la `observacion`, y el empleado ve la notificación en la campanita del header al loguearse.
- [ ] **Step 6:** En el frontend, loguearse como RRHH/Admin y confirmar que la entrada "Reubicación" del menú muestra el tablero (no el formulario del empleado); loguearse como un empleado y confirmar que sigue viendo su formulario.
- [ ] **Step 7:** El toggle Kanban/Tabla funciona en ambas direcciones; Aprobar/Rechazar abre el diálogo, guarda, y el tablero refleja el nuevo estado tras recargar.
