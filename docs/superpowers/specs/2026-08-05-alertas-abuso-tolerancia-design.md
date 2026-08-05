# Alertas por uso reiterado de la tolerancia — Diseño

**Fecha:** 2026-08-05
**Estado:** Aprobado

## Problema

La tolerancia de 15 minutos existe para que un atraso menor no descuente horas. Pero
perdona por igual al que llega a las 7:02 por una demora real y al que llega a las 7:14
todos los días porque descubrió hasta dónde llega el margen.

El segundo caso no se ve en ningún lado: el saldo da cero, la jornada figura `ok` y no
hay diferencia con quien llega puntual. RRHH no tiene cómo detectarlo y el empleado no
tiene cómo saber que está siendo observado hasta que alguien se lo dice.

## Contexto existente

`AsistenciaConfig` ya tiene `toleranciaEntradaMin = 15` y `toleranciaSalidaMin = 15`.

`JornadaDiaria` ya persiste `toleranciaEntradaUsada` y `toleranciaSalidaUsada`, con esta
intención declarada en el docstring de `_ajustar_por_tolerancia`:

> Los dos flags se persisten para que el tablero pueda senalar el uso reiterado sin tener
> que recalcular la jornada.

Este diseño completa esa idea: los flags dicen *si se usó* la tolerancia, no *cuánto*.

## Enfoque

Un segundo umbral, más estricto, por dentro del primero. No cambia ninguna hora
calculada: solo clasifica el día.

| Llega | Horas | Clasificación |
|---|---|---|
| ≤ +7 min | perdonado | normal |
| +7 a +15 min | perdonado | **abuso** |
| > +15 min | descuenta el desvío completo | ya penalizado, no es abuso |

El tercer tramo no cuenta como abuso a propósito: a esa persona ya se le descuentan las
horas. La alerta apunta exactamente a quien se queda del lado perdonado.

El día queda marcado por el motor puro y persistido; la racha se deriva al leer. No se
persiste ningún contador acumulado: sería estado desincronizable frente a un cambio de
umbrales sin recálculo.

## Configuración

Tres valores nuevos en `AsistenciaConfig`:

| Columna | Default | Significado |
|---|---|---|
| `toleranciaEstrictaEntradaMin` | 7 | margen razonable de llegada |
| `toleranciaEstrictaSalidaMin` | 5 | margen razonable de salida |
| `diasRachaAlerta` | 3 | días encadenados que disparan la alerta |

Migración idempotente con `IF COL_LENGTH(...) IS NULL ALTER TABLE ... ADD ... DEFAULT`,
igual que el resto del módulo.

`PUT /asistencia/config` los acepta y valida:

- las tolerancias estrictas entre 0 y la tolerancia común correspondiente. Una estricta
  mayor que la común haría que la condición de abuso nunca se cumpla y las alertas no
  saltarían nunca sin ningún error visible.
- `diasRachaAlerta` entre 1 y 30.

## Motor de cálculo

`_ajustar_por_tolerancia` pasa a devolver un dataclass congelado en vez de una tupla de
cinco elementos:

```python
@dataclass(frozen=True)
class AjusteTolerancia:
    brutas: float
    entradaUsada: bool
    salidaUsada: bool
    abusoEntrada: bool
    abusoSalida: bool
```

La regla, sobre los extremos **antes** del ajuste. La comparación se hace en **segundos
enteros**, no en horas decimales:

```python
desvio_entrada_seg = round((ent - horario.horaInicio) * 3600)
desvio_salida_seg  = round((horario.horaFin - sal) * 3600)

abuso_entrada = uso_entrada and desvio_entrada_seg > estricta_ent_min * 60
abuso_salida  = uso_salida  and desvio_salida_seg  > estricta_sal_min * 60
```

`uso_*` en la condición es lo que deja afuera al tramo ya penalizado.

Los umbrales son indulgentes en el borde: llegar exactamente a +7:00 no es abuso, igual
que llegar exactamente a +15:00 sigue estando perdonado.

El redondeo a segundos no es cosmético. Comparando en horas decimales, `7.5 + 7/60` (un
horario que arranca 7:30 más el umbral) y `_hora_decimal(7:37:00)` son la misma cantidad
matemática pero pueden diferir en el último bit del float, y el borde exacto quedaría
decidido por el error de representación. En segundos enteros la regla es exacta para
cualquier hora de inicio, incluidas las que no caen en hora redonda.

`ResultadoDia` suma `abusoEntrada: bool` y `abusoSalida: bool`, y `JornadaDiaria` las dos
columnas `BIT` correspondientes.

Los estados que no son `ok` nunca marcan abuso: feriado, licencia, sin horario, ausente e
incompleta salen del cálculo antes de llegar a la tolerancia, así que los flags quedan en
`false` por el camino que ya existe. No hay que tratarlos aparte.

## Módulo de rachas

Nuevo módulo puro `app/services/asistencia_alertas.py`. No conoce la base: recibe los días
ordenados por fecha y devuelve el resumen.

```python
@dataclass(frozen=True)
class DiaAbuso:
    fecha: date
    estado: str
    abuso: bool          # abusoEntrada or abusoSalida


@dataclass(frozen=True)
class ResumenAbuso:
    diasAbuso: int                       # total de días con abuso en el rango
    rachaMaxima: int                     # la corrida más larga
    fechasRachaMaxima: tuple[date, ...]  # qué días la formaron
    alerta: bool                         # rachaMaxima >= dias_alerta


def resumir(dias: list[DiaAbuso], dias_alerta: int) -> ResumenAbuso
```

Regla de recorrido: **solo los días con estado `ok` participan**. Todo lo demás es
transparente — no suma ni corta.

| Fecha | Estado | Abuso | Racha |
|---|---|---|---|
| lun 3 | ok | sí | 1 |
| mar 4 | ausente | — | 1 (se saltea) |
| mié 5 | ok | sí | 2 |
| jue 6 | licencia | — | 2 (se saltea) |
| vie 7 | ok | sí | **3 → alerta** |
| lun 10 | ok | no | 0 (corta) |

Sábados, domingos y feriados sin marcaciones no generan fila en `JornadaDiaria`, así que
se saltean por el mismo camino sin necesitar una regla propia.

`fechasRachaMaxima` permite que el aviso diga *"3 días seguidos: 3, 5 y 7 de agosto"* en
vez de un número suelto. Se calcula dentro del mismo bucle y convierte la alerta en algo
que la persona puede verificar.

Ante empate entre dos rachas de igual longitud gana la más reciente: es la que importa
para una conversación hoy.

## Acceso a datos

Dos funciones en `app/database/asistencia.py`:

- `dias_abuso_de(db, employee_id, desde, hasta) -> list[DiaAbuso]` — una persona.
- `dias_abuso_todos(db, desde, hasta) -> dict[int, list[DiaAbuso]]` — todos, en una sola
  consulta ordenada por `(employeeId, fecha)`, agrupada en Python. Es la misma forma que
  ya usa `tablero()` para no disparar una consulta por empleado.

Ambas traen `fecha, estado, abusoEntrada, abusoSalida` y arman los `DiaAbuso` con
`abuso = abusoEntrada or abusoSalida`.

## API

- `GET /asistencia/tablero` — cada fila suma `diasAbuso`, `rachaMaxima` y `alerta`.
- `GET /asistencia/mi` y `GET /asistencia/empleado/{id}` — suman un objeto `abuso` con el
  `ResumenAbuso` completo, incluidas las fechas.
- `GET /asistencia/alertas-tolerancia?desde=&hasta=` — solo los empleados con
  `alerta = true` en el rango, con sus fechas. Mismos defaults que `tablero` (1 de enero
  a hoy) y mismo permiso RRHH. Alimenta el panel del tablero sin obligarlo a filtrar del
  lado del cliente.

## Frontend

**`MiAsistencia`.** Aviso sobre la tarjeta de saldo cuando hay alerta, con las fechas
concretas, y un badge discreto en las filas del desglose que marcaron abuso. El texto es
descriptivo y no acusatorio:

> Entraste pasados los 7 minutos de margen 3 días seguidos (3, 5 y 7 de agosto).

Es deliberado que la persona vea el mismo dato que RRHH y antes de cualquier conversación.
Un aviso verificable y discutible vale más que uno que sorprende.

**Tablero de RRHH.** Un panel nuevo debajo del de jornadas incompletas —"Uso reiterado de
tolerancia"— con los empleados en alerta y sus fechas. Y una columna `Días con tolerancia`
en la tabla de saldo, con el total del rango: cubre al que abusa seguido sin llegar nunca
a encadenar tres.

**Pestaña Asistencia del empleado** (`AsistenciaEmpleadoTab`). Una cuarta tarjeta de
resumen junto a saldo, ausencias e incompletas, más los mismos badges en el desglose.

## Testing

**Motor puro** — casos de borde de cada umbral, con horario 7:00–13:00, tolerancia 15 y
estricta 7/5:

- entrada 7:05 → perdonada, sin abuso
- entrada 7:07:00 → perdonada, sin abuso (el borde estricto es indulgente)
- entrada 7:07:01 → perdonada, **con abuso**
- entrada 7:15:00 → perdonada, con abuso
- entrada 7:15:01 → descontada, **sin abuso** (ya penalizada)
- entrada 6:55 → llegó antes, sin abuso ni tolerancia
- salida 12:56 → perdonada, sin abuso
- salida 12:54 → perdonada, con abuso
- salida 13:05 → salió después, sin abuso
- estados feriado, licencia, ausente, incompleta y sin horario → los dos flags en `false`

**Módulo de rachas** — la tabla de recorrido de arriba como caso principal, más: lista
vacía, un solo día con abuso, todos con abuso, ninguno con abuso, empate entre dos rachas
(gana la más reciente), y una racha que llega justo a `diasRachaAlerta - 1`.

**Validación de configuración** — estricta mayor que la común rechazada, estricta igual a
la común aceptada, `diasRachaAlerta` fuera de rango rechazado.

Todo con funciones puras, sin tocar la base.

## Fuera de alcance

**Pantalla de configuración.** Hoy `GET/PUT /asistencia/config` existen pero ninguna
pantalla los usa: las tolerancias se configuran solo por API. Los tres valores nuevos
siguen esa misma vía. Construir una UI solo para los umbrales nuevos quedaría inconsistente
—se configuraría el 7 pero no el 15— y hacerla completa para los cinco es un trabajo
aparte. Queda como deuda explícita.

**Notificaciones.** La alerta se ve al entrar a la pantalla. No se manda mail ni se genera
aviso push: nadie lo pidió y agregaría un canal con su propio ciclo de vida.

**Racha en curso.** El resumen informa la racha máxima del rango, no cuántos días lleva
encadenados en este momento. Un "llevás 2, cuidado" sería un producto distinto —
preventivo en vez de descriptivo— y conviene decidirlo con datos reales de uso.
