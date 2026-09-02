# Productividad configurable sobre LogSistema

**Fecha:** 2026-09-02
**Estado:** aprobado para planificar

## Objetivo

Que una persona con permiso de administración decida, tildando en una pantalla,
qué acciones del sistema de gestión cuentan como trabajo para el score de
productividad — y que el score se calcule sobre esa decisión en vez de sobre la
fuente equivocada que usa hoy.

## Por qué existe

El score hoy se calcula sobre `[ObraSocial].[dbo].[UsuarioAccesoLogs]`. Esa
tabla no registra trabajo: registra altas y bajas de permisos. Sus filas dicen
"Asignación de acceso por rol AuditoriaMedica" o "Anulación de acceso". Son
~2.500 filas históricas y las genera quien administra accesos, no quien atiende
afiliados.

Es decir que el número que hoy aparece como productividad de una persona no
mide su trabajo. Mide cuántas veces le tocaron los permisos.

La actividad real vive en `[ObraSocial].[dbo].[LogSistema]`, que registra cada
request al sistema de gestión.

### Mediciones sobre los datos reales (2026-09-02)

| Métrica | `UsuarioAccesoLogs` | `LogSistema` |
|---|---|---|
| Filas | ~2.500 | 88.666 |
| Rango | — | 2026-03-04 a 2026-09-02 |
| Usuarios distintos | un puñado | 943 |
| Campos útiles | `codigoAcceso`, `Log` | `metodo`, `url`, `statusCode`, `tiempoRespuestaMs`, `idUsuario`, `nombreUsuario` |

De las 88.666 filas de `LogSistema`:

- **34.816 (39%) tienen `idUsuario` NULL.** Son requests sin sesión — los 401 de
  `/usuario/logout` y `/usuario/sesion-vigente`. No son atribuibles a nadie.
- Quedan **53.850 atribuibles**, repartidas en POST 24.067, GET 23.632,
  PUT 5.961, DELETE 147, JOB 42, HEAD 1.
- De esas, sólo **28.913 son 2xx exitosas**. Hay 13.063 3xx, 11.282 4xx y 592 5xx.
- Las cuentas `prueba` (18.104 hits) y `test` (8.406) encabezan el ranking. No
  están vinculadas a empleados de RRHH, así que caen solas al cruzar identidades.

Sobre la forma de las URLs:

- 8.514 combinaciones crudas de `metodo` + `url`.
- Tras normalizar (sacar query string, colapsar IDs y GUIDs a `:id`) quedan
  **1.830 rutas**.
- **Las 25 rutas más usadas concentran el 79% del volumen**; las 100 primeras,
  el 90,6%. La cola larga es irrelevante en la práctica.

Ejemplos que muestran por qué la granularidad de ruta es necesaria:
`POST /usuario/login-app` es la ruta #1 con 13.965 hits y es ruido puro;
`POST /afiliado/nueva-consulta` (3.644) y `POST /internacion/crear-internacion`
(269) son trabajo. Las tres son POST, y dos de ellas viven bajo `/usuario` y
`/afiliado` respectivamente, así que ni el verbo ni el módulo alcanzan para
separarlas.

## Alcance de la mejora, y su techo

Esto mejora sustancialmente lo que hay: pasa de ~2.500 filas que no son trabajo
a ~29.000 filas que sí lo son, con granularidad suficiente para distinguir
crear una internación de loguearse.

El techo que **no** rompe, y que debe seguir comunicándose en la interfaz:

- Sigue midiendo actividad en un sistema, no productividad. Quien trabaja por
  ventanilla, teléfono o papel da cero, igual que hoy.
- Un request no equivale a otro. El tilde resuelve *qué* cuenta, no *cuánto
  vale*. La columna de peso queda preparada para atacar esto más adelante.
- `LogSistema` arranca el 2026-03-04. La ventana del score es de 12 meses, así
  que durante los próximos meses la ventana está parcialmente vacía.

## Decisiones tomadas

| Decisión | Elegido | Por qué |
|---|---|---|
| Fuente del score | Migrar a `LogSistema` | La fuente actual no mide trabajo |
| Unidad tildable | Método + ruta normalizada | Única granularidad que separa login de trabajo real |
| Ruta nueva sin clasificar | No cuenta, y la pantalla avisa | Nada entra al score sin decisión humana; el aviso evita que la omisión pase inadvertida |
| Alcance de pantalla | Rutas + explorador de logs crudos | Sin ver los logs se tilda a ciegas una ruta cuyo nombre no alcanza |
| Ubicación | Tab en Administración | Coherente con agrupar en tabs en vez de sumar entradas al sidebar |
| Status | Sólo 2xx | Un 401 en loop o un 500 no es trabajo; contarlos premiaría los loops de error |
| Peso | Binario en UI, columna decimal | Permite pesos después sin migrar datos ni reescribir el cálculo |

## Arquitectura

### Unidad 1 — Normalización de rutas

Función pura, sin I/O. Recibe una URL cruda y devuelve la ruta canónica.

- Descarta el query string (todo lo que sigue al primer `?`).
- Reemplaza por `:id` cada segmento que sea íntegramente numérico o que tenga
  forma de GUID.

`/orden/123?detalle=1` y `/orden/456` colapsan ambos a `/orden/:id`.

Es la pieza que hace viable el tilde: sin ella habría 8.514 filas que tildar en
vez de 1.830.

### Unidad 2 — Persistencia de la configuración

Tabla nueva **en la base de RRHH**. ObraSocial permanece de sólo lectura, sin
excepción: no se le crea ni modifica nada.

```
RutaProductividad
  id              int identity PK
  metodo          nvarchar(10)   not null
  ruta            nvarchar(500)  not null
  peso            decimal(5,2)   not null default 0
  clasificadoPor  int            null   -- employeeId de quien decidió
  clasificadoEn   datetime2      null
  notas           nvarchar(500)  null
  UNIQUE (metodo, ruta)
```

Tres estados, no dos:

- **Sin fila** → pendiente de clasificar. No suma. Es lo que la pantalla
  destaca como novedad a revisar.
- **Fila con `peso = 0`** → decisión tomada de que no cuenta. No suma, y no
  vuelve a aparecer como pendiente.
- **Fila con `peso > 0`** → cuenta. La UI de esta etapa escribe siempre 1.

La distinción entre "sin fila" y "peso 0" es deliberada: una ruta que nadie
miró y una ruta que alguien decidió excluir tienen el mismo efecto sobre el
score pero requieren acciones distintas del administrador.

Se crea con el mismo patrón `ensure_*` que ya usa `ScoreHistorico`.

### Unidad 3 — Endpoints

Los tres bajo `require_permission("admin.gestionar")`.

**`GET /admin/logs/rutas`** — catálogo para la vista de configuración.

Agrega `LogSistema` por método y ruta normalizada (sólo filas con `idUsuario`
no nulo), y cruza el resultado contra `RutaProductividad`. Por cada ruta
devuelve: método, ruta, volumen, usuarios distintos, última vez vista y estado
(`cuenta` / `no_cuenta` / `pendiente`). Ordenado por volumen descendente.

La normalización ocurre en Python sobre el agregado crudo, no en SQL: la lógica
de colapsar IDs es la misma función pura de la Unidad 1, y duplicarla en T-SQL
la volvería imposible de mantener en sincronía.

**`PUT /admin/logs/rutas`** — guarda tildes en lote. Recibe una lista de
`{metodo, ruta, cuenta}` y hace upsert por la clave `(metodo, ruta)`,
registrando quién y cuándo. El booleano `cuenta` se traduce a la columna
decimal: `true` escribe `peso = 1`, `false` escribe `peso = 0`. La API expone
el booleano y no el peso porque en esta etapa la interfaz es binaria; cuando
llegue la etapa de pesos, el endpoint aceptará el número sin cambiar la tabla.
En lote porque el flujo real es tildar veinte
rutas de una pasada, y un request por fila multiplicaría los viajes sin dar
nada a cambio.

**`GET /admin/logs`** — explorador crudo, paginado. Filtros por rango de
fechas, usuario, método, clase de status y texto contenido en la URL. Devuelve
las columnas de la tabla tal como están, sin normalizar: el objetivo es
inspeccionar qué pasó realmente.

### Unidad 4 — El cálculo del score

`calculate_productivity_scores` cambia de fuente. La consulta nueva:

- lee `LogSistema` en lugar de `UsuarioAccesoLogs`
- descarta `idUsuario IS NULL`
- se queda sólo con `statusCode` entre 200 y 299
- conserva el cooldown anti-spam de 3 segundos que ya existe hoy
- filtra por las rutas con `peso > 0`, cruzando contra la config de RRHH

El resto de la cadena no se toca: la vinculación de identidades por DNI y por
`User.id`, el cálculo de eventos sobre horas efectivas del reloj, el promedio
para áreas exentas y el registro en `ScoreHistorico` siguen igual.

Como las dos bases son distintas y no se pueden unir en una sola consulta, el
filtro de rutas se aplica en Python: se traen las rutas habilitadas de RRHH y
se cruzan contra el agregado de ObraSocial en memoria. El volumen lo permite
holgadamente.

**Versionado.** Se registra como fórmula `eventos_logsistema_v2`, sumándose a
las dos que ya existen. Sin esto, el histórico calculado sobre auditoría de
permisos y el nuevo quedarían mezclados en el mismo gráfico de trayectoria, y
un salto por cambio de método de medición se leería como cambio de desempeño de
la persona.

**Retroactividad.** Tildar una ruta recalcula los 12 meses de la ventana, no
sólo lo que viene: el score se rehace de cero en cada corrida. Es la conducta
correcta — la clasificación describe qué *es* trabajo, y eso no cambia según
cuándo se tildó — pero tiene que estar dicha en la pantalla para que nadie se
sorprenda.

### Unidad 5 — La pantalla

Tab **Productividad** dentro de Administración, con dos vistas.

**Vista Rutas.** Tabla ordenada por volumen descendente: método, ruta, volumen,
usuarios distintos, última vez, y el check. Cuando hay rutas sin clasificar,
un aviso arriba con la cantidad y un atajo para filtrar por ellas. Filtros por
estado y por método. Los cambios se acumulan y se guardan con un botón, no
request por tilde.

Junto al botón de guardar, uno de **recalcular ahora**, que dispara la misma
rutina que corre el scheduler. Sin él, alguien tilda veinte rutas y no ve
ningún efecto hasta la corrida de la noche siguiente, lo que se lee como que la
pantalla no funciona.

**Vista Logs.** La tabla cruda: fecha, usuario, método, URL, status, tiempo de
respuesta. Filtros por fecha, usuario, método, clase de status y texto en la
URL. Desde una fila se puede saltar a clasificar su ruta en la otra vista.

## Manejo de errores

ObraSocial es una fuente secundaria y ya hay precedente de cómo tratarla: el
job del scheduler no propaga excepciones, porque que esa base no responda no
puede tumbar el resto de los jobs. Se mantiene ese criterio.

En la pantalla, si el agregado de ObraSocial falla, la vista de rutas muestra
la configuración guardada con el volumen en blanco y un aviso de que no se pudo
leer la actividad. Se puede seguir clasificando: la configuración vive en RRHH
y no depende de la otra base.

El recálculo manual devuelve el resultado de la corrida, y si falla lo dice con
el motivo en vez de quedarse en silencio.

## Testing

Las piezas con lógica son puras y se testean con tablas de casos tomados de los
datos reales ya medidos:

- **Normalización de URLs:** query strings, segmentos numéricos, GUIDs, rutas
  sin ID, el caso `/cron/:id`, y URLs con ID en posición intermedia.
- **Cruce catálogo–configuración:** que una ruta sin fila salga `pendiente`,
  una con peso 0 salga `no_cuenta`, y una con peso 1 salga `cuenta`.
- **Filtrado del score:** que las filas con `idUsuario` nulo, las que no son
  2xx y las de rutas no habilitadas queden afuera del conteo.

Los endpoints siguen el patrón de `FakeSession` que ya usa la suite. Ese patrón
no ejecuta SQL real, así que los nombres de columna contra ObraSocial se
verifican aparte contra `INFORMATION_SCHEMA` al escribir las consultas — ya
hubo un caso en este repositorio de una columna mal nombrada que los tests no
pudieron detectar.

## Fuera de alcance

- `LogSistemaResumenGET` (el tab "RESUMEN GET" del sistema de producción). Es
  una preagregación de GET por día y ruta; sumarla obligaría a conciliar dos
  fuentes con criterios distintos.
- Estadísticas por usuario dentro de este tab. Ya viven en Estadísticas, entre
  Indicadores por persona y la ficha de Mérito.
- Pesos por ruta en la interfaz. La columna queda lista; la UI de pesos es una
  etapa posterior.
- Purga o archivado de `LogSistema`. Es de otro sistema y de sólo lectura.

## Restricciones vigentes

- **Nunca escribir en la base ObraSocial.** Todo acceso a
  `[ObraSocial].[dbo].*` es de sólo lectura. La tabla de configuración va en
  RRHH.
- Cero IDs de rol hardcodeados. La autorización siempre vía
  `require_permission(...)`.
