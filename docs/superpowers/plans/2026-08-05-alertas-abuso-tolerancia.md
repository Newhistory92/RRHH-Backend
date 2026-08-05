# Alertas por uso reiterado de la tolerancia — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detectar y mostrar a quienes usan sistemáticamente la tolerancia de 15 minutos, mediante un segundo umbral más estricto (7 min entrada, 5 min salida) que marca el día sin cambiar ninguna hora calculada.

**Arquitectura:** El motor puro de cálculo marca cada jornada con dos flags de abuso que se persisten en `JornadaDiaria`. Un módulo puro nuevo deriva la racha recorriendo los días ordenados, sin guardar ningún contador acumulado. La API expone el resumen y el frontend lo muestra en tres lugares: la vista del empleado, el tablero de RRHH y la pestaña de asistencia del legajo.

**Tech Stack:** FastAPI + SQLAlchemy Core (`text()` con binds nombrados) sobre SQL Server vía pyodbc. Frontend Next.js + TypeScript + Tailwind en `C:\Users\Emiliano\Documents\RRHH`. Tests con pytest.

## Global Constraints

- **NO levantar el servidor.** Nunca ejecutar `uvicorn` ni ningún dev server. La verificación es por tests y por scripts de consulta directa a la base.
- Umbrales por defecto, copiados del spec: `toleranciaEstrictaEntradaMin = 7`, `toleranciaEstrictaSalidaMin = 5`, `diasRachaAlerta = 3`.
- Un día abusa **solo si usó la tolerancia**: el tramo de más de 15 minutos ya se penaliza con descuento de horas y no cuenta como abuso.
- Los bordes son indulgentes: exactamente +7:00 no es abuso, igual que exactamente +15:00 sigue perdonado.
- Las comparaciones de desvío se hacen en **segundos enteros**, nunca en horas decimales.
- **Solo los días con estado `ok` participan** de la racha. Feriado, licencia, ausente, incompleta y sin horario se saltean: no suman ni cortan.
- Ante empate entre dos rachas de igual longitud gana **la más reciente**.
- Toda migración de esquema es idempotente: `IF COL_LENGTH(...) IS NULL ALTER TABLE ... ADD ...`.
- No se persiste ningún contador de racha: es una vista derivada.
- Los commits van en español, sin emoji, con `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` al final.

## Estructura de archivos

**Backend** (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/services/asistencia_calc.py` | *(modificar)* `Tolerancias`, `AjusteTolerancia`, flags de abuso en `ResultadoDia` |
| `app/services/asistencia_alertas.py` | *(crear)* módulo puro de rachas: `DiaAbuso`, `ResumenAbuso`, `resumir()` |
| `app/database/asistencia.py` | *(modificar)* columnas nuevas, config ampliada, `dias_abuso_de`, `dias_abuso_todos` |
| `app/services/asistencia_recalc.py` | *(modificar)* arma `Tolerancias` desde config, persiste los flags |
| `app/routes/asistencia.py` | *(modificar)* validación de config, endpoint de alertas, enriquecer respuestas |
| `tests/test_asistencia_calc.py` | *(modificar)* migrar llamadas + casos de borde de abuso |
| `tests/test_asistencia_alertas.py` | *(crear)* tests del módulo de rachas |

**Frontend** (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Interfas/Interfaces.ts` | *(modificar)* `ResumenAbuso`, campos nuevos en `JornadaDiaria` y `TableroFila` |
| `src/app/Componentes/Asistencia/MiAsistencia.tsx` | *(modificar)* aviso + badges por día |
| `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` | *(modificar)* panel de alertas + columna |
| `src/app/Componentes/TablaOperador/AsistenciaEmpleadoTab.tsx` | *(modificar)* cuarta tarjeta + badges |

---

### Task 1: Motor puro — segundo umbral y flags de abuso

**Files:**
- Modify: `app/services/asistencia_calc.py`
- Test: `tests/test_asistencia_calc.py`

**Interfaces:**
- Consumes: `HorarioDia(horaInicio: float, horaFin: float, horasTrabajo: float)` de `app.services.marcaciones_norm`.
- Produces:
  - `Tolerancias(entradaMin: int, salidaMin: int, estrictaEntradaMin: int, estrictaSalidaMin: int)` — dataclass congelada.
  - `AjusteTolerancia(brutas: float, entradaUsada: bool, salidaUsada: bool, abusoEntrada: bool, abusoSalida: bool)` — dataclass congelada.
  - `calcular_dia(entrada_dia: EntradaDia, tolerancias: Tolerancias, banco_disponible: float) -> Optional[ResultadoDia]`
  - `calcular_anio(dias: list[EntradaDia], tolerancias: Tolerancias) -> list[ResultadoDia]`
  - `ResultadoDia` suma los campos `abusoEntrada: bool` y `abusoSalida: bool`.

**Contexto:** `_ajustar_por_tolerancia` hoy recibe dos enteros sueltos y devuelve una tupla de tres. Sumar dos umbrales más llevaría la firma a seis parámetros posicionales. Por eso este task agrupa los cuatro umbrales en `Tolerancias` y el resultado en `AjusteTolerancia`, lo que obliga a migrar las ~30 llamadas de los tests existentes. Esa migración es mecánica y está resuelta con un `sed` en el paso 3.

- [ ] **Step 1: Migrar las llamadas de los tests existentes a `Tolerancias`**

Agregar la constante debajo de `JORNADA_8H` en `tests/test_asistencia_calc.py`:

```python
TOL = c.Tolerancias(entradaMin=15, salidaMin=15,
                    estrictaEntradaMin=7, estrictaSalidaMin=5)
```

Y reemplazar las llamadas:

```bash
sed -i 's/15, 15, 12\.0/TOL, 12.0/g; s/calcular_anio(dias, 15, 15)/calcular_anio(dias, TOL)/g' tests/test_asistencia_calc.py
```

Verificar que no quedó ninguna llamada vieja:

```bash
grep -n "15, 15" tests/test_asistencia_calc.py
```

Esperado: solo líneas de `_marcas(...)` como `_marcas((8, 15), (16, 0))`, ninguna con `calcular_dia` ni `calcular_anio`.

- [ ] **Step 2: Escribir los tests de borde que fallan**

Agregar al final de la sección `# -- Tolerancia ---` de `tests/test_asistencia_calc.py`.

Recordar que `JORNADA_8H` va de 8:00 a 16:00, con tolerancia 15 y estricta 7/5:

```python
# -- Segundo umbral: abuso de la tolerancia ----------------------------------

def test_entrada_dentro_del_margen_estricto_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 5), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is False


def test_entrada_justo_en_el_umbral_estricto_no_es_abuso():
    # 8:07:00 exacto: el borde es indulgente, igual que el de 15 minutos.
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 7), (16, 0))), TOL, 12.0)
    assert r.abusoEntrada is False


def test_entrada_un_segundo_pasado_el_umbral_estricto_es_abuso():
    dia = _dia(marcaciones=[datetime(2026, 7, 1, 8, 7, 1),
                            datetime(2026, 7, 1, 16, 0)])
    r = c.calcular_dia(dia, TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is True
    assert r.saldoDia == 0.0  # el abuso no descuenta horas


def test_entrada_en_el_limite_de_la_tolerancia_comun_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 15), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is True
    assert r.abusoEntrada is True


def test_entrada_pasada_la_tolerancia_comun_no_es_abuso_porque_ya_se_descuenta():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 16), (16, 0))), TOL, 12.0)
    assert r.toleranciaEntradaUsada is False
    assert r.abusoEntrada is False
    assert r.saldoDia < 0


def test_llegar_antes_de_hora_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((7, 50), (16, 0))), TOL, 12.0)
    assert r.abusoEntrada is False


def test_salida_dentro_del_margen_estricto_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 56))), TOL, 12.0)
    assert r.toleranciaSalidaUsada is True
    assert r.abusoSalida is False


def test_salida_pasada_el_margen_estricto_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (15, 54))), TOL, 12.0)
    assert r.toleranciaSalidaUsada is True
    assert r.abusoSalida is True
    assert r.saldoDia == 0.0


def test_salir_despues_de_hora_no_es_abuso():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 0), (16, 5))), TOL, 12.0)
    assert r.abusoSalida is False


def test_los_dos_extremos_pueden_abusar_el_mismo_dia():
    r = c.calcular_dia(_dia(marcaciones=_marcas((8, 12), (15, 52))), TOL, 12.0)
    assert r.abusoEntrada is True
    assert r.abusoSalida is True


def test_un_horario_que_no_arranca_en_hora_redonda_respeta_el_borde_exacto():
    """
    El desvio se compara en segundos enteros justamente para este caso: en
    horas decimales 7.5 + 7/60 y _hora_decimal(7:37:00) son la misma cantidad
    matematica pero pueden diferir en el ultimo bit del float.
    """
    horario = n.HorarioDia(horaInicio=7.5, horaFin=15.5, horasTrabajo=8.0)
    dia = _dia(horario=horario,
               marcaciones=[datetime(2026, 7, 1, 7, 37, 0),
                            datetime(2026, 7, 1, 15, 30)])
    r = c.calcular_dia(dia, TOL, 12.0)
    assert r.abusoEntrada is False


def test_los_dias_sin_jornada_calculada_no_marcan_abuso():
    ausente = c.calcular_dia(_dia(), TOL, 12.0)
    assert (ausente.abusoEntrada, ausente.abusoSalida) == (False, False)

    incompleta = c.calcular_dia(_dia(marcaciones=_marcas((8, 10))), TOL, 12.0)
    assert (incompleta.abusoEntrada, incompleta.abusoSalida) == (False, False)

    licencia = c.calcular_dia(_dia(tiene_licencia=True), TOL, 12.0)
    assert (licencia.abusoEntrada, licencia.abusoSalida) == (False, False)

    sin_horario = c.calcular_dia(_dia(horario=None), TOL, 12.0)
    assert (sin_horario.abusoEntrada, sin_horario.abusoSalida) == (False, False)

    feriado = c.calcular_dia(
        _dia(es_feriado=True, marcaciones=_marcas((8, 10), (16, 0))), TOL, 12.0,
    )
    assert (feriado.abusoEntrada, feriado.abusoSalida) == (False, False)
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_asistencia_calc.py -v
```

Esperado: FAIL con `AttributeError: module 'app.services.asistencia_calc' has no attribute 'Tolerancias'`.

- [ ] **Step 4: Agregar las dataclasses `Tolerancias` y `AjusteTolerancia`**

En `app/services/asistencia_calc.py`, debajo de la definición de `Permiso`:

```python
@dataclass(frozen=True)
class Tolerancias:
    """
    Los cuatro umbrales que rigen un dia. Van juntos porque siempre se usan
    juntos y porque pasarlos sueltos llevaba calcular_dia a seis parametros
    posicionales.

    Los estrictos son un segundo escalon POR DENTRO de los comunes: no cambian
    ninguna hora calculada, solo clasifican el dia como abuso.
    """
    entradaMin: int
    salidaMin: int
    estrictaEntradaMin: int
    estrictaSalidaMin: int


@dataclass(frozen=True)
class AjusteTolerancia:
    brutas: float
    entradaUsada: bool
    salidaUsada: bool
    abusoEntrada: bool
    abusoSalida: bool
```

- [ ] **Step 5: Sumar los flags a `ResultadoDia` y a `_resultado`**

En `ResultadoDia`, después de `toleranciaSalidaUsada: bool`:

```python
    abusoEntrada: bool
    abusoSalida: bool
```

En la firma de `_resultado`, después de `tol_sal: bool = False`:

```python
               abuso_ent: bool = False, abuso_sal: bool = False) -> ResultadoDia:
```

Y en el `ResultadoDia(...)` que construye, después de `toleranciaSalidaUsada=tol_sal,`:

```python
        abusoEntrada=abuso_ent, abusoSalida=abuso_sal,
```

- [ ] **Step 6: Reescribir `_ajustar_por_tolerancia`**

Reemplazar la función completa:

```python
def _ajustar_por_tolerancia(entrada: datetime, salida: datetime,
                            horario: HorarioDia,
                            tol: Tolerancias) -> AjusteTolerancia:
    """
    Cada extremo tiene su propio margen. Superado el margen se descuenta todo
    el desvio, no solo el excedente. Llegar antes o salir despues si acumula.

    El segundo escalon marca el dia como abuso cuando la persona se quedo del
    lado perdonado pero paso el margen razonable. La condicion exige que la
    tolerancia se haya usado: a quien llega mas tarde ya se le descuentan las
    horas y marcarlo ademas seria penalizarlo dos veces.

    El desvio se compara en segundos enteros. En horas decimales el borde
    exacto quedaria a merced del error del float cuando el horario no arranca
    en hora redonda: 7.5 + 7/60 y 7 + 37/60 son la misma cantidad matematica
    pero no necesariamente el mismo float.
    """
    ent = _hora_decimal(entrada)
    sal = _hora_decimal(salida)
    tol_ent = tol.entradaMin / 60
    tol_sal = tol.salidaMin / 60

    uso_entrada = horario.horaInicio < ent <= horario.horaInicio + tol_ent
    uso_salida = horario.horaFin - tol_sal <= sal < horario.horaFin

    # Antes de ajustar: despues del ajuste el desvio siempre seria cero.
    desvio_ent_seg = round((ent - horario.horaInicio) * 3600)
    desvio_sal_seg = round((horario.horaFin - sal) * 3600)

    abuso_entrada = uso_entrada and desvio_ent_seg > tol.estrictaEntradaMin * 60
    abuso_salida = uso_salida and desvio_sal_seg > tol.estrictaSalidaMin * 60

    if uso_entrada:
        ent = horario.horaInicio
    if uso_salida:
        sal = horario.horaFin

    return AjusteTolerancia(
        brutas=sal - ent,
        entradaUsada=uso_entrada, salidaUsada=uso_salida,
        abusoEntrada=abuso_entrada, abusoSalida=abuso_salida,
    )
```

- [ ] **Step 7: Adaptar `calcular_dia` y `calcular_anio`**

Cambiar la firma de `calcular_dia`:

```python
def calcular_dia(entrada_dia: EntradaDia, tolerancias: Tolerancias,
                 banco_disponible: float) -> Optional[ResultadoDia]:
```

Reemplazar el bloque final de la rama `ESTADO_OK` (desde la llamada a `_ajustar_por_tolerancia` hasta el `return`):

```python
    ajuste = _ajustar_por_tolerancia(entrada, salida, e.horario, tolerancias)
    # El reloj no sabe que se ausento en el medio de la jornada, asi que las
    # horas de permiso se restan siempre de lo trabajado. De lo requerido se
    # restan solo las perdonadas: las oficiales y las que cubre el banco.
    trabajadas = ajuste.brutas - permiso_regular - permiso_oficial
    requeridas = max(e.horario.horasTrabajo - permiso_oficial - permiso_banco, 0.0)

    return _resultado(
        e, ESTADO_OK, requeridas, trabajadas, trabajadas - requeridas,
        banco=permiso_banco, deuda=permiso_deuda, oficial=permiso_oficial,
        tol_ent=ajuste.entradaUsada, tol_sal=ajuste.salidaUsada,
        abuso_ent=ajuste.abusoEntrada, abuso_sal=ajuste.abusoSalida,
    )
```

Cambiar `calcular_anio`:

```python
def calcular_anio(dias: list[EntradaDia],
                  tolerancias: Tolerancias) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.
    """
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(d, tolerancias, BANCO_PERMISO_ANUAL_HORAS - consumido)
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
```

Y agregar los nombres nuevos a `__all__`:

```python
__all__ = [
    "BANCO_PERMISO_ANUAL_HORAS", "DIAS_HABILES", "ESTADO_OK",
    "ESTADO_INCOMPLETA", "ESTADO_AUSENTE", "ESTADO_FERIADO", "ESTADO_LICENCIA",
    "ESTADO_SIN_HORARIO", "HorarioDia", "Permiso", "EntradaDia", "ResultadoDia",
    "Tolerancias", "AjusteTolerancia", "calcular_dia", "calcular_anio",
]
```

- [ ] **Step 8: Correr los tests**

```bash
py -m pytest tests/test_asistencia_calc.py -v
```

Esperado: PASS en todos, incluidos los que ya existían. `app/services/asistencia_recalc.py` todavía no compila contra la firma nueva — se arregla en Task 4, así que la suite completa aún no pasa.

- [ ] **Step 9: Commit**

```bash
git add app/services/asistencia_calc.py tests/test_asistencia_calc.py
git commit -m "feat: segundo umbral de tolerancia que marca el dia como abuso

Agrega Tolerancias y AjusteTolerancia para no llevar calcular_dia a seis
parametros posicionales, y dos flags de abuso en ResultadoDia.

Un dia abusa cuando uso la tolerancia y ademas paso el margen estricto.
La condicion exige haber usado la tolerancia: a quien llega mas tarde ya
se le descuenta el desvio completo.

El desvio se compara en segundos enteros porque en horas decimales el
borde exacto dependeria del error del float con horarios que no arrancan
en hora redonda.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Módulo puro de rachas

**Files:**
- Create: `app/services/asistencia_alertas.py`
- Test: `tests/test_asistencia_alertas.py`

**Interfaces:**
- Consumes: nada del proyecto. Es un módulo puro que solo depende de `dataclasses` y `datetime`.
- Produces:
  - `DiaAbuso(fecha: date, estado: str, abuso: bool)` — dataclass congelada.
  - `ResumenAbuso(diasAbuso: int, rachaMaxima: int, fechasRachaMaxima: tuple[date, ...], alerta: bool)` — dataclass congelada.
  - `resumir(dias: list[DiaAbuso], dias_alerta: int) -> ResumenAbuso`
  - `validar_umbrales(tol_entrada, tol_salida, estricta_entrada, estricta_salida, dias_racha) -> None` — lanza `ValueError` con el mensaje para el usuario.

**Por qué la validación vive acá:** que una tolerancia estricta mayor que la común deje las alertas mudas es política de alertas, no persistencia. Ponerla en este módulo la deja pura y testeable sin `TestClient` ni base, que es como se testea todo lo demás del proyecto.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_asistencia_alertas.py`:

```python
from datetime import date

from app.services import asistencia_alertas as a


def _dia(dia_del_mes, abuso, estado="ok"):
    return a.DiaAbuso(fecha=date(2026, 8, dia_del_mes), estado=estado, abuso=abuso)


def test_lista_vacia_no_tiene_racha_ni_alerta():
    r = a.resumir([], dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.rachaMaxima == 0
    assert r.fechasRachaMaxima == ()
    assert r.alerta is False


def test_ningun_dia_con_abuso():
    r = a.resumir([_dia(3, False), _dia(4, False)], dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.alerta is False


def test_tres_dias_trabajados_encadenados_disparan_la_alerta():
    r = a.resumir([_dia(3, True), _dia(4, True), _dia(5, True)], dias_alerta=3)
    assert r.diasAbuso == 3
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))
    assert r.alerta is True


def test_dos_dias_encadenados_no_alcanzan():
    r = a.resumir([_dia(3, True), _dia(4, True)], dias_alerta=3)
    assert r.rachaMaxima == 2
    assert r.alerta is False


def test_un_dia_trabajado_sin_abuso_corta_la_racha():
    dias = [_dia(3, True), _dia(4, True), _dia(5, False), _dia(6, True)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 3
    assert r.rachaMaxima == 2
    assert r.alerta is False


def test_ausencia_licencia_e_incompleta_se_saltean_sin_cortar():
    """
    La tabla de recorrido del spec: lunes abusa, martes falta, miercoles abusa,
    jueves de licencia, viernes abusa -> tres dias trabajados encadenados.
    """
    dias = [
        _dia(3, True),
        _dia(4, False, estado="ausente"),
        _dia(5, True),
        _dia(6, False, estado="licencia"),
        _dia(7, True),
        _dia(8, False, estado="incompleta"),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 7))
    assert r.alerta is True


def test_los_dias_no_trabajados_no_suman_al_total_aunque_traigan_el_flag():
    dias = [_dia(3, True, estado="feriado"), _dia(4, True, estado="sin_horario")]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 0
    assert r.rachaMaxima == 0


def test_ante_empate_gana_la_racha_mas_reciente():
    dias = [
        _dia(3, True), _dia(4, True),
        _dia(5, False),
        _dia(6, True), _dia(7, True),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 2
    assert r.fechasRachaMaxima == (date(2026, 8, 6), date(2026, 8, 7))


def test_la_racha_mas_larga_gana_aunque_sea_anterior():
    dias = [
        _dia(3, True), _dia(4, True), _dia(5, True),
        _dia(6, False),
        _dia(7, True),
    ]
    r = a.resumir(dias, dias_alerta=3)
    assert r.rachaMaxima == 3
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))


def test_los_dias_se_ordenan_por_fecha_antes_de_recorrer():
    dias = [_dia(5, True), _dia(3, True), _dia(4, True)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.fechasRachaMaxima == (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))


def test_el_umbral_de_alerta_es_configurable():
    dias = [_dia(3, True), _dia(4, True)]
    assert a.resumir(dias, dias_alerta=2).alerta is True
    assert a.resumir(dias, dias_alerta=5).alerta is False


def test_todos_los_dias_con_abuso():
    dias = [_dia(d, True) for d in range(3, 11)]
    r = a.resumir(dias, dias_alerta=3)
    assert r.diasAbuso == 8
    assert r.rachaMaxima == 8
    assert r.alerta is True


# -- Validacion de umbrales ---------------------------------------------------

def test_umbrales_validos_no_lanzan():
    a.validar_umbrales(15, 15, 7, 5, 3)


def test_estricta_igual_a_la_comun_es_valida():
    a.validar_umbrales(15, 15, 15, 15, 3)


def test_estricta_de_entrada_mayor_que_la_comun_se_rechaza():
    """
    Con la estricta por encima de la comun la condicion de abuso no se cumple
    nunca: las alertas quedarian mudas sin ningun error visible.
    """
    try:
        a.validar_umbrales(15, 15, 16, 5, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaEntradaMin" in str(e)


def test_estricta_de_salida_mayor_que_la_comun_se_rechaza():
    try:
        a.validar_umbrales(15, 15, 7, 16, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaSalidaMin" in str(e)


def test_estricta_negativa_se_rechaza():
    try:
        a.validar_umbrales(15, 15, -1, 5, 3)
        assert False, "deberia haber lanzado ValueError"
    except ValueError as e:
        assert "toleranciaEstrictaEntradaMin" in str(e)


def test_dias_de_racha_fuera_de_rango_se_rechaza():
    for valor in (0, 31):
        try:
            a.validar_umbrales(15, 15, 7, 5, valor)
            assert False, f"deberia haber lanzado ValueError con {valor}"
        except ValueError as e:
            assert "diasRachaAlerta" in str(e)


def test_los_umbrales_opcionales_en_none_no_se_validan():
    """None significa 'dejar lo que estaba', no un valor a validar."""
    a.validar_umbrales(15, 15, None, None, None)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_asistencia_alertas.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.asistencia_alertas'`.

- [ ] **Step 3: Escribir el módulo**

Crear `app/services/asistencia_alertas.py`:

```python
"""
Deteccion de uso reiterado de la tolerancia. Funcion pura: recibe los dias ya
leidos de la base y devuelve el resumen, sin tocar SQL.

La racha NO se persiste en ninguna tabla. Es una vista derivada de los flags
que el motor de calculo guarda por dia: guardarla ademas seria estado que se
desincroniza en cuanto cambien los umbrales sin recalcular.
"""

from dataclasses import dataclass
from datetime import date

# Solo las jornadas efectivamente trabajadas participan de la racha. Un dia de
# licencia o una ausencia no son abuso ni lo desmienten: la persona no tuvo la
# oportunidad de llegar tarde, asi que se saltea sin sumar ni cortar.
ESTADO_COMPUTABLE = "ok"


@dataclass(frozen=True)
class DiaAbuso:
    fecha: date
    estado: str
    abuso: bool


@dataclass(frozen=True)
class ResumenAbuso:
    diasAbuso: int
    rachaMaxima: int
    fechasRachaMaxima: tuple[date, ...]
    alerta: bool


def resumir(dias: list[DiaAbuso], dias_alerta: int) -> ResumenAbuso:
    """
    Recorre los dias en orden y devuelve la corrida mas larga de jornadas
    trabajadas consecutivas con abuso.

    Ante empate gana la mas reciente: es la que importa para una conversacion
    hoy. Por eso la comparacion usa >= y no >.
    """
    corriente: list[date] = []
    mejor: list[date] = []
    total = 0

    for d in sorted(dias, key=lambda x: x.fecha):
        if d.estado != ESTADO_COMPUTABLE:
            continue
        if d.abuso:
            total += 1
            corriente.append(d.fecha)
            if len(corriente) >= len(mejor):
                mejor = list(corriente)
        else:
            corriente = []

    return ResumenAbuso(
        diasAbuso=total,
        rachaMaxima=len(mejor),
        fechasRachaMaxima=tuple(mejor),
        alerta=len(mejor) >= dias_alerta,
    )


def validar_umbrales(tol_entrada: int, tol_salida: int,
                     estricta_entrada: Optional[int],
                     estricta_salida: Optional[int],
                     dias_racha: Optional[int]) -> None:
    """
    Verifica la coherencia de la politica de alertas. Lanza ValueError con un
    mensaje listo para mostrar; el traductor a HTTP vive en la capa de rutas.

    Los opcionales en None significan "dejar lo que estaba" y no se validan.

    Una tolerancia estricta por encima de la comun haria que la condicion de
    abuso no se cumpla nunca: las alertas quedarian mudas para siempre sin
    ningun error visible. Se rechaza en vez de aceptar una configuracion que
    no hace nada.
    """
    if estricta_entrada is not None and not (0 <= estricta_entrada <= tol_entrada):
        raise ValueError(
            "toleranciaEstrictaEntradaMin debe estar entre 0 y toleranciaEntradaMin")
    if estricta_salida is not None and not (0 <= estricta_salida <= tol_salida):
        raise ValueError(
            "toleranciaEstrictaSalidaMin debe estar entre 0 y toleranciaSalidaMin")
    if dias_racha is not None and not (1 <= dias_racha <= 30):
        raise ValueError("diasRachaAlerta debe estar entre 1 y 30")
```

El módulo necesita `Optional` en los imports:

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional
```

- [ ] **Step 4: Correr los tests**

```bash
py -m pytest tests/test_asistencia_alertas.py -v
```

Esperado: PASS en los 19.

- [ ] **Step 5: Commit**

```bash
git add app/services/asistencia_alertas.py tests/test_asistencia_alertas.py
git commit -m "feat: modulo puro de rachas de abuso de tolerancia

Recorre los dias ordenados y devuelve la corrida mas larga de jornadas
trabajadas consecutivas con abuso, junto con sus fechas.

Solo participan los dias con estado ok: licencia, ausencia, incompleta y
feriado se saltean sin sumar ni cortar, porque la persona no tuvo la
oportunidad de llegar tarde. Ante empate gana la racha mas reciente.

Incluye validar_umbrales, que rechaza una tolerancia estricta mayor que
la comun: dejaria la condicion de abuso sin cumplirse nunca y las alertas
mudas. Vive aca y no en las rutas para poder testearla sin TestClient.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Persistencia — columnas, configuración y lectura

**Files:**
- Modify: `app/database/asistencia.py`

**Interfaces:**
- Consumes: `DiaAbuso` de `app.services.asistencia_alertas` (Task 2).
- Produces:
  - `get_config(db) -> dict` incluye ahora `toleranciaEstrictaEntradaMin`, `toleranciaEstrictaSalidaMin`, `diasRachaAlerta`.
  - `update_config(db, tol_entrada, tol_salida, fecha_inicio=None, estricta_entrada=None, estricta_salida=None, dias_racha=None) -> dict`
  - `dias_abuso_de(db, employee_id: int, desde: date, hasta: date) -> list[DiaAbuso]`
  - `dias_abuso_todos(db, desde: date, hasta: date) -> dict[int, list[DiaAbuso]]`
  - `reemplazar_jornadas` persiste `abusoEntrada` y `abusoSalida` desde las filas.
  - `jornadas_de` devuelve `abusoEntrada` y `abusoSalida` en cada fila.

**Contexto:** `ensure_tables` corre una vez por proceso y está protegida por el flag global `_tablas_listas`. Las migraciones nuevas van dentro, antes del `SEED_CONFIG_SQL`.

- [ ] **Step 1: Agregar las migraciones de columnas**

En `app/database/asistencia.py`, después de `ALTER_TOLERANCIA_SALIDA_SQL`:

```python
ALTER_ABUSO_ENTRADA_SQL = """
IF COL_LENGTH('JornadaDiaria','abusoEntrada') IS NULL
ALTER TABLE JornadaDiaria ADD abusoEntrada BIT NOT NULL DEFAULT 0;
"""

ALTER_ABUSO_SALIDA_SQL = """
IF COL_LENGTH('JornadaDiaria','abusoSalida') IS NULL
ALTER TABLE JornadaDiaria ADD abusoSalida BIT NOT NULL DEFAULT 0;
"""

# Segundo escalon de tolerancia y umbral de la alerta. Van en la misma fila de
# configuracion que los comunes porque son la misma politica.
ALTER_CONFIG_ESTRICTA_ENTRADA_SQL = """
IF COL_LENGTH('AsistenciaConfig','toleranciaEstrictaEntradaMin') IS NULL
ALTER TABLE AsistenciaConfig ADD toleranciaEstrictaEntradaMin INT NOT NULL DEFAULT 7;
"""

ALTER_CONFIG_ESTRICTA_SALIDA_SQL = """
IF COL_LENGTH('AsistenciaConfig','toleranciaEstrictaSalidaMin') IS NULL
ALTER TABLE AsistenciaConfig ADD toleranciaEstrictaSalidaMin INT NOT NULL DEFAULT 5;
"""

ALTER_CONFIG_DIAS_RACHA_SQL = """
IF COL_LENGTH('AsistenciaConfig','diasRachaAlerta') IS NULL
ALTER TABLE AsistenciaConfig ADD diasRachaAlerta INT NOT NULL DEFAULT 3;
"""
```

Y ejecutarlas en `ensure_tables`, justo después de `db.execute(text(ALTER_TOLERANCIA_SALIDA_SQL))` / `db.commit()`:

```python
    db.execute(text(ALTER_ABUSO_ENTRADA_SQL))
    db.commit()
    db.execute(text(ALTER_ABUSO_SALIDA_SQL))
    db.commit()
    db.execute(text(ALTER_CONFIG_ESTRICTA_ENTRADA_SQL))
    db.commit()
    db.execute(text(ALTER_CONFIG_ESTRICTA_SALIDA_SQL))
    db.commit()
    db.execute(text(ALTER_CONFIG_DIAS_RACHA_SQL))
    db.commit()
```

- [ ] **Step 2: Ampliar `get_config` y `update_config`**

Reemplazar las dos funciones completas:

```python
def get_config(db: Session) -> dict:
    fila = db.execute(text("""
        SELECT toleranciaEntradaMin, toleranciaSalidaMin, fechaInicioModulo,
               toleranciaEstrictaEntradaMin, toleranciaEstrictaSalidaMin,
               diasRachaAlerta
        FROM AsistenciaConfig WHERE id = 1
    """)).mappings().first()
    if fila is None:
        return {"toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
                "fechaInicioModulo": date.today(),
                "toleranciaEstrictaEntradaMin": 7,
                "toleranciaEstrictaSalidaMin": 5,
                "diasRachaAlerta": 3}
    return dict(fila)


def update_config(db: Session, tol_entrada: int, tol_salida: int,
                  fecha_inicio: Optional[date] = None,
                  estricta_entrada: Optional[int] = None,
                  estricta_salida: Optional[int] = None,
                  dias_racha: Optional[int] = None) -> dict:
    """
    fecha_inicio en None deja la que estaba. Se puede mover hacia atras cuando
    se recupera historico de los relojes, y hacia adelante para descartar un
    periodo poco confiable.

    Los tres umbrales de alerta en None tambien dejan lo que estaba: permite
    actualizar solo las tolerancias comunes sin pisar la politica de alertas.
    """
    db.execute(text("""
        UPDATE AsistenciaConfig
        SET toleranciaEntradaMin = :te,
            toleranciaSalidaMin  = :ts,
            fechaInicioModulo    = COALESCE(:fi, fechaInicioModulo),
            toleranciaEstrictaEntradaMin = COALESCE(:ee, toleranciaEstrictaEntradaMin),
            toleranciaEstrictaSalidaMin  = COALESCE(:es, toleranciaEstrictaSalidaMin),
            diasRachaAlerta      = COALESCE(:dr, diasRachaAlerta),
            updatedAt            = GETDATE()
        WHERE id = 1
    """), {"te": int(tol_entrada), "ts": int(tol_salida), "fi": fecha_inicio,
           "ee": estricta_entrada, "es": estricta_salida, "dr": dias_racha})
    db.commit()
    return get_config(db)
```

- [ ] **Step 3: Persistir y leer los flags**

En `reemplazar_jornadas`, cambiar el `INSERT`:

```python
        db.execute(text("""
            INSERT INTO JornadaDiaria
                (employeeId, fecha, estado, horasRequeridas, horasTrabajadas,
                 saldoDia, entrada, salida, entradaManual, salidaManual,
                 permisoBanco, permisoDeuda, permisoOficial,
                 toleranciaEntradaUsada, toleranciaSalidaUsada,
                 abusoEntrada, abusoSalida, calculadoAt)
            VALUES
                (:employeeId, :fecha, :estado, :horasRequeridas, :horasTrabajadas,
                 :saldoDia, :entrada, :salida, :entradaManual, :salidaManual,
                 :permisoBanco, :permisoDeuda, :permisoOficial,
                 :toleranciaEntradaUsada, :toleranciaSalidaUsada,
                 :abusoEntrada, :abusoSalida, :calculadoAt)
        """), {**f, "employeeId": employee_id, "calculadoAt": ahora})
```

En `jornadas_de`, agregar las dos columnas al `SELECT`, después de `j.toleranciaSalidaUsada,`:

```python
               j.abusoEntrada, j.abusoSalida,
```

- [ ] **Step 4: Agregar las funciones de lectura de abuso**

Al final de `app/database/asistencia.py`:

```python
def _a_dia_abuso(fila) -> "DiaAbuso":
    from app.services.asistencia_alertas import DiaAbuso
    f = fila["fecha"]
    return DiaAbuso(
        fecha=f if isinstance(f, date) else f.date(),
        estado=fila["estado"],
        abuso=bool(fila["abusoEntrada"]) or bool(fila["abusoSalida"]),
    )


def dias_abuso_de(db: Session, employee_id: int,
                  desde: date, hasta: date) -> list:
    """Los dias de un empleado, ordenados, listos para el modulo de rachas."""
    filas = db.execute(text("""
        SELECT fecha, estado, abusoEntrada, abusoSalida
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
        ORDER BY fecha
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return [_a_dia_abuso(f) for f in filas]


def dias_abuso_todos(db: Session, desde: date, hasta: date) -> dict[int, list]:
    """
    Lo mismo para todos los empleados en una sola consulta. Agrupar en Python
    evita una consulta por empleado, igual que hace tablero().
    """
    filas = db.execute(text("""
        SELECT employeeId, fecha, estado, abusoEntrada, abusoSalida
        FROM JornadaDiaria
        WHERE fecha >= :desde AND fecha <= :hasta
        ORDER BY employeeId, fecha
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    por_empleado: dict[int, list] = {}
    for f in filas:
        por_empleado.setdefault(int(f["employeeId"]), []).append(_a_dia_abuso(f))
    return por_empleado
```

- [ ] **Step 5: Verificar que las migraciones corren contra la base real**

Este paso toca la base de desarrollo, sin levantar servidor:

```bash
py -c "import sys, os; sys.path.insert(0, os.path.abspath('.')); from app.database.database import SessionLocal; from app.database.asistencia import ensure_tables, get_config; db = SessionLocal(); ensure_tables(db); print(get_config(db)); db.close()"
```

Esperado: imprime el dict de configuración con las seis claves, incluidas `toleranciaEstrictaEntradaMin: 7`, `toleranciaEstrictaSalidaMin: 5` y `diasRachaAlerta: 3`. Correrlo dos veces seguidas debe dar lo mismo sin error: la migración es idempotente.

- [ ] **Step 6: Commit**

```bash
git add app/database/asistencia.py
git commit -m "feat: persistencia de los flags de abuso y de los umbrales de alerta

Agrega abusoEntrada y abusoSalida a JornadaDiaria, y los tres umbrales
nuevos a AsistenciaConfig con sus defaults 7/5/3. Todas las migraciones
son idempotentes.

Suma dias_abuso_de y dias_abuso_todos, que dejan los dias listos para el
modulo de rachas. La version masiva agrupa en Python desde una sola
consulta para no disparar una por empleado.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Recálculo y API

**Files:**
- Modify: `app/services/asistencia_recalc.py`
- Modify: `app/routes/asistencia.py`

**Interfaces:**
- Consumes: `Tolerancias`, `calcular_anio` (Task 1); `resumir`, `ResumenAbuso` (Task 2); `get_config`, `update_config`, `dias_abuso_de`, `dias_abuso_todos` (Task 3).
- Produces:
  - `GET /asistencia/tablero` — cada empleado suma `diasAbuso: int`, `rachaMaxima: int`, `alerta: bool`.
  - `GET /asistencia/mi` y `GET /asistencia/empleado/{id}` — suman `abuso: {diasAbuso, rachaMaxima, fechasRachaMaxima, alerta}`.
  - `GET /asistencia/alertas-tolerancia?desde=&hasta=` — `{desde, hasta, empleados: [{employeeId, employeeName, diasAbuso, rachaMaxima, fechas, alerta}]}`.

- [ ] **Step 1: Adaptar el recálculo a la firma nueva**

En `app/services/asistencia_recalc.py`, agregar `Tolerancias` al import de `asistencia_calc`:

```python
from app.services.asistencia_calc import (
    EntradaDia, Permiso, ResultadoDia, Tolerancias, calcular_anio,
)
```

En `_a_fila`, agregar los dos campos al dict devuelto, después de `"toleranciaSalidaUsada": r.toleranciaSalidaUsada,`:

```python
        "abusoEntrada": r.abusoEntrada,
        "abusoSalida": r.abusoSalida,
```

Y en `recalcular_anio`, reemplazar la llamada a `calcular_anio`:

```python
    resultados = calcular_anio(entradas, Tolerancias(
        entradaMin=cfg["toleranciaEntradaMin"],
        salidaMin=cfg["toleranciaSalidaMin"],
        estrictaEntradaMin=cfg["toleranciaEstrictaEntradaMin"],
        estrictaSalidaMin=cfg["toleranciaEstrictaSalidaMin"],
    ))
```

- [ ] **Step 2: Correr la suite completa**

```bash
py -m pytest tests/ -v
```

Esperado: PASS en todo. Este es el paso que cierra la migración de firma que Task 1 dejó abierta.

- [ ] **Step 3: Validar los umbrales nuevos en `PUT /config`**

En `app/routes/asistencia.py`, dentro de `put_asistencia_config`, después del bloque que valida `0 <= tol_entrada <= 120`:

```python
    def _entero_opcional(clave: str) -> int | None:
        crudo = data.get(clave)
        if crudo in (None, ""):
            return None
        try:
            return int(crudo)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{clave} debe ser un entero")

    estricta_entrada = _entero_opcional("toleranciaEstrictaEntradaMin")
    estricta_salida = _entero_opcional("toleranciaEstrictaSalidaMin")
    dias_racha = _entero_opcional("diasRachaAlerta")

    # La regla vive en el modulo de alertas, que es puro y esta cubierto por
    # tests. Aca solo se traduce el error a HTTP.
    try:
        validar_umbrales(tol_entrada, tol_salida,
                         estricta_entrada, estricta_salida, dias_racha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Y cambiar el `return` final:

```python
    return update_config(db, tol_entrada, tol_salida, fecha_inicio,
                         estricta_entrada, estricta_salida, dias_racha)
```

- [ ] **Step 4: Enriquecer las respuestas y agregar el endpoint de alertas**

En los imports de `app/routes/asistencia.py`, agregar a la lista que viene de `app.database.asistencia`:

```python
    dias_abuso_de, dias_abuso_todos,
```

Y un import nuevo:

```python
from app.services.asistencia_alertas import resumir, validar_umbrales
```

En `get_tablero`, reemplazar el `return`:

```python
    cfg = get_config(db)
    filas = tablero(db, d, h)
    por_empleado = dias_abuso_todos(db, d, h)
    for fila in filas:
        r = resumir(por_empleado.get(fila["employeeId"], []), cfg["diasRachaAlerta"])
        fila["diasAbuso"] = r.diasAbuso
        fila["rachaMaxima"] = r.rachaMaxima
        fila["alerta"] = r.alerta
    return {"desde": d.isoformat(), "hasta": h.isoformat(), "empleados": filas}
```

En `get_empleado` y en `get_mi_asistencia`, agregar al dict devuelto:

```python
        "abuso": _resumen_abuso(db, employee_id, d, h),
```

Y definir el helper antes de `get_empleado`:

```python
def _resumen_abuso(db: Session, employee_id: int, desde, hasta) -> dict:
    """El resumen de abuso serializado, con las fechas como ISO."""
    cfg = get_config(db)
    r = resumir(dias_abuso_de(db, employee_id, desde, hasta), cfg["diasRachaAlerta"])
    return {
        "diasAbuso": r.diasAbuso,
        "rachaMaxima": r.rachaMaxima,
        "fechasRachaMaxima": [f.isoformat() for f in r.fechasRachaMaxima],
        "alerta": r.alerta,
        "toleranciaEstrictaEntradaMin": cfg["toleranciaEstrictaEntradaMin"],
        "toleranciaEstrictaSalidaMin": cfg["toleranciaEstrictaSalidaMin"],
    }
```

Y agregar el endpoint nuevo, después de `get_tablero`:

```python
@router.get("/alertas-tolerancia", dependencies=[SOLO_RRHH])
def get_alertas_tolerancia(desde: str | None = None, hasta: str | None = None,
                           db: Session = Depends(get_db)):
    """
    Solo los empleados que superaron la racha en el rango. El tablero lo usa
    para su panel sin tener que filtrar del lado del cliente.
    """
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    cfg = get_config(db)
    # Solo hacen falta los nombres: tablero() traeria ademas los agregados de
    # saldo y ausencias, que aca no se usan.
    nombres = {
        int(f["id"]): f["name"]
        for f in db.execute(text("SELECT id, name FROM Employee")).mappings().all()
    }
    empleados = []
    for employee_id, dias in dias_abuso_todos(db, d, h).items():
        r = resumir(dias, cfg["diasRachaAlerta"])
        if not r.alerta:
            continue
        empleados.append({
            "employeeId": employee_id,
            "employeeName": nombres.get(employee_id, ""),
            "diasAbuso": r.diasAbuso,
            "rachaMaxima": r.rachaMaxima,
            "fechas": [f.isoformat() for f in r.fechasRachaMaxima],
        })
    empleados.sort(key=lambda x: (-x["rachaMaxima"], x["employeeName"]))
    return {"desde": d.isoformat(), "hasta": h.isoformat(),
            "empleados": empleados, "diasRachaAlerta": cfg["diasRachaAlerta"]}
```

- [ ] **Step 5: Verificar el flujo completo contra la base real**

Sin levantar servidor: recalcular y consultar directamente.

```bash
py -c "import sys, os; sys.path.insert(0, os.path.abspath('.')); from datetime import date; from app.database.database import SessionLocal; from app.services.asistencia_recalc import recalcular_todos; db = SessionLocal(); print(recalcular_todos(db, date.today().year, origen='alertas-tolerancia')); db.close()"
```

Esperado: `{'procesados': N, 'filas': M, 'errores': []}` sin excepciones.

Después, verificar que los flags quedaron escritos:

```bash
py -c "import sys, os; sys.path.insert(0, os.path.abspath('.')); from datetime import date; from app.database.database import SessionLocal; from sqlalchemy import text; db = SessionLocal(); [print(dict(f)) for f in db.execute(text('SELECT TOP 20 employeeId, fecha, estado, entrada, abusoEntrada, abusoSalida FROM JornadaDiaria ORDER BY fecha DESC')).mappings().all()]; db.close()"
```

Esperado: filas con las dos columnas nuevas en `True`/`False`, sin error de columna inexistente.

- [ ] **Step 6: Commit**

```bash
git add app/services/asistencia_recalc.py app/routes/asistencia.py
git commit -m "feat: recalculo y API de alertas por abuso de tolerancia

El recalculo arma Tolerancias desde la configuracion y persiste los dos
flags. El tablero, /mi y /empleado suman el resumen de abuso, y se agrega
/asistencia/alertas-tolerancia con solo los empleados en alerta.

PUT /config valida que la tolerancia estricta no supere a la comun: si lo
hiciera, la condicion de abuso no se cumpliria nunca y las alertas no
saltarian jamas sin ningun error visible.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — vista del empleado

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Interfas\Interfaces.ts`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\Asistencia\MiAsistencia.tsx`

**Interfaces:**
- Consumes: `GET /asistencia/mi` con la forma que produce Task 4.
- Produces: los tipos `ResumenAbuso` y los campos nuevos de `JornadaDiaria` y `TableroFila`, que Task 6 reutiliza.

**Nota de tono:** el texto es descriptivo, nunca acusatorio. La persona ve el mismo dato que RRHH, con las fechas concretas, antes de que exista cualquier conversación. Un aviso verificable y discutible vale más que uno que sorprende.

- [ ] **Step 1: Agregar los tipos**

En `src/app/Interfas/Interfaces.ts`, dentro de `JornadaDiaria`, después de `salidaManual: boolean;`:

```typescript
  abusoEntrada: boolean;
  abusoSalida: boolean;
```

Dentro de `TableroFila`, después de `incompletas: number;`:

```typescript
  diasAbuso: number;
  rachaMaxima: number;
  alerta: boolean;
```

Y agregar las dos interfaces nuevas después de `TableroFila`:

```typescript
/** Resumen de uso reiterado de la tolerancia en un rango. */
export interface ResumenAbuso {
  diasAbuso: number;
  rachaMaxima: number;
  fechasRachaMaxima: string[];
  alerta: boolean;
  toleranciaEstrictaEntradaMin: number;
  toleranciaEstrictaSalidaMin: number;
}

/** Fila del panel de alertas del tablero de RRHH. */
export interface AlertaTolerancia {
  employeeId: number;
  employeeName: string;
  diasAbuso: number;
  rachaMaxima: number;
  fechas: string[];
}
```

- [ ] **Step 2: Mostrar el aviso y los badges en `MiAsistencia`**

En `src/app/Componentes/Asistencia/MiAsistencia.tsx`, cambiar el import de tipos:

```tsx
import { JornadaDiaria, ResumenAbuso } from "@/app/Interfas/Interfaces";
```

Agregar el helper de formato de fechas debajo de `ETIQUETA_ESTADO`:

```tsx
const fmtFechas = (fechas: string[]) =>
  fechas
    .map((f) => {
      const [, mes, dia] = f.split("-");
      return `${Number(dia)}/${Number(mes)}`;
    })
    .join(", ");
```

Agregar el estado, después de `const [jornadas, setJornadas] = useState<JornadaDiaria[]>([]);`:

```tsx
  const [abuso, setAbuso] = useState<ResumenAbuso | null>(null);
```

Cambiar el tipo de la respuesta y guardarlo, dentro del `useEffect`:

```tsx
        const r = await apiClient.get<{
          saldoAcumulado: number;
          jornadas: JornadaDiaria[];
          abuso: ResumenAbuso;
        }>("/asistencia/mi");
        setSaldo(r.saldoAcumulado);
        setJornadas(r.jornadas);
        setAbuso(r.abuso);
```

Insertar el aviso justo después de `<h1 ...>Mi asistencia</h1>`:

```tsx
      {abuso?.alerta && (
        <div className="mb-6 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950/40">
          <p className="font-semibold text-amber-800 dark:text-amber-300">
            Uso reiterado del margen de tolerancia
          </p>
          <p className="mt-1 text-sm text-amber-700 dark:text-amber-400">
            Marcaste fuera del margen de {abuso.toleranciaEstrictaEntradaMin} minutos
            a la entrada o {abuso.toleranciaEstrictaSalidaMin} a la salida{" "}
            {abuso.rachaMaxima} días seguidos ({fmtFechas(abuso.fechasRachaMaxima)}).
            No se te descontaron horas: sigue estando dentro de la tolerancia.
          </p>
        </div>
      )}
```

Y agregar el badge en la fila del desglose, dentro de la celda de estado, reemplazando:

```tsx
                  <td className="py-2 pr-4">{ETIQUETA_ESTADO[j.estado] ?? j.estado}</td>
```

por:

```tsx
                  <td className="py-2 pr-4">
                    {ETIQUETA_ESTADO[j.estado] ?? j.estado}
                    {(j.abusoEntrada || j.abusoSalida) && (
                      <span
                        className="ml-2 rounded px-1.5 py-0.5 text-xs bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
                        title={
                          j.abusoEntrada && j.abusoSalida
                            ? "Fuera del margen en la entrada y en la salida"
                            : j.abusoEntrada
                              ? "Fuera del margen en la entrada"
                              : "Fuera del margen en la salida"
                        }
                      >
                        margen
                      </span>
                    )}
                  </td>
```

- [ ] **Step 3: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "MiAsistencia|Interfaces"
```

Esperado: sin salida. El proyecto tiene errores de tipos previos en otros archivos que no son parte de este trabajo; el filtro aísla los dos que sí lo son.

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Interfas/Interfaces.ts src/app/Componentes/Asistencia/MiAsistencia.tsx
git commit -m "feat: aviso de uso reiterado de tolerancia en Mi Asistencia

El empleado ve el mismo dato que RRHH, con las fechas concretas y antes
de cualquier conversacion. El texto es descriptivo y aclara que no hubo
descuento de horas: un aviso verificable vale mas que uno que sorprende.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — tablero de RRHH y pestaña del legajo

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\Asistencia\AsistenciaTablero.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\AsistenciaEmpleadoTab.tsx`

**Interfaces:**
- Consumes: `TableroFila` con `diasAbuso`/`rachaMaxima`/`alerta`, `AlertaTolerancia` y `ResumenAbuso` (Task 5); `GET /asistencia/alertas-tolerancia` y `GET /asistencia/empleado/{id}` (Task 4).
- Produces: nada que consuman otros tasks. Es la última pieza.

- [ ] **Step 1: Cargar y mostrar el panel de alertas en el tablero**

En `AsistenciaTablero.tsx`, cambiar el import de tipos:

```tsx
import { AlertaTolerancia, JornadaIncompleta, TableroFila } from "@/app/Interfas/Interfaces";
```

Agregar el helper de fechas debajo de `claseSaldo`:

```tsx
const fmtFechas = (fechas: string[]) =>
  fechas
    .map((f) => {
      const [, mes, dia] = f.split("-");
      return `${Number(dia)}/${Number(mes)}`;
    })
    .join(", ");
```

Agregar el estado, después de `const [huerfanos, setHuerfanos] = useState<BiometricoHuerfano[]>([]);`:

```tsx
  const [alertas, setAlertas] = useState<AlertaTolerancia[]>([]);
```

Y sumar la llamada dentro de `cargar()`:

```tsx
      const [t, i, h, a] = await Promise.all([
        apiClient.get<{ empleados: TableroFila[] }>(`/asistencia/tablero?desde=${desdeTablero}&hasta=${hastaTablero}`),
        apiClient.get<{ jornadas: JornadaIncompleta[] }>("/asistencia/incompletas"),
        apiClient.get<{ huerfanos: BiometricoHuerfano[] }>("/asistencia/biometricos-huerfanos"),
        apiClient.get<{ empleados: AlertaTolerancia[] }>(`/asistencia/alertas-tolerancia?desde=${desdeTablero}&hasta=${hastaTablero}`),
      ]);
      setFilas(t.empleados);
      setIncompletas(i.jornadas);
      setHuerfanos(h.huerfanos);
      setAlertas(a.empleados);
```

- [ ] **Step 2: Renderizar el panel**

Insertar justo antes del comentario `{/* ── Tablero de saldo por empleado ─────...`:

```tsx
      {/* ── Uso reiterado de tolerancia ──────────────────────────── */}
      {alertas.length > 0 && (
        <div className="mb-8 bg-card rounded-lg shadow-sm p-6 border border-amber-300 dark:border-amber-700">
          <h2 className="font-heading text-lg text-amber-800 dark:text-amber-300 mb-1">
            Uso reiterado de tolerancia
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Marcaron fuera del margen estricto varios días trabajados seguidos.
            No se les descontaron horas: siguen dentro de la tolerancia.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="py-2 pr-4">Empleado</th>
                  <th className="py-2 pr-4 text-right">Días seguidos</th>
                  <th className="py-2 pr-4 text-right">Días en el período</th>
                  <th className="py-2">Fechas</th>
                </tr>
              </thead>
              <tbody>
                {alertas.map((a) => (
                  <tr key={a.employeeId} className="border-b border-border last:border-0">
                    <td className="py-2 pr-4 text-foreground">{a.employeeName}</td>
                    <td className="py-2 pr-4 text-right font-semibold text-amber-700 dark:text-amber-400">
                      {a.rachaMaxima}
                    </td>
                    <td className="py-2 pr-4 text-right">{a.diasAbuso}</td>
                    <td className="py-2 text-muted-foreground">{fmtFechas(a.fechas)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
```

- [ ] **Step 3: Agregar la columna a la tabla de saldo**

Reemplazar el `<tr>` completo del `<thead>` de la tabla de saldo. Queda así (la
diferencia es que `Incompletas` pierde el `text-right` suelto y gana `pr-4`, y se suma
la columna nueva al final):

```tsx
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="py-2 pr-4">Empleado</th>
                <th className="py-2 pr-4">ID reloj</th>
                <th className="py-2 pr-4 text-right">Saldo acumulado</th>
                <th className="py-2 pr-4 text-right">Ausencias</th>
                <th className="py-2 pr-4 text-right">Incompletas</th>
                <th className="py-2 text-right">Días con tolerancia</th>
              </tr>
```

En el `<tbody>`, reemplazar la celda de incompletas por:

```tsx
                  <td className="py-2 pr-4 text-right">{f.biometricoId ? f.incompletas : "—"}</td>
                  <td className="py-2 text-right">
                    {f.biometricoId ? (
                      <span className={f.alerta ? "text-amber-700 dark:text-amber-400 font-semibold" : ""}>
                        {f.diasAbuso}
                        {f.alerta && <span className="ml-1" title={`${f.rachaMaxima} días seguidos`}>⚠</span>}
                      </span>
                    ) : "—"}
                  </td>
```

Y actualizar el `colSpan` de la fila vacía de `5` a `6`:

```tsx
                  <td colSpan={6} className="py-6 text-center text-muted-foreground">
```

- [ ] **Step 4: Agregar la cuarta tarjeta y los badges en la pestaña del legajo**

En `AsistenciaEmpleadoTab.tsx`, cambiar el import de tipos:

```tsx
import { Employee, JornadaDiaria, ResumenAbuso } from "@/app/Interfas/Interfaces";
```

Agregar el estado, después de `const [jornadas, setJornadas] = useState<JornadaDiaria[]>([]);`:

```tsx
  const [abuso, setAbuso] = useState<ResumenAbuso | null>(null);
```

Cambiar el tipo de la respuesta dentro del `useEffect`:

```tsx
        const r = await apiClient.get<{
          saldoAcumulado: number;
          jornadas: JornadaDiaria[];
          abuso: ResumenAbuso;
        }>(`/asistencia/empleado/${employee.id}`);
        setSaldo(r.saldoAcumulado);
        setJornadas(r.jornadas);
        setAbuso(r.abuso);
```

Cambiar la grilla de resumen de `grid-cols-3` a `grid-cols-4`:

```tsx
      <div className="grid grid-cols-4 gap-4">
```

Y agregar la cuarta tarjeta después de la de incompletas:

```tsx
        <div className="bg-card rounded-lg border border-border p-5">
          <p className="text-xs text-muted-foreground mb-1">Días con tolerancia</p>
          <p className={`text-3xl font-heading ${abuso?.alerta ? "text-amber-700 dark:text-amber-400" : "text-foreground"}`}>
            {abuso?.diasAbuso ?? 0}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {abuso?.alerta
              ? `${abuso.rachaMaxima} días seguidos`
              : "fuera del margen estricto"}
          </p>
        </div>
```

Y el badge en la celda de estado del desglose, reemplazando:

```tsx
                  <td className={`py-2 pr-4 ${COLOR_ESTADO[j.estado] ?? ""}`}>
                    {ETIQUETA[j.estado] ?? j.estado}
                  </td>
```

por:

```tsx
                  <td className={`py-2 pr-4 ${COLOR_ESTADO[j.estado] ?? ""}`}>
                    {ETIQUETA[j.estado] ?? j.estado}
                    {(j.abusoEntrada || j.abusoSalida) && (
                      <span
                        className="ml-2 rounded px-1.5 py-0.5 text-xs bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
                        title={
                          j.abusoEntrada && j.abusoSalida
                            ? "Fuera del margen en la entrada y en la salida"
                            : j.abusoEntrada
                              ? "Fuera del margen en la entrada"
                              : "Fuera del margen en la salida"
                        }
                      >
                        margen
                      </span>
                    )}
                  </td>
```

- [ ] **Step 5: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "AsistenciaTablero|AsistenciaEmpleadoTab"
```

Esperado: sin salida.

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/Asistencia/AsistenciaTablero.tsx src/app/Componentes/TablaOperador/AsistenciaEmpleadoTab.tsx
git commit -m "feat: panel y columna de uso reiterado de tolerancia para RRHH

El tablero suma un panel con los empleados en alerta y sus fechas, mas
una columna con el total de dias del periodo: cubre tambien al que abusa
seguido sin llegar nunca a encadenar tres.

La pestana Asistencia del legajo suma la cuarta tarjeta y los mismos
badges por dia.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verificación final

Después del último task, con la rama completa:

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m pytest tests/ -v
```

Esperado: PASS en toda la suite.

Y un recálculo real seguido de la consulta del resumen, sin levantar servidor:

```bash
py -c "import sys, os; sys.path.insert(0, os.path.abspath('.')); from datetime import date; from app.database.database import SessionLocal; from app.database.asistencia import dias_abuso_todos, get_config; from app.services.asistencia_alertas import resumir; db = SessionLocal(); cfg = get_config(db); [print(eid, resumir(d, cfg['diasRachaAlerta'])) for eid, d in dias_abuso_todos(db, date(date.today().year, 1, 1), date.today()).items()]; db.close()"
```

Esperado: una línea por empleado con su `ResumenAbuso`, sin excepciones.
