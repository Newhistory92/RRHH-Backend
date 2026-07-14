# Portal Institucional — Núcleo de Publicaciones (subsistema 1)

## Contexto

Primer subsistema de un **Portal de Comunicación Institucional / Intranet** nuevo (no existe nada en el código hoy). El módulo completo será la pantalla de inicio tras el login y centraliza la comunicación institucional (noticias, circulares, resoluciones, avisos, eventos, etc.), mostrando a cada empleado solo lo relevante según su posición en el organigrama (departamento y oficina).

El módulo es grande y se descompone en 4 subsistemas independientes, en orden de dependencia:

1. **Núcleo de publicaciones** (este documento): modelo de datos, targeting por organigrama, CRUD de autoría para HR/Admin, y el endpoint de feed del empleado (filtrado en el backend). Editor de texto simple; sin adjuntos pesados; sin notificaciones.
2. **Portal del empleado (Home + UI/UX)**: la pantalla que reemplaza a "estadísticas" como default tras login (cards, sidebar con widgets, calendario institucional de solo lectura), marcar-como-leído, favoritos, notificaciones in-app. Diseño visual con la skill ui-ux-pro-max.
3. **Editor rich-text + adjuntos**: WYSIWYG tipo Word (imágenes, tablas, galerías, video, PDF, links/botones) e infraestructura de adjuntos que escale (no base64-en-DB).
4. **Búsqueda avanzada + dashboard admin**: búsqueda con filtros múltiples y estadísticas (total/activas/archivadas).

Orden confirmado: 1 → 2 → 3 → 4.

## Decisiones de diseño (confirmadas con el usuario)

1. **HR y Admin comparten el permiso de publicar**: cualquiera de los dos roles (ADMIN=1, RRHH=3) puede crear/editar/borrar publicaciones. No se toca el modelo de roles del backend; se usa el patrón existente `require_roles(ADMIN, RRHH)`. La distinción fina "Admin-only para categorías/configuración" del spec original se difiere (las 9 categorías son un set fijo, no administrable dinámicamente por ahora).
2. **Targeting con herencia hacia abajo**: dirigir una publicación al Departamento D alcanza a todos los empleados de D, incluidos los que están en cualquiera de sus oficinas; dirigir a la Oficina O alcanza solo a esa oficina; "toda la institución" alcanza a todos. La herencia sale del modelo existente sin lógica especial (un empleado de oficina también lleva su `departmentId`).
3. **Múltiples destinos por publicación**: una publicación puede apuntar a varios departamentos y/u oficinas a la vez (tabla hija `PublicationTarget`). El empleado la ve si pertenece a cualquiera de los destinos.
4. **Estado efectivo calculado por fecha** (sin cron): solo se persiste si la publicación es Borrador o Finalizada; Programada/Publicada/Archivada se derivan de `fechaPublicacion`/`fechaExpiracion` al consultar. Una publicación programada aparece sola al llegar su fecha y desaparece al expirar.
5. **El feed de lectura del empleado vive en este subsistema**: el subsistema 1 entrega un backend completo y testeable por API (crear → consultar como empleado X → verificar filtrado). El subsistema 2 queda como puro frontend + interacción.
6. **Target explícito obligatorio**: crear una publicación sin ningún destino devuelve 400; no hay default a "toda la institución" (un broadcast institucional accidental es peor que un error).

## A. Modelo de datos

Dos tablas nuevas, creadas idempotentemente vía `ensure_table` (patrón del proyecto: `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... IF COL_LENGTH(...) IS NULL` para columnas futuras).

### `Publication`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `titulo` | NVARCHAR(300) NOT NULL | |
| `resumen` | NVARCHAR(MAX) NULL | texto corto para las cards |
| `contenido` | NVARCHAR(MAX) NULL | cuerpo; texto plano ahora, HTML rico del WYSIWYG en el subsistema 3 (sin cambiar el tipo) |
| `categoria` | NVARCHAR(50) NOT NULL | una de las 9 fijas (validada en código) |
| `prioridad` | NVARCHAR(20) NOT NULL DEFAULT 'Normal' | Baja / Normal / Alta / Urgente |
| `estadoMantenimiento` | NVARCHAR(20) NULL | solo categoría Mantenimiento: Programado/En curso/Completado/Suspendido/Reprogramado |
| `esBorrador` | BIT NOT NULL DEFAULT 1 | único bit de ciclo de vida persistido |
| `destacada` | BIT NOT NULL DEFAULT 0 | featured |
| `fijada` | BIT NOT NULL DEFAULT 0 | pinned (default true si categoría = Aviso Importante) |
| `fechaPublicacion` | DATETIME2 NULL | cuándo se hace visible |
| `fechaExpiracion` | DATETIME2 NULL | cuándo se archiva (NULL = nunca) |
| `autorEmployeeId` | INT NULL | quién la creó |
| `activo` | BIT NOT NULL DEFAULT 1 | soft-delete (patrón EmployeeDocument) |
| `createdAt` | DATETIME2 NOT NULL | |
| `updatedAt` | DATETIME2 NOT NULL | |

### `PublicationTarget` (hija, 1:N)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `publicationId` | INT NOT NULL | FK lógica a `Publication.id` |
| `scope` | NVARCHAR(20) NOT NULL | `'institucion'` \| `'departamento'` \| `'oficina'` |
| `departmentId` | INT NULL | requerido si scope = departamento |
| `officeId` | INT NULL | requerido si scope = oficina |

### Categorías (set fijo, validado en código)

Noticia Institucional, Circular, Resolución, Mantenimiento y Reparaciones, Aviso Importante, Evento Institucional, Oportunidad Interna, Beneficio para Empleados, Comunicación de RRHH.

### Herencia depto→oficina

No requiere lógica especial. Como en el organigrama un empleado de oficina también lleva su `departmentId` (confirmado al construir el `PATCH /reubicacion/{id}/ejecutar` del subsistema 4 de Reubicación), targetear al Departamento D alcanza a los empleados de sus oficinas vía el match por `departmentId`. Targetear a la Oficina O alcanza solo `officeId=O`.

## B. Backend

Archivo nuevo `app/routes/publications.py`, registrado en `main.py`. Modelo de datos en `app/database/publications.py` (con `ensure_table`, `VALID_CATEGORIAS`, `VALID_PRIORIDADES`, `VALID_ESTADOS_MANTENIMIENTO`). SQL parametrizado, transacciones por endpoint.

### Autoría (`require_roles(ADMIN, RRHH)`)

- **`POST /publications`** — crea. Body: `{titulo, resumen, contenido, categoria, prioridad, estadoMantenimiento?, esBorrador, destacada, fijada, fechaPublicacion, fechaExpiracion, autorEmployeeId, targets: [{scope, departmentId?, officeId?}]}`. Inserta `Publication` + filas `PublicationTarget` en una sola transacción. Si `categoria = Aviso Importante` y `fijada` no viene explícito, se setea `fijada = true`.
- **`PUT /publications/{id}`** — edita. Reescribe el set de targets (borra los de esa publicación y reinserta, mismo patrón que las habilidades de departamentos/oficinas). 404 si no existe.
- **`DELETE /publications/{id}`** — soft-delete (`activo = 0`). 404 si no existe.
- **`GET /publications`** — listado admin: todas las publicaciones `activo=1` (todos los estados), con filtros opcionales `categoria` y `estado` (el `estado` filtra sobre el estado efectivo calculado). Cada publicación incluye su estado efectivo y sus targets.
- **`GET /publications/{id}`** — detalle de una publicación (para la pantalla de edición), con sus targets. 404 si no existe.

### Feed del empleado (`require_any_auth`)

- **`GET /publications/feed?employeeId=X`** — publicaciones visibles para ese empleado. Chequeo self-or-admin (un empleado solo pide su propio feed; Admin puede pedir cualquiera). Filtros combinados:
  1. **Estado**: `activo=1`, `esBorrador=0`, `fechaPublicacion <= GETDATE()`, `(fechaExpiracion IS NULL OR fechaExpiracion >= GETDATE())`.
  2. **Targeting**: existe un `PublicationTarget` con `scope='institucion'` **OR** (`scope='departamento'` AND `departmentId` = el del empleado) **OR** (`scope='oficina'` AND `officeId` = el del empleado). Se resuelve el `departmentId`/`officeId` del empleado con un `SELECT` a `Employee`.
  3. **Orden**: `fijada DESC`, luego `fechaPublicacion DESC`.

## C. Lógica de estado

Helper `_estado_efectivo(pub, ahora) -> str`, usado en el listado admin:
- `esBorrador = 1` → `'Borrador'`
- si no, `fechaPublicacion > ahora` → `'Programada'`
- si no, `fechaExpiracion IS NULL OR fechaExpiracion >= ahora` → `'Publicada'`
- si no → `'Archivada'`

## D. Validaciones (400 con mensaje claro, antes de tocar la DB)

- `titulo` vacío → 400.
- `categoria` fuera del set de 9 → 400.
- `prioridad` fuera de {Baja, Normal, Alta, Urgente} → 400.
- `estadoMantenimiento` presente en una categoría distinta de Mantenimiento, o con un valor fuera del set → 400.
- `targets` vacío → 400 (`"Debe indicar al menos un destino"`).
- `scope='departamento'` sin `departmentId`, o `scope='oficina'` sin `officeId`, o `scope` inválido → 400.
- `fechaExpiracion` anterior a `fechaPublicacion` → 400.

## Manejo de errores

- Todas las validaciones anteriores → 400 antes de tocar la DB.
- Publicación inexistente en `PUT`/`DELETE`/`GET {id}` → 404.
- Feed de otro empleado sin ser Admin → 403 (self-or-admin, patrón de reubicación/documentos).
- `POST`/`PUT` transaccionales (publicación + targets juntos, rollback si algo falla).
- El feed nunca rompe: un empleado sin depto/oficina asignada ve solo lo dirigido a "toda la institución".

## Fuera de alcance (otros subsistemas o futuro)

- La Home visual del empleado, cards, sidebar, calendario institucional, dark mode, responsive — subsistema 2.
- Marcar-como-leído, favoritos, notificaciones in-app — subsistema 2.
- Editor WYSIWYG y adjuntos (imágenes/PDF/video/galerías) — subsistema 3.
- Búsqueda avanzada con filtros múltiples y dashboard admin de estadísticas — subsistema 4.
- Distinción de permisos Admin vs HR para gestionar categorías/configuración — diferida (decisión 1).
- Integración de eventos con el calendario institucional — subsistema 2 (la categoría Evento se modela acá, pero su vista en calendario es del 2).
- Categorías administrables dinámicamente (crear/editar categorías) — fuera de alcance; son un set fijo.

## Testing

Sin suite automatizada en ninguno de los dos repos — verificación manual:

1. Backend compila (`py -m py_compile app/routes/publications.py app/database/publications.py`).
2. `POST /publications` sin título, con categoría inválida, con prioridad inválida, o sin targets → 400 en cada caso; con datos válidos → crea la publicación y sus targets.
3. `estadoMantenimiento` en categoría no-Mantenimiento → 400; en Mantenimiento con valor válido → OK.
4. Aviso Importante creado sin tocar `fijada` → queda `fijada=true`.
5. `GET /publications` (admin) lista con el estado efectivo correcto: `fechaPublicacion` futura → "Programada"; expirada → "Archivada"; borrador → "Borrador"; vigente → "Publicada".
6. Targeting: crear tres publicaciones (una a institución, una al Depto D, una a la Oficina O de D). `GET /publications/feed` como: empleado de otra área (ve solo la de institución); empleado directo de D (ve institución + D); empleado de la Oficina O (ve las tres — confirma herencia depto→oficina).
7. Una publicación programada (fecha futura) no aparece en el feed; al llegar su fecha aparece sola; pasada la expiración desaparece.
8. `DELETE` soft: la publicación deja de aparecer en feed y listado, sin borrarse físicamente.
9. Un USER (rol 2) no puede crear/editar/borrar (403); solo Admin/RRHH.
