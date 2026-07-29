# Spec: Modelo de PC asignado + scoring persistente (subsistema 7)

## Contexto

El subsistema 6 implementó modelos de PC de referencia y un motor de scoring
on-demand: el usuario abre la ficha de una PC, elige un modelo del dropdown,
y ve el score. Pero al cerrar la ficha el modelo elegido se pierde — no queda
registrado cuál modelo debe cumplir esa PC. El subsistema 7 cierra ese gap:
cada PC puede tener un modelo de referencia asignado de forma persistente, y
el score se calcula y muestra automáticamente.

## Objetivo

1. Persistir qué modelo de referencia le corresponde a cada PC.
2. Mostrar el score automáticamente al abrir la ficha de una PC que tiene
   modelo asignado, sin que el usuario tenga que elegirlo cada vez.
3. Mostrar un indicador de score en el listado del inventario para las PCs
   que tienen modelo asignado (visión de un vistazo).

## Diseño técnico

### Backend

**Columna nueva: `Activo.modeloId INT NULL`**
- FK lógica a `ActivoModeloPC.id`. Solo aplica a PCs (`puedeAlbergarComponentes=1`).
- Se agrega idempotentemente en `ensure_tables` de `activos_modelos.py`
  (mismo patrón que `specsJson`: ALTER en su propio batch + commit).

**`_SELECT_ACTIVO` ampliado**
- Agregar `a.modeloId` y un LEFT JOIN a `ActivoModeloPC m ON a.modeloId = m.id`
  para resolver `m.nombre AS modeloNombre`.
- `_fila_a_dict` incluye `modeloId` y `modeloNombre`.

**Endpoint `PATCH /activos/{activo_id}/modelo`** (ADMIN)
- Body: `{ modeloId: int | null }`
- Valida que el activo es una PC (`puedeAlbergarComponentes`).
- Si `modeloId` no es null, valida que el modelo existe y está activo.
- Escribe `UPDATE Activo SET modeloId = :m, updatedAt = :now WHERE id = :id`.
- Registra historial: accion `"cambio_modelo"`, campo `"modelo"`,
  valorAnterior = nombre viejo (o null), valorNuevo = nombre nuevo (o null).
- Devuelve `{ message, evaluacion }` donde `evaluacion` es el resultado de
  `evaluar_pc(db, activo_id, modeloId)` si modeloId no es null, else null.

**Endpoint `GET /activos/{activo_id}` enriquecido**
- Si el activo es PC y tiene `modeloId`, el response incluye un campo
  `evaluacion` con el resultado de `evaluar_pc`. Si no tiene modelo,
  `evaluacion` es null.

**Endpoint `GET /activos` enriquecido (listado)**
- Incluir `modeloId`, `modeloNombre` en cada fila (ya viene del JOIN).
- Incluir un `score: int | null` calculado para PCs con modelo. Para
  eficiencia, calcular desde SQL con un subquery o hacerlo en Python
  post-query solo para las PCs que tienen modeloId (son pocas).

### Frontend

**Interfaces.ts**
- `ActivoListItem`: agregar `modeloId: number | null`, `modeloNombre: string | null`,
  `score: number | null`.

**ActivosInventario/Screen.tsx — Ficha de PC**
- Al abrir ficha (`abrirFicha`): si `det.modeloId`, setear `modeloEvalId`
  al modelo asignado y disparar evaluación automática.
- Cambiar el dropdown "Evaluar contra modelo" para que al seleccionar un
  modelo, haga `PATCH /activos/{id}/modelo` y persista la elección.
  Opción vacía ("— Sin modelo —") desasigna.
- Indicar visualmente cuál es el modelo asignado vs evaluación ad-hoc.

**ActivosInventario/Screen.tsx — Listado**
- En la tabla de PCs, agregar una columna "Score" que muestre el badge
  con el porcentaje coloreado (verde ≥80, amarillo ≥50, rojo <50).
- Si no tiene modelo asignado, mostrar "—".

**ActivoForm.tsx (crear/editar PC)**
- Si la categoría es PC, mostrar un select de modelo de referencia (opcional).
- Enviar `modeloId` en el payload de creación/edición.

**Historial**
- Agregar etiqueta para `cambio_modelo` en `etiquetaHistorial`.

## Seguridad

- SQL 100% parametrizado.
- RBAC: lectura cualquier autenticado, escritura ADMIN.
- La asignación de modelo se registra en historial de auditoría.

## Fuera de alcance

- Dashboard de fleet scoring (vista global de todas las PCs con sus scores).
- Notificaciones cuando el score cae por debajo de un umbral.
- Score persistido en tabla separada (se calcula on-the-fly, que es suficiente
  con el volumen actual).
