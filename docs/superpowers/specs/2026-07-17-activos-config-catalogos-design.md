# Sistema de Activos — Configuración + catálogos (subsistema 1)

## Contexto

Primer subsistema del **Sistema Integral de Gestión de Activos Tecnológicos y Patrimoniales**, un módulo nuevo (no existe nada en el código hoy). El sistema completo inventaría equipos informáticos (PC como activo principal), componentes trazables, mobiliario, accesorios; gestiona asignaciones/cambios/reemplazos con trazabilidad y auditoría inalterable; y agrega garantías, vida útil, obsolescencia, modelos de PC + scoring, dashboards y búsqueda global. Reutiliza el organigrama existente del RRHH (`Department` → `Office` → `Employee`).

El sistema es grande y se descompone en 7 subsistemas, en orden de dependencia:

1. **Configuración + catálogos** (este documento): la metadata que todo lo demás referencia (categorías/taxonomía, fabricantes, proveedores, estados de activo). Sin activos todavía.
2. Activos base + ubicación + estados + imágenes (el inventario).
3. PCs compuestas + componentes trazables + cambios/reemplazos (usa `pc-part-dataset` para el catálogo de modelos).
4. Trazabilidad + auditoría inalterable + historial + transferencias + daños.
5. Garantías + vida útil + obsolescencia.
6. Modelos de PC + sistema de scoring.
7. Dashboards ejecutivo/inventario + búsqueda global inteligente.

Transversal (subsistema posterior): RBAC fino por módulo/acción. Arquitectura futura (móvil, escaneo QR, firma digital, Active Directory, agente de descubrimiento, Help Desk): fuera del build ahora; solo se cuida que el modelo de datos no la impida.

Orden confirmado: 1 → 7.

## Decisiones de diseño (confirmadas con el usuario)

1. **Mismos dos repos** (Backend_RRHH + RRHH), como una nueva familia de módulos que reutiliza el organigrama — igual que el Portal Institucional. No es un servicio separado.
2. **RBAC: arrancar con los 4 roles existentes.** La configuración es solo **ADMIN**; el RBAC fino (permisos por módulo/acción) se construye como subsistema posterior, cuando ya existan los módulos y acciones reales que proteger. No se puede diseñar bien "permisos por módulo/acción" antes de que existan los módulos.
3. **Taxonomía unificada: una sola entidad `ActivoCategoria` con campo `grupo`** (`Equipo` / `Componente` / `Accesorio` / `Mobiliario`), en vez de tres tablas separadas. Toda cosa inventariable es una Categoría; la vida útil y los flags de config cuelgan de ella. S2+ tratan todo como "activo con categoría" sin ramas especiales.
4. **`pc-part-dataset` se difiere a S3**, donde el catálogo de modelos de referencia (autocompletado) se consume de verdad. S1 solo define los ~20 tipos de componente como Categorías.
5. **Depto/oficina/personal no se recrean**: se reutiliza el organigrama existente del RRHH.

## A. Modelo de datos

Cuatro tablas de configuración, creadas idempotentemente (patrón `ensure_table` del proyecto: `IF NOT EXISTS ... CREATE TABLE`). Prefijo `Activo` para agrupar todo el módulo (la entidad principal `Activo` llega en S2).

### `ActivoCategoria` (taxonomía unificada)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(150) NOT NULL | ej. "CPU", "Memoria RAM", "PC", "Silla" |
| `grupo` | NVARCHAR(20) NOT NULL | `Equipo` / `Componente` / `Accesorio` / `Mobiliario` |
| `montableEnPC` | BIT NOT NULL DEFAULT 0 | true para componentes que se montan dentro de una PC |
| `requiereSerie` | BIT NOT NULL DEFAULT 0 | si el nº de serie es obligatorio para esta categoría |
| `vidaUtilAnios` | INT NULL | vida útil configurable (años); NULL = sin definir |
| `activo` | BIT NOT NULL DEFAULT 1 | soft-delete |
| `createdAt` | DATETIME2 NOT NULL | |
| `updatedAt` | DATETIME2 NOT NULL | |

**Seed inicial** (solo si la tabla está vacía):
- **Componentes** (grupo=`Componente`): CPU, Disipadores CPU, Placas Base, Memoria RAM, Almacenamiento, Tarjetas de Video, Gabinetes, Fuentes de Alimentación, Unidades Ópticas, Sistemas Operativos, Almacenamiento Externo, Tarjetas de Sonido, Adaptadores de Red Cableados, Adaptadores de Red Inalámbricos. Los internos (CPU, Placas Base, RAM, Almacenamiento, GPU, Fuentes, Disipadores, Unidades Ópticas, Tarjetas de Sonido, Adaptadores) con `montableEnPC=1`.
- **Equipos** (grupo=`Equipo`): PC, Monitor.
- **Accesorios** (grupo=`Accesorio`): UPS, Impresoras, Escáneres, Fotocopiadoras.
- Mobiliario y categorías extra se crean desde config (grupo=`Mobiliario` u otro).

### `ActivoFabricante`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(150) NOT NULL | |
| `activo` | BIT NOT NULL DEFAULT 1 | |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

### `ActivoProveedor`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(150) NOT NULL | |
| `contacto` | NVARCHAR(300) NULL | opcional (teléfono/email/persona) |
| `activo` | BIT NOT NULL DEFAULT 1 | |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

### `ActivoEstado`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(50) NOT NULL | |
| `codigo` | NVARCHAR(30) NOT NULL | código estable para los estados núcleo (ej. `disponible`, `asignado`) |
| `orden` | INT NOT NULL DEFAULT 0 | orden de presentación |
| `esCore` | BIT NOT NULL DEFAULT 0 | los 10 del enunciado: no se pueden borrar, solo desactivar/editar nombre |
| `activo` | BIT NOT NULL DEFAULT 1 | |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

**Seed** (esCore=1): Disponible, Asignado, En reparación, Dañado, En depósito, Prestado, En garantía, Dado de baja, Extraviado, Robado — con `codigo` estable y `orden` incremental.

*Nota:* "Vida útil" no es tabla aparte — vive como `vidaUtilAnios` en cada Categoría. "Tipos de mobiliario" son Categorías con grupo=`Mobiliario`, cubiertos por el mismo CRUD.

## B. Backend

Módulo de datos `app/database/activos_config.py` (las 4 tablas con `ensure_table` + seed idempotente + helpers de consulta, con `VALID_GRUPOS = {Equipo, Componente, Accesorio, Mobiliario}`). Router `app/routes/activos_config.py`, registrado en `main.py`. SQL parametrizado, transacciones por endpoint.

**CRUD por cada entidad** (Categoría, Fabricante, Proveedor, Estado), mismo patrón:

- **`GET /activos/config/categorias`** (y `/fabricantes`, `/proveedores`, `/estados`) — listado `activo=1`; categorías admite filtro opcional `?grupo=`. Protegido con **`require_any_auth`** (cualquier usuario autenticado los lee: son los selectores que S2+ consumen).
- **`POST /activos/config/{entidad}`** — crear (**ADMIN**).
- **`PUT /activos/config/{entidad}/{id}`** — editar (**ADMIN**). 404 si no existe.
- **`DELETE /activos/config/{entidad}/{id}`** — baja lógica (`activo=0`) (**ADMIN**). 404 si no existe.

**Seed idempotente:** al crear cada tabla, si está vacía se insertan las filas semilla. Solo siembra si está vacía; nunca duplica.

**Validaciones (400 antes de tocar la DB):**
- `nombre` vacío → 400.
- Categoría: `grupo` fuera de `VALID_GRUPOS` → 400; `nombre` duplicado (case-insensitive) dentro del mismo grupo entre categorías activas → 400.
- Estado: `DELETE` sobre un estado `esCore=1` → 400 (los 10 núcleo no se eliminan, solo se desactivan los custom; los core se editan pero no se borran).

## C. Frontend

**Nueva sección de sidebar "Activos"** (arranca la familia de módulos patrimoniales). En S1 tiene una sola entrada; los subsistemas siguientes agregan Inventario, Dashboards, etc. bajo la misma sección.

**Pantalla `screens/ActivosConfig/Screen.tsx`** — "Configuración de Activos", visible/accesible **solo ADMIN**. Organizada en **pestañas** (patrón PrimeReact ya usado en el proyecto):

- **Categorías** — tabla (nombre, grupo, montable, requiere serie, vida útil) + crear/editar (nombre, select de grupo, checkboxes `montableEnPC`/`requiereSerie`, input años) + baja. Filtro por grupo arriba.
- **Fabricantes** — tabla + crear/editar/baja (solo nombre).
- **Proveedores** — tabla + crear/editar/baja (nombre + contacto opcional).
- **Estados** — tabla (nombre, código, orden, núcleo) + crear/editar; los `esCore` sin botón de baja (no eliminables), los custom sí.

Cada pestaña consume su endpoint vía `apiClient`, con estados de carga/error/vacío habituales. Estilo "Orgánico Cálido" (tokens semánticos, dark mode automático), responsive.

**Ruteo/RBAC:**
- Nuevo valor `"activos-config"` en el union type `Page` (`Interfas/Interfaces.ts`).
- Entrada en `PAGE_CONFIG` (`util/rbac.ts`): sección `"Activos"`, `visibleFor`/`accessibleFor` = solo `[ROLE_ID.ADMIN]`, ícono lucide (ej. `Boxes`).
- `AppSidebar.tsx`: agregar `"Activos"` al `SECTION_ORDER` y el ícono al `ICON_MAP`.
- `page.tsx`: `case 'activos-config'`.

## Manejo de errores

- Validaciones → 400 con mensaje claro antes de tocar la DB; inexistente en `PUT`/`DELETE` → 404; escritura sin ser ADMIN → 403.
- Seed solo si la tabla está vacía (reinicios no duplican).
- Frontend: cada pestaña con estados de carga/error/vacío; fallo de una no rompe las demás.

## Fuera de alcance (otros subsistemas o futuro)

- La entidad `Activo`, ubicación, estados operativos, imágenes, barcode/QR — subsistema 2.
- Catálogo de modelos de componentes desde `pc-part-dataset` (autocompletado) — subsistema 3.
- Trazabilidad/auditoría/transferencias/daños — subsistema 4.
- Garantías y la lógica de obsolescencia que usa `vidaUtilAnios` — subsistema 5.
- Modelos de PC y scoring — subsistema 6; dashboards y búsqueda global — subsistema 7.
- RBAC fino por módulo/acción — subsistema posterior (por ahora config = ADMIN grueso).

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/activos_config.py app/database/activos_config.py`).
2. Primer arranque: las 4 tablas se crean y se siembran (los ~20 componentes, PC/Monitor/accesorios, los 10 estados). Reiniciar el server no duplica.
3. CRUD de cada entidad (crear/editar/baja) desde la pantalla; los listados reflejan los cambios.
4. Un no-ADMIN puede **leer** los config (para selectores) pero recibe 403 al **escribir**.
5. Un estado `esCore` no se puede eliminar (400/sin botón); uno custom sí.
6. Categoría con grupo inválido → 400; nombre duplicado en el mismo grupo → 400.
7. Dark mode y responsive de la pantalla de configuración.
