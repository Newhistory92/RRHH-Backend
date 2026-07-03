# Reubicación — Motor de Análisis IA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tercer subsistema del módulo de Reubicación Inteligente: botón "Analizar Solicitudes" que corre un motor de matching determinista + Gemini para recomendar, con explicación/beneficios/riesgos, la mejor oficina destino para cada solicitud `Pendiente`, dejándolas en `Recomendada` para que RRHH revise y apruebe (pudiendo cambiar el destino).

**Architecture:** Nueva API route de Next.js (`/api/reubicacion-analysis`) orquesta el flujo: marca solicitudes como `En análisis` (backend), trae datos de empleados/oficinas (`GET /rrhh/org-analysis-data`, ya existe), corre un motor TS puro (`reubicacion-matching-engine.ts`) que calcula destino + score 0-100, y llama a Gemini (`GeminiService`, ya existe) solo para redactar la explicación/beneficios/riesgos (con fallback si falla). Cada recomendación se persiste vía un endpoint nuevo del backend, que pasa la solicitud a `Recomendada`. El tablero de RRHH (subsistema 2) se extiende con el botón, una vista de la recomendación, y un selector de destino (editable) en el diálogo de aprobación.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server (pyodbc), Next.js API routes, `@ai-sdk/google` (Gemini `gemini-2.5-flash` vía `GeminiService`), React, PrimeReact.

## Global Constraints

- Scoring 100% determinista en TS: 70% skill match + 30% déficit de personal de la oficina candidata. Gemini **nunca** decide destino ni score, solo redacta texto.
- La IA tiene **prohibido** mencionar "experiencia previa" — ese dato no existe en `org-analysis-data` hoy.
- Sin umbral de corte: el motor siempre recomienda la mejor oficina disponible; si el score es bajo, la explicación lo dice con honestidad.
- El análisis es **opcional**: RRHH puede aprobar/rechazar tanto en `Pendiente` (a ciegas, sin destino) como en `Recomendada` (con destino sugerido, editable).
- Todos los endpoints nuevos/extendidos usan `require_rrhh_auth` (ya definido en `app/routes/reubicacion.py` del subsistema 2: `require_roles(ROLE_ADMIN, ROLE_ADMIN)`).
- `beneficios`/`riesgos` viajan y se persisten como JSON string (`json.dumps`/`JSON.parse`), nunca como tablas hijas.
- Sin test suite automatizada en ninguno de los dos repos (`Backend_RRHH`, `RRHH`) — verificación por compilación (`py_compile`, `tsc --noEmit` filtrado) más scripts ad-hoc no commiteados para lógica pura, y verificación manual final.

---

### Task 1: Backend — columnas de recomendación y 3 endpoints (nuevos/extendidos)

**Files:**
- Modify: `app/database/reubicacion.py`
- Modify: `app/routes/reubicacion.py`

**Interfaces:**
- Produces: `POST /reubicacion/analizar/iniciar` (`require_rrhh_auth`) → `{"solicitudes": [{id, employeeId, employeeName, tipo, motivo, officeIdActual, departmentIdActual}], "count": n}`. `PATCH /reubicacion/{id}/recomendacion` (`require_rrhh_auth`), body `{officeIdSugerido, departmentIdSugerido, scoreCompatibilidad, explicacionIA, beneficios: string[], riesgos: string[]}` → `{"message": str, "estado": "Recomendada"}`. `GET /reubicacion/solicitudes` extendido con `officeIdSugerido, officeSugeridoName, departmentIdSugerido, departmentSugeridoName, scoreCompatibilidad, explicacionIA, beneficios: string[], riesgos: string[], officeIdDestino, departmentIdDestino`. `PATCH /reubicacion/{id}/estado` extendido: acepta `officeIdDestino`/`departmentIdDestino` opcionales en el body.

- [ ] **Step 1: Agregar las columnas nuevas en `ensure_table` (`app/database/reubicacion.py`)**

Reemplazar:
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
por:
```python
def ensure_table(db: Session) -> None:
    """Crea SolicitudReubicacion si no existe, y agrega las columnas de
    observacion y recomendacion IA si la tabla ya existia sin ellas
    (idempotente)."""
    db.execute(text(CREATE_TABLE_SQL))
    db.execute(text("""
        IF COL_LENGTH('SolicitudReubicacion', 'observacion') IS NULL
            ALTER TABLE SolicitudReubicacion ADD observacion NVARCHAR(MAX) NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'officeIdSugerido') IS NULL
            ALTER TABLE SolicitudReubicacion ADD officeIdSugerido INT NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'departmentIdSugerido') IS NULL
            ALTER TABLE SolicitudReubicacion ADD departmentIdSugerido INT NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'scoreCompatibilidad') IS NULL
            ALTER TABLE SolicitudReubicacion ADD scoreCompatibilidad INT NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'explicacionIA') IS NULL
            ALTER TABLE SolicitudReubicacion ADD explicacionIA NVARCHAR(MAX) NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'beneficios') IS NULL
            ALTER TABLE SolicitudReubicacion ADD beneficios NVARCHAR(MAX) NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'riesgos') IS NULL
            ALTER TABLE SolicitudReubicacion ADD riesgos NVARCHAR(MAX) NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'officeIdDestino') IS NULL
            ALTER TABLE SolicitudReubicacion ADD officeIdDestino INT NULL;
        IF COL_LENGTH('SolicitudReubicacion', 'departmentIdDestino') IS NULL
            ALTER TABLE SolicitudReubicacion ADD departmentIdDestino INT NULL;
    """))
    db.commit()
```

- [ ] **Step 2: Agregar `import json` y un helper de parseo en `app/routes/reubicacion.py`**

Reemplazar:
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
por:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from typing import Optional
import json
from app.database.database import SessionLocal
from app.auth_middleware import require_any_auth, get_current_user, require_roles, ROLE_ADMIN
from app.database.reubicacion import ensure_table, VALID_TIPOS

router = APIRouter(prefix="/reubicacion", tags=["Reubicacion"])

ROLE_RRHH = ROLE_ADMIN
require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)


def _parse_json_list(value) -> list:
    """Parsea un campo NVARCHAR con un JSON array; devuelve [] si es NULL o invalido."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
```

- [ ] **Step 3: Agregar `POST /reubicacion/analizar/iniciar` al final del archivo**

```python
# ─────────────────────────────────────────────────────────────────────────────
# POST /reubicacion/analizar/iniciar — marca Pendiente/En análisis como
# En análisis y las devuelve para que el orquestador (Next.js) las procese.
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/analizar/iniciar", dependencies=[Depends(require_rrhh_auth)])
def iniciar_analisis(db: Session = Depends(get_db)):
    """Marca las solicitudes Pendiente o En análisis como En análisis y las devuelve."""
    ensure_table(db)

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'En análisis', updatedAt = :now
        WHERE estado IN ('Pendiente', 'En análisis')
    """), {"now": now})
    db.commit()

    rows = db.execute(text("""
        SELECT sr.id, sr.employeeId, e.name AS employeeName, sr.tipo, sr.motivo,
               sr.officeIdActual, sr.departmentIdActual
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        WHERE sr.estado = 'En análisis'
        ORDER BY sr.createdAt ASC
    """)).mappings().all()

    solicitudes = [
        {
            "id": r["id"],
            "employeeId": r["employeeId"],
            "employeeName": r["employeeName"],
            "tipo": r["tipo"],
            "motivo": r["motivo"],
            "officeIdActual": r["officeIdActual"],
            "departmentIdActual": r["departmentIdActual"],
        }
        for r in rows
    ]

    return {"solicitudes": solicitudes, "count": len(solicitudes)}


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /reubicacion/{solicitud_id}/recomendacion — guarda la recomendacion
# del motor de IA y pasa la solicitud a 'Recomendada'.
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{solicitud_id}/recomendacion", dependencies=[Depends(require_rrhh_auth)])
def guardar_recomendacion(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Guarda la recomendacion de IA (destino, score, explicacion) y pasa a Recomendada."""
    office_id_sugerido = data.get("officeIdSugerido")
    department_id_sugerido = data.get("departmentIdSugerido")
    score = data.get("scoreCompatibilidad")
    explicacion = data.get("explicacionIA")
    beneficios = data.get("beneficios") or []
    riesgos = data.get("riesgos") or []

    if score is None or not isinstance(score, (int, float)):
        raise HTTPException(status_code=400, detail="scoreCompatibilidad es requerido y debe ser numerico")

    ensure_table(db)

    solicitud = db.execute(text("""
        SELECT id FROM SolicitudReubicacion WHERE id = :id
    """), {"id": solicitud_id}).mappings().first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    now = datetime.utcnow()
    db.execute(text("""
        UPDATE SolicitudReubicacion
        SET estado = 'Recomendada',
            officeIdSugerido = :officeIdSugerido,
            departmentIdSugerido = :departmentIdSugerido,
            scoreCompatibilidad = :score,
            explicacionIA = :explicacion,
            beneficios = :beneficios,
            riesgos = :riesgos,
            updatedAt = :now
        WHERE id = :id
    """), {
        "officeIdSugerido": office_id_sugerido,
        "departmentIdSugerido": department_id_sugerido,
        "score": int(score),
        "explicacion": explicacion,
        "beneficios": json.dumps(beneficios, ensure_ascii=False),
        "riesgos": json.dumps(riesgos, ensure_ascii=False),
        "now": now,
        "id": solicitud_id,
    })
    db.commit()

    return {"message": "Recomendación guardada", "estado": "Recomendada"}
```

- [ ] **Step 4: Extender `PATCH /{solicitud_id}/estado` para aceptar destino confirmado**

Reemplazar:
```python
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
```
por:
```python
@router.patch("/{solicitud_id}/estado", dependencies=[Depends(require_rrhh_auth)])
def update_estado(solicitud_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Aprueba o rechaza una solicitud de reubicacion, notificando al empleado."""
    estado = data.get("estado")
    observacion = data.get("observacion")
    office_id_destino = data.get("officeIdDestino")
    department_id_destino = data.get("departmentIdDestino")

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
        SET estado = :estado, observacion = :observacion,
            officeIdDestino = :officeIdDestino, departmentIdDestino = :departmentIdDestino,
            updatedAt = :now
        WHERE id = :id
    """), {
        "estado": estado, "observacion": observacion,
        "officeIdDestino": office_id_destino, "departmentIdDestino": department_id_destino,
        "now": now, "id": solicitud_id,
    })
```

(El resto de la función — inserción del `Message` y el `return` — no cambia.)

- [ ] **Step 5: Extender `GET /solicitudes` con los campos de recomendación**

Reemplazar:
```python
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
```
por:
```python
    query = """
        SELECT
            sr.id, sr.employeeId, e.name AS employeeName,
            sr.tipo, sr.motivo, sr.estado, sr.observacion,
            sr.officeIdActual, o.nombre AS officeName,
            sr.departmentIdActual, d.nombre AS departmentName,
            sr.officeIdSugerido, os.nombre AS officeSugeridoName,
            sr.departmentIdSugerido, ds.nombre AS departmentSugeridoName,
            sr.scoreCompatibilidad, sr.explicacionIA, sr.beneficios, sr.riesgos,
            sr.officeIdDestino, sr.departmentIdDestino,
            sr.createdAt, sr.updatedAt
        FROM SolicitudReubicacion sr
        LEFT JOIN Employee e ON e.id = sr.employeeId
        LEFT JOIN Office o ON o.id = sr.officeIdActual
        LEFT JOIN Department d ON d.id = sr.departmentIdActual
        LEFT JOIN Office os ON os.id = sr.officeIdSugerido
        LEFT JOIN Department ds ON ds.id = sr.departmentIdSugerido
        WHERE 1=1
    """
```

Y reemplazar el bloque de armado de la respuesta:
```python
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
```
por:
```python
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
                "officeIdSugerido": r["officeIdSugerido"],
                "officeSugeridoName": r["officeSugeridoName"],
                "departmentIdSugerido": r["departmentIdSugerido"],
                "departmentSugeridoName": r["departmentSugeridoName"],
                "scoreCompatibilidad": r["scoreCompatibilidad"],
                "explicacionIA": r["explicacionIA"],
                "beneficios": _parse_json_list(r["beneficios"]),
                "riesgos": _parse_json_list(r["riesgos"]),
                "officeIdDestino": r["officeIdDestino"],
                "departmentIdDestino": r["departmentIdDestino"],
                "createdAt": r["createdAt"].isoformat() if r["createdAt"] else None,
                "updatedAt": r["updatedAt"].isoformat() if r["updatedAt"] else None,
            }
            for r in rows
        ]
    }
```

- [ ] **Step 6: Verificar que compila**

Run: `py -m py_compile app/database/reubicacion.py app/routes/reubicacion.py`
Expected: sin salida.

- [ ] **Step 7: Commit**

```bash
git add app/database/reubicacion.py app/routes/reubicacion.py
git commit -m "feat: agregar motor de analisis IA para reubicacion (backend)"
```

---

### Task 2: Frontend — motor de matching, prompt IA, y route de orquestación

**Files:**
- Create: `src/app/lib/reubicacion-matching-engine.ts`
- Create: `src/app/lib/reubicacion-recomendacion-prompt.ts`
- Create: `src/app/api/reubicacion-analysis/route.ts`

**Interfaces:**
- Consumes: `OrgAnalysisEmployee`, `OrgAnalysisDepartment` (ya existen en `src/app/Interfas/Interfaces.ts`). `GeminiService.generateResponse(messages: ChatMessage[])` (ya existe en `src/app/lib/ai-service.ts`, devuelve `{ text, toolCalls, toolResults }`). Backend: `POST /reubicacion/analizar/iniciar`, `GET /rrhh/org-analysis-data`, `PATCH /reubicacion/{id}/recomendacion` (Task 1).
- Produces: `findBestRelocationMatch(employee, allEmployees, departments): MatchResult` (motor). `buildRecomendacionPrompt(employee, motivo, match): string` y `buildFallbackRecomendacion(match): RecomendacionIA` (prompt). Endpoint `POST /api/reubicacion-analysis` → `{success, analizadas, errores: [{solicitudId, motivo}]}`.

- [ ] **Step 1: Crear `src/app/lib/reubicacion-matching-engine.ts`**

```ts
/**
 * Motor de Matching para Reubicacion Inteligente (subsistema 3).
 *
 * Determina, para un empleado que solicito reubicacion, cual es la mejor
 * oficina destino (excluyendo la actual) en base a:
 * - Skill match (70%): que porcentaje de las habilidades requeridas de la
 *   oficina candidata posee el empleado.
 * - Deficit de personal (30%): que porcentaje de esas habilidades requeridas
 *   NO esta cubierto por la dotacion actual de esa oficina (prioriza mandar
 *   gente a donde falta cobertura).
 */

import type { OrgAnalysisEmployee, OrgAnalysisDepartment } from "@/app/Interfas/Interfaces";

const SKILL_MATCH_WEIGHT = 0.7;
const DEFICIT_WEIGHT = 0.3;

interface CandidateOffice {
  officeId: number;
  officeNombre: string;
  departmentId: number;
  departmentNombre: string;
  habilidadesRequeridas: { nombre: string; level: number }[];
}

export interface MatchResult {
  officeIdSugerido: number | null;
  officeNombreSugerido: string | null;
  departmentIdSugerido: number | null;
  departmentNombreSugerido: string | null;
  scoreCompatibilidad: number;
  matchedSkills: string[];
  missingSkills: string[];
  deficitSkills: string[];
}

function employeeSkillNames(employee: OrgAnalysisEmployee): Set<string> {
  const names = new Set<string>();
  for (const s of employee.softSkills) names.add(s.nombre.toLowerCase());
  for (const t of employee.technicalSkills) names.add(t.nombre.toLowerCase());
  return names;
}

function listCandidateOffices(
  departments: OrgAnalysisDepartment[],
  excludeOfficeId: number | null
): CandidateOffice[] {
  const candidates: CandidateOffice[] = [];
  for (const dept of departments) {
    for (const office of dept.offices) {
      if (office.id === excludeOfficeId) continue;
      candidates.push({
        officeId: office.id,
        officeNombre: office.nombre,
        departmentId: dept.id,
        departmentNombre: dept.nombre,
        habilidadesRequeridas: office.habilidades_requeridas,
      });
    }
  }
  return candidates;
}

type ScoreDetails = Pick<
  MatchResult,
  "scoreCompatibilidad" | "matchedSkills" | "missingSkills" | "deficitSkills"
>;

function scoreCandidate(
  candidate: CandidateOffice,
  empSkillNames: Set<string>,
  allEmployees: OrgAnalysisEmployee[]
): ScoreDetails {
  const required = candidate.habilidadesRequeridas;

  if (required.length === 0) {
    // Sin requisitos definidos para esta oficina: no se puede evaluar match
    // ni deficit, se usa un score neutral para no penalizar ni favorecer.
    return { scoreCompatibilidad: 50, matchedSkills: [], missingSkills: [], deficitSkills: [] };
  }

  const matchedSkills = required.filter((r) => empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const missingSkills = required.filter((r) => !empSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const skillMatchRatio = matchedSkills.length / required.length;

  const staffSkillNames = new Set<string>();
  for (const emp of allEmployees) {
    if (emp.officeId !== candidate.officeId) continue;
    for (const s of emp.softSkills) staffSkillNames.add(s.nombre.toLowerCase());
    for (const t of emp.technicalSkills) staffSkillNames.add(t.nombre.toLowerCase());
  }
  const deficitSkills = required.filter((r) => !staffSkillNames.has(r.nombre.toLowerCase())).map((r) => r.nombre);
  const deficitRatio = deficitSkills.length / required.length;

  const scoreCompatibilidad = Math.round(
    skillMatchRatio * SKILL_MATCH_WEIGHT * 100 + deficitRatio * DEFICIT_WEIGHT * 100
  );

  return { scoreCompatibilidad, matchedSkills, missingSkills, deficitSkills };
}

export function findBestRelocationMatch(
  employee: OrgAnalysisEmployee,
  allEmployees: OrgAnalysisEmployee[],
  departments: OrgAnalysisDepartment[]
): MatchResult {
  const candidates = listCandidateOffices(departments, employee.officeId);
  const empSkillNames = employeeSkillNames(employee);

  let best: MatchResult | null = null;

  for (const candidate of candidates) {
    const scored = scoreCandidate(candidate, empSkillNames, allEmployees);
    if (!best || scored.scoreCompatibilidad > best.scoreCompatibilidad) {
      best = {
        officeIdSugerido: candidate.officeId,
        officeNombreSugerido: candidate.officeNombre,
        departmentIdSugerido: candidate.departmentId,
        departmentNombreSugerido: candidate.departmentNombre,
        ...scored,
      };
    }
  }

  return (
    best ?? {
      officeIdSugerido: null,
      officeNombreSugerido: null,
      departmentIdSugerido: null,
      departmentNombreSugerido: null,
      scoreCompatibilidad: 0,
      matchedSkills: [],
      missingSkills: [],
      deficitSkills: [],
    }
  );
}
```

- [ ] **Step 2: Verificar el motor con un script ad-hoc (no se commitea)**

Crear `verify-matching-tmp.ts` en la raíz de `RRHH` (mismo nivel que `package.json`):

```ts
import assert from "node:assert";
import { findBestRelocationMatch } from "./src/app/lib/reubicacion-matching-engine";
import type { OrgAnalysisEmployee, OrgAnalysisDepartment } from "./src/app/Interfas/Interfaces";

const baseEmployee = {
  dni: "1",
  status: "activo",
  productivityScore: 5,
  officeName: null,
  managerId: null,
  position: null,
  tipoContrato: null,
  fechaIngreso: null,
  categoria: null,
  licenses: {},
  absences: {},
  satisfactionMetrics: {
    overallSatisfaction: 0,
    jobSatisfaction: 0,
    teamSatisfaction: 0,
    leadershipSatisfaction: 0,
    careerGrowthSatisfaction: 0,
  },
};

const employee: OrgAnalysisEmployee = {
  ...baseEmployee,
  id: 1,
  name: "Juan",
  officeId: 1,
  departmentId: 1,
  departmentName: "Ventas",
  softSkills: [],
  technicalSkills: [{ nombre: "React", level: "Avanzado" }],
};

const departments: OrgAnalysisDepartment[] = [
  {
    id: 1,
    nombre: "Ventas",
    description: null,
    jefeId: null,
    nivelJerarquico: null,
    parentId: null,
    habilidades_requeridas: [],
    offices: [{ id: 1, nombre: "Oficina A", jefeId: null, habilidades_requeridas: [] }],
  },
  {
    id: 2,
    nombre: "Sistemas",
    description: null,
    jefeId: null,
    nivelJerarquico: null,
    parentId: null,
    habilidades_requeridas: [],
    offices: [
      {
        id: 2,
        nombre: "Oficina Sistemas",
        jefeId: null,
        habilidades_requeridas: [
          { nombre: "React", level: 3 },
          { nombre: "Node", level: 2 },
        ],
      },
    ],
  },
];

const result = findBestRelocationMatch(employee, [employee], departments);

assert.strictEqual(result.officeIdSugerido, 2);
assert.strictEqual(result.scoreCompatibilidad, 65);
assert.deepStrictEqual(result.matchedSkills, ["React"]);
assert.deepStrictEqual(result.missingSkills, ["Node"]);
assert.deepStrictEqual(result.deficitSkills, ["React", "Node"]);

console.log("OK: findBestRelocationMatch matchea la oficina con mayor score");
```

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsx verify-matching-tmp.ts`
Expected: `OK: findBestRelocationMatch matchea la oficina con mayor score`

Luego borrar el script (no se commitea):
Run: `cd "C:\Users\Emiliano\Documents\RRHH" && rm verify-matching-tmp.ts`

- [ ] **Step 3: Crear `src/app/lib/reubicacion-recomendacion-prompt.ts`**

```ts
/**
 * Prompt Builder para la recomendacion de reubicacion (subsistema 3).
 * El motor determinista (reubicacion-matching-engine.ts) ya calculo el
 * destino y el score; Gemini solo redacta la explicacion en espanol.
 */

import type { OrgAnalysisEmployee } from "@/app/Interfas/Interfaces";
import type { MatchResult } from "./reubicacion-matching-engine";

export interface RecomendacionIA {
  explicacion: string;
  beneficios: string[];
  riesgos: string[];
}

export function buildRecomendacionPrompt(
  employee: OrgAnalysisEmployee,
  motivo: string,
  match: MatchResult
): string {
  return `
Eres un consultor de Recursos Humanos. Redacta en español una recomendación de
reubicación interna para RRHH, basándote EXCLUSIVAMENTE en los siguientes datos
YA CALCULADOS (no inventes información, especialmente NO menciones "experiencia
previa" porque ese dato no está disponible):

Empleado: ${employee.name}
Motivo de la solicitud: ${motivo}
Oficina actual: ${employee.officeName ?? "sin oficina asignada"} (${employee.departmentName})
Oficina destino sugerida: ${match.officeNombreSugerido ?? "ninguna disponible"} (${match.departmentNombreSugerido ?? "-"})
Score de compatibilidad: ${match.scoreCompatibilidad}%
Habilidades que coinciden: ${match.matchedSkills.join(", ") || "ninguna"}
Habilidades que le faltan: ${match.missingSkills.join(", ") || "ninguna"}
Habilidades con déficit de personal en el destino: ${match.deficitSkills.join(", ") || "ninguna"}

Responde ESTRICTAMENTE con este JSON:
{
  "explicacion": "1-2 oraciones explicando por que se recomienda (o no) este destino, mencionando el % de compatibilidad y el deficit de personal si aplica. Si el score es bajo (menor a 50), se honesto y dilo explicitamente.",
  "beneficios": ["beneficio esperado 1", "beneficio esperado 2"],
  "riesgos": ["riesgo 1", "riesgo 2"]
}

REGLAS:
- Responde SOLO con el JSON, sin texto adicional antes ni después.
- Basa todo EXCLUSIVAMENTE en los datos provistos arriba.
- Entre 2 y 4 items en "beneficios" y entre 2 y 4 en "riesgos".
- Todo en español.
`;
}

export function buildFallbackRecomendacion(match: MatchResult): RecomendacionIA {
  const destino = match.officeNombreSugerido;

  if (!destino) {
    return {
      explicacion: `No se encontró un destino con datos suficientes para recomendar una reubicación (score ${match.scoreCompatibilidad}%).`,
      beneficios: [],
      riesgos: ["Sin datos suficientes para evaluar el traslado"],
    };
  }

  const explicacion =
    match.scoreCompatibilidad >= 50
      ? `Se recomienda trasladar al empleado a ${destino} debido a que posee un ${match.scoreCompatibilidad}% de compatibilidad con las competencias requeridas${
          match.deficitSkills.length > 0
            ? " y actualmente existe un déficit de personal especializado en esa oficina"
            : ""
        }.`
      : `La compatibilidad con ${destino} es baja (${match.scoreCompatibilidad}%): se recomienda evaluar con cautela antes de aprobar este traslado.`;

  return {
    explicacion,
    beneficios: ["Mejor aprovechamiento del talento", "Cobertura de vacantes", "Mayor productividad"],
    riesgos: ["Pérdida de conocimiento en la oficina actual", "Necesidad de reemplazo", "Impacto operativo temporal"],
  };
}
```

- [ ] **Step 4: Crear `src/app/api/reubicacion-analysis/route.ts`**

```ts
/**
 * API Route: /api/reubicacion-analysis
 *
 * Orquesta el motor de analisis IA de reubicacion (subsistema 3):
 * 1. Marca las solicitudes Pendiente/En analisis como En analisis (backend).
 * 2. Obtiene datos de empleados/departamentos (backend, ya existente).
 * 3. Para cada solicitud: corre el motor de matching + Gemini (con fallback).
 * 4. Persiste la recomendacion de cada una (backend).
 */

import { NextRequest, NextResponse } from "next/server";
import { findBestRelocationMatch } from "@/app/lib/reubicacion-matching-engine";
import { buildRecomendacionPrompt, buildFallbackRecomendacion } from "@/app/lib/reubicacion-recomendacion-prompt";
import { GeminiService } from "@/app/lib/ai-service";
import type { OrgAnalysisEmployee, OrgAnalysisDepartment } from "@/app/Interfas/Interfaces";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

interface SolicitudAAnalizar {
  id: number;
  employeeId: number;
  employeeName: string;
  tipo: string;
  motivo: string;
  officeIdActual: number | null;
  departmentIdActual: number | null;
}

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("authorization") || "";
  const backendHeaders = { "Content-Type": "application/json", Authorization: authHeader };

  try {
    // ── 1. Marcar solicitudes como "En análisis" ────────────────────────────
    const iniciarResponse = await fetch(`${BACKEND_URL}/reubicacion/analizar/iniciar`, {
      method: "POST",
      headers: backendHeaders,
    });
    if (!iniciarResponse.ok) {
      throw new Error(`Backend respondió con status ${iniciarResponse.status} al iniciar el análisis`);
    }
    const { solicitudes }: { solicitudes: SolicitudAAnalizar[] } = await iniciarResponse.json();

    if (solicitudes.length === 0) {
      return NextResponse.json({ success: true, analizadas: 0, errores: [] });
    }

    // ── 2. Obtener datos de empleados y departamentos ───────────────────────
    const dataResponse = await fetch(`${BACKEND_URL}/rrhh/org-analysis-data`, {
      method: "GET",
      headers: backendHeaders,
    });
    if (!dataResponse.ok) {
      throw new Error(`Backend respondió con status ${dataResponse.status} al obtener org-analysis-data`);
    }
    const { employees, departments }: { employees: OrgAnalysisEmployee[]; departments: OrgAnalysisDepartment[] } =
      await dataResponse.json();

    // ── 3. Analizar cada solicitud ───────────────────────────────────────────
    let analizadas = 0;
    const errores: { solicitudId: number; motivo: string }[] = [];

    for (const solicitud of solicitudes) {
      try {
        const employee = employees.find((e) => e.id === solicitud.employeeId);
        if (!employee) {
          errores.push({ solicitudId: solicitud.id, motivo: "Empleado no encontrado en org-analysis-data" });
          continue;
        }

        const match = findBestRelocationMatch(employee, employees, departments);

        let recomendacion = buildFallbackRecomendacion(match);
        try {
          const prompt = buildRecomendacionPrompt(employee, solicitud.motivo, match);
          const aiResponse = await GeminiService.generateResponse([
            { role: "system", content: "Eres un consultor de RRHH. Responde SOLO con JSON válido." },
            { role: "user", content: prompt },
          ]);
          const jsonMatch = (aiResponse.text || "").match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            if (parsed.explicacion && Array.isArray(parsed.beneficios) && Array.isArray(parsed.riesgos)) {
              recomendacion = parsed;
            }
          }
        } catch (aiError) {
          console.error(`IA falló para solicitud ${solicitud.id}, usando fallback:`, aiError);
        }

        const patchResponse = await fetch(`${BACKEND_URL}/reubicacion/${solicitud.id}/recomendacion`, {
          method: "PATCH",
          headers: backendHeaders,
          body: JSON.stringify({
            officeIdSugerido: match.officeIdSugerido,
            departmentIdSugerido: match.departmentIdSugerido,
            scoreCompatibilidad: match.scoreCompatibilidad,
            explicacionIA: recomendacion.explicacion,
            beneficios: recomendacion.beneficios,
            riesgos: recomendacion.riesgos,
          }),
        });
        if (!patchResponse.ok) {
          throw new Error(`Backend respondió con status ${patchResponse.status}`);
        }

        analizadas++;
      } catch (err) {
        errores.push({
          solicitudId: solicitud.id,
          motivo: err instanceof Error ? err.message : "Error desconocido",
        });
      }
    }

    return NextResponse.json({ success: true, analizadas, errores });
  } catch (error) {
    console.error("Error en análisis de reubicación:", error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : "Error desconocido" },
      { status: 500 }
    );
  }
}
```

- [ ] **Step 5: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "reubicacion-matching-engine|reubicacion-recomendacion-prompt|api/reubicacion-analysis"`
Expected: sin salida (sin errores nuevos en estos 3 archivos).

- [ ] **Step 6: Commit**

```bash
git add src/app/lib/reubicacion-matching-engine.ts src/app/lib/reubicacion-recomendacion-prompt.ts src/app/api/reubicacion-analysis/route.ts
git commit -m "feat: agregar motor de matching y orquestacion IA para reubicacion (frontend)"
```

---

### Task 3: Frontend — botón "Analizar Solicitudes", vista de recomendación, y override de destino

**Files:**
- Modify: `src/app/screens/ReubicacionTablero/Screen.tsx`

**Interfaces:**
- Consumes: `POST /api/reubicacion-analysis` (Task 2) → `{success, analizadas, errores}`. `GET /reubicacion/solicitudes` extendido (Task 1). `PATCH /reubicacion/{id}/estado` extendido (Task 1).
- Produces: ningún consumidor externo — es la pantalla final.

- [ ] **Step 1: Extender la interfaz `SolicitudRRHH` con los campos de recomendación**

Reemplazar:
```tsx
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
```
por:
```tsx
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
  officeIdSugerido: number | null;
  officeSugeridoName: string | null;
  departmentIdSugerido: number | null;
  departmentSugeridoName: string | null;
  scoreCompatibilidad: number | null;
  explicacionIA: string | null;
  beneficios: string[];
  riesgos: string[];
  officeIdDestino: number | null;
  departmentIdDestino: number | null;
  createdAt: string;
  updatedAt: string;
}
```

- [ ] **Step 2: Agregar el estado nuevo (destino seleccionado, análisis en curso, recomendación abierta)**

Reemplazar:
```tsx
  const [seleccionada, setSeleccionada] = useState<{ solicitud: SolicitudRRHH; accion: 'Aprobada' | 'Rechazada' } | null>(null);
  const [observacion, setObservacion] = useState('');
  const [guardando, setGuardando] = useState(false);
  const toast = useRef<Toast>(null);
```
por:
```tsx
  const [seleccionada, setSeleccionada] = useState<{ solicitud: SolicitudRRHH; accion: 'Aprobada' | 'Rechazada' } | null>(null);
  const [observacion, setObservacion] = useState('');
  const [destinoSeleccionado, setDestinoSeleccionado] = useState<number | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [analizando, setAnalizando] = useState(false);
  const [verRecomendacion, setVerRecomendacion] = useState<SolicitudRRHH | null>(null);
  const toast = useRef<Toast>(null);
```

- [ ] **Step 3: Agregar helpers de destino/score y la función `analizarSolicitudes`**

Ubicar el bloque (justo después de `departmentOptions`):
```tsx
  const officeOptions = departments.flatMap((d) => d.offices.map((o) => ({ label: o.nombre, value: o.id })));
  const departmentOptions = departments.map((d) => ({ label: d.nombre, value: d.id }));
```
y agregar debajo:
```tsx

  const findDepartmentIdForOffice = (officeId: number | null): number | null => {
    if (!officeId) return null;
    const dept = departments.find((d) => d.offices.some((o) => o.id === officeId));
    return dept ? dept.id : null;
  };

  const scoreBadgeClase = (score: number) =>
    score >= 70
      ? 'bg-success-soft text-success-soft-foreground border-success'
      : score >= 40
      ? 'bg-warning-soft text-warning-soft-foreground border-warning'
      : 'bg-error-soft text-error-soft-foreground border-error';
```

Ubicar el bloque (justo antes de `const abrirAccion = ...`):
```tsx
  useEffect(() => {
    cargarSolicitudes();
  }, [cargarSolicitudes]);
```
y agregar debajo:
```tsx

  const analizarSolicitudes = async () => {
    setAnalizando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/api/reubicacion-analysis', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!response.ok) throw new Error(`Error: ${response.status}`);
      const data: { analizadas: number; errores: { solicitudId: number; motivo: string }[] } = await response.json();
      if (data.errores.length > 0) {
        toast.current?.show({
          severity: 'warn',
          summary: 'Análisis parcial',
          detail: `${data.analizadas} analizadas, ${data.errores.length} con error`,
          life: 5000,
        });
      } else {
        toast.current?.show({
          severity: 'success',
          summary: 'Análisis completado',
          detail: `${data.analizadas} solicitudes analizadas`,
          life: 4000,
        });
      }
      await cargarSolicitudes();
    } catch (err) {
      console.error('Error al analizar solicitudes:', err);
      toast.current?.show({ severity: 'error', summary: 'Error', detail: 'No se pudo completar el análisis', life: 4000 });
    } finally {
      setAnalizando(false);
    }
  };
```

- [ ] **Step 4: Prefijar el destino sugerido al abrir el diálogo de aprobación**

Reemplazar:
```tsx
  const abrirAccion = (solicitud: SolicitudRRHH, accion: 'Aprobada' | 'Rechazada') => {
    setSeleccionada({ solicitud, accion });
    setObservacion('');
  };
```
por:
```tsx
  const abrirAccion = (solicitud: SolicitudRRHH, accion: 'Aprobada' | 'Rechazada') => {
    setSeleccionada({ solicitud, accion });
    setObservacion('');
    setDestinoSeleccionado(solicitud.officeIdSugerido ?? null);
  };
```

- [ ] **Step 5: Enviar el destino confirmado al aprobar**

Reemplazar:
```tsx
  const confirmarAccion = async () => {
    if (!seleccionada) return;
    setGuardando(true);
    try {
      await apiClient.patch(`/reubicacion/${seleccionada.solicitud.id}/estado`, {
        estado: seleccionada.accion,
        observacion: observacion.trim() || null,
      });
```
por:
```tsx
  const confirmarAccion = async () => {
    if (!seleccionada) return;
    setGuardando(true);
    try {
      const esAprobacion = seleccionada.accion === 'Aprobada';
      await apiClient.patch(`/reubicacion/${seleccionada.solicitud.id}/estado`, {
        estado: seleccionada.accion,
        observacion: observacion.trim() || null,
        officeIdDestino: esAprobacion ? destinoSeleccionado : null,
        departmentIdDestino: esAprobacion ? findDepartmentIdForOffice(destinoSeleccionado) : null,
      });
```

- [ ] **Step 6: Agregar el botón "Analizar Solicitudes" y "Ver recomendación" en las tarjetas**

Reemplazar:
```tsx
  const puedeAccionar = (estado: string) => estado === 'Pendiente' || estado === 'Recomendada';

  const AccionesSolicitud = ({ s }: { s: SolicitudRRHH }) => (
    puedeAccionar(s.estado) ? (
      <div className="flex gap-2 mt-2">
        <Button label="Aprobar" icon="pi pi-check" severity="success" size="small" onClick={() => abrirAccion(s, 'Aprobada')} />
        <Button label="Rechazar" icon="pi pi-times" severity="danger" size="small" onClick={() => abrirAccion(s, 'Rechazada')} />
      </div>
    ) : null
  );
```
por:
```tsx
  const puedeAccionar = (estado: string) => estado === 'Pendiente' || estado === 'Recomendada';
  const hayPendientes = solicitudes.some((s) => s.estado === 'Pendiente' || s.estado === 'En análisis');

  const AccionesSolicitud = ({ s }: { s: SolicitudRRHH }) => (
    puedeAccionar(s.estado) ? (
      <div className="flex gap-2 mt-2">
        <Button label="Aprobar" icon="pi pi-check" severity="success" size="small" onClick={() => abrirAccion(s, 'Aprobada')} />
        <Button label="Rechazar" icon="pi pi-times" severity="danger" size="small" onClick={() => abrirAccion(s, 'Rechazada')} />
      </div>
    ) : null
  );

  const VerRecomendacionBoton = ({ s }: { s: SolicitudRRHH }) => (
    s.estado === 'Recomendada' && s.scoreCompatibilidad !== null ? (
      <Button
        label="Ver recomendación"
        icon="pi pi-eye"
        className="p-button-text p-button-sm mt-1"
        onClick={() => setVerRecomendacion(s)}
      />
    ) : null
  );
```

Reemplazar el `header` (agrega el botón "Analizar Solicitudes" antes del toggle Kanban/Tabla):
```tsx
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground mb-1">Solicitudes de Reubicación</h1>
            <p className="text-muted-foreground">Tablero de RRHH para gestionar la movilidad interna.</p>
          </div>
          <div className="flex gap-2">
            <button
```
por:
```tsx
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground mb-1">Solicitudes de Reubicación</h1>
            <p className="text-muted-foreground">Tablero de RRHH para gestionar la movilidad interna.</p>
          </div>
          <div className="flex gap-2 items-center">
            <Button
              label="Analizar Solicitudes"
              icon="pi pi-sparkles"
              loading={analizando}
              disabled={!hayPendientes}
              onClick={analizarSolicitudes}
            />
            <button
```

- [ ] **Step 7: Mostrar el botón "Ver recomendación" en la vista Kanban y en la vista Tabla**

Reemplazar (vista Kanban):
```tsx
                {solicitudes.filter((s) => s.estado === estado).map((s) => (
                  <div key={s.id} className="p-3 border border-border rounded-lg bg-background">
                    <p className="font-semibold text-sm text-foreground">{s.employeeName}</p>
                    <p className="text-xs text-muted-foreground">{s.tipo}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{s.motivo}</p>
                    <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                    <AccionesSolicitud s={s} />
                  </div>
                ))}
```
por:
```tsx
                {solicitudes.filter((s) => s.estado === estado).map((s) => (
                  <div key={s.id} className="p-3 border border-border rounded-lg bg-background">
                    <p className="font-semibold text-sm text-foreground">{s.employeeName}</p>
                    <p className="text-xs text-muted-foreground">{s.tipo}</p>
                    <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{s.motivo}</p>
                    <p className="text-xs text-muted-foreground mt-1">{formatDate(s.createdAt)}</p>
                    <VerRecomendacionBoton s={s} />
                    <AccionesSolicitud s={s} />
                  </div>
                ))}
```

Reemplazar (vista Tabla):
```tsx
                    <td className="py-2 px-3 text-muted-foreground">{formatDate(s.createdAt)}</td>
                    <td className="py-2 px-3"><AccionesSolicitud s={s} /></td>
```
por:
```tsx
                    <td className="py-2 px-3 text-muted-foreground">{formatDate(s.createdAt)}</td>
                    <td className="py-2 px-3">
                      <VerRecomendacionBoton s={s} />
                      <AccionesSolicitud s={s} />
                    </td>
```

- [ ] **Step 8: Agregar el selector de destino al diálogo de aprobación**

Reemplazar:
```tsx
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
por:
```tsx
        <div className="space-y-3">
          {seleccionada?.accion === 'Aprobada' && (
            <div>
              <label className="block text-sm font-semibold text-foreground mb-1">Oficina destino (opcional)</label>
              <Dropdown
                value={destinoSeleccionado}
                options={officeOptions}
                onChange={(e) => setDestinoSeleccionado(e.value)}
                showClear
                placeholder="Sin destino"
                className="w-full"
              />
            </div>
          )}
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

      <Dialog
        header={verRecomendacion ? `Recomendación para ${verRecomendacion.employeeName}` : ''}
        visible={!!verRecomendacion}
        onHide={() => setVerRecomendacion(null)}
        style={{ width: '32rem' }}
        modal
      >
        {verRecomendacion && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Destino sugerido</p>
                <p className="font-semibold text-foreground">
                  {verRecomendacion.officeSugeridoName ?? 'Sin destino'} / {verRecomendacion.departmentSugeridoName ?? '—'}
                </p>
              </div>
              <span className={`px-3 py-1 text-sm font-bold rounded-full border ${scoreBadgeClase(verRecomendacion.scoreCompatibilidad ?? 0)}`}>
                {verRecomendacion.scoreCompatibilidad ?? 0}%
              </span>
            </div>
            <p className="text-sm text-foreground">{verRecomendacion.explicacionIA}</p>
            <div>
              <p className="text-sm font-semibold text-foreground mb-1">Beneficios esperados</p>
              <ul className="text-sm text-muted-foreground space-y-1">
                {verRecomendacion.beneficios.map((b, i) => (
                  <li key={i}>✓ {b}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground mb-1">Riesgos</p>
              <ul className="text-sm text-muted-foreground space-y-1">
                {verRecomendacion.riesgos.map((r, i) => (
                  <li key={i}>⚠ {r}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 9: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "screens/ReubicacionTablero/Screen"`
Expected: sin salida (sin errores nuevos en este archivo).

- [ ] **Step 10: Commit**

```bash
git add src/app/screens/ReubicacionTablero/Screen.tsx
git commit -m "feat: agregar boton de analisis y vista de recomendacion al tablero de reubicacion"
```

---

### Task 4: Verificación manual

No hay test suite automatizada en ninguno de los dos repos — verificación manual, sin commits.

- [ ] **Step 1:** Levantar el backend y confirmar que arranca sin error; `POST /reubicacion/analizar/iniciar` marca `Pendiente`+`En análisis` → `En análisis` y las devuelve; un usuario USER recibe 403.
- [ ] **Step 2:** `PATCH /reubicacion/{id}/recomendacion` guarda los campos, parsea `beneficios`/`riesgos` correctamente al leer con `GET /solicitudes`, y la solicitud pasa a `Recomendada`.
- [ ] **Step 3:** `PATCH /reubicacion/{id}/estado` con `estado="Aprobada"` y `officeIdDestino` distinto del `officeIdSugerido` persiste el destino elegido por RRHH (override funciona).
- [ ] **Step 4:** En el frontend, loguearse como RRHH/Admin, entrar a "Reubicación", y clickear "Analizar Solicitudes" con al menos una solicitud `Pendiente`: el botón muestra loading, al terminar aparece el toast con la cantidad analizada, y las tarjetas pasan a `Recomendada`.
- [ ] **Step 5:** Abrir "Ver recomendación" en una solicitud `Recomendada`: se ve el destino sugerido, el score con el color correcto (verde ≥70, ámbar 40-69, rojo <40), la explicación, y las listas de beneficios/riesgos.
- [ ] **Step 6:** Aprobar una solicitud `Recomendada` sin tocar el dropdown (usa el destino sugerido) y otra cambiando el dropdown a otra oficina: en ambos casos se guarda el destino correcto y el empleado recibe la notificación en la campanita.
- [ ] **Step 7:** Aprobar una solicitud `Pendiente` sin analizar (a ciegas, dropdown vacío): sigue funcionando igual que antes del subsistema 3.
- [ ] **Step 8:** Con todas las solicitudes ya en `Recomendada`/`Aprobada`/`Rechazada` (ninguna `Pendiente`/`En análisis`), el botón "Analizar Solicitudes" aparece deshabilitado.
