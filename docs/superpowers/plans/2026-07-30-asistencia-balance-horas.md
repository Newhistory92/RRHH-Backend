# Módulo de Asistencia y Balance de Horas — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir las marcaciones crudas de los relojes biométricos en un balance de horas por empleado —acumulado sin corte de período— con tablero de corrección para RRHH y vista propia para el empleado.

**Architecture:** Un motor de cálculo puro sin acceso a base de datos produce una fila por empleado por día en `JornadaDiaria`; el saldo acumulado es un `SUM(saldoDia)`. El recálculo tiene un solo camino de código, con unidad (empleado, año), disparado por un job nocturno y por eventos puntuales (corrección manual, cambio de `biometricoId`, licencias, permisos).

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()` con binds), SQL Server vía pyodbc, APScheduler, pytest. Frontend Next.js 14 App Router + React + PrimeReact + Tailwind.

**Spec:** `docs/superpowers/specs/2026-07-30-asistencia-balance-horas-design.md`

## Global Constraints

- **No levantar el servidor.** Ningún paso de este plan arranca `uvicorn` ni un dev server. La verificación es por `pytest` o por inspección de código. El usuario levanta el servidor cuando quiere.
- **Sin credenciales en código.** Nada de IPs, usuarios ni contraseñas de relojes fuera de `.env`. `.env` está en `.gitignore` y no se commitea nunca.
- **Solo lectura sobre los relojes.** Este módulo no toca `app/services/isapi_client.py` ni agrega llamadas a los equipos. Consume únicamente la tabla `Marcacion` ya poblada.
- **DDL idempotente.** Toda creación de tabla usa `IF OBJECT_ID(...) IS NULL` y toda columna nueva `IF COL_LENGTH(...) IS NULL`, cada sentencia en su propio batch con su `commit()`, igual que `app/database/marcaciones.py`.
- **SQL parametrizado.** Nunca interpolar valores en el SQL. Los `IN (...)` se arman con binds generados (`:s0, :s1, ...`), como en `insertar_marcaciones`.
- `BANCO_PERMISO_ANUAL_HORAS = 12.0` — constante en código, no configurable.
- Días hábiles: **lunes a viernes** (`weekday()` 0 a 4), iguales para todos.
- Tolerancias: default **15 minutos** entrada y **15 minutos** salida, configurables por RRHH en `AsistenciaConfig`.
- `Horario.horaInicio` y `Horario.horaFin` son **decimales** (`8.5` = 08:30), no strings.
- `License.status = 'Aprobada'` es el literal exacto que marca una licencia vigente.
- Los roles se importan de `app/routes/rrhh.py`: `ROLE_RRHH` (hoy aliaseado a `ROLE_ADMIN`). No inventar IDs nuevos.
- Comentarios y docstrings en español sin tildes en identificadores, siguiendo el estilo de `app/services/reloj_sync.py`.

---

## Estructura de archivos

| archivo | responsabilidad |
|---|---|
| `app/services/asistencia_calc.py` | **Crear.** Motor puro: dataclasses de entrada/salida, tolerancia, permisos, banco anual. Cero imports de SQLAlchemy. |
| `app/database/asistencia.py` | **Crear.** DDL idempotente de `JornadaDiaria` y `AsistenciaConfig`, columna `Permission.oficial`, y CRUD. |
| `app/services/asistencia_recalc.py` | **Crear.** Orquestación: carga insumos en bloque, invoca el motor, reemplaza filas. |
| `app/routes/asistencia.py` | **Crear.** Router con los 7 endpoints. |
| `app/scheduler.py` | **Modificar.** Agregar job nocturno de recálculo. |
| `app/main.py` | **Modificar.** `ensure_tables` de asistencia en startup + registrar router. |
| `app/routes/employee.py` | **Modificar.** Disparar `recalcular_historia` al cambiar `biometricoId`. |
| `app/routes/rrhh.py` | **Modificar.** Guardar `Permission.oficial` y disparar recálculo al crear un permiso. |
| `app/routes/licenses.py` | **Modificar.** Disparar recálculo al aprobar o rechazar una licencia. |
| `tests/test_asistencia_calc.py` | **Crear.** Tests del motor puro. |
| `src/app/Interfas/Interfaces.ts` | **Modificar.** Tipos de asistencia + `Page`. |
| `src/app/util/rbac.ts` | **Modificar.** Entrada de navegación. |
| `src/app/page.tsx` | **Modificar.** Ramificación por rol. |
| `src/app/screens/Asistencia/Screen.tsx` | **Crear.** Ramificación por rol. |
| `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` | **Crear.** Tablero RRHH + modal de corrección. |
| `src/app/Componentes/Asistencia/MiAsistencia.tsx` | **Crear.** Vista del empleado. |
| `src/app/Componentes/ModalRRHH/LicenseModal.tsx` | **Modificar.** Checkbox "Oficial" en el alta de permisos. |

El motor puro se aísla deliberadamente de la base de datos: es donde vive toda la lógica difícil (tolerancia, banco de permisos) y así se testea con `pytest` sin fixtures, sin SQL Server y sin relojes.

---

## Task 1: Motor de cálculo puro

**Files:**
- Create: `app/services/asistencia_calc.py`
- Test: `tests/test_asistencia_calc.py`

**Interfaces:**
- Consumes: nada. Es la base del módulo.
- Produces:
  - `BANCO_PERMISO_ANUAL_HORAS: float = 12.0`
  - `ESTADO_OK`, `ESTADO_INCOMPLETA`, `ESTADO_AUSENTE`, `ESTADO_FERIADO`, `ESTADO_LICENCIA`, `ESTADO_SIN_HORARIO` — constantes `str`
  - `@dataclass(frozen=True) HorarioDia(horaInicio: float, horaFin: float, horasTrabajo: float)`
  - `@dataclass(frozen=True) Permiso(horas: float, oficial: bool)`
  - `@dataclass(frozen=True) EntradaDia(fecha: date, marcaciones: list[datetime], horario: Optional[HorarioDia], es_feriado: bool, tiene_licencia: bool, permisos: list[Permiso], entrada_manual: Optional[datetime], salida_manual: Optional[datetime])`
  - `@dataclass(frozen=True) ResultadoDia(fecha, estado, horasRequeridas, horasTrabajadas, saldoDia, entrada, salida, permisoBanco, permisoDeuda, permisoOficial)`
  - `calcular_dia(entrada: EntradaDia, tol_entrada_min: int, tol_salida_min: int, banco_disponible: float) -> Optional[ResultadoDia]`
  - `calcular_anio(dias: list[EntradaDia], tol_entrada_min: int, tol_salida_min: int) -> list[ResultadoDia]`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_asistencia_calc.py`:

```python
from datetime import date, datetime

from app.services import asistencia_calc as c

JORNADA_8H = c.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)


def _dia(fecha=date(2026, 7, 1), marcaciones=None, horario=JORNADA_8H,
         es_feriado=False, tiene_licencia=False, permisos=None,
         entrada_manual=None, salida_manual=None):
    """Miercoles 2026-07-01 por defecto: dia habil."""
    return c.EntradaDia(
        fecha=fecha,
        marcaciones=marcaciones if marcaciones is not None else [],
        horario=horario,
        es_feriado=es_feriado,
        tiene_licencia=tiene_licencia,
        permisos=permisos if permisos is not None else [],
        entrada_manual=entrada_manual,
        salida_manual=salida_manual,
    )


def _marcas(*horas):
    return [datetime(2026, 7, 1, h, m) for h, m in horas]


# ── Tolerancia ───────────────────────────────────────────────────────────────

def test_llegar_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (16, 0))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0
    assert r.estado == c.ESTADO_OK


def test_pasada_la_tolerancia_se_descuenta_todo_el_atraso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 20), (16, 0))), 15, 15, 12.0)
    assert r.horasTrabajadas == 7.0 + 40 / 60
    assert round(r.saldoDia, 4) == round(-20 / 60, 4)


def test_salir_dentro_de_la_tolerancia_no_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 50))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_las_dos_tolerancias_se_aplican_por_separado():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 10), (15, 50))), 15, 15, 12.0)
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_entrada_anticipada_y_salida_tardia_suman_a_favor():
    r = c.calcular_dia(_dia(marcaciones=_marcas((7, 50), (16, 10))), 15, 15, 12.0)
    assert round(r.horasTrabajadas, 4) == round(8.0 + 20 / 60, 4)
    assert round(r.saldoDia, 4) == round(20 / 60, 4)


def test_el_limite_exacto_de_la_tolerancia_todavia_perdona():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 15), (16, 0))), 15, 15, 12.0)
    assert r.saldoDia == 0.0


def test_un_minuto_pasada_la_tolerancia_ya_penaliza():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 16), (16, 0))), 15, 15, 12.0)
    assert round(r.saldoDia, 4) == round(-16 / 60, 4)


# ── Permisos y banco anual ───────────────────────────────────────────────────

def test_permiso_dentro_del_banco_deja_saldo_cero():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 12.0,
    )
    assert r.horasRequeridas == 6.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0
    assert r.permisoBanco == 2.0
    assert r.permisoDeuda == 0.0


def test_permiso_con_banco_agotado_genera_deuda_completa():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 0.0,
    )
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -2.0
    assert r.permisoBanco == 0.0
    assert r.permisoDeuda == 2.0


def test_banco_partido_al_medio_debe_solo_el_excedente():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, False)]),
        15, 15, 1.0,
    )
    assert r.horasRequeridas == 7.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == -1.0
    assert r.permisoBanco == 1.0
    assert r.permisoDeuda == 1.0


def test_permiso_oficial_es_neutro_y_no_consume_banco():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(2.0, True)]),
        15, 15, 0.0,
    )
    assert r.horasRequeridas == 6.0
    assert r.horasTrabajadas == 6.0
    assert r.saldoDia == 0.0
    assert r.permisoOficial == 2.0
    assert r.permisoBanco == 0.0
    assert r.permisoDeuda == 0.0


def test_permiso_mayor_a_la_jornada_trunca_requeridas_en_cero():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), permisos=[c.Permiso(10.0, True)]),
        15, 15, 12.0,
    )
    assert r.horasRequeridas == 0.0


def test_el_banco_se_arrastra_cronologicamente_en_el_anio():
    dias = [
        _dia(fecha=date(2026, 1, 7), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
        _dia(fecha=date(2026, 2, 4), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(8.0, False)]),
    ]
    enero, febrero = c.calcular_anio(dias, 15, 15)
    assert enero.permisoBanco == 8.0
    assert enero.permisoDeuda == 0.0
    assert enero.saldoDia == 0.0
    # Del segundo permiso solo quedan 4 h de banco: las otras 4 son deuda.
    assert febrero.permisoBanco == 4.0
    assert febrero.permisoDeuda == 4.0
    assert febrero.saldoDia == -4.0


# ── Estados especiales ───────────────────────────────────────────────────────

def test_una_sola_marcacion_queda_incompleta_sin_penalizar():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0))), 15, 15, 12.0)
    assert r.estado == c.ESTADO_INCOMPLETA
    assert r.saldoDia == 0.0
    assert r.entrada == datetime(2026, 7, 1, 8, 0)
    assert r.salida is None


def test_sin_marcaciones_en_dia_habil_es_ausente():
    r = c.calcular_dia(_dia(), 15, 15, 12.0)
    assert r.estado == c.ESTADO_AUSENTE
    assert r.horasRequeridas == 8.0
    assert r.horasTrabajadas == 0.0
    assert r.saldoDia == -8.0


def test_licencia_aprobada_neutraliza_el_dia():
    r = c.calcular_dia(_dia(tiene_licencia=True), 15, 15, 12.0)
    assert r.estado == c.ESTADO_LICENCIA
    assert r.saldoDia == 0.0


def test_sin_horario_no_genera_deuda():
    r = c.calcular_dia(_dia(horario=None), 15, 15, 12.0)
    assert r.estado == c.ESTADO_SIN_HORARIO
    assert r.saldoDia == 0.0


def test_fin_de_semana_sin_marcaciones_no_genera_fila():
    # 2026-07-04 es sabado
    assert c.calcular_dia(_dia(fecha=date(2026, 7, 4)), 15, 15, 12.0) is None


def test_feriado_sin_marcaciones_no_genera_fila():
    assert c.calcular_dia(_dia(es_feriado=True), 15, 15, 12.0) is None


def test_feriado_trabajado_suma_todo_a_favor_sin_tolerancia():
    r = c.calcular_dia(
        _dia(es_feriado=True, marcaciones=_marcas((8, 10), (16, 0))), 15, 15, 12.0,
    )
    assert r.estado == c.ESTADO_FERIADO
    assert r.horasRequeridas == 0.0
    # Sin tolerancia: cuenta el tiempo real, 8:10 a 16:00.
    assert round(r.horasTrabajadas, 4) == round(7.0 + 50 / 60, 4)
    assert round(r.saldoDia, 4) == round(7.0 + 50 / 60, 4)


# ── Carga manual de RRHH ─────────────────────────────────────────────────────

def test_la_salida_manual_completa_una_jornada_incompleta():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), salida_manual=datetime(2026, 7, 1, 16, 0)),
        15, 15, 12.0,
    )
    assert r.estado == c.ESTADO_OK
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_la_entrada_manual_pisa_la_primera_marcacion():
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)),
             entrada_manual=datetime(2026, 7, 1, 9, 0)),
        15, 15, 12.0,
    )
    assert r.entrada == datetime(2026, 7, 1, 9, 0)
    assert r.horasTrabajadas == 7.0
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_asistencia_calc.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.asistencia_calc'`

- [ ] **Step 3: Implementar el motor**

Crear `app/services/asistencia_calc.py`:

```python
"""
Motor de calculo de asistencia. Funcion pura: no toca la base de datos ni los
relojes, asi que toda la logica dificil -tolerancia y banco de permisos- se
testea sin fixtures.

La unidad de calculo es el dia. El arrastre del banco anual de permisos es
responsabilidad de calcular_anio, que recorre los dias en orden cronologico.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

BANCO_PERMISO_ANUAL_HORAS = 12.0

# weekday(): lunes=0 ... domingo=6
DIAS_HABILES = frozenset({0, 1, 2, 3, 4})

ESTADO_OK = "ok"
ESTADO_INCOMPLETA = "incompleta"
ESTADO_AUSENTE = "ausente"
ESTADO_FERIADO = "feriado"
ESTADO_LICENCIA = "licencia"
ESTADO_SIN_HORARIO = "sin_horario"


@dataclass(frozen=True)
class HorarioDia:
    """horaInicio y horaFin son decimales: 8.5 es las 08:30."""
    horaInicio: float
    horaFin: float
    horasTrabajo: float


@dataclass(frozen=True)
class Permiso:
    horas: float
    oficial: bool


@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    marcaciones: list[datetime]
    horario: Optional[HorarioDia]
    es_feriado: bool
    tiene_licencia: bool
    permisos: list[Permiso]
    entrada_manual: Optional[datetime]
    salida_manual: Optional[datetime]


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


def _hora_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _extremos(e: EntradaDia) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Primera marcacion = entrada, ultima = salida (todos marcan en el mismo
    reloj). La carga manual de RRHH tiene prioridad sobre el dispositivo.
    """
    ordenadas = sorted(e.marcaciones)
    entrada = e.entrada_manual or (ordenadas[0] if ordenadas else None)
    salida = e.salida_manual
    if salida is None and len(ordenadas) >= 2:
        salida = ordenadas[-1]
    return entrada, salida


def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol_entrada_min: int, tol_salida_min: int) -> float:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol_entrada_min / 60
    tol_sal = tol_salida_min / 60

    if horario.horaInicio < ent <= horario.horaInicio + tol_ent:
        ent = horario.horaInicio
    if horario.horaFin - tol_sal <= sal < horario.horaFin:
        sal = horario.horaFin

    return sal - ent


def _sumar_permisos(permisos: list[Permiso]) -> tuple[float, float]:
    regular = sum(p.horas for p in permisos if not p.oficial)
    oficial = sum(p.horas for p in permisos if p.oficial)
    return regular, oficial


def calcular_dia(entrada_dia: EntradaDia, tol_entrada_min: int,
                 tol_salida_min: int,
                 banco_disponible: float) -> Optional[ResultadoDia]:
    """
    Devuelve la fila del dia, o None cuando no corresponde generar ninguna
    (fin de semana o feriado sin marcaciones).
    """
    e = entrada_dia
    entrada, salida = _extremos(e)
    hay_marcas = entrada is not None
    no_laborable = e.es_feriado or e.fecha.weekday() not in DIAS_HABILES

    # Dia no laborable: sin marcaciones no existe la fila; con marcaciones todo
    # lo trabajado es saldo a favor y no se aplica tolerancia, porque el
    # horario no rige un dia que no se debia trabajar.
    if no_laborable:
        if not hay_marcas or salida is None:
            return None
        trabajadas = _hora_decimal(salida) - _hora_decimal(entrada)
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_FERIADO,
            horasRequeridas=0.0, horasTrabajadas=trabajadas, saldoDia=trabajadas,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if e.tiene_licencia:
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_LICENCIA,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if e.horario is None:
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_SIN_HORARIO,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=salida,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    permiso_regular, permiso_oficial = _sumar_permisos(e.permisos)
    permiso_banco = min(permiso_regular, max(banco_disponible, 0.0))
    permiso_deuda = permiso_regular - permiso_banco

    if not hay_marcas:
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_AUSENTE,
            horasRequeridas=e.horario.horasTrabajo, horasTrabajadas=0.0,
            saldoDia=-e.horario.horasTrabajo,
            entrada=None, salida=None,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    if salida is None:
        # Marco un solo extremo. No se penaliza hasta que RRHH cargue el otro:
        # aparece en el tablero de incompletas con saldo neutro.
        return ResultadoDia(
            fecha=e.fecha, estado=ESTADO_INCOMPLETA,
            horasRequeridas=0.0, horasTrabajadas=0.0, saldoDia=0.0,
            entrada=entrada, salida=None,
            permisoBanco=0.0, permisoDeuda=0.0, permisoOficial=0.0,
        )

    brutas = _ajustar_por_tolerancia(
        entrada, salida, e.horario, tol_entrada_min, tol_salida_min,
    )
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return ResultadoDia(
        fecha=e.fecha, estado=ESTADO_OK,
        horasRequeridas=requeridas, horasTrabajadas=trabajadas,
        saldoDia=trabajadas - requeridas,
        entrada=entrada, salida=salida,
        permisoBanco=permiso_banco, permisoDeuda=permiso_deuda,
        permisoOficial=permiso_oficial,
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

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_asistencia_calc.py -v`
Expected: PASS, 21 tests.

- [ ] **Step 5: Correr la suite completa para verificar que no se rompió nada**

Run: `python -m pytest tests/ -v`
Expected: PASS, los 16 tests previos más los 21 nuevos.

- [ ] **Step 6: Commit**

```bash
git add app/services/asistencia_calc.py tests/test_asistencia_calc.py
git commit -m "feat: motor puro de calculo de asistencia con tolerancia y banco de permisos"
```

---

## Task 2: Tablas y configuración

**Files:**
- Create: `app/database/asistencia.py`

**Interfaces:**
- Consumes: nada de Task 1 (esta capa no importa el motor).
- Produces:
  - `ensure_tables(db: Session) -> None`
  - `get_config(db: Session) -> dict` — claves `toleranciaEntradaMin`, `toleranciaSalidaMin`, `fechaInicioModulo`
  - `update_config(db: Session, tol_entrada: int, tol_salida: int) -> dict`
  - `reemplazar_jornadas(db: Session, employee_id: int, desde: date, hasta: date, filas: list[dict]) -> int`
  - `saldo_acumulado(db: Session, employee_id: int) -> float`
  - `jornadas_de(db: Session, employee_id: int, desde: date, hasta: date) -> list[dict]`
  - `jornadas_incompletas(db: Session) -> list[dict]`
  - `tablero(db: Session, desde: date, hasta: date) -> list[dict]`
  - `get_jornada(db: Session, jornada_id: int) -> Optional[dict]`
  - `marcar_correccion(db: Session, jornada_id: int, entrada: Optional[datetime], salida: Optional[datetime], corregido_por: int, observacion: Optional[str]) -> None`

Las filas de `reemplazar_jornadas` usan exactamente las claves de las columnas de `JornadaDiaria`.

- [ ] **Step 1: Escribir el módulo de base de datos**

Crear `app/database/asistencia.py`:

```python
"""
Persistencia del modulo de asistencia: JornadaDiaria (una fila por empleado por
dia) y AsistenciaConfig (fila unica con las tolerancias).

JornadaDiaria es derivada: se puede borrar entera y regenerarla desde Marcacion
mas los datos de horario, licencias y permisos. Por eso el recalculo reemplaza
el rango en lugar de intentar actualizar fila por fila.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_JORNADA_SQL = """
IF OBJECT_ID('JornadaDiaria', 'U') IS NULL
CREATE TABLE JornadaDiaria (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    employeeId      INT           NOT NULL,
    fecha           DATE          NOT NULL,
    estado          NVARCHAR(20)  NOT NULL,
    horasRequeridas DECIMAL(5,2)  NOT NULL,
    horasTrabajadas DECIMAL(5,2)  NOT NULL,
    saldoDia        DECIMAL(5,2)  NOT NULL,
    entrada         DATETIME2     NULL,
    salida          DATETIME2     NULL,
    entradaManual   BIT           NOT NULL DEFAULT 0,
    salidaManual    BIT           NOT NULL DEFAULT 0,
    permisoBanco    DECIMAL(5,2)  NOT NULL DEFAULT 0,
    permisoDeuda    DECIMAL(5,2)  NOT NULL DEFAULT 0,
    permisoOficial  DECIMAL(5,2)  NOT NULL DEFAULT 0,
    corregidoPor    INT           NULL,
    corregidoAt     DATETIME2     NULL,
    observacion     NVARCHAR(500) NULL,
    calculadoAt     DATETIME2     NOT NULL,
    CONSTRAINT UQ_JornadaDiaria UNIQUE (employeeId, fecha)
);
"""

CREATE_INDEX_ESTADO_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_JornadaDiaria_estado')
CREATE INDEX IX_JornadaDiaria_estado ON JornadaDiaria (estado, fecha);
"""

CREATE_CONFIG_SQL = """
IF OBJECT_ID('AsistenciaConfig', 'U') IS NULL
CREATE TABLE AsistenciaConfig (
    id                   INT       PRIMARY KEY,
    toleranciaEntradaMin INT       NOT NULL DEFAULT 15,
    toleranciaSalidaMin  INT       NOT NULL DEFAULT 15,
    fechaInicioModulo    DATE      NOT NULL,
    updatedAt            DATETIME2 NOT NULL
);
"""

ALTER_PERMISSION_OFICIAL_SQL = """
IF COL_LENGTH('Permission','oficial') IS NULL
ALTER TABLE Permission ADD oficial BIT NOT NULL DEFAULT 0;
"""

# La fecha de arranque por defecto es la marcacion mas antigua registrada: antes
# de esa fecha no existe informacion de reloj y calcular ausencias seria inventar.
SEED_CONFIG_SQL = """
IF NOT EXISTS (SELECT 1 FROM AsistenciaConfig WHERE id = 1)
INSERT INTO AsistenciaConfig (id, toleranciaEntradaMin, toleranciaSalidaMin,
                              fechaInicioModulo, updatedAt)
VALUES (1, 15, 15,
        COALESCE((SELECT CAST(MIN(fechaHora) AS DATE) FROM Marcacion), CAST(GETDATE() AS DATE)),
        GETDATE());
"""


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
    db.execute(text(SEED_CONFIG_SQL))
    db.commit()


def get_config(db: Session) -> dict:
    fila = db.execute(text("""
        SELECT toleranciaEntradaMin, toleranciaSalidaMin, fechaInicioModulo
        FROM AsistenciaConfig WHERE id = 1
    """)).mappings().first()
    if fila is None:
        return {"toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
                "fechaInicioModulo": date.today()}
    return dict(fila)


def update_config(db: Session, tol_entrada: int, tol_salida: int) -> dict:
    db.execute(text("""
        UPDATE AsistenciaConfig
        SET toleranciaEntradaMin = :te, toleranciaSalidaMin = :ts, updatedAt = GETDATE()
        WHERE id = 1
    """), {"te": int(tol_entrada), "ts": int(tol_salida)})
    db.commit()
    return get_config(db)


def reemplazar_jornadas(db: Session, employee_id: int, desde: date, hasta: date,
                        filas: list[dict]) -> int:
    """
    Borra el rango del empleado y reinserta. JornadaDiaria es derivada, asi que
    reemplazar es mas simple y mas seguro que reconciliar fila por fila: no deja
    huerfanas cuando un dia deja de corresponder (por ejemplo al cargarse una
    licencia que lo cubre).
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
                 corregidoPor, corregidoAt, observacion, calculadoAt)
            VALUES
                (:employeeId, :fecha, :estado, :horasRequeridas, :horasTrabajadas,
                 :saldoDia, :entrada, :salida, :entradaManual, :salidaManual,
                 :permisoBanco, :permisoDeuda, :permisoOficial,
                 :corregidoPor, :corregidoAt, :observacion, :calculadoAt)
        """), {**f, "employeeId": employee_id, "calculadoAt": ahora})

    db.commit()
    return len(filas)


def saldo_acumulado(db: Session, employee_id: int) -> float:
    fila = db.execute(text(
        "SELECT COALESCE(SUM(saldoDia), 0) AS s FROM JornadaDiaria WHERE employeeId = :emp"
    ), {"emp": employee_id}).mappings().first()
    return float(fila["s"]) if fila else 0.0


def jornadas_de(db: Session, employee_id: int, desde: date, hasta: date) -> list[dict]:
    filas = db.execute(text("""
        SELECT id, fecha, estado, horasRequeridas, horasTrabajadas, saldoDia,
               entrada, salida, entradaManual, salidaManual,
               permisoBanco, permisoDeuda, permisoOficial, observacion
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
        ORDER BY fecha DESC
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def jornadas_incompletas(db: Session) -> list[dict]:
    """Jornadas que esperan intervencion de RRHH."""
    filas = db.execute(text("""
        SELECT j.id, j.employeeId, e.name AS employeeName, j.fecha, j.estado,
               j.entrada, j.salida
        FROM JornadaDiaria j
        INNER JOIN Employee e ON e.id = j.employeeId
        WHERE j.estado IN ('incompleta', 'sin_horario')
        ORDER BY j.fecha DESC, e.name ASC
    """)).mappings().all()
    return [dict(f) for f in filas]


def tablero(db: Session, desde: date, hasta: date) -> list[dict]:
    """
    Una fila por empleado vinculado a un reloj. El saldo es historico completo;
    ausencias e incompletas se cuentan solo dentro del rango consultado.
    """
    filas = db.execute(text("""
        SELECT
            e.id                AS employeeId,
            e.name              AS employeeName,
            e.biometricoId,
            COALESCE(hist.saldo, 0)        AS saldoAcumulado,
            COALESCE(rango.ausencias, 0)   AS ausencias,
            COALESCE(rango.incompletas, 0) AS incompletas
        FROM Employee e
        LEFT JOIN (
            SELECT employeeId, SUM(saldoDia) AS saldo
            FROM JornadaDiaria GROUP BY employeeId
        ) hist ON hist.employeeId = e.id
        LEFT JOIN (
            SELECT employeeId,
                   SUM(CASE WHEN estado = 'ausente'    THEN 1 ELSE 0 END) AS ausencias,
                   SUM(CASE WHEN estado = 'incompleta' THEN 1 ELSE 0 END) AS incompletas
            FROM JornadaDiaria
            WHERE fecha >= :desde AND fecha <= :hasta
            GROUP BY employeeId
        ) rango ON rango.employeeId = e.id
        WHERE e.biometricoId IS NOT NULL
        ORDER BY e.name ASC
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def get_jornada(db: Session, jornada_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT id, employeeId, fecha, estado, entrada, salida
        FROM JornadaDiaria WHERE id = :id
    """), {"id": jornada_id}).mappings().first()
    return dict(fila) if fila else None


def marcar_correccion(db: Session, jornada_id: int,
                      entrada: Optional[datetime], salida: Optional[datetime],
                      corregido_por: int, observacion: Optional[str]) -> None:
    """
    Persiste la carga manual. Los flags entradaManual y salidaManual son la
    fuente de verdad para el recalculo: sin ellos, la proxima corrida
    sobrescribiria la correccion con lo que dice el reloj.
    """
    db.execute(text("""
        UPDATE JornadaDiaria
        SET entrada       = COALESCE(:entrada, entrada),
            salida        = COALESCE(:salida, salida),
            entradaManual = CASE WHEN :entrada IS NOT NULL THEN 1 ELSE entradaManual END,
            salidaManual  = CASE WHEN :salida  IS NOT NULL THEN 1 ELSE salidaManual  END,
            corregidoPor  = :por,
            corregidoAt   = GETDATE(),
            observacion   = :obs
        WHERE id = :id
    """), {"entrada": entrada, "salida": salida, "por": corregido_por,
           "obs": (observacion or None), "id": jornada_id})
    db.commit()
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `python -c "import app.database.asistencia; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verificar que la suite sigue verde**

Run: `python -m pytest tests/ -v`
Expected: PASS, 37 tests.

- [ ] **Step 4: Commit**

```bash
git add app/database/asistencia.py
git commit -m "feat: tablas JornadaDiaria y AsistenciaConfig + columna Permission.oficial"
```

---

## Task 3: Orquestación del recálculo

**Files:**
- Create: `app/services/asistencia_recalc.py`

**Interfaces:**
- Consumes de Task 1: `asistencia_calc.EntradaDia`, `HorarioDia`, `Permiso`, `ResultadoDia`, `calcular_anio`.
- Consumes de Task 2: `asistencia.get_config`, `asistencia.reemplazar_jornadas`.
- Produces:
  - `recalcular_anio(db: Session, employee_id: int, anio: int) -> int` — devuelve filas escritas
  - `recalcular_historia(db: Session, employee_id: int) -> int`
  - `recalcular_todos(db: Session, anio: int) -> dict` — `{"empleados": int, "filas": int}`

- [ ] **Step 1: Implementar la orquestación**

Crear `app/services/asistencia_recalc.py`:

```python
"""
Orquestacion del recalculo: carga los insumos en bloque, delega el calculo al
motor puro y reemplaza las filas del rango.

La unidad de recalculo es (empleado, anio) y siempre se recomputa desde el 1 de
enero, porque el banco de permisos se consume en orden cronologico. Hay un solo
camino de codigo: no existe una variante incremental que pueda desviarse del
calculo completo.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.asistencia import get_config, reemplazar_jornadas
from app.services.asistencia_calc import (
    EntradaDia, HorarioDia, Permiso, ResultadoDia, calcular_anio,
)

log = logging.getLogger(__name__)


def _rango_dias(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def _datos_empleado(db: Session, employee_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT e.id, e.biometricoId,
               h.horaInicio, h.horaFin, h.horasTrabajo,
               c.fechaIngreso
        FROM Employee e
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None


def _marcaciones_por_dia(db: Session, biometrico_id: str,
                         desde: date, hasta: date) -> dict[date, list[datetime]]:
    filas = db.execute(text("""
        SELECT fechaHora FROM Marcacion
        WHERE biometricoId = :bio AND fechaHora >= :desde AND fechaHora < :hasta
        ORDER BY fechaHora
    """), {"bio": str(biometrico_id), "desde": datetime.combine(desde, datetime.min.time()),
           "hasta": datetime.combine(hasta + timedelta(days=1), datetime.min.time())}
    ).mappings().all()
    por_dia: dict[date, list[datetime]] = {}
    for f in filas:
        por_dia.setdefault(f["fechaHora"].date(), []).append(f["fechaHora"])
    return por_dia


def _feriados(db: Session, desde: date, hasta: date) -> set[date]:
    filas = db.execute(text("""
        SELECT fecha FROM Feriado
        WHERE activo = 1 AND fecha >= :desde AND fecha <= :hasta
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return {f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
            for f in filas}


def _dias_con_licencia(db: Session, employee_id: int,
                       desde: date, hasta: date) -> set[date]:
    filas = db.execute(text("""
        SELECT startDate, endDate FROM License
        WHERE employeeId = :emp AND status = 'Aprobada'
          AND startDate <= :hasta AND endDate >= :desde
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    dias: set[date] = set()
    for f in filas:
        ini = f["startDate"] if isinstance(f["startDate"], date) else f["startDate"].date()
        fin = f["endDate"] if isinstance(f["endDate"], date) else f["endDate"].date()
        for d in _rango_dias(max(ini, desde), min(fin, hasta)):
            dias.add(d)
    return dias


def _permisos_por_dia(db: Session, employee_id: int,
                      desde: date, hasta: date) -> dict[date, list[Permiso]]:
    filas = db.execute(text("""
        SELECT date, hours, oficial FROM Permission
        WHERE employeeId = :emp AND date >= :desde AND date <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    por_dia: dict[date, list[Permiso]] = {}
    for f in filas:
        d = f["date"] if isinstance(f["date"], date) else f["date"].date()
        por_dia.setdefault(d, []).append(
            Permiso(horas=float(f["hours"] or 0), oficial=bool(f["oficial"]))
        )
    return por_dia


def _correcciones_por_dia(db: Session, employee_id: int, desde: date,
                          hasta: date) -> dict[date, dict]:
    """
    Las cargas manuales de RRHH sobreviven al recalculo: se releen de la propia
    JornadaDiaria antes de borrar el rango y se reinyectan al motor.
    """
    filas = db.execute(text("""
        SELECT fecha, entrada, salida, entradaManual, salidaManual,
               corregidoPor, corregidoAt, observacion
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
          AND (entradaManual = 1 OR salidaManual = 1)
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    out: dict[date, dict] = {}
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        out[d] = dict(f)
    return out


def _a_fila(r: ResultadoDia, correccion: Optional[dict]) -> dict:
    c = correccion or {}
    return {
        "fecha": r.fecha,
        "estado": r.estado,
        "horasRequeridas": round(r.horasRequeridas, 2),
        "horasTrabajadas": round(r.horasTrabajadas, 2),
        "saldoDia": round(r.saldoDia, 2),
        "entrada": r.entrada,
        "salida": r.salida,
        "entradaManual": bool(c.get("entradaManual", False)),
        "salidaManual": bool(c.get("salidaManual", False)),
        "permisoBanco": round(r.permisoBanco, 2),
        "permisoDeuda": round(r.permisoDeuda, 2),
        "permisoOficial": round(r.permisoOficial, 2),
        "corregidoPor": c.get("corregidoPor"),
        "corregidoAt": c.get("corregidoAt"),
        "observacion": c.get("observacion"),
    }


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

    correcciones = _correcciones_por_dia(db, employee_id, desde, hasta)
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
        c = correcciones.get(d, {})
        entradas.append(EntradaDia(
            fecha=d,
            marcaciones=marcaciones.get(d, []),
            horario=horario,
            es_feriado=d in feriados,
            tiene_licencia=d in licencias,
            permisos=permisos.get(d, []),
            entrada_manual=c.get("entrada") if c.get("entradaManual") else None,
            salida_manual=c.get("salida") if c.get("salidaManual") else None,
        ))

    resultados = calcular_anio(
        entradas, cfg["toleranciaEntradaMin"], cfg["toleranciaSalidaMin"],
    )
    filas = [_a_fila(r, correcciones.get(r.fecha)) for r in resultados]
    return reemplazar_jornadas(db, employee_id, desde, hasta, filas)


def recalcular_historia(db: Session, employee_id: int) -> int:
    """
    Recomputa todos los anios desde el arranque del modulo. Es lo que se dispara
    al asignar un biometricoId: las marcaciones huerfanas que ya estaban
    guardadas aparecen retroactivamente sin resincronizar los relojes.
    """
    cfg = get_config(db)
    inicio = cfg["fechaInicioModulo"]
    if not isinstance(inicio, date):
        inicio = inicio.date()
    total = 0
    for anio in range(inicio.year, date.today().year + 1):
        total += recalcular_anio(db, employee_id, anio)
    return total


def recalcular_todos(db: Session, anio: int) -> dict:
    """
    Recalculo masivo del job nocturno. Un empleado que falla no debe abortar el
    resto: se registra y se sigue.
    """
    ids = [r["id"] for r in db.execute(text(
        "SELECT id FROM Employee WHERE biometricoId IS NOT NULL ORDER BY id"
    )).mappings().all()]

    filas = 0
    ok = 0
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo fallido para empleado %s: %s", eid, e)
    return {"empleados": ok, "filas": filas}
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `python -c "import app.services.asistencia_recalc; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verificar que la suite sigue verde**

Run: `python -m pytest tests/ -v`
Expected: PASS, 37 tests.

- [ ] **Step 4: Commit**

```bash
git add app/services/asistencia_recalc.py
git commit -m "feat: orquestacion del recalculo de asistencia por (empleado, anio)"
```

---

## Task 4: Endpoints

**Files:**
- Create: `app/routes/asistencia.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes de Task 2: todas las funciones de `app.database.asistencia`.
- Consumes de Task 3: `recalcular_anio`.
- Produces: `router` montado sin prefijo propio en las rutas (usa `prefix="/asistencia"` en el `APIRouter`).

- [ ] **Step 1: Escribir el router**

Crear `app/routes/asistencia.py`:

```python
"""
Router del modulo de asistencia.

GET /asistencia/mi resuelve el empleado desde el token y nunca acepta un
employeeId por parametro: un usuario sin rol de RRHH no puede ver datos ajenos.
"""

from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, get_current_user, require_any_auth, require_roles,
)
from app.database.asistencia import (
    ensure_tables, get_config, get_jornada, jornadas_de, jornadas_incompletas,
    marcar_correccion, saldo_acumulado, tablero, update_config,
)
from app.database.database import SessionLocal
from app.routes.rrhh import ROLE_RRHH
from app.services.asistencia_recalc import recalcular_anio

router = APIRouter(prefix="/asistencia", tags=["Asistencia"])

SOLO_RRHH = Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _rango(desde: str | None, hasta: str | None) -> tuple[date, date]:
    """Sin parametros devuelve el anio en curso."""
    hoy = date.today()
    d = date.fromisoformat(desde) if desde else date(hoy.year, 1, 1)
    h = date.fromisoformat(hasta) if hasta else hoy
    if d > h:
        raise HTTPException(status_code=400, detail="'desde' no puede ser posterior a 'hasta'")
    return d, h


@router.get("/tablero", dependencies=[SOLO_RRHH])
def get_tablero(desde: str | None = None, hasta: str | None = None,
                db: Session = Depends(get_db)):
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {"desde": d.isoformat(), "hasta": h.isoformat(), "empleados": tablero(db, d, h)}


@router.get("/incompletas", dependencies=[SOLO_RRHH])
def get_incompletas(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"jornadas": jornadas_incompletas(db)}


@router.put("/jornada/{jornada_id}", dependencies=[SOLO_RRHH])
def put_jornada(jornada_id: int, data: dict = Body(...),
                usuario: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """
    Carga manual de entrada y/o salida. Dispara el recalculo del anio para que
    el saldo del empleado quede al dia sin esperar al job nocturno.
    """
    jornada = get_jornada(db, jornada_id)
    if jornada is None:
        raise HTTPException(status_code=404, detail="Jornada no encontrada")

    def _parsear(clave: str):
        crudo = data.get(clave)
        if crudo in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(crudo))
        except ValueError:
            raise HTTPException(status_code=400,
                                detail=f"'{clave}' debe ser una fecha-hora ISO valida")

    entrada = _parsear("entrada")
    salida = _parsear("salida")
    if entrada is None and salida is None:
        raise HTTPException(status_code=400,
                            detail="Hay que enviar al menos 'entrada' o 'salida'")
    if entrada is not None and salida is not None and salida <= entrada:
        raise HTTPException(status_code=400,
                            detail="La salida debe ser posterior a la entrada")

    marcar_correccion(db, jornada_id, entrada, salida,
                      int(usuario["employeeId"]), data.get("observacion"))

    fecha = jornada["fecha"]
    anio = fecha.year if isinstance(fecha, date) else fecha.date().year
    recalcular_anio(db, jornada["employeeId"], anio)

    return {"ok": True, "employeeId": jornada["employeeId"], "anio": anio}


@router.get("/empleado/{employee_id}", dependencies=[SOLO_RRHH])
def get_empleado(employee_id: int, desde: str | None = None,
                 hasta: str | None = None, db: Session = Depends(get_db)):
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    return {
        "employeeId": employee_id,
        "saldoAcumulado": saldo_acumulado(db, employee_id),
        "jornadas": jornadas_de(db, employee_id, d, h),
    }


@router.get("/mi", dependencies=[Depends(require_any_auth)])
def get_mi_asistencia(desde: str | None = None, hasta: str | None = None,
                      usuario: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """
    El empleado solo ve lo propio: el id sale del token, no del request.
    get_current_user devuelve {usuario, roleId, employeeId}; employeeId puede
    ser None si la cuenta no esta vinculada a un legajo.
    """
    ensure_tables(db)
    if usuario.get("employeeId") is None:
        raise HTTPException(status_code=404,
                            detail="Tu usuario no esta vinculado a un legajo")
    fila = db.execute(text(
        "SELECT id FROM Employee WHERE id = :id"
    ), {"id": usuario["employeeId"]}).mappings().first()
    if fila is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    d, h = _rango(desde, hasta)
    employee_id = int(fila["id"])
    return {
        "saldoAcumulado": saldo_acumulado(db, employee_id),
        "jornadas": jornadas_de(db, employee_id, d, h),
    }


@router.get("/config", dependencies=[SOLO_RRHH])
def get_asistencia_config(db: Session = Depends(get_db)):
    ensure_tables(db)
    return get_config(db)


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
    return update_config(db, tol_entrada, tol_salida)
```

- [ ] **Step 2: Registrar el router y las tablas en el arranque**

En `app/main.py`, agregar `asistencia` a la lista de imports de routers (línea 5) y estas dos líneas:

```python
from app.database.asistencia import ensure_tables as ensure_tablas_asistencia
```

Dentro de `startup()`, después de `ensure_columna_biometrico(db)`:

```python
        ensure_tablas_asistencia(db)
        print("[OK] tablas de asistencia verificadas")
```

Y junto a los demás `include_router`:

```python
app.include_router(asistencia.router)
```

- [ ] **Step 3: Verificar que la app importa sin errores**

Run: `python -c "from app.main import app; print(len(app.routes), 'rutas')"`
Expected: imprime el total de rutas sin lanzar excepción.

- [ ] **Step 4: Verificar que las 7 rutas quedaron registradas**

Run: `python -c "from app.main import app; print(sorted({r.path for r in app.routes if '/asistencia' in r.path}))"`
Expected: `['/asistencia/config', '/asistencia/empleado/{employee_id}', '/asistencia/incompletas', '/asistencia/jornada/{jornada_id}', '/asistencia/mi', '/asistencia/tablero']`

- [ ] **Step 5: Commit**

```bash
git add app/routes/asistencia.py app/main.py
git commit -m "feat: endpoints de asistencia y registro en el arranque"
```

---

## Task 5: Job nocturno y disparador de biometricoId

**Files:**
- Modify: `app/scheduler.py`
- Modify: `app/routes/employee.py`

**Interfaces:**
- Consumes de Task 3: `recalcular_todos`, `recalcular_historia`.
- Produces: nada que consuman tareas posteriores.

- [ ] **Step 1: Agregar el job nocturno**

En `app/scheduler.py`, agregar el import junto a los existentes:

```python
from app.services.asistencia_recalc import recalcular_todos
```

Agregar la constante junto a `INTERVALO_MINUTOS`:

```python
HORA_RECALCULO_ASISTENCIA = 3  # 3 AM, fuera del horario de uso
```

Agregar la función después de `_tick`:

```python
def _tick_asistencia():
    """
    Recalculo nocturno del anio en curso. Recomputa todo el anio en lugar de
    solo ayer: cuesta unos minutos a las 3 AM y a cambio se auto-repara,
    corrigiendo cualquier inconsistencia que haya dejado un disparador fallido.
    """
    db = SessionLocal()
    try:
        from datetime import date
        resultado = recalcular_todos(db, date.today().year)
        log.info("Recalculo de asistencia: %s empleados, %s jornadas",
                 resultado["empleados"], resultado["filas"])
    except Exception as e:
        log.exception("Fallo inesperado en el recalculo de asistencia: %s", e)
    finally:
        db.close()
```

Dentro de `iniciar_scheduler()`, después del `add_job` existente y antes de `_scheduler.start()`:

```python
    _scheduler.add_job(
        _tick_asistencia,
        "cron",
        hour=HORA_RECALCULO_ASISTENCIA,
        minute=0,
        id="recalculo_asistencia",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
```

Y actualizar el log final:

```python
    log.info("Scheduler iniciado: sync cada %s min, recalculo de asistencia a las %s:00",
             INTERVALO_MINUTOS, HORA_RECALCULO_ASISTENCIA)
```

- [ ] **Step 2: Disparar el recálculo al cambiar el biometricoId**

En `app/routes/employee.py`, en el bloque `if "biometricoId" in data:` del PUT, justo después del `db.execute` del UPDATE, capturar si hubo cambio. Reemplazar:

```python
            db.execute(text("UPDATE Employee SET biometricoId = :bio WHERE id = :id"),
                       {"bio": nuevo, "id": employee_id})
```

por:

```python
            db.execute(text("UPDATE Employee SET biometricoId = :bio WHERE id = :id"),
                       {"bio": nuevo, "id": employee_id})
            # Las marcaciones huerfanas ya guardadas pasan a tener dueno: hay que
            # recalcular toda su historia para que el saldo aparezca completo.
            recalcular_biometrico = True
```

Inicializar la bandera antes del `if` (dentro del `try`, antes del bloque de `biometricoId`):

```python
        recalcular_biometrico = False
```

Y después del `db.commit()` exitoso, antes del `return`:

```python
        if recalcular_biometrico:
            try:
                recalcular_historia(db, employee_id)
            except Exception as e:
                # El vinculo ya quedo guardado. Si el recalculo falla, el job
                # nocturno lo corrige: no se revierte el PUT por esto.
                print(f"[WARN] recalculo de asistencia fallido para {employee_id}: {e}")
```

Agregar el import arriba del archivo:

```python
from app.services.asistencia_recalc import recalcular_historia
```

- [ ] **Step 3: Verificar que ambos módulos importan sin errores**

Run: `python -c "import app.scheduler, app.routes.employee; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Verificar que el job quedó registrado**

Run: `python -c "import app.scheduler as s; print(s.HORA_RECALCULO_ASISTENCIA, callable(s._tick_asistencia))"`
Expected: `3 True`

- [ ] **Step 5: Verificar que la suite sigue verde**

Run: `python -m pytest tests/ -v`
Expected: PASS, 37 tests.

- [ ] **Step 6: Commit**

```bash
git add app/scheduler.py app/routes/employee.py
git commit -m "feat: job nocturno de recalculo y disparador al asignar biometricoId"
```

---

## Task 6: Frontend — tablero de RRHH

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts`
- Create: `src/app/Componentes/Asistencia/AsistenciaTablero.tsx`

Rutas relativas a `C:\Users\Emiliano\Documents\RRHH`.

**Interfaces:**
- Consumes de Task 4: `GET /asistencia/tablero`, `GET /asistencia/incompletas`, `PUT /asistencia/jornada/{id}`.
- Produces: `AsistenciaTablero` (default export), y los tipos `JornadaDiaria`, `TableroFila`, `JornadaIncompleta` exportados desde `Interfaces.ts`.

- [ ] **Step 1: Agregar los tipos**

En `src/app/Interfas/Interfaces.ts`, al final del archivo:

```typescript
export interface JornadaDiaria {
  id: number;
  fecha: string;
  estado: 'ok' | 'incompleta' | 'ausente' | 'feriado' | 'licencia' | 'sin_horario';
  horasRequeridas: number;
  horasTrabajadas: number;
  saldoDia: number;
  entrada: string | null;
  salida: string | null;
  entradaManual: boolean;
  salidaManual: boolean;
  permisoBanco: number;
  permisoDeuda: number;
  permisoOficial: number;
  observacion: string | null;
}

export interface TableroFila {
  employeeId: number;
  employeeName: string;
  biometricoId: string;
  saldoAcumulado: number;
  ausencias: number;
  incompletas: number;
}

export interface JornadaIncompleta {
  id: number;
  employeeId: number;
  employeeName: string;
  fecha: string;
  estado: string;
  entrada: string | null;
  salida: string | null;
}
```

Y agregar `"asistencia"` al type `Page` (línea 677):

```typescript
export type Page =
  | "estadisticas"
  | "asistencia"
  | "recursos-humanos"
```

- [ ] **Step 2: Crear el tablero**

Crear `src/app/Componentes/Asistencia/AsistenciaTablero.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Toast } from "primereact/toast";
import { apiClient } from "@/app/util/apiClient";
import { JornadaIncompleta, TableroFila } from "@/app/Interfas/Interfaces";

const fmtHoras = (h: number) => {
  const signo = h < 0 ? "-" : h > 0 ? "+" : "";
  const abs = Math.abs(h);
  const horas = Math.floor(abs);
  const min = Math.round((abs - horas) * 60);
  return `${signo}${horas}h ${String(min).padStart(2, "0")}m`;
};

const claseSaldo = (h: number) =>
  h < 0 ? "text-error font-semibold" : h > 0 ? "text-success font-semibold" : "text-muted-foreground";

export default function AsistenciaTablero() {
  const [filas, setFilas] = useState<TableroFila[]>([]);
  const [incompletas, setIncompletas] = useState<JornadaIncompleta[]>([]);
  const [cargando, setCargando] = useState(true);
  const [editando, setEditando] = useState<JornadaIncompleta | null>(null);
  const [horaSalida, setHoraSalida] = useState("");
  const [observacion, setObservacion] = useState("");
  const [guardando, setGuardando] = useState(false);
  const toast = useRef<Toast>(null);

  const cargar = async () => {
    setCargando(true);
    try {
      const [t, i] = await Promise.all([
        apiClient.get<{ empleados: TableroFila[] }>("/asistencia/tablero"),
        apiClient.get<{ jornadas: JornadaIncompleta[] }>("/asistencia/incompletas"),
      ]);
      setFilas(t.empleados);
      setIncompletas(i.jornadas);
    } catch (e) {
      toast.current?.show({
        severity: "error", summary: "Error",
        detail: e instanceof Error ? e.message : "No se pudo cargar la asistencia",
        life: 5000,
      });
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => { cargar(); }, []);

  const abrirCorreccion = (j: JornadaIncompleta) => {
    setEditando(j);
    setHoraSalida("");
    setObservacion("");
  };

  const guardarCorreccion = async () => {
    if (!editando || !horaSalida) return;
    setGuardando(true);
    try {
      // La fecha viene del backend como ISO; la hora la carga RRHH.
      const dia = editando.fecha.slice(0, 10);
      await apiClient.put(`/asistencia/jornada/${editando.id}`, {
        salida: `${dia}T${horaSalida}:00`,
        observacion: observacion || null,
      });
      toast.current?.show({
        severity: "success", summary: "Listo",
        detail: "Jornada corregida y saldo recalculado", life: 3000,
      });
      setEditando(null);
      await cargar();
    } catch (e) {
      toast.current?.show({
        severity: "error", summary: "Error",
        detail: e instanceof Error ? e.message : "No se pudo guardar la corrección",
        life: 5000,
      });
    } finally {
      setGuardando(false);
    }
  };

  if (cargando) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-3xl mb-3" />
        <p>Cargando asistencia…</p>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <Toast ref={toast} />
      <h1 className="font-heading text-2xl text-foreground mb-6">Asistencia</h1>

      {incompletas.length > 0 && (
        <div className="mb-8 bg-card rounded-lg shadow-sm p-4 border border-border">
          <h2 className="font-heading text-lg text-foreground mb-1">
            Jornadas por corregir ({incompletas.length})
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Marcaron un solo extremo. No suman deuda hasta que cargues el faltante.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-2 pr-4">Empleado</th>
                  <th className="py-2 pr-4">Fecha</th>
                  <th className="py-2 pr-4">Entrada</th>
                  <th className="py-2 pr-4">Salida</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {incompletas.map((j) => (
                  <tr key={j.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-4 text-foreground">{j.employeeName}</td>
                    <td className="py-2 pr-4">{j.fecha.slice(0, 10)}</td>
                    <td className="py-2 pr-4">
                      {j.entrada ? j.entrada.slice(11, 16) : "—"}
                    </td>
                    <td className="py-2 pr-4">
                      {j.salida ? j.salida.slice(11, 16) : "—"}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        onClick={() => abrirCorreccion(j)}
                        className="px-3 py-1 rounded-lg bg-primary text-white text-xs hover:opacity-90"
                      >
                        Cargar salida
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="bg-card rounded-lg shadow-sm p-4 border border-border">
        <h2 className="font-heading text-lg text-foreground mb-4">
          Saldo por empleado
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="py-2 pr-4">Empleado</th>
                <th className="py-2 pr-4">ID reloj</th>
                <th className="py-2 pr-4 text-right">Saldo acumulado</th>
                <th className="py-2 pr-4 text-right">Ausencias</th>
                <th className="py-2 text-right">Incompletas</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f) => (
                <tr key={f.employeeId} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-foreground">{f.employeeName}</td>
                  <td className="py-2 pr-4 text-muted-foreground">{f.biometricoId}</td>
                  <td className={`py-2 pr-4 text-right ${claseSaldo(f.saldoAcumulado)}`}>
                    {fmtHoras(f.saldoAcumulado)}
                  </td>
                  <td className="py-2 pr-4 text-right">{f.ausencias}</td>
                  <td className="py-2 text-right">{f.incompletas}</td>
                </tr>
              ))}
              {filas.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-muted-foreground">
                    No hay empleados vinculados a un reloj todavía.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editando && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-lg shadow-lg p-6 w-full max-w-md">
            <h3 className="font-heading text-lg text-foreground mb-1">
              Cargar salida
            </h3>
            <p className="text-sm text-muted-foreground mb-4">
              {editando.employeeName} — {editando.fecha.slice(0, 10)}
            </p>

            <label className="block text-sm font-medium text-muted-foreground mb-1">
              Hora de salida
            </label>
            <input
              type="time"
              value={horaSalida}
              onChange={(e) => setHoraSalida(e.target.value)}
              className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm w-full mb-4"
            />

            <label className="block text-sm font-medium text-muted-foreground mb-1">
              Observación
            </label>
            <input
              type="text"
              value={observacion}
              onChange={(e) => setObservacion(e.target.value)}
              placeholder="Ej: olvidó marcar al retirarse"
              className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm w-full mb-6"
            />

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setEditando(null)}
                className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm"
              >
                Cancelar
              </button>
              <button
                onClick={guardarCorreccion}
                disabled={!horaSalida || guardando}
                className="px-4 py-2 rounded-lg bg-primary text-white text-sm disabled:opacity-50"
              >
                {guardando ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verificar que TypeScript compila**

Run desde `C:\Users\Emiliano\Documents\RRHH`: `npx tsc --noEmit`
Expected: sin errores en `AsistenciaTablero.tsx` ni en `Interfaces.ts`.

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/Asistencia/AsistenciaTablero.tsx src/app/Interfas/Interfaces.ts
git commit -m "feat: tablero de asistencia de RRHH con correccion de jornadas incompletas"
```

---

## Task 7: Frontend — vista del empleado y navegación

**Files:**
- Create: `src/app/Componentes/Asistencia/MiAsistencia.tsx`
- Create: `src/app/screens/Asistencia/Screen.tsx`
- Modify: `src/app/util/rbac.ts`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes de Task 4: `GET /asistencia/mi`.
- Consumes de Task 6: los tipos `JornadaDiaria`, el `Page` extendido y `AsistenciaTablero`.

- [ ] **Step 1: Crear la vista del empleado**

Crear `src/app/Componentes/Asistencia/MiAsistencia.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";
import { JornadaDiaria } from "@/app/Interfas/Interfaces";

const fmtHoras = (h: number) => {
  const signo = h < 0 ? "-" : h > 0 ? "+" : "";
  const abs = Math.abs(h);
  const horas = Math.floor(abs);
  const min = Math.round((abs - horas) * 60);
  return `${signo}${horas}h ${String(min).padStart(2, "0")}m`;
};

const ETIQUETA_ESTADO: Record<string, string> = {
  ok: "Normal",
  incompleta: "Incompleta",
  ausente: "Ausente",
  feriado: "No laborable",
  licencia: "Licencia",
  sin_horario: "Sin horario",
};

export default function MiAsistencia() {
  const [saldo, setSaldo] = useState(0);
  const [jornadas, setJornadas] = useState<JornadaDiaria[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get<{ saldoAcumulado: number; jornadas: JornadaDiaria[] }>(
          "/asistencia/mi",
        );
        setSaldo(r.saldoAcumulado);
        setJornadas(r.jornadas);
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo cargar tu asistencia");
      } finally {
        setCargando(false);
      }
    })();
  }, []);

  if (cargando) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-3xl mb-3" />
        <p>Cargando tu asistencia…</p>
      </div>
    );
  }

  if (error) {
    return <div className="p-8 text-center text-error">{error}</div>;
  }

  const debe = saldo < 0;

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <h1 className="font-heading text-2xl text-foreground mb-6">Mi asistencia</h1>

      <div className="bg-card rounded-lg shadow-sm p-6 border border-border mb-8">
        <p className="text-sm text-muted-foreground mb-1">Saldo acumulado</p>
        <p className={`text-4xl font-heading ${debe ? "text-error" : "text-success"}`}>
          {fmtHoras(saldo)}
        </p>
        <p className="text-sm text-muted-foreground mt-2">
          {saldo === 0
            ? "Estás al día."
            : debe
              ? "Horas que debés recuperar."
              : "Horas a tu favor."}
        </p>
      </div>

      <div className="bg-card rounded-lg shadow-sm p-4 border border-border">
        <h2 className="font-heading text-lg text-foreground mb-4">Desglose diario</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="py-2 pr-4">Fecha</th>
                <th className="py-2 pr-4">Entrada</th>
                <th className="py-2 pr-4">Salida</th>
                <th className="py-2 pr-4">Estado</th>
                <th className="py-2 pr-4 text-right">Trabajadas</th>
                <th className="py-2 pr-4 text-right">Requeridas</th>
                <th className="py-2 text-right">Saldo</th>
              </tr>
            </thead>
            <tbody>
              {jornadas.map((j) => (
                <tr key={j.id} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-foreground">{j.fecha.slice(0, 10)}</td>
                  <td className="py-2 pr-4">
                    {j.entrada ? j.entrada.slice(11, 16) : "—"}
                    {j.entradaManual && (
                      <span className="ml-1 text-xs text-muted-foreground">(manual)</span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {j.salida ? j.salida.slice(11, 16) : "—"}
                    {j.salidaManual && (
                      <span className="ml-1 text-xs text-muted-foreground">(manual)</span>
                    )}
                  </td>
                  <td className="py-2 pr-4">{ETIQUETA_ESTADO[j.estado] ?? j.estado}</td>
                  <td className="py-2 pr-4 text-right">{j.horasTrabajadas.toFixed(2)}</td>
                  <td className="py-2 pr-4 text-right">{j.horasRequeridas.toFixed(2)}</td>
                  <td
                    className={`py-2 text-right ${
                      j.saldoDia < 0
                        ? "text-error"
                        : j.saldoDia > 0
                          ? "text-success"
                          : "text-muted-foreground"
                    }`}
                  >
                    {fmtHoras(j.saldoDia)}
                  </td>
                </tr>
              ))}
              {jornadas.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-muted-foreground">
                    Todavía no hay jornadas registradas.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Crear la pantalla que ramifica por rol**

Crear `src/app/screens/Asistencia/Screen.tsx`:

```tsx
"use client";

import AsistenciaTablero from "@/app/Componentes/Asistencia/AsistenciaTablero";
import MiAsistencia from "@/app/Componentes/Asistencia/MiAsistencia";
import { ROLE_ID } from "@/app/util/rbac";

export default function AsistenciaPage({ roleId }: { roleId: number | null }) {
  return roleId === ROLE_ID.ADMIN || roleId === ROLE_ID.RRHH
    ? <AsistenciaTablero />
    : <MiAsistencia />;
}
```

- [ ] **Step 3: Agregar la entrada de navegación**

En `src/app/util/rbac.ts`, agregar en el array de páginas, junto a la entrada `reubicacion` (línea 137):

```typescript
  {
    id: "asistencia",
    label: "Asistencia",
    icon: "Clock",
    section: "Gente",
    visibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH, ROLE_ID.USER],
    accessibleFor: [ROLE_ID.ADMIN, ROLE_ID.RRHH, ROLE_ID.USER],
  },
```

A diferencia de Reubicación, acá `visibleFor` incluye a `USER`: el empleado ve el ítem en el menú porque tiene su propia vista.

- [ ] **Step 4: Enrutar la página**

En `src/app/page.tsx`, agregar el import junto a los demás:

```typescript
import AsistenciaPage from './screens/Asistencia/Screen';
```

Y el case en `renderPage()`, junto al de `reubicacion` (línea 151):

```typescript
      case 'asistencia':
        return <AsistenciaPage roleId={roleId} />;
```

- [ ] **Step 5: Verificar que TypeScript compila**

Run desde `C:\Users\Emiliano\Documents\RRHH`: `npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 6: Commit**

```bash
git add src/app/Componentes/Asistencia/MiAsistencia.tsx src/app/screens/Asistencia/Screen.tsx src/app/util/rbac.ts src/app/page.tsx
git commit -m "feat: vista de asistencia del empleado y navegacion por rol"
```

---

## Task 8: Permisos oficiales y disparadores de licencias

**Files:**
- Modify: `app/routes/rrhh.py:524-556` (endpoint `create_permission`)
- Modify: `app/routes/licenses.py:798-800` (aprobación de licencia)

**Interfaces:**
- Consumes de Task 3: `recalcular_anio`.
- Consumes de Task 2: la columna `Permission.oficial` ya creada por `ensure_tables`.
- Produces: `POST /rrhh/employee/{id}/permission` acepta `oficial: bool` en el body.

Sin esta tarea el spec queda a medias: la columna `oficial` existe y el motor la
usa, pero nada la escribe, y aprobar una licencia retroactiva no actualiza el
saldo hasta las 3 AM.

- [ ] **Step 1: Guardar `oficial` al crear un permiso**

En `app/routes/rrhh.py`, dentro de `create_permission`, agregar la lectura del
flag junto a las demás (después de `return_time = data.get("returnTime")`):

```python
    # Permiso oficial: no consume el banco de 12 h ni suma deuda. Por defecto
    # los permisos son regulares.
    oficial = bool(data.get("oficial", False))
```

Y reemplazar el INSERT:

```python
    db.execute(text("""
        INSERT INTO Permission (employeeId, date, exitTime, returnTime, hours)
        VALUES (:employeeId, :date, :exitTime, :returnTime, :hours)
    """), {"employeeId": employee_id, "date": date, "exitTime": exit_time, "returnTime": return_time, "hours": hours})
    db.commit()
```

por:

```python
    db.execute(text("""
        INSERT INTO Permission (employeeId, date, exitTime, returnTime, hours, oficial)
        VALUES (:employeeId, :date, :exitTime, :returnTime, :hours, :oficial)
    """), {"employeeId": employee_id, "date": date, "exitTime": exit_time,
           "returnTime": return_time, "hours": hours, "oficial": oficial})
    db.commit()

    # El permiso cambia las horas requeridas de ese dia: recalcular para que el
    # saldo quede al dia sin esperar al job nocturno.
    try:
        anio = date.year if hasattr(date, "year") else int(str(date)[:4])
        recalcular_anio(db, employee_id, anio)
    except Exception as e:
        print(f"[WARN] recalculo de asistencia fallido para {employee_id}: {e}")
```

Agregar el import arriba de `app/routes/rrhh.py`:

```python
from app.services.asistencia_recalc import recalcular_anio
```

- [ ] **Step 2: Disparar el recálculo al aprobar o rechazar una licencia**

En `app/routes/licenses.py`, agregar el import arriba del archivo:

```python
from app.services.asistencia_recalc import recalcular_anio as recalcular_asistencia
```

Localizar el `db.commit()` que cierra la transacción de `UPDATE License SET status`
(el bloque que arranca en la línea 798) y agregar inmediatamente después:

```python
        # Una licencia aprobada neutraliza esos dias; una rechazada los devuelve
        # al conteo. En ambos casos hay que recomputar el anio del empleado.
        try:
            inicio = lic["startDate"]
            anio = inicio.year if hasattr(inicio, "year") else int(str(inicio)[:4])
            recalcular_asistencia(db, lic["employeeId"], anio)
        except Exception as e:
            print(f"[WARN] recalculo de asistencia fallido para licencia {license_id}: {e}")
```

El recálculo va **después** del commit y envuelto en `try`: si falla, la licencia
ya quedó guardada y el job nocturno corrige el saldo.

- [ ] **Step 3: Verificar que ambos módulos importan sin errores**

Run: `python -c "import app.routes.rrhh, app.routes.licenses; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Verificar que no hay import circular**

`asistencia.py` importa `ROLE_RRHH` de `rrhh.py`, y ahora `rrhh.py` importa
`asistencia_recalc`. La cadena es `rrhh → asistencia_recalc → asistencia_calc`,
sin vuelta a `rrhh`, así que no hay ciclo.

Run: `python -c "from app.main import app; print('sin ciclos')"`
Expected: `sin ciclos`

- [ ] **Step 5: Verificar que la suite sigue verde**

Run: `python -m pytest tests/ -v`
Expected: PASS, 37 tests.

- [ ] **Step 6: Commit**

```bash
git add app/routes/rrhh.py app/routes/licenses.py
git commit -m "feat: permisos oficiales y disparadores de recalculo en licencias y permisos"
```

---

## Task 9: Frontend — checkbox "Oficial" en el alta de permisos

**Files:**
- Modify: `src/app/Componentes/ModalRRHH/LicenseModal.tsx` (componente `PermissionModal`)

Ruta relativa a `C:\Users\Emiliano\Documents\RRHH`.

**Interfaces:**
- Consumes de Task 8: `POST /rrhh/employee/{id}/permission` con `oficial` en el body.

- [ ] **Step 1: Leer el componente para ubicar el formulario**

Abrir `src/app/Componentes/ModalRRHH/LicenseModal.tsx` y localizar `PermissionModal`:
el estado del formulario, el campo de horas y el handler que hace el POST a
`/rrhh/employee/{id}/permission`.

- [ ] **Step 2: Agregar el estado del checkbox**

Junto a los demás `useState` del formulario de `PermissionModal`:

```tsx
const [oficial, setOficial] = useState(false);
```

- [ ] **Step 3: Agregar el checkbox al formulario**

Debajo del campo de horas, antes de los botones:

```tsx
<label className="flex items-center gap-2 mt-3 cursor-pointer">
  <input
    type="checkbox"
    checked={oficial}
    onChange={(e) => setOficial(e.target.checked)}
    className="w-4 h-4 accent-primary"
  />
  <span className="text-sm text-foreground">Permiso oficial</span>
</label>
<p className="text-xs text-muted-foreground mt-1">
  Un permiso oficial no consume el cupo de 12 h anuales ni genera horas a recuperar.
</p>
```

- [ ] **Step 4: Enviar el flag en el POST**

En el body del POST agregar `oficial`:

```tsx
oficial,
```

- [ ] **Step 5: Resetear el checkbox al cerrar**

Donde el modal limpia el formulario, agregar:

```tsx
setOficial(false);
```

- [ ] **Step 6: Verificar que TypeScript compila**

Run desde `C:\Users\Emiliano\Documents\RRHH`: `npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 7: Commit**

```bash
git add src/app/Componentes/ModalRRHH/LicenseModal.tsx
git commit -m "feat: checkbox de permiso oficial en el alta de permisos"
```

---

## Verificación final

Estos pasos los corre el usuario cuando decida levantar el servidor. **No los ejecutes vos.**

1. Arrancar el backend y confirmar en consola `[OK] tablas de asistencia verificadas`.
2. `POST /asistencia` no existe: la carga inicial de jornadas se dispara sola con el job de las 3 AM, o manualmente asignando un `biometricoId` a alguien desde el perfil.
3. Verificar en SQL Server que `JornadaDiaria` tiene filas y que `SELECT SUM(saldoDia) FROM JornadaDiaria WHERE employeeId = X` coincide con lo que muestra el tablero.
4. Entrar como RRHH a Asistencia, corregir una jornada incompleta y confirmar que desaparece del listado y que el saldo del empleado cambió.
5. Cargar un permiso regular de 2 h y confirmar que el saldo del día queda en 0 (banco disponible). Cargar permisos hasta pasar las 12 h del año y confirmar que el excedente aparece como deuda.
6. Cargar un permiso con "Oficial" tildado y confirmar que el saldo del día no se mueve.
7. Entrar como empleado y confirmar que solo ve lo propio.
