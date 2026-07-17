# Portal Institucional — Búsqueda + filtros (Subsistema 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar filtros y búsqueda (backend) sobre las publicaciones, en la Home del empleado (todos los roles) y en la pantalla de gestión (admin).

**Architecture:** Se extienden los dos endpoints de lectura existentes (`GET /publications` y `GET /publications/feed`) con query params opcionales, con SQL parametrizado. En el frontend, cada pantalla suma una barra de filtros controlada que re-consulta el backend (texto con debounce 300ms, selects/fechas al instante), con guarda contra respuestas obsoletas.

**Tech Stack:** FastAPI + SQLAlchemy `text()` + SQL Server (pyodbc) · Next.js App Router + React + Tailwind · lucide-react.

## Global Constraints

- **Sin tablas ni endpoints nuevos**: solo se extienden `GET /publications` y `GET /publications/feed`.
- **Sin estadísticas / dashboard**: descartado explícitamente por el usuario. Este subsistema es solo filtros + búsqueda.
- **SQL parametrizado**: valores bindeados; búsqueda de texto con `LIKE '%' + :q + '%'` bindeado, nunca concatenando strings de usuario. Los únicos fragmentos interpolados en f-strings son condiciones SQL estáticas (nunca valores de usuario).
- **Set de filtros**: comunes a ambas pantallas → texto (título+resumen), categoría (9), prioridad (Baja/Normal/Alta/Urgente). Solo admin → estado (Borrador/Programada/Publicada/Archivada) + rango de fechas (desde/hasta sobre `fechaPublicacion`).
- **Home del empleado**: sin filtros → vista agrupada (urgentes/destacadas/por categoría); con cualquier filtro activo → lista plana de resultados. El sidebar (calendario + próximos eventos) siempre usa el feed completo del montaje, no el filtrado.
- **Tokens "Orgánico Cálido"** en todo el frontend (`bg-card`, `bg-background`, `border-border`, `shadow-soft`, `text-foreground`, `text-muted-foreground`, `text-primary`), sin hex crudo. Dark mode por tokens.
- **Debounce del texto ~300ms**; selects/fechas disparan al instante. Respuestas obsoletas (una consulta que vuelve después de otra más nueva) se descartan con un contador de request.
- **Sin suite de tests automatizada** (patrón del proyecto): la verificación por tarea es compilación (`py -m py_compile` / `npx tsc --noEmit`) + chequeo manual. No inventar pytest/jest.
- **Categorías (9)**: `Noticia Institucional, Circular, Resolución, Mantenimiento y Reparaciones, Aviso Importante, Evento Institucional, Oportunidad Interna, Beneficio para Empleados, Comunicación de RRHH`. Prioridades: `Baja, Normal, Alta, Urgente`.

---

## File Structure

**Backend_RRHH:**
- Modify: `app/routes/publications.py` — extender `list_publications` (admin) y `get_feed` (empleado) con query params.

**RRHH:**
- Create: `src/app/Componentes/PortalInicio/FeedFilterBar.tsx` — barra de filtros del feed (texto/categoría/prioridad), presentacional controlada.
- Modify: `src/app/screens/PortalInicio/Screen.tsx` — wiring de filtros: feed completo (montaje) + resultados filtrados, vista agrupada vs plana.
- Create: `src/app/Componentes/GestionPublicaciones/PublicationsFilterBar.tsx` — barra de filtros admin (texto/categoría/prioridad/estado/fechas).
- Modify: `src/app/screens/GestionPublicaciones/Screen.tsx` — wiring de filtros sobre la tabla.

---

## Task 1: Backend — query params en los dos endpoints

**Files:**
- Modify: `app/routes/publications.py`

**Interfaces:**
- Consumes: `_parse_dt` (helper ya existente en el archivo), `_estado_efectivo`, `_targets_de`, `adjuntos_descargables_de`.
- Produces: `GET /publications` acepta `texto`, `categoria`, `prioridad`, `estado`, `fechaDesde`, `fechaHasta`. `GET /publications/feed` acepta `texto`, `categoria`, `prioridad` (además de `employeeId`).

- [ ] **Step 1: Extender `list_publications` (admin)**

Reemplazar la función `list_publications` completa (hoy empieza en `def list_publications(categoria: Optional[str] = None, estado: Optional[str] = None, db: Session = Depends(get_db)):`) por:

```python
@router.get("", dependencies=[Depends(require_rrhh_auth)])
def list_publications(
    categoria: Optional[str] = None,
    estado: Optional[str] = None,
    texto: Optional[str] = None,
    prioridad: Optional[str] = None,
    fechaDesde: Optional[str] = None,
    fechaHasta: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Lista publicaciones activas con su estado efectivo y sus destinos.
    Filtros opcionales: categoria, prioridad y texto (titulo/resumen) y rango
    de fechas van en el WHERE SQL; estado se post-filtra sobre el estado
    efectivo calculado."""
    ensure_table(db)

    query = "SELECT * FROM Publication WHERE activo = 1"
    params = {}
    if categoria:
        query += " AND categoria = :categoria"
        params["categoria"] = categoria
    if prioridad:
        query += " AND prioridad = :prioridad"
        params["prioridad"] = prioridad
    if texto:
        query += " AND (titulo LIKE :q OR resumen LIKE :q)"
        params["q"] = f"%{texto}%"
    fdesde = _parse_dt(fechaDesde)
    if fdesde:
        query += " AND fechaPublicacion >= :fdesde"
        params["fdesde"] = fdesde
    fhasta = _parse_dt(fechaHasta)
    if fhasta:
        # < dia siguiente para que un "hasta" con fecha sin hora sea inclusivo
        query += " AND fechaPublicacion < DATEADD(DAY, 1, :fhasta)"
        params["fhasta"] = fhasta
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

- [ ] **Step 2: Extender `get_feed` (empleado)**

Reemplazar la firma de `get_feed` y su consulta. La firma actual es `def get_feed(employeeId: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):`. Reemplazarla por:

```python
@router.get("/feed", dependencies=[Depends(require_any_auth)])
def get_feed(
    employeeId: int,
    texto: Optional[str] = None,
    categoria: Optional[str] = None,
    prioridad: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Publicaciones visibles para el empleado: publicadas por fecha y dirigidas
    a el (institucion, su departamento o su oficina). Filtros opcionales
    (texto/categoria/prioridad) se suman como condiciones AND sobre el conjunto
    ya restringido por visibilidad y targeting."""
    _check_self_or_admin(employeeId, current_user)

    ensure_table(db)
    ensure_attachments_table(db)

    empleado = db.execute(text("""
        SELECT departmentId, officeId FROM Employee WHERE id = :id
    """), {"id": employeeId}).mappings().first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    dep_id = empleado["departmentId"]
    off_id = empleado["officeId"]

    now = datetime.utcnow()
    params = {"depId": dep_id, "offId": off_id, "now": now}
    filtros_sql = ""
    if categoria:
        filtros_sql += " AND p.categoria = :categoria"
        params["categoria"] = categoria
    if prioridad:
        filtros_sql += " AND p.prioridad = :prioridad"
        params["prioridad"] = prioridad
    if texto:
        filtros_sql += " AND (p.titulo LIKE :q OR p.resumen LIKE :q)"
        params["q"] = f"%{texto}%"

    rows = db.execute(text(f"""
        SELECT DISTINCT p.*
        FROM Publication p
        INNER JOIN PublicationTarget t ON t.publicationId = p.id
        WHERE p.activo = 1
          AND p.esBorrador = 0
          AND (p.fechaPublicacion IS NULL OR p.fechaPublicacion <= :now)
          AND (p.fechaExpiracion IS NULL OR p.fechaExpiracion >= :now)
          AND (
                t.scope = 'institucion'
                OR (t.scope = 'departamento' AND t.departmentId = :depId)
                OR (t.scope = 'oficina' AND t.officeId = :offId)
              )
          {filtros_sql}
        ORDER BY p.fijada DESC, p.fechaPublicacion DESC
    """), params).mappings().all()

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
                "adjuntos": adjuntos_descargables_de(db, r["id"]),
            }
            for r in rows
        ]
    }
```

Nota: `filtros_sql` se interpola en el f-string pero se compone SOLO de fragmentos SQL estáticos; todos los valores de usuario van bindeados en `params`. Sin superficie de inyección.

- [ ] **Step 3: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/routes/publications.py`
Expected: sin salida (exit 0).

- [ ] **Step 4: Verificación manual rápida (recomendada, opcional)**

Con el server corriendo y un token válido: `GET /publications?texto=circular`, `?prioridad=Urgente`, `?estado=Borrador`, `?fechaDesde=2026-07-01&fechaHasta=2026-07-31` → cada uno filtra correctamente; sin params → lista completa. `GET /publications/feed?employeeId=X&categoria=Circular` → solo circulares dirigidas a ese empleado.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/routes/publications.py
git commit -m "feat: agregar filtros de busqueda a los endpoints de publicaciones"
```

---

## Task 2: Frontend — filtros en la Home del empleado

**Files:**
- Create: `src/app/Componentes/PortalInicio/FeedFilterBar.tsx`
- Modify: `src/app/screens/PortalInicio/Screen.tsx`

**Interfaces:**
- Consumes: `apiClient`, `PublicationCard`, `PublicationDetailDialog`, `CalendarWidget`, `UpcomingEventsWidget`, `FeedPublication`, `Employee`.
- Produces: `FeedFilterBar({ filtros, onChange, onLimpiar })` con `filtros: { texto, categoria, prioridad }`.

- [ ] **Step 1: Crear `FeedFilterBar.tsx`**

```tsx
'use client';

import React from 'react';
import { Search, X } from 'lucide-react';

export interface FeedFiltros {
  texto: string;
  categoria: string;
  prioridad: string;
}

interface FeedFilterBarProps {
  filtros: FeedFiltros;
  onChange: (patch: Partial<FeedFiltros>) => void;
  onLimpiar: () => void;
}

const CATEGORIAS = [
  'Noticia Institucional', 'Circular', 'Resolución', 'Mantenimiento y Reparaciones',
  'Aviso Importante', 'Evento Institucional', 'Oportunidad Interna',
  'Beneficio para Empleados', 'Comunicación de RRHH',
];
const PRIORIDADES = ['Baja', 'Normal', 'Alta', 'Urgente'];

export function FeedFilterBar({ filtros, onChange, onLimpiar }: FeedFilterBarProps) {
  const hayFiltros = filtros.texto !== '' || filtros.categoria !== '' || filtros.prioridad !== '';
  return (
    <div className="bg-card border border-border rounded-xl p-3 shadow-soft flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[200px]">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={filtros.texto}
          onChange={(e) => onChange({ texto: e.target.value })}
          placeholder="Buscar por título o resumen…"
          className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm"
        />
      </div>
      <select value={filtros.categoria} onChange={(e) => onChange({ categoria: e.target.value })} className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm">
        <option value="">Todas las categorías</option>
        {CATEGORIAS.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select value={filtros.prioridad} onChange={(e) => onChange({ prioridad: e.target.value })} className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm">
        <option value="">Toda prioridad</option>
        {PRIORIDADES.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      {hayFiltros && (
        <button onClick={onLimpiar} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-muted transition-colors duration-150">
          <X size={14} /> Limpiar
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Reemplazar `PortalInicio/Screen.tsx` completo**

```tsx
'use client';

import React, { useEffect, useRef, useState } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { PublicationCard } from '@/app/Componentes/PortalInicio/PublicationCard';
import { PublicationDetailDialog } from '@/app/Componentes/PortalInicio/PublicationDetailDialog';
import { CalendarWidget } from '@/app/Componentes/PortalInicio/CalendarWidget';
import { UpcomingEventsWidget } from '@/app/Componentes/PortalInicio/UpcomingEventsWidget';
import { FeedFilterBar, type FeedFiltros } from '@/app/Componentes/PortalInicio/FeedFilterBar';
import type { Employee, FeedPublication } from '@/app/Interfas/Interfaces';

interface PortalInicioProps {
  employeeData: Employee | null;
}

const CATEGORIAS_SECCION = [
  'Noticia Institucional', 'Circular', 'Resolución', 'Mantenimiento y Reparaciones',
  'Aviso Importante', 'Evento Institucional', 'Oportunidad Interna',
  'Beneficio para Empleados', 'Comunicación de RRHH',
];

const FILTROS_VACIOS: FeedFiltros = { texto: '', categoria: '', prioridad: '' };

export default function PortalInicio({ employeeData }: PortalInicioProps) {
  const [feedCompleto, setFeedCompleto] = useState<FeedPublication[]>([]);
  const [resultados, setResultados] = useState<FeedPublication[]>([]);
  const [cargandoInicial, setCargandoInicial] = useState(true);
  const [errorInicial, setErrorInicial] = useState(false);
  const [buscando, setBuscando] = useState(false);
  const [errorBusqueda, setErrorBusqueda] = useState(false);
  const [seleccionada, setSeleccionada] = useState<FeedPublication | null>(null);

  const [filtros, setFiltros] = useState<FeedFiltros>(FILTROS_VACIOS);
  const [textoDebounced, setTextoDebounced] = useState('');
  const reqId = useRef(0);

  const hayFiltros = textoDebounced.trim() !== '' || filtros.categoria !== '' || filtros.prioridad !== '';

  // Debounce del texto
  useEffect(() => {
    const t = setTimeout(() => setTextoDebounced(filtros.texto), 300);
    return () => clearTimeout(t);
  }, [filtros.texto]);

  // Fetch inicial sin filtros -> feed completo (vista agrupada + sidebar)
  useEffect(() => {
    if (!employeeData?.id) return;
    setCargandoInicial(true);
    apiClient
      .get<{ publications: FeedPublication[] }>(`/publications/feed?employeeId=${employeeData.id}`)
      .then((res) => { setFeedCompleto(res.publications || []); setErrorInicial(false); })
      .catch((err) => { console.error('Error al cargar el feed institucional:', err); setErrorInicial(true); })
      .finally(() => setCargandoInicial(false));
  }, [employeeData?.id]);

  // Fetch filtrado (solo cuando hay filtros activos) -> solo el contenido principal
  useEffect(() => {
    if (!employeeData?.id) return;
    const activo = textoDebounced.trim() !== '' || filtros.categoria !== '' || filtros.prioridad !== '';
    if (!activo) { setResultados([]); setErrorBusqueda(false); return; }

    const params = new URLSearchParams({ employeeId: String(employeeData.id) });
    if (textoDebounced.trim()) params.set('texto', textoDebounced.trim());
    if (filtros.categoria) params.set('categoria', filtros.categoria);
    if (filtros.prioridad) params.set('prioridad', filtros.prioridad);

    const myId = ++reqId.current;
    setBuscando(true);
    apiClient
      .get<{ publications: FeedPublication[] }>(`/publications/feed?${params.toString()}`)
      .then((res) => { if (myId === reqId.current) { setResultados(res.publications || []); setErrorBusqueda(false); } })
      .catch((err) => { if (myId === reqId.current) { console.error('Error en la búsqueda:', err); setErrorBusqueda(true); } })
      .finally(() => { if (myId === reqId.current) setBuscando(false); });
  }, [employeeData?.id, textoDebounced, filtros.categoria, filtros.prioridad]);

  const limpiar = () => { setFiltros(FILTROS_VACIOS); setTextoDebounced(''); };

  // Agrupacion sobre el feed completo (vista por defecto + sidebar)
  const urgentes = feedCompleto.filter((p) => p.prioridad === 'Urgente' || p.fijada);
  const destacadas = feedCompleto.filter((p) => p.destacada && !urgentes.some((u) => u.id === p.id));
  const yaMostradas = new Set([...urgentes, ...destacadas].map((p) => p.id));
  const secciones = CATEGORIAS_SECCION.map((categoria) => ({
    categoria,
    items: feedCompleto.filter((p) => p.categoria === categoria && !yaMostradas.has(p.id)),
  })).filter((s) => s.items.length > 0);

  const ahora = new Date();
  const proximosEventos = feedCompleto
    .filter((p) => p.categoria === 'Evento Institucional' && p.fechaPublicacion && new Date(p.fechaPublicacion) > ahora)
    .sort((a, b) => new Date(a.fechaPublicacion!).getTime() - new Date(b.fechaPublicacion!).getTime())
    .slice(0, 5);

  if (!employeeData) {
    return (
      <div className="bg-background font-sans min-h-screen flex items-center justify-center">
        <p className="text-foreground">Cargando información del empleado...</p>
      </div>
    );
  }

  if (cargandoInicial) {
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

  if (errorInicial) {
    return (
      <div className="max-w-7xl mx-auto p-8 text-center">
        <p className="text-muted-foreground">No se pudieron cargar las publicaciones.</p>
      </div>
    );
  }

  const sidebar = (
    <div className="space-y-6 lg:sticky lg:top-8 lg:self-start">
      <CalendarWidget />
      <UpcomingEventsWidget eventos={proximosEventos} />
    </div>
  );

  return (
    <div className="bg-background min-h-screen font-sans text-foreground p-4 sm:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <header>
          <h1 className="font-heading text-3xl font-bold text-foreground mb-1">Inicio</h1>
          <p className="text-muted-foreground">Novedades y comunicados institucionales.</p>
        </header>

        <FeedFilterBar
          filtros={filtros}
          onChange={(patch) => setFiltros((f) => ({ ...f, ...patch }))}
          onLimpiar={limpiar}
        />

        {hayFiltros ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-3">
              {buscando ? (
                <p className="text-sm text-muted-foreground">Buscando…</p>
              ) : errorBusqueda ? (
                <p className="text-sm text-error">Error al buscar. Cambiá los filtros e intentá de nuevo.</p>
              ) : resultados.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-12 text-center">
                  <p className="text-muted-foreground mb-3">No se encontraron publicaciones con esos filtros.</p>
                  <button onClick={limpiar} className="text-sm text-primary hover:underline">Limpiar filtros</button>
                </div>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    {resultados.length} resultado{resultados.length === 1 ? '' : 's'}
                  </p>
                  {resultados.map((p) => (
                    <PublicationCard key={p.id} publication={p} onClick={() => setSeleccionada(p)} />
                  ))}
                </>
              )}
            </div>
            {sidebar}
          </div>
        ) : (
          <>
            {urgentes.length > 0 && (
              <div className="space-y-3">
                {urgentes.map((p) => (
                  <div key={p.id} className="border-l-4 border-error rounded-xl overflow-hidden">
                    <PublicationCard publication={p} onClick={() => setSeleccionada(p)} />
                  </div>
                ))}
              </div>
            )}

            {feedCompleto.length === 0 ? (
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
                {sidebar}
              </div>
            )}
          </>
        )}
      </div>

      <PublicationDetailDialog publication={seleccionada} onHide={() => setSeleccionada(null)} />
    </div>
  );
}
```

- [ ] **Step 3: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "PortalInicio/Screen|FeedFilterBar"`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/PortalInicio/FeedFilterBar.tsx src/app/screens/PortalInicio/Screen.tsx
git commit -m "feat: agregar barra de filtros y busqueda a la home del empleado"
```

---

## Task 3: Frontend — filtros en la pantalla de gestión (admin)

**Files:**
- Create: `src/app/Componentes/GestionPublicaciones/PublicationsFilterBar.tsx`
- Modify: `src/app/screens/GestionPublicaciones/Screen.tsx`

**Interfaces:**
- Consumes: `apiClient`, `PublicationAdminRow`.
- Produces: `PublicationsFilterBar({ filtros, onChange, onLimpiar })` con `filtros: { texto, categoria, prioridad, estado, fechaDesde, fechaHasta }`.

- [ ] **Step 1: Crear `PublicationsFilterBar.tsx`**

```tsx
'use client';

import React from 'react';
import { Search, X } from 'lucide-react';

export interface AdminFiltros {
  texto: string;
  categoria: string;
  prioridad: string;
  estado: string;
  fechaDesde: string;
  fechaHasta: string;
}

interface PublicationsFilterBarProps {
  filtros: AdminFiltros;
  onChange: (patch: Partial<AdminFiltros>) => void;
  onLimpiar: () => void;
}

const CATEGORIAS = [
  'Noticia Institucional', 'Circular', 'Resolución', 'Mantenimiento y Reparaciones',
  'Aviso Importante', 'Evento Institucional', 'Oportunidad Interna',
  'Beneficio para Empleados', 'Comunicación de RRHH',
];
const PRIORIDADES = ['Baja', 'Normal', 'Alta', 'Urgente'];
const ESTADOS = ['Borrador', 'Programada', 'Publicada', 'Archivada'];

export function PublicationsFilterBar({ filtros, onChange, onLimpiar }: PublicationsFilterBarProps) {
  const hayFiltros =
    filtros.texto !== '' || filtros.categoria !== '' || filtros.prioridad !== '' ||
    filtros.estado !== '' || filtros.fechaDesde !== '' || filtros.fechaHasta !== '';

  const inputCls = 'px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm';

  return (
    <div className="bg-card border border-border rounded-xl p-3 shadow-soft flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[200px]">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={filtros.texto}
          onChange={(e) => onChange({ texto: e.target.value })}
          placeholder="Buscar por título o resumen…"
          className={`w-full pl-9 pr-3 ${inputCls}`}
        />
      </div>
      <select value={filtros.categoria} onChange={(e) => onChange({ categoria: e.target.value })} className={inputCls}>
        <option value="">Todas las categorías</option>
        {CATEGORIAS.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select value={filtros.prioridad} onChange={(e) => onChange({ prioridad: e.target.value })} className={inputCls}>
        <option value="">Toda prioridad</option>
        {PRIORIDADES.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      <select value={filtros.estado} onChange={(e) => onChange({ estado: e.target.value })} className={inputCls}>
        <option value="">Todos los estados</option>
        {ESTADOS.map((e) => <option key={e} value={e}>{e}</option>)}
      </select>
      <input type="date" value={filtros.fechaDesde} onChange={(e) => onChange({ fechaDesde: e.target.value })} className={inputCls} title="Desde" />
      <input type="date" value={filtros.fechaHasta} onChange={(e) => onChange({ fechaHasta: e.target.value })} className={inputCls} title="Hasta" />
      {hayFiltros && (
        <button onClick={onLimpiar} className="inline-flex items-center gap-1 px-3 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-muted transition-colors duration-150">
          <X size={14} /> Limpiar
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wiring en `GestionPublicaciones/Screen.tsx` — imports y estado**

Leé el archivo real primero. Aplicá estos cambios (el archivo es grande y el formulario de autoría queda intacto — solo se toca el listado):

(a) Agregar el import (junto a los otros de componentes, cerca de la línea 5-6):
```tsx
import { PublicationsFilterBar, type AdminFiltros } from '@/app/Componentes/GestionPublicaciones/PublicationsFilterBar';
```

(b) Agregar la constante de filtros vacíos junto a `EMPTY_FORM` (cerca de la línea 40):
```tsx
const FILTROS_VACIOS: AdminFiltros = { texto: '', categoria: '', prioridad: '', estado: '', fechaDesde: '', fechaHasta: '' };
```

(c) En el cuerpo del componente, junto a los demás `useState` (después de `const [error, setError] = useState('');`), agregar:
```tsx
  const [filtros, setFiltros] = useState<AdminFiltros>(FILTROS_VACIOS);
  const [textoDebounced, setTextoDebounced] = useState('');
  const [refetchTick, setRefetchTick] = useState(0);
  const reqId = useRef(0);
```
Y agregar `useRef` al import de React del inicio del archivo (hoy `import React, { useEffect, useState, useCallback } from 'react';` → `import React, { useEffect, useRef, useState, useCallback } from 'react';`).

- [ ] **Step 3: Wiring — reemplazar `cargarLista` y su efecto de montaje**

El código actual tiene (cerca de líneas 63-75):
```tsx
  const cargarLista = useCallback(() => {
    apiClient
      .get<{ publications: PublicationAdminRow[] }>('/publications')
      .then((res) => setRows(res.publications || []))
      .catch((e) => console.error('Error al listar publicaciones:', e));
  }, []);

  useEffect(() => {
    cargarLista();
    apiClient
      .get<{ departments: DeptOption[] }>('/departments/')
      .then((res) => setDepts(res.departments || []))
      .catch((e) => console.error('Error al cargar organigrama:', e));
```
Reemplazar el bloque `const cargarLista = useCallback(...)` **y** la llamada `cargarLista();` dentro del `useEffect` de montaje por: quitar `cargarLista` (ya no existe) y dejar el `useEffect` de montaje SOLO con la carga de departamentos. Es decir, ese `useEffect` queda:
```tsx
  useEffect(() => {
    apiClient
      .get<{ departments: DeptOption[] }>('/departments/')
      .then((res) => setDepts(res.departments || []))
      .catch((e) => console.error('Error al cargar organigrama:', e));
  }, []);
```
(Si el `useEffect` de montaje tenía `[cargarLista]` como dependencia, cambialo a `[]`.)

Agregar el debounce del texto y el efecto de carga filtrada (por ejemplo justo después de ese `useEffect` de departamentos):
```tsx
  // Debounce del texto
  useEffect(() => {
    const t = setTimeout(() => setTextoDebounced(filtros.texto), 300);
    return () => clearTimeout(t);
  }, [filtros.texto]);

  // Carga de la lista segun filtros (y refetch tras guardar)
  useEffect(() => {
    const params = new URLSearchParams();
    if (textoDebounced.trim()) params.set('texto', textoDebounced.trim());
    if (filtros.categoria) params.set('categoria', filtros.categoria);
    if (filtros.prioridad) params.set('prioridad', filtros.prioridad);
    if (filtros.estado) params.set('estado', filtros.estado);
    if (filtros.fechaDesde) params.set('fechaDesde', filtros.fechaDesde);
    if (filtros.fechaHasta) params.set('fechaHasta', filtros.fechaHasta);
    const qs = params.toString();
    const myId = ++reqId.current;
    apiClient
      .get<{ publications: PublicationAdminRow[] }>(`/publications${qs ? `?${qs}` : ''}`)
      .then((res) => { if (myId === reqId.current) setRows(res.publications || []); })
      .catch((e) => { if (myId === reqId.current) console.error('Error al listar publicaciones:', e); });
  }, [textoDebounced, filtros.categoria, filtros.prioridad, filtros.estado, filtros.fechaDesde, filtros.fechaHasta, refetchTick]);
```

- [ ] **Step 4: Wiring — refetch tras guardar**

En la función `guardar`, donde hoy dice `cargarLista();` (justo antes de `setModo('lista');` en el bloque de éxito), reemplazar esa línea por:
```tsx
      setRefetchTick((t) => t + 1);
```
(Así la lista se re-consulta con los filtros actuales tras crear/editar.)

- [ ] **Step 5: Wiring — barra de filtros + contador + estado vacío en el render del listado**

En el `return` del modo lista (el `if (modo === 'lista')`), después del `<header>...</header>` y antes del `<div className="bg-card border border-border rounded-xl shadow-soft overflow-hidden">`, insertar la barra:
```tsx
          <PublicationsFilterBar
            filtros={filtros}
            onChange={(patch) => setFiltros((f) => ({ ...f, ...patch }))}
            onLimpiar={() => { setFiltros(FILTROS_VACIOS); setTextoDebounced(''); }}
          />

          <p className="text-sm text-muted-foreground">
            {rows.length} publicaci{rows.length === 1 ? 'ón' : 'ones'}
          </p>
```
Y reemplazar el texto del estado vacío de la tabla (hoy `No hay publicaciones todavía.`) por uno que contemple el caso "sin resultados por filtros":
```tsx
              <p className="p-8 text-center text-muted-foreground">
                No se encontraron publicaciones con esos filtros.
              </p>
```

- [ ] **Step 6: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "GestionPublicaciones/Screen|PublicationsFilterBar"`
Expected: sin salida.

- [ ] **Step 7: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/GestionPublicaciones/PublicationsFilterBar.tsx src/app/screens/GestionPublicaciones/Screen.tsx
git commit -m "feat: agregar barra de filtros y busqueda a la gestion de publicaciones"
```

---

## Task 4: Verificación manual (sin commits)

Requiere backend + DB + browser reales; no automatizable. Checklist del spec:

- [ ] Backend compila: `py -m py_compile app/routes/publications.py`.
- [ ] `GET /publications` con cada filtro por separado y combinados (texto, categoría, prioridad, estado, rango de fechas) → resultados correctos; sin filtros → lista completa.
- [ ] `GET /publications/feed?employeeId=X` con texto/categoría/prioridad → respeta el targeting (un empleado no ve algo que no le corresponde aunque matchee el texto).
- [ ] Admin: la barra de filtros re-consulta y actualiza la tabla; "Limpiar" restaura; contador correcto; sin resultados muestra el estado vacío; crear/editar una publicación refresca la lista respetando los filtros.
- [ ] Empleado: sin filtros → vista agrupada; con filtro → lista plana con contador; el sidebar (próximos eventos) no se altera al filtrar; el modal de detalle sigue funcionando.
- [ ] Debounce del texto no dispara una consulta por tecla; escribir rápido y borrar no deja un resultado obsoleto en pantalla.
- [ ] Dark mode y responsive de ambas barras de filtro.

---

## Notas para el ejecutor

- **Sin pytest/jest**: la "prueba" de cada task es la compilación (`py -m py_compile` / `npx tsc --noEmit`) + verificación manual. No agregar frameworks de test.
- **Orden**: Task 1 (backend) es independiente de las de frontend; Task 2 y Task 3 son independientes entre sí (archivos y pantallas distintas). Ejecutar en orden numérico es seguro.
- **El archivo `UiRRHH.tsx`** puede tener un cambio local no relacionado en el working tree del repo RRHH: NO incluirlo en ningún commit de este plan.
