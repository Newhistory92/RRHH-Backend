# Feriados configurables por RRHH

## Contexto

`RRHH/src/app/GestionLicencias/Calendario.tsx` (el selector de fechas que usa el empleado para pedir una licencia) ya excluye fines de semana y feriados públicos argentinos del cálculo de "días hábiles" (`countBusinessDays` en `RRHH/src/app/lib/dates.ts`). Los feriados públicos se traen de `https://api.argentinadatos.com/v1/feriados/{year}` y se procesan con `processHolidays()` a un `Map<string, PlainHoliday>` (`holidayMap`).

No existe forma de que RRHH marque un día específico como feriado propio de la empresa (ej. un día de cierre administrativo) para que también se excluya del conteo de días hábiles.

## Backend

Tabla nueva `Feriado`, creada de forma idempotente (`IF NOT EXISTS`, mismo patrón que `app/database/academic_title_mapping.py` y `app/database/employee_documents.py`), `ensure_table()` invocada al inicio de cada endpoint nuevo (no se toca `app/main.py`):

| Columna | Tipo | Notas |
|---|---|---|
| id | INT IDENTITY PK | |
| fecha | DATE NOT NULL | día puntual marcado como feriado |
| nombre | NVARCHAR(255) NOT NULL | descripción (ej. "Cierre administrativo") |
| activo | BIT NOT NULL DEFAULT 1 | soft delete |
| createdAt | DATETIME2 NOT NULL | |

Módulo de datos `app/database/feriados.py` (mismo patrón que `academic_title_mapping.py`): `ensure_table(db)`, `get_feriados(db) -> list[dict]` (`{"id", "fecha", "nombre"}`, solo activos), `save_feriado(db, fecha, nombre) -> int`, `delete_feriado(db, feriado_id) -> bool`.

Endpoints nuevos en `app/routes/licenses.py` (mismo router que ya tiene `/configuracion`):
- `GET /licenses/feriados` — `require_any_auth` (cualquier empleado lo necesita para que su calendario excluya los feriados de empresa correctamente).
- `POST /licenses/feriados` — `require_rrhh_auth` (ya existe como alias local en este archivo). Body `{fecha, nombre}`. Valida ambos no vacíos (400 si falta alguno).
- `DELETE /licenses/feriados/{feriado_id}` — `require_rrhh_auth`. Soft delete (`activo = 0`). 404 si no existe.

## Frontend

**Nueva tab "Feriados"** en `RRHH/src/app/screens/ConfiguracionLicencias/Screen.tsx` (junto a `licencias`/`contratos`/`profesiones`/`habilidades`/`horarios`, agregando `'feriados'` al type `TabId`): tabla con fecha + nombre, formulario de alta (input fecha + input texto), botón eliminar por fila. Mismo patrón visual y de manejo de estado que las tabs existentes (toast de éxito/error, `loadAllData()` tras cada mutación).

**`Calendario.tsx`**: el `useEffect` que hoy hace `fetch` solo a la API pública de feriados se extiende para también pedir `GET /licenses/feriados` (vía `apiClient`, en paralelo con `Promise.all`), y mezclar ambos resultados en el mismo `holidayMap`. El array de feriados de empresa se transforma al mismo shape `HolidayApi` (`{fecha, tipo: "Empresa", nombre}`) antes de pasarlo a `processHolidays()`, para reusar esa función sin modificarla. Si los dos orígenes definen un feriado en la misma fecha, gana el que se procese último (no es un caso que se espere en la práctica, no se resuelve explícitamente).

## Fuera de alcance

- Feriados recurrentes (mismo día todos los años) — cada feriado de empresa es una fecha puntual de un año específico; si se repite, RRHH lo vuelve a cargar el año siguiente.
- Cambios a `calcular_dias_vacaciones` (cuenta antigüedad para el total de días de vacaciones, no días hábiles de una licencia puntual) — no se toca.
- Validación de fecha duplicada o conflicto con feriados públicos — no se pidió.

## Testing

- No hay test suite automatizado en ninguno de los dos repos — verificación manual:
  1. Como RRHH, en ConfiguracionLicencias → tab "Feriados", agregar un feriado con una fecha futura.
  2. Como cualquier empleado, abrir el formulario de nueva licencia (que usa `Calendario.tsx`) — confirmar que esa fecha aparece marcada como feriado y que el conteo de días hábiles la excluye si cae dentro del rango seleccionado.
  3. Eliminar el feriado desde RRHH — confirmar que ya no se excluye en una nueva selección de fechas.
  4. Confirmar que un usuario sin rol RRHH/Admin no puede crear ni eliminar feriados (403), pero sí puede verlos (`GET` funciona para cualquier autenticado).
