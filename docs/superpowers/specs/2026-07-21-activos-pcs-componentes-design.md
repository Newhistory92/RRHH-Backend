# Sistema de Activos — PCs compuestas + componentes trazables + cambios/reemplazos (subsistema 3)

## Contexto

Tercer subsistema del **Sistema Integral de Gestión de Activos Tecnológicos y Patrimoniales**. Construye
sobre el subsistema 2 (Activos base + ubicación + estados, ya mergeado en `main` de ambos repos): permite
componer una **PC** (que es un `Activo` con categoría "PC") a partir de **componentes** (que son otros
`Activo` de categorías montables — CPU, RAM, GPU, etc.), registrar qué componente está instalado en qué
PC, y gestionar cambios/reemplazos con auditoría, todo trazado en `ActivoHistorial` (la tabla de auditoría
que S2 ya escribe en cada mutación).

Se apoya en un catálogo de referencia **`PCParts`** que el usuario **ya tiene poblado** en la misma base de
datos que usa el backend (`ObraSocial`): **71.009 filas** con `id, category, name, image, specs` (specs es
un JSON de texto). Categorías del dataset (con volumen): memory (14.200), case (7.200), video-card (6.800),
internal-hard-drive (6.700), motherboard (5.300), monitor (5.300), keyboard (4.700), power-supply (3.700),
cpu-cooler (3.200), headphones (3.000), case-fan (3.000), mouse (2.900), cpu (1.500), external-hard-drive
(800), ups (800), speakers (400), wireless-network-card (400), optical-drive (300), thermal-paste (300),
wired-network-card (200), webcam (98), sound-card (77), fan-controller (64), os (62), case-accessory (8).
Es **solo lectura**: no se importa, migra ni escribe — es la misma DB, se consulta directo vía SQLAlchemy.

Orden del sistema completo (7 subsistemas): 1 Config+catálogos ✅ → 2 Activos base ✅ → **3 PCs+componentes
(este)** → 4 Trazabilidad/auditoría/transferencias/daños → 5 Garantías/vida útil/obsolescencia → 6 Modelos
de PC + scoring → 7 Dashboards + búsqueda global.

## Decisiones de diseño (confirmadas con el usuario)

1. **Composición vía `pcPadreId` en el mismo `Activo`** (no una tabla junction). Cada `Activo`-componente
   tiene un campo nullable `pcPadreId` que apunta al `Activo`-PC donde está instalado. Simple, reutiliza la
   tabla `Activo` tal cual; el historial de instalar/quitar/reemplazar se registra en `ActivoHistorial`
   igual que S2 ya hace con el cambio de responsable. El historial de instalaciones **pasadas** con fechas
   explícitas (que una tabla junction daría "gratis") queda para S4 (trazabilidad), leyendo `ActivoHistorial`.
2. **Autocompletado opcional desde `PCParts` al crear** (no selección obligatoria). Al elegir la
   `ActivoCategoria` de un componente montable, un buscador consulta `PCParts` filtrado por la categoría del
   dataset mapeada, y al seleccionar un resultado precarga nombre/imagen/specs en el formulario de alta de S2.
   El usuario puede ignorar el buscador y cargar todo a mano (soporta componentes que no estén en el dataset).
3. **Diálogo dedicado de "Reemplazar componente"** (además de agregar/quitar sueltos). Un solo diálogo pide
   "qué componente instalado sale" + "qué componente nuevo entra" y, en **una transacción**, quita uno e
   instala el otro, generando una sola fila de historial `reemplazo` que vincula ambos ids.
4. **Sin FK real a nivel DB** para `pcPadreId` (validación en la capa de app), consistente con el resto de
   `Activo` (`categoriaId`, `estadoId`, `responsable*` tampoco tienen FK física).
5. **Mapeo categoría→PCParts como diccionario fijo en código** (no tabla): ~16 pares fijos que no cambian
   dinámicamente.

## A. Modelo de datos

Sin tablas nuevas. Dos columnas nuevas, ambas con `ALTER TABLE` idempotente (patrón `IF COL_LENGTH('T','c')
IS NULL ALTER TABLE T ADD c ...` ya usado en el proyecto, p. ej. `departments.py`):

### `Activo.pcPadreId` (INT NULL)
Si está seteado, ese `Activo`-componente está instalado dentro del `Activo`-PC con ese id. NULL = componente
libre (o el activo no es un componente). Sin FK física.

### `ActivoCategoria.puedeAlbergarComponentes` (BIT NOT NULL DEFAULT 0)
Marca `1` para la categoría **"PC"** (sembrada en S1). Un `Activo` cuya categoría tiene este flag puede
alojar componentes. Se setea con un `UPDATE` idempotente al correr `ensure_columns` (solo la categoría cuyo
`nombre='PC'`). Evita hardcodear el string 'PC'; permite en el futuro marcar otra categoría (ej. "Servidor")
sin tocar código.

### `MAPEO_PCPARTS` (diccionario fijo en `app/database/activos.py`)
Mapea `ActivoCategoria.nombre` (S1) → `PCParts.category` (dataset):

```
"CPU": "cpu", "Memoria RAM": "memory", "Placas Base": "motherboard",
"Tarjetas de Video": "video-card", "Almacenamiento": "internal-hard-drive",
"Fuentes de Alimentación": "power-supply", "Disipadores CPU": "cpu-cooler",
"Gabinetes": "case", "Unidades Ópticas": "optical-drive",
"Tarjetas de Sonido": "sound-card", "Sistemas Operativos": "os",
"Adaptadores de Red Cableados": "wired-network-card",
"Adaptadores de Red Inalámbricos": "wireless-network-card",
"Monitor": "monitor", "Almacenamiento Externo": "external-hard-drive", "UPS": "ups"
```

Las categorías S1 sin entrada en el mapeo simplemente no ofrecen autocompletado (el buscador no aparece).

## B. Backend

**Módulo de datos** — extender `app/database/activos.py` (S2):
- `ensure_columns(db)`: agrega `Activo.pcPadreId` y `ActivoCategoria.puedeAlbergarComponentes` idempotentemente
  y marca `puedeAlbergarComponentes=1` en la categoría "PC". Se llama defensivamente en los endpoints nuevos
  (mismo patrón que `ensure_tables`).
- `MAPEO_PCPARTS`: el diccionario de arriba.
- Extender `_SELECT_ACTIVO`/`_fila_a_dict`: agregar `pcPadreId`, `pcPadreNombre` (self-LEFT-JOIN a `Activo`
  por `pcPadreId`), y `puedeAlbergarComponentes` (del JOIN a `ActivoCategoria`, ya presente).
- `listar_componentes_de(db, pc_id)`: activos vigentes con `pcPadreId=pc_id`, nombres resueltos.
- `componentes_libres(db, categoria_id=None)`: activos vigentes con `pcPadreId IS NULL`, de categoría
  `montableEnPC=1` (S1), que **no** sean ellos mismos una PC; filtro opcional por `categoriaId`.
- `buscar_pcparts(db, pcparts_category, texto, limit=20)`: `SELECT TOP :limit id, category, name, image, specs
  FROM PCParts WHERE category = :cat AND (:texto = '' OR name LIKE :q) ORDER BY name`. Siempre con límite.

**Router** — nuevos endpoints en `app/routes/activos.py` (prefijo `/activos`):

| Endpoint | RBAC | Descripción |
|---|---|---|
| `GET /activos/{id}/componentes` | `require_any_auth` | Componentes instalados en esa PC |
| `GET /activos/componentes-libres?categoriaId=` | `require_any_auth` | Componentes libres para instalar |
| `GET /activos/pcparts?categoria=&texto=` | `require_any_auth` | Autocompletado desde `PCParts`; `categoria` = nombre de la `ActivoCategoria`, resuelto internamente vía `MAPEO_PCPARTS` |
| `POST /activos/{id}/componentes` | ADMIN | Instala `{componenteId}` → `pcPadreId={id}`, historial `instalacion` en ambos activos |
| `DELETE /activos/{pcId}/componentes/{componenteId}` | ADMIN | Quita → `pcPadreId=NULL`, historial `desinstalacion` |
| `POST /activos/{id}/componentes/reemplazar` | ADMIN | `{saleComponenteId, entraComponenteId, observacion}` → en una transacción quita el que sale + instala el que entra + fila `reemplazo` con ambos ids |

Nota sobre orden de rutas: los paths estáticos/anidados (`/componentes-libres`, `/pcparts`, `/{id}/componentes`)
deben declararse cuidando no chocar con el `/{activo_id}` genérico de S2 — el `GET /{activo_id}` ya existente
debe seguir declarado **después** de las rutas estáticas nuevas, igual que ya se cuida `/buscar` antes de
`/{activo_id}`.

`GET /activos/pcparts` recibe `categoria` = el **nombre de la `ActivoCategoria`** (ej. "Memoria RAM"), y el
backend lo traduce a `PCParts.category` (ej. "memory") vía `MAPEO_PCPARTS` — el mapeo vive en un solo lugar
(el backend). Si la categoría no está en el mapeo, devuelve lista vacía (el frontend simplemente no muestra
resultados / no ofrece el buscador).

**Validaciones (400 antes de tocar la DB):**
- Instalar/quitar/reemplazar sobre un `Activo` cuya categoría **no** tiene `puedeAlbergarComponentes=1` → 400
  ("ese activo no es una PC / no puede alojar componentes").
- El componente a instalar: debe existir, estar vigente (`activo=1`), ser de categoría `montableEnPC=1`, y
  tener `pcPadreId IS NULL` (no instalado en otra PC) → 400 en cada caso con mensaje claro.
- No instalar una PC dentro de otra ni un activo dentro de sí mismo → 400.
- Reemplazar: `saleComponenteId` debe estar realmente instalado en esa PC (`pcPadreId = pcId`) → 400;
  `entraComponenteId` pasa las mismas validaciones que instalar.
- Activo/componente inexistente en cualquier endpoint → 404.

**Auditoría:** cada mutación escribe en `ActivoHistorial` dentro de la misma transacción (patrón S2):
- instalar: fila `instalacion` en el componente (`campo="pcPadre"`, `valorNuevo=pcId`) y una fila
  `componente_agregado` en la PC.
- quitar: fila `desinstalacion` en el componente (`valorAnterior=pcId`, `valorNuevo=NULL`).
- reemplazar: una fila `reemplazo` en la PC con `valorAnterior=saleComponenteId`, `valorNuevo=entraComponenteId`
  y la observación, más las filas de desinstalación/instalación de los componentes afectados.

## C. Frontend

**Tipos** (`Interfaces.ts`): extender `ActivoListItem` con `pcPadreId: number | null`,
`pcPadreNombre: string | null`, `puedeAlbergarComponentes: boolean`. Nuevo tipo
`PCPart { id: number; category: string; name: string; image: string | null; specs: string | null }`.

**Ficha del Activo** (`screens/ActivosInventario/Screen.tsx`, modo `ficha`):
- **Si el activo es una PC** (`puedeAlbergarComponentes`): nueva sección **"Componentes instalados"** — tabla
  (nombre, categoría, nº serie, estado) con:
  - botón **"Agregar componente"** → diálogo que lista `GET /activos/componentes-libres` (filtrable por
    categoría), al confirmar `POST /activos/{id}/componentes`.
  - botón **"Reemplazar"** → diálogo dedicado: select "sale" (uno de los instalados) + select "entra" (uno de
    los libres) + observación → `POST /activos/{id}/componentes/reemplazar`.
  - botón **"Quitar"** por fila → `DELETE /activos/{pcId}/componentes/{componenteId}`.
- **Si el activo es un componente instalado** (`pcPadreId`): línea **"Instalado en: {pcPadreNombre}"** con link
  que abre la ficha de esa PC.

**Formulario de alta/edición** (`Componentes/ActivosInventario/ActivoForm.tsx`, S2): cuando la categoría
elegida es `montableEnPC`, aparece un buscador opcional **"Buscar en catálogo"** que consulta
`GET /activos/pcparts?categoria={nombreCategoria}&texto=` con debounce. Al elegir un resultado, precarga
`nombre`, `imagenReferencial` (el `image` del PCPart) y vuelca `specs` en `observaciones`. Ignorarlo y cargar
a mano sigue funcionando (el buscador es aditivo, no obligatorio). El alta del componente se sigue haciendo
por el `POST /activos` normal de S2 — el componente queda como un `Activo` propio (nº inventario, serie, etc.).

**Sin ruteo/RBAC nuevo**: todo vive dentro de la pantalla "Inventario" de S2. No se toca `rbac.ts` /
`page.tsx` / `AppSidebar.tsx`.

Estilo "Orgánico Cálido" (tokens semánticos, dark mode automático), responsive. Los diálogos usan el mismo
overlay `fixed inset-0 bg-black/50` que el diálogo "Cambiar estado" de S2.

## Manejo de errores

- Validaciones → 400 con mensaje claro antes de tocar la DB; inexistente → 404; escritura sin ser ADMIN → 403.
- `ensure_columns` idempotente (reinicios no rompen ni duplican columnas ni re-marcan de más).
- `GET /activos/pcparts` **siempre** con `limit` (nunca devuelve las 14.200 filas de `memory` de golpe); con
  `texto` vacío devuelve los primeros N por nombre.
- Frontend: cada sección/diálogo con estados de carga/error/vacío; fallo del autocompletado no rompe el form
  (es opcional).

## Fuera de alcance (otros subsistemas o futuro)

- Historial de instalaciones **pasadas** con fechas explícitas / tabla junction / consultas ricas de
  trazabilidad — **S4** (leyendo `ActivoHistorial`).
- Transferencias entre ubicaciones, flujos de daños — **S4**.
- Garantías, vida útil, obsolescencia de PCs/componentes — **S5**.
- Modelos de PC de referencia + scoring/comparación — **S6**.
- Dashboards y búsqueda global — **S7**.
- Importar/escribir en `PCParts` (es solo lectura; ya está poblada).
- Detección automática de hardware (agente de descubrimiento) — futuro.
- RBAC fino por módulo/acción — subsistema posterior (por ahora escrituras = ADMIN grueso).

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/activos.py app/database/activos.py`).
2. `ensure_columns` agrega `pcPadreId` y `puedeAlbergarComponentes`, marca "PC" con el flag en `1`; reiniciar
   el server no duplica ni re-rompe.
3. Autocompletado: al elegir categoría "Memoria RAM" en el form, el buscador trae resultados de `memory`;
   al elegir uno, precarga nombre/imagen/specs; cargar a mano sigue funcionando.
4. Instalar un componente libre en una PC → aparece en "Componentes instalados"; en la ficha del componente
   aparece "Instalado en: {PC}"; se registran filas de historial en ambos.
5. Intentar instalar: un componente ya instalado / uno no-montable / una PC dentro de otra / un activo en sí
   mismo → 400 con mensaje claro.
6. Reemplazar: sale uno, entra otro, en una sola operación; fila de historial `reemplazo` con ambos ids;
   ambos componentes quedan en el estado correcto (`pcPadreId`).
7. Quitar un componente → vuelve a estar libre (`pcPadreId` NULL); fila `desinstalacion`.
8. RBAC: un no-ADMIN lee las secciones pero recibe 403 al instalar/quitar/reemplazar.
9. Dark mode y responsive de la ficha con la sección de componentes y de los tres diálogos.
