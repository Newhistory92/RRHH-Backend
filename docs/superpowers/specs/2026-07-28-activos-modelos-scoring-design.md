# Sistema de Activos — Modelos de PC de referencia + scoring (subsistema 6)

## Contexto

Sexto subsistema del **Sistema Integral de Gestión de Activos Tecnológicos y Patrimoniales**. Construye
sobre los subsistemas 1-4 (config/catálogos, activos base, PCs+componentes, trazabilidad — todos mergeados
en `main` de ambos repos).

Permite definir **modelos de PC de referencia** (ej. "Oficina Básica", "Diseño Gráfico") como conjuntos de
**umbrales mínimos** sobre las specs de los componentes, y **evaluar** cualquier PC del inventario contra
un modelo, obteniendo un **score** = porcentaje de requisitos cumplidos, con el detalle de qué cumple y
qué no.

El insumo de datos son las specs del catálogo `PCParts` (71.009 filas ya pobladas, integrado en el
subsistema 3). Verificado contra la DB real: las specs son **datos crudos por categoría**, no un puntaje
de rendimiento precalculado — de ahí que el scoring se construya sobre umbrales numéricos y no sobre un
"benchmark" inexistente. Ejemplos reales verificados:

| Categoría (PCParts) | Specs reales |
|---|---|
| `cpu` | `{"core_count":8,"core_clock":4.7,"boost_clock":5.2,"tdp":120,...}` |
| `memory` | `{"speed":[5,6000],"modules":[2,16],"cas_latency":36,...}` |
| `video-card` | `{"chipset":"Radeon RX 9060 XT","memory":16,"core_clock":2220,...}` |
| `internal-hard-drive` | `{"capacity":1000,"type":"SSD","interface":"M.2 PCIe 4.0 X4",...}` |
| `power-supply` | `{"wattage":750,"efficiency":"gold","modular":"Full",...}` |
| `motherboard` | `{"socket":"AM5","form_factor":"ATX","max_memory":256,"memory_slots":4,...}` |

**Nota:** el subsistema 5 (garantías + vida útil + obsolescencia) fue **descartado explícitamente por el
usuario**; se pasa directo de 4 a 6. Orden restante: **6 (este)** → 7 (dashboards + búsqueda global).

## Decisiones de diseño (confirmadas con el usuario)

1. **Modelo = umbrales mínimos por categoría** (no componentes de referencia exactos, ni puntajes curados
   a mano). Ej: "CPU ≥ 4 núcleos", "RAM ≥ 16 GB". Usa los campos numéricos que ya vienen en las specs del
   catálogo, sin requerir curar filas ni mantener tablas de puntajes.
2. **Score = porcentaje de umbrales cumplidos**, todos los requisitos pesan igual (no hay pesos por
   categoría). Simple de entender y de explicar al usuario final.
3. **Solo categorías montables en PC** (las ~14 de componentes internos que ya existen desde S1, incluido
   Almacenamiento). No se ponen umbrales sobre Monitor/Accesorios/Mobiliario.
4. **Se persiste el JSON crudo de specs** en el `Activo` al elegir un componente del catálogo (columna
   nueva `Activo.specsJson`). Sin esto no habría datos numéricos que comparar: hoy las specs solo se
   vuelcan como texto legible en `observaciones` (formato "Etiqueta: valor"), que no es parseable de forma
   confiable. La columna es aditiva y no cambia el comportamiento existente de `observaciones`.

## A. Modelo de datos

Dos tablas nuevas (patrón `ensure_table` idempotente del proyecto) + una columna nueva.

### `ActivoModeloPC` (el modelo de referencia)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(150) NOT NULL | ej. "Oficina Básica", "Diseño Gráfico" |
| `descripcion` | NVARCHAR(500) NULL | para qué perfil de puesto sirve |
| `activo` | BIT NOT NULL DEFAULT 1 | baja lógica |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

### `ActivoModeloRequisito` (los umbrales de cada modelo)

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `modeloId` | INT NOT NULL | FK lógica a `ActivoModeloPC` (sin FK física, igual que el resto del módulo) |
| `categoriaId` | INT NOT NULL | FK lógica a `ActivoCategoria` (debe ser `montableEnPC = 1`) |
| `campoSpec` | NVARCHAR(50) NOT NULL | clave dentro del JSON de specs, ej. `core_count`, `capacity` |
| `valorMinimo` | FLOAT NOT NULL | umbral mínimo requerido (> 0) |
| `createdAt` | DATETIME2 NOT NULL | |

Índice por `modeloId`. Un requisito = "componentes de esta categoría deben tener este campo ≥ este valor".

### `Activo.specsJson` (NVARCHAR(MAX) NULL) — columna nueva

Se agrega con `ALTER TABLE` idempotente (mismo patrón `IF COL_LENGTH(...) IS NULL` ya usado para
`Activo.pcPadreId` en S3). Guarda el JSON crudo de specs del `PCPart` elegido del catálogo al crear el
componente. Los componentes cargados a mano quedan con `specsJson = NULL` y se reportan como **"sin
datos"** en el scoring — nunca como incumplidos.

### `CAMPOS_SPEC_POR_CATEGORIA` (diccionario fijo en código, no tabla)

Declara qué campos numéricos son ofrecibles como umbral por cada categoría S1, con su unidad legible.
Derivado de las specs reales verificadas contra la DB:

| Categoría (S1) | Campos ofrecidos (clave → etiqueta, unidad) |
|---|---|
| CPU | `core_count` → Núcleos; `boost_clock` → Frecuencia turbo (GHz) |
| Memoria RAM | `modules` → Capacidad total (GB); `speed` → Velocidad (MHz) |
| Tarjetas de Video | `memory` → Memoria de video (GB) |
| Almacenamiento | `capacity` → Capacidad (GB) |
| Fuentes de Alimentación | `wattage` → Potencia (W) |
| Placas Base | `max_memory` → Memoria máxima (GB); `memory_slots` → Slots de memoria |

Las categorías sin entrada simplemente no ofrecen umbrales (el select de campo queda vacío y el formulario
lo impide). Ampliar la tabla en el futuro es agregar una entrada al diccionario, sin migración.

**Campos tipo par `[a, b]`:** en `memory`, `speed` y `modules` vienen como pares (ej. `"modules":[2,16]`
= 2 módulos de 16 GB → 32 GB totales... y `"speed":[5,6000]` = DDR5 a 6000 MHz). Regla explícita del
motor: para `modules` el valor evaluado es **el producto de ambos elementos** (cantidad × capacidad = GB
totales); para `speed` es **el segundo elemento** (la frecuencia). Para cualquier otro par futuro, el
segundo elemento. Los escalares (`core_count`, `capacity`, `wattage`, etc.) se usan tal cual.

## B. Backend

**Módulo de datos nuevo** `app/database/activos_modelos.py` (archivo propio: `activos.py` ya es grande y
esto es una responsabilidad distinta):
- `ensure_tables(db)` — crea las 2 tablas y asegura `Activo.specsJson` (ALTER idempotente, en batch
  separado del resto por la limitación de SQL Server ya conocida en este proyecto).
- `CAMPOS_SPEC_POR_CATEGORIA` — el diccionario de arriba.
- `listar_modelos(db)`, `obtener_modelo(db, id)` (modelo + requisitos con nombres de categoría resueltos),
  `crear_modelo`, `actualizar_modelo`, `baja_modelo`, `agregar_requisito`, `quitar_requisito`.
- `evaluar_pc(db, pc_id, modelo_id) -> dict` — el motor de scoring.

**Motor `evaluar_pc`:** por cada requisito del modelo, busca los componentes instalados en esa PC
(`pcPadreId = pc_id`) de la categoría del requisito; extrae el valor de `campoSpec` desde el `specsJson`
de cada uno aplicando la regla de pares de arriba; toma el **mejor valor** entre los componentes de esa
categoría (ej. si hay 2 discos, se evalúa el de mayor capacidad); compara contra `valorMinimo`.

Devuelve por requisito: `categoriaNombre`, `campoSpec`, `etiqueta`, `unidad`, `valorMinimo`, `valorReal`
(o `null`), y `estado` ∈ `cumple` / `no_cumple` / `sin_datos`. Y a nivel general: `total`, `cumplidos`,
`sinDatos`, y `score` = `cumplidos / (total - sinDatos) * 100` redondeado, o `null` si no hay ningún
requisito evaluable (nunca división por cero).

**Router nuevo** `app/routes/activos_modelos.py`, prefijo `/activos/modelos`, registrado en `main.py`.
Se registra **antes** que el router `/activos` de S2 para que `/activos/modelos/...` no sea capturado por
el path converter `/{activo_id}` de aquel.

| Endpoint | RBAC | Descripción |
|---|---|---|
| `GET /activos/modelos` | `require_any_auth` | Modelos activos + cantidad de requisitos |
| `GET /activos/modelos/campos` | `require_any_auth` | `CAMPOS_SPEC_POR_CATEGORIA` resuelto con ids/nombres de categoría reales, para poblar los selects |
| `GET /activos/modelos/{id}` | `require_any_auth` | Modelo + sus requisitos |
| `POST /activos/modelos` | ADMIN | Crear |
| `PUT /activos/modelos/{id}` | ADMIN | Editar nombre/descripción |
| `DELETE /activos/modelos/{id}` | ADMIN | Baja lógica |
| `POST /activos/modelos/{id}/requisitos` | ADMIN | Agregar requisito |
| `DELETE /activos/modelos/{id}/requisitos/{reqId}` | ADMIN | Quitar requisito |
| `GET /activos/modelos/evaluar/{pcId}?modeloId=` | `require_any_auth` | Evalúa esa PC contra el modelo |

Además, **`POST /activos` y `PUT /activos/{id}` (S2) aceptan un campo opcional `specsJson`** que se
persiste en la columna nueva. Cambio aditivo, retrocompatible: omitirlo deja la columna en `NULL`.

**Validaciones (400 antes de tocar la DB):**
- `nombre` vacío → 400; nombre duplicado entre modelos activos (case-insensitive) → 400.
- `categoriaId` inexistente o con `montableEnPC = 0` → 400.
- `campoSpec` no declarado en `CAMPOS_SPEC_POR_CATEGORIA` para esa categoría → 400.
- `valorMinimo` ausente, no numérico o ≤ 0 → 400.
- Requisito duplicado (misma categoría + mismo campo en el mismo modelo) → 400.
- Evaluar un activo cuya categoría no tiene `puedeAlbergarComponentes` → 400 (no es una PC).
- Modelo o PC inexistente → 404.

## C. Frontend

**Pantalla nueva "Modelos de PC"** (`src/app/screens/ActivosModelos/Screen.tsx`), visible/accesible solo
ADMIN, con entrada en el sidebar bajo la sección **"Activos"** que ya existe (S1) — se agrega
`"activos-modelos"` al union `Page`, a `PAGE_CONFIG` (`util/rbac.ts`), el ícono a `AppSidebar.tsx` y el
`case` en `page.tsx`.

Dos modos:
- **Lista**: modelos (nombre, descripción, cantidad de requisitos) + botón "Nuevo modelo" + baja.
- **Detalle**: datos del modelo (editables) + tabla de requisitos + formulario para agregar uno. Los
  selects son **encadenados**: elegir **Categoría** (solo las montables, desde
  `GET /activos/modelos/campos`) puebla **Campo** con las opciones válidas de esa categoría; se ingresa
  **Valor mínimo** y la unidad se muestra al lado. Imposible cargar una combinación inválida desde la UI.

**En la ficha de una PC** (`ActivosInventario/Screen.tsx`, dentro de la sección "Componentes instalados"
que ya existe): un selector **"Evaluar contra modelo"**. Al elegir uno se muestra debajo:
- El **score** como porcentaje grande + barra de progreso, con color semántico según nivel (tokens
  `success` / `warning` / `error` que ya existen en el proyecto).
- La **tabla de requisitos**: categoría, campo (etiqueta legible), mínimo pedido, valor real encontrado, y
  estado por fila (cumple / no cumple / sin datos), con la aclaración de cuántos quedaron sin evaluar.

**En el alta de componentes** (`ActivoForm.tsx` y el alta rápida dentro de `ActivosInventario/Screen.tsx`):
al elegir un componente del catálogo, además de precargar nombre/imagen/observaciones como hoy, se envía
el `specs` crudo en el nuevo campo `specsJson` del payload. Invisible para el usuario, es lo que habilita
el scoring.

Estilo "Orgánico Cálido" (tokens semánticos, dark mode, responsive), diálogos con el mismo patrón de
overlay del resto del módulo.

## Manejo de errores

- Validaciones → 400 claro antes de tocar la DB; inexistente → 404; escritura sin ser ADMIN → 403.
- Modelo sin requisitos → `score = null` + mensaje explicativo en la UI, nunca división por cero.
- Componente sin `specsJson`, con JSON corrupto, o sin la clave pedida → ese requisito se reporta
  **"sin datos"**, se excluye del denominador del score, y nunca lanza excepción.
- Valor no numérico dentro del JSON → mismo tratamiento "sin datos".
- Frontend: cada formulario/sección con error inline, sin `alert()`.

## Fuera de alcance (otros subsistemas o futuro)

- Recomendación automática de qué modelo corresponde a cada puesto/empleado.
- Sugerencias de upgrade ("cambiando esta RAM llegás al modelo X").
- Scoring de activos que no son PCs.
- Comparación directa entre dos PCs.
- Ranking/listado masivo de todas las PCs contra un modelo — territorio de **dashboards, subsistema 7**.
- Pesos por categoría (decidido: todos los requisitos pesan igual).
- Backfill de `specsJson` para componentes ya cargados antes de este subsistema (quedan "sin datos" hasta
  que se editen eligiendo del catálogo).
- Garantías / vida útil / obsolescencia — **subsistema 5, descartado explícitamente por el usuario**.
- RBAC fino por módulo/acción — sigue diferido; todas las escrituras son ADMIN grueso.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila; las 2 tablas nuevas y la columna `specsJson` se crean al arrancar; reiniciar no
   duplica ni falla.
2. Crear un modelo "Oficina Básica" con 3 requisitos (CPU ≥ 4 núcleos, RAM ≥ 8 GB, Almacenamiento ≥ 256 GB).
3. Los selects encadenados solo ofrecen campos válidos por categoría; forzar un `campoSpec` inválido vía
   API → 400.
4. Crear una PC con componentes **elegidos del catálogo** y evaluarla → el score refleja correctamente qué
   cumple y qué no, mostrando los valores reales (verificar especialmente que RAM `modules:[2,16]` se
   evalúe como 32 GB, no como 2 ni como 16).
5. Evaluar una PC con un componente cargado **a mano** → ese requisito aparece "sin datos", el score se
   calcula sobre el resto y la UI aclara cuántos no se evaluaron.
6. Modelo sin requisitos → mensaje claro, sin error ni división por cero.
7. Nombre de modelo duplicado / requisito duplicado (misma categoría+campo) → 400.
8. Evaluar un activo que no es PC → 400.
9. RBAC: un no-ADMIN ve modelos y evaluaciones pero recibe 403 al crear/editar/borrar.
10. Dark mode y responsive de la pantalla nueva y de la sección de evaluación en la ficha.
