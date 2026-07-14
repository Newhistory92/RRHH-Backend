# Organigrama — Capacidad requerida por unidad

## Contexto

El organigrama del RRHH tiene dos niveles de unidad: **Departamentos** y **Oficinas** (una oficina siempre pertenece a un departamento). Hoy cada unidad tiene nombre, jefe, habilidades requeridas y empleados asignados, pero no hay noción de "cuánta gente necesita" esa unidad.

Esta feature agrega una **capacidad requerida** (número base configurable) a cada departamento y oficina, con feedback visual tipo **"2/4"** (asignados / requeridos) en el organigrama, y usa ese dato como un **parámetro adicional** en el motor de matching del módulo de Reubicación Inteligente (ya en producción): las unidades con vacantes se vuelven destinos más atractivos para una reubicación.

## Decisiones de diseño (confirmadas con el usuario)

1. **Ambos niveles**: la capacidad se carga en departamentos y en oficinas.
2. **Conteo de asignados**: el numerador de una unidad cuenta a **todos** los empleados de esa unidad — para un departamento, todos los `Employee.departmentId = X` (incluyendo los que además están en una oficina); para una oficina, los `Employee.officeId = Y`. Hay solapamiento esperado (alguien en una oficina cuenta en su oficina y en su departamento), porque la oficina es un subconjunto del departamento.
3. **Asignados calculado al vuelo**: el numerador **no se persiste**; se cuenta con `COUNT` de `Employee` en cada lectura. Es un dato derivable y ya disponible en los endpoints que traen empleados.
4. **Regla del tope (validación dura)**: la capacidad del departamento es el máximo total. `SUM(capacidadRequerida de las oficinas del depto) ≤ capacidadRequerida del departamento`. Si una operación la violaría, el backend rechaza con 400. El remanente (`capacidad_depto − suma_oficinas`) es el cupo de empleados directos del departamento (sin oficina).
5. **Capacidad en el matching como señal ponderada**: una unidad con vacantes puntúa más alto como destino; una llena puntúa bajo, pero igual puede recomendarse si es el mejor match (no es filtro duro). Pesos nuevos: 55% skills + 20% déficit de skills + 25% vacantes.
6. **NULL = neutro, pero obligatoria al crear**: las unidades existentes (que serán borradas y recreadas) no tienen capacidad → NULL → visual sin denominador y matching neutro. De acá en más, **crear** un departamento u oficina **exige** la capacidad (400 si falta). El NULL queda como red de seguridad para datos legacy, no como flujo normal.

## A. Modelo de datos

Se agrega una columna a dos tablas existentes:

| Tabla | Columna | Tipo | Notas |
|---|---|---|---|
| `Department` | `capacidadRequerida` | INT NULL | NULL = no configurada (legacy) |
| `Office` | `capacidadRequerida` | INT NULL | NULL = no configurada (legacy) |

Las tablas `Department`/`Office` son pre-existentes y no usan el patrón `ensure_table` de los módulos nuevos. Se agrega una función `ensure_capacity_columns(db)` en `app/routes/departments.py` con dos `ALTER TABLE ... IF COL_LENGTH(...) IS NULL` idempotentes (mismo patrón que usó reubicación para `observacion`), invocada al inicio de los endpoints que la necesitan. Sin migración de datos: las filas existentes quedan con `capacidadRequerida = NULL`.

El **numerador (asignados)** no es una columna: se calcula con `COUNT` de `Employee` por `departmentId` / `officeId`.

## B. Backend

Todo en `app/routes/departments.py` (y una extensión menor en `app/routes/rrhh.py`). SQL parametrizado, dentro de la transacción que ya maneja cada endpoint.

### Helpers nuevos

- `ensure_capacity_columns(db)`: agrega la columna `capacidadRequerida` a `Department` y `Office` idempotentemente.
- `validar_tope_departamento(db, dep_id, capacidad_depto, capacidad_oficina_nueva=None, office_id_excluir=None)`: calcula `SUM(capacidadRequerida)` de las oficinas del departamento (excluyendo `office_id_excluir` si se está editando esa oficina, e incluyendo `capacidad_oficina_nueva` si se está creando/editando una) y verifica que no supere `capacidad_depto`. Devuelve un error 400 con el mensaje `"La suma de las oficinas (N) supera la capacidad del departamento (M)"` si se viola.

### Endpoints afectados (todos ya existen, se extienden)

- **`POST /departments/`**: exige `capacidadRequerida` (400 `"La capacidad requerida es obligatoria"` si falta o es < 0). La persiste al crear el departamento.
- **`PUT /departments/{dep_id}`**: acepta `capacidadRequerida` (opcional en el body; si viene, la actualiza). Si viene, valida con `validar_tope_departamento` que no quede por debajo de la suma de las oficinas ya cargadas del depto.
- **`POST /departments/{dep_id}/offices`**: exige `capacidadRequerida` (400 si falta o < 0). Valida el tope contra el departamento antes de insertar.
- **`PUT /departments/office/{office_id}`**: acepta `capacidadRequerida`; si viene, valida el tope (excluyendo la propia oficina del `SUM` y sumando el valor nuevo).
- **`GET /departments/`**: agrega a cada departamento y a cada oficina los campos `capacidadRequerida` (el valor guardado, o null) y `asignados` (el `COUNT` de empleados de esa unidad). El endpoint ya trae los empleados de cada unidad, así que el conteo se deriva de ahí o con un `COUNT` directo.
- **`GET /rrhh/org-analysis-data`**: agrega `capacidadRequerida` y `asignados` a cada departamento y a cada oficina del payload, para alimentar el motor de matching.

## C. Motor de matching (frontend)

En `src/app/lib/reubicacion-matching-engine.ts`, la capacidad entra como un tercer factor. Los pesos pasan de 70/30 a:

- **`SKILL_MATCH_WEIGHT = 0.55`** (coincidencia de skills)
- **`DEFICIT_WEIGHT = 0.20`** (déficit de skills)
- **`CAPACITY_WEIGHT = 0.25`** (vacantes por capacidad)

El **factor de vacantes** de una oficina candidata: `clamp((capacidadRequerida − asignados) / capacidadRequerida, 0, 1)` — vacía (0/4) → 1, llena (4/4) → 0, a medias (2/4) → 0.5.

**Manejo del NULL**: si la oficina candidata no tiene `capacidadRequerida`, el factor de vacantes se omite y su peso (0.25) se redistribuye proporcionalmente entre skills (0.55) y déficit (0.20), preservando la relación entre ambos, de modo que una unidad sin capacidad configurada no queda ni penalizada ni favorecida. El score sigue siendo 0-100.

El `matchDetails` que alimenta a Gemini suma la info de capacidad (`vacantes`, `capacidad`), y el prompt permite (no obliga) que la explicación la mencione honestamente. El motor sigue 100% determinista; Gemini solo redacta. El orquestador `src/app/api/reubicacion-analysis/route.ts` no cambia (ya reenvía `departments` con sus oficinas desde `org-analysis-data`).

## D. Frontend (Organigrama)

### Carga del número (edición)

- `src/app/Componentes/Orgamograma/Componente/DepartmentFields.tsx`: agrega un `InputNumber` "Capacidad requerida (personas)" (min 0), enlazado a `formData.capacidadRequerida`.
- `src/app/Componentes/Orgamograma/Componente/OfficeFields.tsx`: mismo `InputNumber`.
- Obligatorio al crear: el submit valida que `capacidadRequerida` tenga valor antes de llamar al backend (además de la validación dura del backend).
- El valor viaja en el `formData` que ya arma el modal, sumándose al payload de los `POST`/`PUT` existentes.

### Feedback visual "X/Y"

Un badge chico en los componentes que muestran los datos de cada unidad (`DepartmentHeader.tsx`, `OfficesList.tsx`, `DepartmentInfo.tsx`), con color según el llenado:

- **Verde** = con cupo (asignados < requeridos, ej. 2/4)
- **Ámbar** = completo (asignados = requeridos, ej. 4/4)
- **Rojo** = sobre-asignado (asignados > requeridos, ej. 5/4)
- **Gris, sin denominador** = capacidad NULL (legacy, ej. solo "3")

Los campos `capacidadRequerida` y `asignados` se agregan a las interfaces TS del organigrama (`Department`/`Office` en `Interfas/Interfaces.ts`) y vienen del `GET /departments/` extendido.

### Manejo del error del tope

Si el backend rechaza por la regla del tope o por capacidad faltante, el modal muestra el mensaje del backend en un toast / mensaje de error sin cerrar el formulario, para que RRHH corrija el número.

## Manejo de errores

- Crear departamento/oficina sin `capacidadRequerida` (o < 0) → 400.
- `SUM(oficinas) > capacidad_depto` (al crear/editar oficina, o al bajar el tope del depto) → 400 con los números concretos.
- Unidad con `capacidadRequerida` NULL (legacy) → nunca rompe: visual sin denominador, matching neutro.
- Toda la validación en la transacción del endpoint (rollback si falla).
- Frontend: muestra el mensaje del backend en el modal sin cerrarlo.

## Fuera de alcance

- Capacidad denormalizada / contador persistido de asignados — se calcula al vuelo.
- Filtro duro que descarte unidades llenas en el matching — es señal ponderada, no filtro.
- Que el motor de IA recomiende activamente "hay que contratar" cuando todas las unidades están llenas — solo pondera vacantes existentes.
- Alertas/notificaciones automáticas cuando una unidad queda sobre-asignada — solo feedback visual.
- Capacidad por rol/skill dentro de una unidad (ej. "4 personas, de las cuales 2 con React") — la capacidad es un número plano de personas.

## Testing

Sin suite automatizada en ninguno de los dos repos — verificación manual:

1. Backend compila (`py -m py_compile app/routes/departments.py app/routes/rrhh.py`).
2. `POST /departments/` y `POST /{dep}/offices` sin capacidad → 400; con capacidad válida → crea OK.
3. Cargar oficinas cuya suma supere el tope del depto → 400; dentro del tope → OK.
4. Bajar la capacidad de un depto por debajo de la suma de sus oficinas → 400.
5. `GET /departments/` devuelve `capacidadRequerida` y `asignados` correctos por depto y oficina (el `asignados` refleja el `COUNT` real).
6. `GET /rrhh/org-analysis-data` incluye ambos campos por unidad.
7. Motor de matching: una oficina con vacantes (2/4) rankea más alto que una llena (4/4) a igual match de skills; una sin capacidad (NULL) no se ve afectada por el factor de vacantes.
8. Frontend: el `InputNumber` aparece y es obligatorio al crear; el badge "X/Y" se ve con el color correcto en depto y oficina; una unidad legacy muestra solo el conteo; el error del tope se ve en el modal sin cerrarlo.
9. End-to-end: cargar capacidades, correr "Analizar Solicitudes" en reubicación, y confirmar que la explicación de la IA puede mencionar las vacantes disponibles.
