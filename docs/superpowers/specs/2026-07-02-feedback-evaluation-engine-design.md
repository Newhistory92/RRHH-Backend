# Motor de evaluación — Feedback 360°

## Contexto

Continuación del subsistema 1 (banco de preguntas — [2026-07-01-feedback-question-bank-design.md](2026-07-01-feedback-question-bank-design.md), ya implementado: tablas `Pregunta` y `RespuestaFeedback`, 38 preguntas sembradas, endpoint `GET /feedback/preguntas`).

Este subsistema reescribe el flujo real de evaluación (`app/routes/feedback.py`) para usar el banco de preguntas nuevo en vez del modelo viejo (`Feedback`/`Respuesta`/`FeedbackEvaluacion`, 1 soft skill a la vez, escala de 3, solo compañeros de depto/oficina, ciclo mensual fijo). Agrega: evaluación de superiores directos, preguntas de liderazgo condicionales, rotación con anti-repetición ajustada a una periodicidad configurable, y un botón temporal de verificación de reglas para RRHH.

Las tablas `Feedback`, `Respuesta`, `FeedbackEvaluacion` quedan sin usar (decisión ya tomada en el subsistema 1, no se migran).

## A. Configuración de periodicidad

Tabla `FeedbackConfig`, fila única activa:

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `periodicidad` | NVARCHAR(20) | `'trimestral'` \| `'semestral'` \| `'anual'`. Default `'trimestral'` si nunca se configuró. |
| `updatedAt` | DATETIME2 | |

Mismo patrón que `academic_title_mapping.py`: `ensure_table()` crea la tabla e inserta la fila default si está vacía; las lecturas/escrituras posteriores hacen `UPDATE` sobre esa única fila (no se insertan filas nuevas).

La periodicidad determina la duración del **ciclo activo**: el inicio de ciclo (`periodo`) se calcula igual que el `cycle_start` que ya usa el módulo (primer día del mes), pero truncado al múltiplo correspondiente:
- `trimestral`: meses [1,4,7,10] → el `periodo` del ciclo actual es el primer día del trimestre en curso.
- `semestral`: meses [1,7].
- `anual`: mes [1].

Endpoints:
- `GET /feedback/config` (`require_any_auth`) → `{"periodicidad": "trimestral", "periodoActual": "2026-07-01"}`.
- `PUT /feedback/config` (`require_rrhh_auth`, mismo helper que ya usa `licenses.py`) → body `{"periodicidad": "semestral"}`, valida que sea uno de los 3 valores válidos, actualiza la fila.

## B. Pool de evaluables

`GET /feedback/peers/{employee_id}` (reescrito, mismo path):
1. Compañeros: igual que hoy — mismo `departmentId` u `officeId`, excluyendo al propio empleado.
2. Superior directo: el `Employee` con `id = employee.managerId`, si existe.
3. Para cada evaluable, se calcula `esJerarquico`: `true` si `Department.jefeId = evaluable.id` (para cualquier departamento) **o** si existe algún `Employee` con `managerId = evaluable.id` (tiene reportes directos).

Respuesta: `{"evaluables": [{id, name, department, office, esJerarquico}]}` — ya no se listan soft skills individuales (eso lo reemplaza el banco de preguntas).

## C. Selección de la siguiente pregunta

`GET /feedback/siguiente/{employee_id}` (nuevo):

1. Arma el pool de pares candidatos: producto de (evaluables de B) × (preguntas activas de `Pregunta`), excluyendo pares donde `Pregunta.soloLiderazgo=1` y el evaluable no es `esJerarquico`.
2. Excluye del pool los pares donde ya existe una fila en `RespuestaFeedback` con `evaluadorEmployeeId=employee_id`, `evaluadoEmployeeId=evaluado.id`, `preguntaId=pregunta.id` y `periodo` = inicio del ciclo activo (según A).
3. Si el pool queda vacío → `{"pregunta": null}` (el frontend muestra "no hay evaluaciones pendientes").
4. Si no, elige un par al azar (`ORDER BY NEWID()` en SQL Server) y devuelve:

```json
{
  "evaluado": {"id": 12, "name": "Juan Pérez"},
  "pregunta": {"id": 7, "texto": "...", "tipo": "escala", "opcionesEscala": ["Siempre", "..."]}
}
```

Las preguntas con `esAmbienteGeneral=1` entran al pool con `evaluado = null` (no requieren exclusión por evaluado, solo por evaluador+pregunta+período).

## D. Guardar una respuesta

`POST /feedback/submit` (reescrito, mismo path):

Body: `{"evaluadorId": 5, "evaluadoId": 12, "preguntaId": 7, "valorEscala": 4}` o `{"evaluadorId": 5, "evaluadoId": null, "preguntaId": 33, "textoLibre": "..."}` (para `esAmbienteGeneral` o `texto_libre`).

1. Valida que la `Pregunta` exista y esté activa; si `tipo='escala'` requiere `valorEscala` entre 1 y 5, si `tipo='texto_libre'` requiere `textoLibre` no vacío.
2. Si `Pregunta.soloLiderazgo=1`, valida que el evaluado sea `esJerarquico` (misma lógica de B.3) — 403 si no.
3. Verifica que no exista ya una fila para ese (evaluador, evaluado, pregunta, período) — 409 si ya existe (evita doble envío).
4. Inserta en `RespuestaFeedback` con `officeId`/`departmentId` tomados del **evaluado** en este momento (snapshot), y `periodo` = inicio del ciclo activo.

## E. Progreso del ciclo

`GET /feedback/status/{employee_id}` (reescrito, mismo path): cuenta el tamaño total del pool inicial (B×preguntas aplicables, sin filtrar por respondidas) vs. cuántas de esas ya tienen fila en `RespuestaFeedback` para el período actual. `{"total": 42, "completadas": 10}`.

## F. Botón "Verificar Evaluación de Equipo"

Solo visible para roles ADMIN/RRHH, en una pestaña nueva del panel de administración de Licencias (`ConfiguracionLicencias/Screen.tsx`, junto a "Feriados") — reutiliza la convención de tabs ya existente en esa pantalla.

`POST /feedback/verificar` (`require_rrhh_auth`), sin body, corre y devuelve un reporte de reglas sobre los datos reales:

```json
{
  "reglas": [
    {"regla": "Sin repeticion de pregunta/evaluador/evaluado en el periodo activo", "cumple": true, "detalle": "0 duplicados encontrados"},
    {"regla": "Preguntas de liderazgo solo a evaluados jerarquicos", "cumple": false, "detalle": "2 respuestas de liderazgo sobre evaluados sin cargo jerarquico (ids 45, 61)"}
  ]
}
```

Chequeos concretos:
1. **Sin duplicados**: `SELECT preguntaId, evaluadorEmployeeId, evaluadoEmployeeId, periodo, COUNT(*) FROM RespuestaFeedback WHERE periodo = <periodo actual> GROUP BY ... HAVING COUNT(*) > 1`.
2. **Liderazgo condicional respetado**: join `RespuestaFeedback` + `Pregunta` donde `soloLiderazgo=1`, verificar para cada `evaluadoEmployeeId` si cumple `esJerarquico` (B.3) al momento de la consulta.

El frontend, al recibir el reporte, además llama `GET /feedback/siguiente/{employeeId}` con el propio usuario RRHH logueado como evaluador (de solo lectura, no guarda nada) y muestra la pregunta+evaluado que devolvería, como demostración visual de que la rotación funciona.

## Fuera de alcance

- `GET /feedback/received/{employee_id}`: sigue con el modelo viejo, sin uso real desde el frontend hoy. Lo reemplaza el subsistema 3 (indicadores RRHH).
- Indicadores para RRHH (top 5 fortalezas/debilidades, evolución temporal) — subsistema 3.
- Estadísticas globales (radar, rankings, comparación de áreas) — subsistema 4.
- Notificar/recordar a un empleado que tiene evaluaciones pendientes (fuera del alcance pedido).

## Testing

Sin test suite automatizada — verificación manual:
1. `GET /feedback/config` devuelve `trimestral` por default; `PUT /feedback/config {"periodicidad":"semestral"}` (como RRHH) lo cambia; un usuario no-RRHH recibe 403 al intentar el PUT.
2. `GET /feedback/peers/{id}` de un empleado con jefe asignado incluye al jefe en la lista con `esJerarquico` reflejando si ese jefe tiene reportes/departamento a cargo.
3. `GET /feedback/siguiente/{id}` nunca devuelve una pregunta `soloLiderazgo=1` con un evaluado que tenga `esJerarquico=false`.
4. Responder la misma pregunta+evaluado dos veces en el mismo período con `POST /feedback/submit` → la segunda devuelve 409.
5. Cambiar la periodicidad y confirmar que el `periodo` calculado (y por lo tanto la ventana anti-repetición) cambia en consecuencia.
6. `POST /feedback/verificar` (como RRHH) devuelve el reporte de reglas; un usuario no-RRHH recibe 403.
7. El botón "Verificar Evaluación de Equipo" es visible solo para ADMIN/RRHH en `ConfiguracionLicencias/Screen.tsx`.
