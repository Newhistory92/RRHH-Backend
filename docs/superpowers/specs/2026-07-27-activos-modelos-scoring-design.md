# Sistema de Activos — Modelos de PC + sistema de scoring (subsistema 6)

## Contexto

Sexto subsistema del **Sistema Integral de Gestión de Activos Tecnológicos y Patrimoniales**. Construye
sobre los subsistemas 1-4 (config/catálogos, activos base, PCs+componentes, trazabilidad — los cuatro ya
mergeados en `main` de ambos repos). El **subsistema 5 (Garantías + vida útil + obsolescencia) se descarta
por decisión explícita del usuario** — no se implementa, y el campo `ActivoCategoria.vidaUtilAnios` (ya
existente desde S1) queda simplemente sin usar, sin que eso afecte a este subsistema.

Este subsistema agrega **modelos de PC de referencia** (perfiles de hardware esperado según el puesto,
ej. "Oficina Básica", "Diseño Gráfico") y un **motor de scoring** que evalúa qué tan bien una PC real
(compuesta de componentes instalados, subsistema 3) cumple los requisitos de un modelo, expresado como
porcentaje de umbrales cumplidos.

Orden del sistema completo (7 subsistemas): 1 Config ✅ → 2 Activos base ✅ → 3 PCs+componentes ✅ →
4 Trazabilidad ✅ → ~~5 Garantías/vida útil/obsolescencia (descartado)~~ → **6 Modelos de PC + scoring
(este)** → 7 Dashboards + búsqueda global.

## Decisiones de diseño (confirmadas con el usuario)

1. **Un modelo de PC se define por umbrales mínimos por categoría** (ej. CPU ≥ 4 núcleos, RAM ≥ 16 GB),
   no por componentes de catálogo exactos ni por un sistema de puntos curado a mano. Se apoya en los
   campos numéricos que ya trae el catálogo `PCParts` (verificado contra la base real: CPU tiene
   `core_count`/`boost_clock`/`tdp`; Memoria RAM tiene `speed`/`modules`; Tarjetas de Video tienen
   `memory`/`core_clock`; Almacenamiento tiene `capacity`; Fuentes tienen `wattage`; Placas Base tienen
   `max_memory`/`memory_slots`). Categorías sin campos numéricos útiles (ej. adaptadores de red) no
   ofrecen umbrales.
2. **El score es el porcentaje de umbrales cumplidos**, todos con el mismo peso — no hay ponderación por
   categoría.
3. **Los umbrales solo pueden aplicar sobre categorías montables en PC** (las mismas ~14 que ya se
   instalan dentro de una PC desde el subsistema 3), no sobre Monitor/Accesorios/Mobiliario.
4. **Se agrega `Activo.specsJson`** (columna nueva, nullable): guarda el JSON crudo de specs del `PCPart`
   elegido del catálogo al crear un componente. El scoring lee de acá, no de `observaciones` (que sigue
   siendo texto legible para humanos, sin cambios). Un componente cargado a mano (sin catálogo) queda con
   `specsJson = NULL` y sus requisitos correspondientes se reportan como "sin datos", nunca como
   incumplidos ni como error.

## A. Modelo de datos

Dos tablas nuevas (prefijo `Activo`, patrón `ensure_table` idempotente ya usado en todo el módulo) más una
columna nueva en `Activo`.

### `ActivoModeloPC`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `nombre` | NVARCHAR(150) NOT NULL | ej. "Oficina Básica", "Diseño Gráfico" |
| `descripcion` | NVARCHAR(500) NULL | para qué perfil de puesto sirve |
| `activo` | BIT NOT NULL DEFAULT 1 | soft-delete |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

### `ActivoModeloRequisito`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `modeloId` | INT NOT NULL | FK lógica a `ActivoModeloPC` |
| `categoriaId` | INT NOT NULL | FK lógica a `ActivoCategoria`, debe ser montable |
| `campoSpec` | NVARCHAR(50) NOT NULL | clave dentro del JSON de specs, ej. `core_count`, `capacity` |
| `valorMinimo` | FLOAT NOT NULL | umbral mínimo a cumplir |
| `unidad` | NVARCHAR(20) NULL | etiqueta para mostrar, ej. "GB", "MHz", "núcleos" |
| `createdAt` / `updatedAt` | DATETIME2 NOT NULL | |

### `Activo.specsJson` (columna nueva)

`NVARCHAR(MAX) NULL`, agregada con `ALTER TABLE` idempotente (`IF COL_LENGTH('Activo','specsJson') IS
NULL ...`, mismo patrón que `pcPadreId` en S3). Guarda el JSON crudo (`PCPart.specs`) del componente
elegido desde el catálogo al crearlo. Puramente aditivo: no reemplaza ni modifica `observaciones`.

### `CAMPOS_SPEC_POR_CATEGORIA` (diccionario fijo en código, no tabla)

Declara qué campos numéricos son ofrecibles como umbral por nombre de `ActivoCategoria`, con su unidad
legible y cómo extraer el valor (directo, o el segundo elemento si el campo es un par `[x, y]` como
`speed`/`modules` de Memoria RAM — verificado que el segundo elemento es el total relevante, ej. GB
totales de RAM):

```
"CPU": {"core_count": "núcleos", "boost_clock": "GHz", "tdp": "W"}
"Memoria RAM": {"speed[1]": "GB (total)", "modules[1]": "GB (total)"}   # ver nota abajo
"Tarjetas de Video": {"memory": "GB", "core_clock": "MHz"}
"Almacenamiento": {"capacity": "GB"}
"Fuentes de Alimentación": {"wattage": "W"}
"Placas Base": {"max_memory": "GB", "memory_slots": "slots"}
```

*Nota:* `speed` y `modules` en el catálogo son pares `[cantidad, valor]` (ej. `modules:[2,16]` = 2 módulos
de 16GB). El campo relevante para un umbral de "RAM total" es `modules[1]` (16, no 2). El backend expone
esto ya resuelto — el frontend no necesita saber de esta particularidad del dataset.

## B. Backend

**Módulo de datos nuevo** `app/database/activos_modelos.py` (archivo propio, separado de `activos.py` que
ya es grande):
- `ensure_tables(db)`: crea las 2 tablas + asegura `Activo.specsJson`.
- `CAMPOS_SPEC_POR_CATEGORIA`: el diccionario de la sección A.
- CRUD de `ActivoModeloPC` y `ActivoModeloRequisito`.
- `evaluar_pc(db, pc_id, modelo_id) -> dict`: el motor de scoring — por cada requisito del modelo, busca
  los componentes instalados de esa categoría en la PC (vía `pcPadreId`, ya existente desde S3), extrae el
  valor de `campoSpec` desde `specsJson` (aplicando la resolución de pares de la nota anterior), compara
  contra `valorMinimo`, y devuelve por requisito `{cumple: true|false|null, valorReal}` (`null` = sin
  datos). El score final es `cumplidos / evaluables * 100` (los "sin datos" no cuentan en el
  denominador); si no hay requisitos evaluables, devuelve `score: null` con un flag explicativo, nunca
  división por cero.

**Router nuevo** `app/routes/activos_modelos.py`, prefijo `/activos/modelos`:

| Endpoint | RBAC | Descripción |
|---|---|---|
| `GET /activos/modelos` | `require_any_auth` | Lista modelos con cantidad de requisitos |
| `GET /activos/modelos/campos` | `require_any_auth` | Devuelve `CAMPOS_SPEC_POR_CATEGORIA` (para poblar selects encadenados) |
| `GET /activos/modelos/{id}` | `require_any_auth` | Modelo + sus requisitos |
| `POST /activos/modelos` | ADMIN | Crear modelo |
| `PUT /activos/modelos/{id}` | ADMIN | Editar nombre/descripción |
| `DELETE /activos/modelos/{id}` | ADMIN | Baja lógica |
| `POST /activos/modelos/{id}/requisitos` | ADMIN | Agregar requisito |
| `DELETE /activos/modelos/{id}/requisitos/{reqId}` | ADMIN | Quitar requisito |
| `GET /activos/{pcId}/evaluacion?modeloId=` | `require_any_auth` | Evalúa esa PC contra el modelo → score + detalle |

Además, `POST /activos` (S2, ya existente) acepta un campo opcional `specsJson` en el body para
persistirlo al crear un componente. El frontend (Task de este mismo subsistema) lo completa
automáticamente cuando el componente se elige desde el buscador de catálogo — no requiere que el usuario
lo cargue a mano.

**Validaciones (400 antes de tocar la DB):**
- `nombre` de modelo obligatorio y no duplicado (case-insensitive) entre modelos activos.
- `categoriaId` de un requisito debe existir y tener `montableEnPC = 1`.
- `campoSpec` debe estar declarado en `CAMPOS_SPEC_POR_CATEGORIA` para la categoría elegida (400 si no).
- `valorMinimo` > 0.
- No se permiten dos requisitos con la misma `categoriaId` + `campoSpec` en un mismo modelo.
- Evaluar (`GET /{pcId}/evaluacion`) sobre un activo que no `puedeAlbergarComponentes` → 400.
- Modelo o PC inexistente → 404.

## C. Frontend

**Nueva pantalla "Modelos de PC"** (`screens/ActivosModelos/Screen.tsx`), visible/accesible solo ADMIN,
con entrada nueva en `PAGE_CONFIG` bajo la sección "Activos" ya existente en el sidebar:
- **Lista** de modelos (nombre, descripción, cantidad de requisitos) + botón "Nuevo modelo".
- **Detalle/edición**: datos del modelo + tabla de requisitos + formulario para agregar uno nuevo con
  **selects encadenados**: Categoría (solo montables) → Campo (poblado según `GET
  /activos/modelos/campos` filtrado por la categoría elegida) → Valor mínimo (con la unidad mostrada al
  lado, tomada del mismo catálogo de campos) — imposible cargar una combinación inválida desde la UI.

**En la ficha de una PC** (`screens/ActivosInventario/Screen.tsx`, dentro de la sección "Componentes
instalados" ya existente de S3): selector **"Evaluar contra modelo"**. Al elegir un modelo, se muestra:
- El **score** como porcentaje grande + barra de progreso, coloreada semánticamente (`success`/`warning`/
  `error`, tokens ya existentes) según el nivel.
- **Tabla de requisitos**: categoría, campo, mínimo pedido, valor real encontrado, ícono de estado por
  fila (✓ cumple / ✗ no cumple / — sin datos).
- Si el modelo no tiene requisitos evaluables, mensaje explicativo en vez de una barra vacía o un error.

**En el alta de componentes** (`ActivoForm.tsx` y el alta rápida dentro de `ActivosInventario/Screen.tsx`,
ambas de S3): al elegir un resultado del buscador de catálogo, además de precargar
nombre/imagen/observaciones (comportamiento ya existente), se guarda el `specs` crudo del `PCPart`
elegido en el nuevo campo `specsJson` del payload de creación — cambio invisible para el usuario, es lo
que habilita el scoring más adelante.

Sin más cambios de ruteo/RBAC que la nueva entrada de sidebar. Estilo "Orgánico Cálido" (tokens
semánticos, dark mode, responsive), diálogos con el mismo patrón de overlay ya usado en todo el módulo.

## Manejo de errores

- Validaciones → 400 con mensaje claro antes de tocar la DB; inexistente → 404; escritura sin ser ADMIN →
  403.
- Evaluar un modelo sin requisitos → respuesta con `score: null` y mensaje explicativo, nunca división
  por cero.
- Componente sin `specsJson` (cargado a mano) → ese requisito se reporta "sin datos" (`cumple: null`),
  **no** cuenta como incumplido ni resta al score — el score se calcula solo sobre requisitos evaluables,
  y la UI aclara cuántos quedaron sin evaluar.
- `specsJson` corrupto, o sin el `campoSpec` esperado → mismo tratamiento "sin datos", nunca una
  excepción no controlada.
- Evaluar un activo que no puede alojar componentes → 400.
- Frontend: cada formulario/sección con estados de carga/error/vacío; sin `alert()`.

## Fuera de alcance (otros subsistemas o futuro)

- Recomendación automática de qué modelo corresponde a cada puesto/empleado.
- Sugerencias de upgrade ("cambiá esta RAM para llegar al modelo X").
- Scoring de activos que no son PCs (Monitor, Mobiliario, Accesorios sueltos).
- Comparar dos PCs directamente entre sí.
- Ranking/listado masivo de todas las PCs evaluadas contra un modelo — territorio de dashboards
  (subsistema 7).
- Pesos distintos por categoría/requisito (ya definido: todos pesan igual).
- Subsistema 5 (garantías/vida útil/obsolescencia) — descartado por decisión del usuario, no se retoma
  acá ni se bloquea si se pidiera en el futuro.

## Testing

Sin suite automatizada — verificación manual:

1. Backend compila (`py -m py_compile app/routes/activos_modelos.py app/database/activos_modelos.py`).
2. Al arrancar: las 2 tablas nuevas y la columna `Activo.specsJson` se crean; reiniciar no duplica ni
   rompe.
3. Crear un modelo "Oficina Básica" con 3 requisitos (CPU ≥ 4 núcleos, RAM ≥ 8 GB, Almacenamiento ≥ 256
   GB) desde la pantalla nueva, con los selects encadenados funcionando.
4. Intentar un `campoSpec` inválido para la categoría vía API directa → 400.
5. Crear una PC con componentes elegidos **desde el catálogo** (así quedan con `specsJson`) y evaluarla
   contra el modelo → el score y el detalle por requisito reflejan correctamente los valores reales.
6. Evaluar una PC con al menos un componente cargado **a mano** (sin catálogo) → ese requisito aparece
   "sin datos", el score se calcula sobre el resto sin romperse.
7. Evaluar contra un modelo sin requisitos → mensaje explicativo, sin error.
8. Nombre de modelo duplicado / requisito duplicado (misma categoría+campo) → 400.
9. RBAC: un no-ADMIN puede ver modelos y evaluaciones, pero no crear/editar/borrar (403).
10. Dark mode y responsive de la pantalla "Modelos de PC" y de la sección de evaluación en la ficha.
