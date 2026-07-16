# Portal Institucional — Editor rich-text + adjuntos (Subsistema 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el `contenido` de texto plano de las publicaciones por un editor WYSIWYG rico (TipTap) con adjuntos guardados en disco, y construir el formulario de autoría que hasta ahora no existía.

**Architecture:** Backend FastAPI agrega una tabla `PublicationAttachment` (metadatos + ruta en disco, nunca base64), un endpoint de subida multipart con validación de tipo/tamaño, servido estático vía `StaticFiles`, sanitización HTML con `nh3` al guardar, y extiende `POST`/`PUT`/`GET` de publicaciones para asociar adjuntos. Frontend Next.js agrega TipTap con nodos custom (botón/galería/video), un formulario de autoría con lista mínima, y cambia el detalle del empleado para renderizar HTML sanitizado (DOMPurify).

**Tech Stack:** FastAPI + SQLAlchemy `text()` + SQL Server (pyodbc) · `nh3` (sanitización) · `StaticFiles` · Next.js App Router + React + PrimeReact + Tailwind · TipTap (`@tiptap/react` + extensiones) · DOMPurify · lucide-react.

## Global Constraints

- **Sin base64 en DB**: los binarios van a disco (`uploads/publications/`), la DB guarda solo ruta + metadatos.
- **Límites de subida** (validados en frontend y backend, rechazo 400 antes de escribir a disco):
  - Imágenes (inline, galerías): 10 MB c/u — extensiones `jpg, jpeg, png, webp, gif`.
  - Documentos (adjuntos): 25 MB c/u — extensiones `pdf, docx, xlsx, pptx, txt, zip`.
  - Video (incrustado): 200 MB c/u — extensiones `mp4, webm`.
- **Nombre en disco generado** (`uuid4.ext`), nunca el nombre del usuario.
- **Sanitización HTML obligatoria**: `nh3` en backend al guardar + DOMPurify en frontend al renderizar.
- **Sin cambio de esquema en `Publication`**: `contenido` sigue `NVARCHAR(MAX)`, ahora guarda HTML.
- **Autoría protegida** con `require_rrhh_auth` (= `require_roles(ROLE_ADMIN, ROLE_RRHH)`) ya definido en `publications.py`. La página frontend `gestion-publicaciones` es visible/accesible solo para ADMIN y RRHH.
- **Tokens semánticos "Orgánico Cálido"** en todo el frontend (`bg-card`, `bg-background`, `border-border`, `shadow-soft`, `font-heading`, `text-foreground`, `text-muted-foreground`), sin hex crudo. Dark mode por tokens.
- **Sin suite de tests automatizada** en ninguno de los dos repos (patrón del proyecto): la verificación por tarea es compilación (`py -m py_compile` / `npx tsc --noEmit`) + chequeo manual descrito. No inventar pytest/jest.
- **Categorías válidas (9)**: `Noticia Institucional, Circular, Resolución, Mantenimiento y Reparaciones, Aviso Importante, Evento Institucional, Oportunidad Interna, Beneficio para Empleados, Comunicación de RRHH`. Prioridades: `Baja, Normal, Alta, Urgente`.

---

## File Structure

**Backend_RRHH:**
- Create: `app/database/publications_attachments.py` — tabla `PublicationAttachment`, constantes de límites/extensiones, validación de subida, helpers de asociación/lectura.
- Modify: `app/routes/publications.py` — endpoint de subida, sanitización, asociación de adjuntos en POST/PUT, adjuntos en GET feed/{id}, cascada en DELETE.
- Modify: `app/main.py` — montar `StaticFiles` en `/uploads` y crear la carpeta al arrancar.
- Modify: `requirements.txt` — agregar `nh3`.
- Modify: `.gitignore` — ignorar `uploads/`.

**RRHH:**
- Modify: `package.json` — dependencias TipTap + dompurify (vía `npm install`).
- Create: `src/app/util/uploadClient.ts` — helper de subida multipart con Bearer (apiClient no soporta FormData).
- Modify: `src/app/Interfas/Interfaces.ts` — `"gestion-publicaciones"` en `Page`, interfaces `PublicationAttachment`, `PublicationAdminRow`, `PublicationEditData`, y `adjuntos` en `FeedPublication`.
- Create: `src/app/Componentes/GestionPublicaciones/tiptap/ButtonNode.ts`, `GalleryNode.ts`, `VideoNode.ts` — nodos custom TipTap.
- Create: `src/app/Componentes/GestionPublicaciones/RichTextEditor.tsx` — editor + toolbar + subida inline.
- Create: `src/app/Componentes/GestionPublicaciones/AttachmentsField.tsx` — gestor de adjuntos descargables.
- Create: `src/app/screens/GestionPublicaciones/Screen.tsx` — formulario de autoría + lista mínima.
- Modify: `src/app/util/rbac.ts` — entrada `gestion-publicaciones` en `PAGE_CONFIG`.
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx` — ícono nuevo en el `ICON_MAP` + import.
- Modify: `src/app/page.tsx` — `case 'gestion-publicaciones'`.
- Modify: `src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx` — render HTML sanitizado + sección de adjuntos.

---

## Task 1: Backend — modelo de datos `PublicationAttachment`

**Files:**
- Create: `app/database/publications_attachments.py`

**Interfaces:**
- Consumes: nada (módulo base).
- Produces:
  - `ensure_attachments_table(db: Session) -> None`
  - `CATEGORIAS_LIMITE: dict[str, int]` (bytes), `EXT_A_CATEGORIA: dict[str, str]`, `VALID_ROLES: set[str]`
  - `validar_subida(file_name: str, size_bytes: int) -> str` (devuelve `storedName` extensión-validada o lanza `ValueError` con mensaje) — en la práctica devuelve la extensión en minúscula; la validación de categoría/tamaño se hace en la función `categoria_y_limite`.
  - `categoria_de_extension(ext: str) -> str | None`
  - `insertar_adjunto(db, rol, file_name, stored_name, mime_type, size_bytes, url) -> dict`
  - `adjuntos_descargables_de(db, publication_id) -> list[dict]`
  - `asociar_adjuntos(db, publication_id, ids: list[int]) -> None`
  - `resync_adjuntos(db, publication_id, ids: list[int]) -> None`
  - `desactivar_adjuntos_de(db, publication_id) -> None`

- [ ] **Step 1: Crear el módulo con la tabla, constantes y helpers**

```python
"""
Adjuntos de las publicaciones del Portal Institucional (subsistema 3).
Los binarios se guardan en disco (uploads/publications/), la DB guarda
solo metadatos + ruta -- nunca base64. Una sola tabla para inline
(imagenes/video/galeria embebidos en el HTML) y adjuntos descargables.
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime


# Limite de tamano por categoria (bytes)
CATEGORIAS_LIMITE = {
    "imagen": 10 * 1024 * 1024,
    "documento": 25 * 1024 * 1024,
    "video": 200 * 1024 * 1024,
}

EXT_A_CATEGORIA = {
    "jpg": "imagen", "jpeg": "imagen", "png": "imagen", "webp": "imagen", "gif": "imagen",
    "pdf": "documento", "docx": "documento", "xlsx": "documento", "pptx": "documento",
    "txt": "documento", "zip": "documento",
    "mp4": "video", "webm": "video",
}

VALID_ROLES = {"inline", "adjunto"}


CREATE_ATTACHMENT_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'PublicationAttachment' AND xtype = 'U'
)
BEGIN
    CREATE TABLE PublicationAttachment (
        id            INT IDENTITY(1,1) PRIMARY KEY,
        publicationId INT           NULL,
        rol           NVARCHAR(20)  NOT NULL,
        fileName      NVARCHAR(300) NOT NULL,
        storedName    NVARCHAR(300) NOT NULL,
        mimeType      NVARCHAR(100) NOT NULL,
        sizeBytes     BIGINT        NOT NULL,
        url           NVARCHAR(500) NOT NULL,
        orden         INT           NOT NULL DEFAULT 0,
        activo        BIT           NOT NULL DEFAULT 1,
        createdAt     DATETIME2     NOT NULL
    );
    CREATE INDEX IX_PublicationAttachment_publicationId ON PublicationAttachment (publicationId);
END
"""


def ensure_attachments_table(db: Session) -> None:
    """Crea PublicationAttachment si no existe (idempotente)."""
    db.execute(text(CREATE_ATTACHMENT_SQL))
    db.commit()


def categoria_de_extension(ext: str) -> str | None:
    """Devuelve 'imagen'|'documento'|'video' para la extension, o None si no permitida."""
    return EXT_A_CATEGORIA.get(ext.lower().lstrip("."))


def insertar_adjunto(db: Session, rol: str, file_name: str, stored_name: str,
                     mime_type: str, size_bytes: int, url: str) -> dict:
    """Inserta una fila de adjunto (publicationId NULL) y devuelve su metadata."""
    now = datetime.utcnow()
    result = db.execute(text("""
        INSERT INTO PublicationAttachment
            (publicationId, rol, fileName, storedName, mimeType, sizeBytes, url, orden, activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (NULL, :rol, :fileName, :storedName, :mimeType, :sizeBytes, :url, 0, 1, :createdAt)
    """), {
        "rol": rol, "fileName": file_name, "storedName": stored_name,
        "mimeType": mime_type, "sizeBytes": size_bytes, "url": url, "createdAt": now,
    })
    new_id = result.scalar()
    db.commit()
    return {"id": new_id, "url": url, "fileName": file_name, "mimeType": mime_type, "sizeBytes": size_bytes}


def adjuntos_descargables_de(db: Session, publication_id: int) -> list[dict]:
    """Adjuntos rol='adjunto' activos de una publicacion, ordenados."""
    rows = db.execute(text("""
        SELECT id, fileName, url, mimeType, sizeBytes
        FROM PublicationAttachment
        WHERE publicationId = :id AND rol = 'adjunto' AND activo = 1
        ORDER BY orden, id
    """), {"id": publication_id}).mappings().all()
    return [dict(r) for r in rows]


def asociar_adjuntos(db: Session, publication_id: int, ids: list[int]) -> None:
    """Asocia (al crear) los adjuntos indicados a la publicacion. Ignora ids invalidos."""
    for raw in ids or []:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        db.execute(text("""
            UPDATE PublicationAttachment SET publicationId = :pid, activo = 1 WHERE id = :aid
        """), {"pid": publication_id, "aid": aid})


def resync_adjuntos(db: Session, publication_id: int, ids: list[int]) -> None:
    """Re-sincroniza (al editar): asocia los de la lista y desactiva los que ya no estan."""
    limpios = []
    for raw in ids or []:
        try:
            limpios.append(int(raw))
        except (TypeError, ValueError):
            continue
    if limpios:
        placeholders = ",".join(str(i) for i in limpios)  # ints ya casteados: sin inyeccion
        db.execute(text(
            f"UPDATE PublicationAttachment SET activo = 0 "
            f"WHERE publicationId = :pid AND id NOT IN ({placeholders})"
        ), {"pid": publication_id})
        for aid in limpios:
            db.execute(text("""
                UPDATE PublicationAttachment SET publicationId = :pid, activo = 1 WHERE id = :aid
            """), {"pid": publication_id, "aid": aid})
    else:
        db.execute(text("""
            UPDATE PublicationAttachment SET activo = 0 WHERE publicationId = :pid
        """), {"pid": publication_id})


def desactivar_adjuntos_de(db: Session, publication_id: int) -> None:
    """Marca todos los adjuntos de una publicacion como inactivos (al borrar la publicacion)."""
    db.execute(text("""
        UPDATE PublicationAttachment SET activo = 0 WHERE publicationId = :id
    """), {"id": publication_id})
```

- [ ] **Step 2: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/database/publications_attachments.py`
Expected: sin salida (exit 0).

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/database/publications_attachments.py
git commit -m "feat: agregar modelo de datos de adjuntos de publicaciones"
```

---

## Task 2: Backend — servido estático + endpoint de subida

**Files:**
- Modify: `app/main.py`
- Modify: `app/routes/publications.py`
- Modify: `.gitignore`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ensure_attachments_table`, `categoria_de_extension`, `CATEGORIAS_LIMITE`, `VALID_ROLES`, `insertar_adjunto` (Task 1).
- Produces: `POST /publications/attachments` → `{id, url, fileName, mimeType, sizeBytes}`; carpeta `uploads/publications/` servida en `GET /uploads/...`.

- [ ] **Step 1: Montar `StaticFiles` y crear la carpeta en `main.py`**

En `app/main.py`, agregar el import y el montaje. Reemplazar:
```python
from fastapi import FastAPI
from app.cors_config import setup_cors
```
por:
```python
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.cors_config import setup_cors
```

Y después de `setup_cors(app)` (línea 8), agregar:
```python
# Carpeta de adjuntos del Portal Institucional (subsistema 3): se sirve
# estaticamente y se crea al importar si no existe.
os.makedirs("uploads/publications", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
```

- [ ] **Step 2: Agregar `nh3` a `requirements.txt`**

Agregar una línea al final de `requirements.txt`:
```
nh3
```
Luego instalar: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && pip install nh3`
Expected: `Successfully installed nh3-...`

- [ ] **Step 3: Ignorar `uploads/` en `.gitignore`**

Agregar al final de `.gitignore`:
```
uploads/
```

- [ ] **Step 4: Agregar el endpoint de subida en `publications.py`**

En `app/routes/publications.py`, agregar a los imports del inicio:
```python
import os
import uuid
from fastapi import UploadFile, File, Form
from app.database.publications_attachments import (
    ensure_attachments_table,
    categoria_de_extension,
    CATEGORIAS_LIMITE,
    VALID_ROLES,
    insertar_adjunto,
    adjuntos_descargables_de,
    asociar_adjuntos,
    resync_adjuntos,
    desactivar_adjuntos_de,
)
```

Y agregar el endpoint (por ejemplo, justo antes del `POST /publications` existente, después de `_notificar_destinatarios`):
```python
UPLOAD_DIR = "uploads/publications"


@router.post("/attachments", dependencies=[Depends(require_rrhh_auth)])
async def upload_attachment(file: UploadFile = File(...), rol: str = Form(...), db: Session = Depends(get_db)):
    """Sube un adjunto a disco y devuelve su metadata. Valida tipo y tamano
    antes de escribir. rol = 'inline' (embebido en el cuerpo) | 'adjunto' (descargable)."""
    ensure_attachments_table(db)

    if rol not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"rol debe ser uno de: {sorted(VALID_ROLES)}")

    original = file.filename or ""
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    categoria = categoria_de_extension(ext)
    if categoria is None:
        raise HTTPException(status_code=400, detail=f"Tipo de archivo no permitido (.{ext})")

    contenido = await file.read()
    size = len(contenido)
    limite = CATEGORIAS_LIMITE[categoria]
    if size > limite:
        mb = limite // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"El archivo excede el limite de {mb} MB para {categoria}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(UPLOAD_DIR, stored_name), "wb") as f:
        f.write(contenido)

    url = f"/uploads/publications/{stored_name}"
    return insertar_adjunto(
        db, rol=rol, file_name=original, stored_name=stored_name,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size, url=url,
    )
```

- [ ] **Step 5: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/main.py app/routes/publications.py`
Expected: sin salida (exit 0).

- [ ] **Step 6: Verificación manual rápida (opcional pero recomendada)**

Arrancar el server (`py -m uvicorn app.main:app --reload`) y subir un archivo con un cliente autenticado (Postman/curl con Bearer): `POST /publications/attachments` con form-data `file=<imagen.png>` y `rol=inline` → 200 con `{id, url, ...}`; subir un `.exe` → 400; subir una imagen > 10 MB → 400.

- [ ] **Step 7: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/main.py app/routes/publications.py .gitignore requirements.txt
git commit -m "feat: agregar servido estatico y endpoint de subida de adjuntos"
```

---

## Task 3: Backend — sanitización + asociación de adjuntos en CRUD y lectura

**Files:**
- Modify: `app/routes/publications.py`

**Interfaces:**
- Consumes: `nh3`, y los helpers de Task 1 (`asociar_adjuntos`, `resync_adjuntos`, `desactivar_adjuntos_de`, `adjuntos_descargables_de`, `ensure_attachments_table`).
- Produces: `contenido` sanitizado al guardar; `attachmentIds` asociados; `adjuntos` incluidos en `GET /publications/feed` y `GET /publications/{id}`.

- [ ] **Step 1: Agregar el helper de sanitización**

En `app/routes/publications.py`, agregar `import nh3` a los imports y esta función helper (por ejemplo tras `_parse_dt`):
```python
_ALLOWED_TAGS = {
    "p", "br", "strong", "em", "u", "s", "h1", "h2", "h3",
    "ul", "ol", "li", "blockquote", "a", "img",
    "table", "thead", "tbody", "tr", "td", "th",
    "div", "span", "video", "source", "figure", "figcaption",
}
_ALLOWED_ATTRS = {
    "a": {"href", "target", "rel", "class"},
    "img": {"src", "alt", "class", "width", "height"},
    "div": {"class"},
    "span": {"class"},
    "video": {"controls", "src", "class", "width", "height"},
    "source": {"src", "type"},
    "table": {"class"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}


def _sanitizar_html(raw):
    """Sanitiza el HTML del contenido con una allowlist (defensa contra XSS)."""
    if not raw:
        return raw
    return nh3.clean(raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
```

- [ ] **Step 2: Sanitizar `contenido` y asociar adjuntos en `POST /publications`**

En `create_publication`, reemplazar la línea del INSERT que pasa `"contenido": data.get("contenido"),` por:
```python
        "contenido": _sanitizar_html(data.get("contenido")),
```
Y después de `_insertar_targets(db, new_id, targets)` (y antes del bloque de notificación), agregar:
```python
    ensure_attachments_table(db)
    asociar_adjuntos(db, new_id, data.get("attachmentIds") or [])
```

- [ ] **Step 3: Sanitizar y re-sincronizar adjuntos en `PUT /publications/{id}`**

En `update_publication`, reemplazar `"contenido": data.get("contenido"),` (en el UPDATE) por:
```python
        "contenido": _sanitizar_html(data.get("contenido")),
```
Y después de `_insertar_targets(db, publication_id, targets)`, agregar:
```python
    ensure_attachments_table(db)
    resync_adjuntos(db, publication_id, data.get("attachmentIds") or [])
```

- [ ] **Step 4: Cascada en `DELETE /publications/{id}`**

En `delete_publication`, después del `UPDATE Publication SET activo = 0 ...` (antes de `db.commit()`), agregar:
```python
    ensure_attachments_table(db)
    desactivar_adjuntos_de(db, publication_id)
```

- [ ] **Step 5: Incluir `adjuntos` en `GET /publications/feed`**

En `get_feed`, agregar `ensure_attachments_table(db)` después del `ensure_table(db)` existente. Luego, en el dict de cada publicación devuelta, agregar la clave:
```python
                "adjuntos": adjuntos_descargables_de(db, r["id"]),
```
(justo después de `"createdAt": ...`).

- [ ] **Step 6: Incluir `adjuntos` en `GET /publications/{id}`**

En `get_publication`, agregar `ensure_attachments_table(db)` después del `ensure_table(db)` existente. En el dict devuelto, agregar (junto a `"targets"`):
```python
        "adjuntos": adjuntos_descargables_de(db, r["id"]),
```

- [ ] **Step 7: Verificar que compila**

Run: `cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m py_compile app/routes/publications.py`
Expected: sin salida (exit 0).

- [ ] **Step 8: Verificación manual (recomendada)**

Con el server corriendo: crear una publicación (`POST /publications`) con `contenido` que incluya `<script>alert(1)</script><p>hola</p>` y `attachmentIds:[<id de un adjunto subido>]` → el `<script>` desaparece al guardar; el adjunto queda con `publicationId` seteado. `GET /publications/{id}` devuelve `adjuntos` con ese archivo.

- [ ] **Step 9: Commit**

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH"
git add app/routes/publications.py
git commit -m "feat: sanitizar HTML y asociar adjuntos en el CRUD de publicaciones"
```

---

## Task 4: Frontend — dependencias, helper de subida y tipos

**Files:**
- Modify: `package.json` (vía `npm install`)
- Create: `src/app/util/uploadClient.ts`
- Modify: `src/app/Interfas/Interfaces.ts`

**Interfaces:**
- Consumes: nada nuevo.
- Produces:
  - `uploadAttachment(file: File, rol: 'inline' | 'adjunto'): Promise<PublicationAttachment>`
  - Tipos: `PublicationAttachment`, `PublicationAdminRow`, `PublicationEditData`; `"gestion-publicaciones"` en `Page`; `adjuntos?: PublicationAttachment[]` en `FeedPublication`.

- [ ] **Step 1: Instalar dependencias TipTap + DOMPurify**

Run:
```bash
cd "C:\Users\Emiliano\Documents\RRHH"
npm install @tiptap/react @tiptap/pm @tiptap/starter-kit @tiptap/extension-image @tiptap/extension-link @tiptap/extension-table @tiptap/extension-table-row @tiptap/extension-table-cell @tiptap/extension-table-header dompurify
npm install -D @types/dompurify
```
Expected: `added N packages`. Verifica que `package.json` liste esas dependencias.

- [ ] **Step 2: Crear el helper de subida `uploadClient.ts`**

`apiClient` fija `Content-Type: application/json` y serializa a JSON, así que no sirve para multipart. Este helper hace `FormData` inyectando el Bearer token:
```typescript
// util/uploadClient.ts
// Subida de archivos multipart al backend. Separado de apiClient porque
// este ultimo fuerza Content-Type JSON; en multipart el browser debe
// setear el boundary. Inyecta el mismo Bearer token de localStorage.

import type { PublicationAttachment } from '@/app/Interfas/Interfaces';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000';

export async function uploadAttachment(
  file: File,
  rol: 'inline' | 'adjunto'
): Promise<PublicationAttachment> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const form = new FormData();
  form.append('file', file);
  form.append('rol', rol);

  const res = await fetch(`${BACKEND_URL}/publications/attachments`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.message || `Error al subir (${res.status})`);
  }
  return res.json();
}
```

- [ ] **Step 3: Agregar los tipos en `Interfaces.ts`**

En `src/app/Interfas/Interfaces.ts`:

(a) Agregar `"gestion-publicaciones"` al union type `Page` (junto a `"inicio"`).

(b) Agregar estas interfaces:
```typescript
export interface PublicationAttachment {
  id: number;
  url: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
}

export interface PublicationAdminRow {
  id: number;
  titulo: string;
  categoria: string;
  estado: string;
  fechaPublicacion: string | null;
  createdAt: string | null;
}

export interface PublicationTargetInput {
  scope: 'institucion' | 'departamento' | 'oficina';
  departmentId?: number | null;
  officeId?: number | null;
}

export interface PublicationEditData {
  id: number;
  titulo: string;
  resumen: string | null;
  contenido: string | null;
  categoria: string;
  prioridad: string;
  estadoMantenimiento: string | null;
  esBorrador: boolean;
  destacada: boolean;
  fijada: boolean;
  fechaPublicacion: string | null;
  fechaExpiracion: string | null;
  targets: PublicationTargetInput[];
  adjuntos: PublicationAttachment[];
}
```

(c) En la interfaz `FeedPublication` existente, agregar:
```typescript
  adjuntos?: PublicationAttachment[];
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "uploadClient|Interfaces"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add package.json package-lock.json src/app/util/uploadClient.ts src/app/Interfas/Interfaces.ts
git commit -m "feat: agregar dependencias del editor, helper de subida y tipos de adjuntos"
```

---

## Task 5: Frontend — nodos custom de TipTap (botón, galería, video)

**Files:**
- Create: `src/app/Componentes/GestionPublicaciones/tiptap/ButtonNode.ts`
- Create: `src/app/Componentes/GestionPublicaciones/tiptap/GalleryNode.ts`
- Create: `src/app/Componentes/GestionPublicaciones/tiptap/VideoNode.ts`

**Interfaces:**
- Consumes: `@tiptap/core`.
- Produces: tres extensiones TipTap con comandos `setButton({href, label})`, `setGallery({srcs})`, `setVideo({src})`. Cada nodo produce HTML semántico auto-contenido (clases `pub-cta`, `pub-gallery`, `<video controls>`) que el detalle renderiza directo y que la allowlist de `nh3` permite.

- [ ] **Step 1: Crear `ButtonNode.ts`**

```typescript
import { Node, mergeAttributes } from '@tiptap/core';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    button: {
      setButton: (attrs: { href: string; label: string }) => ReturnType;
    };
  }
}

export const ButtonNode = Node.create({
  name: 'button',
  group: 'block',
  atom: true,

  addAttributes() {
    return {
      href: { default: '#' },
      label: { default: 'Ver más' },
    };
  },

  parseHTML() {
    return [{ tag: 'a.pub-cta' }];
  },

  renderHTML({ HTMLAttributes, node }) {
    return [
      'a',
      mergeAttributes(HTMLAttributes, {
        class: 'pub-cta',
        href: node.attrs.href,
        target: '_blank',
        rel: 'noopener noreferrer',
      }),
      node.attrs.label,
    ];
  },

  addCommands() {
    return {
      setButton:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    };
  },
});
```

- [ ] **Step 2: Crear `VideoNode.ts`**

```typescript
import { Node, mergeAttributes } from '@tiptap/core';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    video: {
      setVideo: (attrs: { src: string }) => ReturnType;
    };
  }
}

export const VideoNode = Node.create({
  name: 'video',
  group: 'block',
  atom: true,

  addAttributes() {
    return {
      src: { default: '' },
    };
  },

  parseHTML() {
    return [{ tag: 'video' }];
  },

  renderHTML({ HTMLAttributes, node }) {
    return [
      'video',
      mergeAttributes(HTMLAttributes, {
        class: 'pub-video',
        controls: 'true',
        src: node.attrs.src,
      }),
    ];
  },

  addCommands() {
    return {
      setVideo:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    };
  },
});
```

- [ ] **Step 3: Crear `GalleryNode.ts`**

El nodo guarda un array de srcs y renderiza un `<div class="pub-gallery">` con `<img>` hijos, auto-contenido:
```typescript
import { Node, mergeAttributes } from '@tiptap/core';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    gallery: {
      setGallery: (attrs: { srcs: string[] }) => ReturnType;
    };
  }
}

export const GalleryNode = Node.create({
  name: 'gallery',
  group: 'block',
  atom: true,

  addAttributes() {
    return {
      srcs: {
        default: [] as string[],
        parseHTML: (element) =>
          Array.from(element.querySelectorAll('img')).map((img) => img.getAttribute('src') || ''),
        renderHTML: () => ({}),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div.pub-gallery' }];
  },

  renderHTML({ node }) {
    const imgs = (node.attrs.srcs as string[]).map((src) => [
      'img',
      { src, class: 'pub-gallery-img', alt: '' },
    ]);
    return ['div', mergeAttributes({ class: 'pub-gallery' }), ...imgs];
  },

  addCommands() {
    return {
      setGallery:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    };
  },
});
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "tiptap/(ButtonNode|GalleryNode|VideoNode)"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/GestionPublicaciones/tiptap/
git commit -m "feat: agregar nodos custom de TipTap (boton, galeria, video)"
```

---

## Task 6: Frontend — componente `RichTextEditor`

**Files:**
- Create: `src/app/Componentes/GestionPublicaciones/RichTextEditor.tsx`

**Interfaces:**
- Consumes: `@tiptap/react`, `@tiptap/starter-kit`, extensiones `Image`/`Link`/`Table*`, los nodos custom (Task 5), `uploadAttachment` (Task 4).
- Produces: `RichTextEditor({ value, onChange, onInlineUploaded })` — editor controlado que emite HTML por `onChange` y avisa cada id inline subido por `onInlineUploaded(id)`.

- [ ] **Step 1: Crear `RichTextEditor.tsx`**

```tsx
'use client';

import React, { useCallback } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import {
  Bold, Italic, Heading1, Heading2, List, ListOrdered,
  Link2, Image as ImageIcon, Table as TableIcon, MousePointerClick,
  Images, Video as VideoIcon,
} from 'lucide-react';
import { ButtonNode } from './tiptap/ButtonNode';
import { GalleryNode } from './tiptap/GalleryNode';
import { VideoNode } from './tiptap/VideoNode';
import { uploadAttachment } from '@/app/util/uploadClient';

interface RichTextEditorProps {
  value: string;
  onChange: (html: string) => void;
  onInlineUploaded: (id: number) => void;
}

const IMAGE_EXT = ['jpg', 'jpeg', 'png', 'webp', 'gif'];
const VIDEO_EXT = ['mp4', 'webm'];

function pickFile(accept: string, multiple: boolean): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.multiple = multiple;
    input.onchange = () => resolve(input.files ? Array.from(input.files) : []);
    input.click();
  });
}

export function RichTextEditor({ value, onChange, onInlineUploaded }: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Image,
      Link.configure({ openOnClick: false }),
      Table.configure({ resizable: false }),
      TableRow,
      TableCell,
      TableHeader,
      ButtonNode,
      GalleryNode,
      VideoNode,
    ],
    content: value || '',
    immediatelyRender: false,
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  });

  const subirEInsertarImagen = useCallback(async () => {
    if (!editor) return;
    const [file] = await pickFile('image/*', false);
    if (!file) return;
    try {
      const att = await uploadAttachment(file, 'inline');
      editor.chain().focus().setImage({ src: att.url }).run();
      onInlineUploaded(att.id);
    } catch (e) {
      alert((e as Error).message);
    }
  }, [editor, onInlineUploaded]);

  const subirEInsertarVideo = useCallback(async () => {
    if (!editor) return;
    const [file] = await pickFile('video/mp4,video/webm', false);
    if (!file) return;
    try {
      const att = await uploadAttachment(file, 'inline');
      editor.chain().focus().setVideo({ src: att.url }).run();
      onInlineUploaded(att.id);
    } catch (e) {
      alert((e as Error).message);
    }
  }, [editor, onInlineUploaded]);

  const subirEInsertarGaleria = useCallback(async () => {
    if (!editor) return;
    const files = await pickFile('image/*', true);
    if (files.length === 0) return;
    try {
      const subidas = await Promise.all(files.map((f) => uploadAttachment(f, 'inline')));
      editor.chain().focus().setGallery({ srcs: subidas.map((a) => a.url) }).run();
      subidas.forEach((a) => onInlineUploaded(a.id));
    } catch (e) {
      alert((e as Error).message);
    }
  }, [editor, onInlineUploaded]);

  const insertarLink = useCallback(() => {
    if (!editor) return;
    const url = window.prompt('URL del enlace:');
    if (url) editor.chain().focus().setLink({ href: url }).run();
  }, [editor]);

  const insertarBoton = useCallback(() => {
    if (!editor) return;
    const label = window.prompt('Texto del botón:');
    const href = window.prompt('URL del botón:');
    if (label && href) editor.chain().focus().setButton({ href, label }).run();
  }, [editor]);

  if (!editor) return null;

  const btn = 'p-2 rounded-lg hover:bg-muted text-foreground transition-colors duration-150';

  return (
    <div className="border border-border rounded-xl bg-card shadow-soft overflow-hidden">
      <div className="flex flex-wrap gap-1 border-b border-border p-2 bg-background">
        <button type="button" title="Negrita" className={btn} onClick={() => editor.chain().focus().toggleBold().run()}><Bold size={16} /></button>
        <button type="button" title="Itálica" className={btn} onClick={() => editor.chain().focus().toggleItalic().run()}><Italic size={16} /></button>
        <button type="button" title="Título 1" className={btn} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}><Heading1 size={16} /></button>
        <button type="button" title="Título 2" className={btn} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}><Heading2 size={16} /></button>
        <button type="button" title="Lista" className={btn} onClick={() => editor.chain().focus().toggleBulletList().run()}><List size={16} /></button>
        <button type="button" title="Lista numerada" className={btn} onClick={() => editor.chain().focus().toggleOrderedList().run()}><ListOrdered size={16} /></button>
        <button type="button" title="Enlace" className={btn} onClick={insertarLink}><Link2 size={16} /></button>
        <button type="button" title="Imagen" className={btn} onClick={subirEInsertarImagen}><ImageIcon size={16} /></button>
        <button type="button" title="Galería" className={btn} onClick={subirEInsertarGaleria}><Images size={16} /></button>
        <button type="button" title="Video" className={btn} onClick={subirEInsertarVideo}><VideoIcon size={16} /></button>
        <button type="button" title="Tabla" className={btn} onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}><TableIcon size={16} /></button>
        <button type="button" title="Botón/CTA" className={btn} onClick={insertarBoton}><MousePointerClick size={16} /></button>
      </div>
      <EditorContent editor={editor} className="pub-content p-4 min-h-[240px] text-foreground focus:outline-none" />
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "RichTextEditor"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/GestionPublicaciones/RichTextEditor.tsx
git commit -m "feat: agregar editor rich-text con toolbar y subida inline"
```

---

## Task 7: Frontend — componente `AttachmentsField`

**Files:**
- Create: `src/app/Componentes/GestionPublicaciones/AttachmentsField.tsx`

**Interfaces:**
- Consumes: `uploadAttachment` (Task 4), tipo `PublicationAttachment`.
- Produces: `AttachmentsField({ attachments, onChange })` — sube archivos rol `adjunto`, lista con nombre/tamaño, permite quitar. `attachments` es el array controlado por el padre.

- [ ] **Step 1: Crear `AttachmentsField.tsx`**

```tsx
'use client';

import React, { useCallback } from 'react';
import { Paperclip, X, FileText } from 'lucide-react';
import { uploadAttachment } from '@/app/util/uploadClient';
import type { PublicationAttachment } from '@/app/Interfas/Interfaces';

interface AttachmentsFieldProps {
  attachments: PublicationAttachment[];
  onChange: (list: PublicationAttachment[]) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AttachmentsField({ attachments, onChange }: AttachmentsFieldProps) {
  const subir = useCallback(async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = async () => {
      const files = input.files ? Array.from(input.files) : [];
      for (const file of files) {
        try {
          const att = await uploadAttachment(file, 'adjunto');
          onChange([...attachments, att]);
        } catch (e) {
          alert((e as Error).message);
        }
      }
    };
    input.click();
  }, [attachments, onChange]);

  const quitar = (id: number) => onChange(attachments.filter((a) => a.id !== id));

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-semibold text-foreground">Archivos adjuntos</label>
        <button
          type="button"
          onClick={subir}
          className="inline-flex items-center gap-1 text-sm px-3 py-1.5 rounded-lg border border-border hover:bg-muted text-foreground transition-colors duration-150"
        >
          <Paperclip size={14} /> Adjuntar
        </button>
      </div>
      {attachments.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sin adjuntos.</p>
      ) : (
        <ul className="space-y-2">
          {attachments.map((a) => (
            <li key={a.id} className="flex items-center justify-between bg-background border border-border rounded-lg px-3 py-2">
              <span className="inline-flex items-center gap-2 text-sm text-foreground truncate">
                <FileText size={16} className="text-primary shrink-0" />
                <span className="truncate">{a.fileName}</span>
                <span className="text-xs text-muted-foreground shrink-0">({formatSize(a.sizeBytes)})</span>
              </span>
              <button type="button" onClick={() => quitar(a.id)} className="text-muted-foreground hover:text-error transition-colors duration-150">
                <X size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "AttachmentsField"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/GestionPublicaciones/AttachmentsField.tsx
git commit -m "feat: agregar gestor de adjuntos descargables"
```

---

## Task 8: Frontend — pantalla de autoría `GestionPublicaciones/Screen.tsx`

**Files:**
- Create: `src/app/screens/GestionPublicaciones/Screen.tsx`

**Interfaces:**
- Consumes: `apiClient` (GET `/publications`, GET `/publications/{id}`, POST/PUT `/publications`, GET `/departments/`), `RichTextEditor` (Task 6), `AttachmentsField` (Task 7), tipos `PublicationAdminRow`/`PublicationEditData`/`PublicationAttachment`/`PublicationTargetInput` (Task 4).
- Produces: componente `GestionPublicaciones` (export default, sin props) — lista mínima + formulario crear/editar.

- [ ] **Step 1: Crear `GestionPublicaciones/Screen.tsx`**

```tsx
'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { apiClient } from '@/app/util/apiClient';
import { RichTextEditor } from '@/app/Componentes/GestionPublicaciones/RichTextEditor';
import { AttachmentsField } from '@/app/Componentes/GestionPublicaciones/AttachmentsField';
import type {
  PublicationAdminRow, PublicationEditData, PublicationAttachment, PublicationTargetInput,
} from '@/app/Interfas/Interfaces';
import { Plus, ArrowLeft } from 'lucide-react';

const CATEGORIAS = [
  'Noticia Institucional', 'Circular', 'Resolución', 'Mantenimiento y Reparaciones',
  'Aviso Importante', 'Evento Institucional', 'Oportunidad Interna',
  'Beneficio para Empleados', 'Comunicación de RRHH',
];
const PRIORIDADES = ['Baja', 'Normal', 'Alta', 'Urgente'];
const ESTADOS_MANT = ['Programado', 'En curso', 'Completado', 'Suspendido', 'Reprogramado'];
const CAT_MANTENIMIENTO = 'Mantenimiento y Reparaciones';

interface DeptOption { id: number; nombre: string; offices: { id: number; nombre: string }[]; }

const EMPTY_FORM = {
  titulo: '', resumen: '', contenido: '', categoria: 'Noticia Institucional',
  prioridad: 'Normal', esBorrador: true, destacada: false, fijada: false,
  fechaPublicacion: '', fechaExpiracion: '',
};

export default function GestionPublicaciones() {
  const [modo, setModo] = useState<'lista' | 'form'>('lista');
  const [rows, setRows] = useState<PublicationAdminRow[]>([]);
  const [depts, setDepts] = useState<DeptOption[]>([]);
  const [editId, setEditId] = useState<number | null>(null);

  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [estadoMant, setEstadoMant] = useState('');
  const [contenido, setContenido] = useState('');
  const [attachments, setAttachments] = useState<PublicationAttachment[]>([]);
  const [inlineIds, setInlineIds] = useState<number[]>([]);
  const [targetInstitucion, setTargetInstitucion] = useState(false);
  const [targetDeptIds, setTargetDeptIds] = useState<number[]>([]);
  const [targetOfficeIds, setTargetOfficeIds] = useState<number[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');

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
  }, [cargarLista]);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setEstadoMant('');
    setContenido('');
    setAttachments([]);
    setInlineIds([]);
    setTargetInstitucion(false);
    setTargetDeptIds([]);
    setTargetOfficeIds([]);
    setError('');
  };

  const nuevaPublicacion = () => {
    resetForm();
    setEditId(null);
    setModo('form');
  };

  const editarPublicacion = async (id: number) => {
    resetForm();
    try {
      const p = await apiClient.get<PublicationEditData>(`/publications/${id}`);
      setForm({
        titulo: p.titulo, resumen: p.resumen || '', contenido: p.contenido || '',
        categoria: p.categoria, prioridad: p.prioridad, esBorrador: p.esBorrador,
        destacada: p.destacada, fijada: p.fijada,
        fechaPublicacion: p.fechaPublicacion ? p.fechaPublicacion.slice(0, 16) : '',
        fechaExpiracion: p.fechaExpiracion ? p.fechaExpiracion.slice(0, 16) : '',
      });
      setEstadoMant(p.estadoMantenimiento || '');
      setContenido(p.contenido || '');
      setAttachments(p.adjuntos || []);
      setInlineIds([]);
      setTargetInstitucion(p.targets.some((t) => t.scope === 'institucion'));
      setTargetDeptIds(p.targets.filter((t) => t.scope === 'departamento').map((t) => t.departmentId!).filter(Boolean));
      setTargetOfficeIds(p.targets.filter((t) => t.scope === 'oficina').map((t) => t.officeId!).filter(Boolean));
      setEditId(id);
      setModo('form');
    } catch (e) {
      console.error('Error al cargar publicación:', e);
    }
  };

  const buildTargets = (): PublicationTargetInput[] => {
    const targets: PublicationTargetInput[] = [];
    if (targetInstitucion) targets.push({ scope: 'institucion' });
    targetDeptIds.forEach((id) => targets.push({ scope: 'departamento', departmentId: id }));
    targetOfficeIds.forEach((id) => targets.push({ scope: 'oficina', officeId: id }));
    return targets;
  };

  const guardar = async () => {
    setError('');
    if (!form.titulo.trim()) { setError('El título es obligatorio.'); return; }
    const targets = buildTargets();
    if (targets.length === 0) { setError('Indicá al menos un destino.'); return; }

    const attachmentIds = [...attachments.map((a) => a.id), ...inlineIds];
    const payload = {
      ...form,
      contenido,
      estadoMantenimiento: form.categoria === CAT_MANTENIMIENTO ? (estadoMant || null) : null,
      fechaPublicacion: form.fechaPublicacion || null,
      fechaExpiracion: form.fechaExpiracion || null,
      targets,
      attachmentIds,
    };

    setGuardando(true);
    try {
      if (editId) {
        await apiClient.put(`/publications/${editId}`, payload);
      } else {
        await apiClient.post('/publications', payload);
      }
      cargarLista();
      setModo('lista');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGuardando(false);
    }
  };

  const toggleId = (list: number[], id: number, setter: (v: number[]) => void) => {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  if (modo === 'lista') {
    return (
      <div className="bg-background min-h-screen p-4 sm:p-8">
        <div className="max-w-6xl mx-auto space-y-6">
          <header className="flex items-center justify-between">
            <div>
              <h1 className="font-heading text-3xl font-bold text-foreground">Gestión de Publicaciones</h1>
              <p className="text-muted-foreground">Creá y editá los comunicados institucionales.</p>
            </div>
            <button onClick={nuevaPublicacion} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-opacity duration-150">
              <Plus size={18} /> Nueva publicación
            </button>
          </header>

          <div className="bg-card border border-border rounded-xl shadow-soft overflow-hidden">
            {rows.length === 0 ? (
              <p className="p-8 text-center text-muted-foreground">No hay publicaciones todavía.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-background text-muted-foreground">
                  <tr>
                    <th className="text-left font-medium px-4 py-3">Título</th>
                    <th className="text-left font-medium px-4 py-3">Categoría</th>
                    <th className="text-left font-medium px-4 py-3">Estado</th>
                    <th className="text-left font-medium px-4 py-3">Fecha</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} onClick={() => editarPublicacion(r.id)} className="border-t border-border hover:bg-muted cursor-pointer">
                      <td className="px-4 py-3 text-foreground">{r.titulo}</td>
                      <td className="px-4 py-3 text-muted-foreground">{r.categoria}</td>
                      <td className="px-4 py-3 text-muted-foreground">{r.estado}</td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {r.fechaPublicacion ? new Date(r.fechaPublicacion).toLocaleDateString('es-AR') : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-background min-h-screen p-4 sm:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        <button onClick={() => setModo('lista')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors duration-150">
          <ArrowLeft size={16} /> Volver
        </button>
        <h1 className="font-heading text-2xl font-bold text-foreground">
          {editId ? 'Editar publicación' : 'Nueva publicación'}
        </h1>

        {error && <div className="bg-error-soft text-error-soft-foreground border border-error rounded-lg px-4 py-2 text-sm">{error}</div>}

        <div className="space-y-4 bg-card border border-border rounded-xl shadow-soft p-4 sm:p-6">
          <div>
            <label className="text-sm font-semibold text-foreground">Título</label>
            <input value={form.titulo} onChange={(e) => setForm({ ...form, titulo: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground" />
          </div>
          <div>
            <label className="text-sm font-semibold text-foreground">Resumen</label>
            <input value={form.resumen} onChange={(e) => setForm({ ...form, resumen: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-semibold text-foreground">Categoría</label>
              <select value={form.categoria} onChange={(e) => setForm({ ...form, categoria: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground">
                {CATEGORIAS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="text-sm font-semibold text-foreground">Prioridad</label>
              <select value={form.prioridad} onChange={(e) => setForm({ ...form, prioridad: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground">
                {PRIORIDADES.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
          </div>

          {form.categoria === CAT_MANTENIMIENTO && (
            <div>
              <label className="text-sm font-semibold text-foreground">Estado de mantenimiento</label>
              <select value={estadoMant} onChange={(e) => setEstadoMant(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground">
                <option value="">— Sin estado —</option>
                {ESTADOS_MANT.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          )}

          <div>
            <label className="text-sm font-semibold text-foreground">Contenido</label>
            <div className="mt-1">
              <RichTextEditor value={contenido} onChange={setContenido} onInlineUploaded={(id) => setInlineIds((prev) => [...prev, id])} />
            </div>
          </div>

          <AttachmentsField attachments={attachments} onChange={setAttachments} />

          <div>
            <label className="text-sm font-semibold text-foreground">Destinos</label>
            <div className="mt-2 space-y-3">
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input type="checkbox" checked={targetInstitucion} onChange={(e) => setTargetInstitucion(e.target.checked)} />
                Toda la institución
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Departamentos</p>
                  <div className="max-h-40 overflow-y-auto border border-border rounded-lg p-2 space-y-1">
                    {depts.map((d) => (
                      <label key={d.id} className="flex items-center gap-2 text-sm text-foreground">
                        <input type="checkbox" checked={targetDeptIds.includes(d.id)} onChange={() => toggleId(targetDeptIds, d.id, setTargetDeptIds)} />
                        {d.nombre}
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Oficinas</p>
                  <div className="max-h-40 overflow-y-auto border border-border rounded-lg p-2 space-y-1">
                    {depts.flatMap((d) => d.offices.map((o) => (
                      <label key={o.id} className="flex items-center gap-2 text-sm text-foreground">
                        <input type="checkbox" checked={targetOfficeIds.includes(o.id)} onChange={() => toggleId(targetOfficeIds, o.id, setTargetOfficeIds)} />
                        {d.nombre} / {o.nombre}
                      </label>
                    )))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-semibold text-foreground">Fecha de publicación</label>
              <input type="datetime-local" value={form.fechaPublicacion} onChange={(e) => setForm({ ...form, fechaPublicacion: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground" />
            </div>
            <div>
              <label className="text-sm font-semibold text-foreground">Fecha de expiración</label>
              <input type="datetime-local" value={form.fechaExpiracion} onChange={(e) => setForm({ ...form, fechaExpiracion: e.target.value })} className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background text-foreground" />
            </div>
          </div>

          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={form.destacada} onChange={(e) => setForm({ ...form, destacada: e.target.checked })} /> Destacada</label>
            <label className="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={form.fijada} onChange={(e) => setForm({ ...form, fijada: e.target.checked })} /> Fijada</label>
            <label className="flex items-center gap-2 text-sm text-foreground"><input type="checkbox" checked={form.esBorrador} onChange={(e) => setForm({ ...form, esBorrador: e.target.checked })} /> Guardar como borrador</label>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button onClick={() => setModo('lista')} className="px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted transition-colors duration-150">Cancelar</button>
            <button onClick={guardar} disabled={guardando} className="px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:opacity-90 transition-opacity duration-150 disabled:opacity-50">
              {guardando ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "GestionPublicaciones/Screen"`
Expected: sin salida.

- [ ] **Step 3: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/screens/GestionPublicaciones/Screen.tsx
git commit -m "feat: agregar formulario de autoria de publicaciones con lista minima"
```

---

## Task 9: Frontend — ruteo y RBAC

**Files:**
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/Componentes/Shell/AppSidebar.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: `GestionPublicaciones` (Task 8).
- Produces: página `"gestion-publicaciones"` accesible/visible solo para ADMIN y RRHH.

- [ ] **Step 1: Agregar la entrada en `PAGE_CONFIG` (`rbac.ts`)**

Insertar una entrada nueva en el array `PAGE_CONFIG` (después de la de `recursos-humanos`, dentro de la sección `"Gente"`):
```typescript
  {
    id: "gestion-publicaciones",
    label: "Publicaciones",
    icon: "Newspaper",
    section: "Gente",
    visibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH],
    accessibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH],
  },
```

- [ ] **Step 2: Registrar el ícono en `AppSidebar.tsx`**

En la lista de imports de `lucide-react` de `src/app/Componentes/Shell/AppSidebar.tsx`, agregar `Newspaper`. Y en el objeto `ICON_MAP`, agregar la clave:
```tsx
  Newspaper,
```
(Leé el archivo real primero para ubicar las dos ubicaciones exactas; el patrón es idéntico al usado para `Home` en el subsistema 2.)

- [ ] **Step 3: Registrar la pantalla en `page.tsx`**

Agregar el import (junto a los demás screens):
```tsx
import GestionPublicaciones from '@/app/screens/GestionPublicaciones/Screen';
```
Y agregar el `case` en el switch (por ejemplo tras `case 'recursos-humanos'`):
```tsx
      case 'gestion-publicaciones':
        return <GestionPublicaciones />;
```

- [ ] **Step 4: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "rbac|AppSidebar|page\.tsx"`
Expected: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/util/rbac.ts src/app/Componentes/Shell/AppSidebar.tsx src/app/page.tsx
git commit -m "feat: enganchar la pantalla de gestion de publicaciones en el ruteo"
```

---

## Task 10: Frontend — render rico + adjuntos en el detalle del empleado

**Files:**
- Modify: `src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx`
- Modify: `src/app/globals.css`

**Interfaces:**
- Consumes: `dompurify`, tipo `FeedPublication` (ya con `adjuntos?`).
- Produces: el detalle renderiza `contenido` como HTML sanitizado (clase `.pub-content`) y muestra la sección "Archivos adjuntos"; estilos globales para el HTML rico (encabezados, listas, tablas, galería, botón/CTA, video), usados tanto acá como en el editor (Task 6).

- [ ] **Step 1: Reemplazar el render de texto plano por HTML sanitizado + adjuntos**

En `src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx`:

(a) Agregar imports:
```tsx
import DOMPurify from 'dompurify';
import { Paperclip } from 'lucide-react';
```

(b) Reemplazar el bloque:
```tsx
          <div className="text-sm text-foreground whitespace-pre-wrap">
            {publication.contenido || publication.resumen || 'Sin contenido adicional.'}
          </div>
```
por:
```tsx
          {publication.contenido ? (
            <div
              className="pub-content text-sm text-foreground space-y-2"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(publication.contenido) }}
            />
          ) : (
            <div className="text-sm text-foreground whitespace-pre-wrap">
              {publication.resumen || 'Sin contenido adicional.'}
            </div>
          )}

          {publication.adjuntos && publication.adjuntos.length > 0 && (
            <div className="pt-2 border-t border-border">
              <p className="text-sm font-semibold text-foreground mb-2">Archivos adjuntos</p>
              <ul className="space-y-2">
                {publication.adjuntos.map((a) => (
                  <li key={a.id}>
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 text-sm text-primary hover:underline"
                    >
                      <Paperclip size={14} />
                      {a.fileName}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
```

- [ ] **Step 2: Agregar estilos del HTML rico en `globals.css`**

Al final de `src/app/globals.css`, agregar reglas scopeadas a `.pub-content` (usadas por el detalle y el editor). Usan tokens semánticos vía `var(--color-...)` / `hsl` según el patrón del archivo; el objetivo es que encabezados, listas, tablas, galería, botón/CTA y video se vean coherentes en claro y oscuro:
```css
/* Contenido rico de las publicaciones (editor + detalle) */
.pub-content h1 { font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0; }
.pub-content h2 { font-size: 1.25rem; font-weight: 700; margin: 0.5rem 0; }
.pub-content h3 { font-size: 1.1rem; font-weight: 600; margin: 0.5rem 0; }
.pub-content p { margin: 0.5rem 0; }
.pub-content ul { list-style: disc; padding-left: 1.5rem; margin: 0.5rem 0; }
.pub-content ol { list-style: decimal; padding-left: 1.5rem; margin: 0.5rem 0; }
.pub-content a { color: var(--color-primary); text-decoration: underline; }
.pub-content img { max-width: 100%; border-radius: 0.5rem; margin: 0.5rem 0; }
.pub-content table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; }
.pub-content th, .pub-content td { border: 1px solid var(--color-border); padding: 0.5rem; text-align: left; }
.pub-content video.pub-video { max-width: 100%; border-radius: 0.5rem; margin: 0.5rem 0; }
.pub-content .pub-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 0.5rem; margin: 0.75rem 0; }
.pub-content .pub-gallery-img { width: 100%; height: 100px; object-fit: cover; border-radius: 0.5rem; }
.pub-content a.pub-cta { display: inline-block; text-decoration: none; background: var(--color-primary); color: var(--color-primary-foreground); padding: 0.5rem 1rem; border-radius: 0.75rem; margin: 0.5rem 0; font-weight: 600; }
```
Nota: si algún token no existe con ese nombre exacto en `globals.css`, usá el nombre real definido en el bloque `@theme` del archivo (leélo primero). Los nombres esperados (`--color-primary`, `--color-border`, `--color-primary-foreground`) siguen el patrón "Orgánico Cálido" ya usado en el proyecto.

- [ ] **Step 3: Verificar tipos**

Run: `cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "PublicationDetailDialog"`
Expected: sin salida.

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/PortalInicio/PublicationDetailDialog.tsx src/app/globals.css
git commit -m "feat: renderizar contenido rico y adjuntos en el detalle de publicacion"
```

---

## Task 11: Verificación manual (sin commits)

Requiere backend + DB + browser reales; no automatizable. Checklist del spec (sección Testing):

- [ ] Backend compila: `py -m py_compile app/main.py app/routes/publications.py app/database/publications_attachments.py`.
- [ ] Subir imagen/pdf/video válidos → 200 con URL; subir `.exe` o imagen > 10 MB → 400.
- [ ] Crear una publicación con formato rico, imagen inline, tabla, botón, galería, video y un PDF adjunto → se guarda; el HTML persiste sanitizado; los adjuntos quedan con `publicationId` seteado.
- [ ] Abrir el detalle como empleado (rol USER) → se ve el contenido rico y la lista de adjuntos; el PDF descarga.
- [ ] Editar la publicación quitando un adjunto → ese adjunto queda `activo=0` y desaparece del detalle.
- [ ] Inyectar `<script>` / `onerror` en el contenido → eliminado por la sanitización (backend + DOMPurify).
- [ ] USER/Estadista no ven ni acceden a "Publicaciones"; ADMIN/RRHH sí (sidebar + navegación).
- [ ] Dark mode y responsive del formulario de autoría y del detalle rico.
- [ ] Una publicación vieja de texto plano se sigue viendo bien tras el cambio de render.

---

## Notas para el ejecutor

- **Backend sin pytest, frontend sin jest**: la "prueba" de cada task es la compilación (`py -m py_compile` / `npx tsc --noEmit`) más la verificación manual descrita. No agregar frameworks de test.
- **Orden de dependencias**: Tasks 1→2→3 (backend) son independientes de 4→10 (frontend) salvo que Task 8 consume 6 y 7, Task 9 consume 8, y Task 10 consume el tipo de Task 4. Ejecutar en orden numérico es seguro.
- **`immediatelyRender: false`** en `useEditor` es necesario en Next.js App Router (SSR) para evitar el error de hidratación de TipTap.
- **El archivo `UiRRHH.tsx`** tiene un cambio local no relacionado en el working tree del repo RRHH: NO incluirlo en ningún commit de este plan.
