# Score de productividad para áreas sin actividad en el sistema — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que las áreas cuyo trabajo no genera logs de acceso al sistema (Sistemas, mantenimiento, etc.) dejen de tener score 0 y aparecer últimas en el ranking, sin perder la capacidad de distinguir quién es el mejor dentro de esa área.

**Architecture:** Se agrega una marca de exención a `Department` y `Office`. En el cálculo del score (`sync_productivity_scores`), los empleados exentos dejan de recibir su conteo de sesiones y pasan a recibir el **promedio de los no exentos**, más un ajuste de desempate derivado de su asistencia real (`Employee.horas`), de forma que el promedio del grupo se conserve pero cada empleado tenga un número propio. El frontend suma un check en la pantalla de Organigrama/Departamentos para que RRHH marque las áreas.

**Tech Stack:** FastAPI + SQLAlchemy Core (`text()`) + SQL Server en `Backend_RRHH`; Next.js 15 + TypeScript en `RRHH`; pytest con `FakeSession` para los tests.

## Global Constraints

- **No levantar servidor.** Verificación por `venv/Scripts/python.exe -m pytest tests/ -q` (siempre acotado a `tests/`, nunca `pytest` pelado — hay scripts sueltos en la raíz que cuelgan) y `npx tsc --noEmit` en el frontend.
- **Nunca escribir en la base ObraSocial.** Todo acceso a `[ObraSocial].[dbo].*` es de solo lectura. El cálculo de sesiones sigue siendo un `SELECT`.
- **Ningún test toca bases reales.** Usar `FakeSession` de `tests/fakes.py`.
- **DDL idempotente.** Toda columna nueva se agrega con `IF COL_LENGTH(...) IS NULL`, siguiendo el patrón de `app/database/permissions.py` y `ensure_columna_origen`.
- **Cero IDs de rol hardcodeados.** La autorización va por `require_permission(...)`.
- **El promedio del grupo exento debe conservarse.** El desempate redistribuye alrededor del promedio, no lo desplaza.

---

## Decisiones tomadas con el usuario (no volver a preguntar)

| Decisión | Valor |
|---|---|
| Score de los exentos | El **promedio de los no exentos**, con desempate por asistencia |
| Dónde se marca la exención | En **Department Y Office** — un empleado queda exento si su departamento **o** su oficina está marcada |
| Empleados exentos sin datos de asistencia | Reciben el **promedio limpio, sin ajuste** (no se los castiga por falta de datos) |
| Por qué no un score plano por grupo | Con todos iguales, una autoridad no puede elegir a quién ascender dentro de esa área |

---

## Diagnóstico (ya verificado, no reinvestigar)

| Hallazgo | Evidencia |
|---|---|
| El score sale de sesiones de acceso a ObraSocial | `app/routes/stats.py:20-68`, `calculate_productivity_scores` cuenta eventos de `UsuarioAccesoLogs` agrupados en sesiones |
| `sync_productivity_scores` es el **único** lugar que escribe el score | `app/routes/stats.py:69-84`. Todo el resto (`employee.py:47,403`, `rrhh.py:82,353,616,761`, `stats.py:90,117,162-189`) solo lee `Employee.productivityScore` |
| El sync corre al abrir el dashboard | `app/routes/stats.py:105`, dentro de `get_dashboard`, con `try/except` que degrada al último valor guardado si ObraSocial no responde |
| `Office` está **vacía** | 0 filas, 0 empleados con `officeId`. Solo hay departamentos, y 5 de 10 empleados tampoco tienen `departmentId` |
| La asistencia cubre a la mitad | `Employee.horas` tiene valor en 5 de 10 empleados (el resto `null`); `Ausencia` está vacía; `Marcacion` sí tiene 11.442 filas y 5 empleados con `biometricoId` |
| Hoy casi todos están en 0 | Solo un empleado tiene score ≠ 0 (1.60). El resto en 0.00 o `null` |

---

## El cálculo

Sea `P` el promedio de `productivityScore` de los empleados **no exentos** que tienen score > 0.

Para cada empleado exento:

- **Sin dato de asistencia** (`Employee.horas IS NULL`) → recibe exactamente `P`.
- **Con dato de asistencia** → recibe `P + ajuste`, donde el ajuste sale de comparar su saldo de horas contra el promedio de saldos de su propio grupo exento, escalado a un rango acotado.

El ajuste se acota a **±15% de P** para que el desempate ordene sin distorsionar: nadie salta por encima de un área que realmente trabaja más, y el promedio del grupo se mantiene en `P` porque los ajustes están centrados en la media del grupo.

```
ajuste_i = (horas_i - promedio_horas_del_grupo) / rango_horas_del_grupo * (0.15 * P)
```

Con `rango_horas_del_grupo = max(horas) - min(horas)`. Si el rango es 0 (todos con el mismo saldo) el ajuste es 0 y todos reciben `P`.

**Casos borde a cubrir con tests:**
- No hay ningún empleado no exento → `P` no se puede calcular; los exentos conservan su score anterior (no se pisa con 0).
- Todos los exentos tienen `horas = NULL` → todos reciben `P`, sin ajuste.
- Un solo empleado exento → recibe `P` (el rango es 0).
- `P = 0` (nadie tiene actividad) → el ajuste es 0; todos los exentos reciben 0, igual que hoy. No empeora nada.

---

## Task 1: Marca de exención en la base

**Files:**
- Create: `app/database/score_exencion.py`
- Modify: `app/main.py` (llamar al ensure en el startup)
- Test: `tests/test_score_exencion.py`

**Interfaces:**
- Produces: `ensure_columnas_exencion(db) -> None`, `empleados_exentos(db) -> set[int]` (devuelve los `Employee.id` cuyo departamento u oficina está marcado).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_score_exencion.py`:

```python
"""Tests de la marca de exencion de score, sin base real."""

from app.database.score_exencion import empleados_exentos
from tests.fakes import FakeSession


def test_devuelve_los_empleados_de_un_departamento_exento():
    db = FakeSession({"FROM Employee e": [{"id": 3}, {"id": 7}]})
    assert empleados_exentos(db) == {3, 7}


def test_sin_areas_exentas_devuelve_conjunto_vacio():
    db = FakeSession({"FROM Employee e": []})
    assert empleados_exentos(db) == set()


def test_la_consulta_mira_departamento_y_oficina():
    db = FakeSession({"FROM Employee e": []})
    empleados_exentos(db)
    sql, _ = db.ejecutadas[0]
    assert "scoreExento" in sql
    assert "Department" in sql
    assert "Office" in sql
```

- [ ] **Step 2: Correr el test para verificar que falla**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_exencion.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.database.score_exencion'`.

- [ ] **Step 3: Escribir el módulo**

Crear `app/database/score_exencion.py`:

```python
"""
Marca de exencion del score de productividad.

El score sale de contar sesiones de acceso al sistema (ver stats.py). Las areas
cuyo trabajo no pasa por el sistema -- Sistemas, mantenimiento -- generan pocos
logs o ninguno, asi que siempre quedan en 0 y ultimas en el ranking, sin que eso
diga nada sobre cuanto trabajan. Marcar el area exime a su gente de esa metrica
y les asigna el promedio de los demas (ver sync_productivity_scores).

Se marca en Department y en Office: un empleado queda exento si cualquiera de
las dos lo esta. Hoy Office esta vacia en esta base, pero la columna se agrega
igual para que funcione cuando se carguen oficinas.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_columnas_exencion(db: Session) -> None:
    """Agrega scoreExento a Department y Office. Seguro de repetir."""
    db.execute(text(
        "IF COL_LENGTH('Department','scoreExento') IS NULL "
        "ALTER TABLE Department ADD scoreExento BIT NOT NULL DEFAULT 0;"
    ))
    db.execute(text(
        "IF COL_LENGTH('Office','scoreExento') IS NULL "
        "ALTER TABLE Office ADD scoreExento BIT NOT NULL DEFAULT 0;"
    ))
    db.commit()


def empleados_exentos(db: Session) -> set[int]:
    """
    Ids de empleados cuyo departamento u oficina esta marcado como exento.

    El LEFT JOIN es a proposito: un empleado sin oficina (el caso normal en
    esta base) sigue siendo evaluable por su departamento.
    """
    filas = db.execute(text("""
        SELECT e.id
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        WHERE ISNULL(d.scoreExento, 0) = 1 OR ISNULL(o.scoreExento, 0) = 1
    """)).mappings().all()
    return {f["id"] for f in filas}
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_exencion.py -v
```

Esperado: PASS, 3 tests.

- [ ] **Step 5: Llamar el ensure en el startup**

En `app/main.py`, importar `ensure_columnas_exencion` y llamarlo dentro del bloque `startup()` que ya corre los demás ensure (junto a `ensure_columna_origen`), con su `print("[OK] ...")` siguiendo el estilo ASCII de las demás líneas.

- [ ] **Step 6: Verificar que la app importa y arranca el DDL**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -c "import app.main; print('IMPORT OK')"
```

Esperado: `IMPORT OK`.

- [ ] **Step 7: Commit**

```bash
git add app/database/score_exencion.py app/main.py tests/test_score_exencion.py
git commit -m "feat(score): marca de exencion por departamento y oficina"
```

---

## Task 2: Cálculo del score con exención y desempate

**Files:**
- Modify: `app/routes/stats.py:69-84` (`sync_productivity_scores`)
- Test: `tests/test_score_promedio.py`

**Interfaces:**
- Consumes: `empleados_exentos` de la Task 1.
- Produces: `aplicar_score_exentos(scores, exentos, horas_por_empleado) -> dict[int, float]` — **función pura**, sin I/O, que recibe los scores ya calculados y devuelve los scores finales. Se separa así justamente para poder testear la matemática sin base.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_score_promedio.py`:

```python
"""
Tests del reparto de score para areas exentas.

La funcion es pura: recibe scores, exentos y horas; devuelve scores finales.
Sin base de datos, sin I/O.
"""

from app.routes.stats import aplicar_score_exentos


def test_el_exento_sin_horas_recibe_el_promedio_limpio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={})
    assert resultado[3] == 5.0  # promedio de 6.0 y 4.0
    assert resultado[1] == 6.0  # los no exentos no se tocan
    assert resultado[2] == 4.0


def test_los_exentos_se_desempatan_por_horas_conservando_el_promedio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    # 3 tiene mejor saldo que 4
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 10.0, 4: -10.0})
    assert resultado[3] > resultado[4], "el de mejor asistencia debe quedar arriba"
    promedio_grupo = (resultado[3] + resultado[4]) / 2
    assert abs(promedio_grupo - 5.0) < 0.01, "el promedio del grupo se conserva"


def test_exentos_con_el_mismo_saldo_reciben_todos_el_promedio():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 5.0, 4: 5.0})
    assert resultado[3] == resultado[4] == 5.0


def test_el_exento_sin_horas_no_se_mezcla_con_los_que_si_tienen():
    scores = {1: 6.0, 2: 4.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 10.0})
    assert resultado[4] == 5.0, "sin dato de asistencia recibe el promedio limpio"


def test_sin_no_exentos_no_se_pisa_el_score_previo():
    scores = {1: 3.0, 2: 2.0}
    resultado = aplicar_score_exentos(scores, exentos={1, 2}, horas={})
    assert resultado == scores, "sin base para promediar, no se toca nada"


def test_promedio_cero_no_empeora_a_nadie():
    scores = {1: 0.0, 2: 0.0, 3: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3}, horas={3: 10.0})
    assert resultado[3] == 0.0


def test_el_ajuste_no_supera_el_quince_por_ciento_del_promedio():
    scores = {1: 10.0, 2: 10.0, 3: 0.0, 4: 0.0}
    resultado = aplicar_score_exentos(scores, exentos={3, 4}, horas={3: 999.0, 4: -999.0})
    assert resultado[3] <= 10.0 * 1.15
    assert resultado[4] >= 10.0 * 0.85
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_promedio.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'aplicar_score_exentos'`.

- [ ] **Step 3: Escribir la función pura**

En `app/routes/stats.py`, antes de `sync_productivity_scores`:

```python
# Cuanto puede moverse un exento respecto del promedio, por su asistencia.
# Acotado a proposito: el desempate ordena dentro del area, no compite contra
# las areas que si generan actividad medible.
MARGEN_DESEMPATE = 0.15


def aplicar_score_exentos(
    scores: dict[int, float],
    exentos: set[int],
    horas: dict[int, float],
) -> dict[int, float]:
    """
    Reemplaza el score de las areas exentas por el promedio de las demas.

    Las areas cuyo trabajo no pasa por el sistema no generan logs de acceso, asi
    que su score medido siempre da ~0 y quedan ultimas sin que eso diga nada de
    cuanto trabajan. Se les asigna el promedio de los no exentos, mas un ajuste
    derivado de su saldo de horas para que no queden todos con el mismo numero:
    una autoridad tiene que poder ver quien es el mejor DENTRO del area.

    El ajuste esta centrado en la media del propio grupo, asi que el promedio
    del grupo sigue siendo el promedio general. Quien no tiene dato de
    asistencia recibe el promedio limpio: no se lo castiga por falta de datos.

    Funcion pura, sin I/O, para poder testear la matematica sin base.
    """
    no_exentos = [s for emp_id, s in scores.items() if emp_id not in exentos and s > 0]
    if not no_exentos:
        # Sin base para promediar no se inventa nada: se deja lo que habia.
        return dict(scores)

    promedio = sum(no_exentos) / len(no_exentos)
    resultado = dict(scores)

    con_horas = {emp_id: horas[emp_id] for emp_id in exentos if emp_id in horas}

    if con_horas:
        valores = list(con_horas.values())
        media_horas = sum(valores) / len(valores)
        rango = max(valores) - min(valores)
    else:
        rango = 0.0
        media_horas = 0.0

    for emp_id in exentos:
        if emp_id not in scores:
            continue
        if emp_id in con_horas and rango > 0:
            desvio = (con_horas[emp_id] - media_horas) / rango
            resultado[emp_id] = round(promedio + desvio * MARGEN_DESEMPATE * promedio, 2)
        else:
            resultado[emp_id] = round(promedio, 2)

    return resultado
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/test_score_promedio.py -v
```

Esperado: PASS, 7 tests.

- [ ] **Step 5: Conectar la función al sync**

Modificar `sync_productivity_scores` en `app/routes/stats.py`. Hoy mapea `user_id -> score` y escribe directo; ahora tiene que:

1. Traer también `Employee.horas` en la query de usuarios (agregar el campo al `SELECT` que ya trae `id, employeeId`, con un `JOIN Employee`).
2. Armar `scores_por_empleado: dict[int, float]` (por `employeeId`, no por `user_id`) y `horas_por_empleado: dict[int, float]` salteando los `NULL`.
3. Llamar `empleados_exentos(db)` (importar de `app.database.score_exencion`).
4. Pasar todo por `aplicar_score_exentos`.
5. Escribir el resultado con el `UPDATE` que ya existe.

Conservar el `db.commit()` final y no cambiar la firma de la función (`sync_productivity_scores(db, stats_db) -> None`), porque `get_dashboard` la llama tal cual en `stats.py:105`.

- [ ] **Step 6: Correr la suite completa**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: todo verde, con los 10 tests nuevos sumados al total previo (247).

- [ ] **Step 7: Commit**

```bash
git add app/routes/stats.py tests/test_score_promedio.py
git commit -m "feat(score): los exentos reciben el promedio con desempate por asistencia"
```

---

## Task 3: Endpoint para marcar áreas exentas

**Files:**
- Modify: `app/routes/departments.py`
- Test: `tests/test_score_exencion_endpoint.py`

**Interfaces:**
- Consumes: `require_permission` de `app.auth_middleware`.
- Produces: `PUT /departments/{id}/score-exento` y `PUT /departments/office/{id}/score-exento`, ambos con body `{"exento": bool}`.

- [ ] **Step 1: Leer el router antes de tocarlo**

Leer `app/routes/departments.py` completo: ver el prefijo real del router, cómo están escritos los endpoints de oficina que ya existen (para seguir el mismo patrón de ruta y de respuesta) y qué permiso usan los `PUT` de ese archivo. **Usar el permiso que ya use ese router para modificar departamentos** (probablemente `organigrama.gestionar`), no inventar uno nuevo.

- [ ] **Step 2: Escribir el test que falla**

Crear `tests/test_score_exencion_endpoint.py` con `FakeSession`, verificando que el handler ejecuta un `UPDATE` sobre la tabla correcta con el valor booleano correcto, y que rechaza un body sin el campo `exento` con 400. Seguir el estilo de un test de endpoint que ya exista en `tests/` (buscar uno con `grep -l "def test_.*endpoint\|import.*routes" tests/*.py`) para importar el handler directamente en vez de levantar la app.

- [ ] **Step 3: Escribir los endpoints**

Dos handlers, uno por tabla, ambos con `dependencies=[Depends(require_permission("<el permiso del router>"))]`, validando que `exento` venga en el body y sea booleano, y devolviendo `{"success": True, "exento": <valor>}`.

- [ ] **Step 4: Correr los tests**

```bash
cd /c/Users/Emiliano/Documents/Backend_RRHH && venv/Scripts/python.exe -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/departments.py tests/test_score_exencion_endpoint.py
git commit -m "feat(score): endpoints para marcar un area como exenta"
```

---

## Task 4: Check en el frontend

**Files:**
- Modify: los componentes de detalle de departamento y de oficina en `RRHH/src/app/Componentes/Orgamograma/`
- Modify: `RRHH/src/app/Interfas/Interfaces.ts` (agregar `scoreExento?: boolean` a los tipos de departamento y oficina)

**Interfaces:**
- Consumes: los endpoints de la Task 3.

- [ ] **Step 1: Ubicar dónde se editan departamento y oficina**

```bash
cd /c/Users/Emiliano/Documents/RRHH
grep -rn "capacidadRequerida" src --include="*.tsx" | head
```

`capacidadRequerida` es un campo del mismo tipo (booleano/numérico por área, editable por RRHH) que ya está resuelto en la UI — **usar sus componentes como molde** para dónde va el check y cómo se guarda.

- [ ] **Step 2: Agregar el campo a los tipos**

En `Interfaces.ts`, agregar `scoreExento?: boolean` a las interfaces de departamento y de oficina. Opcional (`?`) a propósito: las respuestas viejas de la API no lo traen.

- [ ] **Step 3: Agregar el check en la UI**

Un checkbox etiquetado **"Exento del score de productividad"**, con un texto de ayuda debajo explicando por qué existe:

> El trabajo de esta área no queda registrado en los accesos al sistema. Sus empleados reciben el promedio general en lugar de un score medido, ordenados entre sí por asistencia.

Seguir el estilo de formulario del archivo (tokens semánticos, sin hex crudo) y llamar al endpoint correspondiente al togglear.

- [ ] **Step 4: Verificar**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit
```

Esperado: los mismos 27 errores preexistentes, ninguno nuevo en los archivos tocados.

```bash
npm run build
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(score): check para marcar un area como exenta del score"
```

---

## Task 5: Explicar el score en la pantalla de Estadísticas

**Files:**
- Modify: `RRHH/src/app/Componentes/ComponEstadistica/Productivity.tsx`

Sin esto, una autoridad ve a toda la gente de Sistemas con un número parecido y no sabe por qué. El dato tiene que explicarse solo.

- [ ] **Step 1: Traer el marcador de exención al front**

El endpoint del dashboard (`GET /stats/dashboard`, `app/routes/stats.py:101`) arma su respuesta en `fetch_all_employees_data`. Agregar ahí el dato de si el empleado es exento (vía el mismo `LEFT JOIN` de `empleados_exentos`), exponerlo en el objeto de cada empleado, y sumarlo al tipo del frontend.

- [ ] **Step 2: Marcar la fila en el ranking**

En la columna de Productividad, cuando el empleado es exento, mostrar un indicador discreto al lado del número (un ícono con `title`, o un badge chico usando los tokens `info-soft`) que aclare: **"Promedio del área — el trabajo de esta área no se mide por accesos al sistema"**.

Respetar la regla de que el color no sea el único indicador: el badge lleva texto o ícono, no solo un tono distinto.

- [ ] **Step 3: Verificar**

```bash
cd /c/Users/Emiliano/Documents/RRHH && npx tsc --noEmit && node scripts/check-contrast.mjs && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(score): marcar en el ranking a quienes reciben el promedio del area"
```

---

## Verificación final

- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -m pytest tests/ -q` — todo verde, acotado a `tests/`.
- [ ] `Backend_RRHH`: `venv/Scripts/python.exe -c "import app.main"` sin error.
- [ ] `RRHH`: `npx tsc --noEmit` en la línea base de 27 preexistentes, `node scripts/check-contrast.mjs` en verde, `npm run build` exitoso.
- [ ] Marcar un departamento como exento, abrir el dashboard y confirmar que su gente pasó de 0 al promedio, con números distintos entre sí si tienen saldo de horas cargado.

## Nota operativa

Hoy `Office` está vacía y 5 de 10 empleados no tienen departamento asignado. La exención se aplica por área, así que **un empleado sin departamento ni oficina nunca puede quedar exento**. Para que esto sirva de verdad en producción hace falta que RRHH complete la asignación de departamento/oficina de esa gente — no es parte de este plan, pero sin eso la mitad de la plantilla queda fuera del alcance del arreglo.
