# Documentos en el perfil del empleado (solo lectura) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una vista de solo lectura al menú del navbar del empleado donde pueda ver los documentos que RRHH le adjuntó (sin poder subir ni borrar).

**Architecture:** Dos endpoints nuevos en `app/routes/employee.py` (mismo patrón self-or-admin ya usado en `PUT /{employee_id}`), reutilizando las funciones de `app/database/employee_documents.py` ya existentes. En el frontend: nueva entrada en el menú del navbar, nuevo valor de `Page`, nuevo case en el router de `page.tsx`, y una pantalla nueva (`MisDocumentos/Screen.tsx`) que reusa la lógica de blob-URL para ver/imprimir PDFs ya construida en `DocumentsTab`.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL) (backend); Next.js, TypeScript, `apiClient`, Tailwind CSS v4 semantic tokens, lucide-react (frontend).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-employee-documents-self-service-design.md`
- No se modifica `app/database/employee_documents.py` ni la tabla `EmployeeDocument` — se reutilizan `get_documents`/`get_document` tal como están.
- Ambos endpoints nuevos usan el mismo chequeo self-or-admin que `PUT /employee/{employee_id}` (`app/routes/employee.py:603-606`): `current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN` → 403.
- El empleado es estrictamente de solo lectura — no se agregan endpoints de carga ni borrado en este plan.
- No hay test suite automatizado en ninguno de los dos repos — verificación vía `python -c "import ..."`, `npx tsc --noEmit`, y un checklist manual.

---

### Task 1: Endpoints de solo lectura en `employee.py`

**Files:**
- Modify: `app/routes/employee.py` (agregar import + 2 endpoints al final del archivo)

**Interfaces:**
- Consumes: `get_documents`, `get_document` de `app.database.employee_documents` (ya existen, ver `app/database/employee_documents.py`). `get_current_user`, `ROLE_ADMIN` (ya importados en este archivo).
- Produces: `GET /employee/{employee_id}/documents` → `{"documents": [...]}`. `GET /employee/{employee_id}/documents/{document_id}/download` → el documento completo incl. `fileData`, o 404.

- [ ] **Step 1: Agregar el import al inicio del archivo**

Antes (línea 1-6 de `app/routes/employee.py`):
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN, get_current_user
from datetime import datetime
```

Después:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, require_any_auth, ROLE_ADMIN, get_current_user
from datetime import datetime
from app.database.employee_documents import get_documents as get_employee_documents_data, get_document as get_employee_document_data
```

- [ ] **Step 2: Agregar los 2 endpoints al final del archivo**

Agregar al final de `app/routes/employee.py` (después de `delete_academic_record`, el último endpoint existente):

```python
@router.get("/{employee_id}/documents", dependencies=[Depends(require_any_auth)])
def list_my_documents(employee_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Lista los documentos del propio empleado (o cualquiera, si es Admin). Solo lectura."""
    if current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenés permiso para ver estos documentos")
    try:
        return {"documents": get_employee_documents_data(db, employee_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener documentos: {str(e)}")


@router.get("/{employee_id}/documents/{document_id}/download", dependencies=[Depends(require_any_auth)])
def download_my_document(employee_id: int, document_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Devuelve un documento completo (incluyendo fileData) para ver/descargar. Solo lectura."""
    if current_user["employeeId"] != employee_id and current_user["roleId"] != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="No tenés permiso para ver este documento")
    doc = get_employee_document_data(db, employee_id, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc
```

- [ ] **Step 3: Verificar que el servidor levanta sin errores de sintaxis**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.routes.employee"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/employee.py
git commit -m "feat: agregar endpoints de solo lectura para que el empleado vea sus documentos"
```

---

### Task 2: Frontend — menú, ruteo y pantalla `MisDocumentos`

**Files:**
- Modify: `RRHH/src/app/Interfas/Interfaces.ts` (agregar `"documentos"` al type `Page`)
- Modify: `RRHH/src/app/Componentes/Shell/AppHeader.tsx` (agregar el ítem de menú)
- Modify: `RRHH/src/app/page.tsx` (import + case nuevo)
- Create: `RRHH/src/app/screens/MisDocumentos/Screen.tsx`

**Interfaces:**
- Consumes: `GET /employee/{id}/documents`, `GET /employee/{id}/documents/{docId}/download` (Task 1). `apiClient` (`RRHH/src/app/util/apiClient.ts`, ya tiene `get`). `Employee` type (`Interfaces.ts`, ya existe, tiene `.id`).
- Produces: pantalla `MisDocumentos` default-exportada, consumida por `page.tsx`.

- [ ] **Step 1: Agregar `"documentos"` al type `Page`**

Antes (`RRHH/src/app/Interfas/Interfaces.ts`, líneas 671-681):
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
  | "test"
  | "admin";
```

Después:
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

- [ ] **Step 2: Agregar el ítem "Documentos" al menú del navbar**

Antes (`RRHH/src/app/Componentes/Shell/AppHeader.tsx`, líneas 104-109):
```tsx
            <DropdownMenuItem onClick={() => setPage("editar-perfil")}>
              <UserCircle size={16} className="mr-2" /> Editar Perfil
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setPage("licencias")}>
              <FileText size={16} className="mr-2" /> Licencias
            </DropdownMenuItem>
```

Después:
```tsx
            <DropdownMenuItem onClick={() => setPage("editar-perfil")}>
              <UserCircle size={16} className="mr-2" /> Editar Perfil
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setPage("licencias")}>
              <FileText size={16} className="mr-2" /> Licencias
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setPage("documentos")}>
              <Folder size={16} className="mr-2" /> Documentos
            </DropdownMenuItem>
```

Y agregar `Folder` al import de íconos (línea 5):

Antes:
```tsx
import { Bell, Sun, Moon, LogOut, UserCircle, FileText, MessageSquare } from "lucide-react";
```

Después:
```tsx
import { Bell, Sun, Moon, LogOut, UserCircle, FileText, MessageSquare, Folder } from "lucide-react";
```

- [ ] **Step 3: Crear la pantalla `MisDocumentos`**

Archivo completo `RRHH/src/app/screens/MisDocumentos/Screen.tsx`:

```tsx
"use client";

import React, { useEffect, useState } from 'react';
import { Eye, FileText } from 'lucide-react';
import { apiClient } from '@/app/util/apiClient';
import { Employee } from '@/app/Interfas/Interfaces';
import { SectionTitle } from '@/app/util/UiCv';

interface EmployeeDocumentSummary {
  id: number;
  tipo: string;
  descripcion: string | null;
  fileName: string;
  mimeType: string;
  createdAt: string;
}

interface MisDocumentosProps {
  employeeData: Employee | null;
}

const formatDate = (iso: string) => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
};

export default function MisDocumentos({ employeeData }: MisDocumentosProps) {
  const [documents, setDocuments] = useState<EmployeeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeData?.id) return;
    const loadDocuments = async () => {
      setLoading(true);
      try {
        const res = await apiClient.get<{ documents: EmployeeDocumentSummary[] }>(
          `/employee/${employeeData.id}/documents`
        );
        setDocuments(res.documents);
        setError(null);
      } catch (err) {
        console.error('Error al cargar documentos:', err);
        setError('No se pudieron cargar tus documentos.');
      } finally {
        setLoading(false);
      }
    };
    loadDocuments();
  }, [employeeData?.id]);

  const handleViewDocument = async (doc: EmployeeDocumentSummary) => {
    if (!employeeData?.id) return;
    try {
      const full = await apiClient.get<{ fileData: string; mimeType: string }>(
        `/employee/${employeeData.id}/documents/${doc.id}/download`
      );
      // Los navegadores bloquean la navegacion de nivel superior a URLs "data:"
      // (especialmente PDFs). Se decodifica el base64 a un Blob y se abre como
      // URL "blob:", que si se puede navegar/imprimir.
      const byteCharacters = atob(full.fileData);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: full.mimeType });
      const blobUrl = URL.createObjectURL(blob);
      window.open(blobUrl, "_blank");
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
    } catch (err) {
      console.error('Error al abrir documento:', err);
      setError('No se pudo abrir el documento.');
    }
  };

  if (!employeeData) {
    return (
      <div className="bg-background font-sans min-h-screen flex items-center justify-center">
        <p className="text-foreground">Cargando información del empleado...</p>
      </div>
    );
  }

  return (
    <div className="bg-background font-sans min-h-screen">
      <main className="max-w-4xl mx-auto p-4 sm:p-6 lg:p-8">
        <div className="flex justify-between items-start mb-6">
          <SectionTitle icon={FileText} title="Mis Documentos" />
        </div>

        <div className="bg-card p-6 rounded-lg shadow-sm">
          {loading ? (
            <p className="text-muted-foreground text-sm">Cargando documentos...</p>
          ) : error ? (
            <p className="text-error text-sm">{error}</p>
          ) : documents.length === 0 ? (
            <p className="text-muted-foreground text-sm italic">
              Todavía no tenés documentos cargados por RRHH.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-2">Tipo</th>
                  <th className="py-2">Descripción</th>
                  <th className="py-2">Archivo</th>
                  <th className="py-2">Fecha</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id} className="border-b border-border">
                    <td className="py-2 text-foreground">{doc.tipo}</td>
                    <td className="py-2 text-foreground">{doc.descripcion || "—"}</td>
                    <td className="py-2 text-foreground">{doc.fileName}</td>
                    <td className="py-2 text-foreground">{formatDate(doc.createdAt)}</td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => handleViewDocument(doc)}
                        className="inline-flex items-center gap-1 text-primary hover:opacity-80"
                      >
                        <Eye size={16} /> Ver
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Conectar la pantalla en `page.tsx`**

Antes (`RRHH/src/app/page.tsx`, línea 16, imports):
```tsx
import EmployeeCV from '@/app/screens/Cv/Screen';
```

Después:
```tsx
import EmployeeCV from '@/app/screens/Cv/Screen';
import MisDocumentos from '@/app/screens/MisDocumentos/Screen';
```

Antes (`RRHH/src/app/page.tsx`, líneas 135-136):
```tsx
      case 'licencias':
        return <LicenciasManage />;
```

Después:
```tsx
      case 'licencias':
        return <LicenciasManage />;
      case 'documentos':
        return <MisDocumentos employeeData={employeeData} />;
```

- [ ] **Step 5: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "MisDocumentos|page\.tsx|AppHeader|Interfas/Interfaces"`
Expected: ningún resultado (sin errores nuevos en los archivos tocados).

- [ ] **Step 6: Commit**

```bash
git add src/app/Interfas/Interfaces.ts src/app/Componentes/Shell/AppHeader.tsx src/app/page.tsx src/app/screens/MisDocumentos/Screen.tsx
git commit -m "feat: agregar vista de solo lectura Mis Documentos al menu del navbar"
```

---

### Task 3: Verificación manual end-to-end

**Files:** ninguno (solo verificación, no produce commits de código).

**Interfaces:**
- Consumes: el flujo completo de las Tasks 1-2.
- Produces: confirmación de que el comportamiento documentado en la spec se cumple.

- [ ] **Step 1: Levantar ambos servidores**

Backend: `uvicorn app.main:app --reload` (desde `Backend_RRHH`)
Frontend: `npm run dev` (desde `RRHH`)

- [ ] **Step 2: Confirmar visibilidad del documento**

Como RRHH, cargar un documento para un empleado de prueba (ya implementado en una sesión anterior). Loguearse como ese empleado, abrir el menú del navbar (avatar arriba a la derecha) → "Documentos" → confirmar que aparece el documento cargado.

- [ ] **Step 3: Confirmar ver/imprimir**

Tocar "Ver" en el documento. Confirmar que se abre en una pestaña nueva (visor nativo de PDF o imagen) y que se puede imprimir desde ahí.

- [ ] **Step 4: Confirmar que es solo lectura**

Confirmar visualmente que no hay formulario de carga ni botón de eliminar en esta pantalla — a diferencia de la tab "Documentos" del lado de RRHH.

- [ ] **Step 5: Confirmar aislamiento entre empleados**

Como un empleado distinto al dueño del documento, intentar `GET /employee/{otro_id}/documents` (vía `curl` con el token de este segundo empleado) — debe devolver 403.

- [ ] **Step 6: Confirmar acceso de Admin**

Como Admin, confirmar que `GET /employee/{id}/documents` funciona para cualquier `id`, no solo el propio.
