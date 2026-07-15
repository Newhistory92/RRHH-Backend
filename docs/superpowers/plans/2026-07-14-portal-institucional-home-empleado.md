# Portal Institucional — Home del Empleado Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Segundo subsistema del Portal Institucional: una nueva Home ("Inicio") que reemplaza la pantalla default de los empleados (rol USER) tras login, muestra el feed de publicaciones filtrado por organigrama (ya expuesto en el subsistema 1) agrupado visualmente, con calendario de feriados y próximos eventos en el sidebar, y notificación in-app cuando HR publica de inmediato.

**Architecture:** Un solo cambio de backend (fan-out de notificaciones sobre `POST /publications`, ya mergeado). En el frontend: tipos compartidos, componentes de presentación (card + modal de detalle), widgets del sidebar (calendario de feriados + próximos eventos), la pantalla orquestadora `PortalInicio/Screen.tsx`, y por último el wiring de routing (`rbac.ts`, `AppSidebar.tsx`, `page.tsx`) — en ese orden para que cada tarea compile de forma independiente sin referencias a componentes que todavía no existen.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact, Tailwind, lucide-react.

## Global Constraints

- El portal reemplaza la pantalla default **solo** para el rol USER (`getDefaultPage`); Admin/RRHH/Estadista no cambian su default actual.
- "Inicio" es accesible (`accessibleFor`) para los 4 roles; visible en el sidebar (`visibleFor`) solo para Admin/RRHH/Estadista — USER no tiene sidebar (patrón ya establecido: `getSidebarPages`/`getSidebarSections` devuelven `[]` para USER) y llega a "Inicio" porque es su default, no por navegación.
- Notificación **solo** en publicaciones inmediatas: al crear (`POST`), si `esBorrador=0` y (`fechaPublicacion` es NULL o ya pasó), se notifica de inmediato a los empleados targeteados. `PUT` (editar) **nunca** dispara notificación.
- La notificación reutiliza la tabla `Message` existente (mismo patrón que `reubicacion.py`/`licenses.py`): `days=0`, `startDate=endDate=now`, `status='active'`, `createdAt=GETDATE()`.
- Sin "marcar como leído" y sin favoritos — explícitamente descartados por el usuario, no se implementan.
- El calendario institucional muestra **solo feriados**, vía `GET /licenses/feriados` (ya existe, sin cambios de backend). "Próximos eventos" es un filtro **client-side** sobre el feed ya obtenido (categoría "Evento Institucional", `fechaPublicacion` futura) — sin endpoint nuevo.
- El detalle de una publicación se abre en un **modal** (`Dialog` de PrimeReact), no en una ruta/pantalla propia.
- Estilo visual: reutilizar los tokens semánticos ya existentes del proyecto (`bg-card`, `bg-background`, `text-foreground`, `text-muted-foreground`, `border-border`, `shadow-soft`, `font-heading`, `bg-warning-soft`/`bg-error-soft` y sus variantes `-foreground`/`border-warning`/`border-error`) — **sin paleta nueva**. Cards con `rounded-xl`, hover con transición 150-300ms.
- Sin test suite automatizada en ninguno de los dos repos — verificación por `py_compile`/`tsc --noEmit` filtrado y manual.

---

### Task 1: Backend — notificación al publicar de inmediato

**Files:**
- Modify: `app/routes/publications.py`

**Interfaces:**
- Produces: `_notificar_destinatarios(db, publication_id, categoria, titulo, now)` (helper interno, sin uso fuera de este archivo). `POST /publications` (ya existe) ahora además inserta `Message` cuando corresponde.

- [ ] **Step 1: Agregar el helper `_notificar_destinatarios`**

Reemplazar:
```python
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


# ─────────────────────────────────────────────────────────────────────────────
# POST /publications — crear publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
```
por:
```python
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


def _notificar_destinatarios(db: Session, publication_id: int, categoria: str, titulo: str, now: datetime) -> None:
    """Inserta un Message para cada empleado alcanzado por los destinos de la publicacion."""
    destinatarios = db.execute(text("""
        SELECT DISTINCT e.id
        FROM Employee e
        INNER JOIN PublicationTarget t ON t.publicationId = :pubId
        WHERE t.scope = 'institucion'
           OR (t.scope = 'departamento' AND t.departmentId = e.departmentId)
           OR (t.scope = 'oficina' AND t.officeId = e.officeId)
    """), {"pubId": publication_id}).mappings().all()

    msg_text = f"Nueva {categoria.lower()}: {titulo}"
    for r in destinatarios:
        db.execute(text("""
            INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt)
            VALUES (:empId, :msg, 0, :now, :now, 'active', GETDATE())
        """), {"empId": r["id"], "msg": msg_text, "now": now})


# ─────────────────────────────────────────────────────────────────────────────
# POST /publications — crear publicacion (HR/Admin)
# ─────────────────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: Llamar al helper desde `create_publication`, solo si es inmediata**

Reemplazar:
```python
    new_id = result.fetchone()[0]

    _insertar_targets(db, new_id, targets)

    db.commit()
    return {"message": "Publicacion creada", "id": new_id}
```
por:
```python
    new_id = result.fetchone()[0]

    _insertar_targets(db, new_id, targets)

    es_borrador = 1 if data.get("esBorrador", True) else 0
    if not es_borrador and (fecha_pub is None or fecha_pub <= now):
        _notificar_destinatarios(db, new_id, data.get("categoria"), data.get("titulo").strip(), now)

    db.commit()
    return {"message": "Publicacion creada", "id": new_id}
```

- [ ] **Step 3: Verificar que compila**

Run: `py -m py_compile app/routes/publications.py`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
git add app/routes/publications.py
git commit -m "feat: notificar a empleados destinatarios al publicar de inmediato"
```

---

### Task 2: Frontend — tipos compartidos

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts`

**Interfaces:**
- Produces: `Page` (union) gana `"inicio"`. Nueva interfaz `FeedPublication` con los campos exactos que devuelve `GET /publications/feed` (Task 1 del subsistema 1, ya mergeado): `{id, titulo, resumen, contenido, categoria, prioridad, estadoMantenimiento, destacada, fijada, fechaPublicacion, fechaExpiracion, createdAt}`.

- [ ] **Step 1: Agregar `"inicio"` al tipo `Page` y la interfaz `FeedPublication`**

Reemplazar:
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
por:
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
  | "admin"
  | "inicio";

export interface FeedPublication {
  id: number;
  titulo: string;
  resumen: string | null;
  contenido: string | null;
  categoria: string;
  prioridad: string;
  estadoMantenimiento: string | null;
  destacada: boolean;
  fijada: boolean;
  fechaPublicacion: string | null;
  fechaExpiracion: string | null;
  createdAt: string | null;
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Interfas/Interfaces"`
Expected: sin salida (sin errores nuevos en este archivo; el proyecto tiene errores preexistentes en otros archivos, no relacionados).

- [ ] **Step 3: Commit**

```bash
git add src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar tipo Page 'inicio' y FeedPublication para el portal institucional"
```

---

### Task 3: Frontend — componentes de presentación (card + detalle)

**Files:**
- Create: `src/app/Componentes/PortalInicio/publicationHelpers.ts`
- Create: `src/app/Componentes/PortalInicio/PublicationCard.tsx`
- Create: `src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx`

**Interfaces:**
- Consumes: `FeedPublication` (Task 2).
- Produces: `CATEGORIA_ICONOS`, `PRIORIDAD_CLASES`, `formatFechaRelativa(iso)` (helpers). Componentes `PublicationCard({publication, onClick})` y `PublicationDetailDialog({publication, onHide})`, ambos usados por la pantalla del Task 5.

- [ ] **Step 1: Crear `src/app/Componentes/PortalInicio/publicationHelpers.ts`**

```tsx
import {
  Newspaper,
  FileText,
  Gavel,
  Wrench,
  AlertTriangle,
  CalendarDays,
  Briefcase,
  Gift,
  Users,
  type LucideIcon,
} from 'lucide-react';

export const CATEGORIA_ICONOS: Record<string, LucideIcon> = {
  'Noticia Institucional': Newspaper,
  'Circular': FileText,
  'Resolución': Gavel,
  'Mantenimiento y Reparaciones': Wrench,
  'Aviso Importante': AlertTriangle,
  'Evento Institucional': CalendarDays,
  'Oportunidad Interna': Briefcase,
  'Beneficio para Empleados': Gift,
  'Comunicación de RRHH': Users,
};

export const PRIORIDAD_CLASES: Record<string, string> = {
  Baja: 'bg-muted text-muted-foreground border-border',
  Normal: 'bg-primary/15 text-primary border-primary/30',
  Alta: 'bg-warning-soft text-warning-soft-foreground border-warning',
  Urgente: 'bg-error-soft text-error-soft-foreground border-error',
};

export function formatFechaRelativa(iso: string | null): string {
  if (!iso) return '';
  const fecha = new Date(iso);
  if (isNaN(fecha.getTime())) return '';
  const ahora = new Date();
  const diffMs = ahora.getTime() - fecha.getTime();
  const diffDias = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDias === 0) return 'Hoy';
  if (diffDias === 1) return 'Ayer';
  if (diffDias > 1 && diffDias < 7) return `Hace ${diffDias} días`;
  return fecha.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}
```

- [ ] **Step 2: Crear `src/app/Componentes/PortalInicio/PublicationCard.tsx`**

```tsx
'use client';

import React from 'react';
import { FileText } from 'lucide-react';
import { CATEGORIA_ICONOS, PRIORIDAD_CLASES, formatFechaRelativa } from './publicationHelpers';
import type { FeedPublication } from '@/app/Interfas/Interfaces';

interface PublicationCardProps {
  publication: FeedPublication;
  onClick: () => void;
}

export function PublicationCard({ publication, onClick }: PublicationCardProps) {
  const Icono = CATEGORIA_ICONOS[publication.categoria] ?? FileText;

  return (
    <button
      onClick={onClick}
      className="w-full text-left bg-card border border-border rounded-xl p-4 shadow-soft hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icono size={20} className="text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${PRIORIDAD_CLASES[publication.prioridad] ?? PRIORIDAD_CLASES.Normal}`}>
              {publication.prioridad}
            </span>
            <span className="text-xs text-muted-foreground">{publication.categoria}</span>
          </div>
          <h3 className="font-heading font-semibold text-foreground truncate">{publication.titulo}</h3>
          {publication.resumen && (
            <p className="text-sm text-muted-foreground line-clamp-2 mt-1">{publication.resumen}</p>
          )}
          <p className="text-xs text-muted-foreground mt-2">
            {formatFechaRelativa(publication.fechaPublicacion ?? publication.createdAt)}
          </p>
        </div>
      </div>
    </button>
  );
}
```

- [ ] **Step 3: Crear `src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx`**

```tsx
'use client';

import React from 'react';
import { Dialog } from 'primereact/dialog';
import { FileText } from 'lucide-react';
import { CATEGORIA_ICONOS, PRIORIDAD_CLASES, formatFechaRelativa } from './publicationHelpers';
import type { FeedPublication } from '@/app/Interfas/Interfaces';

interface PublicationDetailDialogProps {
  publication: FeedPublication | null;
  onHide: () => void;
}

export function PublicationDetailDialog({ publication, onHide }: PublicationDetailDialogProps) {
  const Icono = publication ? (CATEGORIA_ICONOS[publication.categoria] ?? FileText) : FileText;

  return (
    <Dialog
      header={publication ? publication.titulo : ''}
      visible={!!publication}
      onHide={onHide}
      style={{ width: '40rem' }}
      modal
    >
      {publication && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2 py-0.5 text-xs font-semibold rounded-full border ${PRIORIDAD_CLASES[publication.prioridad] ?? PRIORIDAD_CLASES.Normal}`}>
              {publication.prioridad}
            </span>
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Icono size={14} />
              {publication.categoria}
            </span>
            <span className="text-xs text-muted-foreground">
              {formatFechaRelativa(publication.fechaPublicacion ?? publication.createdAt)}
            </span>
          </div>
          {publication.estadoMantenimiento && (
            <p className="text-sm font-semibold text-foreground">
              Estado: <span className="font-normal">{publication.estadoMantenimiento}</span>
            </p>
          )}
          <div className="text-sm text-foreground whitespace-pre-wrap">
            {publication.contenido || publication.resumen || 'Sin contenido adicional.'}
          </div>
        </div>
      )}
    </Dialog>
  );
}
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "PortalInicio/publicationHelpers|PortalInicio/PublicationCard|PortalInicio/PublicationDetailDialog"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
git add src/app/Componentes/PortalInicio/publicationHelpers.ts src/app/Componentes/PortalInicio/PublicationCard.tsx src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx
git commit -m "feat: agregar card y modal de detalle de publicaciones del portal institucional"
```

---

### Task 4: Frontend — widgets del sidebar (calendario + próximos eventos)

**Files:**
- Create: `src/app/Componentes/PortalInicio/CalendarWidget.tsx`
- Create: `src/app/Componentes/PortalInicio/UpcomingEventsWidget.tsx`

**Interfaces:**
- Consumes: `apiClient` (`src/app/util/apiClient.ts`, ya existe), `FeedPublication` (Task 2).
- Produces: `CalendarWidget()` (sin props, hace su propio fetch a `GET /licenses/feriados`). `UpcomingEventsWidget({eventos})` (recibe la lista ya filtrada/ordenada por el padre — puro presentacional).

- [ ] **Step 1: Crear `src/app/Componentes/PortalInicio/CalendarWidget.tsx`**

```tsx
'use client';

import React, { useEffect, useState } from 'react';
import { Calendar } from 'primereact/calendar';
import { addLocale, type LocaleOptions } from 'primereact/api';
import { CalendarDays } from 'lucide-react';
import { apiClient } from '@/app/util/apiClient';

addLocale('es', {
  firstDayOfWeek: 1,
  dayNames: ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'],
  dayNamesShort: ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'],
  dayNamesMin: ['D', 'L', 'M', 'X', 'J', 'V', 'S'],
  monthNames: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
  monthNamesShort: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
  today: 'Hoy',
  clear: 'Limpiar',
} as LocaleOptions);

interface Feriado {
  id: number;
  fecha: string;
  nombre: string;
}

interface CalendarDateTemplateArg {
  day: number;
  month: number;
  year: number;
}

export function CalendarWidget() {
  const [feriados, setFeriados] = useState<Feriado[]>([]);

  useEffect(() => {
    apiClient
      .get<{ feriados: Feriado[] }>('/licenses/feriados')
      .then((res) => setFeriados(res.feriados || []))
      .catch((err) => console.error('Error al cargar feriados:', err));
  }, []);

  const feriadoFechas = new Set(feriados.map((f) => f.fecha.slice(0, 10)));

  const dateTemplate = (date: CalendarDateTemplateArg) => {
    const iso = `${date.year}-${String(date.month + 1).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`;
    const esFeriado = feriadoFechas.has(iso);
    return (
      <span className={esFeriado ? 'flex items-center justify-center w-full h-full rounded-full bg-error/20 text-error font-semibold' : ''}>
        {date.day}
      </span>
    );
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-soft">
      <h3 className="font-heading text-sm font-semibold text-foreground flex items-center gap-2 mb-3">
        <CalendarDays size={16} className="text-primary" />
        Calendario
      </h3>
      <Calendar inline locale="es" dateTemplate={dateTemplate} className="w-full" />
    </div>
  );
}
```

- [ ] **Step 2: Crear `src/app/Componentes/PortalInicio/UpcomingEventsWidget.tsx`**

```tsx
'use client';

import React from 'react';
import { CalendarClock } from 'lucide-react';
import type { FeedPublication } from '@/app/Interfas/Interfaces';

interface UpcomingEventsWidgetProps {
  eventos: FeedPublication[];
}

export function UpcomingEventsWidget({ eventos }: UpcomingEventsWidgetProps) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-soft">
      <h3 className="font-heading text-sm font-semibold text-foreground flex items-center gap-2 mb-3">
        <CalendarClock size={16} className="text-primary" />
        Próximos eventos
      </h3>
      {eventos.length === 0 ? (
        <p className="text-sm text-muted-foreground">No hay eventos próximos.</p>
      ) : (
        <ul className="space-y-3">
          {eventos.map((ev) => (
            <li key={ev.id} className="text-sm">
              <p className="font-medium text-foreground truncate">{ev.titulo}</p>
              <p className="text-xs text-muted-foreground">
                {ev.fechaPublicacion
                  ? new Date(ev.fechaPublicacion).toLocaleDateString('es-AR', { day: '2-digit', month: 'short' })
                  : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "PortalInicio/CalendarWidget|PortalInicio/UpcomingEventsWidget"`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/PortalInicio/CalendarWidget.tsx src/app/Componentes/PortalInicio/UpcomingEventsWidget.tsx
git commit -m "feat: agregar widgets de calendario de feriados y proximos eventos"
```

---

### Task 5: Frontend — pantalla `PortalInicio/Screen.tsx`

**Files:**
- Create: `src/app/screens/PortalInicio/Screen.tsx`

**Interfaces:**
- Consumes: `apiClient`, `PublicationCard`, `PublicationDetailDialog`, `CalendarWidget`, `UpcomingEventsWidget` (Tasks 2-4), `Employee`/`FeedPublication` (`Interfas/Interfaces.ts`).
- Produces: componente `PortalInicio` (export default), prop `{employeeData: Employee | null}` — mismo patrón que `MisDocumentos`/`Reubicacion`.

- [ ] **Step 1: Crear `src/app/screens/PortalInicio/Screen.tsx`**

```tsx
'use client';

import React, { useEffect, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { PublicationCard } from '@/app/Componentes/PortalInicio/PublicationCard';
import { PublicationDetailDialog } from '@/app/Componentes/PortalInicio/PublicationDetailDialog';
import { CalendarWidget } from '@/app/Componentes/PortalInicio/CalendarWidget';
import { UpcomingEventsWidget } from '@/app/Componentes/PortalInicio/UpcomingEventsWidget';
import type { Employee, FeedPublication } from '@/app/Interfas/Interfaces';

interface PortalInicioProps {
  employeeData: Employee | null;
}

const CATEGORIAS_SECCION = [
  'Circular',
  'Resolución',
  'Mantenimiento y Reparaciones',
  'Noticia Institucional',
  'Oportunidad Interna',
  'Beneficio para Empleados',
  'Comunicación de RRHH',
];

export default function PortalInicio({ employeeData }: PortalInicioProps) {
  const [publicaciones, setPublicaciones] = useState<FeedPublication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [seleccionada, setSeleccionada] = useState<FeedPublication | null>(null);

  useEffect(() => {
    if (!employeeData?.id) return;
    setLoading(true);
    apiClient
      .get<{ publications: FeedPublication[] }>(`/publications/feed?employeeId=${employeeData.id}`)
      .then((res) => {
        setPublicaciones(res.publications || []);
        setError(false);
      })
      .catch((err) => {
        console.error('Error al cargar el feed institucional:', err);
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [employeeData?.id]);

  const urgentes = publicaciones.filter((p) => p.prioridad === 'Urgente' || p.fijada);
  const destacadas = publicaciones.filter(
    (p) => p.destacada && !urgentes.some((u) => u.id === p.id)
  );
  const yaMostradas = new Set([...urgentes, ...destacadas].map((p) => p.id));

  const secciones = CATEGORIAS_SECCION.map((categoria) => ({
    categoria,
    items: publicaciones.filter((p) => p.categoria === categoria && !yaMostradas.has(p.id)),
  })).filter((s) => s.items.length > 0);

  const ahora = new Date();
  const proximosEventos = publicaciones
    .filter(
      (p) =>
        p.categoria === 'Evento Institucional' &&
        p.fechaPublicacion &&
        new Date(p.fechaPublicacion) > ahora
    )
    .sort((a, b) => new Date(a.fechaPublicacion!).getTime() - new Date(b.fechaPublicacion!).getTime())
    .slice(0, 5);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-4 sm:p-8 space-y-4">
        <div className="h-8 w-48 bg-muted rounded-lg animate-pulse" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 bg-muted rounded-xl animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto p-8 text-center">
        <p className="text-muted-foreground">No se pudieron cargar las publicaciones.</p>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen font-sans text-foreground p-4 sm:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <header>
          <h1 className="font-heading text-3xl font-bold text-foreground mb-1">Inicio</h1>
          <p className="text-muted-foreground">Novedades y comunicados institucionales.</p>
        </header>

        {urgentes.length > 0 && (
          <div className="space-y-3">
            {urgentes.map((p) => (
              <div key={p.id} className="border-l-4 border-error rounded-xl overflow-hidden">
                <PublicationCard publication={p} onClick={() => setSeleccionada(p)} />
              </div>
            ))}
          </div>
        )}

        {publicaciones.length === 0 ? (
          <div className="bg-card border border-border rounded-xl p-12 text-center">
            <p className="text-muted-foreground">No hay publicaciones por ahora.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              {destacadas.length > 0 && (
                <section>
                  <h2 className="font-heading text-xl font-bold text-foreground mb-3">Destacadas</h2>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {destacadas.map((p) => (
                      <PublicationCard key={p.id} publication={p} onClick={() => setSeleccionada(p)} />
                    ))}
                  </div>
                </section>
              )}

              {secciones.map(({ categoria, items }) => (
                <section key={categoria}>
                  <h2 className="font-heading text-xl font-bold text-foreground mb-3">{categoria}</h2>
                  <div className="space-y-3">
                    {items.map((p) => (
                      <PublicationCard key={p.id} publication={p} onClick={() => setSeleccionada(p)} />
                    ))}
                  </div>
                </section>
              ))}
            </div>

            <div className="space-y-6 lg:sticky lg:top-8 lg:self-start">
              <CalendarWidget />
              <UpcomingEventsWidget eventos={proximosEventos} />
            </div>
          </div>
        )}
      </div>

      <PublicationDetailDialog publication={seleccionada} onHide={() => setSeleccionada(null)} />
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "screens/PortalInicio/Screen"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
git add src/app/screens/PortalInicio/Screen.tsx
git commit -m "feat: agregar pantalla de inicio del portal institucional"
```

---

### Task 6: Frontend — routing (rbac, sidebar, page.tsx)

**Files:**
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `PortalInicio` (Task 5, ya existe en este punto).
- Produces: ningún consumidor externo — cierra el wiring de la pantalla nueva.

- [ ] **Step 1: Agregar "Inicio" a `PAGE_CONFIG`**

Reemplazar:
```typescript
export const PAGE_CONFIG: PageConfig[] = [
  {
    id: "estadisticas",
```
por:
```typescript
export const PAGE_CONFIG: PageConfig[] = [
  {
    id: "inicio",
    label: "Inicio",
    icon: "Home",
    section: "General",
    // USER llega aca porque es su pagina default (ver getDefaultPage), no via
    // sidebar -- USER no tiene sidebar (getSidebarPages/getSidebarSections
    // devuelven [] para ese rol).
    visibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH, ROLE_ID.ESTADISTA],
    accessibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH, ROLE_ID.ESTADISTA, ROLE_ID.USER],
  },
  {
    id: "estadisticas",
```

- [ ] **Step 2: Cambiar el default de USER en `getDefaultPage`**

Reemplazar:
```typescript
export function getDefaultPage(roleId: number): Page {
  const defaults: Record<number, Page> = {
    [ROLE_ID.ADMIN]: "admin",
    [ROLE_ID.RRHH]: "estadisticas",
    [ROLE_ID.ESTADISTA]: "estadisticas",
    [ROLE_ID.USER]: "editar-perfil",
  };
  return defaults[roleId] ?? "estadisticas";
}
```
por:
```typescript
export function getDefaultPage(roleId: number): Page {
  const defaults: Record<number, Page> = {
    [ROLE_ID.ADMIN]: "admin",
    [ROLE_ID.RRHH]: "estadisticas",
    [ROLE_ID.ESTADISTA]: "estadisticas",
    [ROLE_ID.USER]: "inicio",
  };
  return defaults[roleId] ?? "estadisticas";
}
```

- [ ] **Step 3: Agregar el ícono `Home` al sidebar**

Reemplazar:
```tsx
import {
  BarChart2,
  Users,
  BrainCircuit,
  GitMerge,
  ClipboardList,
  ChevronLeft,
  ChevronRight,
  Shield,
  UserCircle,
  FileText,
  MessageSquare,
  Settings,
} from "lucide-react";
```
por:
```tsx
import {
  BarChart2,
  Users,
  BrainCircuit,
  GitMerge,
  ClipboardList,
  ChevronLeft,
  ChevronRight,
  Shield,
  UserCircle,
  FileText,
  MessageSquare,
  Settings,
  Home,
} from "lucide-react";
```

Reemplazar:
```tsx
const ICON_MAP: Record<string, React.ElementType> = {
  BarChart2,
  Users,
  Settings,
  BrainCircuit,
  GitMerge,
  ClipboardList,
  Shield,
  UserCircle,
  FileText,
  MessageSquare,
};
```
por:
```tsx
const ICON_MAP: Record<string, React.ElementType> = {
  BarChart2,
  Users,
  Settings,
  BrainCircuit,
  GitMerge,
  ClipboardList,
  Shield,
  UserCircle,
  FileText,
  MessageSquare,
  Home,
};
```

- [ ] **Step 4: Registrar la pantalla en `page.tsx`**

Reemplazar:
```tsx
import EstadisticasPage from '@/app/screens/Estadisticas/Screen';
```
por:
```tsx
import EstadisticasPage from '@/app/screens/Estadisticas/Screen';
import PortalInicio from '@/app/screens/PortalInicio/Screen';
```

Reemplazar:
```tsx
    switch (page) {
      case 'estadisticas':
        return <EstadisticasPage />;
```
por:
```tsx
    switch (page) {
      case 'inicio':
        return <PortalInicio employeeData={employeeData} />;
      case 'estadisticas':
        return <EstadisticasPage />;
```

- [ ] **Step 5: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "util/rbac|Shell/AppSidebar|app/page\.tsx"`
Expected: sin salida.

- [ ] **Step 6: Commit**

```bash
git add src/app/util/rbac.ts src/app/Componentes/Shell/AppSidebar.tsx src/app/page.tsx
git commit -m "feat: enganchar el portal institucional como home de los empleados"
```

---

### Task 7: Verificación manual

No hay test suite automatizada en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `POST /publications` (como Admin/RRHH) con fecha inmediata (`fechaPublicacion` vacío o pasado) e `esBorrador=false`: inserta un `Message` por cada empleado targeteado. Probar los 3 scopes: institución (todos los empleados), departamento (incluye a los de sus oficinas — herencia), oficina puntual (solo esa oficina).
- [ ] **Step 3:** `POST /publications` con `fechaPublicacion` futura (programada) no inserta ningún `Message`.
- [ ] **Step 4:** `PUT /publications/{id}` (editar una ya existente) no dispara ninguna notificación nueva.
- [ ] **Step 5:** En el frontend, loguearse como un empleado (rol USER): aterriza en "Inicio" (ya no en "Editar Perfil").
- [ ] **Step 6:** Loguearse como Admin o RRHH: sigue aterrizando en su pantalla de siempre ("admin"/"estadisticas"); "Inicio" aparece como opción en el sidebar y se puede navegar ahí.
- [ ] **Step 7:** El feed se agrupa correctamente: urgentes/fijadas arriba, luego destacadas, luego por categoría (solo las secciones con contenido). Un empleado no ve publicaciones fuera de su targeting.
- [ ] **Step 8:** Click en una card abre el modal con el contenido completo; el botón de cierre funciona.
- [ ] **Step 9:** El widget de Calendario muestra los feriados cargados marcados en el mes; el widget "Próximos eventos" solo muestra publicaciones de categoría "Evento Institucional" con fecha futura, ordenadas ascendente, máximo 5.
- [ ] **Step 10:** Dark mode: toda la pantalla (cards, badges, calendario, modal) se ve correctamente en ambos modos.
- [ ] **Step 11:** Responsive: en una ventana angosta (mobile), el sidebar (Calendario + Próximos eventos) pasa a estar debajo del contenido principal, no al costado.
- [ ] **Step 12:** La notificación de una publicación nueva aparece en la campanita existente del header, sin haber tocado su código.
