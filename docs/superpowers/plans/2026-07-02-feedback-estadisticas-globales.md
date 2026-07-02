# Estadísticas globales de Feedback 360° Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar `GET /feedback/estadisticas-globales?departmentId={id}` (radar área vs. institucional + rankings del área por categoría) y una pestaña "Feedback 360°" nueva en el panel de Estadísticas con selector de departamento.

**Architecture:** Un endpoint nuevo en `app/routes/feedback.py` con una sola query agregada. En el frontend, un componente nuevo `Feedback360Stats.tsx` en `Componentes/ComponEstadistica/` (mismo directorio que `Globalstat.tsx`, que ya usa `recharts`), enganchado como 3ra pestaña en `Estadisticas/Screen.tsx` (que ya tiene un patrón de tabs con 2 pestañas).

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, `recharts` (ya instalado), PrimeReact.

## Global Constraints

- Solo cuentan para el radar/rankings las respuestas donde `Pregunta.tipo = 'escala'` y `Pregunta.esAmbienteGeneral = 0` (mismo filtro usado en el subsistema 3 de indicadores por empleado).
- `RespuestaFeedback.departmentId` ya existe (snapshot del departamento del evaluado al momento de la respuesta, sembrado desde el subsistema 1) — no hace falta JOIN contra `Employee`.
- `promedioInstitucional` es el mismo valor sin importar qué `departmentId` se pase (agregado global, `AVG` sin filtro).
- No se toca ningún otro endpoint de `feedback.py` (`/peers`, `/siguiente`, `/submit`, `/status`, `/verificar`, `/config`, `/preguntas`, `/received`).
- No se modifica `app/main.py`, `app/routes/contracts.py`, `app/routes/professions.py`, `app/routes/schedules.py`.

---

### Task 1: Backend — `GET /feedback/estadisticas-globales`

**Files:**
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Produces: `GET /feedback/estadisticas-globales?departmentId={id}` (`require_any_auth`) → `{"departmentId", "radar": [{categoria, promedioArea, promedioInstitucional}], "fortalezasArea": [{categoria, promedio}], "debilidadesArea": [{categoria, promedio}]}`.

- [ ] **Step 1: Agregar el endpoint al final de `app/routes/feedback.py`**

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/estadisticas-globales — radar y rankings por departamento
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/estadisticas-globales", dependencies=[Depends(require_any_auth)])
def get_estadisticas_globales(departmentId: int, db: Session = Depends(get_db)):
    """
    Radar de habilidades (promedio del departamento seleccionado vs.
    promedio institucional, por categoria) y ranking de fortalezas/
    debilidades del departamento seleccionado.
    """
    rows = db.execute(text("""
        SELECT
            p.categoria,
            AVG(CASE WHEN rf.departmentId = :deptId THEN CAST(rf.valorEscala AS FLOAT) END) AS promedio_area,
            AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio_institucional
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE p.tipo = 'escala' AND p.esAmbienteGeneral = 0
        GROUP BY p.categoria
        ORDER BY p.categoria ASC
    """), {"deptId": departmentId}).mappings().all()

    radar = []
    ranking_area = []
    for r in rows:
        promedio_area = round(r["promedio_area"], 2) if r["promedio_area"] is not None else None
        promedio_institucional = round(r["promedio_institucional"], 2) if r["promedio_institucional"] is not None else None
        radar.append({
            "categoria": r["categoria"],
            "promedioArea": promedio_area,
            "promedioInstitucional": promedio_institucional,
        })
        if promedio_area is not None:
            ranking_area.append({"categoria": r["categoria"], "promedio": promedio_area})

    ranking_area_desc = sorted(ranking_area, key=lambda x: x["promedio"], reverse=True)
    fortalezas_area = ranking_area_desc[:5]
    debilidades_area = list(reversed(ranking_area_desc))[:5]

    return {
        "departmentId": departmentId,
        "radar": radar,
        "fortalezasArea": fortalezas_area,
        "debilidadesArea": debilidades_area,
    }
```

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/routes/feedback.py`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
git add app/routes/feedback.py
git commit -m "feat: agregar GET /feedback/estadisticas-globales con radar y rankings por departamento"
```

---

### Task 2: Frontend — pestaña "Feedback 360°" en Estadísticas

**Files:**
- Create: `src/app/Componentes/ComponEstadistica/Feedback360Stats.tsx`
- Modify: `src/app/screens/Estadisticas/Screen.tsx`

**Interfaces:**
- Consumes: `GET /departments/` (ya existe, devuelve un array de `Department` — usar solo `.id`/`.nombre`) y `GET /feedback/estadisticas-globales?departmentId={id}` (Task 1).
- Produces: componente `Feedback360Stats` exportado, sin props (autocontenido).

- [ ] **Step 1: Crear `Feedback360Stats.tsx`**

```tsx
"use client"
import React, { useEffect, useState } from 'react';
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, Legend, Tooltip, ResponsiveContainer } from 'recharts';
import { Dropdown } from 'primereact/dropdown';
import { apiClient } from '@/app/util/apiClient';
import type { Department } from '@/app/Interfas/Interfaces';

interface CategoriaRadar {
  categoria: string;
  promedioArea: number | null;
  promedioInstitucional: number | null;
}

interface CategoriaPromedio {
  categoria: string;
  promedio: number;
}

interface EstadisticasGlobalesData {
  departmentId: number;
  radar: CategoriaRadar[];
  fortalezasArea: CategoriaPromedio[];
  debilidadesArea: CategoriaPromedio[];
}

export const Feedback360Stats = () => {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<number | null>(null);
  const [data, setData] = useState<EstadisticasGlobalesData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get<Department[]>('/departments/')
      .then((depts) => {
        setDepartments(depts);
        if (depts.length > 0) setSelectedDeptId(depts[0].id);
        else setLoading(false);
      })
      .catch((err) => {
        console.error('Error al cargar departamentos:', err);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (selectedDeptId === null) return;
    setLoading(true);
    apiClient
      .get<EstadisticasGlobalesData>(`/feedback/estadisticas-globales?departmentId=${selectedDeptId}`)
      .then(setData)
      .catch((err) => console.error('Error al cargar estadisticas globales de Feedback 360:', err))
      .finally(() => setLoading(false));
  }, [selectedDeptId]);

  const departmentOptions = departments.map((d) => ({ label: d.nombre, value: d.id }));
  const tieneDatos = data !== null && data.radar.some((r) => r.promedioArea !== null);

  return (
    <div className="space-y-6">
      <div className="max-w-xs">
        <label className="block text-sm font-semibold text-foreground mb-1">Departamento</label>
        <Dropdown
          value={selectedDeptId}
          options={departmentOptions}
          onChange={(e) => setSelectedDeptId(e.value)}
          placeholder="Seleccioná un departamento"
          className="w-full"
        />
      </div>

      {loading ? (
        <div className="p-6 text-center text-muted-foreground">Cargando estadísticas...</div>
      ) : !tieneDatos ? (
        <div className="p-6 text-center text-muted-foreground">
          Este departamento todavía no tiene evaluaciones de Feedback 360°.
        </div>
      ) : (
        <>
          <div className="bg-card border border-border rounded-lg p-4">
            <h3 className="font-heading font-semibold text-foreground mb-3">Radar de habilidades</h3>
            <ResponsiveContainer width="100%" height={400}>
              <RadarChart data={data!.radar}>
                <PolarGrid />
                <PolarAngleAxis dataKey="categoria" />
                <PolarRadiusAxis angle={30} domain={[0, 5]} />
                <Radar name="Área seleccionada" dataKey="promedioArea" stroke="#2563eb" fill="#2563eb" fillOpacity={0.3} />
                <Radar name="Institucional" dataKey="promedioInstitucional" stroke="#16a34a" fill="#16a34a" fillOpacity={0.2} />
                <Legend />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-card border border-border rounded-lg p-4">
              <h3 className="font-heading font-semibold text-foreground mb-3">Fortalezas del área</h3>
              {data!.fortalezasArea.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">Sin datos suficientes.</p>
              ) : (
                <ul className="space-y-2">
                  {data!.fortalezasArea.map((f) => (
                    <li key={f.categoria} className="flex justify-between text-sm">
                      <span className="text-foreground">{f.categoria}</span>
                      <span className="font-semibold text-success">{f.promedio.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="bg-card border border-border rounded-lg p-4">
              <h3 className="font-heading font-semibold text-foreground mb-3">Debilidades del área</h3>
              {data!.debilidadesArea.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">Sin datos suficientes.</p>
              ) : (
                <ul className="space-y-2">
                  {data!.debilidadesArea.map((d) => (
                    <li key={d.categoria} className="flex justify-between text-sm">
                      <span className="text-foreground">{d.categoria}</span>
                      <span className="font-semibold text-error">{d.promedio.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
```

- [ ] **Step 2: Enganchar la pestaña nueva en `Estadisticas/Screen.tsx`**

Cambiar la línea de import de íconos (línea 15 del archivo actual):
```tsx
import { BarChart2, User, RefreshCw, AlertCircle } from 'lucide-react';
```
por:
```tsx
import { BarChart2, User, RefreshCw, AlertCircle, Award } from 'lucide-react';
```

Agregar el import del componente nuevo, debajo de los demás imports de `Componentes/ComponEstadistica`:
```tsx
import { Feedback360Stats } from '@/app/Componentes/ComponEstadistica/Feedback360Stats';
```

Cambiar la línea del `useState` del tab activo (línea 30 del archivo actual):
```tsx
const [activeTab, setActiveTab]         = React.useState<'ranking' | 'globales'>('ranking');
```
por:
```tsx
const [activeTab, setActiveTab]         = React.useState<'ranking' | 'globales' | 'feedback360'>('ranking');
```

Agregar la entrada de tab nueva al array de tabs (dentro del `.map` de `nav`, líneas ~141-144 del archivo actual):
```tsx
{([
  { id: 'ranking',     label: 'Ranking de Productividad', Icon: User },
  { id: 'globales',    label: 'Estadísticas Globales',    Icon: BarChart2 },
  { id: 'feedback360', label: 'Feedback 360°',            Icon: Award },
] as const).map(({ id, label, Icon }) => (
```

Reemplazar el bloque de renderizado condicional (líneas ~158-172 del archivo actual):
```tsx
{activeTab === 'ranking' ? (
  <ProductivityRanking
    employees={employees}
    onSelectEmployee={setSelectedEmployee}
    filters={filters}
    onFilterChange={handleFilterChange}
    sortConfig={sortConfig}
    onSortChange={setSortConfig}
    currentPage={currentPage}
    onPageChange={setCurrentPage}
    metadata={metadata}
  />
) : (
  <GlobalStats data={globalStats} isLoading={isLoading} error={error} />
)}
```
por:
```tsx
{activeTab === 'ranking' && (
  <ProductivityRanking
    employees={employees}
    onSelectEmployee={setSelectedEmployee}
    filters={filters}
    onFilterChange={handleFilterChange}
    sortConfig={sortConfig}
    onSortChange={setSortConfig}
    currentPage={currentPage}
    onPageChange={setCurrentPage}
    metadata={metadata}
  />
)}
{activeTab === 'globales' && (
  <GlobalStats data={globalStats} isLoading={isLoading} error={error} />
)}
{activeTab === 'feedback360' && (
  <Feedback360Stats />
)}
```

- [ ] **Step 3: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "ComponEstadistica/Feedback360Stats|screens/Estadisticas/Screen"`
Expected: sin salida (sin errores nuevos en estos 2 archivos).

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/ComponEstadistica/Feedback360Stats.tsx src/app/screens/Estadisticas/Screen.tsx
git commit -m "feat: agregar pestana Feedback 360 con radar y rankings por departamento en Estadisticas"
```

---

### Task 3: Verificación manual

No hay test suite automatizado en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** `GET /feedback/estadisticas-globales?departmentId={id}` para un departamento con respuestas registradas devuelve `radar` con `promedioArea` y `promedioInstitucional` numéricos.
- [ ] **Step 3:** Para un departamento sin ninguna respuesta: todos los `promedioArea` del radar son `null`, `fortalezasArea`/`debilidadesArea` vacíos.
- [ ] **Step 4:** `promedioInstitucional` es igual entre 2 llamadas con distinto `departmentId` (mismo valor agregado global).
- [ ] **Step 5:** En el frontend, ir a Estadísticas → pestaña "Feedback 360°" → cambiar el selector de departamento y confirmar que el radar y los rankings se actualizan.
- [ ] **Step 6:** Seleccionar un departamento sin datos y confirmar que se ve el mensaje "Este departamento todavía no tiene evaluaciones de Feedback 360°".
