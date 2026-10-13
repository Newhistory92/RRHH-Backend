# Alerta de recálculos con errores

**Fecha:** 2026-10-13
**Estado:** aprobado

## El problema

El 13 de octubre el usuario reportó que su asistencia del 9 y del 13 no aparecía, y que "Recalcular todo" no la traía. La causa era un `TypeError` en el recálculo de su legajo.

Lo que importa para este spec no es ese bug —ya está corregido— sino cómo se descubrió: **el sistema lo sabía desde el primer día y nadie se enteró.** Cada corrida nocturna desde el 9 de octubre había guardado el error exacto en `RecalculoLog.errores`:

```
[{"employeeId": 8, "error": "'>' not supported between instances of 'datetime.date' and 'datetime.datetime'"}]
```

Cuatro corridas, cuatro días, el mismo error guardado en una tabla de la propia base. Nadie lo miraba.

Peor: el tablero de Asistencia **ya consulta** `GET /asistencia/recalculos`, pero solo para saber cuándo terminó el recálculo que acaba de lanzar. Lee `id` y `finalizadoAt` y descarta `errores`. El dato viajaba hasta el navegador y se tiraba ahí.

El recálculo masivo está diseñado a propósito para que un empleado que falla no aborte el resto: se registra y se sigue. Esa decisión es correcta —un legajo roto no puede dejar sin asistencia a toda la planta— pero deja un agujero: sin nadie que lea el registro, un empleado puede quedar sin calcular indefinidamente y en silencio.

Este spec cierra ese agujero.

## El alcance

Hacer visible lo que ya se guarda. No se agregan tablas, columnas ni estados nuevos.

Queda **fuera** a propósito:

- Botón de reintentar por empleado: "Recalcular todo" ya lo cubre.
- Notificación por campanita o mail: decisión del usuario, el panel alcanza.
- Marcar errores como "vistos": requeriría estado persistente nuevo, y la regla de abajo hace que el panel se apague solo.

## Las decisiones

| Decisión | Elegido | Por qué |
|---|---|---|
| Dónde avisa | Panel plegable en el tablero de Asistencia | Hermano del de "IDs del reloj sin vincular", que ya existe en esa misma pantalla. Sin infraestructura nueva. |
| Qué corridas mira | Solo la última masiva terminada | Refleja el estado de hoy. Una corrida posterior limpia apaga el panel sola, sin que nadie marque nada. |
| Qué muestra | Legajo, nombre y el texto exacto de la excepción | El texto técnico es lo que permitió diagnosticar este bug en segundos. Sin él solo se sabe que algo falló, no qué. |

## Qué cuenta como "corrida masiva"

Verificado contra el código, no asumido. `recalcular_todos` es la única función que barre toda la nómina (`SELECT id FROM Employee WHERE biometricoId IS NOT NULL`, sin más filtros), y se registra con tres orígenes:

| Origen | Quién lo dispara |
|---|---|
| `nocturno` | El scheduler, 3 AM |
| `manual` | El botón "Recalcular todo" |
| `arranque` | El scheduler al levantar el server |

Los otros dos orígenes que existen en `RecalculoLog` son barridos **parciales** y no cuentan:

| Origen | Alcance |
|---|---|
| `cupo_permiso` | Solo los empleados de una jornada laboral |
| `extension_tolerancia` | Solo los marcados fuera del anillo |

Ignorarlos no esconde nada: los dos filtran sobre la misma nómina que el nocturno barre entera cada noche, así que cualquier empleado que falle en un barrido parcial vuelve a fallar en el nocturno siguiente, dentro de las 24 horas. A cambio, la regla queda honesta: el panel dice "el último barrido completo dejó estos errores", y eso o es cierto ahora o no lo es.

## El backend

### `errores_del_ultimo_barrido(db) -> dict | None`

Vive en `app/database/asistencia_auditoria.py`, junto a `ultimos_recalculos`, que es su vecina natural.

Toma la última corrida **terminada** (`finalizadoAt IS NOT NULL`) cuyo origen sea uno de los tres masivos. Una corrida en curso no se considera: todavía no se sabe cómo le fue.

- Si no hay ninguna corrida masiva, o la última no dejó errores (`errores IS NULL`), devuelve `None`. El frontend no dibuja panel.
- Si dejó errores, parsea el JSON y le pega el nombre de cada empleado con una sola consulta a `Employee`.

Forma de la respuesta:

```python
{
    "id": 109,
    "origen": "manual",
    "finalizadoAt": datetime(2026, 10, 13, 7, 51, 13),
    "procesados": 4,
    "errores": [
        {"employeeId": 8, "nombre": "Emiliano Rojo",
         "error": "'>' not supported between instances of ..."},
    ],
}
```

**Bordes:**

- `errores` con JSON malformado: se devuelve el texto crudo como una entrada sola (`employeeId` en `None`, `error` con el contenido literal) en vez de propagar la excepción. Un registro de auditoría corrupto no puede tumbar la pantalla que existe justamente para mostrar fallas.
- Empleado cuyo nombre no se encuentra (borrado de la base): `nombre` en `None`, el frontend muestra el legajo pelado.
- Una entrada del JSON sin la clave `employeeId`: se muestra igual, con `employeeId` en `None`.

### `GET /asistencia/recalculos/errores`

En `app/routes/asistencia.py`, bajo `asistencia.gestionar`, igual que `GET /asistencia/biometricos-huerfanos`.

```json
{
  "ultimoBarrido": {
    "id": 109,
    "origen": "manual",
    "finalizadoAt": "2026-10-13T07:51:13",
    "procesados": 4,
    "errores": [
      { "employeeId": 8, "nombre": "Emiliano Rojo", "error": "..." }
    ]
  }
}
```

`ultimoBarrido` es `null` cuando no hay nada que mostrar.

## El frontend

En `AsistenciaTablero.tsx`, un panel hermano del de huérfanos:

- Se pide en el mismo `Promise.all` que ya trae los huérfanos y el tablero. Una llamada más en paralelo, no una cascada.
- Se vuelve a pedir cuando termina el polling de "Recalcular todo", para que el panel se apague en el acto si la corrida salió limpia.
- Solo se dibuja si `ultimoBarrido` no es `null`.

Contenido:

- Encabezado plegable, en tono de error: **"Empleados que no se pudieron calcular (N)"**.
- Debajo del título, en letra chica: el origen y la fecha de la corrida, para que se entienda de cuándo es el dato.
- Una línea por empleado: legajo, nombre y el texto del error.
- Una nota al pie: que esos empleados quedaron sin asistencia actualizada y que, una vez corregida la causa, "Recalcular todo" los vuelve a procesar.

Se usan los tokens del design system (`text-error`, `border-border`, `bg-card`), como el panel de huérfanos.

## Testing

**Backend**, con `FakeSession`:

| Caso | Qué prueba |
|---|---|
| Última masiva sin errores | Devuelve `None`; el panel no aparece |
| Última masiva con errores | Parsea el JSON y pega los nombres |
| JSON malformado | Devuelve el texto crudo, no levanta excepción |
| Barrido parcial con errores, último barrido completo limpio | Devuelve `None`: la regla de "solo masivas" se cumple de verdad |
| Empleado sin nombre en `Employee` | `nombre` en `None`, sin romper |
| La consulta filtra por los tres orígenes y por `finalizadoAt` | El SQL ejecutado contiene ambos filtros |

**Frontend:** sin runner, como todo el repo. `npx tsc --noEmit`, criterio no agregar errores nuevos sobre el baseline de 27, contado con `grep -c "error TS"`. Verificación visual del usuario.

**Verificación contra la base real:** el endpoint se consulta contra la base de desarrollo, donde `RecalculoLog` todavía tiene las corridas fallidas del 9 al 13 de octubre en el historial y la última corrida limpia arriba. El panel tiene que **no** aparecer —porque la última masiva salió limpia— y eso confirma de una sola vez la regla de autoapagado y que la consulta mira la corrida correcta.

## Notas de implementación

- Comentarios Python sin tildes (convención del repo); comentarios del frontend con tildes.
- `json` ya está importado en `asistencia_auditoria.py` (lo usa `cerrar_recalculo`).
- La fecha de la corrida se serializa con `.isoformat()`, como el resto de los endpoints del módulo.
