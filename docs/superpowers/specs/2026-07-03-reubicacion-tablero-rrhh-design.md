# Módulo de Reubicación — Tablero de RRHH (subsistema 2)

## Contexto

Segundo subsistema del módulo de Reubicación Inteligente. El subsistema 1 (ya implementado y mergeado, [2026-07-02-reubicacion-solicitud-empleado-design.md](2026-07-02-reubicacion-solicitud-empleado-design.md)) creó la tabla `SolicitudReubicacion`, la creación de solicitudes por el empleado (`POST /reubicacion/request`) y su pantalla de historial propio.

Este subsistema da a RRHH un tablero para ver todas las solicitudes, filtrarlas, y aprobarlas o rechazarlas, notificando al empleado.

Los 6 estados del documento (`Pendiente`, `En análisis`, `Recomendada`, `Aprobada`, `Rechazada`, `Ejecutada`) se reparten entre subsistemas: `Pendiente` lo produce el subsistema 1; `En análisis`/`Recomendada` los produce el motor de IA (subsistema 3); `Aprobada`/`Rechazada` los produce RRHH (este subsistema); `Ejecutada` lo produce la actualización del organigrama (subsistema 4). El tablero muestra las 6 columnas, pero en este subsistema RRHH solo acciona **Aprobar / Rechazar**.

## A. Backend

### Columna nueva

Se agrega `observacion NVARCHAR(MAX) NULL` a `SolicitudReubicacion` para guardar la nota de RRHH al aprobar/rechazar. Se hace con un `ALTER TABLE` idempotente dentro de `ensure_table()`:

```sql
IF COL_LENGTH('SolicitudReubicacion', 'observacion') IS NULL
    ALTER TABLE SolicitudReubicacion ADD observacion NVARCHAR(MAX) NULL;
```

### `require_rrhh_auth`

Se define en `app/routes/reubicacion.py`, mismo patrón que `licenses.py`: `ROLE_RRHH = ROLE_ADMIN`, `require_rrhh_auth = require_roles(ROLE_ADMIN, ROLE_RRHH)`.

### `GET /reubicacion/solicitudes` (`require_rrhh_auth`)

Lista **todas** las solicitudes con datos del empleado, oficina y departamento (joins a `Employee`, `Office`, `Department`). Query params opcionales de filtro:
- `estado`: uno de los 6 estados.
- `officeId`: filtra por `officeIdActual`.
- `departmentId`: filtra por `departmentIdActual`.
- `fechaDesde` / `fechaHasta`: rango sobre `createdAt` (formato ISO `YYYY-MM-DD`).

Respuesta:
```json
{
  "solicitudes": [
    {
      "id": 1, "employeeId": 5, "employeeName": "Juan Pérez",
      "tipo": "Cambio de oficina", "motivo": "...", "estado": "Pendiente",
      "officeIdActual": 3, "officeName": "Sistemas",
      "departmentIdActual": 2, "departmentName": "Tecnología",
      "observacion": null,
      "createdAt": "2026-07-01T10:00:00", "updatedAt": "2026-07-01T10:00:00"
    }
  ]
}
```

Los filtros se aplican dinámicamente (solo se agregan al `WHERE` los que vienen con valor), con parámetros bindeados.

### `PATCH /reubicacion/{solicitud_id}/estado` (`require_rrhh_auth`)

Body: `{"estado": "Aprobada", "observacion": "opcional"}`.
1. Valida que `estado` sea `"Aprobada"` o `"Rechazada"` (400 si no).
2. Busca la solicitud (404 si no existe).
3. Actualiza `estado`, `observacion`, `updatedAt`.
4. Inserta un `Message` activo para `employeeId`: `"Tu solicitud de reubicación ({tipo}) fue {estado} por RRHH."` (+ observación si viene) — aparece en la campanita del header (mismo mecanismo que licencias/feedback).

Devuelve `{"message": "Solicitud actualizada", "estado": "..."}`.

## B. Frontend

### Ruteo por rol

En `page.tsx`, el `case 'reubicacion'` pasa a ser consciente del rol:
- ADMIN (`roleId === 1`) o RRHH (`roleId === 3`) → `<ReubicacionTablero />`.
- USER (`roleId === 2`) → `<Reubicacion employeeData={employeeData} />` (la pantalla del subsistema 1).

`roleId` ya está disponible en `page.tsx` (se usa para `canAccess`). Un solo ítem de menú, sin rutas nuevas.

### Nueva pantalla `screens/ReubicacionTablero/Screen.tsx`

- **Filtros** (fila superior): dropdown Estado (los 6 + "Todos"), dropdown Oficina, dropdown Departamento, y rango de fechas (2 inputs `date`). Al cambiar cualquiera, re-consulta `GET /reubicacion/solicitudes` con los query params correspondientes. Las oficinas/departamentos se obtienen de `GET /departments/` (que ya trae departamentos con sus oficinas anidadas).
- **Toggle Kanban ↔ Tabla**: botón que alterna la vista.
- **Kanban**: 6 columnas (una por estado), cada solicitud una tarjeta con nombre del empleado, tipo, motivo truncado, fecha, y —si el estado es `Pendiente` o `Recomendada`— botones Aprobar/Rechazar.
- **Tabla**: filas con empleado, tipo, motivo, oficina/departamento, estado (chip de color), fecha, y acciones Aprobar/Rechazar en la misma condición.
- **Aprobar / Rechazar**: abre un mini-diálogo (`Dialog` de PrimeReact) con un textarea de observación opcional; al confirmar llama `PATCH /reubicacion/{id}/estado` y recarga el tablero. Toast de éxito/error.

## Fuera de alcance

- Botón "Analizar Solicitudes" y estados `En análisis`/`Recomendada` producidos por IA — subsistema 3.
- Paso a `Ejecutada` con actualización automática del organigrama — subsistema 4.
- Filtros por Antigüedad y Profesión (requieren joins/cálculos extra; se difieren) — el tablero muestra 4 filtros: Estado, Oficina, Departamento, Fecha.
- Edición del `motivo` o del `tipo` de una solicitud por parte de RRHH.

## Testing

Sin test suite automatizada — verificación manual:
1. `GET /reubicacion/solicitudes` (como RRHH) devuelve todas las solicitudes con nombres de empleado/oficina/departamento; un usuario USER recibe 403.
2. Los filtros `estado`, `officeId`, `departmentId`, `fechaDesde`/`fechaHasta` acotan el resultado correctamente y de forma combinable.
3. `PATCH /reubicacion/{id}/estado` con un `estado` distinto de Aprobada/Rechazada devuelve 400.
4. `PATCH` válido cambia el estado, guarda la observación, e inserta un `Message` para el empleado (verificable en la campanita al loguearse como ese empleado).
5. En el frontend: RRHH ve el tablero (no el formulario del empleado); un empleado (USER) sigue viendo su formulario en la misma entrada de menú.
6. El toggle Kanban/Tabla funciona; Aprobar/Rechazar abre el diálogo, guarda, y refleja el cambio de estado en el tablero.
