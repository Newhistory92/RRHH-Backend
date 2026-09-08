# Carga inicial de saldos de licencias

**Fecha:** 2026-09-03
**Estado:** aprobado para planificar

## Objetivo

Que RRHH pueda cargar, empleado por empleado, los días de licencia que le
quedan pendientes de años anteriores a su alta en el sistema — y que mientras
tanto se corrijan los defectos del endpoint con el que hoy se aplican
licencias, que descuenta días a la persona equivocada.

## Por qué existe

El saldo se calcula como `diasTotales - consumidos`, y `consumidos` sale
únicamente de `ConsumoLicencias` unido a filas de `License` creadas por el
propio sistema.

Un empleado recién cargado no tiene ninguna fila en `License`. Su consumo da
cero para todos los años. El sistema le muestra entonces las vacaciones
completas de la ventana vigente, aunque en la realidad ya se las haya tomado:
se las otorga de nuevo.

No hay hoy ningún mecanismo de saldo de apertura. La única "carga inicial" que
existe en el repositorio es la del reloj de asistencia, que no tiene relación.

### Estado medido de los datos (2026-09-03)

- 21 categorías en `ConfiguracionLicencias`, **todas configuradas solo para
  2026**. Como el armado de saldos itera sobre esa tabla, un año sin fila no
  aparece en el saldo.
- `ConsumoLicencias.licenseId` es `NOT NULL`: todo consumo exige una fila en
  `License`.
- Para Vacaciones el total **no** se lee de la configuración: lo calcula
  `calcular_dias_vacaciones` a partir de la antigüedad actual, y ese mismo
  número se aplica a los tres años de la ventana.
- El único tratamiento de arrastre que existe es el de Vacaciones, con su
  expiración a 3 años, escrito a mano contra la categoría `'vacaciones'`.

## Decisiones tomadas

| Decisión | Elegido | Por qué |
|---|---|---|
| Qué se arrastra | Solo Vacaciones | Es lo único que el sistema ya modela como acumulable |
| Qué carga RRHH | Los días que **faltan consumir** | Es el dato que RRHH efectivamente tiene del legajo |
| Granularidad | Un saldo por año | La expiración trabaja año por año; un total único obligaría a inventar una fecha de vencimiento |
| Ventana | 3 años: el año calendario en curso y los dos anteriores | Coincide con el ciclo de expiración; algo más viejo vencería apenas se cargue |
| Almacenamiento | Tabla propia de saldo inicial | Guardar el complemento derivado se desviaría solo al cambiar la antigüedad |
| Apagado | Permiso dedicado | Se apaga sin redeploy y el borrado del código queda sin apuro |
| Contenido de la ayuda | El mecanismo, no la normativa | Es lo verificable contra el código; el encuadre legal no se inventa |
| `/aplicar` sin match | Corta con error | Crear la licencia adivinando el dueño es peor que avisar |

### Por qué una tabla y no el consumo derivado

La alternativa natural era guardar el complemento: si RRHH dice "le quedan 5
de 2024", registrar `total - 5` como consumido y dejar que la matemática
existente haga el resto. No requiere esquema nuevo.

Se descartó por una razón concreta. Para Vacaciones el total se recalcula en
cada consulta a partir de la antigüedad **de hoy**. El consumo quedaría
congelado, pero el total se mueve: cuando el empleado cruce un tramo de
antigüedad, el saldo pendiente sube solo. Se cargó 5 y un día muestra 9, sin
que nadie haya tocado nada.

Guardar directamente lo que RRHH sabe elimina esa deriva, y de paso no exige
sembrar filas de configuración para años viejos.

## Arquitectura

### Unidad 1 — Persistencia del saldo inicial

Tabla nueva en la base de RRHH, con el mismo patrón `ensure_*` que ya usan
`ScoreHistorico` y `RutaProductividad`.

```
SaldoInicialLicencia
  id              int identity PK
  employeeId      int            not null
  anio            int            not null
  categoria       nvarchar(100)  not null
  diasPendientes  int            not null
  cargadoPor      int            null       -- employeeId de quien cargó
  cargadoEn       datetime2      not null
  UNIQUE (employeeId, anio, categoria)
```

La clave única convierte una corrección en un upsert, en vez de acumular filas
contradictorias. `cargadoPor` y `cargadoEn` existen porque esto mueve saldos
que se convierten en días libres: tiene que ser trazable quién los puso.

Tres estados, no dos:

- **Sin fila** → no se cargó nada; rige el cálculo normal del sistema.
- **Fila con `diasPendientes = 0`** → decisión tomada de que no le queda nada.
- **Fila con `diasPendientes > 0`** → le quedan esos días.

La distinción entre "sin fila" y "cero" es deliberada: no haber mirado a un
empleado y haber determinado que no le queda saldo son cosas distintas.

### Unidad 2 — El saldo inicial dentro del cálculo

En `GET /licenses/saldos`, donde hoy se decide el total:

```
totales = saldo_inicial   si hay carga para (año, categoría)
          dias_vac        si es vacaciones
          diasTotales     en cualquier otro caso
```

El resto de la cadena no cambia: `disponibles = max(0, totales - consumidos)`.
Recién cargado no hay consumo del sistema, así que muestra exactamente lo
cargado; después decrementa solo, por el circuito común.

**Años sin configuración.** El armado de saldos recorre las filas de
`ConfiguracionLicencias`, y solo existe 2026: un saldo cargado para 2024 nunca
aparecería. Después de recorrer la configuración se agregan las filas de saldo
inicial que no quedaron cubiertas. Es lo que permite cargar años viejos sin
sembrar configuración global.

**Expiración.** Hoy lee `diasTotales` de la configuración para el año que
vence. Pasa a leer el saldo inicial cuando exista, para que un saldo cargado a
mano venza igual que cualquier otro en vez de quedar inmortal. Con el ciclo
vigente el año que vence es 2022, así que en la práctica no toca nada de lo que
se cargue ahora; queda consistente para cuando el ciclo avance.

### Unidad 3 — Endpoints de carga

Dos, ambos bajo `require_permission("licencias.cargaInicial")`, un permiso
nuevo que se suma al catálogo de `app/permisos.py`.

**`GET /licenses/carga-inicial/{employee_id}`** — devuelve las categorías que
le aplican a ese empleado, separadas en acumulables y anuales, cada una con el
valor ya cargado si lo hay. Aplica los mismos filtros de género y rol que el
saldo: no tiene sentido ofrecer la carga de una licencia que el empleado nunca
va a ver.

**`PUT /licenses/carga-inicial/{employee_id}`** — guarda en lote, con upsert
por `(employeeId, anio, categoria)`, registrando quién y cuándo. En lote porque
el flujo real es completar varias filas de una pasada.

Validaciones: `diasPendientes` no negativo, año dentro de la ventana de tres
años, y categoría existente en la configuración.

### Unidad 4 — Corrección de `/licenses/aplicar`

El endpoint tiene tres defectos, todos con el mismo efecto: descontarle días a
quien no corresponde.

**Aprueba la licencia de otro empleado.** Busca la `License` solo por fechas,
sin filtrar por persona, y se queda con la primera. Dos empleados que se toman
la misma semana -- habitual -- y aprueba la del otro.

Pasa a aceptar un `licenseId` opcional y usarlo cuando venga. Sin él, el match
por fechas debe ser inequívoco: se acota a las licencias todavía no aprobadas
y, si aparece más de una candidata, devuelve 409 indicando resolverla desde el
listado de solicitudes. Hoy elige una en silencio; con esto, ante la duda no
elige.

**Todo se consume como Vacaciones.** El frontend manda `type: "Vacaciones"`
fijo, y ese valor va a `ConsumoLicencias.tipo`: una licencia por Nacimiento
aprobada desde ese panel descuenta días de vacaciones. El tipo pasa a salir de
la `License` encontrada; el del payload queda solo como respaldo para el alta.

**El fallback crea la licencia a nombre del supervisor.** Si no encuentra
match usa el `employeeId` del payload, que es el del mensaje -- y el mensaje
está dirigido al supervisor. Crea y aprueba una licencia atada a la persona
equivocada. Pasa a cortar con un error explicando que no se encontró la
solicitud: toda solicitud pasa por `create_license_request`, que siempre crea
la `License`, así que la ausencia de match indica un problema real, y crear
adivinando el dueño es peor que avisar.

### Unidad 5 — La pantalla

Pestaña en el legajo, junto a "Feedback 360°" y "Alertas de tolerancia",
visible solo con `licencias.cargaInicial`.

Dos bloques:

- **Acumulables** — Vacaciones, una fila por año: el año calendario en curso y
  los dos anteriores. Al escribir esta spec, 2026, 2025 y 2024.
- **Anuales** — las demás categorías, solo el año en curso. Cargar años viejos
  de algo que no se arrastra no tendría efecto.

La ventana se define por año calendario, no por el ciclo que usa la expiración
-- que arranca en octubre y hoy vale 2025. Son cosas distintas a propósito: la
ventana dice qué se puede cargar, el ciclo dice qué vence. Los tres años
cargables caen dentro de lo que el saldo ya muestra (`anio >= 2023`), así que
todo lo que se cargue se ve.

Cada fila es un campo numérico que distingue vacío de cero, según los tres
estados de la Unidad 1. Los cambios se acumulan y se guardan con un botón, no
una request por casillero.

La pestaña es transitoria. Cuando termine la migración se le quita el permiso
al rol y desaparece para todos sin tocar código ni redesplegar; el borrado del
código queda para después, sin apuro.

### Unidad 6 — Documento de ayuda

Un botón con signo de admiración en la pantalla de licencias abre un modal con
la misma estructura y tono que `ComoSeCalculaModal` del panel estadístico: el
lector es una autoridad, no un desarrollador.

Cubre el mecanismo, que es lo verificable contra el código: cómo se forma el
saldo, por qué Vacaciones vence a los tres años y las demás no, por qué algunas
licencias solo las ve RRHH o un género, y el circuito solicitud → aprobación
del supervisor → consumo.

Los días de cada tipo se leen de la configuración en vivo en vez de escribirse
en el texto, así que el documento no queda desactualizado cuando RRHH cambia un
tope.

## Manejo de errores

La carga valida antes de escribir y devuelve el motivo: días negativos, año
fuera de la ventana, categoría inexistente. Guardar dos veces el mismo
`(empleado, año, categoría)` corrige el valor en lugar de duplicarlo.

Los tres cortes nuevos de `/aplicar` devuelven un motivo legible en vez de
fallar en silencio o acertar por casualidad.

## Testing

Las piezas con decisión se aíslan como funciones puras y los endpoints siguen
el patrón `FakeSession` que ya usa la suite.

- El saldo inicial reemplaza al total de ese año y categoría, y el consumo
  posterior lo descuenta.
- Vacío y cero dan resultados distintos. Es el caso que más fácil se rompe al
  refactorizar y el que peor falla: confundirlos otorga días que no existen.
- Un año sin fila de configuración igual aparece si tiene saldo cargado.
- El catálogo de carga respeta los filtros de género y rol.
- `/aplicar`: match ambiguo corta con 409, sin match corta con error, y el tipo
  sale de la licencia y no del payload.
- Los dos endpoints nuevos exigen `licencias.cargaInicial`.

`FakeSession` no ejecuta SQL real, así que los nombres de columna se verifican
aparte contra `INFORMATION_SCHEMA` al escribir las consultas — como ya se
confirmó el esquema de las tres tablas involucradas.

## Fuera de alcance

- Extender el arrastre a otras categorías. Solo Vacaciones se acumula.
- Reconstruir el historial de licencias ya tomadas. Se carga el saldo
  pendiente, no el consumo pasado.
- Rediseñar el circuito de `/aplicar`. Se corrigen sus defectos; el camino
  correcto sigue siendo `PATCH /licenses/requests/{id}/status`, que recibe el
  id de la licencia directamente.
- El encuadre normativo de cada licencia en el documento de ayuda.
- `get_tipos_para_contrato` (`licenses.py`) es código muerto y referencia una
  constante inexistente. Se deja anotado; no se toca en este trabajo.

## Restricciones vigentes

- **Nunca escribir en la base ObraSocial.** Todo acceso a
  `[ObraSocial].[dbo].*` es de sólo lectura. Las tablas de este trabajo van en
  RRHH.
- Cero IDs de rol hardcodeados. La autorización siempre vía
  `require_permission(...)`.
