# Mapeo de títulos académicos → profesión Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el diccionario hardcodeado `SPECIAL_TITLE_MAPPINGS` en el frontend por una tabla `AcademicTitleMapping` administrable desde TestConfig, manteniendo el comportamiento actual vía un seed inicial.

**Architecture:** Tabla nueva creada de forma idempotente (`IF NOT EXISTS`, mismo patrón que `app/database/token_blacklist.py`) en un módulo dedicado `app/database/academic_title_mapping.py`. Tres endpoints nuevos en `app/routes/configtest.py` (mismo router que ya expone `/configtest/technical`). El frontend reemplaza el hardcode por un fetch, y TestConfig gana una sub-sección de administración.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server vía pyodbc (backend); Next.js, TypeScript, `apiClient` (frontend).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-academic-title-mapping-design.md`
- La tabla se crea de forma idempotente (`IF NOT EXISTS`) y se invoca **dentro de cada endpoint nuevo**, no desde `app/main.py` — ese archivo tiene cambios sin commitear del usuario (registro de `contracts`/`professions`/`schedules`) que no deben tocarse ni commitearse como parte de este plan.
- Todo INSERT/UPDATE en la tabla nueva setea `createdAt`/`updatedAt` explícitamente con `datetime.utcnow()` — esta base de datos no tiene defaults en esas columnas (confirmado por los `IntegrityError` ya resueltos en el fix de persistencia del CV).
- `GET /configtest/academic-title-mappings` es `require_any_auth` (lo consume cualquier empleado autenticado al ver su CV); `POST`/`DELETE` son `require_admin`.
- No se toca `TechnicalSkill.profession` ni la tabla `Profession` (WIP del usuario en `professions.py`) — son conceptos paralelos, fuera de alcance.
- No hay test suite automatizado en ninguno de los dos repos — verificación manual vía `python -c "import ..."`, `npx tsc --noEmit`, y un checklist end-to-end documentado en la Task 4.

---

### Task 1: Tabla `AcademicTitleMapping` y funciones de acceso a datos

**Files:**
- Create: `app/database/academic_title_mapping.py`

**Interfaces:**
- Consumes: nada (módulo de datos puro).
- Produces: `ensure_table(db: Session) -> None`, `get_active_mappings(db: Session) -> list[dict]` (cada dict: `{"id": int, "tituloAcademico": str, "profession": str}`), `save_mapping(db: Session, titulo_academico: str, profession: str, mapping_id: int | None) -> None`, `delete_mapping(db: Session, mapping_id: int) -> bool` (retorna `False` si no existía, `True` si se borró).

- [ ] **Step 1: Crear el módulo con la tabla y las funciones de acceso**

Archivo completo `app/database/academic_title_mapping.py`:

```python
"""
Mapeo de títulos académicos a nombres de profesión (texto libre,
mismo valor que TechnicalSkill.profession), administrable desde TestConfig.

Reemplaza el diccionario SPECIAL_TITLE_MAPPINGS que antes vivía
hardcodeado en el frontend (HabilidadesTecnicas.tsx).
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'AcademicTitleMapping' AND xtype = 'U'
)
BEGIN
    CREATE TABLE AcademicTitleMapping (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        tituloAcademico NVARCHAR(255)  NOT NULL,
        profession      NVARCHAR(255)  NOT NULL,
        activo          BIT            NOT NULL DEFAULT 1,
        createdAt       DATETIME2      NOT NULL,
        updatedAt       DATETIME2      NOT NULL
    );
    CREATE INDEX IX_AcademicTitleMapping_titulo ON AcademicTitleMapping (tituloAcademico);
END
"""

SEED_ROWS = [
    ("Bachiller", "Administración Pública"),
    ("Bachillerato", "Administración Pública"),
    ("Administración Pública", "Administración Pública"),
]


def ensure_table(db: Session) -> None:
    """Crea la tabla AcademicTitleMapping si no existe, y siembra los
    3 mapeos que antes estaban hardcodeados en el frontend (solo si la
    tabla está vacía, para no duplicar en cada llamada)."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()

    count = db.execute(text("SELECT COUNT(*) AS c FROM AcademicTitleMapping")).mappings().first()
    if count["c"] == 0:
        now = datetime.utcnow()
        for titulo, profession in SEED_ROWS:
            db.execute(text("""
                INSERT INTO AcademicTitleMapping (tituloAcademico, profession, activo, createdAt, updatedAt)
                VALUES (:titulo, :profession, 1, :createdAt, :updatedAt)
            """), {"titulo": titulo, "profession": profession, "createdAt": now, "updatedAt": now})
        db.commit()


def get_active_mappings(db: Session) -> list[dict]:
    rows = db.execute(text("""
        SELECT id, tituloAcademico, profession
        FROM AcademicTitleMapping
        WHERE activo = 1
    """)).mappings().all()
    return [dict(r) for r in rows]


def save_mapping(db: Session, titulo_academico: str, profession: str, mapping_id: int | None) -> None:
    now = datetime.utcnow()
    if mapping_id:
        db.execute(text("""
            UPDATE AcademicTitleMapping
            SET tituloAcademico = :titulo, profession = :profession, activo = 1, updatedAt = :updatedAt
            WHERE id = :id
        """), {"titulo": titulo_academico, "profession": profession, "updatedAt": now, "id": mapping_id})
    else:
        existing = db.execute(text("""
            SELECT id FROM AcademicTitleMapping WHERE tituloAcademico = :titulo
        """), {"titulo": titulo_academico}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE AcademicTitleMapping
                SET profession = :profession, activo = 1, updatedAt = :updatedAt
                WHERE tituloAcademico = :titulo
            """), {"profession": profession, "updatedAt": now, "titulo": titulo_academico})
        else:
            db.execute(text("""
                INSERT INTO AcademicTitleMapping (tituloAcademico, profession, activo, createdAt, updatedAt)
                VALUES (:titulo, :profession, 1, :createdAt, :updatedAt)
            """), {"titulo": titulo_academico, "profession": profession, "createdAt": now, "updatedAt": now})
    db.commit()


def delete_mapping(db: Session, mapping_id: int) -> bool:
    existing = db.execute(text("SELECT id FROM AcademicTitleMapping WHERE id = :id"), {"id": mapping_id}).fetchone()
    if not existing:
        return False
    db.execute(text("UPDATE AcademicTitleMapping SET activo = 0, updatedAt = :updatedAt WHERE id = :id"),
               {"updatedAt": datetime.utcnow(), "id": mapping_id})
    db.commit()
    return True
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.database.academic_title_mapping"`
Expected: sin `ImportError`/`SyntaxError` (puede imprimir el log de conexión a la base, eso es normal en este proyecto).

- [ ] **Step 3: Commit**

```bash
git add app/database/academic_title_mapping.py
git commit -m "feat: agregar tabla AcademicTitleMapping y funciones de acceso a datos"
```

---

### Task 2: Endpoints en `configtest.py`

**Files:**
- Modify: `app/routes/configtest.py` (agregar al final del archivo, después del último endpoint existente)

**Interfaces:**
- Consumes: `ensure_table`, `get_active_mappings`, `save_mapping`, `delete_mapping` de `app.database.academic_title_mapping` (Task 1).
- Produces: `GET /configtest/academic-title-mappings` → `{"mappings": [{"id": int, "tituloAcademico": str, "profession": str}, ...]}`. `POST /configtest/academic-title-mappings` body `{"id"?: int, "tituloAcademico": str, "profession": str}` → `{"success": true}`. `DELETE /configtest/academic-title-mappings/{mapping_id}` → `{"success": true}` o 404.

- [ ] **Step 1: Agregar el import al inicio del archivo**

Antes (línea 1-6 de `app/routes/configtest.py`):
```python
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth
import json
```

Después:
```python
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import SessionLocal
from app.auth_middleware import require_admin, require_any_auth
from app.database.academic_title_mapping import (
    ensure_table as ensure_academic_title_mapping_table,
    get_active_mappings,
    save_mapping,
    delete_mapping,
)
import json
```

- [ ] **Step 2: Agregar los 3 endpoints al final del archivo**

Agregar al final de `app/routes/configtest.py` (después del último `@router...` existente):

```python
@router.get("/academic-title-mappings", dependencies=[Depends(require_any_auth)])
def get_academic_title_mappings(db: Session = Depends(get_db)):
    """Lista los mapeos titulo academico -> profesion activos."""
    ensure_academic_title_mapping_table(db)
    try:
        return {"mappings": get_active_mappings(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener mapeos: {str(e)}")


@router.post("/academic-title-mappings", dependencies=[Depends(require_admin)])
def save_academic_title_mapping(data: dict = Body(...), db: Session = Depends(get_db)):
    """Crea o actualiza un mapeo titulo academico -> profesion."""
    ensure_academic_title_mapping_table(db)
    titulo = data.get("tituloAcademico")
    profession = data.get("profession")
    mapping_id = data.get("id")

    if not titulo or not profession:
        raise HTTPException(status_code=400, detail="tituloAcademico y profession son requeridos")

    try:
        save_mapping(db, titulo, profession, mapping_id)
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar mapeo: {str(e)}")


@router.delete("/academic-title-mappings/{mapping_id}", dependencies=[Depends(require_admin)])
def delete_academic_title_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """Soft delete de un mapeo titulo academico -> profesion."""
    ensure_academic_title_mapping_table(db)
    try:
        deleted = delete_mapping(db, mapping_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Mapeo no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar mapeo: {str(e)}")
```

- [ ] **Step 3: Verificar que el servidor levanta sin errores de sintaxis**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.routes.configtest"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/configtest.py
git commit -m "feat: agregar endpoints CRUD para AcademicTitleMapping en /configtest"
```

---

### Task 3: Frontend — reemplazar el hardcode y agregar administración en TestConfig

**Files:**
- Modify: `RRHH/src/app/Interfas/Interfaces.ts` (agregar interfaz nueva)
- Modify: `RRHH/src/app/Componentes/CvComponente/HabilidadesTecnicas.tsx` (eliminar hardcode, agregar fetch)
- Modify: `RRHH/src/app/screens/TestConfig/Screen.tsx` (agregar sub-sección de administración)

**Interfaces:**
- Consumes: `GET /configtest/academic-title-mappings`, `POST /configtest/academic-title-mappings`, `DELETE /configtest/academic-title-mappings/{id}` (Task 2). `apiClient.get/post/delete` ya existen en `RRHH/src/app/util/apiClient.ts`.
- Produces: interfaz TypeScript `AcademicTitleMapping` exportada desde `Interfaces.ts`, usada por ambos componentes modificados.

- [ ] **Step 1: Agregar la interfaz `AcademicTitleMapping`**

En `RRHH/src/app/Interfas/Interfaces.ts`, agregar justo después de la interfaz `SoftSkill` (línea 231, antes de la línea en blanco que sigue):

```typescript
export interface AcademicTitleMapping {
  id: number;
  tituloAcademico: string;
  profession: string;
}
```

- [ ] **Step 2: Reemplazar `SPECIAL_TITLE_MAPPINGS` por un fetch en `HabilidadesTecnicas.tsx`**

Antes (líneas 1-44 de `RRHH/src/app/Componentes/CvComponente/HabilidadesTecnicas.tsx`):
```tsx
import React, { useState, useEffect } from 'react';
import { Accordion, AccordionTab } from 'primereact/accordion';
import { Message } from 'primereact/message';
import { SkillCard } from '@/app/util/UiRRHH';
import { TechnicalSkill, SkillStatus, Skill, AcademicFormation, EmployeeTechnicalSkill } from "@/app/Interfas/Interfaces"
import { SkillTestDialog} from './SkillTest';
import TestModal from '@/app/Componentes/Validaciones/TestModal';

// Props del componente HabilidadesTecnicas
export type HabilidadesTecnicasProps = {
  data: EmployeeTechnicalSkill[];
  skillStatus: SkillStatus[];
  academicFormation: AcademicFormation[];
  updateData: (technicalSkills: EmployeeTechnicalSkill[], skillStatus: SkillStatus[]) => void;
  isEditing: boolean;
  position: string;
  employeeId: number;
};

export default function HabilidadesTecnicas({ 
    data, 
    skillStatus, 
    academicFormation = [],
    updateData, 
    isEditing, 
    position,
    employeeId 
}: HabilidadesTecnicasProps) {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [dbSkills, setDbSkills] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isTestModalVisible, setIsTestModalVisible] = useState(false);
    const [selectedSkillForTest, setSelectedSkillForTest] = useState<Skill | null>(null);
    
    // Estado para el TestModal (validacion con IA via API)
    const [testModalVisible, setTestModalVisible] = useState(false);
    const [selectedSkillForAITest, setSelectedSkillForAITest] = useState<{ id: number; nombre: string } | null>(null);

    // Mapeo especial para títulos específicos
    const SPECIAL_TITLE_MAPPINGS: Record<string, string> = {
        "Bachiller": "Administración Pública",
        "Bachillerato": "Administración Pública",
        "Administración Pública": "Administración Pública",
    };

    // 1. Cargar habilidades disponibles desde la DB
    const fetchDbSkills = async () => {
        if (!employeeId) return;
        try {
            setLoading(true);
            const token = localStorage.getItem('token');
            const response = await fetch(`http://127.0.0.1:8000/tests/skills/${employeeId}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const resData = await response.json();
            if (resData.skills) {
                setDbSkills(resData.skills);
            }
        } catch (error) {
            console.error("Error cargando habilidades de la DB:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchDbSkills();
    }, [employeeId]);
```

Después:
```tsx
import React, { useState, useEffect } from 'react';
import { Accordion, AccordionTab } from 'primereact/accordion';
import { Message } from 'primereact/message';
import { SkillCard } from '@/app/util/UiRRHH';
import { TechnicalSkill, SkillStatus, Skill, AcademicFormation, EmployeeTechnicalSkill, AcademicTitleMapping } from "@/app/Interfas/Interfaces"
import { SkillTestDialog} from './SkillTest';
import TestModal from '@/app/Componentes/Validaciones/TestModal';
import { apiClient } from '@/app/util/apiClient';

// Props del componente HabilidadesTecnicas
export type HabilidadesTecnicasProps = {
  data: EmployeeTechnicalSkill[];
  skillStatus: SkillStatus[];
  academicFormation: AcademicFormation[];
  updateData: (technicalSkills: EmployeeTechnicalSkill[], skillStatus: SkillStatus[]) => void;
  isEditing: boolean;
  position: string;
  employeeId: number;
};

export default function HabilidadesTecnicas({ 
    data, 
    skillStatus, 
    academicFormation = [],
    updateData, 
    isEditing, 
    position,
    employeeId 
}: HabilidadesTecnicasProps) {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [dbSkills, setDbSkills] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isTestModalVisible, setIsTestModalVisible] = useState(false);
    const [selectedSkillForTest, setSelectedSkillForTest] = useState<Skill | null>(null);
    
    // Estado para el TestModal (validacion con IA via API)
    const [testModalVisible, setTestModalVisible] = useState(false);
    const [selectedSkillForAITest, setSelectedSkillForAITest] = useState<{ id: number; nombre: string } | null>(null);

    // Mapeo titulo academico -> profesion, cargado desde /configtest/academic-title-mappings
    const [titleMappings, setTitleMappings] = useState<Record<string, string>>({});

    // 1. Cargar habilidades disponibles desde la DB
    const fetchDbSkills = async () => {
        if (!employeeId) return;
        try {
            setLoading(true);
            const token = localStorage.getItem('token');
            const response = await fetch(`http://127.0.0.1:8000/tests/skills/${employeeId}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            const resData = await response.json();
            if (resData.skills) {
                setDbSkills(resData.skills);
            }
        } catch (error) {
            console.error("Error cargando habilidades de la DB:", error);
        } finally {
            setLoading(false);
        }
    };

    // 1b. Cargar el mapeo titulo academico -> profesion
    const fetchTitleMappings = async () => {
        try {
            const res = await apiClient.get<{ mappings: AcademicTitleMapping[] }>('/configtest/academic-title-mappings');
            const map: Record<string, string> = {};
            res.mappings.forEach(m => { map[m.tituloAcademico] = m.profession; });
            setTitleMappings(map);
        } catch (error) {
            console.error("Error cargando mapeo de titulos academicos:", error);
        }
    };

    useEffect(() => {
        fetchDbSkills();
        fetchTitleMappings();
    }, [employeeId]);
```

- [ ] **Step 3: Reemplazar la referencia a `SPECIAL_TITLE_MAPPINGS` por `titleMappings`**

Antes (dentro del `useEffect` de cálculo de habilidades relevantes, en el bloque `academicFormation.forEach`):
```tsx
        academicFormation.forEach(record => {
            if (record.title) {
                // Aplicar mapeo especial si existe, sino usar el título original
                const mappedTitle = SPECIAL_TITLE_MAPPINGS[record.title.trim()] || record.title.trim();
                titlesToMap.add(mappedTitle);
            }
        });
```

Después:
```tsx
        academicFormation.forEach(record => {
            if (record.title) {
                // Aplicar mapeo configurado (TestConfig) si existe, sino usar el título original
                const mappedTitle = titleMappings[record.title.trim()] || record.title.trim();
                titlesToMap.add(mappedTitle);
            }
        });
```

Y agregar `titleMappings` a las dependencias del `useEffect` que contiene este bloque (busca el `useEffect` cuyo arreglo de dependencias es `[position, academicFormation, dbSkills, data, loading]` y reemplázalo por `[position, academicFormation, dbSkills, data, loading, titleMappings]`).

- [ ] **Step 4: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit`
Expected: mismos 2 errores preexistentes documentados en el último report de retheme de `ConfiguracionLicencias` (no relacionados a este archivo: `Screen.tsx(281,30)` y `(284,62)` sobre `SoftSkill`), ningún error nuevo en `HabilidadesTecnicas.tsx` ni `Interfaces.ts`.

- [ ] **Step 5: Agregar la sub-sección de administración en `TestConfig/Screen.tsx`**

Antes (líneas 1-42 de `RRHH/src/app/screens/TestConfig/Screen.tsx`):
```tsx
"use client"
import React, { useState, useEffect } from 'react';
import { TechnicalTests } from '@/app/Componentes/TestComponent/TechnicalTests';
import { Test, TestsByProfession, SoftSkill } from "@/app/Interfas/Interfaces";
import { apiClient } from '@/app/util/apiClient';

type ActiveTab = "technical";

export default function TestPage(){
  // Tab State
  const [activeTab, setActiveTab] = useState<ActiveTab>("technical");

  // Loading State
  const [loading, setLoading] = useState<boolean>(true);

  // Technical Tests State
  const [testsByProfession, setTestsByProfession] = useState<TestsByProfession>({});
  const [professions, setProfessions] = useState<{ [key: string]: number[] }>({});
  const [selectedProfession, setSelectedProfession] = useState<string>("Abogado");

  // Soft Skills State
  const [softSkills, setSoftSkills] = useState<SoftSkill[]>([]);

  // Fetch data on mount
  useEffect(() => {
    Promise.all([
      apiClient.get<{ professions: { [key: string]: number[] }, testsByProfession: TestsByProfession }>("/configtest/technical"),
      apiClient.get<SoftSkill[]>("/configtest/soft")
    ]).then(([techData, softData]) => {
      setProfessions(techData.professions);
      setTestsByProfession(techData.testsByProfession);
      const keys = Object.keys(techData.professions);
      if (keys.length > 0) {
        setSelectedProfession(keys[0]);
      }
      setSoftSkills(softData);
      setLoading(false);
    }).catch(err => {
      console.error("Error fetching test configuration:", err);
      setLoading(false);
    });
  }, []);
```

Después:
```tsx
"use client"
import React, { useState, useEffect } from 'react';
import { TechnicalTests } from '@/app/Componentes/TestComponent/TechnicalTests';
import { Test, TestsByProfession, SoftSkill, AcademicTitleMapping } from "@/app/Interfas/Interfaces";
import { apiClient } from '@/app/util/apiClient';

type ActiveTab = "technical";

export default function TestPage(){
  // Tab State
  const [activeTab, setActiveTab] = useState<ActiveTab>("technical");

  // Loading State
  const [loading, setLoading] = useState<boolean>(true);

  // Technical Tests State
  const [testsByProfession, setTestsByProfession] = useState<TestsByProfession>({});
  const [professions, setProfessions] = useState<{ [key: string]: number[] }>({});
  const [selectedProfession, setSelectedProfession] = useState<string>("Abogado");

  // Soft Skills State
  const [softSkills, setSoftSkills] = useState<SoftSkill[]>([]);

  // Academic Title Mappings State
  const [titleMappings, setTitleMappings] = useState<AcademicTitleMapping[]>([]);
  const [newTitulo, setNewTitulo] = useState("");
  const [newProfession, setNewProfession] = useState("");

  // Fetch data on mount
  useEffect(() => {
    Promise.all([
      apiClient.get<{ professions: { [key: string]: number[] }, testsByProfession: TestsByProfession }>("/configtest/technical"),
      apiClient.get<SoftSkill[]>("/configtest/soft"),
      apiClient.get<{ mappings: AcademicTitleMapping[] }>("/configtest/academic-title-mappings")
    ]).then(([techData, softData, mappingsData]) => {
      setProfessions(techData.professions);
      setTestsByProfession(techData.testsByProfession);
      const keys = Object.keys(techData.professions);
      if (keys.length > 0) {
        setSelectedProfession(keys[0]);
      }
      setSoftSkills(softData);
      setTitleMappings(mappingsData.mappings);
      setLoading(false);
    }).catch(err => {
      console.error("Error fetching test configuration:", err);
      setLoading(false);
    });
  }, []);

  // Academic Title Mapping Handlers
  const handleAddTitleMapping = () => {
    if (!newTitulo.trim() || !newProfession.trim()) return;
    apiClient.post<{ success: boolean }>("/configtest/academic-title-mappings", {
      tituloAcademico: newTitulo.trim(),
      profession: newProfession.trim(),
    }).then(() => {
      return apiClient.get<{ mappings: AcademicTitleMapping[] }>("/configtest/academic-title-mappings");
    }).then(res => {
      setTitleMappings(res.mappings);
      setNewTitulo("");
      setNewProfession("");
    }).catch(err => {
      console.error("Error al guardar mapeo:", err);
      alert("Error al guardar el mapeo: " + err.message);
    });
  };

  const handleDeleteTitleMapping = (id: number) => {
    apiClient.delete(`/configtest/academic-title-mappings/${id}`)
      .then(() => {
        setTitleMappings(prev => prev.filter(m => m.id !== id));
      })
      .catch(err => {
        console.error("Error al eliminar mapeo:", err);
        alert("Error al eliminar el mapeo: " + err.message);
      });
  };
```

- [ ] **Step 6: Renderizar la sub-sección de administración**

Antes (líneas 135-149 de `RRHH/src/app/screens/TestConfig/Screen.tsx`, el bloque "Tab Content"):
```tsx
        {/* Tab Content */}
        <div className="p-6">
          {activeTab === "technical" && (
            <TechnicalTests
              testsByProfession={testsByProfession}
              professions={professions}
              selectedProfession={selectedProfession}
              onSelectedProfessionChange={handleSelectedProfessionChange}
              onAddProfession={handleAddProfession}
              onSaveTest={handleSaveTest}
              onDeleteTest={handleDeleteTest}
            />
          )}
        </div>
```

Después:
```tsx
        {/* Tab Content */}
        <div className="p-6">
          {activeTab === "technical" && (
            <TechnicalTests
              testsByProfession={testsByProfession}
              professions={professions}
              selectedProfession={selectedProfession}
              onSelectedProfessionChange={handleSelectedProfessionChange}
              onAddProfession={handleAddProfession}
              onSaveTest={handleSaveTest}
              onDeleteTest={handleDeleteTest}
            />
          )}
        </div>

        {/* Academic Title Mappings */}
        <div className="bg-card rounded-lg p-6 shadow-sm mb-8">
          <h2 className="font-heading text-xl font-semibold text-foreground mb-2">
            Alias de títulos académicos
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Define qué profesión corresponde a un título académico cuando el nombre no coincide literalmente (ej. "Bachiller" → "Administración Pública").
          </p>

          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <input
              type="text"
              placeholder="Título académico (ej. Bachiller)"
              value={newTitulo}
              onChange={(e) => setNewTitulo(e.target.value)}
              className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground"
            />
            <input
              type="text"
              placeholder="Profesión (ej. Administración Pública)"
              value={newProfession}
              onChange={(e) => setNewProfession(e.target.value)}
              className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground"
            />
            <button
              onClick={handleAddTitleMapping}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground hover:opacity-90 font-semibold"
            >
              Agregar
            </button>
          </div>

          {titleMappings.length === 0 ? (
            <p className="text-muted-foreground italic">No hay mapeos configurados.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-2">Título académico</th>
                  <th className="py-2">Profesión</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {titleMappings.map(m => (
                  <tr key={m.id} className="border-b border-border">
                    <td className="py-2 text-foreground">{m.tituloAcademico}</td>
                    <td className="py-2 text-foreground">{m.profession}</td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => handleDeleteTitleMapping(m.id)}
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
```

- [ ] **Step 7: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit`
Expected: mismos 2 errores preexistentes (no relacionados, ver Step 4), ningún error nuevo en `TestConfig/Screen.tsx`.

- [ ] **Step 8: Commit**

```bash
git add src/app/Interfas/Interfaces.ts src/app/Componentes/CvComponente/HabilidadesTecnicas.tsx src/app/screens/TestConfig/Screen.tsx
git commit -m "feat: reemplazar hardcode de titulos academicos por mapeo configurable desde TestConfig"
```

---

### Task 4: Verificación manual end-to-end

**Files:** ninguno (solo verificación, no produce commits de código).

**Interfaces:**
- Consumes: el flujo completo de las Tasks 1-3.
- Produces: confirmación de que el comportamiento documentado en la spec se cumple.

- [ ] **Step 1: Levantar ambos servidores**

Backend: `uvicorn app.main:app --reload` (desde `Backend_RRHH`)
Frontend: `npm run dev` (desde `RRHH`)

- [ ] **Step 2: Confirmar que el seed se aplicó**

Como cualquier usuario autenticado, hacer `GET http://127.0.0.1:8000/configtest/academic-title-mappings` (o entrar a TestConfig como admin). Confirmar que aparecen los 3 mapeos: `Bachiller`, `Bachillerato`, `Administración Pública` → `Administración Pública`.

- [ ] **Step 3: Confirmar que el caso original sigue funcionando**

Como empleado con título académico "Bachiller" (o "Bachillerato"), abrir su CV → sección "Habilidades Técnicas". Confirmar que ve los tests de la profesión "Administración Pública", igual que antes del cambio.

- [ ] **Step 4: Agregar un mapeo nuevo desde TestConfig**

Como admin, en TestConfig → "Alias de títulos académicos", agregar un mapeo (ej. "Técnico Superior" → cualquier profesión que ya tenga tests configurados en `TechnicalTests`). Confirmar que aparece en la tabla.

- [ ] **Step 5: Confirmar que el mapeo nuevo se aplica**

Como empleado con ese título académico nuevo, abrir su CV → "Habilidades Técnicas". Confirmar que ahora ve los tests de la profesión mapeada.

- [ ] **Step 6: Eliminar el mapeo de prueba**

Desde TestConfig, eliminar el mapeo agregado en el Step 4. Confirmar que desaparece de la tabla y que, al recargar el CV del empleado de prueba, vuelve a buscar por el título literal (sin traducir).

- [ ] **Step 7: Confirmar permisos**

Como empleado no-admin, intentar `POST /configtest/academic-title-mappings` (vía `curl` o similar) — debe devolver 403. `GET` debe funcionar para cualquier usuario autenticado.
