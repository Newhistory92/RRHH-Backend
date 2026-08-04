# Refactor del motor de asistencia e integridad de datos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir el motor de asistencia para que el balance de horas sea
correcto y auditable, separando la interpretación de marcaciones del cálculo de
saldo y sacando los datos propios de la tabla derivada.

**Architecture:** Se agrega un módulo puro `marcaciones_norm.py` que convierte
marcaciones crudas en extremos confiables (dedup, clasificación, incidencias);
`asistencia_calc.py` pasa a consumir ese resultado y solo calcula saldo. Las
cargas manuales de RRHH se mudan a `JornadaCorreccion`, que el `DELETE`+`INSERT`
del recálculo no puede tocar. Se agregan detección de huecos al arrancar y
auditoría de corridas.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core (`text()` con binds
nombrados), SQL Server vía pyodbc, APScheduler, pytest.

**Spec:** `docs/superpowers/specs/2026-08-03-asistencia-motor-integridad-design.md`

## Global Constraints

- **Nunca levantar el servidor.** No ejecutar `uvicorn` ni ningún dev server.
- **Los relojes son de solo lectura.** No modificar la allowlist de
  `app/services/isapi_client.py` bajo ninguna circunstancia.
- **Credenciales solo en `.env`** (`RELOJ_USER`, `RELOJ_PASS`, `RELOJ_IPS`).
  Nunca en código, tests ni documentos. `.env` no se commitea.
- `VENTANA_REBOTE_MIN = 5` — ventana de deduplicación, en minutos.
- **La deduplicación es global, nunca por reloj.** `normalizar()` recibe una
  lista de `datetime` sin la IP del equipo.
- `fechaInicioModulo` del módulo pasa a **`2026-07-30`**.
- **Clave natural `(employeeId, fecha)`** en las tablas nuevas. Sin FK a
  `JornadaDiaria.id`, que cambia en cada recálculo.
- **DDL idempotente:** `IF OBJECT_ID(...) IS NULL` / `IF COL_LENGTH(...) IS NULL`,
  cada sentencia en su propio batch seguida de `db.commit()`.
- **SQL siempre parametrizado** con binds nombrados. La única interpolación
  permitida es la de `_drop_columna`, sobre constantes del propio código.
- **Los tests no tocan base de datos ni relojes.** `marcaciones_norm` y
  `asistencia_calc` son puros; `reloj_sync` se prueba con el cliente mockeado.
- **Estados existentes que no cambian:** `ok`, `incompleta`, `ausente`,
  `feriado`, `licencia`, `sin_horario`.
- `BANCO_PERMISO_ANUAL_HORAS = 12.0` — no se toca.
- Días hábiles: lunes a viernes (`weekday()` 0–4).
- Todo commit termina con la línea
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Comandos de test: `py -m pytest ...` (en este entorno `python` no está en PATH).

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/services/marcaciones_norm.py` | **Nuevo.** Puro. Marcaciones crudas → extremos + incidencias. Módulo de más bajo nivel. |
| `app/services/asistencia_calc.py` | Puro. Extremos → saldo del día. Importa de `marcaciones_norm`. |
| `app/services/asistencia_recalc.py` | I/O. Carga insumos, orquesta, reemplaza el rango, audita. |
| `app/services/reloj_sync.py` | I/O. Sincronización por ventanas diarias. |
| `app/database/asistencia_auditoria.py` | **Nuevo.** DDL/CRUD de `JornadaCorreccion`, `JornadaIncidencia`, `RecalculoLog`. |
| `app/database/asistencia.py` | DDL/CRUD de `JornadaDiaria` y `AsistenciaConfig`. |
| `app/routes/asistencia.py` | Endpoints del módulo. |
| `app/routes/relojes.py` | Endpoint de re-sincronización. |
| `app/scheduler.py` | Job de auto-reparación al arrancar. |

Dependencia de una sola dirección: `asistencia_calc` importa de
`marcaciones_norm`, nunca al revés.

---

## Task 1: Módulo puro de normalización de marcaciones

**Files:**
- Create: `app/services/marcaciones_norm.py`
- Test: `tests/test_marcaciones_norm.py`

**Interfaces:**
- Consumes: nada. Es el módulo de más bajo nivel.
- Produces:
  - `VENTANA_REBOTE_MIN: int = 5`
  - `INCIDENCIA_FALTA_SALIDA = "falta_salida"`, `INCIDENCIA_FALTA_ENTRADA = "falta_entrada"`, `INCIDENCIA_SIN_CRONOGRAMA = "sin_cronograma"`, `INCIDENCIA_REBOTE = "rebote_descartado"`
  - `HorarioDia(horaInicio: float, horaFin: float, horasTrabajo: float)` — se **muda** desde `asistencia_calc.py`
  - `Correccion(entrada: Optional[datetime] = None, salida: Optional[datetime] = None)`
  - `ExtremosDia(entrada, salida, incidencias: tuple[str, ...], descartadas: int, entrada_manual: bool, salida_manual: bool)`
  - `deduplicar(marcaciones: list[datetime], ventana_min: int = VENTANA_REBOTE_MIN) -> list[datetime]`
  - `normalizar(marcaciones: list[datetime], horario: Optional[HorarioDia], correccion: Optional[Correccion] = None, ventana_min: int = VENTANA_REBOTE_MIN) -> ExtremosDia`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_marcaciones_norm.py`:

```python
from datetime import datetime

from app.services import marcaciones_norm as n

JORNADA_7_A_13 = n.HorarioDia(horaInicio=7.0, horaFin=13.0, horasTrabajo=6.0)


def _m(*hms):
    """(hora, minuto) o (hora, minuto, segundo) -> datetime del 2026-07-30."""
    return [datetime(2026, 7, 30, *hm) for hm in hms]


# -- Deduplicacion ------------------------------------------------------------

def test_rebote_de_tres_segundos_colapsa_en_una_marca():
    marcas = _m((8, 9, 21), (8, 9, 23), (8, 9, 24))
    assert n.deduplicar(marcas) == [datetime(2026, 7, 30, 8, 9, 21)]


def test_marcas_separadas_por_seis_minutos_no_colapsan():
    marcas = _m((7, 0), (7, 6))
    assert n.deduplicar(marcas) == marcas


def test_el_limite_exacto_de_la_ventana_no_colapsa():
    marcas = _m((7, 0), (7, 5))
    assert n.deduplicar(marcas) == marcas


def test_rafaga_larga_no_se_encadena_mas_alla_de_la_ventana():
    # Cinco marcas de a dos minutos: 7:00 7:02 7:04 7:06 7:08.
    # Comparando contra la ultima CONSERVADA sobreviven 7:00 y 7:06.
    marcas = _m((7, 0), (7, 2), (7, 4), (7, 6), (7, 8))
    assert n.deduplicar(marcas) == [
        datetime(2026, 7, 30, 7, 0), datetime(2026, 7, 30, 7, 6),
    ]


def test_deduplicar_ordena_marcas_desordenadas():
    marcas = _m((13, 0), (7, 0))
    assert n.deduplicar(marcas) == [
        datetime(2026, 7, 30, 7, 0), datetime(2026, 7, 30, 13, 0),
    ]


def test_deduplicar_lista_vacia():
    assert n.deduplicar([]) == []


# -- Clasificacion de marca unica ---------------------------------------------

def test_marca_unica_cerca_del_inicio_es_entrada():
    e = n.normalizar(_m((7, 13)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 13)
    assert e.salida is None
    assert n.INCIDENCIA_FALTA_SALIDA in e.incidencias


def test_marca_unica_cerca_del_fin_es_salida():
    e = n.normalizar(_m((12, 59)), JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida == datetime(2026, 7, 30, 12, 59)
    assert n.INCIDENCIA_FALTA_ENTRADA in e.incidencias


def test_empate_exacto_entre_inicio_y_fin_se_resuelve_como_salida():
    # 10:00 esta a 3 h de las 7:00 y a 3 h de las 13:00.
    e = n.normalizar(_m((10, 0)), JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida == datetime(2026, 7, 30, 10, 0)
    assert n.INCIDENCIA_FALTA_ENTRADA in e.incidencias


# -- Jornada normal -----------------------------------------------------------

def test_dos_marcas_dan_entrada_y_salida_sin_incidencias():
    e = n.normalizar(_m((7, 1), (13, 2)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 1)
    assert e.salida == datetime(2026, 7, 30, 13, 2)
    assert e.incidencias == ()


def test_dia_sin_marcaciones_ni_correccion_no_tiene_extremos():
    e = n.normalizar([], JORNADA_7_A_13)
    assert e.entrada is None
    assert e.salida is None
    assert e.incidencias == ()


# -- Marcacion cruzada entre relojes ------------------------------------------

def test_entrada_de_un_reloj_y_salida_del_otro_es_una_jornada_normal():
    # normalizar() no conoce el equipo de origen: las marcas de los dos relojes
    # llegan en la misma lista.
    e = n.normalizar(_m((7, 21), (13, 36)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 21)
    assert e.salida == datetime(2026, 7, 30, 13, 36)
    assert e.incidencias == ()


def test_dos_relojes_a_tres_minutos_colapsan_en_vez_de_dar_jornada_corta():
    # El empleado ficha en los dos lectores al llegar. Sin dedup global esto
    # daria una jornada de tres minutos con la deuda completa.
    e = n.normalizar(_m((7, 0), (7, 3)), JORNADA_7_A_13)
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida is None
    assert e.descartadas == 1
    assert n.INCIDENCIA_FALTA_SALIDA in e.incidencias
    assert n.INCIDENCIA_REBOTE in e.incidencias


# -- Sin cronograma -----------------------------------------------------------

def test_sin_horario_emite_incidencia_y_no_clasifica():
    e = n.normalizar(_m((7, 0), (13, 0)), None)
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida == datetime(2026, 7, 30, 13, 0)


def test_sin_horario_con_una_sola_marca_no_infiere_salida():
    e = n.normalizar(_m((7, 0)), None)
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.salida is None
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias


# -- Correccion de RRHH -------------------------------------------------------

def test_la_salida_manual_limpia_la_incidencia_de_falta_salida():
    e = n.normalizar(
        _m((7, 13)), JORNADA_7_A_13,
        n.Correccion(salida=datetime(2026, 7, 30, 13, 0)),
    )
    assert e.salida == datetime(2026, 7, 30, 13, 0)
    assert e.salida_manual is True
    assert n.INCIDENCIA_FALTA_SALIDA not in e.incidencias


def test_la_entrada_manual_limpia_la_incidencia_de_falta_entrada():
    e = n.normalizar(
        _m((12, 59)), JORNADA_7_A_13,
        n.Correccion(entrada=datetime(2026, 7, 30, 7, 0)),
    )
    assert e.entrada == datetime(2026, 7, 30, 7, 0)
    assert e.entrada_manual is True
    assert n.INCIDENCIA_FALTA_ENTRADA not in e.incidencias


def test_la_correccion_pisa_lo_que_dice_el_reloj():
    e = n.normalizar(
        _m((7, 0), (13, 0)), JORNADA_7_A_13,
        n.Correccion(entrada=datetime(2026, 7, 30, 9, 0)),
    )
    assert e.entrada == datetime(2026, 7, 30, 9, 0)
    assert e.salida == datetime(2026, 7, 30, 13, 0)
    assert e.entrada_manual is True
    assert e.salida_manual is False


def test_sin_cronograma_sobrevive_a_la_correccion():
    # La correccion aporta los extremos, pero el empleado sigue sin horario.
    e = n.normalizar(
        [], None,
        n.Correccion(entrada=datetime(2026, 7, 30, 7, 0),
                     salida=datetime(2026, 7, 30, 13, 0)),
    )
    assert n.INCIDENCIA_SIN_CRONOGRAMA in e.incidencias
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `py -m pytest tests/test_marcaciones_norm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.marcaciones_norm'`

- [ ] **Step 3: Implementar el módulo**

Crear `app/services/marcaciones_norm.py`:

```python
"""
Interpretacion de marcaciones crudas: de las fichadas del dia a los dos extremos
confiables de la jornada, mas las incidencias que quedaron abiertas.

Funcion pura: no toca la base de datos ni los relojes. Es el modulo de mas bajo
nivel del calculo de asistencia; asistencia_calc importa de aca, nunca al reves.

Interpretar marcaciones y calcular saldo son responsabilidades distintas: la
primera decide QUE paso, la segunda CUANTO vale. Separarlas deja las dos
testeables con fixtures triviales.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

VENTANA_REBOTE_MIN = 5

INCIDENCIA_FALTA_SALIDA = "falta_salida"
INCIDENCIA_FALTA_ENTRADA = "falta_entrada"
INCIDENCIA_SIN_CRONOGRAMA = "sin_cronograma"
INCIDENCIA_REBOTE = "rebote_descartado"


@dataclass(frozen=True)
class HorarioDia:
    """horaInicio y horaFin son decimales: 8.5 es las 08:30."""
    horaInicio: float
    horaFin: float
    horasTrabajo: float


@dataclass(frozen=True)
class Correccion:
    """Carga manual de RRHH. Cualquiera de los dos extremos puede venir vacio."""
    entrada: Optional[datetime] = None
    salida: Optional[datetime] = None


@dataclass(frozen=True)
class ExtremosDia:
    entrada: Optional[datetime]
    salida: Optional[datetime]
    incidencias: tuple[str, ...]
    descartadas: int
    entrada_manual: bool
    salida_manual: bool


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def deduplicar(marcaciones: list[datetime],
               ventana_min: int = VENTANA_REBOTE_MIN) -> list[datetime]:
    """
    Colapsa marcas separadas por menos de la ventana, conservando la primera de
    cada grupo.

    La comparacion es contra la ultima marca CONSERVADA, no contra la anterior
    cruda: de lo contrario una rafaga de marcas de a dos minutos se encadenaria
    indefinidamente y terminaria fusionando una jornada entera.

    No distingue el reloj de origen a proposito, y por eso la firma no recibe la
    IP del equipo. Hay dos relojes y un empleado puede fichar en ambos al
    llegar; si se deduplicara por equipo esas dos marcas sobrevivirian y el
    motor las leeria como entrada y salida de una jornada de tres minutos.
    """
    if not marcaciones:
        return []
    ventana = timedelta(minutes=ventana_min)
    ordenadas = sorted(marcaciones)
    conservadas = [ordenadas[0]]
    for m in ordenadas[1:]:
        if m - conservadas[-1] >= ventana:
            conservadas.append(m)
    return conservadas


def normalizar(marcaciones: list[datetime],
               horario: Optional[HorarioDia],
               correccion: Optional[Correccion] = None,
               ventana_min: int = VENTANA_REBOTE_MIN) -> ExtremosDia:
    """
    Marcaciones crudas del dia -> extremos confiables mas sus incidencias.

    La correccion de RRHH pisa lo que diga el reloj y limpia la incidencia del
    extremo que aporta. sin_cronograma sobrevive: la correccion completa los
    horarios de un dia, no le asigna un cronograma al empleado.
    """
    limpias = deduplicar(marcaciones, ventana_min)
    descartadas = len(marcaciones) - len(limpias)
    incidencias: list[str] = []
    if descartadas:
        incidencias.append(INCIDENCIA_REBOTE)

    entrada: Optional[datetime] = None
    salida: Optional[datetime] = None

    if horario is None:
        # Sin horario no hay contra que comparar: se toman los extremos crudos
        # y el dia se resuelve como sin_horario aguas abajo.
        incidencias.append(INCIDENCIA_SIN_CRONOGRAMA)
        if limpias:
            entrada = limpias[0]
            if len(limpias) >= 2:
                salida = limpias[-1]
    elif len(limpias) >= 2:
        entrada = limpias[0]
        salida = limpias[-1]
    elif len(limpias) == 1:
        marca = limpias[0]
        h = _hora_decimal(marca)
        # El empate se resuelve hacia salida: los datos del periodo observado
        # muestran mas marcas unicas vespertinas que matutinas.
        if abs(h - horario.horaInicio) < abs(h - horario.horaFin):
            entrada = marca
            incidencias.append(INCIDENCIA_FALTA_SALIDA)
        else:
            salida = marca
            incidencias.append(INCIDENCIA_FALTA_ENTRADA)

    c = correccion or Correccion()
    entrada_manual = c.entrada is not None
    salida_manual = c.salida is not None
    if entrada_manual:
        entrada = c.entrada
        incidencias = [i for i in incidencias if i != INCIDENCIA_FALTA_ENTRADA]
    if salida_manual:
        salida = c.salida
        incidencias = [i for i in incidencias if i != INCIDENCIA_FALTA_SALIDA]

    return ExtremosDia(
        entrada=entrada,
        salida=salida,
        incidencias=tuple(incidencias),
        descartadas=descartadas,
        entrada_manual=entrada_manual,
        salida_manual=salida_manual,
    )
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_marcaciones_norm.py -v`
Expected: PASS — 19 passed

Run: `py -m pytest tests/ -v`
Expected: PASS — 57 tests (38 previos + 19 nuevos)

- [ ] **Step 5: Commit**

```bash
git add app/services/marcaciones_norm.py tests/test_marcaciones_norm.py
git commit -m "feat: modulo puro de normalizacion de marcaciones

Dedup global de 5 minutos, clasificacion de marca unica por cercania al
horario e incidencias. La deduplicacion no distingue el reloj de origen: un
empleado puede fichar en los dos equipos al llegar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Adaptar el motor de cálculo a los extremos normalizados

**Files:**
- Modify: `app/services/asistencia_calc.py`
- Test: `tests/test_asistencia_calc.py`

**Interfaces:**
- Consumes de Task 1: `ExtremosDia`, `HorarioDia`, `Correccion` de
  `app.services.marcaciones_norm`.
- Produces:
  - `EntradaDia(fecha, extremos: ExtremosDia, horario, es_feriado, tiene_licencia, permisos)` — **ya no** recibe `marcaciones`, `entrada_manual` ni `salida_manual`
  - `ResultadoDia(...)` con cinco campos nuevos: `incidencias: tuple[str, ...]`, `toleranciaEntradaUsada: bool`, `toleranciaSalidaUsada: bool`, `entradaManual: bool`, `salidaManual: bool`
  - `HorarioDia` se re-exporta desde `marcaciones_norm` para no romper importaciones existentes
  - `calcular_dia(entrada_dia, tol_entrada_min, tol_salida_min, banco_disponible) -> Optional[ResultadoDia]` — firma sin cambios
  - `calcular_anio(dias, tol_entrada_min, tol_salida_min) -> list[ResultadoDia]` — firma sin cambios

- [ ] **Step 1: Reescribir el helper de los tests y agregar los casos nuevos**

En `tests/test_asistencia_calc.py`, reemplazar el encabezado (líneas 1–25) por:

```python
from datetime import date, datetime

from app.services import asistencia_calc as c
from app.services import marcaciones_norm as n

JORNADA_8H = n.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)


def _dia(fecha=date(2026, 7, 1), marcaciones=None, horario=JORNADA_8H,
         es_feriado=False, tiene_licencia=False, permisos=None,
         entrada_manual=None, salida_manual=None):
    """
    Miercoles 2026-07-01 por defecto: dia habil.

    Arma los extremos pasando por normalizar(), asi los tests del motor
    ejercitan la misma cadena que produccion.
    """
    correccion = None
    if entrada_manual is not None or salida_manual is not None:
        correccion = n.Correccion(entrada=entrada_manual, salida=salida_manual)
    return c.EntradaDia(
        fecha=fecha,
        extremos=n.normalizar(
            marcaciones if marcaciones is not None else [], horario, correccion,
        ),
        horario=horario,
        es_feriado=es_feriado,
        tiene_licencia=tiene_licencia,
        permisos=permisos if permisos is not None else [],
    )


def _marcas(*horas):
    return [datetime(2026, 7, 1, h, m) for h, m in horas]
```

El resto del archivo (líneas 28–218) queda **sin cambios**: los 22 tests
existentes siguen valiendo porque `_dia()` mantiene su firma.

Un test existente cambia de expectativa y hay que corregirlo. Reemplazar
`test_una_sola_marcacion_queda_incompleta_sin_penalizar`:

```python
def test_una_sola_marcacion_queda_incompleta_sin_penalizar():
    # 8:00 esta mas cerca del inicio (8.0) que del fin (16.0): es entrada.
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0))), 15, 15, 12.0)
    assert r.estado == c.ESTADO_INCOMPLETA
    assert r.saldoDia == 0.0
    assert r.entrada == datetime(2026, 7, 1, 8, 0)
    assert r.salida is None
    assert n.INCIDENCIA_FALTA_SALIDA in r.incidencias
```

Agregar al final del archivo:

```python
# -- Flags de tolerancia ------------------------------------------------------

def test_flag_de_tolerancia_de_entrada_cuando_se_aplica():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 0))), 15, 15, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.toleranciaSalidaUsada is False


def test_flag_de_tolerancia_de_salida_cuando_se_aplica():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 50))), 15, 15, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.toleranciaSalidaUsada is True


def test_ambas_tolerancias_marcadas():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (15, 50))), 15, 15, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.toleranciaSalidaUsada is True


def test_ninguna_tolerancia_cuando_llega_puntual():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 0))), 15, 15, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.toleranciaSalidaUsada is False


def test_pasada_la_tolerancia_el_flag_queda_en_falso():
    # 8:20 supera los 15 min: no se perdona, asi que la tolerancia no se "uso".
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 20), (16, 0))), 15, 15, 12.0)
    assert r.toleranciaEntradaUsada is False


# -- Incidencias y flags manuales ---------------------------------------------

def test_las_incidencias_llegan_al_resultado():
    r = c.calcular_dia(_dia(horario=None), 15, 15, 12.0)
    assert n.INCIDENCIA_SIN_CRONOGRAMA in r.incidencias


def test_los_flags_manuales_llegan_al_resultado():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), salida_manual=datetime(2026, 7, 1, 16, 0)),
        15, 15, 12.0,
    )
    assert r.entradaManual is False
    assert r.salidaManual is True


def test_jornada_normal_no_tiene_incidencias():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 0))), 15, 15, 12.0)
    assert r.incidencias == ()
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `py -m pytest tests/test_asistencia_calc.py -v`
Expected: FAIL — `TypeError: EntradaDia.__init__() got an unexpected keyword argument 'extremos'`

- [ ] **Step 3: Reescribir el motor**

Reemplazar el contenido completo de `app/services/asistencia_calc.py`:

```python
"""
Motor de calculo de asistencia. Funcion pura: no toca la base de datos ni los
relojes, asi que toda la logica dificil -tolerancia y banco de permisos- se
testea sin fixtures.

Recibe los extremos del dia ya interpretados por marcaciones_norm: aca no se
decide cual marca es la entrada, solo cuanto vale la jornada.

La unidad de calculo es el dia. El arrastre del banco anual de permisos es
responsabilidad de calcular_anio, que recorre los dias en orden cronologico.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from app.services.marcaciones_norm import ExtremosDia, HorarioDia

BANCO_PERMISO_ANUAL_HORAS = 12.0

# weekday(): lunes=0 ... domingo=6
DIAS_HABILES = frozenset({0, 1, 2, 3, 4})

ESTADO_OK = "ok"
ESTADO_INCOMPLETA = "incompleta"
ESTADO_AUSENTE = "ausente"
ESTADO_FERIADO = "feriado"
ESTADO_LICENCIA = "licencia"
ESTADO_SIN_HORARIO = "sin_horario"

# Re-export: los consumidores historicos importan HorarioDia desde aca.
__all__ = [
    "BANCO_PERMISO_ANUAL_HORAS", "DIAS_HABILES", "ESTADO_OK",
    "ESTADO_INCOMPLETA", "ESTADO_AUSENTE", "ESTADO_FERIADO", "ESTADO_LICENCIA",
    "ESTADO_SIN_HORARIO", "HorarioDia", "Permiso", "EntradaDia", "ResultadoDia",
    "calcular_dia", "calcular_anio",
]


@dataclass(frozen=True)
class Permiso:
    horas: float
    oficial: bool


@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    extremos: ExtremosDia
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
    incidencias: tuple[str, ...]
    toleranciaEntradaUsada: bool
    toleranciaSalidaUsada: bool
    entradaManual: bool
    salidaManual: bool


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol_entrada_min: int,
                            tol_salida_min: int) -> tuple[float, bool, bool]:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.

    Devuelve las horas brutas y si cada tolerancia se aplico. Los dos flags se
    persisten para que el tablero pueda senalar el uso reiterado sin tener que
    recalcular la jornada.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol_entrada_min / 60
    tol_sal = tol_salida_min / 60

    uso_entrada = horario.horaInicio < ent <= horario.horaInicio + tol_ent
    if uso_entrada:
        ent = horario.horaInicio
    uso_salida = horario.horaFin - tol_sal <= sal < horario.horaFin
    if uso_salida:
        sal = horario.horaFin

    return sal - ent, uso_entrada, uso_salida


def _sumar_permisos(permisos: list[Permiso]) -> tuple[float, float]:
    regular = sum(p.horas for p in permisos if not p.oficial)
    oficial = sum(p.horas for p in permisos if p.oficial)
    return regular, oficial


def _resultado(e: EntradaDia, estado: str, requeridas: float, trabajadas: float,
               saldo: float, banco: float = 0.0, deuda: float = 0.0,
               oficial: float = 0.0, tol_ent: bool = False,
               tol_sal: bool = False) -> ResultadoDia:
    """Arma la fila arrastrando lo que ya venia resuelto en los extremos."""
    x = e.extremos
    return ResultadoDia(
        fecha=e.fecha, estado=estado,
        horasRequeridas=requeridas, horasTrabajadas=trabajadas, saldoDia=saldo,
        entrada=x.entrada, salida=x.salida,
        permisoBanco=banco, permisoDeuda=deuda, permisoOficial=oficial,
        incidencias=x.incidencias,
        toleranciaEntradaUsada=tol_ent, toleranciaSalidaUsada=tol_sal,
        entradaManual=x.entrada_manual, salidaManual=x.salida_manual,
    )


def calcular_dia(entrada_dia: EntradaDia, tol_entrada_min: int,
                 tol_salida_min: int,
                 banco_disponible: float) -> Optional[ResultadoDia]:
    """
    Devuelve la fila del dia, o None cuando no corresponde generar ninguna
    (fin de semana o feriado sin marcaciones).
    """
    e = entrada_dia
    entrada = e.extremos.entrada
    salida = e.extremos.salida
    no_laborable = e.es_feriado or e.fecha.weekday() not in DIAS_HABILES

    # Dia no laborable: sin marcaciones no existe la fila; con marcaciones todo
    # lo trabajado es saldo a favor y no se aplica tolerancia, porque el
    # horario no rige un dia que no se debia trabajar.
    if no_laborable:
        if entrada is None or salida is None:
            return None
        trabajadas = _hora_decimal(salida) - _hora_decimal(entrada)
        return _resultado(e, ESTADO_FERIADO, 0.0, trabajadas, trabajadas)

    if e.tiene_licencia:
        return _resultado(e, ESTADO_LICENCIA, 0.0, 0.0, 0.0)

    if e.horario is None:
        return _resultado(e, ESTADO_SIN_HORARIO, 0.0, 0.0, 0.0)

    permiso_regular, permiso_oficial = _sumar_permisos(e.permisos)
    permiso_banco = min(permiso_regular, max(banco_disponible, 0.0))
    permiso_deuda = permiso_regular - permiso_banco

    if entrada is None and salida is None:
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return _resultado(
            e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
            -e.horario.horasTrabajo,
        )

    if entrada is None or salida is None:
        # Falta un extremo. No se penaliza hasta que RRHH cargue el otro: el dia
        # queda neutro y visible en el tablero de incidencias.
        return _resultado(e, ESTADO_INCOMPLETA, 0.0, 0.0, 0.0)

    brutas, tol_ent, tol_sal = _ajustar_por_tolerancia(
        entrada, salida, e.horario, tol_entrada_min, tol_salida_min,
    )
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return _resultado(
        e, ESTADO_OK, requeridas, trabajadas, trabajadas - requeridas,
        banco=permiso_banco, deuda=permiso_deuda, oficial=permiso_oficial,
        tol_ent=tol_ent, tol_sal=tol_sal,
    )


def calcular_anio(dias: list[EntradaDia], tol_entrada_min: int,
                  tol_salida_min: int) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.
    """
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(
            d, tol_entrada_min, tol_salida_min,
            BANCO_PERMISO_ANUAL_HORAS - consumido,
        )
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
```

- [ ] **Step 4: Correr toda la suite**

Run: `py -m pytest tests/ -v`
Expected: PASS — 65 tests. Desglose: 30 en `test_asistencia_calc.py`
(22 originales + 8 nuevos), 19 en `test_marcaciones_norm.py`, 6 en
`test_reloj_sync.py` y 10 en `test_isapi_client.py`, estos dos últimos sin
tocar.

- [ ] **Step 5: Commit**

```bash
git add app/services/asistencia_calc.py tests/test_asistencia_calc.py
git commit -m "refactor: el motor consume extremos ya normalizados

EntradaDia recibe ExtremosDia en lugar de marcaciones crudas. ResultadoDia
suma incidencias, los flags de tolerancia usada y los de carga manual.
HorarioDia se muda a marcaciones_norm y se re-exporta.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Tablas de correcciones, incidencias y auditoría

**Files:**
- Create: `app/database/asistencia_auditoria.py`
- Modify: `app/database/asistencia.py`

**Interfaces:**
- Consumes de Task 1: `Correccion` de `app.services.marcaciones_norm`.
- Produces (`app.database.asistencia_auditoria`):
  - `ensure_tables(db: Session) -> None`
  - `correcciones_por_dia(db, employee_id: int, desde: date, hasta: date) -> dict[date, Correccion]`
  - `upsert_correccion(db, employee_id: int, fecha: date, entrada, salida, corregido_por: int, observacion) -> None`
  - `get_correccion(db, employee_id: int, fecha: date) -> Optional[dict]`
  - `reemplazar_incidencias(db, employee_id: int, desde: date, hasta: date, filas: list[dict]) -> int` — cada fila: `{"fecha": date, "tipo": str, "detalle": str | None}`
  - `incidencias_abiertas(db, tipo: Optional[str], desde: date, hasta: date) -> list[dict]`
  - `abrir_recalculo(db, origen: str, disparado_por, employee_id, desde, hasta) -> int`
  - `cerrar_recalculo(db, log_id: int, procesados: int, filas: int, errores: list) -> None`
  - `ultimos_recalculos(db, limite: int = 50) -> list[dict]`
- Produces (`app.database.asistencia`): `JornadaDiaria` gana
  `toleranciaEntradaUsada` y `toleranciaSalidaUsada` (BIT), y pierde
  `corregidoPor`, `corregidoAt`, `observacion`.

- [ ] **Step 1: Crear el módulo de auditoría**

Crear `app/database/asistencia_auditoria.py`:

```python
"""
Tablas que el recalculo no puede pisar.

JornadaDiaria es derivada: el recalculo la borra entera y la reinserta. Todo lo
que no se puede reconstruir desde Marcacion -las cargas manuales de RRHH- vive
aca, en JornadaCorreccion, con clave natural (employeeId, fecha) y sin FK al id
de la jornada, que cambia en cada corrida.

JornadaIncidencia si es derivada, pero vive aparte porque es 1:N con el dia.
RecalculoLog es la auditoria de las corridas.
"""

import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.marcaciones_norm import Correccion

CREATE_CORRECCION_SQL = """
IF OBJECT_ID('JornadaCorreccion', 'U') IS NULL
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
"""

CREATE_INCIDENCIA_SQL = """
IF OBJECT_ID('JornadaIncidencia', 'U') IS NULL
CREATE TABLE JornadaIncidencia (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    employeeId  INT           NOT NULL,
    fecha       DATE          NOT NULL,
    tipo        NVARCHAR(30)  NOT NULL,
    detalle     NVARCHAR(300) NULL,
    detectadoAt DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaIncidencia UNIQUE (employeeId, fecha, tipo)
);
"""

CREATE_INDEX_INCIDENCIA_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_JornadaIncidencia_tipo')
CREATE INDEX IX_JornadaIncidencia_tipo ON JornadaIncidencia (tipo, fecha);
"""

CREATE_RECALCULO_LOG_SQL = """
IF OBJECT_ID('RecalculoLog', 'U') IS NULL
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
"""


def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_CORRECCION_SQL))
    db.commit()
    db.execute(text(CREATE_INCIDENCIA_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_INCIDENCIA_SQL))
    db.commit()
    db.execute(text(CREATE_RECALCULO_LOG_SQL))
    db.commit()


# -- Correcciones -------------------------------------------------------------

def correcciones_por_dia(db: Session, employee_id: int, desde: date,
                         hasta: date) -> dict[date, Correccion]:
    """Lo que el recalculo reinyecta al motor para que la carga manual gane."""
    filas = db.execute(text("""
        SELECT fecha, entrada, salida FROM JornadaCorreccion
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    out: dict[date, Correccion] = {}
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        out[d] = Correccion(entrada=f["entrada"], salida=f["salida"])
    return out


def get_correccion(db: Session, employee_id: int, fecha: date) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, employeeId, fecha, entrada, salida, corregidoPor,
               corregidoAt, observacion
        FROM JornadaCorreccion WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()
    return dict(fila) if fila else None


def upsert_correccion(db: Session, employee_id: int, fecha: date,
                      entrada: Optional[datetime], salida: Optional[datetime],
                      corregido_por: int, observacion: Optional[str]) -> None:
    """
    Inserta o actualiza la correccion del dia. Un extremo en None no borra el
    que ya estaba: RRHH puede cargar la entrada hoy y la salida manana.
    """
    db.execute(text("""
        MERGE JornadaCorreccion AS destino
        USING (SELECT :emp AS employeeId, :fecha AS fecha) AS origen
            ON destino.employeeId = origen.employeeId
           AND destino.fecha = origen.fecha
        WHEN MATCHED THEN UPDATE SET
            entrada      = COALESCE(:entrada, destino.entrada),
            salida       = COALESCE(:salida, destino.salida),
            corregidoPor = :por,
            corregidoAt  = GETDATE(),
            observacion  = :obs
        WHEN NOT MATCHED THEN INSERT
            (employeeId, fecha, entrada, salida, corregidoPor, corregidoAt, observacion)
            VALUES (:emp, :fecha, :entrada, :salida, :por, GETDATE(), :obs);
    """), {"emp": employee_id, "fecha": fecha, "entrada": entrada,
           "salida": salida, "por": corregido_por, "obs": (observacion or None)})
    db.commit()


# -- Incidencias --------------------------------------------------------------

def reemplazar_incidencias(db: Session, employee_id: int, desde: date,
                           hasta: date, filas: list[dict]) -> int:
    """
    Derivadas: se borran y se reinsertan junto con las jornadas del rango. No
    hace commit; lo hace reemplazar_jornadas al cerrar la transaccion del
    recalculo, para que jornadas e incidencias no queden desincronizadas.
    """
    db.execute(text("""
        DELETE FROM JornadaIncidencia
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta})

    ahora = datetime.now()
    for f in filas:
        db.execute(text("""
            INSERT INTO JornadaIncidencia (employeeId, fecha, tipo, detalle, detectadoAt)
            VALUES (:employeeId, :fecha, :tipo, :detalle, :detectadoAt)
        """), {"employeeId": employee_id, "fecha": f["fecha"], "tipo": f["tipo"],
               "detalle": f.get("detalle"), "detectadoAt": ahora})
    return len(filas)


def incidencias_abiertas(db: Session, tipo: Optional[str], desde: date,
                         hasta: date) -> list[dict]:
    filas = db.execute(text("""
        SELECT i.id, i.employeeId, e.name AS employeeName, i.fecha, i.tipo,
               i.detalle, i.detectadoAt
        FROM JornadaIncidencia i
        INNER JOIN Employee e ON e.id = i.employeeId
        WHERE i.fecha >= :desde AND i.fecha <= :hasta
          AND (:tipo IS NULL OR i.tipo = :tipo)
        ORDER BY i.fecha DESC, e.name ASC
    """), {"desde": desde, "hasta": hasta, "tipo": tipo}).mappings().all()
    return [dict(f) for f in filas]


# -- Log de recalculos --------------------------------------------------------

def abrir_recalculo(db: Session, origen: str, disparado_por: Optional[int],
                    employee_id: Optional[int], desde: Optional[date],
                    hasta: Optional[date]) -> int:
    fila = db.execute(text("""
        INSERT INTO RecalculoLog (origen, disparadoPor, employeeId, desde, hasta, iniciadoAt)
        OUTPUT INSERTED.id
        VALUES (:origen, :por, :emp, :desde, :hasta, GETDATE())
    """), {"origen": origen, "por": disparado_por, "emp": employee_id,
           "desde": desde, "hasta": hasta}).mappings().first()
    db.commit()
    return int(fila["id"])


def cerrar_recalculo(db: Session, log_id: int, procesados: int, filas: int,
                     errores: list) -> None:
    db.execute(text("""
        UPDATE RecalculoLog
        SET procesados = :proc, filas = :filas, errores = :err,
            finalizadoAt = GETDATE()
        WHERE id = :id
    """), {"proc": procesados, "filas": filas,
           "err": (json.dumps(errores, ensure_ascii=False) if errores else None),
           "id": log_id})
    db.commit()


def ultimos_recalculos(db: Session, limite: int = 50) -> list[dict]:
    filas = db.execute(text("""
        SELECT TOP (:limite) id, origen, disparadoPor, employeeId, desde, hasta,
               procesados, filas, errores, iniciadoAt, finalizadoAt
        FROM RecalculoLog ORDER BY id DESC
    """), {"limite": int(limite)}).mappings().all()
    return [dict(f) for f in filas]
```

- [ ] **Step 2: Modificar el DDL de `JornadaDiaria`**

En `app/database/asistencia.py`, agregar después de `ALTER_PERMISSION_OFICIAL_SQL`
(línea 60):

```python
ALTER_TOLERANCIA_ENTRADA_SQL = """
IF COL_LENGTH('JornadaDiaria','toleranciaEntradaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaEntradaUsada BIT NOT NULL DEFAULT 0;
"""

ALTER_TOLERANCIA_SALIDA_SQL = """
IF COL_LENGTH('JornadaDiaria','toleranciaSalidaUsada') IS NULL
ALTER TABLE JornadaDiaria ADD toleranciaSalidaUsada BIT NOT NULL DEFAULT 0;
"""

# Columnas que dejaron de ser derivadas: se mudaron a JornadaCorreccion.
# entradaManual y salidaManual se conservan porque si son derivadas -se
# reconstruyen leyendo JornadaCorreccion- y evitan un join en cada lectura.
COLUMNAS_A_ELIMINAR = ("corregidoPor", "corregidoAt", "observacion")


def _drop_columna(db: Session, tabla: str, columna: str) -> None:
    """
    Suelta el constraint de default antes de borrar la columna: SQL Server no
    permite eliminar una columna con default sin quitarlo primero.

    tabla y columna son constantes del propio codigo, nunca entrada del
    usuario: la interpolacion no expone inyeccion.
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

Reemplazar la función `ensure_tables` (líneas 74–85) por:

```python
def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_JORNADA_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_ESTADO_SQL))
    db.commit()
    db.execute(text(CREATE_CONFIG_SQL))
    db.commit()
    db.execute(text(ALTER_PERMISSION_OFICIAL_SQL))
    db.commit()
    db.execute(text(ALTER_TOLERANCIA_ENTRADA_SQL))
    db.commit()
    db.execute(text(ALTER_TOLERANCIA_SALIDA_SQL))
    db.commit()
    for columna in COLUMNAS_A_ELIMINAR:
        _drop_columna(db, "JornadaDiaria", columna)
    db.execute(text(SEED_CONFIG_SQL))
    db.commit()
    auditoria_ensure_tables(db)
```

Agregar el import al principio del archivo, después de la línea 14. **Una sola
línea con los dos nombres** — `reemplazar_incidencias` se usa en el Step 3:

```python
from app.database.asistencia_auditoria import (
    ensure_tables as auditoria_ensure_tables,
    reemplazar_incidencias,
)
```

- [ ] **Step 3: Actualizar las consultas de `JornadaDiaria`**

En `app/database/asistencia.py`, reemplazar `reemplazar_jornadas` (líneas 109–138):

```python
def reemplazar_jornadas(db: Session, employee_id: int, desde: date, hasta: date,
                        filas: list[dict], incidencias: list[dict]) -> int:
    """
    Borra el rango del empleado y reinserta jornadas e incidencias en la misma
    transaccion. Las dos son derivadas, asi que reemplazar es mas simple y mas
    seguro que reconciliar fila por fila: no deja huerfanas cuando un dia deja
    de corresponder (por ejemplo al cargarse una licencia que lo cubre).

    JornadaCorreccion no se toca: es dato propio y vive en su tabla.
    """
    db.execute(text("""
        DELETE FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta})

    ahora = datetime.now()
    for f in filas:
        db.execute(text("""
            INSERT INTO JornadaDiaria
                (employeeId, fecha, estado, horasRequeridas, horasTrabajadas,
                 saldoDia, entrada, salida, entradaManual, salidaManual,
                 permisoBanco, permisoDeuda, permisoOficial,
                 toleranciaEntradaUsada, toleranciaSalidaUsada, calculadoAt)
            VALUES
                (:employeeId, :fecha, :estado, :horasRequeridas, :horasTrabajadas,
                 :saldoDia, :entrada, :salida, :entradaManual, :salidaManual,
                 :permisoBanco, :permisoDeuda, :permisoOficial,
                 :toleranciaEntradaUsada, :toleranciaSalidaUsada, :calculadoAt)
        """), {**f, "employeeId": employee_id, "calculadoAt": ahora})

    reemplazar_incidencias(db, employee_id, desde, hasta, incidencias)
    db.commit()
    return len(filas)
```

`reemplazar_incidencias` ya quedó importado en el Step 2: no agregar una
segunda línea de import del mismo módulo.

Reemplazar `jornadas_de` (líneas 148–157):

```python
def jornadas_de(db: Session, employee_id: int, desde: date, hasta: date) -> list[dict]:
    """Jornadas del rango con sus incidencias agregadas como lista."""
    filas = db.execute(text("""
        SELECT j.id, j.fecha, j.estado, j.horasRequeridas, j.horasTrabajadas,
               j.saldoDia, j.entrada, j.salida, j.entradaManual, j.salidaManual,
               j.permisoBanco, j.permisoDeuda, j.permisoOficial,
               j.toleranciaEntradaUsada, j.toleranciaSalidaUsada,
               c.corregidoPor, c.observacion
        FROM JornadaDiaria j
        LEFT JOIN JornadaCorreccion c
               ON c.employeeId = j.employeeId AND c.fecha = j.fecha
        WHERE j.employeeId = :emp AND j.fecha >= :desde AND j.fecha <= :hasta
        ORDER BY j.fecha DESC
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()

    incidencias = db.execute(text("""
        SELECT fecha, tipo FROM JornadaIncidencia
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    por_dia: dict[date, list[str]] = {}
    for i in incidencias:
        d = i["fecha"] if isinstance(i["fecha"], date) else i["fecha"].date()
        por_dia.setdefault(d, []).append(i["tipo"])

    salida = []
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        salida.append({**dict(f), "incidencias": por_dia.get(d, [])})
    return salida
```

Reemplazar `get_jornada` (líneas 205–214):

```python
def get_jornada(db: Session, jornada_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT j.id, j.employeeId, j.fecha, j.estado,
               j.horasRequeridas, j.horasTrabajadas, j.saldoDia,
               j.entrada, j.salida, j.entradaManual, j.salidaManual,
               j.permisoBanco, j.permisoDeuda, j.permisoOficial,
               j.toleranciaEntradaUsada, j.toleranciaSalidaUsada,
               c.corregidoPor, c.observacion
        FROM JornadaDiaria j
        LEFT JOIN JornadaCorreccion c
               ON c.employeeId = j.employeeId AND c.fecha = j.fecha
        WHERE j.id = :id
    """), {"id": jornada_id}).mappings().first()
    return dict(fila) if fila else None
```

Eliminar por completo la función `marcar_correccion` (líneas 217–237): su
reemplazo es `upsert_correccion` en el módulo de auditoría.

- [ ] **Step 4: Permitir editar `fechaInicioModulo`**

Reemplazar `update_config` en `app/database/asistencia.py` (líneas 99–106):

```python
def update_config(db: Session, tol_entrada: int, tol_salida: int,
                  fecha_inicio: Optional[date] = None) -> dict:
    """
    fecha_inicio en None deja la que estaba. Se puede mover hacia atras cuando
    se recupera historico de los relojes, y hacia adelante para descartar un
    periodo poco confiable.
    """
    db.execute(text("""
        UPDATE AsistenciaConfig
        SET toleranciaEntradaMin = :te,
            toleranciaSalidaMin  = :ts,
            fechaInicioModulo    = COALESCE(:fi, fechaInicioModulo),
            updatedAt            = GETDATE()
        WHERE id = 1
    """), {"te": int(tol_entrada), "ts": int(tol_salida), "fi": fecha_inicio})
    db.commit()
    return get_config(db)
```

- [ ] **Step 5: Verificar que la suite sigue verde**

Run: `py -m pytest tests/ -v`
Expected: PASS — 65 tests, los mismos que antes. Son puros y no tocan estas
funciones; la corrida sirve como control de que no se rompió ninguna
importación al agregar el módulo de auditoría.

- [ ] **Step 6: Commit**

```bash
git add app/database/asistencia_auditoria.py app/database/asistencia.py
git commit -m "feat: tablas de correccion, incidencias y auditoria de recalculo

JornadaCorreccion saca las cargas manuales de la tabla derivada, con clave
natural (employeeId, fecha) y sin FK al id que el recalculo regenera.
JornadaIncidencia y RecalculoLog completan la trazabilidad.

JornadaDiaria suma los flags de tolerancia usada y pierde corregidoPor,
corregidoAt y observacion. fechaInicioModulo pasa a ser editable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Recálculo con las tablas nuevas y detección de huecos

**Files:**
- Modify: `app/services/asistencia_recalc.py`
- Modify: `app/routes/asistencia.py:64-106` (endpoint de corrección)

**Interfaces:**
- Consumes de Task 1: `Correccion`, `HorarioDia`, y las constantes `INCIDENCIA_*`.
- Consumes de Task 2: `EntradaDia`, `ResultadoDia`, `calcular_anio`.
- Consumes de Task 3: `correcciones_por_dia`, `upsert_correccion`,
  `abrir_recalculo`, `cerrar_recalculo`, `reemplazar_jornadas(db, emp, desde, hasta, filas, incidencias)`.
- Produces:
  - `recalcular_anio(db, employee_id: int, anio: int) -> int`
  - `recalcular_historia(db, employee_id: int) -> int`
  - `recalcular_todos(db, anio: int, origen: str = "nocturno", disparado_por: Optional[int] = None) -> dict` — devuelve `{"procesados", "filas", "errores"}`
  - `anios_con_huecos(db, hoy: Optional[date] = None) -> list[int]`

- [ ] **Step 1: Reemplazar la lectura de correcciones y el armado de filas**

En `app/services/asistencia_recalc.py`, reemplazar los imports (líneas 11–23):

```python
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.asistencia import get_config, reemplazar_jornadas
from app.database.asistencia_auditoria import (
    abrir_recalculo, cerrar_recalculo, correcciones_por_dia,
)
from app.services.asistencia_calc import (
    EntradaDia, Permiso, ResultadoDia, calcular_anio,
)
from app.services.marcaciones_norm import Correccion, HorarioDia, normalizar

log = logging.getLogger(__name__)
```

Eliminar por completo `_correcciones_por_dia` (líneas 105–122): su reemplazo es
`correcciones_por_dia` del módulo de auditoría, que lee de `JornadaCorreccion`.

Reemplazar `_a_fila` (líneas 125–143):

```python
def _a_fila(r: ResultadoDia) -> dict:
    """
    La fila de JornadaDiaria. Todo sale del resultado: los flags manuales ya
    vienen resueltos desde los extremos, y corregidoPor y observacion viven en
    JornadaCorreccion, no aca.
    """
    return {
        "fecha": r.fecha,
        "estado": r.estado,
        "horasRequeridas": round(r.horasRequeridas, 2),
        "horasTrabajadas": round(r.horasTrabajadas, 2),
        "saldoDia": round(r.saldoDia, 2),
        "entrada": r.entrada,
        "salida": r.salida,
        "entradaManual": r.entradaManual,
        "salidaManual": r.salidaManual,
        "permisoBanco": round(r.permisoBanco, 2),
        "permisoDeuda": round(r.permisoDeuda, 2),
        "permisoOficial": round(r.permisoOficial, 2),
        "toleranciaEntradaUsada": r.toleranciaEntradaUsada,
        "toleranciaSalidaUsada": r.toleranciaSalidaUsada,
    }


def _a_incidencias(resultados: list[ResultadoDia]) -> list[dict]:
    """Aplana las incidencias de todos los dias a filas de JornadaIncidencia."""
    return [
        {"fecha": r.fecha, "tipo": tipo, "detalle": None}
        for r in resultados
        for tipo in r.incidencias
    ]
```

- [ ] **Step 2: Reescribir `recalcular_anio`**

Reemplazar la función completa (líneas 146–198):

```python
def recalcular_anio(db: Session, employee_id: int, anio: int) -> int:
    """Recomputa el anio completo de un empleado. Idempotente."""
    emp = _datos_empleado(db, employee_id)
    if emp is None or not emp["biometricoId"]:
        return 0

    cfg = get_config(db)
    inicio_modulo = cfg["fechaInicioModulo"]
    if not isinstance(inicio_modulo, date):
        inicio_modulo = inicio_modulo.date()

    desde = max(date(anio, 1, 1), inicio_modulo)
    ingreso = emp.get("fechaIngreso")
    if ingreso is not None:
        ingreso = ingreso if isinstance(ingreso, date) else ingreso.date()
        desde = max(desde, ingreso)
    hasta = min(date(anio, 12, 31), date.today())
    if desde > hasta:
        return 0

    correcciones = correcciones_por_dia(db, employee_id, desde, hasta)
    marcaciones = _marcaciones_por_dia(db, emp["biometricoId"], desde, hasta)
    feriados = _feriados(db, desde, hasta)
    licencias = _dias_con_licencia(db, employee_id, desde, hasta)
    permisos = _permisos_por_dia(db, employee_id, desde, hasta)

    horario = None
    if emp["horaInicio"] is not None and emp["horaFin"] is not None:
        horario = HorarioDia(
            horaInicio=float(emp["horaInicio"]),
            horaFin=float(emp["horaFin"]),
            horasTrabajo=float(emp["horasTrabajo"] or 0),
        )

    entradas = []
    for d in _rango_dias(desde, hasta):
        entradas.append(EntradaDia(
            fecha=d,
            extremos=normalizar(
                marcaciones.get(d, []), horario, correcciones.get(d),
            ),
            horario=horario,
            es_feriado=d in feriados,
            tiene_licencia=d in licencias,
            permisos=permisos.get(d, []),
        ))

    resultados = calcular_anio(
        entradas, cfg["toleranciaEntradaMin"], cfg["toleranciaSalidaMin"],
    )
    return reemplazar_jornadas(
        db, employee_id, desde, hasta,
        [_a_fila(r) for r in resultados], _a_incidencias(resultados),
    )
```

- [ ] **Step 3: Agregar auditoría a `recalcular_todos` y la detección de huecos**

Reemplazar `recalcular_todos` (líneas 217–237) y agregar `anios_con_huecos`:

```python
def recalcular_todos(db: Session, anio: int, origen: str = "nocturno",
                     disparado_por: Optional[int] = None) -> dict:
    """
    Recalculo masivo. Un empleado que falla no debe abortar el resto: se
    registra y se sigue. Toda la corrida queda auditada en RecalculoLog.
    """
    log_id = abrir_recalculo(db, origen, disparado_por, None,
                             date(anio, 1, 1), date(anio, 12, 31))
    ids = [r["id"] for r in db.execute(text(
        "SELECT id FROM Employee WHERE biometricoId IS NOT NULL ORDER BY id"
    )).mappings().all()]

    filas = 0
    ok = 0
    errores = []
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo fallido para empleado %s: %s", eid, e)
            errores.append({"employeeId": eid, "error": str(e)})

    cerrar_recalculo(db, log_id, ok, filas, errores)
    return {"procesados": ok, "filas": filas, "errores": errores}


def anios_con_huecos(db: Session, hoy: Optional[date] = None) -> list[int]:
    """
    Anios que hay que recalcular porque algun empleado vinculado quedo atrasado.

    Toma la fecha calculada mas vieja entre todos los empleados con reloj: si
    alguno no tiene ninguna jornada, cuenta como fechaInicioModulo. Si esa
    fecha esta a mas de un dia de hoy, hay hueco.

    Es deliberadamente grueso. Recalcular un anio de mas cuesta segundos y da
    el mismo resultado, mientras que no detectar un hueco deja el saldo mal.
    """
    cfg = get_config(db)
    inicio = cfg["fechaInicioModulo"]
    if not isinstance(inicio, date):
        inicio = inicio.date()
    hoy = hoy or date.today()

    fila = db.execute(text("""
        SELECT MIN(COALESCE(j.ultima, :inicio)) AS mas_atrasada
        FROM Employee e
        LEFT JOIN (
            SELECT employeeId, MAX(fecha) AS ultima
            FROM JornadaDiaria GROUP BY employeeId
        ) j ON j.employeeId = e.id
        WHERE e.biometricoId IS NOT NULL
    """), {"inicio": inicio}).mappings().first()

    if fila is None or fila["mas_atrasada"] is None:
        return []
    atrasada = fila["mas_atrasada"]
    if not isinstance(atrasada, date):
        atrasada = atrasada.date()
    if atrasada >= hoy - timedelta(days=1):
        return []
    return list(range(max(atrasada.year, inicio.year), hoy.year + 1))
```

- [ ] **Step 4: Apuntar el endpoint de corrección a la tabla nueva**

En `app/routes/asistencia.py`, reemplazar el import de la línea 17–20:

```python
from app.database.asistencia import (
    ensure_tables, get_config, get_jornada, jornadas_de, jornadas_incompletas,
    saldo_acumulado, tablero, update_config,
)
from app.database.asistencia_auditoria import upsert_correccion
```

En `post_correccion_jornada`, reemplazar el bloque de las líneas 98–104:

```python
    corregido_por = int(usuario["employeeId"])
    fecha = jornada["fecha"]
    fecha = fecha if isinstance(fecha, date) else fecha.date()
    upsert_correccion(db, jornada["employeeId"], fecha, entrada, salida,
                      corregido_por, data.get("observacion"))

    anio = fecha.year
    recalcular_anio(db, jornada["employeeId"], anio)
```

- [ ] **Step 5: Verificar que la suite sigue verde**

Run: `py -m pytest tests/ -v`
Expected: PASS — 65 tests. No se rompió ninguna importación ni quedó ninguna
referencia a `marcar_correccion`, que se eliminó en la Task 3.

- [ ] **Step 6: Commit**

```bash
git add app/services/asistencia_recalc.py app/routes/asistencia.py
git commit -m "refactor: el recalculo lee correcciones de JornadaCorreccion

Las cargas manuales ya no se releen desde la tabla que el DELETE va a borrar.
Se persisten las incidencias por dia y toda corrida masiva queda auditada.
anios_con_huecos detecta empleados atrasados para la autoreparacion.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Sincronización por ventanas diarias

**Files:**
- Modify: `app/services/reloj_sync.py`
- Modify: `app/routes/relojes.py`
- Test: `tests/test_reloj_sync.py`

**Interfaces:**
- Consumes: nada de las tareas anteriores. Es independiente.
- Produces:
  - `ventanas_diarias(desde: datetime, hasta: datetime) -> Iterator[tuple[datetime, datetime]]`
  - `parece_truncado(payload: dict) -> bool`
  - `sincronizar_reloj(db, reloj_ip, desde=None, hasta=None) -> dict` — el dict suma la clave `"ventanasTruncadas": list[str]`
  - `sincronizar_todos(db, desde=None, hasta=None) -> list[dict]` — firma sin cambios
  - `POST /relojes/resincronizar` con body `{"desde": "YYYY-MM-DD", "hasta": "YYYY-MM-DD"}`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_reloj_sync.py`:

```python
# -- Ventanas diarias ---------------------------------------------------------

def test_un_rango_de_un_dia_da_una_sola_ventana():
    desde = datetime(2026, 7, 30, 8, 0)
    hasta = datetime(2026, 7, 30, 20, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == [(desde, hasta)]


def test_un_rango_de_tres_dias_se_parte_en_tres_ventanas():
    desde = datetime(2026, 7, 30, 8, 0)
    hasta = datetime(2026, 8, 1, 10, 0)
    ventanas = list(s.ventanas_diarias(desde, hasta))
    assert ventanas == [
        (datetime(2026, 7, 30, 8, 0), datetime(2026, 7, 31, 0, 0)),
        (datetime(2026, 7, 31, 0, 0), datetime(2026, 8, 1, 0, 0)),
        (datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 1, 10, 0)),
    ]


def test_la_ventana_incremental_de_cinco_minutos_no_se_parte():
    desde = datetime(2026, 7, 30, 9, 55)
    hasta = datetime(2026, 7, 30, 10, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == [(desde, hasta)]


def test_rango_invertido_no_produce_ventanas():
    desde = datetime(2026, 7, 30, 10, 0)
    hasta = datetime(2026, 7, 30, 9, 0)
    assert list(s.ventanas_diarias(desde, hasta)) == []


def test_la_carga_inicial_de_treinta_dias_da_treinta_y_un_ventanas():
    ahora = datetime(2026, 7, 30, 12, 0)
    desde, hasta = s.calcular_ventana(None, ahora)
    # 30 dias hacia atras desde el mediodia: 30 cortes de medianoche + el resto.
    assert len(list(s.ventanas_diarias(desde, hasta))) == 31


# -- Deteccion de truncamiento ------------------------------------------------

def test_respuesta_en_el_tope_exacto_sin_mas_paginas_parece_truncada():
    payload = {"AcsEvent": {"responseStatusStrg": "OK",
                            "numOfMatches": s.MAX_RESULTS}}
    assert s.parece_truncado(payload) is True


def test_respuesta_por_debajo_del_tope_no_parece_truncada():
    payload = {"AcsEvent": {"responseStatusStrg": "OK",
                            "numOfMatches": s.MAX_RESULTS - 1}}
    assert s.parece_truncado(payload) is False


def test_respuesta_en_el_tope_pero_con_mas_paginas_no_parece_truncada():
    # El equipo avisa que hay mas: esta paginando bien, no truncando.
    payload = {"AcsEvent": {"responseStatusStrg": "MORE",
                            "numOfMatches": s.MAX_RESULTS}}
    assert s.parece_truncado(payload) is False


def test_payload_vacio_no_parece_truncado():
    assert s.parece_truncado({}) is False
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `py -m pytest tests/test_reloj_sync.py -v`
Expected: FAIL — `AttributeError: module 'app.services.reloj_sync' has no attribute 'ventanas_diarias'`

- [ ] **Step 3: Implementar las ventanas diarias y la detección**

En `app/services/reloj_sync.py`, reemplazar el import de la línea 12:

```python
from datetime import datetime, time, timedelta
from typing import Iterator, Optional
```

Agregar después de `calcular_ventana` (línea 41):

```python
def ventanas_diarias(desde: datetime,
                     hasta: datetime) -> Iterator[tuple[datetime, datetime]]:
    """
    Parte un rango en ventanas que no cruzan la medianoche.

    La carga inicial pedia 30 dias en una sola llamada y los equipos devolvian
    solo una fraccion: en el periodo 30/06-29/07 se capturo el 7,4% del rango
    de correlativos, contra el 25% del sync incremental. Pedir de a un dia
    mantiene cada respuesta dentro de lo que el equipo puede entregar.

    Una ventana corta -los 5 minutos del sync incremental- sale entera, sin
    partir.
    """
    actual = desde
    while actual < hasta:
        siguiente_medianoche = datetime.combine(
            actual.date() + timedelta(days=1), time.min,
        )
        fin = min(siguiente_medianoche, hasta)
        yield actual, fin
        actual = fin


def parece_truncado(payload: dict) -> bool:
    """
    El equipo devolvio exactamente el tope pedido y dijo que no hay mas.

    Es el sintoma de un dispositivo que corta la respuesta por su cuenta en vez
    de paginar: si de verdad no hubiera mas eventos, el numero seria menor al
    tope casi siempre.
    """
    ev = (payload or {}).get("AcsEvent") or {}
    if ev.get("responseStatusStrg") == "MORE":
        return False
    return ev.get("numOfMatches") == MAX_RESULTS
```

- [ ] **Step 4: Reescribir `sincronizar_reloj` para iterar ventanas**

Reemplazar `sincronizar_reloj` (líneas 90–148):

```python
def _sincronizar_ventana(db: Session, reloj_ip: str, desde: datetime,
                         hasta: datetime, resultado: dict) -> int:
    """
    Una ventana temporal, paginada hasta agotarla. Acumula en resultado y
    devuelve el serialNo mas alto que vio.
    """
    posicion = 0
    max_visto = 0
    for _ in range(MAX_PAGINAS):
        payload = buscar_eventos(reloj_ip, desde, hasta, posicion, MAX_RESULTS)
        filas = extraer_marcaciones(payload, reloj_ip)
        resultado["leidos"] += len(filas)
        if filas:
            resultado["insertados"] += insertar_marcaciones(db, filas)
            max_visto = max(max_visto, max(f["serialNo"] for f in filas))
        if not hay_mas_paginas(payload):
            if parece_truncado(payload):
                log.warning(
                    "Reloj %s: la ventana %s a %s devolvio el tope exacto de "
                    "%s resultados sin indicar mas paginas. El equipo pudo "
                    "haber cortado la respuesta.",
                    reloj_ip, desde, hasta, MAX_RESULTS,
                )
                resultado["ventanasTruncadas"].append(
                    f"{desde.isoformat()}/{hasta.isoformat()}"
                )
            return max_visto
        posicion += (payload.get("AcsEvent") or {}).get("numOfMatches", MAX_RESULTS)

    log.warning(
        "Reloj %s: cap MAX_PAGINAS=%s alcanzado en la ventana %s a %s. "
        "Quedan eventos sin leer.",
        reloj_ip, MAX_PAGINAS, desde, hasta,
    )
    resultado["ventanasTruncadas"].append(
        f"{desde.isoformat()}/{hasta.isoformat()}"
    )
    return max_visto


def sincronizar_reloj(db: Session, reloj_ip: str,
                     desde: Optional[datetime] = None,
                     hasta: Optional[datetime] = None) -> dict:
    """
    Sincroniza un equipo iterando ventanas de un dia. Nunca propaga excepcion:
    un reloj caido se registra en RelojSync.ultimoError y no debe tumbar el job
    ni el otro equipo.
    """
    registrar_reloj(db, reloj_ip)
    ahora = hasta or datetime.now()
    if desde is None:
        desde, ahora = calcular_ventana(ultima_sync(db, reloj_ip), ahora)

    resultado = {"relojIp": reloj_ip, "leidos": 0, "insertados": 0,
                 "error": None, "ventanasTruncadas": []}
    previo_max = max_serial_no(db, reloj_ip)

    try:
        max_visto = 0
        for v_desde, v_hasta in ventanas_diarias(desde, ahora):
            max_visto = max(
                max_visto,
                _sincronizar_ventana(db, reloj_ip, v_desde, v_hasta, resultado),
            )

        # Riesgo conocido: si el equipo reinicia su correlativo, los eventos
        # nuevos colisionarian con los viejos y se descartarian en silencio.
        if previo_max is not None and max_visto and max_visto < previo_max:
            log.warning(
                "Reloj %s: serialNo maximo recibido (%s) es menor al almacenado (%s). "
                "Posible reinicio del correlativo: las marcaciones nuevas podrian "
                "estar descartandose por la unicidad.",
                reloj_ip, max_visto, previo_max,
            )

        if resultado["ventanasTruncadas"]:
            # No se avanza ultimaSync: el proximo ciclo reintenta la ventana.
            log.warning("Reloj %s: %s ventanas incompletas, no se avanza ultimaSync",
                        reloj_ip, len(resultado["ventanasTruncadas"]))
            db.commit()
            return resultado

        marcar_sync_ok(db, reloj_ip, ahora)
        db.commit()
    except Exception as e:
        resultado["error"] = str(e)
        marcar_sync_error(db, reloj_ip, str(e))
        db.commit()
        log.warning("Reloj %s: sync fallida: %s", reloj_ip, e)

    return resultado
```

- [ ] **Step 5: Agregar el endpoint de re-sincronización**

En `app/routes/relojes.py`, agregar el import de `Body` en la línea 11:

```python
from fastapi import APIRouter, Body, Depends, HTTPException
```

Agregar el endpoint después de `post_carga_inicial` (línea 62):

```python
@router.post("/relojes/resincronizar", dependencies=[Depends(require_admin)])
def post_resincronizar(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Re-lee un rango historico iterando de a un dia.

    Sirve para recuperar periodos que la carga inicial trajo truncados: los
    eventos siguen en los equipos y la unicidad (relojIp, serialNo) hace que
    reprocesar sea inofensivo.
    """
    try:
        desde = datetime.fromisoformat(str(data["desde"]))
        hasta = datetime.fromisoformat(str(data["hasta"]))
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Hay que enviar 'desde' y 'hasta' en formato ISO (YYYY-MM-DD)",
        )
    if desde >= hasta:
        raise HTTPException(status_code=400,
                            detail="'desde' debe ser anterior a 'hasta'")
    if (hasta - desde).days > 90:
        raise HTTPException(
            status_code=400,
            detail="El rango no puede superar los 90 dias: partilo en tramos",
        )
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resultados": sincronizar_todos(db, desde=desde, hasta=hasta),
    }
```

- [ ] **Step 6: Correr los tests**

Run: `py -m pytest tests/test_reloj_sync.py -v`
Expected: PASS — 15 tests (6 originales + 9 nuevos)

- [ ] **Step 7: Commit**

```bash
git add app/services/reloj_sync.py app/routes/relojes.py tests/test_reloj_sync.py
git commit -m "fix: sincronizar por ventanas diarias en vez de 30 dias de golpe

La carga inicial pedia un mes en una llamada y los equipos devolvian una
fraccion: 7,4% del rango de correlativos contra 25% del sync incremental.
Se agrega deteccion de truncamiento y el endpoint de resincronizacion para
recuperar rangos historicos.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Endpoints de asistencia y auto-reparación al arrancar

**Files:**
- Modify: `app/routes/asistencia.py`
- Modify: `app/scheduler.py`

**Interfaces:**
- Consumes de Task 3: `incidencias_abiertas`, `ultimos_recalculos`, `update_config` con `fecha_inicio`.
- Consumes de Task 4: `recalcular_anio`, `recalcular_todos`, `anios_con_huecos`.
- Produces:
  - `POST /asistencia/recalcular` — body opcional `{employeeId?, anio?}`
  - `GET /asistencia/incidencias` — params `tipo?`, `desde?`, `hasta?`
  - `GET /asistencia/recalculos` — param `limite?`
  - `PUT /asistencia/config` acepta `fechaInicioModulo`
  - `app.scheduler.SEGUNDOS_AUTOREPARACION = 30`

- [ ] **Step 1: Agregar los endpoints**

En `app/routes/asistencia.py`, ampliar los imports:

```python
from app.database.asistencia_auditoria import (
    incidencias_abiertas, ultimos_recalculos, upsert_correccion,
)
from app.services.asistencia_recalc import recalcular_anio, recalcular_todos
```

Agregar al final del archivo:

```python
@router.post("/recalcular", dependencies=[SOLO_RRHH])
def post_recalcular(data: dict = Body(default={}),
                    usuario: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Recalculo manual. Sin cuerpo recalcula todos los empleados del anio en
    curso; con employeeId, solo ese. Es el disparador que faltaba: el job
    nocturno requiere que el servidor este vivo a las 3 AM.
    """
    ensure_tables(db)
    anio = data.get("anio")
    try:
        anio = int(anio) if anio is not None else date.today().year
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'anio' debe ser un entero")
    if not (2000 <= anio <= date.today().year + 1):
        raise HTTPException(status_code=400, detail="'anio' fuera de rango")

    disparado_por = usuario.get("employeeId")
    employee_id = data.get("employeeId")
    if employee_id is not None:
        try:
            employee_id = int(employee_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail="'employeeId' debe ser un entero")
        filas = recalcular_anio(db, employee_id, anio)
        return {"employeeId": employee_id, "anio": anio,
                "procesados": 1, "filas": filas, "errores": []}

    resultado = recalcular_todos(db, anio, origen="manual",
                                 disparado_por=disparado_por)
    return {"anio": anio, **resultado}


@router.get("/incidencias", dependencies=[SOLO_RRHH])
def get_incidencias(tipo: str | None = None, desde: str | None = None,
                    hasta: str | None = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {"desde": d.isoformat(), "hasta": h.isoformat(),
            "incidencias": incidencias_abiertas(db, tipo, d, h)}


@router.get("/recalculos", dependencies=[SOLO_RRHH])
def get_recalculos(limite: int = 50, db: Session = Depends(get_db)):
    ensure_tables(db)
    if not (1 <= limite <= 200):
        raise HTTPException(status_code=400,
                            detail="'limite' debe estar entre 1 y 200")
    return {"recalculos": ultimos_recalculos(db, limite)}
```

Reemplazar `put_asistencia_config` (líneas 158–170):

```python
@router.put("/config", dependencies=[SOLO_RRHH])
def put_asistencia_config(data: dict = Body(...), db: Session = Depends(get_db)):
    ensure_tables(db)
    try:
        tol_entrada = int(data.get("toleranciaEntradaMin"))
        tol_salida = int(data.get("toleranciaSalidaMin"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="toleranciaEntradaMin y toleranciaSalidaMin deben ser enteros")
    if not (0 <= tol_entrada <= 120) or not (0 <= tol_salida <= 120):
        raise HTTPException(status_code=400,
                            detail="Las tolerancias deben estar entre 0 y 120 minutos")

    fecha_inicio = None
    crudo = data.get("fechaInicioModulo")
    if crudo not in (None, ""):
        try:
            fecha_inicio = date.fromisoformat(str(crudo))
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="fechaInicioModulo debe ser YYYY-MM-DD")
        if fecha_inicio > date.today():
            raise HTTPException(status_code=400,
                                detail="fechaInicioModulo no puede ser futura")

    return update_config(db, tol_entrada, tol_salida, fecha_inicio)
```

- [ ] **Step 2: Agregar el job de auto-reparación**

En `app/scheduler.py`, ampliar el import de la línea 16:

```python
from app.services.asistencia_recalc import anios_con_huecos, recalcular_todos
```

Agregar la constante después de la línea 21:

```python
SEGUNDOS_AUTOREPARACION = 30  # margen para que el arranque termine primero
```

Agregar la función después de `_tick_asistencia` (línea 56):

```python
def _tick_autoreparacion():
    """
    Busca empleados con jornadas atrasadas y recalcula sus anios.

    Es la red que atrapa el modo de falla que dejo JornadaDiaria vacia: el job
    nocturno corre a las 3 AM y nunca hubo un servidor vivo a esa hora. Corre
    una sola vez, unos segundos despues del arranque, para no demorar el
    startup.
    """
    db = SessionLocal()
    try:
        anios = anios_con_huecos(db)
        if not anios:
            log.info("Autoreparacion de asistencia: sin huecos que completar")
            return
        for anio in anios:
            resultado = recalcular_todos(db, anio, origen="arranque")
            log.info("Autoreparacion %s: %s empleados, %s jornadas, %s errores",
                     anio, resultado["procesados"], resultado["filas"],
                     len(resultado["errores"]))
    except Exception as e:
        log.exception("Fallo inesperado en la autoreparacion de asistencia: %s", e)
    finally:
        db.close()
```

Agregar el job dentro de `iniciar_scheduler`, después del bloque de
`recalculo_asistencia` (línea 88):

```python
    _scheduler.add_job(
        _tick_autoreparacion,
        "date",
        run_date=datetime.now() + timedelta(seconds=SEGUNDOS_AUTOREPARACION),
        id="autoreparacion_asistencia",
        max_instances=1,
        replace_existing=True,
    )
```

Ampliar el import de fechas de la línea 9:

```python
from datetime import date, datetime, timedelta
```

Actualizar el log final de `iniciar_scheduler` (líneas 90–91):

```python
    _scheduler.start()
    log.info("Scheduler iniciado: sync cada %s min, recalculo a las %s:00, "
             "autoreparacion en %s s",
             INTERVALO_MINUTOS, HORA_RECALCULO_ASISTENCIA, SEGUNDOS_AUTOREPARACION)
    return _scheduler
```

- [ ] **Step 3: Verificar que la suite sigue verde**

Run: `py -m pytest tests/ -v`
Expected: PASS — 74 tests. Los endpoints y el scheduler no tienen tests
unitarios: son capas de I/O cuya lógica ya está cubierta en los módulos puros.

- [ ] **Step 4: Verificar que los módulos importan sin errores**

Run: `py -c "import app.main"`
Expected: la salida del arranque de la conexión a ObraSocial, sin traceback.
Confirma que no quedó ninguna importación rota ni referencia a
`marcar_correccion`, que se eliminó en la Task 3.

- [ ] **Step 5: Commit**

```bash
git add app/routes/asistencia.py app/scheduler.py
git commit -m "feat: endpoints de recalculo e incidencias mas autoreparacion

POST /asistencia/recalcular da el disparador manual que faltaba, y un job
one-shot a los 30 s del arranque completa los dias que quedaron sin calcular.
fechaInicioModulo pasa a editarse desde la configuracion.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Migración de datos y verificación end-to-end

**Files:**
- Create: `scripts/migrar_asistencia_2026_08.py`

**Interfaces:**
- Consumes de Task 3: `ensure_tables` de `app.database.asistencia`.
- Consumes de Task 4: `recalcular_todos`.
- Produces: nada que consuman tareas posteriores. Es la última.

**Contexto:** `JornadaDiaria` está vacía y `fechaInicioModulo` vale `2026-06-30`.
Esta tarea mueve la fecha al `2026-07-30` y corre el primer backfill. El cambio
de fecha **no** va en `ensure_tables`: una sentencia que corre en cada arranque
volvería a empujar la fecha hacia adelante si RRHH la mueve hacia atrás tras
recuperar histórico.

- [ ] **Step 1: Escribir el script de migración**

Crear `scripts/migrar_asistencia_2026_08.py`:

```python
"""
Migracion unica del modulo de asistencia, agosto 2026.

1. Crea las tablas nuevas y aplica los cambios de esquema.
2. Mueve fechaInicioModulo del 30/06 al 30/07.
3. Corre el primer backfill.

El paso 2 se hace aca y no en ensure_tables a proposito: si corriera en cada
arranque, volveria a empujar la fecha hacia adelante cada vez que RRHH la mueva
hacia atras despues de recuperar historico de los relojes.

Motivo del cambio de fecha: la carga inicial del 30/07 pidio 30 dias en una
sola llamada y los equipos devolvieron una fraccion. En el periodo 30/06-29/07
se capturo el 7,4% del rango de correlativos, contra el 25% del sync
incremental posterior. Calcular saldos sobre ese mes produciria ausencias y
jornadas incompletas falsas para casi todo el personal.

Uso:
    py scripts/migrar_asistencia_2026_08.py
"""

import sys
from datetime import date

from sqlalchemy import text

from app.database.asistencia import ensure_tables, get_config
from app.database.database import SessionLocal
from app.services.asistencia_recalc import recalcular_todos

FECHA_INICIO_NUEVA = date(2026, 7, 30)


def main() -> int:
    db = SessionLocal()
    try:
        print("[1/3] Creando tablas y aplicando cambios de esquema...")
        ensure_tables(db)
        print("      OK")

        print(f"[2/3] Moviendo fechaInicioModulo a {FECHA_INICIO_NUEVA}...")
        antes = get_config(db)["fechaInicioModulo"]
        db.execute(text("""
            UPDATE AsistenciaConfig
            SET fechaInicioModulo = :fecha, updatedAt = GETDATE()
            WHERE id = 1
        """), {"fecha": FECHA_INICIO_NUEVA})
        db.commit()
        print(f"      {antes} -> {get_config(db)['fechaInicioModulo']}")

        print(f"[3/3] Backfill del anio {FECHA_INICIO_NUEVA.year}...")
        resultado = recalcular_todos(db, FECHA_INICIO_NUEVA.year, origen="manual")
        print(f"      {resultado['procesados']} empleados, "
              f"{resultado['filas']} jornadas, "
              f"{len(resultado['errores'])} errores")
        for e in resultado["errores"]:
            print(f"      ERROR empleado {e['employeeId']}: {e['error']}")

        return 1 if resultado["errores"] else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Correr la migración**

Run: `py scripts/migrar_asistencia_2026_08.py`
Expected:
```
[1/3] Creando tablas y aplicando cambios de esquema...
      OK
[2/3] Moviendo fechaInicioModulo a 2026-07-30...
      2026-06-30 -> 2026-07-30
[3/3] Backfill del anio 2026...
      5 empleados, N jornadas, 0 errores
```

Si aparecen errores por empleado, **no continuar**: reportarlos como bloqueo.

- [ ] **Step 3: Verificar el resultado contra la base**

Run:
```bash
py -c "
from sqlalchemy import text
from app.database.database import SessionLocal
db = SessionLocal()
for t, q in [
    ('Config', 'SELECT fechaInicioModulo FROM AsistenciaConfig WHERE id=1'),
    ('Jornadas por estado', 'SELECT estado, COUNT(*) n, SUM(saldoDia) saldo FROM JornadaDiaria GROUP BY estado'),
    ('Saldo por empleado', 'SELECT j.employeeId, e.name, COUNT(*) dias, SUM(j.saldoDia) saldo FROM JornadaDiaria j JOIN Employee e ON e.id=j.employeeId GROUP BY j.employeeId, e.name'),
    ('Incidencias', 'SELECT tipo, COUNT(*) n FROM JornadaIncidencia GROUP BY tipo'),
    ('Recalculos', 'SELECT TOP 3 id, origen, procesados, filas, finalizadoAt FROM RecalculoLog ORDER BY id DESC'),
]:
    print(f'== {t}')
    for r in db.execute(text(q)).mappings().all():
        print('  ', dict(r))
db.close()
"
```

Expected — verificaciones concretas:
- `fechaInicioModulo` es `2026-07-30`
- Hay filas en `JornadaDiaria` con fechas desde el 30/07
- **Ningún** empleado tiene saldo exactamente `0` con `dias > 0` salvo que
  todos sus días sean `sin_horario` o `incompleta`
- `JornadaIncidencia` tiene al menos dos filas `sin_cronograma` (los empleados
  1 y 2 no tienen `cronogramaId`)
- `RecalculoLog` tiene una corrida con `finalizadoAt` no nulo

- [ ] **Step 4: Correr la suite completa**

Run: `py -m pytest tests/ -v`
Expected: PASS — 74 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/migrar_asistencia_2026_08.py
git commit -m "chore: migracion de agosto 2026 del modulo de asistencia

Mueve fechaInicioModulo al 30/07 -descartando el mes que la carga inicial
trajo truncado- y corre el primer backfill. Va en un script y no en
ensure_tables para que no vuelva a empujar la fecha si RRHH la mueve hacia
atras tras recuperar historico.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verificación final

Al terminar las 7 tareas:

- `py -m pytest tests/ -v` → 74 tests en verde (38 previos + 36 nuevos)
- `py -c "import app.main"` → sin traceback
- `JornadaDiaria` poblada desde el 30/07/2026
- `JornadaIncidencia` con las incidencias `sin_cronograma` de los empleados sin
  cronograma
- `RecalculoLog` con la corrida del backfill cerrada

**Fuera de alcance, para los bloques B y C:** justificación de ausencias con
documentación adjunta, timeline colapsable del empleado, taxonomía extendida de
estados con badges, indicador de abuso de tolerancia, y sacar los acumulados
del dashboard del empleado.

**Pendiente operativo, no de código:** 169 de los 174 biométricos que marcan no
tienen empleado vinculado. `GET /asistencia/incidencias` no los expone —solo
cubre empleados ya vinculados—, así que sigue siendo carga de datos de RRHH.
