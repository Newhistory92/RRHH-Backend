# Módulo de Asistencia — Refactor del motor e integridad de datos

**Fecha:** 2026-08-03
**Estado:** aprobado
**Bloque:** A de 3 (ver "Alcance")

## Problema

El tablero muestra 0 horas acumuladas para todos los empleados. El diagnóstico
contra la base de producción encontró tres causas independientes, dos de ellas
más graves que el síntoma reportado.

### 1. `JornadaDiaria` está vacía

Cero filas. El recálculo nunca se ejecutó: el job nocturno corre a las 3 AM y
requiere que el servidor esté vivo a esa hora, y `recalcular_historia` solo se
dispara *al asignar* un `biometricoId` — pero los cinco IDs vinculados ya
estaban cargados antes de que ese disparador existiera. No falta lógica de
cálculo: falta un disparador manual y una detección de huecos.

### 2. El histórico de marcaciones está truncado

`Marcacion` contiene 2.316 filas del 30/06 al 03/08, pero la distribución de
inserciones revela que no son un mes de operación normal:

| Insertado el | Filas | Eventos que cubre |
|---|---|---|
| 30/07 08:00 | 1.847 | 30/06 → 30/07 |
| 31/07 | 111 | 31/07 |
| 03/08 | 359 | 31/07 → 03/08 |

Las 1.847 filas del 30/07 son la carga inicial de `DIAS_CARGA_INICIAL = 30`
(`reloj_sync.py:28`): un único pedido de 30 días. Y vino incompleta. El
`serialNo` es el correlativo interno del reloj y sirve de testigo:

| Reloj | Período | Filas | Rango del correlativo | % capturado |
|---|---|---|---|---|
| 10.25.2.24 | antes 30/07 | 1.170 | 15.887 | 7,4% |
| 10.25.2.24 | desde 30/07 | 530 | 2.099 | 25,3% |
| 10.25.2.25 | antes 30/07 | 450 | 6.114 | 7,4% |
| 10.25.2.25 | desde 30/07 | 167 | 770 | 21,7% |

El porcentaje absoluto no equivale a marcaciones perdidas — el correlativo
también numera eventos que el filtro descarta (`major != 5`, `minor != 38`).
La comparación válida es la relativa: mismo equipo, mismo filtro, y el sync
incremental captura tres veces más denso que la carga inicial. La ventana de
30 días superó algún tope del equipo y el bucle cortó antes de terminar.

Consecuencia medible: el 70% de los días-persona tiene una sola marcación,
contra ~15-20% en los días con sync incremental sano. Calcular saldos sobre
ese período produciría jornadas incompletas y ausencias falsas para casi todo
el personal.

### 3. Bugs del motor sobre datos válidos

- **Rebote de dedo.** `_extremos()` toma la primera y la última marcación del
  día. El biométrico 238 marcó tres veces entre `08:09:21` y `08:09:24`: el
  motor lo lee como jornada de tres segundos y genera −6 h de deuda falsa.
- **Empleado sin cronograma.** Dos de los cinco vinculados tienen
  `cronogramaId = NULL`. Caen en `sin_horario` con saldo 0 y nadie se entera.
- **Marca única.** Queda en `incompleta` con saldo 0, sin distinguirse de otras
  causas ni señalar qué extremo falta.

## Alcance

### Entra en este bloque

Corregir el motor y la integridad de los datos, y dejar los cimientos que los
bloques siguientes necesitan.

### No entra

- **Bloque B — justificación de ausencias:** tabla de justificaciones,
  documentación adjunta, vínculo con licencias posteriores, restitución de
  horas descontadas.
- **Bloque C — UX del empleado:** timeline colapsable por mes, taxonomía
  extendida de estados diarios con badges, indicador de abuso de tolerancia,
  quitar los acumulados del dashboard del empleado.

B depende de A: el saldo debe ser correcto antes de restituirlo. C depende de
A y B: la interfaz muestra los estados que ellos producen.

## Decisiones

| Decisión | Elección | Motivo |
|---|---|---|
| Fecha de arranque | **30/07/2026** | Descartar el período truncado. Mejor poco dato verdadero que mucho dato falso. |
| Marca única | Saldo **0** + incidencia visible | No inventa horas ni castiga al empleado por una falla del reloj. |
| Rebote | Colapsar dentro de **5 minutos** | Cubre reintentos por lectura fallida sin fusionar entrada con salida real. |
| Sin cronograma | Saldo **0** + incidencia para RRHH | No inventa una jornada que nadie definió; hace visible el agujero. |
| Referencia entre tablas | Clave natural `(employeeId, fecha)` | Preserva la propiedad de que `JornadaDiaria` es derivada y desechable. |
| Normalización | Módulo puro separado | Interpretar marcaciones y calcular saldo son responsabilidades distintas. |
| Disparo del recálculo | Endpoint + botón + auto-reparación | Cubre el modo de falla que dejó la tabla vacía. |
| Auditoría | Datos propios fuera + log de corridas | El `DELETE`+`INSERT` no puede tocar lo que no es derivado. |

### Consecuencia de arrancar el 30/07

Desde esa fecha hay dos días hábiles completos (30/07 y 31/07), el sábado
01/08 y el lunes 03/08 en curso. El módulo mostrará muy poco al principio.
El endpoint de re-sincronización queda disponible para recuperar junio y julio
desde los relojes más adelante; `fechaInicioModulo` pasa a ser editable para
que RRHH pueda moverla hacia atrás cuando esos datos existan.

## Arquitectura

```
Marcacion (cruda)
      │
      ▼
marcaciones_norm.py   ── puro ──  dedup 5 min, clasificación, incidencias
      │  ExtremosDia
      ▼
asistencia_calc.py    ── puro ──  tolerancia, permisos, saldo del día
      │  ResultadoDia
      ▼
asistencia_recalc.py  ── I/O  ──  carga insumos, reemplaza el rango, loguea
      │
      ▼
JornadaDiaria + JornadaIncidencia   (derivadas, desechables)
JornadaCorreccion                   (dato propio, sobrevive)
RecalculoLog                        (auditoría)
```

La dependencia es de una sola dirección: `asistencia_calc` importa de
`marcaciones_norm`, nunca al revés. Los dos módulos son puros y se testean sin
base de datos.

### Archivos

| Archivo | Acción |
|---|---|
| `app/services/marcaciones_norm.py` | crear |
| `app/services/asistencia_calc.py` | modificar |
| `app/services/asistencia_recalc.py` | modificar |
| `app/services/reloj_sync.py` | modificar |
| `app/database/asistencia_auditoria.py` | crear |
| `app/database/asistencia.py` | modificar |
| `app/routes/asistencia.py` | modificar |
| `app/routes/relojes.py` | modificar |
| `app/scheduler.py` | modificar |
| `tests/test_marcaciones_norm.py` | crear |
| `tests/test_asistencia_calc.py` | modificar |
| `tests/test_reloj_sync.py` | modificar |

## Modelo de datos

DDL idempotente, cada sentencia en su propio batch con su `commit()`, siguiendo
el patrón ya establecido en `app/database/asistencia.py`.

### `JornadaCorreccion` — dato propio

Sobrevive al recálculo. Es la fuente de verdad de las cargas manuales de RRHH.

```sql
IF OBJECT_ID('JornadaCorreccion','U') IS NULL
CREATE TABLE JornadaCorreccion (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    employeeId   INT           NOT NULL,
    fecha        DATE          NOT NULL,
    entrada      DATETIME2     NULL,
    salida       DATETIME2     NULL,
    corregidoPor INT           NOT NULL,
    corregidoAt  DATETIME2     NOT NULL,
    observacion  NVARCHAR(500) NULL,
    CONSTRAINT UQ_JornadaCorreccion UNIQUE (employeeId, fecha)
);
```

### `JornadaIncidencia` — derivada

Se reconstruye en cada recálculo junto con la jornada.

```sql
IF OBJECT_ID('JornadaIncidencia','U') IS NULL
CREATE TABLE JornadaIncidencia (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    employeeId  INT           NOT NULL,
    fecha       DATE          NOT NULL,
    tipo        NVARCHAR(30)  NOT NULL,
    detalle     NVARCHAR(300) NULL,
    detectadoAt DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaIncidencia UNIQUE (employeeId, fecha, tipo)
);
```

Tipos: `falta_salida`, `falta_entrada`, `sin_cronograma`, `rebote_descartado`.

### `RecalculoLog` — auditoría

```sql
IF OBJECT_ID('RecalculoLog','U') IS NULL
CREATE TABLE RecalculoLog (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    origen       NVARCHAR(20)  NOT NULL,
    disparadoPor INT           NULL,
    employeeId   INT           NULL,
    desde        DATE          NULL,
    hasta        DATE          NULL,
    procesados   INT           NOT NULL DEFAULT 0,
    filas        INT           NOT NULL DEFAULT 0,
    errores      NVARCHAR(MAX) NULL,
    iniciadoAt   DATETIME2     NOT NULL,
    finalizadoAt DATETIME2     NULL
);
```

`origen`: `manual`, `nocturno`, `arranque`, `evento`. `employeeId` nulo indica
corrida masiva.

### Cambios en `JornadaDiaria`

Se agregan dos columnas que este bloque escribe pero no consume. Sin ellas el
bloque C no podría detectar el abuso de tolerancia sin recalcular todo de nuevo.

```sql
IF COL_LENGTH('JornadaDiaria','toleranciaEntradaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaEntradaUsada BIT NOT NULL DEFAULT 0;

IF COL_LENGTH('JornadaDiaria','toleranciaSalidaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaSalidaUsada BIT NOT NULL DEFAULT 0;
```

Se eliminan las tres columnas que son dato propio y se mudan a
`JornadaCorreccion`: `corregidoPor`, `corregidoAt` y `observacion`.

`entradaManual` y `salidaManual` **se conservan**: son derivadas — se
recalculan leyendo `JornadaCorreccion` en cada corrida — y tenerlas en la fila
evita un join en cada lectura del detalle diario. Es la misma categoría que el
resto de `JornadaDiaria`: información reconstruible desde sus fuentes.

La tabla está vacía, así que no hay datos que migrar. En SQL Server hay que
soltar primero el constraint de default:

```python
def _drop_columna(db: Session, tabla: str, columna: str) -> None:
    """
    tabla y columna son constantes del propio código, nunca entrada del
    usuario: la interpolación no expone inyección.
    """
    db.execute(text(f"""
        IF COL_LENGTH('{tabla}','{columna}') IS NOT NULL
        BEGIN
            DECLARE @c NVARCHAR(200);
            SELECT @c = dc.name
            FROM sys.default_constraints dc
            JOIN sys.columns c ON c.object_id = dc.parent_object_id
                              AND c.column_id = dc.parent_column_id
            WHERE dc.parent_object_id = OBJECT_ID('{tabla}')
              AND c.name = '{columna}';
            IF @c IS NOT NULL
                EXEC('ALTER TABLE {tabla} DROP CONSTRAINT ' + @c);
            ALTER TABLE {tabla} DROP COLUMN {columna};
        END
    """))
    db.commit()
```

### Fecha de arranque

`fechaInicioModulo` pasa a 30/07/2026. **No** se cambia dentro de
`ensure_tables`: una sentencia que corre en cada arranque volvería a empujar la
fecha hacia adelante si RRHH la mueve hacia atrás tras una re-sincronización.
Se aplica una vez, a mano, y se expone en el endpoint de configuración:

```sql
UPDATE AsistenciaConfig
SET fechaInicioModulo = '2026-07-30', updatedAt = GETDATE()
WHERE id = 1;
```

El seed para instalaciones nuevas mantiene su lógica actual (la marcación más
antigua registrada).

## Normalización de marcaciones

`app/services/marcaciones_norm.py`. Puro: sin imports de base de datos.

```python
VENTANA_REBOTE_MIN = 5

INCIDENCIA_FALTA_SALIDA    = "falta_salida"
INCIDENCIA_FALTA_ENTRADA   = "falta_entrada"
INCIDENCIA_SIN_CRONOGRAMA  = "sin_cronograma"
INCIDENCIA_REBOTE          = "rebote_descartado"


@dataclass(frozen=True)
class HorarioDia:
    """horaInicio y horaFin son decimales: 8.5 es las 08:30."""
    horaInicio: float
    horaFin: float
    horasTrabajo: float


@dataclass(frozen=True)
class Correccion:
    entrada: Optional[datetime]
    salida: Optional[datetime]


@dataclass(frozen=True)
class ExtremosDia:
    entrada: Optional[datetime]
    salida: Optional[datetime]
    incidencias: tuple[str, ...]
    descartadas: int
    entrada_manual: bool
    salida_manual: bool


def deduplicar(marcaciones: list[datetime],
               ventana_min: int = VENTANA_REBOTE_MIN) -> list[datetime]:
    """
    Colapsa marcas consecutivas separadas por menos de la ventana, quedándose
    con la primera de cada grupo. La comparación es contra la última marca
    conservada, no contra la anterior cruda, para que una ráfaga larga no se
    vaya encadenando más allá de la ventana.
    """


def normalizar(marcaciones: list[datetime],
               horario: Optional[HorarioDia],
               correccion: Optional[Correccion] = None,
               ventana_min: int = VENTANA_REBOTE_MIN) -> ExtremosDia:
    """Marcaciones crudas del día -> extremos confiables más sus incidencias."""
```

`HorarioDia` se muda desde `asistencia_calc.py` a este módulo, que es el de
nivel más bajo. `asistencia_calc` lo importa desde acá.

### Reglas

**Deduplicación.** Marcas separadas por menos de `ventana_min` colapsan en la
primera. `descartadas` cuenta cuántas se fusionaron; si es mayor que cero se
emite `rebote_descartado` como incidencia informativa.

**Dos o más marcas tras deduplicar.** La primera es entrada, la última es
salida. Sin incidencias.

**Una sola marca tras deduplicar.** Se compara su distancia a `horaInicio`
contra su distancia a `horaFin`:

- más cerca del inicio → es entrada, `salida = None`, incidencia `falta_salida`
- más cerca del fin, o empate → es salida, `entrada = None`, incidencia
  `falta_entrada`

El empate se resuelve hacia salida porque los datos muestran más marcas únicas
vespertinas que matutinas (636 contra 459).

**Sin horario.** No se puede clasificar: la primera marca se toma como entrada
y la última como salida si hay dos o más. Se emite `sin_cronograma`.

**Corrección de RRHH.** Pisa lo que diga el reloj. Cada extremo cargado
manualmente marca su flag (`entrada_manual` / `salida_manual`) y elimina la
incidencia correspondiente. Una corrección que aporta el extremo faltante deja
el día sin incidencias.

## Motor de cálculo

`app/services/asistencia_calc.py` deja de interpretar marcaciones crudas.
`_extremos()` se elimina; `_ajustar_por_tolerancia()` pasa a informar si aplicó
la tolerancia.

```python
@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    extremos: ExtremosDia          # reemplaza marcaciones/entrada_manual/salida_manual
    horario: Optional[HorarioDia]
    es_feriado: bool
    tiene_licencia: bool
    permisos: list[Permiso]


@dataclass(frozen=True)
class ResultadoDia:
    fecha: date
    estado: str
    horasRequeridas: float
    horasTrabajadas: float
    saldoDia: float
    entrada: Optional[datetime]
    salida: Optional[datetime]
    permisoBanco: float
    permisoDeuda: float
    permisoOficial: float
    incidencias: tuple[str, ...]           # nuevo
    toleranciaEntradaUsada: bool           # nuevo
    toleranciaSalidaUsada: bool            # nuevo
    entradaManual: bool                    # nuevo, viene de ExtremosDia
    salidaManual: bool                     # nuevo, viene de ExtremosDia
```

Las reglas de saldo no cambian respecto de la implementación actual:

- Ausencia en día hábil sin licencia ni feriado: `saldoDia = -horasTrabajo`
- Día con un solo extremo: estado `incompleta`, saldo 0
- Sin horario: estado `sin_horario`, saldo 0
- Feriado o fin de semana con marcas: todo lo trabajado es saldo a favor
- Licencia aprobada: neutro
- Permisos oficiales: neutros; los regulares consumen el banco anual de 12 h

Los estados siguen siendo los seis actuales. El bloque C derivará su taxonomía
extendida (`llegada_tarde`, `salida_temprana`, `tolerancia_usada`, `overtime`)
a partir de los campos que este bloque persiste, sin recalcular.

## Recálculo, auto-reparación y auditoría

`recalcular_anio` mantiene el `DELETE`+`INSERT` sobre `JornadaDiaria` y lo
extiende a `JornadaIncidencia`. El cambio de fondo: las correcciones ya no se
releen desde `JornadaDiaria` antes de borrarla, sino desde `JornadaCorreccion`,
que el borrado no toca. Se elimina `_correcciones_por_dia()` en su forma actual
y se reemplaza por una lectura de la tabla nueva.

Del otro lado, `marcar_correccion()` pasa a hacer un upsert sobre
`JornadaCorreccion` por `(employeeId, fecha)` en lugar de un `UPDATE` sobre
`JornadaDiaria`. La corrección queda persistida antes de que el recálculo
regenere la jornada, y sobrevive a todas las corridas posteriores.

Toda corrida abre una fila en `RecalculoLog` con `iniciadoAt` y la cierra con
`finalizadoAt`, `procesados`, `filas` y `errores` serializados en JSON.

**Detección de huecos al arrancar.** Un job one-shot programado a los 30
segundos del arranque — no bloquea el startup — busca días hábiles entre
`fechaInicioModulo` y hoy sin fila en `JornadaDiaria`, para empleados con
`biometricoId` no nulo, y recalcula los años afectados. Queda registrado con
`origen = 'arranque'`. Es la red que atrapa el modo de falla original.

Se conservan sin cambios el job nocturno de las 3 AM y los disparadores por
evento (alta de permiso, cambio de horario, aprobación o rechazo de licencia,
asignación de `biometricoId`).

## Sincronización de relojes

`app/services/reloj_sync.py`. Los equipos siguen tratándose como **solo
lectura**: la allowlist de `isapi_client.py` no se modifica.

**Carga inicial por ventanas diarias.** `calcular_ventana` deja de devolver un
único rango de 30 días. Cuando no hay sync previa, `sincronizar_reloj` itera
día por día desde `DIAS_CARGA_INICIAL` hasta hoy, con una llamada paginada por
día. Es la corrección directa de la causa del truncamiento.

**Detección de truncamiento.** Si una ventana devuelve exactamente el tope de
resultados y el equipo no reporta `MORE`, se registra una advertencia con el
rango afectado: es el síntoma de que el equipo cortó la respuesta por su cuenta.

**Endpoint de re-sincronización.** `POST /relojes/resincronizar` con `desde` y
`hasta` obligatorios, que itera día por día sobre el rango pedido. Permite
recuperar junio y julio a mano cuando se decida. Los duplicados los descarta la
unicidad `(relojIp, serialNo)` ya existente, así que reprocesar un rango es
inofensivo.

## API

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `POST` | `/asistencia/recalcular` | RRHH/Admin | Body opcional `{employeeId?, anio?}`. Sin cuerpo: todos los empleados, año en curso. Devuelve `procesados`, `filas`, `errores`. |
| `GET` | `/asistencia/incidencias` | RRHH/Admin | Incidencias abiertas con nombre de empleado, filtrables por `tipo`, `desde`, `hasta`. |
| `GET` | `/asistencia/recalculos` | RRHH/Admin | Últimas corridas del log, más recientes primero. |
| `POST` | `/relojes/resincronizar` | RRHH/Admin | Body `{desde, hasta}` obligatorio. Itera día por día. |

`PUT /asistencia/config` acepta además `fechaInicioModulo`, validando que sea
una fecha ISO y que no sea futura.

`GET /asistencia/mi` y `GET /asistencia/empleado/{id}` agregan a cada jornada
su lista de incidencias.

## Testing

**`tests/test_marcaciones_norm.py`** (nuevo):

- rebote de tres marcas en tres segundos colapsa a una
- marcas legítimas separadas por seis minutos no colapsan
- ráfaga larga: cinco marcas de a dos minutos colapsan a una sola, no encadenan
- marca única cercana a `horaInicio` → entrada + `falta_salida`
- marca única cercana a `horaFin` → salida + `falta_entrada`
- empate exacto entre inicio y fin → salida
- sin horario → `sin_cronograma`, primera y última sin clasificar
- corrección de RRHH aportando la salida elimina `falta_salida`
- corrección de RRHH pisa el valor del reloj y marca el flag
- día sin marcaciones ni corrección → ambos extremos en `None`, sin incidencias

**`tests/test_asistencia_calc.py`** (modificar): los 22 tests actuales se
adaptan a construir `EntradaDia` con `ExtremosDia` en lugar de marcaciones
crudas. Se agregan casos para `toleranciaEntradaUsada` y `toleranciaSalidaUsada`
en los cuatro cruces posibles (dentro y fuera de tolerancia, en cada extremo).

**`tests/test_reloj_sync.py`** (modificar): la carga inicial sin sync previa
emite una llamada por día del rango; una ventana que devuelve el tope exacto de
resultados sin `MORE` registra la advertencia de truncamiento.

Los tests no tocan la base ni los relojes: `marcaciones_norm` y
`asistencia_calc` son puros, y `reloj_sync` se prueba con el cliente ISAPI
mockeado, como ya lo hace la suite actual.

## Riesgos y limitaciones

**Solo dos días hábiles de datos confiables.** Hasta que pase un par de
semanas, o hasta que se re-sincronice el histórico, el balance será poco
informativo. Es una limitación aceptada al elegir la fecha de arranque.

**169 biométricos sin empleado vinculado.** De los 174 que marcan, solo 5
tienen `Employee.biometricoId` cargado. Es carga de datos de RRHH, fuera del
alcance de este bloque, pero `GET /asistencia/incidencias` los expondrá para
que se vea el tamaño real del problema.

**Causa exacta del truncamiento no confirmada en el equipo.** La evidencia
apunta a un tope del dispositivo sobre la ventana de búsqueda, pero no se probó
contra el firmware. La corrección — ventanas diarias más detección de tope — es
válida en cualquiera de los escenarios posibles, y la advertencia dejará
registro si el problema persiste.

**Reinicio del correlativo.** El riesgo ya documentado en `reloj_sync.py:130`
se mantiene: si un equipo reinicia su `serialNo`, los eventos nuevos colisionan
con los viejos y se descartan en silencio. Fuera de alcance; la advertencia
existente se conserva.
