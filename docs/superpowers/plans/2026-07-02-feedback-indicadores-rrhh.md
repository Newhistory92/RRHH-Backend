# Indicadores para RRHH de Feedback 360° Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescribir `GET /feedback/received/{employee_id}` para devolver fortalezas/debilidades Top 5 por categoría (promedio histórico) y evolución período actual vs. anterior, y mostrarlo en la ficha de empleado que usa RRHH.

**Architecture:** Se agrega `get_periodo_anterior(db)` a `app/database/feedback_config.py` (ya existe con `get_periodo_actual`). Se reescribe el endpoint en `app/routes/feedback.py` (mismo path, mismo archivo que ya venimos modificando). En el frontend, se agrega un componente `FeedbackIndicatorsTab` en `RRHH/src/app/Componentes/TablaOperador/DetailTables.tsx` (mismo archivo donde ya viven `ProfileTab`, `DocumentsTab`, etc.) y se lo engancha como pestaña nueva en `Perfildetail.tsx`.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js/React, PrimeReact.

## Global Constraints

- Solo cuentan para fortalezas/debilidades las respuestas donde `Pregunta.tipo = 'escala'` y `Pregunta.esAmbienteGeneral = 0` (se excluyen preguntas de texto libre y las que no son sobre una persona puntual).
- Fortalezas/debilidades se calculan sobre **todo el histórico** de `RespuestaFeedback` donde el empleado es el evaluado, agrupado por `Pregunta.categoria`, promediando `valorEscala`.
- Evolución = promedio del período actual (`get_periodo_actual`) vs. promedio del período anterior (`get_periodo_anterior`, nuevo). `null` en los promedios/diferencia si no hay datos en ese período.
- No se toca `/peers`, `/siguiente`, `/submit`, `/status`, `/verificar`, `/config`, `/preguntas`.
- No se modifica `app/main.py`, `app/routes/contracts.py`, `app/routes/professions.py`, `app/routes/schedules.py`.

---

### Task 1: `get_periodo_anterior` + reescritura de `GET /feedback/received/{employee_id}`

**Files:**
- Modify: `app/database/feedback_config.py`
- Modify: `app/routes/feedback.py`

**Interfaces:**
- Produces: `get_periodo_anterior(db: Session) -> date` en `app/database/feedback_config.py`. Endpoint `GET /feedback/received/{employee_id}` → `{"employeeId", "fortalezas": [{categoria, promedio}], "debilidades": [{categoria, promedio}], "evolucion": {periodoActual, promedioActual, periodoAnterior, promedioAnterior, diferencia}}`.

- [ ] **Step 1: Agregar `get_periodo_anterior` a `app/database/feedback_config.py`**

Agregar al final del archivo, después de `get_periodo_actual`:

```python
def get_periodo_anterior(db: Session) -> date:
    """Calcula el inicio del ciclo inmediatamente anterior al actual,
    restando una unidad de periodicidad (trimestral: -3 meses,
    semestral: -6 meses, anual: -1 anio) a get_periodo_actual.
    """
    periodicidad = get_periodicidad(db)
    actual = get_periodo_actual(db)

    if periodicidad == "anual":
        return date(actual.year - 1, 1, 1)
    if periodicidad == "semestral":
        if actual.month == 1:
            return date(actual.year - 1, 7, 1)
        return date(actual.year, 1, 1)
    mes = actual.month - 3
    anio = actual.year
    if mes <= 0:
        mes += 12
        anio -= 1
    return date(anio, mes, 1)
```

- [ ] **Step 2: Agregar el import en `app/routes/feedback.py`**

Ubicar la línea existente:
```python
from app.database.feedback_config import (
    ensure_table as ensure_config_table,
    get_periodicidad,
    set_periodicidad,
    get_periodo_actual,
)
```
y reemplazarla por:
```python
from app.database.feedback_config import (
    ensure_table as ensure_config_table,
    get_periodicidad,
    set_periodicidad,
    get_periodo_actual,
    get_periodo_anterior,
)
```

- [ ] **Step 3: Reemplazar por completo el endpoint `GET /feedback/received/{employee_id}`**

Buscar el bloque que empieza en:
```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/received/{employee_id} — resultados recibidos por el empleado
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/received/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_received_feedback(employee_id: int, db: Session = Depends(get_db)):
```
y termina justo antes de:
```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/preguntas — Banco de preguntas de Feedback 360
```

Reemplazarlo por:

```python
# ─────────────────────────────────────────────────────────────────────────────
# GET /feedback/received/{employee_id} — indicadores para RRHH
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/received/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_received_feedback(employee_id: int, db: Session = Depends(get_db)):
    """
    Indicadores de Feedback 360 recibidos por el empleado: fortalezas y
    debilidades Top 5 por categoria (promedio historico de valorEscala),
    y evolucion del promedio general entre el periodo actual y el anterior.
    """
    ensure_config_table(db)

    categorias = db.execute(text("""
        SELECT p.categoria, AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio
        FROM RespuestaFeedback rf
        INNER JOIN Pregunta p ON p.id = rf.preguntaId
        WHERE rf.evaluadoEmployeeId = :emp
          AND p.tipo = 'escala'
          AND p.esAmbienteGeneral = 0
        GROUP BY p.categoria
        ORDER BY promedio DESC
    """), {"emp": employee_id}).mappings().all()

    ranking = [{"categoria": c["categoria"], "promedio": round(c["promedio"], 2)} for c in categorias]
    fortalezas = ranking[:5]
    debilidades = list(reversed(ranking))[:5]

    periodo_actual = get_periodo_actual(db)
    periodo_anterior = get_periodo_anterior(db)

    def promedio_periodo(periodo):
        row = db.execute(text("""
            SELECT AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio
            FROM RespuestaFeedback rf
            INNER JOIN Pregunta p ON p.id = rf.preguntaId
            WHERE rf.evaluadoEmployeeId = :emp
              AND p.tipo = 'escala'
              AND p.esAmbienteGeneral = 0
              AND rf.periodo = :periodo
        """), {"emp": employee_id, "periodo": periodo}).mappings().first()
        return round(row["promedio"], 2) if row and row["promedio"] is not None else None

    promedio_actual = promedio_periodo(periodo_actual)
    promedio_anterior = promedio_periodo(periodo_anterior)
    diferencia = (
        round(promedio_actual - promedio_anterior, 2)
        if promedio_actual is not None and promedio_anterior is not None
        else None
    )

    return {
        "employeeId": employee_id,
        "fortalezas": fortalezas,
        "debilidades": debilidades,
        "evolucion": {
            "periodoActual": periodo_actual.isoformat(),
            "promedioActual": promedio_actual,
            "periodoAnterior": periodo_anterior.isoformat(),
            "promedioAnterior": promedio_anterior,
            "diferencia": diferencia,
        },
    }
```

- [ ] **Step 4: Verificar que compila**

Run: `py -m py_compile app/database/feedback_config.py app/routes/feedback.py`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
git add app/database/feedback_config.py app/routes/feedback.py
git commit -m "feat: reescribir GET /feedback/received con indicadores de fortalezas/debilidades y evolucion"
```

---

### Task 2: Frontend — sección "Feedback 360°" en la ficha de empleado

**Files:**
- Modify: `src/app/Componentes/TablaOperador/DetailTables.tsx`
- Modify: `src/app/Componentes/TablaOperador/Perfildetail.tsx`

**Interfaces:**
- Consumes: `GET /feedback/received/{employeeId}` → `{employeeId, fortalezas: [{categoria, promedio}], debilidades: [{categoria, promedio}], evolucion: {periodoActual, promedioActual, periodoAnterior, promedioAnterior, diferencia}}` (Task 1).
- Produces: componente `FeedbackIndicatorsTab({ employee }: { employee: Employee })` exportado desde `DetailTables.tsx`.

- [ ] **Step 1: Agregar `FeedbackIndicatorsTab` en `DetailTables.tsx`**

Agregar al final del archivo (después del cierre de `DocumentsTab`), reutilizando `apiClient` ya importado en este archivo:

```tsx
interface CategoriaPromedio {
  categoria: string;
  promedio: number;
}

interface FeedbackIndicadores {
  employeeId: number;
  fortalezas: CategoriaPromedio[];
  debilidades: CategoriaPromedio[];
  evolucion: {
    periodoActual: string;
    promedioActual: number | null;
    periodoAnterior: string;
    promedioAnterior: number | null;
    diferencia: number | null;
  };
}

export const FeedbackIndicatorsTab = ({ employee }: { employee: Employee }) => {
  const [indicadores, setIndicadores] = useState<FeedbackIndicadores | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiClient
      .get<FeedbackIndicadores>(`/feedback/received/${employee.id}`)
      .then(setIndicadores)
      .catch((err) => console.error("Error al cargar indicadores de Feedback 360:", err))
      .finally(() => setLoading(false));
  }, [employee.id]);

  if (loading) {
    return <div className="p-6 text-center text-muted-foreground">Cargando indicadores...</div>;
  }

  if (!indicadores || (indicadores.fortalezas.length === 0 && indicadores.debilidades.length === 0)) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        Este empleado todavía no recibió evaluaciones de Feedback 360°.
      </div>
    );
  }

  const { fortalezas, debilidades, evolucion } = indicadores;
  const tieneComparacion = evolucion.diferencia !== null;

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="font-heading font-semibold text-foreground mb-3">Fortalezas</h3>
          {fortalezas.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">Sin datos suficientes.</p>
          ) : (
            <ul className="space-y-2">
              {fortalezas.map((f) => (
                <li key={f.categoria} className="flex justify-between text-sm">
                  <span className="text-foreground">{f.categoria}</span>
                  <span className="font-semibold text-success">{f.promedio.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="font-heading font-semibold text-foreground mb-3">Debilidades</h3>
          {debilidades.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">Sin datos suficientes.</p>
          ) : (
            <ul className="space-y-2">
              {debilidades.map((d) => (
                <li key={d.categoria} className="flex justify-between text-sm">
                  <span className="text-foreground">{d.categoria}</span>
                  <span className="font-semibold text-error">{d.promedio.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="font-heading font-semibold text-foreground mb-3">Evolución</h3>
        {tieneComparacion ? (
          <p className="text-sm text-foreground">
            {evolucion.diferencia! > 0 ? '↑' : evolucion.diferencia! < 0 ? '↓' : '='}{' '}
            {evolucion.promedioAnterior} → {evolucion.promedioActual}{' '}
            <span className={evolucion.diferencia! > 0 ? 'text-success' : evolucion.diferencia! < 0 ? 'text-error' : 'text-muted-foreground'}>
              ({evolucion.diferencia! > 0 ? '+' : ''}{evolucion.diferencia})
            </span>
          </p>
        ) : (
          <p className="text-sm text-muted-foreground italic">Sin datos suficientes para comparar.</p>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Enganchar la pestaña nueva en `Perfildetail.tsx`**

Agregar el import (junto a los demás componentes de `DetailTables`):
```tsx
import {ProfileTab,LicenseHistoryTab,PermissionHistoryTab,DocumentsTab,FeedbackIndicatorsTab} from "./DetailTables"
```

Agregar el botón de tab, después del botón "documentos" (línea ~90-99 del archivo actual):
```tsx
<button
  onClick={() => setActiveTab("feedback360")}
  className={`${
    activeTab === "feedback360"
      ? "border-primary text-primary"
      : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
  } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
>
  Feedback 360°
</button>
```

Agregar el contenido de la pestaña, después de `{activeTab === "documentos" && <DocumentsTab employee={employee} />}`:
```tsx
{activeTab === "feedback360" && <FeedbackIndicatorsTab employee={employee} />}
```

- [ ] **Step 3: Verificar tipos**

Run: `npx tsc --noEmit 2>&1 | grep -E "TablaOperador/DetailTables|TablaOperador/Perfildetail"`
Expected: sin salida (sin errores nuevos en estos 2 archivos).

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/TablaOperador/DetailTables.tsx src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "feat: agregar seccion Feedback 360 con fortalezas/debilidades en la ficha de empleado"
```

---

### Task 3: Verificación manual

No hay test suite automatizado en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error.
- [ ] **Step 2:** Un empleado con respuestas recibidas en al menos 2 categorías distintas: `GET /feedback/received/{id}` devuelve `fortalezas`/`debilidades` ordenadas correctamente por promedio (fortalezas descendente, debilidades ascendente por puntuación).
- [ ] **Step 3:** Un empleado sin ninguna respuesta recibida: `GET /feedback/received/{id}` devuelve `fortalezas: []`, `debilidades: []`, `evolucion.diferencia: null`.
- [ ] **Step 4:** Cambiar la periodicidad vía `PUT /feedback/config` a cada uno de los 3 valores y confirmar (con un script rápido o inspección manual) que `get_periodo_anterior` calcula el período previo correctamente en cada caso.
- [ ] **Step 5:** En el frontend, abrir la ficha de un empleado con evaluaciones recibidas → pestaña "Feedback 360°" → confirmar que se ven las listas de Fortalezas/Debilidades y el indicador de evolución.
- [ ] **Step 6:** Abrir la ficha de un empleado sin evaluaciones recibidas → confirmar que se ve el mensaje "Este empleado todavía no recibió evaluaciones de Feedback 360°".
