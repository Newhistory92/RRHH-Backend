# Módulo de Reubicación — Ejecución en el organigrama (subsistema 4)

## Contexto

Cuarto y último subsistema del módulo de Reubicación Inteligente. Los tres anteriores ya están implementados y mergeados a `main`:

- **Subsistema 1** ([2026-07-02-reubicacion-solicitud-empleado-design.md](2026-07-02-reubicacion-solicitud-empleado-design.md)): tabla `SolicitudReubicacion`, creación por el empleado, historial propio. Nace en `Pendiente`.
- **Subsistema 2** ([2026-07-03-reubicacion-tablero-rrhh-design.md](2026-07-03-reubicacion-tablero-rrhh-design.md)): tablero de RRHH (Kanban/tabla con los 6 estados), aprobar/rechazar con notificación y `observacion`.
- **Subsistema 3** ([2026-07-03-reubicacion-motor-ia-design.md](2026-07-03-reubicacion-motor-ia-design.md)): motor de análisis IA que recomienda destino + score + explicación; RRHH puede overridear el destino al aprobar. Agregó las columnas `officeIdSugerido`, `departmentIdSugerido`, `scoreCompatibilidad`, `explicacionIA`, `beneficios`, `riesgos`, `officeIdDestino`, `departmentIdDestino`.

Este subsistema cierra el ciclo: cuando una solicitud está `Aprobada`, RRHH la **ejecuta** — se mueve al empleado a su nueva oficina/departamento en el organigrama (tabla `Employee`), se le reasigna el jefe directo, y la solicitud pasa a `Ejecutada`. Es el único subsistema que produce el estado `Ejecutada` y el único que modifica el organigrama.

## Decisiones de diseño (confirmadas con el usuario)

1. **Paso manual separado de la aprobación**: aprobar deja la solicitud en `Aprobada` (subsistema 2, sin cambios); ejecutar es una acción posterior y explícita de RRHH. El modelo ya distingue `Aprobada` de `Ejecutada` como estados separados — ese espacio intermedio permite coordinar la mudanza (fecha, avisos) antes de aplicarla.
2. **Ejecución por solicitud individual** (no batch): a diferencia del análisis IA del subsistema 3 (cálculo sin efecto real), ejecutar mueve físicamente a una persona, y cada traslado tiene su propio momento acordado. Cada tarjeta `Aprobada` tiene su botón "Ejecutar".
3. **Destino definible al ejecutar**: si la solicitud se aprobó "a ciegas" (sin pasar por IA ni elegir destino, `officeIdDestino` NULL), el diálogo de ejecución exige elegir la oficina destino en ese momento. Si ya tiene destino guardado, viene pre-cargado y editable.
4. **Reasignar `managerId`**: al mover al empleado, se le asigna como jefe directo el `jefeId` de la oficina destino.
5. **Sin jefe en el destino → `managerId` NULL**: si la oficina destino no tiene `jefeId` (o el jefe sería el propio empleado), se limpia el `managerId` en vez de arrastrar el jefe anterior (obsoleto tras la mudanza).
6. **Notificar al empleado**: la ejecución inserta un `Message` activo (mismo patrón que los subsistemas 1-3), avisando que su reubicación se hizo efectiva.

## Arquitectura y flujo

Un endpoint nuevo en el backend, `PATCH /reubicacion/{id}/ejecutar`, separado del `/estado` existente (que solo maneja Aprobada/Rechazada). La UI vive en el mismo tablero (`ReubicacionTablero/Screen.tsx`). No hay motor de IA ni Next.js API route en este subsistema — es una operación transaccional directa contra el backend.

Flujo al hacer click en "Ejecutar":

1. Frontend abre un diálogo con un dropdown de oficina destino (pre-cargado con `officeIdDestino` si existe, vacío si no). "Confirmar" queda deshabilitado hasta que haya una oficina seleccionada.
2. Al confirmar → `PATCH /reubicacion/{id}/ejecutar` con `{officeId}`. **Solo se envía la oficina**; el departamento y el jefe los deriva el backend a partir de la oficina (no se confía en el cliente, para evitar inconsistencias).
3. El backend, en una sola transacción:
   a. Valida que la solicitud exista (404) y esté en `Aprobada` (400 si no).
   b. Valida que venga `officeId` (400 si falta).
   c. Busca la oficina destino → su `departmentId` y `jefeId` (404 si la oficina no existe).
   d. Calcula `managerId` = `jefeId` de la oficina, o NULL si el jefe es NULL o es el propio empleado.
   e. `UPDATE Employee` con `officeId`, `departmentId`, `managerId`.
   f. `UPDATE SolicitudReubicacion` a `Ejecutada`, persistiendo `officeIdDestino`/`departmentIdDestino`.
   g. `INSERT INTO Message` para el empleado.
   h. `commit`, devuelve `{"message": "Reubicación ejecutada", "estado": "Ejecutada"}`.

## A. Modelo de datos

**Sin cambios de esquema.** Todas las columnas necesarias (`officeIdDestino`, `departmentIdDestino`) ya existen desde el subsistema 3 y se crean/migran idempotentemente en `ensure_table()`. Este subsistema solo lee y escribe columnas existentes.

Cambios por `UPDATE` (no `ALTER`) al ejecutar:
- `SolicitudReubicacion`: `estado = 'Ejecutada'`, `officeIdDestino`/`departmentIdDestino` (se llenan si venían NULL de una aprobación a ciegas), `updatedAt`.
- `Employee`: `officeId`, `departmentId`, `managerId`.

## B. Backend

`PATCH /reubicacion/{solicitud_id}/ejecutar` (`require_rrhh_auth`), nuevo, al final de `app/routes/reubicacion.py`.

Body: `{"officeId": int}` (obligatorio).

Lógica:
1. `ensure_table(db)`.
2. Buscar la solicitud (`SELECT id, employeeId, estado FROM SolicitudReubicacion WHERE id = :id`) → 404 si no existe.
3. Validar `estado == 'Aprobada'` → 400 (`"Solo se pueden ejecutar solicitudes en estado 'Aprobada'"`). Previene doble ejecución y ejecutar estados no aprobados.
4. Validar `officeId` presente → 400 (`"Debe indicar la oficina destino para ejecutar"`).
5. Buscar oficina destino (`SELECT id, departmentId, jefeId, nombre FROM Office WHERE id = :officeId`) → 404 si no existe.
6. `manager_id = office["jefeId"] if office["jefeId"] and office["jefeId"] != solicitud["employeeId"] else None`.
7. `UPDATE Employee SET officeId=:officeId, departmentId=:deptId, managerId=:managerId WHERE id=:employeeId`.
8. `UPDATE SolicitudReubicacion SET estado='Ejecutada', officeIdDestino=:officeId, departmentIdDestino=:deptId, updatedAt=:now WHERE id=:id`.
9. `INSERT INTO Message (employeeId, text, days, startDate, endDate, status, createdAt) VALUES (..., 'active', GETDATE())` con texto `"Tu reubicación fue ejecutada. Nueva oficina: {office_nombre}."` (mismo patrón que subsistema 2).
10. `db.commit()`. Devuelve `{"message": "Reubicación ejecutada", "estado": "Ejecutada"}`.

Todo en una sola transacción: si algo falla, no queda el empleado movido con la solicitud sin actualizar, ni viceversa.

El endpoint no reemplaza ni modifica ningún endpoint existente de `reubicacion.py` (`/request`, `/mis-solicitudes/{id}`, `/solicitudes`, `/{id}/estado`, `/{id}/recomendacion`, `/analizar/iniciar`).

## C. Frontend

Todo sobre `src/app/screens/ReubicacionTablero/Screen.tsx`.

1. **Botón "Ejecutar"** en las tarjetas (Kanban) y filas (tabla) en estado `Aprobada`. Solo aparece para `Aprobada`.
2. **Diálogo de ejecución** (nuevo, separado del de aprobar/rechazar):
   - Título: `"Ejecutar reubicación de {employeeName}"`.
   - Dropdown "Oficina destino" (opciones de `GET /departments/`, que el tablero ya carga en `officeOptions`), pre-cargado con `officeIdDestino` si existe; vacío si no.
   - Texto informativo: "Se moverá al empleado a esta oficina/departamento y se actualizará el organigrama."
   - "Confirmar" deshabilitado si no hay oficina seleccionada.
   - Al confirmar: `apiClient.patch('/reubicacion/{id}/ejecutar', { officeId })`, toast de éxito/error, recarga del tablero (`cargarSolicitudes`).
3. **Sin cambios** en aprobar/rechazar/analizar. La columna `Ejecutada` del Kanban (hoy siempre vacía) se puebla al ejecutar.

## Manejo de errores

- Solicitud inexistente → 404.
- Estado ≠ `Aprobada` → 400 (previene doble ejecución y ejecutar no-aprobadas).
- `officeId` faltante → 400 (cubre aprobación a ciegas sin destino).
- Oficina destino inexistente → 404.
- Transacción única: Employee + SolicitudReubicacion + Message se aplican juntos o nada (rollback).
- Frontend: "Confirmar" deshabilitado sin oficina evita el 400 más común antes de salir; toast de error si el PATCH falla.

## Fuera de alcance

- Reversión de una reubicación ya ejecutada (volver `Ejecutada` a un estado anterior o deshacer el movimiento) — no se pidió.
- Ejecución batch de varias solicitudes a la vez — se decidió individual.
- Fecha programada de ejecución futura (ejecución diferida automática) — se decidió disparo manual en el momento.
- Reasignación en cascada (mover también a subordinados del empleado) — el movimiento es individual.
- Fallback a `Department.jefeId` cuando la oficina no tiene jefe — se decidió limpiar a NULL en ese caso.

## Testing

Sin suite automatizada en ninguno de los dos repos — verificación manual:

1. Backend compila (`py -m py_compile app/routes/reubicacion.py`).
2. `PATCH /reubicacion/{id}/ejecutar` sobre una `Aprobada` con `officeId` válido: mueve `Employee` (officeId/departmentId/managerId correctos), pasa la solicitud a `Ejecutada`, e inserta el `Message`.
3. `managerId` queda con el `jefeId` de la oficina destino; si la oficina no tiene jefe, o el jefe sería el propio empleado → `managerId` NULL.
4. `PATCH /ejecutar` sobre una solicitud no-`Aprobada` → 400; inexistente → 404; sin `officeId` → 400; con `officeId` inexistente → 404.
5. En el módulo Organigrama, el empleado aparece efectivamente en su nueva oficina/departamento.
6. Frontend: botón "Ejecutar" solo en `Aprobada`; el diálogo pre-carga el destino si existe y lo exige si no; tras confirmar, la tarjeta se mueve a la columna `Ejecutada`.
7. El empleado recibe la notificación de ejecución en la campanita del header al loguearse.
