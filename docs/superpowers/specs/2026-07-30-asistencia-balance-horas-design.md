# Módulo de Asistencia y Balance de Horas — Diseño

**Fecha:** 2026-07-30
**Subsistema:** capa de cálculo sobre el conector de relojes biométricos ISAPI
**Depende de:** `Marcacion`, `Employee.biometricoId`, `Horario`, `Feriado`, `License`, `Permission`

## Objetivo

Convertir las marcaciones crudas de los relojes Hikvision en un balance de horas
por empleado: cuánto trabajó contra cuánto debía trabajar, acumulado sin corte de
período. RRHH obtiene un tablero con las jornadas que necesitan intervención
manual; el empleado ve su propio saldo y desglose diario.

## Arquitectura

Enfoque **precalculado con recálculo por disparadores explícitos**.

Una tabla `JornadaDiaria` guarda una fila por empleado por día con el resultado
del cálculo. El saldo acumulado es un `SUM(saldoDia)`. Un motor de cálculo puro
—sin acceso a base de datos— produce cada fila a partir de las marcaciones,
el horario, los feriados, las licencias y los permisos del día.

Se descartó el cálculo on-demand por dos razones concretas:

1. El saldo es acumulado sin límite de tiempo. Recalcular desde la fecha de
   ingreso en cada consulta no escala para un tablero de todos los empleados.
2. La corrección manual de RRHH necesita persistirse, y no puede vivir en
   `Marcacion`: esa tabla es espejo de solo lectura del dispositivo.

## Modelo de datos

### `AsistenciaConfig`

Fila única (`id = 1`), editable por RRHH.

| campo | tipo | default | descripción |
|---|---|---|---|
| `id` | INT PK | 1 | siempre 1 |
| `toleranciaEntradaMin` | INT NOT NULL | 15 | margen sin penalización al entrar |
| `toleranciaSalidaMin` | INT NOT NULL | 15 | margen sin penalización al salir |
| `fechaInicioModulo` | DATE NOT NULL | fecha de la marcación más antigua en `Marcacion`, o la fecha de hoy si la tabla está vacía | no se calcula ninguna jornada anterior a esta fecha |
| `updatedAt` | DATETIME2 NOT NULL | — | |

Constantes en código, deliberadamente **no** configurables:

- `BANCO_PERMISO_ANUAL_HORAS = 12` — horas de permiso por año calendario que no
  se recuperan.
- Días hábiles: **lunes a viernes**, iguales para todos los empleados.

### `JornadaDiaria`

`UNIQUE (employeeId, fecha)`. Índice adicional por `(estado, fecha)` para el
tablero de incompletas.

| campo | tipo | descripción |
|---|---|---|
| `id` | INT IDENTITY PK | |
| `employeeId` | INT NOT NULL | |
| `fecha` | DATE NOT NULL | |
| `estado` | NVARCHAR(20) NOT NULL | `ok` / `incompleta` / `ausente` / `feriado` / `licencia` / `sin_horario` |
| `horasRequeridas` | DECIMAL(5,2) NOT NULL | jornada exigida ese día, ya neta de permisos perdonados |
| `horasTrabajadas` | DECIMAL(5,2) NOT NULL | tiempo computado, ya neto de permisos |
| `saldoDia` | DECIMAL(5,2) NOT NULL | `horasTrabajadas - horasRequeridas`; positivo a favor, negativo adeudado |
| `entrada` | DATETIME2 NULL | primera marcación (o carga manual) |
| `salida` | DATETIME2 NULL | última marcación (o carga manual) |
| `entradaManual` | BIT NOT NULL DEFAULT 0 | la entrada la cargó RRHH, no el reloj |
| `salidaManual` | BIT NOT NULL DEFAULT 0 | la salida la cargó RRHH, no el reloj |
| `permisoBanco` | DECIMAL(5,2) NOT NULL DEFAULT 0 | horas de permiso absorbidas por el banco de 12 h |
| `permisoDeuda` | DECIMAL(5,2) NOT NULL DEFAULT 0 | horas de permiso que excedieron el banco |
| `permisoOficial` | DECIMAL(5,2) NOT NULL DEFAULT 0 | horas de permiso oficial (neutras) |
| `corregidoPor` | INT NULL | `Employee.id` del usuario de RRHH que corrigió |
| `corregidoAt` | DATETIME2 NULL | |
| `observacion` | NVARCHAR(500) NULL | nota libre de la corrección |
| `calculadoAt` | DATETIME2 NOT NULL | |

### Cambio en `Permission`

Se agrega una columna, con DDL idempotente:

```sql
IF COL_LENGTH('Permission','oficial') IS NULL
ALTER TABLE Permission ADD oficial BIT NOT NULL DEFAULT 0;
```

`oficial = 0` es el permiso regular (consume el banco de 12 h). `oficial = 1`
es el permiso oficial: no consume banco, no suma ni resta al saldo.

## Motor de cálculo

Función pura en `app/services/asistencia_calc.py`. Recibe los datos de un día ya
cargados y devuelve la fila de `JornadaDiaria`. No toca la base de datos, lo que
la hace testeable sin fixtures.

### Orden de evaluación

Para el empleado `E` en la fecha `D`:

1. Si `D < config.fechaInicioModulo` → **no se genera fila**.
2. Si `D` es anterior a la `fechaIngreso` del empleado en `CondicionLaboral` →
   **no se genera fila**. Nadie acumula ausencias antes de haber ingresado.
3. Si `E.biometricoId` es `NULL` → **no se genera ninguna fila** para `E`.
   Un empleado sin vínculo al reloj no puede acumular ausencias.
4. Si `D` cae sábado o domingo, o existe un `Feriado` activo con esa fecha:
   - sin marcaciones → **no se genera fila**.
   - con marcaciones → `estado = 'feriado'`, `horasRequeridas = 0`,
     `horasTrabajadas = última marcación − primera marcación` **sin aplicar
     tolerancia** (el horario no rige un día no laborable),
     `saldoDia = +horasTrabajadas`.
5. Si `E` tiene una licencia con `License.status = 'Aprobada'` cuyo rango
   `startDate`–`endDate` cubre `D` → `estado = 'licencia'`, requeridas `0`,
   trabajadas `0`, saldo `0`.
6. Si `E` no tiene `cronogramaId` o el `Horario` referenciado no existe →
   `estado = 'sin_horario'`, requeridas `0`, saldo `0`. Se expone en el tablero
   para que RRHH cargue el horario.
7. Día hábil normal: se aplican las reglas de marcaciones, tolerancia y permisos
   que siguen.

### Marcaciones

Los empleados marcan en el **mismo reloj** al entrar y al salir. El sistema toma
la **primera** marcación del día como entrada y la **última** como salida.

| marcaciones del día | resultado |
|---|---|
| 0 | `estado = 'ausente'`, requeridas = jornada, trabajadas = 0, saldo = −jornada |
| 1 | `estado = 'incompleta'`, **saldo = 0** — no penaliza hasta que RRHH cargue el extremo faltante |
| 2 o más | se computa normalmente (primera = entrada, última = salida) |

El caso de una sola marcación es deliberadamente neutro: el empleado no queda
debiendo una jornada entera por un error del dispositivo o un olvido. La fila
aparece en `GET /asistencia/incompletas` hasta que se corrige.

### Tolerancia

Se aplica por separado a cada extremo. Con `horaInicio = 8:00`, `horaFin = 16:00`
y tolerancia de 15 minutos:

```
entradaAjustada = horaInicio  si  horaInicio < entrada <= horaInicio + toleranciaEntrada
                  entrada     en cualquier otro caso

salidaAjustada  = horaFin     si  horaFin - toleranciaSalida <= salida < horaFin
                  salida      en cualquier otro caso
```

Superada la tolerancia se descuenta **todo** el atraso, no solo el excedente.
Llegar antes de hora o retirarse después de hora **sí** acumula saldo a favor.

| entrada | salida | ajustadas | trabajadas | saldo |
|---|---|---|---|---|
| 8:10 | 16:00 | 8:00 – 16:00 | 8:00 | 0 |
| 8:20 | 16:00 | 8:20 – 16:00 | 7:40 | −0:20 |
| 8:00 | 15:50 | 8:00 – 16:00 | 8:00 | 0 |
| 8:10 | 15:50 | 8:00 – 16:00 | 8:00 | 0 |
| 7:50 | 16:10 | 7:50 – 16:10 | 8:20 | +0:20 |

### Permisos

Como el empleado marca entrada a la mañana y salida a la tarde, el reloj no
registra que se ausentó en el medio. Por eso las horas de permiso se restan
**siempre** de `horasTrabajadas`.

Se restan además de `horasRequeridas` solo cuando el permiso es oficial o cuando
entra dentro del banco de 12 h anuales:

```
jornada       = Horario.horasTrabajo del empleado

disponible    = 12 - horas de permiso regular ya consumidas en el año
permisoBanco  = min(permisoRegular, disponible)
permisoDeuda  = permisoRegular - permisoBanco

horasRequeridas = jornada - permisoOficial - permisoBanco
horasTrabajadas = (salidaAjustada - entradaAjustada) - permisoRegular - permisoOficial
```

`horasRequeridas` nunca baja de `0`: si los permisos de un día superan la jornada,
se trunca en cero y el excedente no genera crédito.

Con jornada de 8 h y un permiso de 2 h:

| situación | requeridas | trabajadas | saldo |
|---|---|---|---|
| banco con 12 h libres | 6 | 6 | 0 |
| banco agotado | 8 | 6 | −2 |
| banco con solo 1 h libre | 7 | 6 | −1 |
| permiso marcado Oficial | 6 | 6 | 0 |

El banco parcial cae solo en su lugar: queda debiendo exactamente la hora que
excedió el tope. La porción no perdonada nunca se resta de las requeridas, así
que se transforma en deuda por la vía natural del cálculo.

El banco se consume en orden cronológico y se reinicia el 1 de enero. Lo no usado
no se traslada al año siguiente.

### Saldo acumulado

```sql
SELECT SUM(saldoDia) FROM JornadaDiaria WHERE employeeId = :id
```

Sin corte de período: lo adeudado en enero sigue pesando en diciembre y se
compensa con lo trabajado de más en cualquier otro mes.

## Recálculo

La unidad de recálculo es **(empleado, año)**. Siempre se recomputa desde el
1 de enero hacia adelante, arrastrando el consumo acumulado del banco de
permisos. Existe un solo camino de código: no hay una variante incremental que
pueda desviarse del cálculo completo.

`app/services/asistencia_recalc.py` expone:

```python
def recalcular_anio(db: Session, employee_id: int, anio: int) -> int
def recalcular_historia(db: Session, employee_id: int) -> int
def recalcular_todos(db: Session, anio: int) -> dict
```

Cada una carga en bloque los insumos del empleado para el rango (marcaciones,
permisos, licencias) más los feriados —compartidos entre todos y cargados una
sola vez—, invoca el motor puro día por día y hace upsert de las filas.

### Disparadores

| evento | alcance |
|---|---|
| Job nocturno APScheduler (3 AM) | `recalcular_todos` del año en curso |
| RRHH corrige una entrada o salida | `recalcular_anio` de ese empleado |
| Se asigna o cambia `Employee.biometricoId` | `recalcular_historia` de ese empleado |
| Se aprueba, edita o borra una licencia | `recalcular_anio` de los años afectados |
| Se carga, edita o borra un permiso | `recalcular_anio` de ese empleado |

El disparador del `biometricoId` es el que preserva el comportamiento que ya
documenta `app/database/marcaciones.py`: las marcaciones huérfanas aparecen
retroactivamente al cargar el vínculo, sin necesidad de resincronizar los
relojes. Al asignar el ID se recalcula toda la historia y el saldo aparece
completo.

El job nocturno recalcula el año entero en lugar de solo el día anterior. Cuesta
más —del orden de minutos para ~200 empleados, a las 3 AM— pero se auto-repara:
cualquier inconsistencia introducida por un disparador que falló se corrige sola
en la siguiente corrida.

### Limitación conocida: cambios de horario

`horasRequeridas` se recalcula con el horario **actual** del empleado. Cambiar su
`Horario` de 8 h a 6 h reescribe el saldo del año en curso con la jornada nueva,
porque el sistema no guarda historial de horarios.

Se acepta deliberadamente. Guardar versiones de `Horario` con vigencia por rango
de fechas resolvería el problema, pero agrega complejidad que hoy no se justifica.
Si en la práctica resulta molesto, se agrega en una iteración posterior.

## API

Router `app/routes/asistencia.py`, prefijo `/asistencia`.

| método | ruta | rol | descripción |
|---|---|---|---|
| GET | `/tablero` | ADMIN, RRHH | saldo acumulado, incompletas y ausencias de todos los empleados |
| GET | `/incompletas` | ADMIN, RRHH | jornadas en estado `incompleta` o `sin_horario` que esperan intervención |
| PUT | `/jornada/{id}` | ADMIN, RRHH | carga manual de entrada y/o salida + observación; dispara recálculo |
| GET | `/empleado/{id}` | ADMIN, RRHH | desglose diario y saldo de un empleado, filtrable por año |
| GET | `/mi` | autenticado | desglose y saldo **propios**, resueltos por token |
| GET | `/config` | ADMIN, RRHH | tolerancias y fecha de inicio del módulo |
| PUT | `/config` | ADMIN, RRHH | actualiza tolerancias; dispara recálculo del año en curso |

`GET /mi` deriva el empleado del token de sesión y nunca acepta un `employeeId`
por parámetro: un usuario sin rol de RRHH no puede consultar datos ajenos.

`PUT /jornada/{id}` marca `entradaManual` o `salidaManual` según qué extremo se
cargó, registra `corregidoPor` y `corregidoAt`, y deja la `observacion`. La
corrección es auditable: queda constancia de quién intervino y cuándo.

## Frontend

Una sola clave de página `asistencia` que ramifica por rol, siguiendo el patrón
que ya usa Reubicación en `src/app/page.tsx`:

```tsx
case 'asistencia':
  return roleId === ROLE_ID.ADMIN || roleId === ROLE_ID.RRHH
    ? <AsistenciaTablero />
    : <MiAsistencia employeeData={employeeData} />;
```

### Tablero RRHH

Tabla de empleados con saldo acumulado —en verde a favor, en rojo adeudado—,
cantidad de ausencias y cantidad de jornadas incompletas del período.

Las incompletas se destacan y abren un modal donde RRHH carga la hora faltante y
una observación. Al guardar se dispara el recálculo y la fila desaparece del
listado pendiente.

### Vista del empleado

Card con el saldo acumulado y si debe o tiene horas a favor, más la tabla de
desglose diario: fecha, entrada, salida, horas trabajadas, horas requeridas y
saldo del día. Las jornadas corregidas manualmente se muestran señalizadas.

El empleado no accede a datos de terceros ni a la configuración.

## Testing

El motor de cálculo es una función pura, así que los casos difíciles se cubren
sin base de datos ni relojes en `tests/test_asistencia_calc.py`:

- tolerancia justo en el límite y justo pasada, en ambos extremos
- entrada anticipada y salida tardía acumulando saldo a favor
- banco de permisos partido al medio (el caso de `−1` de la tabla)
- permiso oficial neutro
- banco agotado convirtiendo el permiso en deuda
- arrastre cronológico del banco a lo largo de un año
- marcación única → `incompleta` con saldo 0
- ausencia en día hábil sin licencia ni feriado
- feriado y fin de semana con marcaciones → saldo a favor
- empleado sin `biometricoId` → sin filas
- empleado sin `cronogramaId` → `sin_horario` con saldo 0
- fecha anterior a `fechaInicioModulo` → sin fila
- fecha anterior a la `fechaIngreso` del empleado → sin fila
- permisos que superan la jornada → requeridas truncadas en 0, sin crédito

Sobre `asistencia_recalc.py` se testea la idempotencia: recalcular dos veces el
mismo año produce exactamente las mismas filas.

## Estructura de archivos

| archivo | responsabilidad |
|---|---|
| `app/database/asistencia.py` | DDL idempotente de `JornadaDiaria` y `AsistenciaConfig`, columna `Permission.oficial`, y CRUD |
| `app/services/asistencia_calc.py` | motor de cálculo puro, sin base de datos |
| `app/services/asistencia_recalc.py` | orquestación: carga insumos, invoca el motor, hace upsert |
| `app/routes/asistencia.py` | endpoints |
| `app/scheduler.py` | *(modificar)* job nocturno de recálculo |
| `app/main.py` | *(modificar)* `ensure_tables` de asistencia en el startup |
| `app/routes/employee.py` | *(modificar)* disparar `recalcular_historia` al cambiar `biometricoId` |
| `tests/test_asistencia_calc.py` | tests del motor puro |
| `src/app/screens/Asistencia/Screen.tsx` | ramificación por rol |
| `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` | tablero RRHH + modal de corrección |
| `src/app/Componentes/Asistencia/MiAsistencia.tsx` | vista del empleado |
