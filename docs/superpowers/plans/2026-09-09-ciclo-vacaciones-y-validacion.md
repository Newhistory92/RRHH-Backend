# Ciclo de vacaciones, configuracion sin año y validacion de saldo — Plan de implementacion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que las vacaciones de un año se habiliten el 1 de octubre de ese año, que exista una sola definicion de "año vigente", que la configuracion de licencias sean dias base por contrato sin año, y que el backend rechace pedidos que superan el saldo.

**Architecture:** Una funcion pura `ciclo_vacaciones(hoy)` pasa a ser la unica fuente de "que año rige" y la consumen los tres lugares que hoy deciden por su cuenta. `ConfiguracionLicencias` deja de tener dimension temporal: la ventana de años se genera por codigo y se cruza contra la base del contrato. La validacion de saldo reusa el calculo que ya hace `/tipos-disponibles` en lugar de reimplementarlo.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()`), SQL Server (pyodbc), pytest con el doble `FakeSession`. Frontend Next.js 15 con TypeScript.

## Global Constraints

- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de solo lectura.
- Cero IDs de rol hardcodeados. La autorizacion siempre via `require_permission(...)`.
- Comentarios y docstrings en español **sin tildes**, como el resto del repositorio.
- La columna `anio` de `ConfiguracionLicencias` **se deja en la tabla**. Ningun task hace `DROP COLUMN`; el codigo solo deja de leerla y escribirla.
- La validacion de saldo **no distingue por rol**: alcanza tambien a RRHH.
- La regla del ciclo aplica **solo a Vacaciones**. Las demas categorias siguen resolviendose contra el año calendario.
- Baseline de TypeScript en el repo RRHH: **27 errores** preexistentes. Ningun task puede aumentar ese numero.
- Los 4 modulos de tests de chat (`tests/test_chat_*.py`) fallan al importar por una dependencia ausente (`google.genai`) en este entorno. Es preexistente y ajeno a este trabajo: excluirlos al correr la suite completa.

---

## Estructura de archivos

**Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)**

| Archivo | Responsabilidad |
|---|---|
| `app/services/saldo_licencias.py` | Decisiones puras del saldo. Gana `ciclo_vacaciones`, `anios_de_ventana` y `expandir_por_anio`; pierde `saldos_sin_configuracion` |
| `app/routes/licenses.py` | Endpoints. Consume el ciclo, deja de leer `anio` de la configuracion, revive la ventana Oct-Abr y valida saldo |
| `app/routes/carga_inicial_licencias.py` | Catalogo de carga inicial. Deja de filtrar configuracion por año y alinea su ventana al ciclo |
| `app/routes/rrhh.py` | Legajo bulk. Deja de seleccionar `anio` en la consulta vestigial por `licenseId` |
| `tests/test_ciclo_vacaciones.py` | **Nuevo.** La funcion pura del ciclo y la expansion por año |
| `tests/test_tipos_disponibles.py` | Existente. Gana los casos del ciclo |
| `tests/test_ventana_vacaciones.py` | **Nuevo.** Que la ventana Oct-Abr efectivamente corte |
| `tests/test_validacion_saldo.py` | **Nuevo.** Que el backend rechace excederse |

**Frontend (`C:\Users\Emiliano\Documents\RRHH`)**

| Archivo | Responsabilidad |
|---|---|
| `src/app/screens/ConfiguracionLicencias/Screen.tsx` | Pierde la columna Año, su orden, su busqueda y el campo del formulario |
| `src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx` | Deja de filtrar por `?anio=` |
| `src/app/Interfas/Interfaces.ts` | `ConfiguracionLicencia` pierde `anio` |

---

### Task 1: La funcion pura del ciclo

**Files:**
- Modify: `app/services/saldo_licencias.py`
- Test: `tests/test_ciclo_vacaciones.py` (crear)

**Interfaces:**
- Produces: `ciclo_vacaciones(hoy: date) -> int`, `anios_de_ventana(ciclo: int) -> list[int]`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_ciclo_vacaciones.py`:

```python
"""
El ciclo de vacaciones: que anio rige segun la fecha.

La regla es un borde, asi que se prueba el dia de cada lado y no un mes
cualquiera del medio: si el corte se corre un dia, estos tests lo dicen.
"""

from datetime import date

import pytest

from app.services.saldo_licencias import anios_de_ventana, ciclo_vacaciones


@pytest.mark.parametrize("hoy, esperado", [
    (date(2026, 9, 30), 2025),   # vispera del corte
    (date(2026, 10, 1), 2026),   # el corte
    (date(2026, 12, 31), 2026),  # fin de anio, ya habilitado
    (date(2027, 1, 1), 2026),    # anio nuevo, todavia rige el anterior
    (date(2027, 9, 30), 2026),
    (date(2027, 10, 1), 2027),
])
def test_el_ciclo_cambia_el_1_de_octubre(hoy, esperado):
    assert ciclo_vacaciones(hoy) == esperado


def test_la_ventana_va_del_ciclo_hacia_atras():
    """Tres anios contando el ciclo, del mas nuevo al mas viejo."""
    assert anios_de_ventana(2026) == [2026, 2025, 2024]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_ciclo_vacaciones.py -v`
Expected: FAIL con `ImportError: cannot import name 'ciclo_vacaciones'`

- [ ] **Step 3: Implementar**

En `app/services/saldo_licencias.py`, agregar el import de `date` arriba de todo y las dos funciones al final del archivo:

```python
from datetime import date
```

```python
def ciclo_vacaciones(hoy: date) -> int:
    """
    Que anio de vacaciones rige en esta fecha.

    Las vacaciones de un anio se habilitan recien el 1 de octubre de ese
    anio: hasta entonces sigue rigiendo el saldo del anterior. Antes esta
    regla vivia como expresion suelta dentro del endpoint de saldos y no
    existia en el de tipos disponibles, que es el que de verdad limita
    cuantos dias se pueden pedir -- de ahi que los dos discreparan.
    """
    return hoy.year if hoy.month >= MES_DE_CORTE else hoy.year - 1


def anios_de_ventana(ciclo: int) -> list[int]:
    """La ventana vigente, del mas nuevo al mas viejo."""
    return [ciclo - i for i in range(ANIOS_DE_VENTANA)]
```

Y agregar la constante junto a `ANIOS_DE_VENTANA`:

```python
# El mes en que se habilitan las vacaciones del anio en curso.
MES_DE_CORTE = 10
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `py -m pytest tests/test_ciclo_vacaciones.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/saldo_licencias.py tests/test_ciclo_vacaciones.py
git commit -m "feat(licencias): el ciclo de vacaciones como funcion pura"
```

---

### Task 2: La expansion por año, sin configuracion anual

**Files:**
- Modify: `app/services/saldo_licencias.py`
- Test: `tests/test_ciclo_vacaciones.py`

**Interfaces:**
- Consumes: `anios_de_ventana(ciclo)` de Task 1
- Produces: `expandir_por_anio(configs, anios, consumidos_por_clave) -> list[dict]`, con filas de forma `{"anio", "tipoLicencia", "contrato", "diasTotales", "diasConsumidos"}`

**Contexto:** hoy `/saldos` deriva sus años de las filas de `ConfiguracionLicencias`. Cuando la configuracion deje de tener año, la ventana tiene que generarse por codigo y cruzarse contra la base del contrato. Esta funcion produce exactamente la misma forma de fila que `armar_balances` ya consume, asi que esa funcion no se entera del cambio.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_ciclo_vacaciones.py`:

```python
from app.services.saldo_licencias import expandir_por_anio

CONFIGS = [
    {"categoria": "Vacaciones", "contrato": "permanente", "diasTotales": 0},
    {"categoria": "Particular", "contrato": "permanente", "diasTotales": 5},
]


def test_cada_configuracion_se_repite_en_cada_anio_de_la_ventana():
    """La configuracion ya no trae anio: los anios los pone el codigo."""
    filas = expandir_por_anio(CONFIGS, [2026, 2025], {})
    assert len(filas) == 4
    assert {f["anio"] for f in filas} == {2026, 2025}
    assert {f["tipoLicencia"] for f in filas} == {"Vacaciones", "Particular"}


def test_el_consumo_se_imputa_al_anio_y_categoria_que_corresponde():
    filas = expandir_por_anio(
        CONFIGS, [2026, 2025], {(2025, "particular"): 3},
    )
    fila = next(f for f in filas if f["anio"] == 2025 and f["tipoLicencia"] == "Particular")
    assert fila["diasConsumidos"] == 3
    otra = next(f for f in filas if f["anio"] == 2026 and f["tipoLicencia"] == "Particular")
    assert otra["diasConsumidos"] == 0


def test_el_consumo_se_cruza_sin_importar_mayusculas():
    """ConsumoLicencias.tipo lo escribe quien aprueba y no respeta el casing
    de la categoria configurada."""
    filas = expandir_por_anio(CONFIGS, [2026], {(2026, "vacaciones"): 4})
    fila = next(f for f in filas if f["tipoLicencia"] == "Vacaciones")
    assert fila["diasConsumidos"] == 4
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_ciclo_vacaciones.py -v`
Expected: FAIL con `ImportError: cannot import name 'expandir_por_anio'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/saldo_licencias.py`:

```python
def expandir_por_anio(
    configs: list[dict],
    anios: list[int],
    consumidos_por_clave: dict[tuple[int, str], int],
) -> list[dict]:
    """
    Cruza la base de cada categoria con cada anio de la ventana.

    ConfiguracionLicencias guarda dias base por contrato y categoria, sin
    anio: los anios son una decision de codigo. Sin este cruce, un anio sin
    fila de configuracion simplemente no existia, que es de donde venia toda
    la familia de problemas de saldos invisibles.

    Devuelve la misma forma de fila que armar_balances ya consume.
    """
    return [
        {
            "anio": anio,
            "tipoLicencia": cfg["categoria"],
            "contrato": cfg["contrato"],
            "diasTotales": cfg["diasTotales"],
            "diasConsumidos": consumidos_por_clave.get(
                (anio, cfg["categoria"].lower()), 0
            ),
        }
        for anio in anios
        for cfg in configs
    ]
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `py -m pytest tests/test_ciclo_vacaciones.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/saldo_licencias.py tests/test_ciclo_vacaciones.py
git commit -m "feat(licencias): expansion por anio de la configuracion sin dimension temporal"
```

---

### Task 3: `/saldos` sobre el ciclo y sin año en la configuracion

**Files:**
- Modify: `app/routes/licenses.py`
- Modify: `app/services/saldo_licencias.py` (borrar `saldos_sin_configuracion`)
- Test: `tests/test_saldos_con_saldo_inicial.py`

**Interfaces:**
- Consumes: `ciclo_vacaciones(hoy)`, `anios_de_ventana(ciclo)`, `expandir_por_anio(...)` de Tasks 1 y 2
- Produces: `armar_balances(rows, saldos_iniciales, dias_vac, gender, role_name) -> list[dict]` — pierde los parametros `consumidos_por_clave` y `min_anio`

**Contexto:** `armar_balances` tiene hoy un segundo bucle que agrega los saldos cargados para años sin fila de configuracion. Ese bucle existe solo porque la configuracion tenia año y solo habia filas de 2026. Con la expansion de Task 2 todos los años de la ventana tienen fila por construccion, asi que el bucle y su funcion auxiliar se eliminan.

- [ ] **Step 1: Escribir el test que falla**

En `tests/test_saldos_con_saldo_inicial.py`, **borrar** los dos tests que prueban el bucle eliminado (`test_un_anio_sin_configuracion_aparece_si_tiene_saldo_cargado`, `test_el_fallback_descuenta_consumo_real_en_vez_de_asumir_cero`, `test_el_fallback_respeta_el_piso_de_anios`) y agregar:

```python
def test_armar_balances_ya_no_recibe_los_parametros_del_fallback():
    """El bucle de 'sin configuracion' se elimino: la expansion por anio hace
    que todo anio de la ventana tenga fila. Si alguien reintroduce esos
    parametros, es senal de que volvio el parche."""
    import inspect
    from app.routes.licenses import armar_balances

    params = set(inspect.signature(armar_balances).parameters)
    assert "consumidos_por_clave" not in params
    assert "min_anio" not in params
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_saldos_con_saldo_inicial.py -v`
Expected: FAIL — los parametros todavia existen

- [ ] **Step 3: Borrar `saldos_sin_configuracion`**

En `app/services/saldo_licencias.py`, eliminar la funcion `saldos_sin_configuracion` completa (definicion y docstring).

- [ ] **Step 4: Simplificar `armar_balances`**

En `app/routes/licenses.py`, reemplazar la firma y el segundo bucle de `armar_balances`. La firma queda:

```python
def armar_balances(
    rows: list[dict],
    saldos_iniciales: dict[tuple[int, str], int],
    dias_vac: int,
    gender: str | None,
    role_name: str,
) -> list[dict]:
```

Eliminar del cuerpo: la linea `consumidos_por_clave = consumidos_por_clave or {}`, la variable `cubiertas` y todas sus escrituras (`cubiertas.add(clave)`), y **todo** el bloque final que arranca con el comentario `# Un anio sin fila de configuracion no aparece en rows.` hasta antes de `return balances`.

Del import de `app.services.saldo_licencias` en la cabecera del archivo, quitar `saldos_sin_configuracion`.

- [ ] **Step 5: Reemplazar la consulta y el armado en `get_license_saldos`**

Reemplazar el bloque que arranca en `# ── 3. Obtener balances ──` (la `rows_query` completa y su `db.execute`) por:

```python
    # ── 3. Obtener balances ──────────────────────────────────────────────────
    # La configuracion ya no tiene anio: son dias base por contrato. Los anios
    # de la ventana los pone el codigo y se cruzan contra esa base.
    configs = db.execute(text("""
        SELECT categoria, tipo AS contrato, diasTotales
        FROM ConfiguracionLicencias
        WHERE LOWER(tipo) = :tipoContrato
        ORDER BY categoria
    """), {"tipoContrato": tipo_contrato}).mappings().all()
```

Y reemplazar el `return` final del endpoint por:

```python
    consumo_rows = db.execute(text("""
        SELECT cl_i.anio, LOWER(cl_i.tipo) AS categoria, SUM(cl_i.diasConsumidos) AS total
        FROM ConsumoLicencias cl_i
        INNER JOIN License l_i ON cl_i.licenseId = l_i.id
        WHERE l_i.employeeId = :empId
        GROUP BY cl_i.anio, LOWER(cl_i.tipo)
    """), {"empId": employee_id}).mappings().all()
    consumidos_por_clave = {(r["anio"], r["categoria"]): int(r["total"]) for r in consumo_rows}

    filas = expandir_por_anio(
        [dict(c) for c in configs],
        anios_de_ventana(current_cycle),
        consumidos_por_clave,
    )

    return {"balances": armar_balances(
        rows=filas,
        saldos_iniciales=saldos_iniciales,
        dias_vac=dias_vac,
        gender=gender,
        role_name=role_name,
    )}
```

- [ ] **Step 6: Usar la funcion del ciclo y ajustar la expiracion**

Reemplazar la linea del ciclo y las dos que la siguen:

```python
    current_cycle = ciclo_vacaciones(today)
    min_anio      = current_cycle - (ANIOS_DE_VENTANA - 1)
    expire_anio   = current_cycle - ANIOS_DE_VENTANA
```

En la consulta de expiracion (`exp_query`), quitar la linea `AND c.anio = :expAnio` y el bind `"expAnio": expire_anio` del diccionario de parametros. La base del contrato es el mismo numero que correspondia ese año; el año sigue importando para el consumo y para el saldo inicial, que ya se consultan aparte.

Actualizar el import de `app.services.saldo_licencias` para incluir `ANIOS_DE_VENTANA`, `anios_de_ventana`, `ciclo_vacaciones` y `expandir_por_anio`.

- [ ] **Step 7: Correr los tests**

Run: `py -m pytest tests/test_saldos_con_saldo_inicial.py tests/test_ciclo_vacaciones.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/routes/licenses.py app/services/saldo_licencias.py tests/test_saldos_con_saldo_inicial.py
git commit -m "feat(licencias): saldos sobre el ciclo, con la ventana generada por codigo"
```

---

### Task 4: `/tipos-disponibles` con vacaciones atadas al ciclo

**Files:**
- Modify: `app/routes/licenses.py`
- Test: `tests/test_tipos_disponibles.py`

**Interfaces:**
- Consumes: `ciclo_vacaciones(hoy)` de Task 1
- Produces: `tipos_disponibles_de(db, employee_id) -> dict` — la funcion que Task 6 reusa para validar

**Contexto:** este es el endpoint que fija el tope real del selector de fechas. Las vacaciones pasan a resolverse contra el ciclo; las demas categorias siguen en año calendario. Se extrae el cuerpo a una funcion reutilizable para que la validacion de Task 6 valide exactamente contra el mismo numero que la pantalla ofrecio.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_tipos_disponibles.py`:

```python
from unittest.mock import patch


def test_vacaciones_consulta_el_anio_del_ciclo_no_el_calendario():
    """Antes del 1 de octubre rige el anio anterior. Sin esto, el empleado
    podia pedir las vacaciones del anio nuevo desde el 1 de enero."""
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": 2025, "categoria": "Vacaciones", "diasPendientes": 7},
        ],
    })

    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 30)
        resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 7


def test_despues_del_corte_vacaciones_toma_el_anio_en_curso():
    db = FakeSession({
        EMP_QUERY_FRAGMENTO: [_emp_row()],
        CONFIG_QUERY_FRAGMENTO: [{"nombre": "Vacaciones", "diasTotales": 30, "consumidos": 0}],
        SALDO_INICIAL_FRAGMENTO: [
            {"anio": 2026, "categoria": "Vacaciones", "diasPendientes": 12},
        ],
    })

    with patch("app.routes.licenses.date") as fake_date:
        fake_date.today.return_value = date(2026, 10, 1)
        resultado = get_tipos_disponibles(employee_id=8, db=db)

    fila = next(t for t in resultado["tipos"] if t["nombre"] == "Vacaciones")
    assert fila["diasTotales"] == 12
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_tipos_disponibles.py -v`
Expected: FAIL — hoy la clave del saldo inicial usa el año calendario

- [ ] **Step 3: Implementar el ciclo y quitar el año de la consulta**

En `get_tipos_disponibles`, reemplazar la linea del ciclo:

```python
    today = date.today()
    current_cycle = today.year
    # Las vacaciones se habilitan el 1 de octubre: hasta entonces rige el
    # saldo del anio anterior. Solo aplica a vacaciones -- las demas
    # categorias son anuales sin arrastre y siguen el anio calendario.
    ciclo_vac = ciclo_vacaciones(today)
```

En la consulta principal, quitar `AND c.anio = :anio` del `WHERE` y quitar `"anio": current_cycle` de los binds. La subconsulta de consumo mantiene su filtro por año, pero pasa a recibir dos binds distintos, asi que se reemplaza la consulta completa por:

```python
    query = text("""
        SELECT
            c.categoria as nombre,
            c.diasTotales,
            COALESCE(SUM(cons.diasConsumidos), 0) as consumidos
        FROM ConfiguracionLicencias c
        LEFT JOIN (
            SELECT cl_i.tipo as categoria_consumo, cl_i.diasConsumidos, cl_i.anio
            FROM ConsumoLicencias cl_i
            INNER JOIN License l_i ON cl_i.licenseId = l_i.id
            WHERE l_i.employeeId = :empId
        ) cons
            ON cons.categoria_consumo = c.categoria
           AND cons.anio = (CASE WHEN LOWER(c.categoria) = 'vacaciones'
                                 THEN :cicloVac ELSE :anioCalendario END)
        WHERE c.tipo = :tipoConfig
        GROUP BY c.categoria, c.diasTotales
    """)

    rows = db.execute(query, {
        "empId": employee_id,
        "cicloVac": ciclo_vac,
        "anioCalendario": current_cycle,
        "tipoConfig": tipo_config
    }).mappings().all()
```

- [ ] **Step 4: Usar el año correcto para el saldo inicial**

En el bucle, reemplazar la llamada a `total_del_anio` por:

```python
        anio_de_esta_categoria = (
            ciclo_vac if "vacaciones" in nombre_lower else current_cycle
        )
        dias_totales = total_del_anio(
            saldo_inicial=saldos_iniciales.get((anio_de_esta_categoria, nombre)),
            es_vacaciones=False,
            dias_vac=0,
            dias_totales=dias_totales_base,
        )
```

- [ ] **Step 5: Extraer el cuerpo a una funcion reutilizable**

Renombrar el cuerpo actual de `get_tipos_disponibles` a una funcion `tipos_disponibles_de(db, employee_id)` que devuelva el mismo diccionario, y dejar el endpoint como:

```python
@router.get("/tipos-disponibles", dependencies=[Depends(require_auth)])
def get_tipos_disponibles(employee_id: int, db: Session = Depends(get_db)):
    """
    Retorna los tipos de licencia que el empleado puede solicitar.

    El cuerpo vive en tipos_disponibles_de porque la validacion de saldo al
    crear una solicitud tiene que comparar contra exactamente este numero:
    una segunda implementacion del mismo calculo es lo que hizo que este
    endpoint y el de saldos discreparan durante meses.
    """
    return tipos_disponibles_de(db, employee_id)
```

Agregar `ciclo_vacaciones` al import de `app.services.saldo_licencias`.

- [ ] **Step 6: Correr los tests**

Run: `py -m pytest tests/test_tipos_disponibles.py -v`
Expected: PASS — los 4 tests previos siguen pasando y los 2 nuevos tambien

- [ ] **Step 7: Commit**

```bash
git add app/routes/licenses.py tests/test_tipos_disponibles.py
git commit -m "feat(licencias): las vacaciones se habilitan el 1 de octubre"
```

---

### Task 5: Revivir la ventana Oct-Abr

**Files:**
- Modify: `app/routes/licenses.py`
- Test: `tests/test_ventana_vacaciones.py` (crear)

**Contexto:** la validacion existe pero su `raise HTTPException` esta adentro de un `try` cuyo `except Exception: pass` lo atrapa — `HTTPException` hereda de `Exception`. Nunca bloqueo nada. El test se escribe **contra el endpoint** y no contra una funcion interna: a nivel unitario el defecto era invisible, que es exactamente por lo que sobrevivio.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_ventana_vacaciones.py`:

```python
"""
La ventana Oct-Abr de vacaciones.

La validacion ya existia, pero su HTTPException caia dentro de un
`except Exception: pass` que se la tragaba. El test va contra el endpoint
porque a nivel de funcion interna el defecto no se veia.
"""

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession


def _payload(start: str, tipo: str = "Vacaciones") -> dict:
    return {
        "type": tipo,
        "startDate": start,
        "endDate": start,
        "duration": 1,
        "employeeId": 8,
        "supervisorId": 3,
        "mensajeOriginal": "test",
    }


def _db_empleado():
    return FakeSession({
        "SELECT e.gender": [{
            "gender": "Masculino", "employee_name": "Test",
            "tipoContrato": "permanente", "fechaIngreso": None,
            "roleName": "user",
        }],
    })


def test_vacaciones_en_junio_se_rechazan():
    """Junio esta fuera de la ventana Oct-Abr."""
    with pytest.raises(HTTPException) as e:
        create_license_request(
            data=_payload("2026-06-15T00:00:00"),
            db=_db_empleado(),
            current_user={"employeeId": 8, "permisos": set()},
        )
    assert e.value.status_code == 400
    assert "Octubre" in str(e.value.detail)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_ventana_vacaciones.py -v`
Expected: FAIL — hoy no levanta nada, el `except` se lo traga

- [ ] **Step 3: Sacar el raise del try**

En `create_license_request`, reemplazar el bloque D:

```python
    # D. Vacaciones: Ventana Oct-Abr
    if "vacaciones" in type_lower:
        # El raise va FUERA del try a proposito: cuando estaba adentro, el
        # `except Exception: pass` atrapaba su propia HTTPException --
        # HTTPException hereda de Exception -- y la validacion nunca corto
        # nada. El try solo cubre el parseo de la fecha, que es lo unico que
        # legitimamente puede fallar por un dato mal formado.
        mes_inicio = None
        try:
            mes_inicio = datetime.fromisoformat(start_date.replace('Z', '+00:00')).month
        except Exception:
            pass

        if mes_inicio is not None and mes_inicio not in MESES_DE_VACACIONES:
            raise HTTPException(
                status_code=400,
                detail="Las vacaciones solo pueden tomarse entre el 1 de Octubre y el 30 de Abril.",
            )
```

Agregar la constante cerca de las demas del modulo:

```python
# Ventana en la que se pueden tomar vacaciones: octubre a abril.
MESES_DE_VACACIONES = (10, 11, 12, 1, 2, 3, 4)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `py -m pytest tests/test_ventana_vacaciones.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/licenses.py tests/test_ventana_vacaciones.py
git commit -m "fix(licencias): la ventana Oct-Abr deja de tragarse su propia excepcion"
```

---

### Task 6: Validacion de saldo al crear la solicitud

**Files:**
- Modify: `app/routes/licenses.py`
- Test: `tests/test_validacion_saldo.py` (crear)

**Interfaces:**
- Consumes: `tipos_disponibles_de(db, employee_id)` de Task 4

**Contexto:** hoy el backend no compara los dias pedidos contra el saldo: el tope es una cortesia del navegador y un POST directo con noventa dias entra sin objecion. La validacion **alcanza tambien a RRHH**, sin excepcion por rol.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_validacion_saldo.py`:

```python
"""
El backend rechaza pedir mas dias de los que hay.

Hasta ahora el unico limite era el selector de fechas del navegador: un POST
directo entraba sin objecion.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routes.licenses import create_license_request
from tests.fakes import FakeSession


def _payload(dias: int, tipo: str = "Particular") -> dict:
    return {
        "type": tipo,
        "startDate": "2026-11-10T00:00:00",
        "endDate": "2026-11-20T00:00:00",
        "duration": dias,
        "employeeId": 8,
        "supervisorId": 3,
        "mensajeOriginal": "test",
    }


def _db():
    return FakeSession({
        "SELECT e.gender": [{
            "gender": "Masculino", "employee_name": "Test",
            "tipoContrato": "permanente", "fechaIngreso": None,
            "roleName": "user",
        }],
    })


DISPONIBLES_5 = {"tipos": [{"nombre": "Particular", "diasTotales": 5,
                            "consumidos": 0, "disponibles": 5}]}


def test_rechaza_pedir_mas_de_lo_disponible():
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        with pytest.raises(HTTPException) as e:
            create_license_request(
                data=_payload(6), db=_db(),
                current_user={"employeeId": 8, "permisos": set()},
            )
    assert e.value.status_code == 400
    assert "5" in str(e.value.detail)


def test_permite_pedir_exactamente_el_limite():
    """El borde tiene que entrar: pedir justo lo que hay no es excederse."""
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        try:
            create_license_request(
                data=_payload(5), db=_db(),
                current_user={"employeeId": 8, "permisos": set()},
            )
        except HTTPException as e:
            # Contra FakeSession la insercion posterior puede fallar; lo que
            # este test afirma es que NO corta por saldo.
            assert "saldo" not in str(e.detail).lower()


def test_la_validacion_tambien_alcanza_a_rrhh():
    """Se decidio criterio parejo: RRHH tampoco puede exceder el saldo.

    El permiso que habilita a pedir a nombre de otro es licencias.configurar
    (no rrhh.gestionar): con cualquier otro, el endpoint corta antes con un
    403 y este test no llegaria a probar lo que dice probar."""
    with patch("app.routes.licenses.tipos_disponibles_de", return_value=DISPONIBLES_5):
        with pytest.raises(HTTPException) as e:
            create_license_request(
                data=_payload(6), db=_db(),
                current_user={"employeeId": 99, "permisos": {"licencias.configurar"}},
            )
    assert e.value.status_code == 400
    assert "5" in str(e.value.detail)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_validacion_saldo.py -v`
Expected: FAIL — hoy no hay ninguna validacion de saldo

- [ ] **Step 3: Implementar**

En `create_license_request`, inmediatamente despues del bloque D (la ventana Oct-Abr) y antes del bloque E (Embarazo), agregar:

```python
    # D bis. Saldo disponible. Se compara contra el mismo numero que ofrecio
    # la pantalla, reusando su calculo: reimplementarlo aca es lo que hizo
    # que /saldos y /tipos-disponibles discreparan.
    #
    # No distingue por rol: RRHH tampoco puede exceder el saldo.
    if duration:
        catalogo = tipos_disponibles_de(db, int(employee_id))
        fila = next(
            (t for t in catalogo["tipos"] if t["nombre"].lower() == type_lower),
            None,
        )
        if fila is not None and int(duration) > fila["disponibles"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No hay saldo suficiente de {fila['nombre']}: "
                    f"pediste {int(duration)} dias y hay {fila['disponibles']} disponibles."
                ),
            )
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `py -m pytest tests/test_validacion_saldo.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add app/routes/licenses.py tests/test_validacion_saldo.py
git commit -m "feat(licencias): el backend rechaza pedidos que superan el saldo"
```

---

### Task 7: Los sitios secundarios dejan de leer el año

**Files:**
- Modify: `app/routes/licenses.py` (CRUD de configuracion, `seed_configs_si_faltan`)
- Modify: `app/routes/carga_inicial_licencias.py`
- Modify: `app/routes/rrhh.py:197-202`
- Test: `tests/test_carga_inicial_endpoints.py`

**Interfaces:**
- Consumes: `ciclo_vacaciones(hoy)`, `anios_de_ventana(ciclo)` de Task 1

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_carga_inicial_endpoints.py`:

```python
def test_la_ventana_de_carga_sigue_al_ciclo_no_al_calendario():
    """Las dos ventanas -- la que se carga y la que /saldos muestra -- tienen
    que ser la misma, o se cargarian anios que no se ven."""
    from datetime import date
    from app.services.saldo_licencias import anios_de_ventana, ciclo_vacaciones

    assert anios_de_ventana(ciclo_vacaciones(date(2026, 9, 30))) == [2025, 2024, 2023]
    assert anios_de_ventana(ciclo_vacaciones(date(2026, 10, 1))) == [2026, 2025, 2024]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `py -m pytest tests/test_carga_inicial_endpoints.py -v`
Expected: FAIL si `anios_de_carga` todavia se usa con el año calendario

- [ ] **Step 3: Alinear la carga inicial al ciclo**

En `app/routes/carga_inicial_licencias.py`:

- Reemplazar `anio_actual = date.today().year` por `anio_actual = ciclo_vacaciones(date.today())` en `get_carga_inicial` y en `guardar_carga_inicial`.
- Cambiar el import: `from app.services.saldo_licencias import anios_de_ventana, ciclo_vacaciones`, y reemplazar las llamadas a `anios_de_carga(...)` por `anios_de_ventana(...)`.
- En la consulta de `dias_configurados`, quitar `anio = :anio AND` del `WHERE` y el bind `"anio": anio_actual`:

```python
            text("""
                SELECT categoria, diasTotales
                FROM ConfiguracionLicencias
                WHERE tipo = :tipoConfig
            """),
            {"tipoConfig": tipo_config},
```

En `app/services/saldo_licencias.py`, eliminar `anios_de_carga` (queda reemplazada por `anios_de_ventana`).

- [ ] **Step 4: Quitar el año del CRUD de configuracion**

En `app/routes/licenses.py`:

- `get_configuraciones`: eliminar el parametro `anio`, el `if anio:` y su bind. La consulta queda:

```python
    query = "SELECT id, tipo, categoria , diasTotales, createdAt, updatedAt FROM ConfiguracionLicencias ORDER BY tipo ASC, categoria ASC"
    config_result = db.execute(text(query)).mappings().all()
    return {"configuraciones": [dict(c) for c in config_result]}
```

- `create_configuracion`: quitar `anio = data.get("anio")`, sacarlo del `if not all([...])` (queda `if not all([tipo, dias_totales])`), del `INSERT` y de los binds.
- `update_configuracion`: quitar `anio = data.get("anio")`, `anio = :anio,` del `SET` y su bind.
- Eliminar `seed_configs_si_faltan` completa: sin año no hay nada por año que sembrar.

En `app/routes/rrhh.py`, en la consulta bulk por `licenseId`, quitar `anio,` del `SELECT` y cambiar `ORDER BY anio DESC` por `ORDER BY id DESC`.

- [ ] **Step 5: Correr la suite completa**

Run: `py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py`
Expected: PASS, sin regresiones

- [ ] **Step 6: Commit**

```bash
git add app/routes/licenses.py app/routes/carga_inicial_licencias.py app/routes/rrhh.py app/services/saldo_licencias.py tests/test_carga_inicial_endpoints.py
git commit -m "refactor(licencias): la configuracion deja de tener dimension temporal"
```

---

### Task 8: La pantalla de configuracion sin el año

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Interfas\Interfaces.ts`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\screens\ConfiguracionLicencias\Screen.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\ModalRRHH\ComoFuncionanLicenciasModal.tsx`

**Contexto:** todo el trabajo de este task es en el repo **RRHH**, no en Backend_RRHH. No hay suite de tests unitarios para estas pantallas: la verificacion es que `tsc --noEmit` no supere los 27 errores de baseline.

- [ ] **Step 1: Medir el baseline**

Run: `cd C:\Users\Emiliano\Documents\RRHH && npx tsc --noEmit 2>&1 | Select-String "error TS" | Measure-Object | Select-Object -ExpandProperty Count`
Expected: 27

- [ ] **Step 2: Quitar `anio` del tipo**

En `src/app/Interfas/Interfaces.ts`, en la interfaz `ConfiguracionLicencia`, eliminar la linea `anio: number;`.

- [ ] **Step 3: Quitar el año de la pantalla**

En `src/app/screens/ConfiguracionLicencias/Screen.tsx`:

- El estado del orden: cambiar `useState<'anio' | 'tipo' | 'categoria' | 'diasTotales'>('anio')` por `useState<'tipo' | 'categoria' | 'diasTotales'>('tipo')`.
- El estado del formulario: `useState<Partial<ConfiguracionLicencia>>({ tipo: "", categoria: "", diasTotales: 0 })` (sin `anio`).
- El reset al crear: `setLicenciaForm({ tipo: contracts[0]?.key || "", categoria: "", diasTotales: 5 })`.
- La busqueda: eliminar la linea `c.anio.toString().includes(searchTerm)` y su `||`.
- La tabla: eliminar el `<th>` de Año completo (con su `toggleSort('anio')` y su `SortIcon`) y la `<td>` que muestra `{config.anio}`.
- El formulario: eliminar el `<input type="number">` de año, junto con su `<label>` y el contenedor que lo envuelve.

- [ ] **Step 4: Quitar el filtro del modal**

En `src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx`, reemplazar la llamada por:

```typescript
      .get<{ configuraciones: ConfigLicencia[] }>("/licenses/configuracion")
```

Y eliminar la linea `const anioActual = new Date().getFullYear();`. El agrupado por categoria que muestra el rango entre contratos **se conserva**: distintos contratos siguen teniendo topes distintos, y esa es justamente la dimension que la tabla mantiene.

- [ ] **Step 5: Verificar que no aumentaron los errores**

Run: `cd C:\Users\Emiliano\Documents\RRHH && npx tsc --noEmit 2>&1 | Select-String "error TS" | Measure-Object | Select-Object -ExpandProperty Count`
Expected: 27

- [ ] **Step 6: Commit**

```bash
cd C:\Users\Emiliano\Documents\RRHH
git add src/app/Interfas/Interfaces.ts src/app/screens/ConfiguracionLicencias/Screen.tsx src/app/Componentes/ModalRRHH/ComoFuncionanLicenciasModal.tsx
git commit -m "refactor(licencias): la configuracion deja de pedir un anio"
```

---

## Precondicion operativa antes de desplegar

La validacion de saldo alcanza tambien a RRHH, asi que **una categoria configurada en cero bloquea a todos, sin salida por el costado**. Antes de que esto entre en produccion hay que revisar los valores de las 21 categorias en Configuracion → Licencias.

Es configuracion, no desarrollo, pero es condicion para que el circuito de licencias no se corte.

Ademas: el `DROP COLUMN` de `ConfiguracionLicencias.anio` **no lo hace ningun task**. Queda como paso posterior y deliberado, una vez confirmado en el servidor que nada quedo leyendola.
