# Estadísticas globales de Feedback 360°

## Contexto

Último subsistema de la reconstrucción del módulo Feedback 360° (subsistemas 1-3 ya implementados y mergeados: banco de preguntas, motor de evaluación, indicadores por empleado). Este agrega la vista de "Estadísticas globales" pedida en el documento original: radar de habilidades, ranking de fortalezas/debilidades, y comparación con el promedio del área e institucional — a nivel de **departamento**, no de empleado individual (eso ya lo cubre el subsistema 3).

Decisión confirmada con el usuario: la vista tiene un selector de departamento; se muestra el radar (departamento vs. institucional) y los rankings del departamento seleccionado.

## A. Backend

`GET /feedback/estadisticas-globales?departmentId={id}` (`require_any_auth`):

Una sola query agrupa `RespuestaFeedback` por `Pregunta.categoria` (mismo filtro que el subsistema 3: `tipo='escala'` y `esAmbienteGeneral=0`), calculando en la misma fila el promedio del departamento seleccionado y el promedio institucional:

```sql
SELECT
    p.categoria,
    AVG(CASE WHEN rf.departmentId = :deptId THEN CAST(rf.valorEscala AS FLOAT) END) AS promedio_area,
    AVG(CAST(rf.valorEscala AS FLOAT)) AS promedio_institucional
FROM RespuestaFeedback rf
INNER JOIN Pregunta p ON p.id = rf.preguntaId
WHERE p.tipo = 'escala' AND p.esAmbienteGeneral = 0
GROUP BY p.categoria
```

`rf.departmentId` es el snapshot del departamento del evaluado al momento de la respuesta (ya existe en el modelo desde el subsistema 1), así que no hace falta un JOIN contra `Employee`.

Respuesta:
```json
{
  "departmentId": 3,
  "radar": [
    {"categoria": "Comunicación", "promedioArea": 4.1, "promedioInstitucional": 3.8},
    ...
  ],
  "fortalezasArea": [{"categoria": "Responsabilidad", "promedio": 4.6}, ...],
  "debilidadesArea": [{"categoria": "Comunicación", "promedio": 2.9}, ...]
}
```

`fortalezasArea`/`debilidadesArea` son Top 5, ordenando por `promedioArea` (excluyendo categorías donde `promedioArea` sea `null` — sin datos de ese departamento todavía). `promedioArea`/`promedioInstitucional` son `null` si no hay ninguna respuesta que aplique.

## B. Frontend

Se agrega una 3ra pestaña "Feedback 360°" en `RRHH/src/app/screens/Estadisticas/Screen.tsx` (junto a "Ranking de Productividad" y "Estadísticas Globales", que ya existen con el mismo patrón de tabs). Un componente nuevo en `Componentes/ComponEstadistica/` (ej. `Feedback360Stats.tsx`):
- Selector de departamento, poblado con `GET /departments/` (ya existe).
- Al cambiar la selección, llama a `GET /feedback/estadisticas-globales?departmentId={id}`.
- Radar (`RadarChart` de `recharts`, ya usado en `Globalstat.tsx`) con 2 series superpuestas: "Área seleccionada" e "Institucional", una arista por categoría.
- Dos listas: "Fortalezas del área" y "Debilidades del área" (Top 5).
- Si no hay departamento seleccionado todavía, se preselecciona el primero de la lista al cargar.
- Si el departamento no tiene ninguna respuesta registrada, se muestra un mensaje ("Este departamento todavía no tiene evaluaciones de Feedback 360°") en vez de un radar vacío.

## Fuera de alcance

- Cualquier cambio a los endpoints existentes de Feedback 360 (`/peers`, `/siguiente`, `/submit`, `/status`, `/verificar`, `/config`, `/preguntas`, `/received`).
- Comparación entre 2 departamentos a la vez, o vista histórica/temporal a nivel departamento (el subsistema 3 ya cubre evolución temporal, pero solo por empleado).

## Testing

Sin test suite automatizada — verificación manual:
1. `GET /feedback/estadisticas-globales?departmentId={id}` para un departamento con respuestas registradas devuelve `radar` con `promedioArea` y `promedioInstitucional` numéricos para cada categoría con datos.
2. Para un departamento sin ninguna respuesta: `promedioArea` es `null` en todas las categorías del radar, `fortalezasArea`/`debilidadesArea` vacíos.
3. `promedioInstitucional` es igual para cualquier `departmentId` que se pase (es un agregado global, no depende del filtro de área).
4. En el frontend: cambiar el selector de departamento y confirmar que el radar y los rankings se actualizan.
5. Seleccionar un departamento sin datos y confirmar que se ve el mensaje vacío, no un radar en blanco.
