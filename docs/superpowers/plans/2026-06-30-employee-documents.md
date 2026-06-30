# Adjuntar Documentación (módulo RRHH) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una pestaña "Documentos" al detalle de empleado del módulo RRHH donde se puedan cargar, listar, ver/descargar y eliminar documentos (PDF/imágenes) con tipo y descripción.

**Architecture:** Tabla `EmployeeDocument` creada de forma idempotente (mismo patrón que `app/database/academic_title_mapping.py`), 4 endpoints nuevos en el router existente `app/routes/rrhh.py`, y un componente `DocumentsTab` nuevo en `DetailTables.tsx` (mismo archivo/patrón que `ProfileTab`/`LicenseHistoryTab`), agregado como tab nueva en `Perfildetail.tsx`. Los archivos se convierten a base64 en el navegador (mismo patrón que `ProfilePictureUploader`) — no hay infraestructura de almacenamiento nueva.

**Tech Stack:** FastAPI, SQLAlchemy (`text()` raw SQL), SQL Server vía pyodbc (backend); Next.js, TypeScript, PrimeReact, `apiClient` (frontend).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-30-employee-documents-design.md`
- La tabla se crea de forma idempotente (`IF NOT EXISTS`) y se invoca **dentro de cada endpoint nuevo** — no se toca `app/main.py` (tiene cambios sin commitear del usuario que no deben tocarse).
- Todos los endpoints nuevos usan `dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))]`, igual que el resto de `app/routes/rrhh.py`.
- `GET /rrhh/employee/{employee_id}/documents` (lista) NUNCA incluye `fileData` en la respuesta — solo el endpoint de `/download` lo devuelve. Esto evita cargar blobs base64 pesados en la vista de lista.
- El archivo se convierte a base64 en el frontend (`FileReader.readAsDataURL`, igual que `ProfilePictureUploader` en `RRHH/src/app/util/UiRRHH.tsx`) — no se manda como `multipart/form-data`.
- No hay test suite automatizado en ninguno de los dos repos — verificación vía `python -c "import ..."`, `npx tsc --noEmit`, y un checklist manual.

---

### Task 1: Tabla `EmployeeDocument` y funciones de acceso a datos

**Files:**
- Create: `app/database/employee_documents.py`

**Interfaces:**
- Consumes: nada (módulo de datos puro).
- Produces: `ensure_table(db: Session) -> None`, `get_documents(db: Session, employee_id: int) -> list[dict]` (cada dict: `{"id", "tipo", "descripcion", "fileName", "mimeType", "createdAt"}`, sin `fileData`), `get_document(db: Session, employee_id: int, document_id: int) -> dict | None` (incluye `fileData`), `save_document(db: Session, employee_id: int, tipo: str, descripcion: str | None, file_name: str, mime_type: str, file_data: str) -> int` (retorna el `id` insertado), `delete_document(db: Session, employee_id: int, document_id: int) -> bool`.

- [ ] **Step 1: Crear el módulo con la tabla y las funciones de acceso**

Archivo completo `app/database/employee_documents.py`:

```python
"""
Documentos adjuntos del legajo de un empleado (DNI, resoluciones,
certificados, etc.), cargados desde la pestaña "Documentos" del
modulo RRHH. El archivo se guarda como base64 en la columna fileData
-- mismo patron que ya usa Employee.photo (ProfilePictureUploader en
el frontend), sin infraestructura de almacenamiento nueva.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects
    WHERE name = 'EmployeeDocument' AND xtype = 'U'
)
BEGIN
    CREATE TABLE EmployeeDocument (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        employeeId  INT            NOT NULL,
        tipo        NVARCHAR(100)  NOT NULL,
        descripcion NVARCHAR(500)  NULL,
        fileName    NVARCHAR(255)  NOT NULL,
        mimeType    NVARCHAR(100)  NOT NULL,
        fileData    NVARCHAR(MAX)  NOT NULL,
        activo      BIT            NOT NULL DEFAULT 1,
        createdAt   DATETIME2      NOT NULL
    );
    CREATE INDEX IX_EmployeeDocument_employeeId ON EmployeeDocument (employeeId);
END
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla EmployeeDocument si no existe."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def get_documents(db: Session, employee_id: int) -> list[dict]:
    """Lista documentos activos de un empleado, SIN fileData (liviano)."""
    rows = db.execute(text("""
        SELECT id, tipo, descripcion, fileName, mimeType, createdAt
        FROM EmployeeDocument
        WHERE employeeId = :employeeId AND activo = 1
        ORDER BY createdAt DESC
    """), {"employeeId": employee_id}).mappings().all()
    return [dict(r) for r in rows]


def get_document(db: Session, employee_id: int, document_id: int) -> dict | None:
    """Devuelve un documento completo (incluye fileData) para descarga."""
    row = db.execute(text("""
        SELECT id, tipo, descripcion, fileName, mimeType, fileData, createdAt
        FROM EmployeeDocument
        WHERE id = :id AND employeeId = :employeeId AND activo = 1
    """), {"id": document_id, "employeeId": employee_id}).mappings().first()
    return dict(row) if row else None


def save_document(db: Session, employee_id: int, tipo: str, descripcion: str | None,
                   file_name: str, mime_type: str, file_data: str) -> int:
    """Inserta un nuevo documento y retorna su id."""
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO EmployeeDocument (employeeId, tipo, descripcion, fileName, mimeType, fileData, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:employeeId, :tipo, :descripcion, :fileName, :mimeType, :fileData, 1, :createdAt)
    """), {
        "employeeId": employee_id,
        "tipo": tipo,
        "descripcion": descripcion,
        "fileName": file_name,
        "mimeType": mime_type,
        "fileData": file_data,
        "createdAt": now,
    })
    new_id = result.scalar()
    db.commit()
    return new_id


def delete_document(db: Session, employee_id: int, document_id: int) -> bool:
    """Soft delete de un documento. Retorna False si no existia."""
    existing = db.execute(text("""
        SELECT id FROM EmployeeDocument WHERE id = :id AND employeeId = :employeeId
    """), {"id": document_id, "employeeId": employee_id}).fetchone()
    if not existing:
        return False
    db.execute(text("""
        UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
    """), {"id": document_id})
    db.commit()
    return True
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.database.employee_documents"`
Expected: sin `ImportError`/`SyntaxError` (puede imprimir el log de conexión a la base, eso es normal en este proyecto).

- [ ] **Step 3: Commit**

```bash
git add app/database/employee_documents.py
git commit -m "feat: agregar tabla EmployeeDocument y funciones de acceso a datos"
```

---

### Task 2: Endpoints en `rrhh.py`

**Files:**
- Modify: `app/routes/rrhh.py` (agregar al final del archivo, después del último endpoint existente)

**Interfaces:**
- Consumes: `ensure_table`, `get_documents`, `get_document`, `save_document`, `delete_document` de `app.database.employee_documents` (Task 1).
- Produces: `GET /rrhh/employee/{employee_id}/documents` → `{"documents": [...]}`. `POST /rrhh/employee/{employee_id}/documents` → `{"success": true, "id": int}`. `GET /rrhh/employee/{employee_id}/documents/{document_id}/download` → el documento completo incl. `fileData`, o 404. `DELETE /rrhh/employee/{employee_id}/documents/{document_id}` → `{"success": true}` o 404.

- [ ] **Step 1: Agregar el import al inicio del archivo**

Antes (línea 12-18 de `app/routes/rrhh.py`):
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN, ROLE_USER
from datetime import datetime
from collections import defaultdict
```

Después:
```python
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import SessionLocal
from app.auth_middleware import require_roles, ROLE_ADMIN, ROLE_USER
from datetime import datetime
from collections import defaultdict
from app.database.employee_documents import (
    ensure_table as ensure_employee_document_table,
    get_documents as get_employee_documents,
    get_document as get_employee_document,
    save_document as save_employee_document,
    delete_document as delete_employee_document,
)
```

- [ ] **Step 2: Agregar los 4 endpoints al final del archivo**

Agregar al final de `app/routes/rrhh.py` (después del último `@router...` existente, el de `/org-analysis-data`):

```python
# ---------------------------------------------------------------------------
# Documentos adjuntos del legajo de un empleado
# ---------------------------------------------------------------------------
@router.get("/employee/{employee_id}/documents", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def list_employee_documents(employee_id: int, db: Session = Depends(get_db)):
    """Lista los documentos activos de un empleado (sin fileData)."""
    ensure_employee_document_table(db)
    try:
        return {"documents": get_employee_documents(db, employee_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener documentos: {str(e)}")


@router.post("/employee/{employee_id}/documents", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def upload_employee_document(employee_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    """Carga un nuevo documento para el empleado."""
    ensure_employee_document_table(db)
    tipo = data.get("tipo")
    file_name = data.get("fileName")
    mime_type = data.get("mimeType")
    file_data = data.get("fileData")
    descripcion = data.get("descripcion")

    if not tipo or not file_name or not mime_type or not file_data:
        raise HTTPException(status_code=400, detail="tipo, fileName, mimeType y fileData son requeridos")

    try:
        new_id = save_employee_document(db, employee_id, tipo, descripcion, file_name, mime_type, file_data)
        return {"success": True, "id": new_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar documento: {str(e)}")


@router.get("/employee/{employee_id}/documents/{document_id}/download", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def download_employee_document(employee_id: int, document_id: int, db: Session = Depends(get_db)):
    """Devuelve un documento completo (incluyendo fileData) para ver/descargar."""
    ensure_employee_document_table(db)
    doc = get_employee_document(db, employee_id, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.delete("/employee/{employee_id}/documents/{document_id}", dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def delete_employee_document_endpoint(employee_id: int, document_id: int, db: Session = Depends(get_db)):
    """Soft delete de un documento del empleado."""
    ensure_employee_document_table(db)
    try:
        deleted = delete_employee_document(db, employee_id, document_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar documento: {str(e)}")
```

- [ ] **Step 3: Verificar que el servidor levanta sin errores de sintaxis**

Run: `PYTHONIOENCODING=utf-8 python -c "import app.routes.rrhh"`
Expected: sin `ImportError`/`SyntaxError`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/rrhh.py
git commit -m "feat: agregar endpoints CRUD de documentos adjuntos en /rrhh"
```

---

### Task 3: Frontend — `DocumentsTab` y wiring en `Perfildetail.tsx`

**Files:**
- Modify: `RRHH/src/app/Componentes/TablaOperador/DetailTables.tsx` (agregar el componente `DocumentsTab` al final del archivo)
- Modify: `RRHH/src/app/Componentes/TablaOperador/Perfildetail.tsx` (importar y agregar la tab nueva)

**Interfaces:**
- Consumes: `GET /rrhh/employee/{id}/documents`, `POST /rrhh/employee/{id}/documents`, `GET /rrhh/employee/{id}/documents/{docId}/download`, `DELETE /rrhh/employee/{id}/documents/{docId}` (Task 2). `apiClient` (`RRHH/src/app/util/apiClient.ts`, ya tiene `get`/`post`/`delete`).
- Produces: `DocumentsTab` exportado desde `DetailTables.tsx`, consumido por `Perfildetail.tsx`.

- [ ] **Step 1: Agregar `useEffect` al import de React existente**

`DetailTables.tsx` no importa `useEffect` hoy (el nuevo componente lo necesita para cargar la lista al montar).

Antes (línea 5 de `RRHH/src/app/Componentes/TablaOperador/DetailTables.tsx`):
```tsx
import { useMemo, useState } from "react";
```

Después:
```tsx
import { useMemo, useState, useEffect } from "react";
```

- [ ] **Step 2: Agregar el componente `DocumentsTab` al final de `DetailTables.tsx`**

Agregar al final de `RRHH/src/app/Componentes/TablaOperador/DetailTables.tsx`:

```tsx
// ---------------------------------------------------------------------------
// Tab: Documentos adjuntos del legajo
// ---------------------------------------------------------------------------

interface EmployeeDocumentSummary {
  id: number;
  tipo: string;
  descripcion: string | null;
  fileName: string;
  mimeType: string;
  createdAt: string;
}

const DOCUMENT_TYPES = [
  "DNI",
  "CUIL",
  "Resolución",
  "Título Académico",
  "Certificado Médico",
  "Certificado de Antecedentes Penales",
  "Constancia de CBU",
  "Constancia de AFIP",
  "Curriculum Vitae",
  "Contrato de Trabajo",
  "Recibo de Sueldo",
  "Apto Psicofísico",
  "Carnet de Obra Social",
  "Licencia de Conducir",
  "Foto Carnet",
  "Declaración Jurada",
  "Certificado de Estudios",
  "Comprobante de Domicilio",
  "Acta de Matrimonio",
  "Otro",
];

export const DocumentsTab = ({ employee }: { employee: Employee }) => {
  const [documents, setDocuments] = useState<EmployeeDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [tipo, setTipo] = useState<string | null>(null);
  const [descripcion, setDescripcion] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const toast = useRef<Toast>(null);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const res = await apiClient.get<{ documents: EmployeeDocumentSummary[] }>(
        `/rrhh/employee/${employee.id}/documents`
      );
      setDocuments(res.documents);
    } catch (error) {
      console.error("Error al cargar documentos:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee.id]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSelectedFile(e.target.files?.[0] || null);
  };

  const handleUpload = async () => {
    if (!tipo || !selectedFile) {
      toast.current?.show({
        severity: "warn",
        summary: "Campos incompletos",
        detail: "Seleccioná un tipo de documento y un archivo.",
        life: 3000,
      });
      return;
    }

    setIsUploading(true);
    try {
      const fileData = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          if (typeof reader.result === "string") {
            // readAsDataURL produce "data:<mime>;base64,<data>" -- nos quedamos solo con el base64
            resolve(reader.result.split(",")[1] || "");
          } else {
            reject(new Error("No se pudo leer el archivo"));
          }
        };
        reader.onerror = () => reject(new Error("No se pudo leer el archivo"));
        reader.readAsDataURL(selectedFile);
      });

      await apiClient.post(`/rrhh/employee/${employee.id}/documents`, {
        tipo,
        descripcion: descripcion || null,
        fileName: selectedFile.name,
        mimeType: selectedFile.type || "application/octet-stream",
        fileData,
      });

      toast.current?.show({
        severity: "success",
        summary: "Documento cargado",
        detail: "El documento se guardó correctamente.",
        life: 3000,
      });

      setTipo(null);
      setDescripcion("");
      setSelectedFile(null);
      await loadDocuments();
    } catch (error) {
      console.error("Error al subir documento:", error);
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: error instanceof Error ? error.message : "No se pudo subir el documento.",
        life: 5000,
      });
    } finally {
      setIsUploading(false);
    }
  };

  const handleViewDocument = async (doc: EmployeeDocumentSummary) => {
    try {
      const full = await apiClient.get<{ fileData: string; mimeType: string }>(
        `/rrhh/employee/${employee.id}/documents/${doc.id}/download`
      );
      const dataUrl = `data:${full.mimeType};base64,${full.fileData}`;
      window.open(dataUrl, "_blank");
    } catch (error) {
      console.error("Error al abrir documento:", error);
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: "No se pudo abrir el documento.",
        life: 5000,
      });
    }
  };

  const handleDeleteDocument = async (doc: EmployeeDocumentSummary) => {
    if (!confirm(`¿Eliminar el documento "${doc.fileName}"?`)) return;
    try {
      await apiClient.delete(`/rrhh/employee/${employee.id}/documents/${doc.id}`);
      toast.current?.show({
        severity: "success",
        summary: "Documento eliminado",
        life: 3000,
      });
      await loadDocuments();
    } catch (error) {
      console.error("Error al eliminar documento:", error);
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: "No se pudo eliminar el documento.",
        life: 5000,
      });
    }
  };

  return (
    <div className="mt-6 space-y-6">
      <Toast ref={toast} />

      <div className="bg-card p-6 rounded-lg shadow-sm">
        <h3 className="font-heading text-lg font-bold text-foreground mb-4 border-b border-border pb-2">
          Cargar Documento
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">Tipo de Documento</label>
            <Dropdown
              value={tipo}
              options={DOCUMENT_TYPES.map((t) => ({ label: t, value: t }))}
              onChange={(e) => setTipo(e.value)}
              placeholder="Seleccioná un tipo..."
              className="w-full"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">Descripción (opcional)</label>
            <InputText
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              className="w-full"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-foreground">Archivo (PDF/Imagen)</label>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              onChange={handleFileChange}
              className="w-full p-2 border border-border rounded-md text-sm"
            />
          </div>
        </div>
        <div className="mt-4">
          <Button
            label={isUploading ? "Subiendo..." : "Subir documento"}
            icon="pi pi-upload"
            className="p-button-sm p-button-primary"
            onClick={handleUpload}
            loading={isUploading}
            disabled={isUploading}
          />
        </div>
      </div>

      <div className="bg-card p-6 rounded-lg shadow-sm">
        <h3 className="font-heading text-lg font-bold text-foreground mb-4 border-b border-border pb-2">
          Documentos Cargados
        </h3>
        {loading ? (
          <p className="text-muted-foreground text-sm">Cargando documentos...</p>
        ) : documents.length === 0 ? (
          <p className="text-muted-foreground text-sm italic">No hay documentos cargados.</p>
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
                  <td className="py-2 text-foreground">{formatDate(new Date(doc.createdAt))}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <Button
                      icon="pi pi-eye"
                      className="p-button-text p-button-sm"
                      onClick={() => handleViewDocument(doc)}
                      style={{ color: "var(--primary)" }}
                    />
                    <Button
                      icon="pi pi-trash"
                      className="p-button-text p-button-sm"
                      onClick={() => handleDeleteDocument(doc)}
                      style={{ color: "var(--error)" }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
```

- [ ] **Step 3: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "TablaOperador/DetailTables"`
Expected: ningún resultado (sin errores nuevos en este archivo).

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/TablaOperador/DetailTables.tsx
git commit -m "feat: agregar DocumentsTab para adjuntar documentacion del legajo"
```

- [ ] **Step 5: Agregar la tab "Documentos" en `Perfildetail.tsx`**

Antes (`RRHH/src/app/Componentes/TablaOperador/Perfildetail.tsx`, líneas 1-13 y 80-106):
```tsx
"use client"
import { ArrowLeft } from "lucide-react";
import {ProfileTab,LicenseHistoryTab,PermissionHistoryTab} from "./DetailTables"
import {StatusBadge} from "@/app/util/UiRRHH"
import { useState } from "react";
import {  Employee, LicenseHistory} from '@/app/Interfas/Interfaces';
import { Avatar } from 'primereact/avatar';

export interface EmployeeDetailViewProps {
  employee: Employee | null | undefined;
  onBack: () => void;
 onLicenseClick: (license: LicenseHistory | null) => void;
}
```

```tsx
          <button
            onClick={() => setActiveTab("permisos")}
            className={`${
              activeTab === "permisos"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Historial de Permisos
          </button>
        </nav>
      </div>
      <div className="no-print">
        {activeTab === "perfil" && <ProfileTab employee={employee} />}
        {activeTab === "licencias" && (
          <LicenseHistoryTab
            licenses={employee.licenses}
            employee={employee}
            onRowClick={onLicenseClick}
          />
        )}
        {activeTab === "permisos" && (
          <PermissionHistoryTab permisos={employee.permisos} />
        )}
      </div>
    </div>
  );
};
```

Después:
```tsx
"use client"
import { ArrowLeft } from "lucide-react";
import {ProfileTab,LicenseHistoryTab,PermissionHistoryTab,DocumentsTab} from "./DetailTables"
import {StatusBadge} from "@/app/util/UiRRHH"
import { useState } from "react";
import {  Employee, LicenseHistory} from '@/app/Interfas/Interfaces';
import { Avatar } from 'primereact/avatar';

export interface EmployeeDetailViewProps {
  employee: Employee | null | undefined;
  onBack: () => void;
 onLicenseClick: (license: LicenseHistory | null) => void;
}
```

```tsx
          <button
            onClick={() => setActiveTab("permisos")}
            className={`${
              activeTab === "permisos"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Historial de Permisos
          </button>
          <button
            onClick={() => setActiveTab("documentos")}
            className={`${
              activeTab === "documentos"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Documentos
          </button>
        </nav>
      </div>
      <div className="no-print">
        {activeTab === "perfil" && <ProfileTab employee={employee} />}
        {activeTab === "licencias" && (
          <LicenseHistoryTab
            licenses={employee.licenses}
            employee={employee}
            onRowClick={onLicenseClick}
          />
        )}
        {activeTab === "permisos" && (
          <PermissionHistoryTab permisos={employee.permisos} />
        )}
        {activeTab === "documentos" && <DocumentsTab employee={employee} />}
      </div>
    </div>
  );
};
```

- [ ] **Step 6: Verificar tipos**

Run: `cd RRHH && npx tsc --noEmit 2>&1 | grep -E "TablaOperador/Perfildetail"`
Expected: ningún resultado.

- [ ] **Step 7: Commit**

```bash
git add src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "feat: agregar tab Documentos al detalle de empleado de RRHH"
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

- [ ] **Step 2: Cargar un documento**

Como RRHH, entrar al detalle de un empleado → tab "Documentos". Seleccionar tipo "DNI", escribir una descripción, elegir un PDF, tocar "Subir documento". Confirmar el toast de éxito y que aparece en la lista.

- [ ] **Step 3: Cargar una imagen**

Repetir con un tipo distinto y un archivo JPG/PNG. Confirmar que también aparece en la lista.

- [ ] **Step 4: Ver/Descargar**

Tocar el ícono de ojo en cada documento cargado. Confirmar que se abre correctamente en una pestaña nueva (PDF se renderiza, imagen se muestra).

- [ ] **Step 5: Eliminar**

Eliminar uno de los documentos. Confirmar que desaparece de la lista y que, recargando la página (F5) y volviendo a la tab "Documentos", sigue sin aparecer.

- [ ] **Step 6: Confirmar persistencia entre tabs**

Cambiar a otra tab ("Perfil") y volver a "Documentos" sin recargar la página — confirmar que la lista sigue mostrando los documentos cargados (no se resetea por cambiar de tab, ya que `DocumentsTab` recarga al montar).

- [ ] **Step 7: Confirmar permisos**

Como usuario sin rol Admin/RRHH, intentar acceder a `GET /rrhh/employee/{id}/documents` (vía `curl` o similar) — debe devolver 403.
