# Feriados configurables por RRHH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que RRHH marque fechas puntuales como feriado de empresa, y que el calendario de licencias (`Calendario.tsx`) las excluya del conteo de días hábiles igual que los feriados públicos.

**Architecture:** Tabla `Feriado` creada de forma idempotente (mismo patrón que `app/database/academic_title_mapping.py`), 3 endpoints nuevos en el router existente `app/routes/licenses.py`, una tab nueva en `ConfiguracionLicencias/Screen.tsx` (formulario inline + tabla, sin modal — mismo patrón liviano ya usado en `DocumentsTab`), y una extensión del fetch de feriados en `Calendario.tsx` para mezclar feriados de empresa con los públicos en el mismo `holidayMap`.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server vía pyodbc (backend); Next.js, TypeScript, `@js-temporal/polyfill`, `apiClient` (frontend).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-feriados-configurables-design.md`
- La tabla se crea de forma idempotente (`IF NOT EXISTS`) e invocada **dentro de cada endpoint nuevo** — no se toca `app/main.py`.
- `GET /licenses/feriados` es `require_any_auth` (lo necesita cualquier empleado para que su calendario excluya correctamente los feriados de empresa); `POST`/`DELETE` son `require_rrhh_auth` (alias ya existente en `app/routes/licenses.py:16`: `require_roles(ROLE_ADMIN, ROLE_RRHH)`).
- No se toca `calcular_dias_vacaciones` ni la lógica de antigüedad — fuera de alcance.
- Cada feriado es una fecha puntual de un año específico — no hay recurrencia anual automática.
- No hay test suite automatizado en ninguno de los dos repos — verificación vía `python -c "import ..."`, `npx tsc --noEmit`, y un checklist manual.

---

### Task 1: Tabla `Feriado` y funciones de acceso a datos

**Files:**
- Create: `app/database/feriados.py`

**Interfaces:**
- Consumes: nada (módulo de datos puro).
- Produces: `ensure_table(db: Session) -> None`, `get_feriados(db: Session) -> list[dict]` (cada dict: `{"id", "fecha", "nombre"}`, solo activos), `save_feriado(db: Session, fecha: str, nombre: str) -> int` (retorna el `id` insertado), `delete_feriado(db: Session, feriado_id: int) -> bool`.

- [ ] **Step 1: Crear el módulo con la tabla y las funciones de acceso**

Archivo completo `app/database/feriados.py`:

```python
"""
Feriados de empresa configurables por RRHH -- fechas puntuales que se
excluyen del conteo de dias habiles en Calendario.tsx (frontend), junto
con los feriados publicos argentinos (traidos de una API externa).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'Feriado' AND xtype = 'U'
)
BEGIN
    CREATE TABLE Feriado (
        id        INT IDENTITY(1,1) PRIMARY KEY,
        fecha     DATE           NOT NULL,
        nombre    NVARCHAR(255)  NOT NULL,
        activo    BIT            NOT NULL DEFAULT 1,
        createdAt DATETIME2      NOT NULL
    );
    CREATE INDEX IX_Feriado_fecha ON Feriado (fecha);
END
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla Feriado si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def get_feriados(db: Session) -> list[dict]:
    """Lista feriados de empresa activos."""
    rows = db.execute(text("""
        SELECT id, fecha, nombre
        FROM Feriado
        WHERE activo = 1
        ORDER BY fecha ASC
    """)).mappings().all()
    return [dict(r) for r in rows]


def save_feriado(db: Session, fecha: str, nombre: str) -> int:
    """Inserta un nuevo feriado y retorna su id."""
    result = db.execute(text("""
        INSERT INTO Feriado (fecha, nombre, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:fecha, :nombre, 1, :createdAt)
    """), {"fecha": fecha, "nombre": nombre, "createdAt": datetime.utcnow()})
    new_id = result.scalar()
    db.commit()
    return new_id


def delete_feriado(db: Session, feriado_id: int) -> bool:
    """Soft delete de un feriado. Retorna False si no existia."""
    existing = db.execute(text("SELECT id FROM Feriado WHERE id = :id"), {"id": feriado_id}).fetchone()
    if not existing:
        return False
    db.execute(text("UPDATE Feriado SET activo = 0 WHERE id = :id"), {"id": feriado_id})
    db.commit()
    return True
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.database.feriados"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 3: Commit**

```bash
git add app/database/feriados.py
git commit -m "feat: agregar tabla Feriado y funciones de acceso a datos"
```

---

### Task 2: Endpoints en `licenses.py`

**Files:**
- Modify: `app/routes/licenses.py` (agregar import + 3 endpoints al final del archivo)

**Interfaces:**
- Consumes: `ensure_table`, `get_feriados`, `save_feriado`, `delete_feriado` de `app.database.feriados` (Task 1). `require_rrhh_auth` (ya existe en este archivo, línea 16).
- Produces: `GET /licenses/feriados` → `{"feriados": [...]}`. `POST /licenses/feriados` → `{"success": true, "id": int}`. `DELETE /licenses/feriados/{feriado_id}` → `{"success": true}` o 404.

- [ ] **Step 1: Agregar el import al inicio del archivo**

Antes (línea 1-7 de `app/routes/licenses.py`):
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from datetime import datetime, date, timedelta
from typing import Optional
```

Después:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, require_roles, ROLE_ADMIN, get_current_user
from datetime import datetime, date, timedelta
from typing import Optional
from app.database.feriados import (
    ensure_table as ensure_feriado_table,
    get_feriados as get_feriados_data,
    save_feriado as save_feriado_data,
    delete_feriado as delete_feriado_data,
)
```

- [ ] **Step 2: Agregar los 3 endpoints al final del archivo**

Agregar al final de `app/routes/licenses.py` (después del último `@router...` existente, el de `/aplicar`):

```python
# ---------------------------------------------------------------------------
# Feriados de empresa (configurables por RRHH)
# ---------------------------------------------------------------------------
@router.get("/feriados", dependencies=[Depends(require_any_auth)])
def list_feriados(db: Session = Depends(get_db)):
    """Lista los feriados de empresa activos."""
    ensure_feriado_table(db)
    try:
        return {"feriados": get_feriados_data(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener feriados: {str(e)}")


@router.post("/feriados", dependencies=[Depends(require_rrhh_auth)])
def create_feriado(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea un feriado de empresa."""
    ensure_feriado_table(db)
    fecha = data.get("fecha")
    nombre = data.get("nombre")

    if not fecha or not nombre:
        raise HTTPException(status_code=400, detail="fecha y nombre son requeridos")

    try:
        new_id = save_feriado_data(db, fecha, nombre)
        return {"success": True, "id": new_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar feriado: {str(e)}")


@router.delete("/feriados/{feriado_id}", dependencies=[Depends(require_rrhh_auth)])
def delete_feriado_endpoint(feriado_id: int, db: Session = Depends(get_db)):
    """Soft delete de un feriado de empresa."""
    ensure_feriado_table(db)
    try:
        deleted = delete_feriado_data(db, feriado_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Feriado no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar feriado: {str(e)}")
```

- [ ] **Step 3: Verificar que el servidor levanta sin errores de sintaxis**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.routes.licenses"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/licenses.py
git commit -m "feat: agregar endpoints CRUD de feriados de empresa en /licenses"
```

---

### Task 3: Frontend — tab "Feriados" en `ConfiguracionLicencias/Screen.tsx`

**Files:**
- Modify: `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`

**Interfaces:**
- Consumes: `GET /licenses/feriados`, `POST /licenses/feriados`, `DELETE /licenses/feriados/{id}` (Task 2). `apiClient` (ya importado en este archivo). `showToast` (ya existe en este archivo).
- Produces: nada consumido por otros archivos en esta tarea — Task 4 consume el endpoint directamente, no este componente.

- [ ] **Step 1: Agregar la interfaz `Feriado` y el valor `'feriados'` a `TabId`**

Antes (líneas 46-59 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`):
```tsx
interface Horario {
    id?: number;
    horaInicio: number;
    horaFin: number;
    horasTrabajo?: number;
}

type TabId = 'licencias' | 'contratos' | 'profesiones' | 'habilidades' | 'horarios';
```

Después:
```tsx
interface Horario {
    id?: number;
    horaInicio: number;
    horaFin: number;
    horasTrabajo?: number;
}

interface Feriado {
    id: number;
    fecha: string;
    nombre: string;
}

type TabId = 'licencias' | 'contratos' | 'profesiones' | 'habilidades' | 'horarios' | 'feriados';
```

- [ ] **Step 2: Agregar el estado de la lista de feriados y del formulario de alta**

Antes (líneas 91-96 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`):
```tsx
    // Data lists
    const [configuraciones, setConfiguraciones] = useState<ConfiguracionLicencia[]>([]);
    const [contracts, setContracts] = useState<ContractType[]>([]);
    const [professions, setProfessions] = useState<Profession[]>([]);
    const [softSkills, setSoftSkills] = useState<SoftSkill[]>([]);
    const [jornadas, setJornadas] = useState<JornadaLaboral[]>([]);
```

Después:
```tsx
    // Data lists
    const [configuraciones, setConfiguraciones] = useState<ConfiguracionLicencia[]>([]);
    const [contracts, setContracts] = useState<ContractType[]>([]);
    const [professions, setProfessions] = useState<Profession[]>([]);
    const [softSkills, setSoftSkills] = useState<SoftSkill[]>([]);
    const [jornadas, setJornadas] = useState<JornadaLaboral[]>([]);
    const [feriados, setFeriados] = useState<Feriado[]>([]);
    const [newFeriadoFecha, setNewFeriadoFecha] = useState("");
    const [newFeriadoNombre, setNewFeriadoNombre] = useState("");
```

- [ ] **Step 3: Cargar feriados en `loadAllData`**

Antes (líneas 125-144 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`):
```tsx
    const loadAllData = async () => {
        setLoading(true);
        try {
            const [licRes, conRes, profRes, softRes, schedRes] = await Promise.all([
                apiClient.get<{ configuraciones: ConfiguracionLicencia[] }>('/licenses/configuracion'),
                apiClient.get<{ types: ContractType[] }>('/contracts/types'),
                apiClient.get<{ professions: Profession[] }>('/professions'),
                apiClient.get<SoftSkill[]>('/configtest/soft'),
                apiClient.get<{ jornadas: JornadaLaboral[], horarios: Horario[] }>('/schedules/regimes')
            ]);
            setConfiguraciones(licRes.configuraciones || []);
            setContracts(conRes.types || []);
            setProfessions(profRes.professions || []);
            setSoftSkills(softRes || []);
            setJornadas(schedRes.jornadas || []);
        } catch (error: any) {
            showToast(error.message || "Error al cargar configuraciones", "error");
        } finally {
            setLoading(false);
        }
    };
```

Después:
```tsx
    const loadAllData = async () => {
        setLoading(true);
        try {
            const [licRes, conRes, profRes, softRes, schedRes, ferRes] = await Promise.all([
                apiClient.get<{ configuraciones: ConfiguracionLicencia[] }>('/licenses/configuracion'),
                apiClient.get<{ types: ContractType[] }>('/contracts/types'),
                apiClient.get<{ professions: Profession[] }>('/professions'),
                apiClient.get<SoftSkill[]>('/configtest/soft'),
                apiClient.get<{ jornadas: JornadaLaboral[], horarios: Horario[] }>('/schedules/regimes'),
                apiClient.get<{ feriados: Feriado[] }>('/licenses/feriados')
            ]);
            setConfiguraciones(licRes.configuraciones || []);
            setContracts(conRes.types || []);
            setProfessions(profRes.professions || []);
            setSoftSkills(softRes || []);
            setJornadas(schedRes.jornadas || []);
            setFeriados(ferRes.feriados || []);
        } catch (error: any) {
            showToast(error.message || "Error al cargar configuraciones", "error");
        } finally {
            setLoading(false);
        }
    };
```

- [ ] **Step 4: Agregar los handlers de alta y baja, justo antes de `// --- Tab Button Component ---`**

Antes (líneas 149-150 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`):
```tsx

    // --- Tab Button Component ---
```

Después:
```tsx

    // --- Feriados Handlers ---
    const handleAddFeriado = async () => {
        if (!newFeriadoFecha || !newFeriadoNombre.trim()) return;
        try {
            await apiClient.post('/licenses/feriados', { fecha: newFeriadoFecha, nombre: newFeriadoNombre.trim() });
            showToast("Feriado creado", "success");
            setNewFeriadoFecha("");
            setNewFeriadoNombre("");
            loadAllData();
        } catch (error: any) {
            showToast(error.message || "Error al guardar feriado", "error");
        }
    };

    const handleDeleteFeriado = async (id: number) => {
        try {
            await apiClient.delete(`/licenses/feriados/${id}`);
            showToast("Feriado eliminado", "success");
            loadAllData();
        } catch (error: any) {
            showToast(error.message || "Error al eliminar feriado", "error");
        }
    };

    // --- Tab Button Component ---
```

- [ ] **Step 5: Agregar el botón de la tab nueva en la navegación**

Antes (líneas 350-356 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx`):
```tsx
                <nav className="flex space-x-1 overflow-x-auto">
                    <TabButton id="licencias" label="Reglas de Licencias" icon={Settings} />
                    <TabButton id="contratos" label="Tipos de Contrato" icon={Briefcase} />
                    <TabButton id="profesiones" label="Profesiones y Cargos" icon={GraduationCap} />
                    <TabButton id="habilidades" label="Habilidades Blandas" icon={Award} />
                    <TabButton id="horarios" label="Régimen Horario" icon={ClockIcon} />
                </nav>
```

Después:
```tsx
                <nav className="flex space-x-1 overflow-x-auto">
                    <TabButton id="licencias" label="Reglas de Licencias" icon={Settings} />
                    <TabButton id="contratos" label="Tipos de Contrato" icon={Briefcase} />
                    <TabButton id="profesiones" label="Profesiones y Cargos" icon={GraduationCap} />
                    <TabButton id="habilidades" label="Habilidades Blandas" icon={Award} />
                    <TabButton id="horarios" label="Régimen Horario" icon={ClockIcon} />
                    <TabButton id="feriados" label="Feriados" icon={Settings} />
                </nav>
```

- [ ] **Step 6: Agregar el contenido de la tab, justo después del bloque de TAB 5 (HORARIOS)**

Antes (líneas 564-568 de `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx` — el cierre del bloque de la tab "horarios", seguido del cierre del contenedor principal):
```tsx
                            </div>
                        )}
                    </div>
                )}
            </div>
```

Después (se inserta el bloque nuevo entre el `)}` que cierra la tab "horarios" y el `</div>` que cierra el contenedor principal — el bloque nuevo queda DENTRO de `<div className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden p-6">`):
```tsx
                            </div>
                        )}

                        {/* ── TAB 6: FERIADOS ─────────────────────────────────────────── */}
                        {activeTab === 'feriados' && (
                            <div>
                                <h2 className="font-heading text-lg font-bold text-foreground mb-2">Feriados de Empresa</h2>
                                <p className="text-sm text-muted-foreground mb-4">
                                    Fechas puntuales que se excluyen del conteo de días hábiles en el calendario de licencias, además de los feriados públicos.
                                </p>

                                <div className="flex flex-col sm:flex-row gap-3 mb-6">
                                    <input
                                        type="date"
                                        value={newFeriadoFecha}
                                        onChange={(e) => setNewFeriadoFecha(e.target.value)}
                                        className="px-3 py-2 rounded-md border border-border bg-background text-foreground"
                                    />
                                    <input
                                        type="text"
                                        placeholder="Nombre (ej. Cierre administrativo)"
                                        value={newFeriadoNombre}
                                        onChange={(e) => setNewFeriadoNombre(e.target.value)}
                                        className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground"
                                    />
                                    <button
                                        onClick={handleAddFeriado}
                                        className="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 font-semibold"
                                    >
                                        Agregar
                                    </button>
                                </div>

                                {feriados.length === 0 ? (
                                    <p className="text-muted-foreground italic">No hay feriados de empresa configurados.</p>
                                ) : (
                                    <table className="w-full text-sm">
                                        <thead>
                                            <tr className="text-left text-muted-foreground border-b border-border">
                                                <th className="py-2">Fecha</th>
                                                <th className="py-2">Nombre</th>
                                                <th className="py-2"></th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {feriados.map(f => (
                                                <tr key={f.id} className="border-b border-border">
                                                    <td className="py-2 text-foreground">{f.fecha}</td>
                                                    <td className="py-2 text-foreground">{f.nombre}</td>
                                                    <td className="py-2 text-right">
                                                        <button
                                                            onClick={() => handleDeleteFeriado(f.id)}
                                                            className="text-error hover:opacity-80"
                                                        >
                                                            Eliminar
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
```

- [ ] **Step 7: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "ConfiguracionLicencias/Screen"`
Expected: mismos 2 errores preexistentes ya documentados en reportes anteriores de este archivo (`Property 'id' does not exist on type 'SoftSkill'`, líneas ~281/284), ningún error nuevo.

- [ ] **Step 8: Commit**

```bash
git add src/app/screens/ConfiguracionLicencias/Screen.tsx
git commit -m "feat: agregar tab Feriados de Empresa a ConfiguracionLicencias"
```

---

### Task 4: Frontend — mezclar feriados de empresa en `Calendario.tsx`

**Files:**
- Modify: `RRHH/src/app/GestionLicencias/Calendario.tsx`

**Interfaces:**
- Consumes: `GET /licenses/feriados` (Task 2). `apiClient` (no usado hoy en este archivo — se agrega el import). `processHolidays`, `HolidayApi` (ya importados desde `@/app/lib/dates`, sin cambios a esas funciones).
- Produces: nada consumido por otros archivos.

- [ ] **Step 1: Agregar el import de `apiClient`**

Antes (líneas 1-15 de `RRHH/src/app/GestionLicencias/Calendario.tsx`):
```tsx
'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Temporal } from '@js-temporal/polyfill';
import { Calendar } from 'primereact/calendar';
import { addLocale, type LocaleOptions } from 'primereact/api';
import { CalendarDays, X } from 'lucide-react';
import {
  type HolidayApi,
  type PlainHoliday,
  processHolidays,
  countBusinessDays,
  toNativeDate,
  fromNativeDate,
} from '@/app/lib/dates';
```

Después:
```tsx
'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Temporal } from '@js-temporal/polyfill';
import { Calendar } from 'primereact/calendar';
import { addLocale, type LocaleOptions } from 'primereact/api';
import { CalendarDays, X } from 'lucide-react';
import { apiClient } from '@/app/util/apiClient';
import {
  type HolidayApi,
  type PlainHoliday,
  processHolidays,
  countBusinessDays,
  toNativeDate,
  fromNativeDate,
} from '@/app/lib/dates';
```

- [ ] **Step 2: Mezclar feriados de empresa con los públicos**

Antes (líneas 59-68 de `RRHH/src/app/GestionLicencias/Calendario.tsx`):
```tsx
  // ── Fetch feriados ──────────────────────────────────────────────────────────
  useEffect(() => {
    const year = Temporal.Now.plainDateISO().year;

    fetch(`https://api.argentinadatos.com/v1/feriados/${year}`)
      .then(r => { if (!r.ok) throw new Error('Error al obtener feriados'); return r.json(); })
      .then((data: HolidayApi[]) => setHolidayMap(processHolidays(data)))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);
```

Después:
```tsx
  // ── Fetch feriados (públicos + de empresa) ────────────────────────────────────
  useEffect(() => {
    const year = Temporal.Now.plainDateISO().year;

    Promise.all([
      fetch(`https://api.argentinadatos.com/v1/feriados/${year}`)
        .then(r => { if (!r.ok) throw new Error('Error al obtener feriados públicos'); return r.json(); })
        .then((data: HolidayApi[]) => data)
        .catch(err => { console.error(err); return [] as HolidayApi[]; }),
      apiClient.get<{ feriados: { id: number; fecha: string; nombre: string }[] }>('/licenses/feriados')
        .then(res => res.feriados.map(f => ({ fecha: f.fecha, tipo: 'Empresa', nombre: f.nombre } as HolidayApi)))
        .catch(err => { console.error(err); return [] as HolidayApi[]; }),
    ])
      .then(([publicos, empresa]) => setHolidayMap(processHolidays([...publicos, ...empresa])))
      .finally(() => setLoading(false));
  }, []);
```

- [ ] **Step 3: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "GestionLicencias/Calendario"`
Expected: ningún resultado (sin errores nuevos en este archivo).

- [ ] **Step 4: Commit**

```bash
git add src/app/GestionLicencias/Calendario.tsx
git commit -m "feat: incluir feriados de empresa en el calculo de dias habiles del calendario"
```

---

### Task 5: Verificación manual end-to-end

**Files:** ninguno (solo verificación, no produce commits de código).

**Interfaces:**
- Consumes: el flujo completo de las Tasks 1-4.
- Produces: confirmación de que el comportamiento documentado en la spec se cumple.

- [ ] **Step 1: Levantar ambos servidores**

Backend: `uvicorn app.main:app --reload` (desde `Backend_RRHH`)
Frontend: `npm run dev` (desde `RRHH`)

- [ ] **Step 2: Agregar un feriado de empresa**

Como RRHH, en ConfiguracionLicencias → tab "Feriados", agregar uno con una fecha futura (ej. dentro del próximo mes) y un nombre. Confirmar que aparece en la tabla.

- [ ] **Step 3: Confirmar exclusión en el calendario**

Como cualquier empleado, abrir el formulario de nueva solicitud de licencia (el que usa `Calendario.tsx` / `DateRangePicker`). Seleccionar un rango de fechas que incluya el feriado recién creado. Confirmar que el día aparece marcado visualmente como feriado y que el conteo de "días hábiles" no lo cuenta.

- [ ] **Step 4: Eliminar el feriado**

Desde RRHH, eliminar el feriado de prueba. Confirmar que desaparece de la tabla y que, al volver a seleccionar el mismo rango de fechas en el calendario (puede requerir recargar la página), ese día vuelve a contarse como hábil.

- [ ] **Step 5: Confirmar permisos**

Como empleado no-RRHH/Admin, intentar `POST /licenses/feriados` (vía `curl` o similar) — debe devolver 403. `GET /licenses/feriados` debe funcionar para cualquier usuario autenticado.
