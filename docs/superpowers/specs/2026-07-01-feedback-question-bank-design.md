# Banco de preguntas y nuevo modelo de respuestas — Feedback 360°

## Contexto

El módulo actual de Feedback 360° (`app/routes/feedback.py`, `RRHH/.../Feedback/Screen.tsx`) es una versión simplificada: evalúa 1 *soft skill* del perfil de un compañero por vez, con una escala de 3 valores (Malo/Bueno/Excelente) guardados como contadores agregados en `Respuesta`, sin vincular evaluador, oficina, departamento ni fecha por respuesta individual, en un ciclo mensual.

El usuario entregó una especificación mucho más amplia para el módulo (evaluación de compañeros y superiores, preguntas de liderazgo condicionales, banco de 31 preguntas base + preguntas de ambiente laboral, escala 1-5, texto libre, rotación sin repetición por semestre, indicadores para RRHH, estadísticas globales). Es una reconstrucción grande del módulo, dividida en 4 subsistemas independientes:

1. **Banco de preguntas + nuevo modelo de respuestas** (este documento).
2. Motor de evaluación: compañeros + superiores, preguntas de liderazgo condicionales, rotación con historial anti-repetición por semestre, periodicidad configurable. Incluye el botón temporal "Verificar Evaluación de Equipo" para validar estas reglas.
3. Indicadores para RRHH (fortalezas/debilidades top 5 por empleado, evolución temporal).
4. Estadísticas globales (radar de habilidades, rankings, comparación por área/institucional).

Decisión confirmada con el usuario: las tablas actuales `Feedback`, `Respuesta` y `FeedbackEvaluacion` se **descartan** (no se migran) — el nuevo módulo arranca de cero con tablas nuevas. Las tablas viejas quedan en la base sin usarse (no se eliminan físicamente, pero el código deja de escribirlas/leerlas).

## Alcance de este subsistema

Solo modelo de datos + seed de las preguntas + endpoint de lectura. **No** se toca todavía `/feedback/submit` ni la lógica de rotación/anti-repetición — eso es el subsistema 2.

## Modelo de datos

### `Pregunta`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `texto` | NVARCHAR(500) | Texto de la pregunta |
| `categoria` | NVARCHAR(100) | Texto libre: "Respeto y convivencia", "Comunicación", "Responsabilidad", "Profesionalismo", "Liderazgo", "Riesgos laborales", "Conductas de riesgo", "Confianza", "Preguntas abiertas", "Ambiente laboral general" |
| `tipo` | NVARCHAR(20) | `'escala'` \| `'texto_libre'` |
| `opcionesEscala` | NVARCHAR(500) NULL | JSON de 5 labels ordenados de mejor a peor (ej. `["Siempre","Casi siempre","Algunas veces","Rara vez","Nunca"]`). NULL si `tipo = 'texto_libre'`. Las preguntas 27 y 28 (categoría Confianza) usan sus propias 5 etiquetas en vez de la escala estándar. |
| `soloLiderazgo` | BIT | Default 0. True para las 5 preguntas de la categoría Liderazgo — el frontend/motor de rotación (subsistema 2) solo las muestra si el evaluado tiene cargo jerárquico (`Department.jefeId = evaluado.id` o el evaluado tiene reportes directos vía `Employee.managerId`). |
| `esAmbienteGeneral` | BIT | Default 0. True para las 8 preguntas sin evaluado (percepción del entorno de trabajo, no de una persona). |
| `activo` | BIT | Default 1 |
| `createdAt` | DATETIME | GETDATE() |

Idempotencia: se crea con el mismo patrón `IF NOT EXISTS (... sysobjects ...) BEGIN CREATE TABLE ... END` usado en `app/database/feriados.py`.

### `RespuestaFeedback`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `preguntaId` | INT FK → Pregunta.id | |
| `evaluadorEmployeeId` | INT FK → Employee.id | |
| `evaluadoEmployeeId` | INT NULL FK → Employee.id | NULL cuando `Pregunta.esAmbienteGeneral = 1` |
| `officeId` | INT NULL | Snapshot del `Employee.officeId` del evaluado (o del evaluador si es pregunta de ambiente general) al momento de responder |
| `departmentId` | INT NULL | Snapshot análogo de `departmentId` |
| `periodo` | DATE | Fecha de inicio del ciclo evaluado (mismo concepto que el `cycleStart` actual) |
| `valorEscala` | INT NULL | 1 a 5. NULL si `tipo = 'texto_libre'` |
| `textoLibre` | NVARCHAR(MAX) NULL | NULL si `tipo = 'escala'` |
| `createdAt` | DATETIME | GETDATE() |

Se guarda un snapshot de oficina/departamento (no un JOIN en el momento de leer) porque un empleado puede cambiar de área entre el momento de la respuesta y el momento del reporte, y las comparaciones "por área" del subsistema 4 deben reflejar el área en el momento evaluado, no la actual.

## Seed de preguntas

Se cargan, solo si la tabla está vacía (mismo patrón no bloqueante que `feriados.py`/`academic_title_mapping.py` — no pisa filas existentes si RRHH ya las editó):

- Las 31 preguntas base del documento, con su `categoria` correspondiente, `tipo='escala'` (con `opcionesEscala` estándar, salvo las 2 de Confianza que llevan sus propias etiquetas) para las preguntas 1–28, y `tipo='texto_libre'` para las 3 preguntas abiertas (29, 30, 31).
- Las 5 preguntas de categoría "Liderazgo" (15–19) con `soloLiderazgo=1`.
- Las 8 preguntas de "Ambiente laboral general" del documento, con `esAmbienteGeneral=1`, `tipo='escala'`, escala estándar.

## Endpoint

`GET /feedback/preguntas` (dependencia `require_any_auth`, de solo lectura):
- Query params opcionales: `soloLiderazgo` (bool), `esAmbienteGeneral` (bool) para filtrar.
- Devuelve `{"preguntas": [{id, texto, categoria, tipo, opcionesEscala, soloLiderazgo, esAmbienteGeneral}]}`.

## Fuera de alcance (subsistemas siguientes)

- Lógica de rotación aleatoria, anti-repetición por semestre, periodicidad configurable (trimestral/semestral/anual).
- Evaluación de superiores directos (hoy solo compañeros de depto/oficina).
- Preguntas de liderazgo condicionadas dinámicamente al cargo del evaluado en el flujo real de evaluación.
- El botón temporal "Verificar Evaluación de Equipo".
- Indicadores para RRHH y estadísticas globales (radar, rankings, comparaciones).
- Cualquier cambio a `/feedback/submit`, `/feedback/peers`, `/feedback/status`, `/feedback/received` — siguen funcionando igual que hoy con el modelo viejo hasta que el subsistema 2 los reemplace.

## Apéndice: preguntas a sembrar

**Nota de ambigüedad detectada:** en el listado original entregado por el usuario, la categoría "Respeto y convivencia" salta del ítem 4 al 6 — **la pregunta #5 nunca fue especificada**. El seed de este subsistema carga las **30 preguntas confirmadas** abajo (numeración 1–4, 6–31, tal cual el original) más las 8 de ambiente general. Si el usuario provee el texto de la pregunta #5 antes de implementar, se agrega como pregunta #32 del banco (no se renumera el resto).

### Preguntas base (escala 1-5, salvo aclaración)

**1. Respeto y convivencia**
1. ¿La persona trata a sus compañeros con respeto?
2. ¿Mantiene un trato cordial durante la jornada laboral?
3. ¿Has presenciado conductas inapropiadas por parte de esta persona?
4. ¿Comparte información importante con el equipo?
6. ¿Genera conflictos innecesarios?

**3. Comunicación**
7. ¿Escucha las opiniones de los demás?
8. ¿Expresa sus ideas de forma respetuosa?
9. ¿Acepta críticas constructivas?

**4. Responsabilidad**
10. ¿Cumple con sus tareas en tiempo y forma?
11. ¿Es confiable cuando se le asigna una tarea?
12. ¿Su trabajo genera retrabajos para otros?

**5. Profesionalismo**
13. ¿Respeta horarios y normas internas?
14. ¿Mantiene una actitud profesional?

**6. Liderazgo** (`soloLiderazgo=1`)
15. ¿Brinda instrucciones claras?
16. ¿Escucha las inquietudes del equipo?
17. ¿Distribuye el trabajo de manera justa?
18. ¿Reconoce el buen desempeño?
19. ¿Resuelve conflictos de manera adecuada?

**7. Riesgos laborales**
20. ¿Alguna persona del equipo genera un ambiente tenso?
21. ¿Te sentís cómodo trabajando con esta persona?
22. ¿Evitás interactuar con esta persona cuando es posible?
23. ¿Considerás que esta persona afecta negativamente al equipo?

**8. Conductas de riesgo**
24. ¿Has observado faltas de respeto hacia compañeros?
25. ¿Has observado conductas intimidantes o agresivas?
26. ¿Creés que esta persona discrimina o hace comentarios ofensivos?

**9. Confianza** (`opcionesEscala` propias, no la escala estándar)
27. ¿Confiarías en esta persona para trabajar en una tarea importante? → `["Totalmente","Sí","Parcialmente","Poco","No"]`
28. ¿Volverías a elegir trabajar con esta persona? → `["Sí, sin dudas","Sí","Me es indiferente","Preferiría que no","Definitivamente no"]`

**10. Preguntas abiertas** (`tipo='texto_libre'`)
29. ¿Qué fortalezas destacás de esta persona?
30. ¿Qué aspecto debería mejorar?
31. ¿Hay algo que Recursos Humanos o la dirección debería conocer?

### Preguntas de ambiente laboral general (`esAmbienteGeneral=1`, escala estándar)

- ¿Te sentís valorado en tu trabajo?
- ¿Existe favoritismo?
- ¿Te sentís escuchado?
- ¿Te sentís cómodo expresando desacuerdos?
- ¿Existe colaboración entre áreas?
- ¿Te sentís sobrecargado de trabajo?
- ¿Has pensado en renunciar por el ambiente laboral?
- ¿Recomendarías esta oficina como lugar para trabajar?

### Escala estándar (`opcionesEscala` por defecto)

`["Siempre","Casi siempre","Algunas veces","Rara vez","Nunca"]` → valores 5,4,3,2,1 respectivamente.

## Testing

- No hay test suite automatizado en el repo backend — verificación manual:
  1. Levantar el backend y confirmar que las tablas `Pregunta` y `RespuestaFeedback` se crean sin error.
  2. Confirmar que el seed cargó 31 + 8 = 39 preguntas (`SELECT COUNT(*) FROM Pregunta`).
  3. Confirmar que las 5 preguntas de Liderazgo tienen `soloLiderazgo=1` y las 8 de ambiente tienen `esAmbienteGeneral=1`.
  4. `GET /feedback/preguntas` devuelve las 39 preguntas; `GET /feedback/preguntas?soloLiderazgo=true` devuelve solo 5; `GET /feedback/preguntas?esAmbienteGeneral=true` devuelve solo 8.
  5. Confirmar que `/feedback/submit`, `/feedback/peers`, `/feedback/status`, `/feedback/received` siguen funcionando sin cambios (no se tocaron).
