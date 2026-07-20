# Sistema de Activos — Activos base + ubicación + estados (subsistema 2)

## Contexto

Segundo subsistema del Sistema Integral de Gestión de Activos. El subsistema 1 ([2026-07-17-activos-config-catalogos-design.md](2026-07-17-activos-config-catalogos-design.md), ya mergeado a `main`) creó la configuración: `ActivoCategoria` (taxonomía unificada con `grupo`, `montableEnPC`, `requiereSerie`, `vidaUtilAnios`), `ActivoFabricante`, `ActivoProveedor`, `ActivoEstado` (10 estados sembrados con `codigo`/`esCore`), con sus endpoints `/activos/config/*`.

Este subsistema construye la **entidad principal `Activo`** (el inventario en sí): datos obligatorios y opcionales, ubicación en el organigrama existente (depto/oficina/empleado responsable), estado operativo referenciando `ActivoEstado`, y una tabla de **historial/auditoría** que se escribe en cada mutación. Cubre PCs, mobiliario y accesorios de forma uniforme: todos son un `Activo` distinguido por su `categoriaId` y el `grupo` de esa categoría.

Los 7 subsistemas del sistema: 1 (config, hecho), **2 (este documento)**, 3 (PCs compuestas + componentes + `pc-part-dataset`), 4 (trazabilidad/consultas + transferencias + daños), 5 (garantías + vida útil + obsolescencia), 6 (modelos de PC + scoring), 7 (dashboards + búsqueda global).

## Decisiones de diseño (confirmadas con el usuario)

1. **Un único responsable por activo**, que puede ser una Oficina, un Departamento o un Empleado (una sola asignación, no los tres a la vez). Modela "quién tiene esto ahora" y es lo que la transferencia de S4 va a mover.
2. **S2 crea la tabla de historial/auditoría desde el arranque y escribe una fila por cada mutación** (crear, editar, cambio de estado, cambio de responsable, baja). S4 construye encima las consultas (historial por activo/persona/oficina/depto), la pantalla "Cambiar Responsable" y el flujo de daños. La escritura de la traza va con las mutaciones (S2); la lectura/flujos ricos van en S4 — sin huecos en la traza.
3. **Códigos**: `numeroSerie`, `codigoBarras`, `codigoQR` como campos de texto opcionales + búsqueda por código (`GET /activos/buscar`) para el "escanear → precargar". **Se genera QR y código de barras imprimibles en el cliente** (librerías JS), a partir del `numeroInventario`/`codigoBarras`, sin backend ni almacenamiento. El escaneo con cámara del celular queda para el futuro.
4. **Sin inventario fotográfico**: una sola `imagenReferencial` como URL de texto en el propio `Activo` (la imagen ya proviene de datos existentes del usuario). S2 no construye subida ni almacenamiento de imágenes.
5. **RBAC**: gestión de inventario = **ADMIN** (consistente con la config de S1). El RBAC fino por módulo/acción es subsistema posterior.
6. **Depto/oficina/empleado se reutilizan del organigrama existente** (`/departments/`, `/rrhh/employees`).

## A. Modelo de datos

Dos tablas nuevas, creadas idempotentemente (`ensure_tables`).

### `Activo`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `numeroInventario` | NVARCHAR(100) NOT NULL | único entre activos vigentes (`activo=1`) |
| `nombre` | NVARCHAR(300) NOT NULL | nombre / especificación |
| `categoriaId` | INT NOT NULL | → `ActivoCategoria` (S1) |
| `fabricanteId` | INT NULL | → `ActivoFabricante` (S1), opcional |
| `estadoId` | INT NOT NULL | → `ActivoEstado` (S1); al crear, default "Disponible" |
| `fechaAlta` | DATE NOT NULL | obligatorio |
| `anio` | INT NULL | opcional |
| `observaciones` | NVARCHAR(MAX) NULL | opcional |
| `imagenReferencial` | NVARCHAR(1000) NULL | URL, opcional |
| `numeroSerie` | NVARCHAR(200) NULL | opcional; obligatorio si la categoría tiene `requiereSerie=1` |
| `codigoBarras` | NVARCHAR(200) NULL | opcional |
| `codigoQR` | NVARCHAR(500) NULL | opcional |
| `responsableTipo` | NVARCHAR(20) NULL | `empleado` / `oficina` / `departamento` / NULL (sin asignar) |
| `responsableEmpleadoId` | INT NULL | → Employee (solo si tipo=empleado) |
| `responsableOficinaId` | INT NULL | → Office (solo si tipo=oficina) |
| `responsableDepartamentoId` | INT NULL | → Department (solo si tipo=departamento) |
| `activo` | BIT NOT NULL DEFAULT 1 | baja lógica (dato erróneo); distinto del **estado** "Dado de baja" (ciclo de vida) |
| `createdAt` | DATETIME2 NOT NULL | |
| `updatedAt` | DATETIME2 NOT NULL | |

### `ActivoHistorial`

Auditoría: se escribe en cada mutación de S2; **inmutable** (solo INSERT, nunca UPDATE/DELETE). S4 construye las consultas y flujos encima de esta misma tabla.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `activoId` | INT NOT NULL | |
| `accion` | NVARCHAR(30) NOT NULL | `creacion` / `modificacion` / `cambio_estado` / `cambio_responsable` / `baja` |
| `campo` | NVARCHAR(50) NULL | qué cambió (ej. `estado`, `responsable`, `nombre`); NULL en creación |
| `valorAnterior` | NVARCHAR(MAX) NULL | |
| `valorNuevo` | NVARCHAR(MAX) NULL | |
| `usuarioEmpleadoId` | INT NULL | quién lo hizo (del token) |
| `observacion` | NVARCHAR(500) NULL | motivo (ej. al cambiar de estado) |
| `createdAt` | DATETIME2 NOT NULL | |

**Responsable:** `responsableTipo` + las 3 columnas nullable (a lo sumo una seteada) — permite join directo a Employee/Office/Department en la ficha y en las consultas de S4. `responsableTipo=NULL` = sin asignar.

## B. Backend

Módulo de datos `app/database/activos.py` (las 2 tablas con `ensure_tables`, helper `_registrar_historial(...)`, y helpers de lectura con joins que resuelven nombres de categoría/estado/fabricante/responsable). Router `app/routes/activos.py` registrado en `main.py`. SQL parametrizado, transacciones por endpoint. Reutiliza `require_any_auth`, `require_roles(ROLE_ADMIN)`, `get_current_user` del middleware existente.

### Lectura (`require_any_auth`)

- **`GET /activos`** — listado con filtros opcionales (`categoriaId`, `grupo`, `estadoId`, `responsableTipo` + id, `texto` sobre nombre/nº inventario/serie). Cada activo con nombres resueltos (categoría, estado, fabricante, responsable). Excluye `activo=0`.
- **`GET /activos/{id}`** — ficha completa (todos los campos + nombres resueltos). 404 si no existe o `activo=0`.
- **`GET /activos/buscar?codigo=X`** — busca por `numeroInventario` / `codigoBarras` / `codigoQR` / `numeroSerie` (match exacto sobre activos vigentes); si hay match devuelve el activo, si no → 404.

### Escritura (`require_roles(ADMIN)`)

- **`POST /activos`** — crear. Valida obligatorios + serie-si-la-categoría-lo-exige + nº inventario único. Estado default "Disponible" (resuelto por `codigo='disponible'`) si no se manda. Escribe historial `creacion`.
- **`PUT /activos/{id}`** — editar. Detecta qué campos cambiaron respecto del valor actual y escribe un historial por cambio relevante: `cambio_estado` si cambió `estadoId`, `cambio_responsable` si cambió el responsable, `modificacion` (con `campo`/anterior→nuevo) para otros campos de negocio (nombre, categoría, etc.). 404 si no existe.
- **`PATCH /activos/{id}/estado`** — cambiar estado con `observacion`/motivo opcional; escribe historial `cambio_estado` (anterior→nuevo + observación). Endpoint dedicado porque es la mutación más frecuente y auditada. 404 si no existe.
- **`DELETE /activos/{id}`** — baja lógica (`activo=0`); escribe historial `baja`. 404 si no existe.

**Validaciones (400 antes de la DB):** `numeroInventario` vacío o duplicado entre activos vigentes; `categoriaId`/`estadoId`/`fabricanteId` inexistentes; `numeroSerie` faltante cuando la categoría tiene `requiereSerie=1`; `responsableTipo` inválido o sin el id correspondiente (ej. tipo=empleado sin `responsableEmpleadoId`); `fechaAlta` faltante.

**Auditoría:** `_registrar_historial` inserta la fila dentro de la misma transacción que la mutación (si algo falla, no queda la mutación sin su registro, ni al revés). El `usuarioEmpleadoId` sale del token (`get_current_user`). El valor "resuelto" que se guarda en `valorAnterior`/`valorNuevo` para estado/responsable es legible (ej. el nombre del estado, el nombre del responsable), no solo el id.

## C. Frontend

**Nueva entrada "Inventario"** en la sección de sidebar "Activos" (junto a "Configuración de Activos" de S1). Acceso **solo ADMIN** (consistente con la config; el RBAC fino que abra a otros roles es subsistema posterior).

**Pantalla `screens/ActivosInventario/Screen.tsx`** con tres modos (patrón de `GestionPublicaciones`):

- **Lista** — tabla (nº inventario, nombre, categoría, estado con color, responsable resuelto, fecha alta) + barra de filtros (categoría, grupo, estado, texto) + botón "Nuevo activo". Los dropdowns se pueblan de los selectores de S1 (`/activos/config/*`).
- **Ficha** (click en una fila) — vista de solo lectura: todos los datos, imagen referencial (por URL), responsable resuelto, y el **QR + código de barras generados en el cliente** (`qrcode` / `jsbarcode`, a partir del `numeroInventario`/`codigoBarras`, imprimibles). Botones "Editar" y "Cambiar estado". *(El historial completo y "Cambiar responsable" como flujo dedicado son S4; en S2 la ficha muestra los datos y permite editar.)*
- **Formulario** (crear/editar) — todos los campos: nº inventario, nombre, categoría (select), fabricante (select opcional), estado (select), fecha alta, año, observaciones, imagen referencial (URL), nº serie (marcado obligatorio si la categoría elegida tiene `requiereSerie`), códigos, y el **responsable** (selector de tipo empleado/oficina/departamento + el select correspondiente según el tipo, poblado del organigrama vía `/departments/` y `/rrhh/employees`).

**Registro por código:** en el formulario de alta, un campo "buscar por código" que llama `GET /activos/buscar?codigo=` — si ya existe, ofrece abrir ese activo; si no, sigue el alta normal.

**Cambiar estado:** un diálogo pequeño (select de estado + campo motivo) que llama `PATCH /activos/{id}/estado`.

Estilo "Orgánico Cálido" (tokens semánticos, dark mode automático), responsive. Ruteo/RBAC: nuevo `"activos-inventario"` en el union `Page` (`Interfas/Interfaces.ts`), entrada en `PAGE_CONFIG` (`util/rbac.ts`, sección "Activos", solo `[ADMIN]`), ícono lucide en `AppSidebar.tsx`, `case` en `page.tsx`.

**Dependencias nuevas (frontend):** `qrcode` y `jsbarcode`. Backend: ninguna nueva.

## Manejo de errores

- Validaciones → 400 con mensaje claro antes de tocar la DB; inexistente → 404; escritura sin ser ADMIN → 403.
- Mutación + fila de historial en la misma transacción (nunca una sin la otra).
- `GET /activos/buscar` sin match → 404 (el frontend lo interpreta como "código libre para el alta", no como error).
- Frontend: estados de carga/error/vacío en lista y ficha; fallo de un selector de config no rompe el formulario.

## Fuera de alcance (otros subsistemas o futuro)

- Historial consultable (por activo/persona/oficina/depto), "Cambiar Responsable" como flujo dedicado, gestión de daños con evidencia — subsistema 4. *(S2 ya escribe las filas de historial; S4 las lee y agrega los flujos.)*
- PCs compuestas + componentes montados + catálogo de modelos desde `pc-part-dataset` — subsistema 3.
- Garantías, vida útil aplicada, obsolescencia — subsistema 5. Modelos de PC + scoring — subsistema 6. Dashboards + búsqueda global avanzada — subsistema 7.
- Escaneo con cámara del celular, impresión masiva de etiquetas, firma digital — futuro.
- RBAC fino por módulo/acción — subsistema posterior (por ahora inventario = ADMIN).
- Reglas de máquina de estados (ej. auto-setear "Asignado" al asignar responsable) — S2 mantiene estado y responsable como campos independientes; el refinamiento de reglas queda para más adelante.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/activos.py app/database/activos.py app/main.py`).
2. Primer arranque: las 2 tablas se crean. Crear un activo → aparece en la lista, con estado default "Disponible" y una fila `creacion` en `ActivoHistorial`.
3. Crear un activo de una categoría con `requiereSerie=1` sin nº de serie → 400; con serie → OK.
4. Nº inventario duplicado (entre activos vigentes) → 400.
5. Editar un activo cambiando estado y responsable → se escriben las filas de historial correctas (anterior→nuevo, con valores legibles).
6. `PATCH .../estado` con motivo → historial `cambio_estado` con la observación.
7. `GET /activos/buscar?codigo=` con un código existente → devuelve el activo; inexistente → 404.
8. Ficha: QR y código de barras se generan y se ven; imagen referencial (URL) se muestra.
9. Responsable: asignar a empleado / oficina / departamento y ver el nombre resuelto en lista y ficha.
10. Un no-ADMIN no ve "Inventario" ni puede escribir (403); puede leer (`GET`) para selectores.
11. Dark mode y responsive.
