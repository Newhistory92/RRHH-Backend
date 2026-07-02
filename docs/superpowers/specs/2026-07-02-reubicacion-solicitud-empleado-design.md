# Módulo de Reubicación — Solicitud del empleado (subsistema 1)

## Contexto

El usuario pidió un módulo completo de "Solicitud de Cambio de Oficina y Reubicación Inteligente": portal del empleado para crear la solicitud, tablero RRHH tipo Kanban con 6 estados, motor de análisis/matching asistido por IA, y actualización automática del organigrama al ejecutar. Es demasiado grande para un solo plan — se decompone en 4 subsistemas independientes:

1. **Solicitud del empleado** (este documento): modelo de datos + creación + historial propio.
2. Tablero RRHH: Kanban/tabla con los 6 estados, filtros, aprobar/rechazar, notificación al empleado.
3. Motor de análisis IA / matching: índice de compatibilidad ponderado, evaluación de oficina actual vs. candidatas, explicación generada por IA (reutiliza el patrón ya existente en `org-analysis-engine.ts` + `ai-service.ts`/Gemini, usado hoy en Optimización de Departamentos).
4. Ejecución automática: al aprobar/ejecutar, actualizar el departamento/oficina del empleado en el organigrama.

Decisión confirmada con el usuario: el orden de trabajo es 1 → 2 → 3 → 4 (2 y 4 dependen de que exista 1; 3 depende de que exista 2).

## A. Modelo de datos

Tabla `SolicitudReubicacion`:

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `employeeId` | INT | FK lógica a `Employee.id` |
| `tipo` | NVARCHAR(50) | Uno de: `'Cambio de oficina'`, `'Cambio de departamento'`, `'Reubicación por desarrollo profesional'`, `'Reubicación por clima laboral'`, `'Reubicación por razones personales'`, `'Otra'` |
| `motivo` | NVARCHAR(MAX) | Texto libre, obligatorio |
| `estado` | NVARCHAR(20) | `'Pendiente'` \| `'En análisis'` \| `'Recomendada'` \| `'Aprobada'` \| `'Rechazada'` \| `'Ejecutada'`. Toda solicitud nueva nace en `'Pendiente'` — los estados intermedios/finales los gestiona el subsistema 2. |
| `officeIdActual` | INT NULL | Snapshot de `Employee.officeId` al momento de crear la solicitud |
| `departmentIdActual` | INT NULL | Snapshot de `Employee.departmentId` al momento de crear la solicitud |
| `createdAt` | DATETIME2 | |
| `updatedAt` | DATETIME2 | |

**No hay campo de oficina/departamento destino** — el empleado no elige a dónde quiere ir; eso lo determina el motor de IA en el subsistema 3, y RRHH lo confirma en el subsistema 2.

Sin migración de datos previos (tabla nueva, no reemplaza nada existente).

## B. Endpoints

- `POST /reubicacion/request` (`require_any_auth`): body `{employeeId, tipo, motivo}`. Valida que `tipo` sea uno de los 6 valores válidos y que `motivo` no esté vacío. Aplica el mismo chequeo self-or-admin que el resto de los módulos (un empleado solo puede crear una solicitud a su propio nombre, salvo que quien llame sea RRHH/Admin). Inserta con `officeIdActual`/`departmentIdActual` snapshot del `Employee` actual y `estado='Pendiente'`.
- `GET /reubicacion/mis-solicitudes/{employee_id}` (`require_any_auth`): devuelve el historial de solicitudes de ese empleado, mismo chequeo self-or-admin, ordenado por `createdAt DESC`.

## C. Frontend

Nueva pantalla "Solicitudes de Reubicación", siguiendo el mismo patrón de acceso que Licencias/Feedback/Documentos (confirmado en el código: `Sidebar.tsx` retorna `null` para el rol USER — los empleados acceden a esos 3 módulos vía el menú del `Header.tsx`, no la sidebar):

- Entrada nueva en el array de menú de `Header.tsx` (junto a licencias/feedback/documentos).
- Entrada nueva en `PAGE_CONFIG` de `rbac.ts` (mismo patrón: `visibleFor: [ADMIN, RRHH]`, `accessibleFor: [ADMIN, RRHH, USER]`).
- Case nuevo en el switch de `page.tsx`.
- Pantalla con: botón "Nueva Solicitud" que abre un formulario (dropdown de `tipo` con las 6 opciones + textarea de `motivo`), y debajo el historial de solicitudes propias con su `estado` (chip de color, sin acciones — el empleado no puede editar/cancelar en este subsistema).

## Fuera de alcance

- Tablero Kanban de RRHH, cambios de estado, aprobación/rechazo, notificaciones — subsistema 2.
- Motor de IA / matching / recomendaciones — subsistema 3.
- Actualización automática del organigrama — subsistema 4.
- Cancelar o editar una solicitud ya creada (no se pidió).
- Bloquear al empleado de crear una segunda solicitud mientras tiene una pendiente (no se pidió explícitamente para este módulo; a diferencia de Licencias, el documento no menciona esta regla — se puede agregar después si se pide).

## Testing

Sin test suite automatizada — verificación manual:
1. `POST /reubicacion/request` con un `tipo` inválido devuelve 400.
2. `POST /reubicacion/request` con `motivo` vacío devuelve 400.
3. `POST /reubicacion/request` válido crea la fila con `estado='Pendiente'` y los snapshots de oficina/departamento correctos.
4. Un empleado no puede crear una solicitud a nombre de otro (403), salvo que sea RRHH/Admin.
5. `GET /reubicacion/mis-solicitudes/{id}` devuelve solo las solicitudes de ese empleado, ordenadas por fecha descendente.
6. En el frontend: el ítem "Solicitudes de Reubicación" aparece en el menú del header para cualquier rol (incluido empleado); se puede crear una solicitud y aparece en el historial con estado "Pendiente".
