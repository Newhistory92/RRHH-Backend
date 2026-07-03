# Módulo de Reubicación — Motor de análisis IA (subsistema 3)

## Contexto

Tercer subsistema del módulo de Reubicación Inteligente. Los subsistemas previos ya están implementados y mergeados:

- **Subsistema 1** ([2026-07-02-reubicacion-solicitud-empleado-design.md](2026-07-02-reubicacion-solicitud-empleado-design.md)): tabla `SolicitudReubicacion`, creación por el empleado (`POST /reubicacion/request`), historial propio. Toda solicitud nace en `Pendiente`. **No hay campo de destino** — lo determina este subsistema.
- **Subsistema 2** ([2026-07-03-reubicacion-tablero-rrhh-design.md](2026-07-03-reubicacion-tablero-rrhh-design.md)): tablero de RRHH (Kanban/tabla con los 6 estados, filtros), aprobar/rechazar con notificación al empleado, columna `observacion`.

Este subsistema le da a RRHH un botón **"Analizar Solicitudes"** que corre un motor de matching sobre las solicitudes `Pendiente`: para cada una determina la mejor oficina destino con un **score de compatibilidad**, y genera con IA una **explicación** para RRHH (con beneficios y riesgos esperados). Las solicitudes pasan de `Pendiente` → `En análisis` → `Recomendada`. RRHH luego revisa la recomendación y aprueba/rechaza (subsistema 2), pudiendo **cambiar el destino** sugerido.

Los 6 estados (`Pendiente`, `En análisis`, `Recomendada`, `Aprobada`, `Rechazada`, `Ejecutada`) se reparten entre subsistemas: `Pendiente` lo produce el subsistema 1; **`En análisis`/`Recomendada` los produce este subsistema**; `Aprobada`/`Rechazada` los produce RRHH (subsistema 2); `Ejecutada` lo produce la actualización del organigrama (subsistema 4).

## Decisiones de diseño (confirmadas con el usuario)

1. **Salida de la IA**: destino específico + score de compatibilidad + explicación estructurada (explicación narrativa + lista de **beneficios** + lista de **riesgos**). Ejemplo de explicación: *"Se recomienda trasladar al empleado a la Oficina de Sistemas debido a que posee un 92% de compatibilidad con las competencias requeridas y actualmente existe un déficit de personal especializado."*
2. **Scoring determinista + IA solo redacta**: el % de compatibilidad y el déficit de personal se calculan en código (auditable, reproducible); Gemini solo convierte esos datos en lenguaje natural. Es el patrón ya usado en "Optimización de Departamentos" (`org-analysis-engine.ts` + `ai-service.ts`).
3. **Disparo batch**: un botón global "Analizar Solicitudes" procesa todas las `Pendiente` de una vez.
4. **Override de destino**: al aprobar (subsistema 2), RRHH puede confirmar el destino sugerido o cambiarlo por otro.
5. **Sin umbral**: el motor siempre recomienda el mejor destino disponible; si el score es bajo, la explicación lo refleja con honestidad (no hay corte que marque "no recomendar").

## Arquitectura y flujo

Sigue el patrón existente de `/api/org-analysis`: **la orquestación vive en una API route de Next.js**, porque Gemini hoy se invoca solo desde el frontend (`@ai-sdk/google`, `GeminiService`, la key `GOOGLE_GENERATIVE_AI_API_KEY` es env var de Next.js). El backend FastAPI no tiene integración con Gemini y no se agrega.

Flujo al hacer click en "Analizar Solicitudes":

1. Frontend (`ReubicacionTablero`) → `POST /api/reubicacion-analysis` (Next.js route, nueva).
2. La route:
   a. `POST /reubicacion/analizar/iniciar` (backend) → marca todas las solicitudes `Pendiente` **y** `En análisis` como `En análisis` (bulk) y las devuelve.
   b. `GET /rrhh/org-analysis-data` (backend, **ya existe**) → empleados con skills blandas/técnicas y departamentos/oficinas con `habilidades_requeridas` y dotación.
   c. Para cada solicitud a analizar:
      - Motor TS determinista (`reubicacion-matching-engine.ts`, nuevo): compara skills del empleado vs. cada oficina candidata + déficit de personal → elige la mejor oficina + score 0-100 + `matchDetails`.
      - Gemini (`GeminiService`, ya existe): recibe los datos calculados y redacta `{explicacion, beneficios[], riesgos[]}`. Fallback templado si falla.
      - `PATCH /reubicacion/{id}/recomendacion` (backend, nuevo) → persiste la recomendación y pasa la solicitud a `Recomendada`.
   d. Devuelve `{analizadas, errores[]}` → el frontend recarga el tablero.
3. RRHH revisa cada `Recomendada` (ve destino/score/beneficios/riesgos) y al Aprobar confirma o cambia el destino (subsistema 2 extendido).

**Por qué se persiste `En análisis` primero (2a):** honra el modelo de 6 estados y deja las solicitudes en un estado visible y recuperable — si Gemini o el `PATCH` fallan en una, queda en `En análisis` y re-correr "Analizar" la vuelve a tomar (por eso `iniciar` agarra `Pendiente` **y** `En análisis`).

**Separación de responsabilidades:**
- **Backend** = dueño de los datos (lee solicitudes, persiste recomendaciones y transiciones de estado).
- **Next.js route** = orquestador (matching + IA + escritura vía endpoints del backend).
- **Motor TS** = cálculo puro y testeable (entra empleado + oficinas, sale destino + score).
- **Gemini** = solo redacción en lenguaje natural.

## A. Modelo de datos

Columnas nuevas en `SolicitudReubicacion`, agregadas con `ALTER TABLE` idempotente dentro de `ensure_table()` (mismo patrón que `observacion` en el subsistema 2). Sin migración de datos previos; todas NULL para solicitudes ya existentes.

| Columna | Tipo | Quién la escribe | Para qué |
|---|---|---|---|
| `officeIdSugerido` | INT NULL | Motor IA | Oficina destino recomendada por la IA |
| `departmentIdSugerido` | INT NULL | Motor IA | Departamento de esa oficina (derivado) |
| `scoreCompatibilidad` | INT NULL | Motor IA | Compatibilidad 0-100 (determinista) |
| `explicacionIA` | NVARCHAR(MAX) NULL | Gemini | Texto narrativo para RRHH |
| `beneficios` | NVARCHAR(MAX) NULL | Gemini | JSON array de strings |
| `riesgos` | NVARCHAR(MAX) NULL | Gemini | JSON array de strings |
| `officeIdDestino` | INT NULL | RRHH (al aprobar) | Destino **confirmado** (puede diferir del sugerido) |
| `departmentIdDestino` | INT NULL | RRHH (al aprobar) | Depto del destino confirmado |

**Decisiones:**
- `beneficios`/`riesgos` se guardan como **JSON string** en `NVARCHAR(MAX)` (listas de largo variable; `json.dumps` al escribir, `JSON.parse` al leer en el frontend). Es texto plano, no el tipo JSON nativo de SQL Server, para máxima compatibilidad.
- **Sugerido vs. Destino separados**: `*Sugerido` conserva lo que propuso la IA (auditoría, aunque RRHH cambie el destino); `*Destino` guarda lo que RRHH confirmó. El subsistema 4 (ejecución) usará `officeIdDestino`/`departmentIdDestino`.

## B. Endpoints del backend

En `app/routes/reubicacion.py`, todos con `require_rrhh_auth` (ya definido en el subsistema 2).

**1. `POST /reubicacion/analizar/iniciar`** (nuevo)
Marca todas las solicitudes en estado `Pendiente` o `En análisis` como `En análisis` (bulk `UPDATE`) y las devuelve.
Respuesta: `{"solicitudes": [{id, employeeId, employeeName, tipo, motivo, officeIdActual, departmentIdActual}], "count": n}`.

**2. `PATCH /reubicacion/{id}/recomendacion`** (nuevo)
Body: `{officeIdSugerido, departmentIdSugerido, scoreCompatibilidad, explicacionIA, beneficios, riesgos}`. `beneficios`/`riesgos` llegan como arrays y se guardan con `json.dumps`. Persiste la recomendación y pasa la solicitud de `En análisis` → `Recomendada`.
Respuesta: `{"message": "Recomendación guardada", "estado": "Recomendada"}`.

**3. `PATCH /reubicacion/{id}/estado`** (extender el existente)
Cuando `estado="Aprobada"`, acepta opcionalmente `officeIdDestino`/`departmentIdDestino` y los persiste. La lógica actual (validación Aprobada/Rechazada, `observacion`, inserción del `Message` de notificación) no cambia.

**4. `GET /reubicacion/solicitudes`** (extender el existente)
Se agregan al `SELECT` y a la respuesta: `officeIdSugerido`, `officeSugeridoName`, `departmentIdSugerido`, `departmentSugeridoName`, `scoreCompatibilidad`, `explicacionIA`, `beneficios` (parseado a array), `riesgos` (parseado a array), `officeIdDestino`, `departmentIdDestino`. Se agregan los JOINs a `Office`/`Department` para los nombres sugeridos. Así el tablero muestra la recomendación completa sin llamadas extra.

## C. Motor de matching (TS) + redacción IA

**Motor determinista** — `src/app/lib/reubicacion-matching-engine.ts` (nuevo)

Entrada: un empleado (con `softSkills`/`technicalSkills` y oficina/depto actual) + todas las oficinas con sus `habilidades_requeridas` y dotación actual. Para cada oficina candidata (excluyendo la actual):

- **Skill match (peso 70%)**: proporción de las `habilidades_requeridas` de la oficina que el empleado posee, considerando el nivel. Es el núcleo del %.
- **Déficit de personal (peso 30%)**: si la oficina/depto tiene habilidades requeridas sin cubrir por su dotación actual (reutiliza el concepto de "skill gap" de `org-analysis-engine.ts`). Prioriza destinos donde falta gente.
- **Score final** = combinación ponderada, 0-100. Se elige la oficina de mayor score → `officeIdSugerido`, `departmentIdSugerido` (depto de esa oficina), `scoreCompatibilidad`, y un `matchDetails` (skills que coinciden, cuáles faltan, info de déficit) que alimenta a Gemini.

**Redacción IA** — `src/app/lib/reubicacion-recomendacion-prompt.ts` (nuevo) + `GeminiService` (ya existe)

Gemini recibe los datos calculados y devuelve **solo JSON**: `{explicacion, beneficios[], riesgos[]}`, en español. Prompt estricto: **usar únicamente los hechos provistos** (no inventar), y si el score es bajo decirlo con honestidad. **Fallback templado** (como el patrón actual) si Gemini falla: arma `explicacion`/`beneficios`/`riesgos` a partir de los números del motor.

**Señales disponibles vs. no disponibles:** el motor se basa en **compatibilidad de skills + déficit de personal** (y opcionalmente subutilización del empleado en su depto actual — dato que sí existe en `org-analysis-data`). **"Experiencia previa en el área" NO está en el modelo de datos actual** (`org-analysis-data` tiene la oficina/depto actual y la fecha de ingreso, pero no un historial de áreas), así que la IA tiene **prohibido** afirmarla. Se reserva como mejora futura para cuando el subsistema 4 acumule solicitudes `Ejecutada` que sirvan de historial.

## D. Frontend

Todo sobre `src/app/screens/ReubicacionTablero/Screen.tsx` (ya existe del subsistema 2) + una API route nueva.

**1. API route** — `src/app/api/reubicacion-analysis/route.ts` (nueva)
Orquesta el flujo de la sección Arquitectura (iniciar → org-data → motor → Gemini → recomendacion por cada solicitud). Forwardea el `Authorization` header al backend (mismo patrón que `/api/org-analysis`). Devuelve `{analizadas, errores[]}`.

**2. Botón "Analizar Solicitudes"** en el header del tablero (junto al toggle Kanban/Tabla)
Corre `POST /api/reubicacion-analysis`, muestra spinner mientras procesa, y al terminar recarga el tablero + toast (`"N solicitudes analizadas"`, o error/parcial). Se deshabilita si no hay ninguna solicitud `Pendiente`.

**3. Vista de la recomendación** (estado `Recomendada`)
Las tarjetas/filas en `Recomendada` muestran un botón **"Ver recomendación"** que abre un `Dialog` con: destino sugerido (oficina/depto), **score con badge de color** (verde alto / ámbar medio / rojo bajo), la `explicacionIA`, y dos listas **Beneficios** y **Riesgos**.

**4. Diálogo de aprobación extendido** (override de destino)
El diálogo de Aprobar incluye un **dropdown de oficina destino** (opciones de `GET /departments/`, que el tablero ya carga). Si la solicitud es `Recomendada`, viene **pre-cargado** con `officeIdSugerido` (editable). Si es `Pendiente` (aprobación a ciegas), viene **vacío**. Al confirmar Aprobar, manda `officeIdDestino`/`departmentIdDestino` (el depto se deriva de la oficina elegida) junto con `estado` y `observacion`. Si no se elige oficina, `officeIdDestino` queda NULL (el subsistema 4 lo tratará como "sin destino definido"). Rechazar no cambia.

**Sin restricciones de flujo:** el análisis por IA es una **ayuda opcional**, no un paso obligatorio. RRHH mantiene Aprobar/Rechazar disponibles tanto en `Pendiente` (a ciegas, sin analizar) como en `Recomendada`.

## Manejo de errores

- **Por solicitud (dentro del batch):** si Gemini falla → fallback templado (igual produce `Recomendada`). Si el `PATCH /recomendacion` falla → esa solicitud queda en `En análisis` y se agrega a `errores[]`; el resto del lote continúa. Re-correr "Analizar" la re-toma (porque `iniciar` agarra `Pendiente` **y** `En análisis`).
- **Falla global:** si `iniciar` o `org-analysis-data` fallan → la route aborta con error; el frontend muestra toast rojo. Nada queda a medias salvo el `En análisis` (recuperable).
- **Respuesta de la route:** `{analizadas: n, errores: [{solicitudId, motivo}]}` → toast de éxito parcial si hubo errores (`"8 analizadas, 2 con error"`).
- **Sin candidatos:** si un empleado no tiene ninguna oficina candidata (única oficina, o sin skills requeridas en ningún lado) → score 0, `officeIdSugerido` NULL, explicación honesta ("no se encontró un destino con datos suficientes"). No rompe.

## Fuera de alcance

- Ejecución automática (paso a `Ejecutada` + actualización del organigrama) — subsistema 4.
- "Experiencia previa en el área" como señal de matching (no hay datos históricos hoy) — mejora futura.
- Umbral de corte que marque "no recomendar" — se decidió recomendar siempre el mejor con explicación honesta.
- Análisis automático al crear la solicitud (sin intervención de RRHH) — se decidió disparo manual batch.
- Re-análisis selectivo de una sola solicitud desde la UI — el botón es global (batch).

## Testing

Sin suite automatizada en ninguno de los dos repos — verificación manual:

1. Backend compila; `POST /analizar/iniciar` marca `Pendiente`+`En análisis` → `En análisis` y las devuelve; un usuario USER recibe 403.
2. `PATCH /{id}/recomendacion` guarda los campos, parsea `beneficios`/`riesgos`, y pasa la solicitud a `Recomendada`.
3. `PATCH /{id}/estado` con `Aprobada` + `officeIdDestino` persiste el destino confirmado; el override funciona (destino ≠ sugerido).
4. `GET /solicitudes` devuelve los campos nuevos con nombres de oficina/depto sugeridos y `beneficios`/`riesgos` como arrays.
5. Motor TS: un empleado con skills que matchean una oficina da score alto y la elige; sin matches da score bajo con explicación honesta.
6. Frontend: "Analizar Solicitudes" procesa la cola, las tarjetas pasan a `Recomendada`, "Ver recomendación" muestra destino/score/beneficios/riesgos.
7. Aprobar una `Recomendada` con el destino sugerido, y otra cambiándolo → ambos casos persisten el destino correcto y notifican al empleado.
8. Aprobar una `Pendiente` a ciegas (sin analizar, destino vacío) sigue funcionando.
