# Carga inicial de saldos de licencias — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que RRHH pueda cargar, empleado por empleado, los días de licencia que le quedan pendientes de años anteriores a su alta, y corregir de paso los tres defectos de `/licenses/aplicar` que descuentan días a la persona equivocada.

**Architecture:** Una tabla nueva en RRHH guarda el saldo pendiente por `(empleado, año, categoría)`. Donde hay saldo cargado, ese valor reemplaza al total en el cálculo de `GET /licenses/saldos`; el consumo posterior lo descuenta por el circuito común. Los endpoints de carga viven en un router propio para que borrarlos al terminar la migración sea eliminar un archivo y una línea, no cirugía sobre un archivo de 1100 líneas.

**Tech Stack:** FastAPI, SQLAlchemy Core con `text()`, SQL Server (pyodbc), pytest con el patrón `FakeSession`; Next.js 15 App Router, PrimeReact, Tailwind.

## Global Constraints

- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de sólo lectura. Las tablas de este trabajo van en RRHH.
- Cero IDs de rol hardcodeados. La autorización siempre vía `require_permission(...)`.
- Los archivos `.env` no se commitean ni se copian a ningún lado.
- El permiso nuevo se llama exactamente `licencias.cargaInicial`.
- La tabla nueva se llama exactamente `SaldoInicialLicencia`.
- Tres estados y no dos: sin fila = no se cargó nada; `diasPendientes = 0` = no le queda nada; `> 0` = le quedan esos días. Vacío y cero nunca se confunden.
- La ventana de carga es el año calendario en curso y los dos anteriores.
- Solo Vacaciones es acumulable. Las demás categorías se cargan únicamente para el año en curso.
- Comentarios y docstrings en español sin tildes, como el resto del repositorio.

---

## Estructura de archivos

**Backend — `C:\Users\Emiliano\Documents\Backend_RRHH`**

| Archivo | Responsabilidad |
|---|---|
| `app/database/saldo_inicial_licencias.py` *(nuevo)* | DDL de `SaldoInicialLicencia` y capa de datos: leer y guardar saldos |
| `app/services/saldo_licencias.py` *(nuevo)* | Funciones puras de decisión: qué total rige y qué años faltan |
| `app/routes/carga_inicial_licencias.py` *(nuevo)* | Los dos endpoints de carga. Archivo aparte para poder borrarlo entero al terminar |
| `app/permisos.py` *(modificar)* | Sumar `licencias.cargaInicial` al catálogo |
| `app/routes/licenses.py` *(modificar)* | Integrar el saldo inicial al cálculo y corregir `/aplicar` |
| `app/main.py` *(modificar)* | Registrar el router nuevo |

**Frontend — `C:\Users\Emiliano\Documents\RRHH`**

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/TablaOperador/CargaInicialLicenciasTab.tsx` *(nuevo)* | La pestaña de carga. Se borra al terminar la migración |
| `src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx` *(nuevo)* | El documento de ayuda |
| `src/app/Componentes/TablaOperador/Perfildetail.tsx` *(modificar)* | Sumar la pestaña, condicionada al permiso |
| `src/app/screens/LicenciasManage/Screen.tsx` *(modificar)* | El botón con signo de admiración |
| `src/app/Interfas/Interfaces.ts` *(modificar)* | Tipos de la carga inicial |

---

### Task 1: Capa de datos de SaldoInicialLicencia

**Files:**
- Create: `app/database/saldo_inicial_licencias.py`
- Test: `tests/test_saldo_inicial_licencias.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `ensure_table(db: Session) -> None`
  - `saldos_de_empleado(db: Session, employee_id: int) -> dict[tuple[int, str], int]` — clave `(anio, categoria)`, valor `diasPendientes`
  - `upsert_saldos(db: Session, employee_id: int, filas: list[dict], cargado_por: int | None) -> int` — cada fila es `{"anio": int, "categoria": str, "diasPendientes": int}`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_saldo_inicial_licencias.py`:

```python
"""
Tests de la capa de datos de SaldoInicialLicencia.

FakeSession no ejecuta SQL: verifica que se emitan las sentencias correctas
con los binds correctos, y que las funciones traduzcan bien las filas.
"""

from app.database.saldo_inicial_licencias import (
    ensure_table,
    saldos_de_empleado,
    upsert_saldos,
)
from tests.fakes import FakeSession


def test_ensure_table_crea_tabla_en_rrhh_no_en_obrasocial():
    """El saldo inicial vive en RRHH: ObraSocial es de solo lectura."""
    db = FakeSession()
    ensure_table(db)
    sql = db.sql_ejecutado()
    assert "SaldoInicialLicencia" in sql
    assert "ObraSocial" not in sql


def test_ensure_table_es_repetible():
    """Se llama en cada request de la carga; no puede fallar la segunda vez."""
    db = FakeSession()
    ensure_table(db)
    assert "IF OBJECT_ID" in db.sql_ejecutado()


def test_saldos_de_empleado_mapea_por_anio_y_categoria():
    db = FakeSession({"FROM SaldoInicialLicencia": [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
        {"anio": 2026, "categoria": "Particular", "diasPendientes": 0},
    ]})
    assert saldos_de_empleado(db, 8) == {
        (2024, "Vacaciones"): 5,
        (2026, "Particular"): 0,
    }


def test_saldos_de_empleado_filtra_por_empleado():
    """Sin este bind, un empleado veria el saldo cargado de otro."""
    db = FakeSession()
    saldos_de_empleado(db, 8)
    _sql, params = db.ejecutadas[-1]
    assert params["empId"] == 8


def test_saldos_de_empleado_conserva_el_cero():
    """Cero es 'no le queda nada', un dato cargado a proposito. Si se
    perdiera, la fila volveria a leerse como 'no se cargo nada' y el sistema
    le otorgaria los dias completos."""
    db = FakeSession({"FROM SaldoInicialLicencia": [
        {"anio": 2026, "categoria": "Particular", "diasPendientes": 0},
    ]})
    assert saldos_de_empleado(db, 8) == {(2026, "Particular"): 0}


def test_upsert_guarda_dias_y_quien_cargo():
    db = FakeSession()
    upsert_saldos(db, 8, [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
    ], cargado_por=7)
    _sql, params = db.ejecutadas[-1]
    assert params[0]["empId"] == 8
    assert params[0]["anio"] == 2024
    assert params[0]["categoria"] == "Vacaciones"
    assert params[0]["diasPendientes"] == 5
    assert params[0]["cargadoPor"] == 7


def test_upsert_usa_merge_con_holdlock():
    """Sin HOLDLOCK, dos cargas concurrentes de la misma clave pueden entrar
    las dos por la rama NOT MATCHED y violar la unica."""
    db = FakeSession()
    upsert_saldos(db, 8, [
        {"anio": 2024, "categoria": "Vacaciones", "diasPendientes": 5},
    ], cargado_por=7)
    sql = db.sql_ejecutado()
    assert "MERGE" in sql
    assert "HOLDLOCK" in sql


def test_upsert_con_lista_vacia_no_toca_la_base():
    db = FakeSession()
    assert upsert_saldos(db, 8, [], cargado_por=7) == 0
    assert db.ejecutadas == []
    assert db.commits == 0
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_saldo_inicial_licencias.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.database.saldo_inicial_licencias'`

- [ ] **Step 3: Escribir la implementación**

Crear `app/database/saldo_inicial_licencias.py`:

```python
"""
Saldo de licencias pendiente al momento del alta de un empleado.

El saldo se calcula como dias que corresponden menos consumidos, y el consumo
sale solo de licencias que tramito este sistema. Un empleado cargado hoy no
tiene ninguna, asi que su consumo da cero y el sistema le muestra las
vacaciones completas de la ventana aunque ya se las haya tomado.

Esta tabla guarda lo que RRHH sabe del legajo: cuantos dias le quedan de cada
anio. Guarda el pendiente y no el consumo derivado porque para Vacaciones el
total se recalcula en cada consulta segun la antiguedad actual: el consumo
quedaria congelado mientras el total se mueve, y el saldo se desviaria solo al
cruzar un tramo de antiguedad.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('SaldoInicialLicencia', 'U') IS NULL
CREATE TABLE SaldoInicialLicencia (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    employeeId     INT           NOT NULL,
    anio           INT           NOT NULL,
    categoria      NVARCHAR(100) NOT NULL,
    diasPendientes INT           NOT NULL,
    cargadoPor     INT           NULL,
    cargadoEn      DATETIME2     NOT NULL,
    CONSTRAINT UQ_SaldoInicialLicencia_emp_anio_cat
        UNIQUE (employeeId, anio, categoria)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def saldos_de_empleado(db: Session, employee_id: int) -> dict[tuple[int, str], int]:
    """
    Lo cargado para un empleado, indexado por (anio, categoria).

    Que una clave NO aparezca significa "no se cargo nada", que es un estado
    distinto de "se cargo cero": la primera deja que rija el calculo normal
    del sistema, la segunda afirma que no le queda ningun dia.
    """
    filas = db.execute(
        text("""
            SELECT anio, categoria, diasPendientes
            FROM SaldoInicialLicencia
            WHERE employeeId = :empId
        """),
        {"empId": employee_id},
    ).mappings().all()
    return {(f["anio"], f["categoria"]): int(f["diasPendientes"]) for f in filas}


def upsert_saldos(
    db: Session,
    employee_id: int,
    filas: list[dict],
    cargado_por: int | None,
) -> int:
    """
    Guarda una tanda de saldos.

    Cada fila es {"anio", "categoria", "diasPendientes"}. Es MERGE y no INSERT
    porque corregir una carga equivocada es el caso normal y la clave
    (employeeId, anio, categoria) es unica; sin esto quedarian filas
    contradictorias para la misma celda.

    HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    simultaneas de la misma clave entrando las dos por NOT MATCHED.
    """
    if not filas:
        return 0

    db.execute(
        text("""
            MERGE SaldoInicialLicencia WITH (HOLDLOCK) AS destino
            USING (SELECT :empId AS employeeId,
                          :anio AS anio,
                          :categoria AS categoria) AS origen
                ON destino.employeeId = origen.employeeId
               AND destino.anio = origen.anio
               AND destino.categoria = origen.categoria
            WHEN MATCHED THEN
                UPDATE SET diasPendientes = :diasPendientes,
                           cargadoPor = :cargadoPor,
                           cargadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (employeeId, anio, categoria, diasPendientes,
                        cargadoPor, cargadoEn)
                VALUES (:empId, :anio, :categoria, :diasPendientes,
                        :cargadoPor, GETDATE());
        """),
        [
            {
                "empId": employee_id,
                "anio": f["anio"],
                "categoria": f["categoria"],
                "diasPendientes": f["diasPendientes"],
                "cargadoPor": cargado_por,
            }
            for f in filas
        ],
    )
    db.commit()
    return len(filas)
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_saldo_inicial_licencias.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add app/database/saldo_inicial_licencias.py tests/test_saldo_inicial_licencias.py
git commit -m "feat(licencias): tabla SaldoInicialLicencia y capa de datos"
```

---

### Task 2: Funciones puras de decision del saldo

**Files:**
- Create: `app/services/saldo_licencias.py`
- Test: `tests/test_saldo_licencias_service.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `total_del_anio(saldo_inicial: int | None, es_vacaciones: bool, dias_vac: int, dias_totales: int) -> int`
  - `saldos_sin_configuracion(saldos_iniciales: dict[tuple[int, str], int], cubiertas: set[tuple[int, str]]) -> list[tuple[int, str]]`
  - `anios_de_carga(anio_actual: int) -> list[int]`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_saldo_licencias_service.py`:

```python
"""
Decisiones puras del saldo de licencias, sin I/O.

Estas tres funciones concentran las reglas que antes vivian sueltas dentro
del endpoint de saldos, donde no se podian probar sin base.
"""

from app.services.saldo_licencias import (
    anios_de_carga,
    saldos_sin_configuracion,
    total_del_anio,
)


def test_saldo_inicial_manda_sobre_vacaciones():
    """Lo cargado a mano reemplaza al calculo por antiguedad. Si no lo hiciera,
    la carga inicial no tendria ningun efecto sobre vacaciones."""
    assert total_del_anio(5, es_vacaciones=True, dias_vac=20, dias_totales=30) == 5


def test_saldo_inicial_manda_sobre_las_demas():
    assert total_del_anio(3, es_vacaciones=False, dias_vac=20, dias_totales=30) == 3


def test_saldo_inicial_en_cero_manda_igual():
    """Cero cargado es 'no le queda nada'. Confundirlo con 'sin cargar' le
    otorgaria los dias completos, que es exactamente el bug que motivo todo."""
    assert total_del_anio(0, es_vacaciones=True, dias_vac=20, dias_totales=30) == 0


def test_sin_saldo_inicial_vacaciones_usa_la_antiguedad():
    assert total_del_anio(None, es_vacaciones=True, dias_vac=20, dias_totales=30) == 20


def test_sin_saldo_inicial_el_resto_usa_la_configuracion():
    assert total_del_anio(None, es_vacaciones=False, dias_vac=20, dias_totales=30) == 30


def test_saldos_sin_configuracion_devuelve_los_no_cubiertos():
    """El armado de saldos recorre ConfiguracionLicencias, y solo existe 2026:
    un saldo cargado para 2024 no apareceria nunca sin esto."""
    iniciales = {
        (2024, "Vacaciones"): 5,
        (2025, "Vacaciones"): 10,
        (2026, "Vacaciones"): 20,
    }
    cubiertas = {(2026, "Vacaciones")}
    assert saldos_sin_configuracion(iniciales, cubiertas) == [
        (2024, "Vacaciones"),
        (2025, "Vacaciones"),
    ]


def test_saldos_sin_configuracion_ordena_por_anio():
    """La pantalla los muestra en orden; que el orden lo fije esta funcion
    evita que dependa del orden de iteracion de un dict."""
    iniciales = {(2026, "Vacaciones"): 1, (2024, "Vacaciones"): 2}
    assert saldos_sin_configuracion(iniciales, set()) == [
        (2024, "Vacaciones"),
        (2026, "Vacaciones"),
    ]


def test_saldos_sin_configuracion_sin_faltantes_devuelve_vacio():
    iniciales = {(2026, "Vacaciones"): 20}
    assert saldos_sin_configuracion(iniciales, {(2026, "Vacaciones")}) == []


def test_anios_de_carga_son_el_actual_y_los_dos_previos():
    assert anios_de_carga(2026) == [2026, 2025, 2024]


def test_anios_de_carga_van_de_mas_nuevo_a_mas_viejo():
    """La pantalla los lista en ese orden y el mas relevante es el actual."""
    assert anios_de_carga(2030)[0] == 2030
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_saldo_licencias_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.saldo_licencias'`

- [ ] **Step 3: Escribir la implementación**

Crear `app/services/saldo_licencias.py`:

```python
"""
Decisiones del saldo de licencias. Funciones puras, sin I/O.

Concentran tres reglas que antes vivian sueltas dentro del endpoint de saldos:
que total rige para un anio, que saldos cargados no tienen configuracion que
los muestre, y cual es la ventana de anios cargables.
"""

# La ventana de carga: el anio calendario en curso y los dos anteriores.
# Coincide con el ciclo de expiracion de vacaciones; cargar algo mas viejo
# venceria en la primera corrida.
ANIOS_DE_VENTANA = 3


def total_del_anio(
    saldo_inicial: int | None,
    es_vacaciones: bool,
    dias_vac: int,
    dias_totales: int,
) -> int:
    """
    Cuantos dias corresponden para un anio y categoria.

    El saldo cargado a mano gana sobre todo lo demas, incluido el cero: cero
    es una afirmacion de RRHH de que no le queda nada, no la ausencia de dato.
    La ausencia de dato es None, y recien ahi rige el calculo del sistema.
    """
    if saldo_inicial is not None:
        return saldo_inicial
    return dias_vac if es_vacaciones else dias_totales


def saldos_sin_configuracion(
    saldos_iniciales: dict[tuple[int, str], int],
    cubiertas: set[tuple[int, str]],
) -> list[tuple[int, str]]:
    """
    Las claves con saldo cargado que la configuracion no llego a mostrar.

    El armado de saldos recorre ConfiguracionLicencias, que hoy solo tiene
    filas de 2026: sin esto, un saldo cargado para 2024 quedaria guardado y
    seria invisible.
    """
    return sorted(clave for clave in saldos_iniciales if clave not in cubiertas)


def anios_de_carga(anio_actual: int) -> list[int]:
    """La ventana cargable, del mas nuevo al mas viejo."""
    return [anio_actual - i for i in range(ANIOS_DE_VENTANA)]
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_saldo_licencias_service.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/saldo_licencias.py tests/test_saldo_licencias_service.py
git commit -m "feat(licencias): decisiones puras del saldo con saldo inicial"
```

---

### Task 3: Integrar el saldo inicial al calculo de saldos

**Files:**
- Modify: `app/routes/licenses.py` (imports; bloque de armado de respuesta en torno a las lineas 674-713; filtro por rol en la linea 692)
- Test: `tests/test_saldos_con_saldo_inicial.py`

**Interfaces:**
- Consumes: `saldos_de_empleado`, `ensure_table` de `app.database.saldo_inicial_licencias`; `total_del_anio`, `saldos_sin_configuracion` de `app.services.saldo_licencias`.
- Produces: `GET /licenses/saldos` devuelve filas cuyo `diasTotales` respeta el saldo inicial, e incluye filas de anios sin configuracion.

**Nota sobre el filtro por rol.** En la linea 661 el rol se pasa a minuscula (`.lower()`) y en la 692 se compara contra `["RRHH", "ADMIN"]` en mayuscula. La condicion es siempre verdadera, asi que las licencias restringidas estan ocultas para todos, RRHH incluido. Se corrige en esta task porque el catalogo de carga replica este mismo filtro y replicarlo roto haria imposible cargar esas categorias.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_saldos_con_saldo_inicial.py`:

```python
"""
El saldo inicial dentro del endpoint de saldos.

Se prueba la funcion pura de armado, que es donde vive la decision. El
endpoint completo depende de seis consultas encadenadas y probarlo entero
mediria el andamiaje, no la regla.
"""

from app.routes.licenses import armar_balances


FILAS_CONFIG = [
    {"anio": 2026, "tipoLicencia": "Vacaciones", "contrato": "permanente",
     "diasTotales": 30, "diasConsumidos": 0},
]


def test_sin_saldo_inicial_vacaciones_usa_la_antiguedad():
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["diasTotales"] == 20
    assert balances[0]["disponibles"] == 20


def test_el_saldo_inicial_reemplaza_al_total():
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={(2026, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["diasTotales"] == 5
    assert balances[0]["disponibles"] == 5


def test_el_consumo_posterior_descuenta_del_saldo_inicial():
    """Cargado el saldo, el circuito comun sigue funcionando encima."""
    filas = [dict(FILAS_CONFIG[0], diasConsumidos=2)]
    balances = armar_balances(
        rows=filas, saldos_iniciales={(2026, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["disponibles"] == 3


def test_saldo_inicial_en_cero_no_otorga_dias():
    """Es el bug que motivo el trabajo: un cero leido como 'sin dato' le
    devolveria las vacaciones completas."""
    balances = armar_balances(
        rows=FILAS_CONFIG, saldos_iniciales={(2026, "Vacaciones"): 0},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    assert balances[0]["disponibles"] == 0


def test_un_anio_sin_configuracion_aparece_si_tiene_saldo_cargado():
    """Solo existe configuracion de 2026: sin esto el saldo de 2024 quedaria
    guardado y seria invisible."""
    balances = armar_balances(
        rows=FILAS_CONFIG,
        saldos_iniciales={(2026, "Vacaciones"): 20, (2024, "Vacaciones"): 5},
        dias_vac=20, gender="Masculino", role_name="rrhh",
    )
    anios = {b["anio"] for b in balances}
    assert anios == {2024, 2026}
    fila_2024 = next(b for b in balances if b["anio"] == 2024)
    assert fila_2024["diasTotales"] == 5
    assert fila_2024["disponibles"] == 5


def test_nacimiento_no_se_le_ofrece_a_una_empleada():
    filas = [{"anio": 2026, "tipoLicencia": "Nacimiento", "contrato": "permanente",
              "diasTotales": 5, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Femenino", role_name="rrhh",
    )
    assert balances == []


def test_embarazo_no_se_le_ofrece_a_un_empleado():
    filas = [{"anio": 2026, "tipoLicencia": "Embarazo", "contrato": "permanente",
              "diasTotales": 90, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert balances == []


def test_las_licencias_restringidas_se_le_muestran_a_rrhh():
    """El rol llega en minuscula y se comparaba contra mayuscula, asi que la
    condicion era siempre verdadera y estas licencias estaban ocultas para
    todos, RRHH incluido."""
    filas = [{"anio": 2026, "tipoLicencia": "Accidente de trabajo",
              "contrato": "permanente", "diasTotales": 30, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="rrhh",
    )
    assert len(balances) == 1


def test_las_licencias_restringidas_no_se_le_muestran_a_un_empleado_comun():
    filas = [{"anio": 2026, "tipoLicencia": "Accidente de trabajo",
              "contrato": "permanente", "diasTotales": 30, "diasConsumidos": 0}]
    balances = armar_balances(
        rows=filas, saldos_iniciales={}, dias_vac=20,
        gender="Masculino", role_name="user",
    )
    assert balances == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_saldos_con_saldo_inicial.py -v`
Expected: FAIL con `ImportError: cannot import name 'armar_balances' from 'app.routes.licenses'`

- [ ] **Step 3: Agregar los imports en `app/routes/licenses.py`**

Sumar al bloque de imports del principio del archivo:

```python
from app.database.saldo_inicial_licencias import (
    ensure_table as ensure_saldo_inicial,
    saldos_de_empleado,
)
from app.services.saldo_licencias import saldos_sin_configuracion, total_del_anio
```

- [ ] **Step 4: Extraer `armar_balances` como funcion pura**

Insertar esta funcion en `app/routes/licenses.py`, inmediatamente antes de `def get_license_saldos(`:

```python
# Categorias que solo ve RRHH: son las de encuadre medico y las excepcionales,
# que no se solicitan por el circuito comun.
RRHH_ONLY_TYPES = [
    "lesiones de largo tratamiento",
    "lar",
    "accidente de trabajo",
    "enfermedad profesional",
    "enfermedad de miembros del grupo",
    "lic por enfermedad",
    "licencia sin goce de haberes",
    "fallecimiento en parto",
]

ROLES_CON_LICENCIAS_RESTRINGIDAS = {"rrhh", "admin"}


def armar_balances(
    rows: list[dict],
    saldos_iniciales: dict[tuple[int, str], int],
    dias_vac: int,
    gender: str | None,
    role_name: str,
) -> list[dict]:
    """
    Arma la respuesta de saldos a partir de la configuracion y lo cargado.

    Es funcion pura para poder probar las reglas sin base: el endpoint que la
    llama encadena seis consultas y probarlo entero mediria el andamiaje.

    role_name llega en minuscula. La comparacion tambien esta en minuscula: la
    version anterior comparaba contra ["RRHH", "ADMIN"] en mayuscula, con lo
    cual la condicion era siempre verdadera y las licencias restringidas
    quedaban ocultas para todos, RRHH incluido.
    """
    balances = []
    cubiertas: set[tuple[int, str]] = set()

    for row in rows:
        tipo_lower = row["tipoLicencia"].lower()

        if "nacimiento" in tipo_lower and gender != "Masculino":
            continue
        if "embarazo" in tipo_lower and gender != "Femenino":
            continue
        if any(t in tipo_lower for t in RRHH_ONLY_TYPES):
            if role_name not in ROLES_CON_LICENCIAS_RESTRINGIDAS:
                continue

        clave = (row["anio"], row["tipoLicencia"])
        cubiertas.add(clave)

        totales = total_del_anio(
            saldo_inicial=saldos_iniciales.get(clave),
            es_vacaciones=tipo_lower == "vacaciones",
            dias_vac=dias_vac,
            dias_totales=row["diasTotales"],
        )
        consumidos = row["diasConsumidos"]

        balances.append({
            "anio": row["anio"],
            "tipo": row["tipoLicencia"],
            "contrato": row["contrato"],
            "diasTotales": totales,
            "consumidos": consumidos,
            "disponibles": max(0, totales - consumidos),
        })

    # Un anio sin fila de configuracion no aparece en rows. Como solo existe
    # configuracion de 2026, sin esto todo saldo cargado para un anio anterior
    # quedaria guardado y seria invisible.
    contrato = rows[0]["contrato"] if rows else None
    for anio, categoria in saldos_sin_configuracion(saldos_iniciales, cubiertas):
        dias = saldos_iniciales[(anio, categoria)]
        balances.append({
            "anio": anio,
            "tipo": categoria,
            "contrato": contrato,
            "diasTotales": dias,
            "consumidos": 0,
            "disponibles": dias,
        })

    return balances
```

- [ ] **Step 5: Reemplazar el armado inline por la llamada**

En `get_license_saldos`, borrar el bloque que va desde `rrhh_only_types = [` (linea ~663) hasta el `return {"balances": balances}` (linea ~713) y dejar en su lugar:

```python
    ensure_saldo_inicial(db)
    saldos_iniciales = saldos_de_empleado(db, employee_id)

    dias_vac = calcular_dias_vacaciones(
        tipo_contrato, fecha_ingreso, cl.get("fechaJubilacion"),
    )

    return {"balances": armar_balances(
        rows=[dict(r) for r in rows],
        saldos_iniciales=saldos_iniciales,
        dias_vac=dias_vac,
        gender=gender,
        role_name=role_name,
    )}
```

- [ ] **Step 6: Hacer que la expiracion respete el saldo inicial**

En el bloque de expiracion, reemplazar la linea que calcula el remanente:

```python
    if exp and (exp["totales"] - exp["consumidos"]) > 0:
        remanente = exp["totales"] - exp["consumidos"]
```

por:

```python
    # Si hay saldo cargado a mano para el anio que vence, ese es el total que
    # corresponde: sin esto un saldo cargado quedaria inmortal, porque la
    # configuracion de ese anio no existe y totales daria cero.
    saldos_previos = saldos_de_empleado(db, employee_id)
    total_a_vencer = saldos_previos.get(
        (expire_anio, "Vacaciones"), exp["totales"] if exp else 0
    )
    if exp and (total_a_vencer - exp["consumidos"]) > 0:
        remanente = total_a_vencer - exp["consumidos"]
```

Y mover `ensure_saldo_inicial(db)` para que quede antes de este bloque, justo despues de leer la condicion laboral.

- [ ] **Step 7: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_saldos_con_saldo_inicial.py -v`
Expected: PASS, 9 tests

- [ ] **Step 8: Correr la suite de licencias para descartar regresiones**

Run: `py -m pytest tests/ -q -k "licen or saldo"`
Expected: PASS, sin fallos

- [ ] **Step 9: Commit**

```bash
git add app/routes/licenses.py tests/test_saldos_con_saldo_inicial.py
git commit -m "feat(licencias): el saldo inicial manda sobre el total del anio"
```

---

### Task 4: Permiso y endpoints de carga inicial

**Files:**
- Modify: `app/permisos.py`
- Create: `app/routes/carga_inicial_licencias.py`
- Modify: `app/main.py`
- Test: `tests/test_carga_inicial_endpoints.py`

**Interfaces:**
- Consumes: `ensure_table`, `saldos_de_empleado`, `upsert_saldos` de `app.database.saldo_inicial_licencias`; `anios_de_carga` de `app.services.saldo_licencias`; `armar_catalogo_carga` se define aca.
- Produces:
  - `GET /licenses/carga-inicial/{employee_id}` → `{"acumulables": [...], "anuales": [...]}`
  - `PUT /licenses/carga-inicial/{employee_id}` → `{"guardados": int}`
  - `armar_catalogo_carga(categorias, saldos, anio_actual, gender, role_name) -> dict`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_carga_inicial_endpoints.py`:

```python
"""
Catalogo y guardado de la carga inicial de saldos.

El catalogo es funcion pura: recibe las categorias configuradas y lo ya
cargado, y decide que se le ofrece a ese empleado.
"""

import pytest
from fastapi import HTTPException

from app.routes.carga_inicial_licencias import (
    SaldoCargado,
    CargaInicialRequest,
    armar_catalogo_carga,
    guardar_carga_inicial,
)
from tests.fakes import FakeSession

CATEGORIAS = ["Vacaciones", "Particular", "Nacimiento", "Accidente de trabajo"]


def test_vacaciones_va_a_acumulables_con_tres_anios():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert [f["anio"] for f in cat["acumulables"]] == [2026, 2025, 2024]
    assert all(f["categoria"] == "Vacaciones" for f in cat["acumulables"])


def test_las_demas_van_a_anuales_solo_con_el_anio_actual():
    cat = armar_catalogo_carga(
        categorias=["Particular"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert [f["anio"] for f in cat["anuales"]] == [2026]
    assert cat["acumulables"] == []


def test_devuelve_el_valor_ya_cargado():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={(2024, "Vacaciones"): 5},
        anio_actual=2026, gender="Masculino", role_name="rrhh",
    )
    fila = next(f for f in cat["acumulables"] if f["anio"] == 2024)
    assert fila["diasPendientes"] == 5


def test_lo_no_cargado_viene_en_none_y_no_en_cero():
    """None es 'no se cargo'; cero es 'no le queda nada'. La pantalla los
    muestra distinto y el backend no puede aplastarlos."""
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert all(f["diasPendientes"] is None for f in cat["acumulables"])


def test_el_cero_cargado_se_conserva():
    cat = armar_catalogo_carga(
        categorias=["Vacaciones"], saldos={(2026, "Vacaciones"): 0},
        anio_actual=2026, gender="Masculino", role_name="rrhh",
    )
    fila = next(f for f in cat["acumulables"] if f["anio"] == 2026)
    assert fila["diasPendientes"] == 0


def test_no_ofrece_nacimiento_a_una_empleada():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Femenino", role_name="rrhh",
    )
    assert all(f["categoria"] != "Nacimiento" for f in cat["anuales"])


def test_no_ofrece_restringidas_a_un_rol_comun():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Masculino", role_name="user",
    )
    assert all(f["categoria"] != "Accidente de trabajo" for f in cat["anuales"])


def test_ofrece_restringidas_a_rrhh():
    cat = armar_catalogo_carga(
        categorias=CATEGORIAS, saldos={}, anio_actual=2026,
        gender="Masculino", role_name="rrhh",
    )
    assert any(f["categoria"] == "Accidente de trabajo" for f in cat["anuales"])


def test_guardar_rechaza_dias_negativos():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Vacaciones", diasPendientes=-1),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_rechaza_un_anio_fuera_de_la_ventana():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2019, categoria="Vacaciones", diasPendientes=5),
    ])
    with pytest.raises(HTTPException) as e:
        guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    assert e.value.status_code == 400


def test_guardar_registra_quien_cargo():
    db = FakeSession()
    payload = CargaInicialRequest(saldos=[
        SaldoCargado(anio=2026, categoria="Vacaciones", diasPendientes=5),
    ])
    guardar_carga_inicial(8, payload, db, {"employeeId": 7})
    _sql, params = db.ejecutadas[-1]
    assert params[0]["cargadoPor"] == 7
    assert params[0]["empId"] == 8


def test_el_payload_no_puede_declarar_quien_cargo():
    """El id de quien carga sale del token. Si el request pudiera declararlo,
    cualquiera podria firmar la carga con el legajo de otro."""
    campos = set(CargaInicialRequest.model_fields) | set(SaldoCargado.model_fields)
    assert "cargadoPor" not in campos
    assert "employeeId" not in campos
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_carga_inicial_endpoints.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.routes.carga_inicial_licencias'`

- [ ] **Step 3: Sumar el permiso en `app/permisos.py`**

Agregar `"licencias.cargaInicial",` al `frozenset` `PERMISOS`, inmediatamente despues de `"licencias.configurar",`:

```python
    "licencias.propias",
    "licencias.configurar",
    "licencias.cargaInicial",
```

Agregar su descripcion al dict `DESCRIPCIONES`, despues de la de `licencias.configurar`:

```python
    "licencias.configurar": "Configurar tipos de licencia, topes y feriados",
    "licencias.cargaInicial": "Cargar saldos de licencias previos al alta (transitorio)",
```

No se agrega a `PERMISOS_POR_ROL`: el permiso se asigna a mano desde la UI de roles mientras dure la migracion, y quitarlo apaga la pestaña sin redeploy.

- [ ] **Step 4: Escribir el router**

Crear `app/routes/carga_inicial_licencias.py`:

```python
"""
Carga inicial de saldos de licencias. TRANSITORIO.

Existe para poblar el saldo pendiente de los empleados que ya venian
trabajando cuando el sistema se puso en marcha: sin esto su consumo da cero y
el sistema les otorga de nuevo vacaciones que ya se tomaron.

Vive en su propio archivo a proposito. Cuando termine la migracion se le quita
el permiso licencias.cargaInicial al rol -- con eso la pestaña desaparece sin
redeploy -- y despues se borra este archivo y su linea en main.py, sin tener
que operar dentro de licenses.py.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.database import SessionLocal
from app.database.saldo_inicial_licencias import (
    ensure_table,
    saldos_de_empleado,
    upsert_saldos,
)
from app.routes.licenses import (
    ROLES_CON_LICENCIAS_RESTRINGIDAS,
    RRHH_ONLY_TYPES,
)
from app.services.saldo_licencias import anios_de_carga

router = APIRouter(prefix="/licenses/carga-inicial", tags=["Carga inicial licencias"])

# Unica categoria que se arrastra de un anio a otro. El resto se consume
# dentro del anio, asi que cargarle anios viejos no tendria efecto.
CATEGORIA_ACUMULABLE = "Vacaciones"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SaldoCargado(BaseModel):
    anio: int
    categoria: str
    diasPendientes: int


class CargaInicialRequest(BaseModel):
    saldos: list[SaldoCargado]


def _le_aplica(categoria: str, gender: str | None, role_name: str) -> bool:
    """Mismos filtros que el saldo: no se ofrece cargar lo que nunca se vera."""
    tipo_lower = categoria.lower()
    if "nacimiento" in tipo_lower and gender != "Masculino":
        return False
    if "embarazo" in tipo_lower and gender != "Femenino":
        return False
    if any(t in tipo_lower for t in RRHH_ONLY_TYPES):
        return role_name in ROLES_CON_LICENCIAS_RESTRINGIDAS
    return True


def armar_catalogo_carga(
    categorias: list[str],
    saldos: dict[tuple[int, str], int],
    anio_actual: int,
    gender: str | None,
    role_name: str,
) -> dict:
    """
    Que se le ofrece cargar a este empleado, partido en dos bloques.

    diasPendientes viene en None cuando no se cargo nada y en 0 cuando se
    cargo un cero: son estados distintos y la pantalla los muestra distinto.
    """
    acumulables = []
    anuales = []

    for categoria in categorias:
        if not _le_aplica(categoria, gender, role_name):
            continue

        if categoria == CATEGORIA_ACUMULABLE:
            for anio in anios_de_carga(anio_actual):
                acumulables.append({
                    "anio": anio,
                    "categoria": categoria,
                    "diasPendientes": saldos.get((anio, categoria)),
                })
        else:
            anuales.append({
                "anio": anio_actual,
                "categoria": categoria,
                "diasPendientes": saldos.get((anio_actual, categoria)),
            })

    return {"acumulables": acumulables, "anuales": anuales}


@router.get("/{employee_id}")
def get_carga_inicial(
    employee_id: int,
    db: Session = Depends(get_db),
    _user: dict = Depends(require_permission("licencias.cargaInicial")),
):
    """Catalogo de lo que se le puede cargar, con lo ya cargado."""
    ensure_table(db)

    emp = db.execute(
        text("""
            SELECT e.gender, r.name AS roleName
            FROM Employee e
            INNER JOIN [User] u ON u.employeeId = e.id
            INNER JOIN Role r ON u.roleId = r.id
            WHERE e.id = :empId
        """),
        {"empId": employee_id},
    ).mappings().first()

    if not emp:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    anio_actual = date.today().year

    categorias = [
        f["categoria"]
        for f in db.execute(
            text("""
                SELECT DISTINCT categoria
                FROM ConfiguracionLicencias
                ORDER BY categoria
            """)
        ).mappings().all()
    ]

    return armar_catalogo_carga(
        categorias=categorias,
        saldos=saldos_de_empleado(db, employee_id),
        anio_actual=anio_actual,
        gender=emp["gender"],
        role_name=(emp["roleName"] or "").lower(),
    )


@router.put("/{employee_id}")
def guardar_carga_inicial(
    employee_id: int,
    payload: CargaInicialRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("licencias.cargaInicial")),
):
    """
    Guarda una tanda de saldos.

    El id de quien carga sale del token y no del payload: esto mueve dias que
    se convierten en licencia paga, y la firma tiene que ser de quien
    efectivamente la hizo.
    """
    ensure_table(db)

    ventana = set(anios_de_carga(date.today().year))
    for s in payload.saldos:
        if s.diasPendientes < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Los dias de {s.categoria} {s.anio} no pueden ser negativos",
            )
        if s.anio not in ventana:
            raise HTTPException(
                status_code=400,
                detail=f"El anio {s.anio} esta fuera de la ventana de carga {sorted(ventana)}",
            )

    guardados = upsert_saldos(
        db,
        employee_id,
        [s.model_dump() for s in payload.saldos],
        cargado_por=user.get("employeeId"),
    )
    return {"guardados": guardados}
```

- [ ] **Step 5: Registrar el router en `app/main.py`**

Sumar `carga_inicial_licencias` a la lista de imports de `app.routes` y agregar, junto a los demas `include_router`:

```python
app.include_router(carga_inicial_licencias.router)
```

- [ ] **Step 6: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_carga_inicial_endpoints.py -v`
Expected: PASS, 12 tests

- [ ] **Step 7: Commit**

```bash
git add app/permisos.py app/routes/carga_inicial_licencias.py app/main.py tests/test_carga_inicial_endpoints.py
git commit -m "feat(licencias): endpoints de carga inicial de saldos"
```

---

### Task 5: Corregir los tres defectos de /licenses/aplicar

**Files:**
- Modify: `app/routes/licenses.py` (`rrhh_apply_license`, lineas ~954-1000)
- Test: `tests/test_aplicar_licencia.py`

**Interfaces:**
- Consumes: nada de tasks previas.
- Produces: `resolver_licencia(candidatas, license_id_pedido) -> dict` — funcion pura que decide cual licencia se aplica o corta.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_aplicar_licencia.py`:

```python
"""
Los tres defectos de /licenses/aplicar.

Los tres tenian el mismo efecto: descontarle dias a quien no corresponde.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import resolver_licencia

LIC_A = {"id": 1, "employeeId": 10, "type": "Vacaciones"}
LIC_B = {"id": 2, "employeeId": 20, "type": "Vacaciones"}


def test_una_sola_candidata_se_aplica():
    assert resolver_licencia([LIC_A], None)["id"] == 1


def test_dos_candidatas_cortan_en_vez_de_elegir():
    """Dos personas tomandose la misma semana es habitual. Antes elegia la
    primera en silencio y le aprobaba la licencia al empleado equivocado."""
    with pytest.raises(HTTPException) as e:
        resolver_licencia([LIC_A, LIC_B], None)
    assert e.value.status_code == 409


def test_el_license_id_pedido_desempata():
    """Con el id explicito no hay ambiguedad posible."""
    assert resolver_licencia([LIC_A, LIC_B], 2)["id"] == 2


def test_un_license_id_que_no_esta_entre_las_candidatas_corta():
    with pytest.raises(HTTPException) as e:
        resolver_licencia([LIC_A, LIC_B], 99)
    assert e.value.status_code == 404


def test_sin_candidatas_corta_en_vez_de_crear():
    """Antes creaba la licencia con el employeeId del payload, que es el del
    mensaje y por lo tanto el del supervisor: le descontaba los dias a el."""
    with pytest.raises(HTTPException) as e:
        resolver_licencia([], None)
    assert e.value.status_code == 404


def test_el_tipo_sale_de_la_licencia_y_no_del_payload():
    """El frontend manda type 'Vacaciones' fijo: una licencia por Nacimiento
    aprobada desde ese panel descontaba dias de vacaciones."""
    lic = resolver_licencia([{"id": 3, "employeeId": 10, "type": "Nacimiento"}], None)
    assert lic["type"] == "Nacimiento"
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_aplicar_licencia.py -v`
Expected: FAIL con `ImportError: cannot import name 'resolver_licencia' from 'app.routes.licenses'`

- [ ] **Step 3: Escribir `resolver_licencia`**

Insertar en `app/routes/licenses.py`, inmediatamente antes de `def rrhh_apply_license(`:

```python
def resolver_licencia(candidatas: list[dict], license_id_pedido: int | None) -> dict:
    """
    Decide que licencia se aplica, o corta.

    Antes se hacia SELECT TOP 1 por fechas sin filtrar por empleado y se
    tomaba la primera. Dos personas que se toman la misma semana -- habitual
    -- y aprobaba la del otro, descontandole los dias a quien no correspondia.

    Ahora: si viene el id explicito manda ese; si no, el match tiene que ser
    inequivoco. Ante la duda no elige.
    """
    if license_id_pedido is not None:
        for lic in candidatas:
            if lic["id"] == license_id_pedido:
                return lic
        raise HTTPException(
            status_code=404,
            detail=f"No se encontro la licencia {license_id_pedido} para esas fechas",
        )

    if not candidatas:
        raise HTTPException(
            status_code=404,
            detail=(
                "No se encontro una solicitud para esas fechas. Toda solicitud "
                "crea su licencia, asi que revisar el listado de solicitudes "
                "antes de reintentar."
            ),
        )

    if len(candidatas) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Hay {len(candidatas)} licencias con esas fechas. Aplicarla "
                "desde el listado de solicitudes, que identifica cual es."
            ),
        )

    return candidatas[0]
```

- [ ] **Step 4: Usar `resolver_licencia` dentro de `rrhh_apply_license`**

Reemplazar el bloque que va desde `# ── Paso 1: Buscar la License REAL por fechas` hasta el cierre del `else` que hacia el INSERT (lineas ~955-985) por:

```python
        # ── Paso 1: Identificar la licencia, sin adivinar ──
        # Se acota a las que todavia no estan aprobadas: una ya aplicada no es
        # candidata, y eso solo ya desambigua la mayoria de los casos.
        candidatas = [dict(f) for f in db.execute(text("""
            SELECT id, employeeId, type FROM License
            WHERE startDate = :start AND endDate = :end
              AND status <> 'Aprobada'
            ORDER BY createdAt DESC
        """), {"start": start_date, "end": end_date}).mappings().all()]

        lic = resolver_licencia(candidatas, data.get("licenseId"))
        license_id = lic["id"]
        real_employee_id = lic["employeeId"]
        # El tipo sale de la licencia y no del payload: el frontend manda
        # "Vacaciones" fijo, con lo cual una licencia por Nacimiento aprobada
        # desde ese panel descontaba dias del cupo de vacaciones.
        lic_type = lic["type"]

        db.execute(text("""
            UPDATE License SET status = 'Aprobada', updatedAt = GETDATE() WHERE id = :id
        """), {"id": license_id})
```

- [ ] **Step 5: Sacar el `type` del payload de la lectura inicial**

En la lectura de campos del principio de la funcion, borrar la linea:

```python
    lic_type = data.get("type", "Vacaciones")
```

El tipo ahora sale siempre de la licencia encontrada.

- [ ] **Step 6: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_aplicar_licencia.py -v`
Expected: PASS, 6 tests

- [ ] **Step 7: Correr la suite completa de licencias**

Run: `py -m pytest tests/ -q -k "licen or saldo or aplicar"`
Expected: PASS, sin fallos

- [ ] **Step 8: Commit**

```bash
git add app/routes/licenses.py tests/test_aplicar_licencia.py
git commit -m "fix(licencias): aplicar deja de adivinar la licencia y el tipo"
```

---

### Task 6: Pestaña de carga inicial en el legajo

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts`
- Create: `src/app/Componentes/TablaOperador/CargaInicialLicenciasTab.tsx`
- Modify: `src/app/Componentes/TablaOperador/Perfildetail.tsx`

Repositorio: `C:\Users\Emiliano\Documents\RRHH`

**Interfaces:**
- Consumes: `GET /licenses/carga-inicial/{employee_id}` → `{acumulables, anuales}` con filas `{anio, categoria, diasPendientes}` donde `diasPendientes` es `number | null`; `PUT /licenses/carga-inicial/{employee_id}` con body `{saldos: [{anio, categoria, diasPendientes}]}`.
- Produces: `<CargaInicialLicenciasTab employee={employee} />`

- [ ] **Step 1: Agregar los tipos en `src/app/Interfas/Interfaces.ts`**

```typescript
/** Una celda de la carga inicial de saldos de licencias. TRANSITORIO:
 *  se borra junto con la pestaña al terminar la migracion. */
export interface SaldoCargaInicial {
  anio: number;
  categoria: string;
  /** null = no se cargo nada (rige el calculo del sistema).
   *  0 = se cargo un cero (no le queda ningun dia). Son distintos. */
  diasPendientes: number | null;
}

export interface CatalogoCargaInicial {
  acumulables: SaldoCargaInicial[];
  anuales: SaldoCargaInicial[];
}
```

- [ ] **Step 2: Escribir el componente**

Crear `src/app/Componentes/TablaOperador/CargaInicialLicenciasTab.tsx`:

```tsx
"use client";

// Carga inicial de saldos de licencias. TRANSITORIO.
//
// Existe para poblar el saldo de los empleados que ya venian trabajando
// cuando el sistema arranco: sin esto su consumo da cero y el sistema les
// otorga de nuevo vacaciones que ya se tomaron.
//
// Se borra junto con el router del backend cuando termine la migracion. Hasta
// entonces se apaga quitandole el permiso licencias.cargaInicial al rol.

import { useCallback, useEffect, useState } from "react";
import { Save, TriangleAlert } from "lucide-react";
import { apiClient } from "@/app/util/apiClient";
import type {
  CatalogoCargaInicial,
  Employee,
  SaldoCargaInicial,
} from "@/app/Interfas/Interfaces";

const clave = (f: { anio: number; categoria: string }) => `${f.anio}|${f.categoria}`;

export const CargaInicialLicenciasTab = ({ employee }: { employee: Employee }) => {
  const [catalogo, setCatalogo] = useState<CatalogoCargaInicial | null>(null);
  const [cambios, setCambios] = useState<Map<string, number | null>>(new Map());
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guardado, setGuardado] = useState(false);

  const traer = useCallback(() => {
    setCargando(true);
    apiClient
      .get<CatalogoCargaInicial>(`/licenses/carga-inicial/${employee.id}`)
      .then((c) => {
        setCatalogo(c);
        setCambios(new Map());
        setError(null);
      })
      .catch((e) => setError(e.message ?? "No se pudo cargar el catalogo"))
      .finally(() => setCargando(false));
  }, [employee.id]);

  useEffect(() => { traer(); }, [traer]);

  const editar = (fila: SaldoCargaInicial, crudo: string) => {
    setGuardado(false);
    const siguiente = new Map(cambios);
    // Vacio y cero son distintos: vacio deja que rija el calculo del sistema,
    // cero afirma que no le queda ningun dia.
    siguiente.set(clave(fila), crudo.trim() === "" ? null : Number(crudo));
    setCambios(siguiente);
  };

  const valorDe = (fila: SaldoCargaInicial): string => {
    const k = clave(fila);
    const v = cambios.has(k) ? cambios.get(k)! : fila.diasPendientes;
    return v === null || v === undefined ? "" : String(v);
  };

  const guardar = async () => {
    const saldos = Array.from(cambios.entries())
      .filter(([, dias]) => dias !== null)
      .map(([k, dias]) => {
        const [anio, categoria] = k.split("|");
        return { anio: Number(anio), categoria, diasPendientes: dias as number };
      });

    if (saldos.length === 0) return;

    setGuardando(true);
    setError(null);
    try {
      await apiClient.put(`/licenses/carga-inicial/${employee.id}`, { saldos });
      setGuardado(true);
      traer();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  if (cargando) {
    return <div className="p-6 text-center text-muted-foreground">Cargando saldos...</div>;
  }

  if (error && !catalogo) {
    return <div className="p-6 text-center text-error">{error}</div>;
  }

  if (!catalogo) return null;

  const Bloque = ({ titulo, ayuda, filas }: {
    titulo: string; ayuda: string; filas: SaldoCargaInicial[];
  }) => (
    <div className="bg-card border border-border rounded-lg p-4">
      <h3 className="font-heading font-semibold text-foreground">{titulo}</h3>
      <p className="text-xs text-muted-foreground mb-3">{ayuda}</p>
      {filas.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">
          No hay licencias de este tipo para este empleado.
        </p>
      ) : (
        <div className="space-y-2">
          {filas.map((f) => (
            <div key={clave(f)} className="grid grid-cols-[1fr_5rem_6rem] gap-3 items-center">
              <span className="text-sm text-foreground">{f.categoria}</span>
              <span className="text-sm text-muted-foreground tabular-nums">{f.anio}</span>
              <input
                type="number"
                min={0}
                inputMode="numeric"
                placeholder="—"
                value={valorDe(f)}
                onChange={(e) => editar(f, e.target.value)}
                className="w-full rounded border border-border bg-background px-2 py-1 text-sm text-foreground text-right tabular-nums"
                aria-label={`Dias pendientes de ${f.categoria} ${f.anio}`}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="rounded-xl border-l-4 border-warning bg-warning-soft p-4">
        <div className="flex gap-3">
          <TriangleAlert className="text-warning shrink-0 mt-0.5" size={18} aria-hidden="true" />
          <p className="text-sm text-warning-soft-foreground">
            <strong>Carga inicial, por unica vez.</strong> Se cargan los dias que
            al empleado <strong>le quedan por tomarse</strong>, no los que ya se
            tomo. Dejar un casillero vacio significa no cargar nada y que rija el
            calculo del sistema; escribir <strong>0</strong> significa que no le
            queda ningun dia.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Bloque
          titulo="Se arrastran de años anteriores"
          ayuda="Las vacaciones se acumulan y vencen a los 3 años. Cargar el saldo de cada año por separado."
          filas={catalogo.acumulables}
        />
        <Bloque
          titulo="Solo del año en curso"
          ayuda="Estas licencias no se arrastran: lo que no se usa en el año no pasa al siguiente."
          filas={catalogo.anuales}
        />
      </div>

      {error && <p className="text-sm text-error">{error}</p>}
      {guardado && <p className="text-sm text-success">Saldos guardados.</p>}

      <button
        onClick={guardar}
        disabled={guardando || cambios.size === 0}
        className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        <Save size={16} />
        {guardando ? "Guardando..." : "Guardar saldos"}
      </button>
    </div>
  );
};
```

- [ ] **Step 3: Sumar la pestaña en `Perfildetail.tsx`**

Agregar los imports al principio del archivo:

```tsx
import { CargaInicialLicenciasTab } from "./CargaInicialLicenciasTab";
import { leerPermisos, tienePermiso } from "@/app/util/permisos";
```

Dentro del componente, junto al `useState` de `activeTab`:

```tsx
  // Pestaña transitoria: se apaga quitandole el permiso al rol, sin redeploy.
  const puedeCargarSaldos = tienePermiso(leerPermisos(), "licencias.cargaInicial");
```

Agregar el boton de pestaña despues del de "Alertas de tolerancia":

```tsx
          {puedeCargarSaldos && (
            <button
              onClick={() => setActiveTab("cargaInicial")}
              className={`${
                activeTab === "cargaInicial"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              Carga inicial de saldos
            </button>
          )}
```

Y su render, junto a los demas:

```tsx
        {activeTab === "cargaInicial" && puedeCargarSaldos && (
          <CargaInicialLicenciasTab employee={employee} />
        )}
```

- [ ] **Step 4: Verificar que TypeScript no suma errores**

Run: `npx tsc --noEmit 2>&1 | Select-String "error TS" | Measure-Object | Select-Object -ExpandProperty Count`
Expected: `27` (el baseline del repositorio; no debe subir)

- [ ] **Step 5: Commit**

```bash
git add src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/CargaInicialLicenciasTab.tsx src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "feat(licencias): pestaña transitoria de carga inicial de saldos"
```

---

### Task 7: Documento de ayuda de licencias

**Files:**
- Create: `src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx`
- Modify: `src/app/screens/LicenciasManage/Screen.tsx`

Repositorio: `C:\Users\Emiliano\Documents\RRHH`

**Interfaces:**
- Consumes: `GET /licenses/configuracion` → `{configuraciones: [{categoria, tipo, anio, diasTotales}]}` para listar los dias en vivo.
- Produces: `<ComoFuncionanLicenciasModal onClose={...} />`

- [ ] **Step 1: Escribir el modal**

Crear `src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx`:

```tsx
"use client";

// Guia de licencias para empleados y autoridades.
// Explica el mecanismo -- lo verificable contra el codigo -- y no el encuadre
// normativo, que no vive en este sistema. Los dias de cada tipo se leen de la
// configuracion en vivo para que el documento no quede desactualizado cuando
// RRHH cambia un tope.

import { useEffect, useState } from "react";
import { X, CalendarDays, Clock, ShieldCheck, Info, AlertTriangle } from "lucide-react";
import { apiClient } from "@/app/util/apiClient";

interface ConfigLicencia {
  categoria: string;
  diasTotales: number;
}

interface Props {
  onClose: () => void;
}

export function ComoFuncionanLicenciasModal({ onClose }: Props) {
  const [tipos, setTipos] = useState<ConfigLicencia[]>([]);

  useEffect(() => {
    apiClient
      .get<{ configuraciones: ConfigLicencia[] }>("/licenses/configuracion")
      .then((r) => {
        const vistas = new Map<string, number>();
        for (const c of r.configuraciones ?? []) {
          if (!vistas.has(c.categoria)) vistas.set(c.categoria, c.diasTotales);
        }
        setTipos([...vistas].map(([categoria, diasTotales]) => ({ categoria, diasTotales })));
      })
      .catch(() => setTipos([]));
  }, []);

  return (
    <div
      className="fixed inset-0 bg-overlay flex justify-center items-start z-50 p-4 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="licencias-guia-titulo"
    >
      <div
        className="bg-card rounded-2xl shadow-2xl w-full max-w-3xl my-8 relative border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Cerrar"
        >
          <X size={22} />
        </button>

        <div className="p-6 sm:p-8">
          <p className="font-mono text-xs tracking-widest uppercase text-muted-foreground mb-2">
            Guía de uso
          </p>
          <h2
            id="licencias-guia-titulo"
            className="font-heading text-2xl sm:text-3xl font-bold text-foreground mb-6"
          >
            Cómo funcionan las licencias
          </h2>

          <section className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <CalendarDays size={20} className="text-primary shrink-0" aria-hidden="true" />
              <h3 className="font-heading text-lg font-semibold text-foreground">
                Cómo se forma tu saldo
              </h3>
            </div>
            <p className="text-sm text-muted-foreground mb-3">
              Cada tipo de licencia tiene una cantidad de días que te corresponden
              por año. Tu saldo disponible es esa cantidad menos los días que ya
              te tomaste y fueron aprobados. Una solicitud pendiente todavía no
              descuenta: recién lo hace cuando la aprueban.
            </p>
          </section>

          <section className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <Clock size={20} className="text-primary shrink-0" aria-hidden="true" />
              <h3 className="font-heading text-lg font-semibold text-foreground">
                Qué se acumula y qué no
              </h3>
            </div>
            <div className="rounded-xl border-l-4 border-warning bg-warning-soft p-4 mb-3">
              <div className="flex gap-3">
                <AlertTriangle className="text-warning shrink-0 mt-0.5" size={18} aria-hidden="true" />
                <p className="text-sm text-warning-soft-foreground">
                  <strong>Solo las vacaciones se acumulan, y vencen a los 3 años.</strong>{" "}
                  Lo que no uses de un año pasa al siguiente, pero el sistema da de
                  baja automáticamente el saldo que cumple tres años sin usarse.
                </p>
              </div>
            </div>
            <p className="text-sm text-muted-foreground">
              El resto de las licencias es anual: lo que no se usa dentro del año
              no pasa al siguiente. No hace falta pedirlas para “no perderlas” —
              se otorgan cuando ocurre el hecho que las justifica.
            </p>
          </section>

          <section className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck size={20} className="text-primary shrink-0" aria-hidden="true" />
              <h3 className="font-heading text-lg font-semibold text-foreground">
                Por qué no ves todas las licencias
              </h3>
            </div>
            <p className="text-sm text-muted-foreground">
              La lista se adapta a cada persona. Las licencias por nacimiento y por
              embarazo se muestran según corresponda, y las de encuadre médico o
              excepcional — accidente de trabajo, enfermedad profesional, licencia
              sin goce de haberes — las gestiona RRHH directamente y no aparecen
              para solicitarlas por el circuito común.
            </p>
          </section>

          <section className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <Info size={20} className="text-primary shrink-0" aria-hidden="true" />
              <h3 className="font-heading text-lg font-semibold text-foreground">
                El recorrido de una solicitud
              </h3>
            </div>
            <div className="rounded-xl border border-border overflow-hidden">
              <Paso n="1" texto="Elegís el tipo de licencia y las fechas. El sistema cuenta los días hábiles y verifica que no superes tu saldo." />
              <Paso n="2" texto="La solicitud le llega a tu superior, que la aprueba o la rechaza." />
              <Paso n="3" texto="Aprobada, RRHH la aplica y recién ahí se descuentan los días de tu saldo." ultimo />
            </div>
          </section>

          {tipos.length > 0 && (
            <section>
              <h3 className="font-heading text-lg font-semibold text-foreground mb-3">
                Días por tipo de licencia
              </h3>
              <p className="text-sm text-muted-foreground mb-3">
                Los valores vigentes según la configuración actual. Si RRHH los
                cambia, este listado lo refleja solo.
              </p>
              <div className="rounded-xl border border-border overflow-hidden">
                {tipos.map((t, i) => (
                  <div
                    key={t.categoria}
                    className={`grid grid-cols-[1fr_5rem] gap-3 p-3 bg-card ${
                      i === tipos.length - 1 ? "" : "border-b border-border"
                    }`}
                  >
                    <span className="text-sm text-foreground">{t.categoria}</span>
                    <span className="text-sm text-muted-foreground text-right tabular-nums">
                      {t.diasTotales} días
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Paso({ n, texto, ultimo }: { n: string; texto: string; ultimo?: boolean }) {
  return (
    <div className={`grid grid-cols-[2rem_1fr] gap-3 p-3 bg-card ${ultimo ? "" : "border-b border-border"}`}>
      <span className="font-mono text-sm font-semibold text-primary">{n}</span>
      <span className="text-sm text-muted-foreground">{texto}</span>
    </div>
  );
}
```

- [ ] **Step 2: Sumar el boton en `src/app/screens/LicenciasManage/Screen.tsx`**

Agregar los imports:

```tsx
import { CircleAlert } from "lucide-react";
import { ComoFuncionanLicenciasModal } from "@/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal";
```

Agregar el estado junto a los demas `useState` del componente:

```tsx
  const [mostrarGuia, setMostrarGuia] = useState(false);
```

Reemplazar el encabezado (lineas ~150-155) por:

```tsx
      <div className="flex items-center gap-3 py-4 px-4">
        <FileText className="text-primary" size={32} />
        <h1 className="font-heading text-2xl font-bold text-foreground">
          Gestión de Licencias
        </h1>
        <button
          type="button"
          onClick={() => setMostrarGuia(true)}
          className="text-muted-foreground hover:text-primary transition-colors"
          aria-label="Cómo funcionan las licencias"
          title="Cómo funcionan las licencias"
        >
          <CircleAlert size={22} />
        </button>
      </div>
      {mostrarGuia && <ComoFuncionanLicenciasModal onClose={() => setMostrarGuia(false)} />}
```

- [ ] **Step 3: Verificar que TypeScript no suma errores**

Run: `npx tsc --noEmit 2>&1 | Select-String "error TS" | Measure-Object | Select-Object -ExpandProperty Count`
Expected: `27` (el baseline del repositorio; no debe subir)

- [ ] **Step 4: Commit**

```bash
git add src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx src/app/screens/LicenciasManage/Screen.tsx
git commit -m "feat(licencias): guia de como funcionan las licencias"
```

---

## Cómo apagar y borrar la pestaña al terminar la migración

Queda escrito acá porque es parte del trabajo, no una nota suelta.

1. **Apagar** — quitarle `licencias.cargaInicial` al rol desde la UI de administración de roles. La pestaña desaparece para todos, sin redeploy.
2. **Borrar**, con calma y en un commit propio:
   - `app/routes/carga_inicial_licencias.py` y su línea en `app/main.py`
   - `src/app/Componentes/TablaOperador/CargaInicialLicenciasTab.tsx` y sus tres bloques en `Perfildetail.tsx`
   - `tests/test_carga_inicial_endpoints.py`
   - El código de `licencias.cargaInicial` en `app/permisos.py`
3. **No borrar** la tabla `SaldoInicialLicencia` ni su integración en `armar_balances`: los saldos cargados siguen siendo el dato que sostiene el cálculo de esos empleados.

## Precondición operativa

La configuración de `ConfiguracionLicencias` solo tiene filas de 2026. La carga de años anteriores funciona igual — para eso está `saldos_sin_configuracion` — pero conviene saberlo antes de que alguien reporte que 2024 "no aparece" hasta que se le carga algo.
