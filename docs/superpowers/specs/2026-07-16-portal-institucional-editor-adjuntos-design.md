# Portal Institucional — Editor rich-text + adjuntos (subsistema 3)

## Contexto

Tercer subsistema del Portal de Comunicación Institucional. El subsistema 1 ([2026-07-14-portal-institucional-nucleo-publicaciones-design.md](2026-07-14-portal-institucional-nucleo-publicaciones-design.md), mergeado) creó el modelo `Publication`/`PublicationTarget`, el CRUD de autoría (`POST`/`PUT`/`DELETE`/`GET /publications`) y el feed del empleado. El subsistema 2 ([2026-07-14-portal-institucional-home-empleado-design.md](2026-07-14-portal-institucional-home-empleado-design.md), mergeado) creó la Home del empleado (`screens/PortalInicio/Screen.tsx`) y el modal de detalle `Componentes/PortalInicio/PublicationDetailDialog.tsx`, que hoy renderiza `contenido` como **texto plano** (`whitespace-pre-wrap`).

Este subsistema reemplaza el texto plano por un **editor WYSIWYG rico** (formato, imágenes inline, tablas, botones/CTA, galerías, video subido) e **infraestructura de adjuntos** que escala sin base64 en la base de datos. Como parte necesaria, construye el **formulario de autoría de publicaciones**, que hasta ahora no existía en el frontend (el subsistema 1 fue backend-only).

Los 4 subsistemas del módulo: 1 (núcleo, hecho), 2 (Home empleado, hecho), **3 (este documento)**, 4 (búsqueda avanzada + dashboard admin).

## Hallazgo de contexto (verificado antes de diseñar)

- **No existe** formulario de autoría de publicaciones en el frontend. El backend `POST`/`PUT /publications` funciona y recibe `contenido` como string, pero ninguna pantalla lo consume hoy.
- **No hay** infraestructura de archivos: el único patrón existente es `EmployeeDocument`, que guarda **base64 en `NVARCHAR(MAX)`** — explícitamente descartado acá.
- **No hay** editor rich-text ni librería de formularios instalada. Stack frontend: PrimeReact, Radix, Tailwind, Zod, lucide-react.
- **No hay** servido de archivos estáticos en `main.py` (sin `StaticFiles`/`mount`).
- Auth de autoría: `require_roles(ADMIN, RRHH)` + JWT — reutilizable.

## Decisiones de diseño (confirmadas con el usuario)

1. **El subsistema 3 construye el formulario de autoría completo** (crear/editar una publicación) con el editor rich-text y los adjuntos como su núcleo. El *dashboard/listado admin* con búsqueda avanzada, filtros y estadísticas queda para el subsistema 4. El subsistema 3 incluye solo una **lista mínima** como punto de entrada al formulario.
2. **Almacenamiento en disco local + servido estático de FastAPI.** Los archivos van a `uploads/publications/` en el server; la DB guarda ruta + metadatos, nunca el binario. Descarta base64-en-DB.
3. **Alcance del editor: todo.** Formato (negrita/itálica/encabezados/listas/links), imágenes inline, adjuntos descargables, tablas, botones/CTA, galerías de imágenes, y video subido.
4. **Límites de subida** (validados en frontend y backend):
   - Imágenes (inline, galerías): 10 MB c/u — `jpg, png, webp, gif`.
   - Documentos (adjuntos descargables): 25 MB c/u — `pdf, docx, xlsx, pptx, txt, zip`.
   - Video (incrustado): 200 MB c/u — `mp4, webm`.
   - Fuera de tamaño o tipo → rechazo con 400 antes de escribir a disco.
5. **Librería del editor: TipTap** (headless, ProseMirror, React, MIT). Toolbar propio estilado con Tailwind/PrimeReact; nodos custom (botón, galería, video) como extensiones TipTap del repo.
6. **Sanitización de HTML obligatoria** en backend al guardar (allowlist) + DOMPurify en frontend al renderizar. El detalle pasa a renderizar HTML, así que la sanitización es defensa contra XSS almacenado.
7. **Sin cambio de esquema en `Publication`**: `contenido` sigue `NVARCHAR(MAX)`, ahora guarda HTML. Compatibilidad hacia atrás: las publicaciones viejas de texto plano se renderizan bien como HTML, sin migración.

## A. Backend — almacenamiento, modelo, endpoints

### A.1 Servido de archivos estáticos

En `main.py` se monta `StaticFiles` en `/uploads`, apuntando a `uploads/publications/` (creada al arrancar si no existe). URL pública directa: `GET /uploads/publications/<storedName>`. La carpeta `uploads/` se agrega a `.gitignore`.

### A.2 Nueva tabla `PublicationAttachment`

Creada idempotentemente vía `ensure_table` (patrón del proyecto). Una sola tabla para inline y descargables.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `publicationId` | INT NULL | se asocia al guardar la publicación; NULL mientras se redacta |
| `rol` | NVARCHAR(20) NOT NULL | `'inline'` (imagen/video/galería en el cuerpo) o `'adjunto'` (descargable al pie) |
| `fileName` | NVARCHAR(300) NOT NULL | nombre original que ve el usuario |
| `storedName` | NVARCHAR(300) NOT NULL | nombre en disco (`uuid4 + extensión`), nunca el nombre del usuario |
| `mimeType` | NVARCHAR(100) NOT NULL | |
| `sizeBytes` | BIGINT NOT NULL | |
| `url` | NVARCHAR(500) NOT NULL | ruta pública `/uploads/publications/<storedName>` |
| `orden` | INT NOT NULL DEFAULT 0 | orden de la lista de adjuntos descargables |
| `activo` | BIT NOT NULL DEFAULT 1 | soft-delete |
| `createdAt` | DATETIME2 NOT NULL | |

Constantes en el módulo de datos: `LIMITES_POR_TIPO` (mapa tipo→bytes máximos), `EXTENSIONES_PERMITIDAS`/`MIMES_PERMITIDOS` por categoría, `VALID_ROLES = {'inline', 'adjunto'}`.

### A.3 Endpoint de subida

`POST /publications/attachments` — multipart, `UploadFile` + campo `rol`. Protegido con `require_roles(ADMIN, RRHH)`.

- Valida **extensión + mime-type + tamaño** contra las tablas de límites. Fuera de rango o tipo no permitido → 400 con mensaje claro, **antes** de escribir a disco.
- Guarda en disco como `uuid4.ext`; inserta fila `PublicationAttachment` con `publicationId = NULL` y el `rol` recibido.
- Devuelve `{id, url, fileName, mimeType, sizeBytes}`.

El editor usa `url` para incrustar el nodo inline; el formulario usa la metadata para construir la lista de adjuntos descargables.

### A.4 Extensión de `POST`/`PUT /publications`

Sin cambio de esquema. Se agrega al body `attachmentIds: [int]` (los ids devueltos por A.3 que quedaron en uso: inline referenciados + adjuntos descargables). `contenido` ahora llega como HTML.

- **Al guardar**: `UPDATE PublicationAttachment SET publicationId = :id, activo = 1 WHERE id IN (:attachmentIds)`.
- **En `PUT`**: re-sincroniza — los adjuntos previamente asociados que ya no están en `attachmentIds` se marcan `activo = 0`.
- **Sanitización**: `contenido` pasa por un sanitizador con allowlist (`nh3`, binding de ammonia; alternativa `bleach`) antes de persistir. Allowlist cubre las etiquetas/atributos que produce TipTap (formato, `p`, `h1-h3`, `ul/ol/li`, `a[href]`, `img[src,alt]`, `table/thead/tbody/tr/td/th`, y los envoltorios de los nodos custom botón/galería/video con sus clases y `src`/`href`). Todo lo demás (`script`, handlers `on*`, `style` peligroso) se elimina.
- La asociación de adjuntos y el guardado de la publicación van en la **misma transacción**.

### A.5 Lectura

`GET /publications/{id}` y `GET /publications/feed` (sub 2) se extienden para incluir, por cada publicación, sus **adjuntos descargables** (`rol='adjunto'`, `activo=1`, ordenados por `orden`): array `adjuntos: [{id, fileName, url, mimeType, sizeBytes}]`. Las imágenes/video inline ya viven embebidos en el HTML de `contenido`, no se devuelven aparte. El listado admin `GET /publications` no necesita adjuntos (solo metadatos de fila).

### A.6 Borrado

`DELETE /publications/{id}` (soft-delete existente) además marca sus `PublicationAttachment` como `activo = 0`. Los archivos en disco no se borran físicamente en v1 (posible job de limpieza futuro) — se prioriza no romper referencias.

## B. Frontend — editor, formulario, ruteo

### B.1 Dependencias

Se agregan a `RRHH`: `@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-image`, `@tiptap/extension-link`, `@tiptap/extension-table` (+ `-table-row`, `-table-cell`, `-table-header`), y `dompurify` (+ `@types/dompurify`). Los nodos custom se definen en el repo.

### B.2 Componente editor `RichTextEditor.tsx`

En `Componentes/GestionPublicaciones/`. Envuelve TipTap con un **toolbar propio** estilado con Tailwind/PrimeReact (tokens "Orgánico Cálido"). Botones: negrita, itálica, encabezados, listas, link, insertar imagen, tabla, botón/CTA, galería, video. Al insertar imagen/galería/video sube el archivo vía `POST /publications/attachments` (rol `inline`) y con la `url` devuelta incrusta el nodo. Valida tamaño/tipo en el cliente **antes** de subir (feedback inmediato + evita round-trip). Emite el HTML actual vía `onUpdate` al formulario padre. Props: `{ value: string, onChange: (html: string) => void, onAttachmentUploaded: (id: number) => void }`.

### B.3 Nodos custom (extensiones TipTap)

Tres extensiones en archivos separados dentro de `Componentes/GestionPublicaciones/tiptap/`:
- **Botón/CTA** (`ButtonNode.ts`): renderiza un `<a>` estilizado como botón (texto + URL destino).
- **Galería** (`GalleryNode.ts`): set de imágenes subidas mostradas en grilla; en el detalle se ven con visor.
- **Video** (`VideoNode.ts`): `<video controls>` apuntando a la URL subida.

Cada nodo produce HTML con clases estables que la sanitización del backend permite y el render del detalle estila.

### B.4 Campo de adjuntos descargables `AttachmentsField.tsx`

Debajo del editor. Sube archivos (rol `adjunto`), los lista con ícono + nombre + tamaño, permite quitar y reordenar. Mantiene el array de `attachmentIds` (rol adjunto) que va al submit. Props: `{ attachments: AttachmentMeta[], onChange: (list: AttachmentMeta[]) => void }`.

### B.5 Formulario de autoría `screens/GestionPublicaciones/Screen.tsx`

Pantalla de crear/editar. Campos: título, resumen, categoría (las 9), prioridad, `estadoMantenimiento` (condicional a categoría Mantenimiento), **targeting** (institución / departamentos / oficinas, multi-select — reutiliza los endpoints de organigrama existentes para poblar las opciones), fechas de publicación y expiración, flags `destacada`/`fijada`/`esBorrador`, + `RichTextEditor` para `contenido` + `AttachmentsField`. Botón guardar: `POST` si es nueva, `PUT` si edita. Validaciones cliente (título no vacío, categoría/prioridad válidas, al menos un destino, expiración ≥ publicación) antes de mandar. Reutiliza `apiClient`.

### B.6 Punto de entrada mínimo

La misma pantalla `GestionPublicaciones` muestra, en modo listado, un botón "Nueva publicación" y una **tabla simple** (título, categoría, estado efectivo, fecha) alimentada por `GET /publications` (ya existe). Clic en fila → modo edición cargando `GET /publications/{id}`. Deliberadamente básica: sin filtros ni estadísticas (eso es del subsistema 4).

### B.7 Ruteo / RBAC

Nueva página `"gestion-publicaciones"` en `PAGE_CONFIG` (`util/rbac.ts`), `visibleFor` y `accessibleFor` solo **ADMIN y RRHH**; entrada en el sidebar con ícono (`lucide-react`, ej. `FileEdit`/`Newspaper`); `case 'gestion-publicaciones'` en `page.tsx`. USER y Estadista no la ven ni acceden. Se agrega `"gestion-publicaciones"` al union type `Page` en `Interfas/Interfaces.ts`.

## C. Frontend — render en el detalle (integración con Subsistema 2)

### C.1 `PublicationDetailDialog.tsx`

Deja de renderizar `contenido` como texto plano. Ahora renderiza **HTML sanitizado con DOMPurify** (doble defensa: backend ya sanitizó al guardar). Debajo del cuerpo, si la publicación trae `adjuntos` (rol descargable), muestra una sección **"Archivos adjuntos"** con ícono + nombre + tamaño + link de descarga. La `PublicationCard` no cambia (el `resumen` sigue siendo texto corto plano).

### C.2 Estilos del HTML renderizado

El contenido rico se muestra dentro de un contenedor con clases tipográficas coherentes con "Orgánico Cálido" (encabezados, listas, tablas, imágenes, botones, galerías, video), consistente en claro y oscuro. Se agrega el tipo `adjuntos` a la interfaz `FeedPublication` (o una interfaz de detalle) en `Interfas/Interfaces.ts`.

## Manejo de errores

- Subida que excede tamaño/tipo → 400 del backend con mensaje claro; el frontend muestra toast y no inserta el nodo.
- Fallo de red durante la subida → toast de error; el editor no incrusta nada roto.
- Guardar con `attachmentIds` que referencian archivos inexistentes o ajenos → se ignoran los ids inválidos, no rompe el guardado.
- Asociación de adjuntos + guardado de publicación en la misma transacción: si algo falla, no queda la publicación a medias.
- El detalle del empleado nunca rompe: una publicación sin adjuntos simplemente no muestra la sección; contenido vacío muestra el fallback existente.

## Seguridad

- Sanitización HTML en backend (allowlist) al guardar + DOMPurify en frontend al renderizar.
- Uploads: nombre en disco generado (`uuid4.ext`), nunca el nombre del usuario; validación de extensión + mime + tamaño; la carpeta servida no ejecuta código.
- Endpoints de subida y de autoría protegidos con `require_roles(ADMIN, RRHH)`; el feed/detalle sigue con `require_any_auth` self-or-admin del sub 1.

## Compatibilidad hacia atrás

Las publicaciones existentes con `contenido` en texto plano se renderizan correctamente como HTML (el texto queda como nodos de texto). Sin migración de datos.

## Fuera de alcance (subsistema 4 o futuro)

- Dashboard admin con búsqueda avanzada, filtros múltiples y estadísticas (total/activas/archivadas) — subsistema 4.
- Job de limpieza de archivos huérfanos en disco (uploads iniciados pero nunca asociados a una publicación guardada).
- Versionado/historial de publicaciones.
- Edición colaborativa en tiempo real (feature paga de TipTap, no requerida).
- Migración a cloud object storage (S3/Azure Blob) — el diseño con URL en DB deja la puerta abierta, pero no se implementa ahora.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile` de los archivos tocados).
2. Subir imagen/pdf/video válidos → 200 con URL; subir uno que excede tamaño o tipo no permitido → 400.
3. Crear una publicación con formato rico, imagen inline, tabla, botón, galería, video y un PDF adjunto → se guarda; el HTML persiste sanitizado; los adjuntos quedan asociados (`publicationId` seteado).
4. Abrir el detalle como empleado → se ve el contenido rico correctamente y la lista de adjuntos descargables; el PDF descarga.
5. Editar la publicación quitando un adjunto → ese adjunto queda `activo=0` y desaparece del detalle.
6. Intentar inyectar `<script>`/`onerror` en el contenido → queda eliminado por la sanitización (backend y/o DOMPurify).
7. USER/Estadista no ven ni acceden a "Gestión de Publicaciones"; ADMIN/RRHH sí.
8. Dark mode y responsive del formulario de autoría y del detalle rico.
9. Una publicación vieja de texto plano sigue viéndose bien tras el cambio de render.
