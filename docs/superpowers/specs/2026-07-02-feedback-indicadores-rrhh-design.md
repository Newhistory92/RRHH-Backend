# Indicadores para RRHH — Feedback 360°

## Contexto

Continuación del subsistema 2 (motor de evaluación — [2026-07-02-feedback-evaluation-engine-design.md](2026-07-02-feedback-evaluation-engine-design.md), ya implementado y mergeado). Este subsistema reescribe `GET /feedback/received/{employee_id}` (hoy usa el modelo viejo `Feedback`/`Respuesta`, sin uso real desde el frontend) para leer de `RespuestaFeedback` y devolver los indicadores que RRHH necesita ver por empleado: fortalezas/debilidades Top 5 y evolución temporal.

## A. Backend — `GET /feedback/received/{employee_id}` reescrito

Requiere `require_any_auth` (igual que hoy).

### Fortalezas y Debilidades (Top 5 por categoría)

Se agrupan **todas** las respuestas históricas donde el empleado es el evaluado (`RespuestaFeedback.evaluadoEmployeeId = employee_id`), uniendo con `Pregunta` para excluir:
- `Pregunta.tipo = 'texto_libre'` (sin valor numérico).
- `Pregunta.esAmbienteGeneral = 1` (no son sobre una persona puntual).

Se promedia `valorEscala` agrupado por `Pregunta.categoria`. Las 5 categorías con mayor promedio son "fortalezas"; las 5 con menor promedio son "debilidades". Si hay menos de 5 categorías con datos, se devuelven las que existan (sin rellenar con vacíos).

### Evolución temporal (período actual vs. anterior)

Se agrega `get_periodo_anterior(db)` a `app/database/feedback_config.py`: calcula el inicio del ciclo inmediatamente anterior al actual, restando una unidad de periodicidad (trimestral: -3 meses, semestral: -6 meses, anual: -1 año) a `get_periodo_actual`.

Se calcula el promedio general de `valorEscala` (mismo filtro de exclusión que arriba: sin `texto_libre` ni `esAmbienteGeneral`) para el período actual y para el período anterior, sobre las respuestas donde el empleado es evaluado. Se devuelve la diferencia (`promedioActual - promedioAnterior`), `null` si no hay datos en alguno de los dos períodos (no se puede comparar).

### Shape de respuesta

```json
{
  "employeeId": 12,
  "fortalezas": [{"categoria": "Responsabilidad", "promedio": 4.6}, ...],
  "debilidades": [{"categoria": "Comunicación", "promedio": 2.8}, ...],
  "evolucion": {
    "periodoActual": "2026-07-01",
    "promedioActual": 4.1,
    "periodoAnterior": "2026-04-01",
    "promedioAnterior": 3.7,
    "diferencia": 0.4
  }
}
```

`promedioActual`/`promedioAnterior`/`diferencia` son `null` si no hay respuestas en ese período.

## B. Frontend — sección "Feedback 360°" en la ficha de empleado

En `Componentes/TablaOperador/Perfildetail.tsx` (vista de detalle que ya usa RRHH para ver licencias/permisos de un empleado), se agrega una sección nueva que llama a `GET /feedback/received/{employeeId}` al montar y muestra:
- Lista "Fortalezas" (Top 5 categorías, con su promedio).
- Lista "Debilidades" (Top 5 categorías, con su promedio).
- Un indicador de evolución (↑/↓/= según `diferencia`, con el valor numérico), o un mensaje "Sin datos suficientes para comparar" si `diferencia` es `null`.

Si el empleado no tiene ninguna respuesta recibida todavía, se muestra un mensaje vacío ("Este empleado todavía no recibió evaluaciones de Feedback 360°") en vez de listas vacías sin contexto.

## Fuera de alcance

- Radar de habilidades, ranking global, comparación con promedio de área/institucional — subsistema 4 (Estadísticas globales).
- Cualquier cambio a `/peers`, `/siguiente`, `/submit`, `/status`, `/verificar`, `/config`, `/preguntas` — no se tocan.

## Testing

Sin test suite automatizada — verificación manual:
1. Un empleado con respuestas recibidas en al menos 2 categorías distintas: `GET /feedback/received/{id}` devuelve `fortalezas`/`debilidades` ordenadas correctamente por promedio.
2. Un empleado sin ninguna respuesta recibida: devuelve `fortalezas: []`, `debilidades: []`, `evolucion` con todos los campos de promedio en `null`.
3. Cambiar la periodicidad (vía `PUT /feedback/config`) y confirmar que `get_periodo_anterior` calcula el período previo correctamente para cada valor (trimestral/semestral/anual).
4. En el frontend, abrir la ficha de un empleado con evaluaciones recibidas y confirmar que se ven las 2 listas Top 5 y el indicador de evolución.
5. Abrir la ficha de un empleado sin evaluaciones recibidas y confirmar que se ve el mensaje vacío, no listas en blanco.
