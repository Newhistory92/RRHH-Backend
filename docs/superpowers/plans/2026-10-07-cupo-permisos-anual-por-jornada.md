# Cupo anual de permisos por jornada — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el cupo anual de horas de permiso salga de la jornada laboral de cada empleado en vez de estar fijo en 12 en el código, y que el empleado lo vea en una pantalla propia con sus permisos del año.

**Architecture:** El motor de cálculo (`asistencia_calc.calcular_anio`) deja de conocer la cifra y la recibe por parámetro, igual que ya recibe las tolerancias; así sigue siendo una función pura testeable sin base. Quien la resuelve es `asistencia_recalc.recalcular_anio`, leyendo `Employee.jornadaId → JornadaLaboral.horasPermisoAnual`. Editar el cupo dispara un recálculo masivo en segundo plano acotado a los empleados de esa jornada. La pantalla nueva lee totales ya resueltos de `JornadaDiaria`, sin reimplementar la regla.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15 (App Router), React, Tailwind con los tokens CSS del proyecto, lucide-react.

## Global Constraints

- **Dos repos.** Backend: `C:\Users\Emiliano\Documents\Backend_RRHH`. Frontend: `C:\Users\Emiliano\Documents\RRHH`. Cada tarea dice en cuál trabaja. Los commits van en el repo que corresponde, nunca cruzados.
- Columna nueva: `horasPermisoAnual DECIMAL(6,2) NOT NULL DEFAULT 12` en `JornadaLaboral`. El default es lo que hace que la migración no le cambie el cupo a nadie.
- `JornadaLaboral` es una tabla preexistente que este repo no crea: el `ALTER` va con el patrón `IF COL_LENGTH(...) IS NULL`, en su propio batch con su propio commit.
- **Empleado sin jornada asignada → cupo `0.0`.** Es deliberado: todo permiso regular le genera horas a recuperar desde el primer minuto, para que el legajo incompleto se note.
- **El permiso oficial no se toca.** Sigue siendo neutro en los dos sentidos: no consume cupo y no genera deuda. Ninguna tarea cambia esa lógica.
- Validación de `horasPermisoAnual`: se rechaza negativo y se rechaza por encima de `2000`.
- El recálculo al cambiar el cupo corre **en segundo plano**, **solo si el cupo cambió**, y **solo para el año en curso**.
- `GET /asistencia/mis-permisos` resuelve el empleado desde el token y **nunca** acepta `employeeId` por parámetro.
- Los totales de cupo consumido y deuda se **leen** de `JornadaDiaria`. Prohibido reimplementar la regla cronológica fuera de `calcular_anio`.
- Backend: `python -m pytest` desde `C:\Users\Emiliano\Documents\Backend_RRHH`. La suite pasa en verde (247 tests antes de este plan); el criterio es que siga en verde con los tests nuevos sumados.
- Frontend: **no tiene runner de tests.** La verificación es `npx tsc --noEmit -p tsconfig.json` (el repo arrastra ~27 errores previos no relacionados: el criterio es **no agregar ninguno nuevo**) más prueba en el navegador.
- Commits en español, estilo del repo (`feat(...)`, `fix(...)`, `test(...)`, `docs(...)`), terminando con una línea en blanco y `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Archivos con finales de línea LF y UTF-8.
- Los comentarios del repo están sin tildes en el backend (es la convención del código Python existente) y con tildes en el frontend.

---

## Estructura de archivos

### Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/database/asistencia.py` | **Modificar.** Suma el `ALTER` de la columna, y la función `mis_permisos` que arma la respuesta de la pantalla. |
| `app/services/asistencia_calc.py` | **Modificar.** `calcular_anio` recibe el cupo; desaparece `BANCO_PERMISO_ANUAL_HORAS`. |
| `app/services/asistencia_recalc.py` | **Modificar.** `_datos_empleado` lee el cupo de la jornada; `recalcular_anio` lo pasa; se agrega `recalcular_jornada`. |
| `app/routes/schedules.py` | **Modificar.** Lee y escribe la columna, valida, y dispara el recálculo en segundo plano. |
| `app/routes/asistencia.py` | **Modificar.** Suma `GET /asistencia/mis-permisos`. |
| `tests/test_asistencia_calc.py` | **Modificar.** Actualiza el único call site de `calcular_anio` y suma el caso de cupo 0. |
| `tests/test_dias_excluidos_por_baja.py` | **Modificar.** El fixture de `Employee` suma la columna nueva. |
| `tests/test_cupo_permisos.py` | **Nuevo.** El cupo sale de la jornada, `recalcular_jornada`, y la validación. |
| `tests/test_mis_permisos.py` | **Nuevo.** La respuesta del endpoint de la pantalla. |

### Frontend (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/screens/ConfiguracionLicencias/Screen.tsx` | **Modificar.** Tercer input en el modal de jornada y el cupo en la tarjeta. |
| `src/app/Componentes/ModalRRHH/LicenseModal.tsx` | **Modificar.** Saca la cifra "12 h" del texto del permiso oficial. |
| `src/app/Interfas/Interfaces.ts` | **Modificar.** `Page` suma `"mis-permisos"`. |
| `src/app/util/rbac.ts` | **Modificar.** `PAGE_CONFIG` suma la entrada. |
| `src/app/screens/MisPermisos/Screen.tsx` | **Nuevo.** La pantalla. |
| `src/app/page.tsx` | **Modificar.** El `case` del switch. |
| `src/app/Componentes/Shell/AppHeader.tsx` | **Modificar.** La entrada del menú del avatar en celular. |

**Orden de las tareas:** primero el backend completo (1 a 3), porque el frontend consume sus endpoints. Dentro del backend, primero el dato y el motor (1), después la configuración (2), después la lectura para la pantalla (3). El frontend va después: la configuración de RRHH (4) y la pantalla del empleado (5).

---

## Task 1: El cupo sale de la jornada

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/asistencia.py` (constantes de DDL, y `ensure_tables`)
- Modify: `app/services/asistencia_calc.py:19` (la constante), `:33-39` (`__all__`), `:248-262` (`calcular_anio`)
- Modify: `app/services/asistencia_recalc.py:48-62` (`_datos_empleado`), `:292-297` (la llamada al motor)
- Modify: `tests/test_asistencia_calc.py:281`
- Modify: `tests/test_dias_excluidos_por_baja.py:72-76`
- Test: `tests/test_cupo_permisos.py` (nuevo, la parte del cupo por jornada)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `calcular_anio(dias: list[EntradaDia], tolerancias: Tolerancias, banco_anual: float) -> list[ResultadoDia]`
  - `_datos_empleado` devuelve ahora también la clave `horasPermisoAnual` (puede venir `None`)
  - La columna `JornadaLaboral.horasPermisoAnual`

**Por qué las tres cosas van juntas:** cambiar la firma de `calcular_anio` sin cambiar su único llamador deja el código roto, y el llamador no puede resolver el cupo sin la columna. Es un cambio atómico.

- [ ] **Step 1: Escribir el test que falla, del motor con cupo 0**

En `tests/test_asistencia_calc.py`, agregar justo después de `test_el_banco_se_arrastra_cronologicamente_en_el_anio` (línea 288):

```python
def test_cupo_cero_convierte_todo_permiso_regular_en_deuda():
    """Es el caso del empleado sin jornada asignada: no tiene horas libres."""
    dias = [
        _dia(fecha=date(2026, 1, 7), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(2.0, False)]),
    ]
    enero, = c.calcular_anio(dias, TOL, 0.0)
    assert enero.permisoBanco == 0.0
    assert enero.permisoDeuda == 2.0
    assert enero.saldoDia == -2.0


def test_cupo_cero_no_afecta_al_permiso_oficial():
    """El oficial es la unica valvula que le queda a quien no tiene jornada."""
    dias = [
        _dia(fecha=date(2026, 1, 7), marcaciones=_marcas((8, 0), (16, 0)),
             permisos=[c.Permiso(2.0, True)]),
    ]
    enero, = c.calcular_anio(dias, TOL, 0.0)
    assert enero.permisoDeuda == 0.0
    assert enero.saldoDia == 0.0
```

Y cambiar la llamada de la línea 281, que hoy es `c.calcular_anio(dias, TOL)`, por:

```python
    enero, febrero = c.calcular_anio(dias, TOL, 12.0)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_asistencia_calc.py -v -k "cupo_cero or banco_se_arrastra"
```

Esperado: los tres FALLAN con `TypeError: calcular_anio() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Cambiar el motor para que reciba el cupo**

En `app/services/asistencia_calc.py`, borrar la línea 19 completa:

```python
BANCO_PERMISO_ANUAL_HORAS = 12.0
```

En el `__all__` (línea 33), sacar la constante de la lista. Queda:

```python
__all__ = [
    "DIAS_HABILES", "ESTADO_OK",
    "ESTADO_INCOMPLETA", "ESTADO_AUSENTE", "ESTADO_FERIADO", "ESTADO_LICENCIA",
    "ESTADO_JUSTIFICADA", "ESTADO_SIN_HORARIO", "HorarioDia", "Permiso",
    "EntradaDia", "ResultadoDia", "Tolerancias", "AjusteTolerancia",
    "calcular_dia", "calcular_anio",
]
```

Y reemplazar `calcular_anio` entera (líneas 248-262) por:

```python
def calcular_anio(dias: list[EntradaDia], tolerancias: Tolerancias,
                  banco_anual: float) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.

    El cupo entra por parametro y no como constante: cada jornada laboral
    tiene el suyo, y un empleado sin jornada asignada recibe 0.0. Quien lo
    resuelve es asistencia_recalc, que es el que habla con la base; aca se
    recibe ya decidido para que esta funcion siga siendo pura.
    """
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(d, tolerancias, banco_anual - consumido)
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
```

Actualizar también el docstring del módulo (línea 9-10), que hoy dice "El arrastre del banco anual de permisos es responsabilidad de calcular_anio". Reemplazar ese párrafo por:

```
La unidad de calculo es el dia. El arrastre del banco anual de permisos es
responsabilidad de calcular_anio, que recorre los dias en orden cronologico
con el cupo que le pasan: el numero no vive aca, sale de la jornada laboral
del empleado.
```

- [ ] **Step 4: Correr los tests del motor para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_asistencia_calc.py -v
```

Esperado: PASS todos, incluidos los tres del paso 1.

- [ ] **Step 5: Escribir el test que falla, del cupo leído de la jornada**

Crear `tests/test_cupo_permisos.py`:

```python
"""
El cupo anual de permisos sale de la jornada laboral del empleado.

La parte pura (como se consume el cupo) se testea en test_asistencia_calc.
Aca se testea el cableado: que recalcular_anio lea el cupo de la jornada y
que un empleado sin jornada reciba 0.
"""

from datetime import date

from app.services.asistencia_recalc import recalcular_anio
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db(cupo):
    """FakeSession con un empleado cuya jornada declara `cupo` horas."""
    return FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": cupo,
        }],
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "FROM EmployeeBaja": [],
    })


def test_el_select_del_empleado_trae_el_cupo_de_la_jornada():
    """Sin el JOIN, recalcular_anio no tendria de donde sacar el cupo."""
    db = _db(12.0)
    recalcular_anio(db, 8, 2026, hoy=HOY)
    sql = db.sql_ejecutado()
    assert "JornadaLaboral" in sql
    assert "horasPermisoAnual" in sql


def test_un_empleado_sin_jornada_no_rompe_el_recalculo():
    """
    jornadaId null hace que el LEFT JOIN devuelva None en el cupo. Tiene que
    resolverse como 0.0 y no explotar en el float().
    """
    db = _db(None)
    # No lanza: es la afirmacion. El cupo 0 en si se testea en el motor.
    recalcular_anio(db, 8, 2026, hoy=HOY)
    assert db.commits >= 1
```

- [ ] **Step 6: Correr para verificar que falla**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_cupo_permisos.py -v
```

Esperado: `test_el_select_del_empleado_trae_el_cupo_de_la_jornada` FALLA (`assert "JornadaLaboral" in sql`), y `test_un_empleado_sin_jornada_no_rompe_el_recalculo` FALLA con `TypeError: calcular_anio() missing 1 required positional argument: 'banco_anual'`.

- [ ] **Step 7: Agregar la columna a la base**

En `app/database/asistencia.py`, agregar la constante después de `ALTER_CONFIG_DIAS_RACHA_SQL` (que termina en la línea 102):

```python
# JornadaLaboral es preexistente: este repo no la crea, solo le suma la
# columna. El DEFAULT 12 es lo que hace que la migracion no le cambie el cupo
# a nadie: las jornadas que ya existen arrancan con el valor que regia cuando
# el numero estaba fijo en el codigo.
ALTER_JORNADA_CUPO_PERMISO_SQL = """
IF COL_LENGTH('JornadaLaboral','horasPermisoAnual') IS NULL
ALTER TABLE JornadaLaboral ADD horasPermisoAnual DECIMAL(6,2) NOT NULL DEFAULT 12;
"""
```

Y en `ensure_tables`, después del `db.commit()` de la línea 174 (el que sigue a `ALTER_CONFIG_DIAS_RACHA_SQL`) y antes del `for columna in COLUMNAS_A_ELIMINAR`:

```python
    db.execute(text(ALTER_JORNADA_CUPO_PERMISO_SQL))
    db.commit()
```

- [ ] **Step 8: Leer el cupo en el recálculo**

En `app/services/asistencia_recalc.py`, reemplazar `_datos_empleado` entera (líneas 48-62) por:

```python
def _datos_empleado(db: Session, employee_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT e.id, e.biometricoId,
               h.horaInicio, h.horaFin, h.horasTrabajo,
               c.fechaIngreso,
               j.horasPermisoAnual
        FROM Employee e
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        LEFT JOIN (
            SELECT employeeId, MIN(fechaIngreso) AS fechaIngreso
            FROM CondicionLaboral
            GROUP BY employeeId
        ) c ON c.employeeId = e.id
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None
```

Y en `recalcular_anio`, reemplazar la llamada al motor (líneas 292-297) por:

```python
    # Sin jornada asignada el LEFT JOIN devuelve None y el cupo queda en 0:
    # es deliberado. A esa persona todo permiso regular le genera horas a
    # recuperar, para que el legajo incompleto se note en vez de quedar
    # tapado por un valor por omision.
    banco_anual = float(emp.get("horasPermisoAnual") or 0)
    resultados = calcular_anio(entradas, Tolerancias(
        entradaMin=cfg["toleranciaEntradaMin"],
        salidaMin=cfg["toleranciaSalidaMin"],
        estrictaEntradaMin=cfg["toleranciaEstrictaEntradaMin"],
        estrictaSalidaMin=cfg["toleranciaEstrictaSalidaMin"],
    ), banco_anual)
```

- [ ] **Step 9: Actualizar el fixture del test de bajas**

En `tests/test_dias_excluidos_por_baja.py`, la fila de `Employee` del helper `_db` (líneas 72-76) pasa a:

```python
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": 12.0,
        }],
```

- [ ] **Step 10: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde. Si algún test de asistencia falla con `KeyError: 'horasPermisoAnual'`, es un fixture de `FakeSession` al que le falta la clave: agregársela como en el paso 9.

- [ ] **Step 11: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/asistencia.py app/services/asistencia_calc.py app/services/asistencia_recalc.py tests/test_asistencia_calc.py tests/test_dias_excluidos_por_baja.py tests/test_cupo_permisos.py
git commit -m "$(cat <<'EOF'
feat(asistencia): el cupo anual de permisos sale de la jornada laboral

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Configurar el cupo y recalcular en segundo plano

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/services/asistencia_recalc.py` (agregar `recalcular_jornada` después de `recalcular_todos`, que termina en la línea 347)
- Modify: `app/routes/schedules.py:16-27` (`get_schedules_regimes`), `:29-55` (`save_jornada`)
- Test: `tests/test_cupo_permisos.py` (sumar los casos de `recalcular_jornada` y de validación)

**Interfaces:**
- Consumes: la columna `JornadaLaboral.horasPermisoAnual` y `recalcular_anio` de la Task 1.
- Produces: `recalcular_jornada(db: Session, jornada_id: int, anio: int) -> dict` con la forma `{"procesados": int, "filas": int, "errores": list}`, igual que `recalcular_todos`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_cupo_permisos.py`:

```python
# -- recalcular_jornada --------------------------------------------------------

def _db_jornada(ids_empleados):
    """FakeSession para recalcular_jornada: la consulta de ids y el log."""
    return FakeSession({
        "OUTPUT INSERTED.id": [{"id": 99}],
        "WHERE jornadaId": [{"id": eid} for eid in ids_empleados],
    })


def test_recalcular_jornada_solo_toca_los_empleados_de_esa_jornada(monkeypatch):
    """El filtro es lo que evita barrer la nomina entera por un cambio de cupo."""
    from app.services import asistencia_recalc as r

    llamados = []
    monkeypatch.setattr(r, "recalcular_anio",
                        lambda db, eid, anio: llamados.append((eid, anio)) or 1)

    db = _db_jornada([3, 7])
    resultado = r.recalcular_jornada(db, jornada_id=2, anio=2026)

    assert llamados == [(3, 2026), (7, 2026)]
    assert resultado["procesados"] == 2
    assert resultado["filas"] == 2
    assert resultado["errores"] == []
    # El filtro tiene que estar en el SQL, no resolverse en Python.
    assert "jornadaId" in db.sql_ejecutado()


def test_recalcular_jornada_sigue_cuando_un_empleado_falla(monkeypatch):
    """Un legajo roto no puede dejar a los demas con el cupo viejo."""
    from app.services import asistencia_recalc as r

    def fake(db, eid, anio):
        if eid == 3:
            raise RuntimeError("legajo roto")
        return 1

    monkeypatch.setattr(r, "recalcular_anio", fake)

    db = _db_jornada([3, 7])
    resultado = r.recalcular_jornada(db, jornada_id=2, anio=2026)

    assert resultado["procesados"] == 1
    assert len(resultado["errores"]) == 1
    assert resultado["errores"][0]["employeeId"] == 3
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_cupo_permisos.py -v -k recalcular_jornada
```

Esperado: los dos FALLAN con `AttributeError: module 'app.services.asistencia_recalc' has no attribute 'recalcular_jornada'`.

- [ ] **Step 3: Escribir `recalcular_jornada`**

En `app/services/asistencia_recalc.py`, agregar después de `recalcular_todos` (que termina en la línea 347):

```python
def recalcular_jornada(db: Session, jornada_id: int, anio: int) -> dict:
    """
    Recalcula el anio de los empleados de una jornada. Es lo que se dispara al
    cambiarle el cupo de permisos: el banco se consume en orden cronologico,
    asi que mover el cupo cambia retroactivamente que horas fueron libres y
    cuales quedaron como deuda, para todo el anio.

    Hermana de recalcular_todos: misma auditoria y misma garantia de que un
    empleado que falla se registra y no aborta el resto. Lo unico que cambia
    es a quien se le aplica.
    """
    log_id = abrir_recalculo(db, "cupo_permiso", None, None,
                             date(anio, 1, 1), date(anio, 12, 31))
    ids = [r["id"] for r in db.execute(text("""
        SELECT id FROM Employee
        WHERE jornadaId = :jornada AND biometricoId IS NOT NULL
        ORDER BY id
    """), {"jornada": jornada_id}).mappings().all()]

    filas = 0
    ok = 0
    errores = []
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo por cupo fallido para empleado %s: %s", eid, e)
            errores.append({"employeeId": eid, "error": str(e)})

    cerrar_recalculo(db, log_id, ok, filas, errores)
    return {"procesados": ok, "filas": filas, "errores": errores}
```

También actualizar el docstring del módulo (líneas 10-14), que hoy enumera quién recalcula a quién. Reemplazar ese párrafo por:

```
Lo que si varia es a quien se recalcula. recalcular_todos barre la nomina
entera para el job nocturno; recalcular_marcados elige solo a los que acaban de
fichar, que es lo que hace viable correrlo cada pocos minutos; recalcular_jornada
toma a los de una jornada, que es lo que hace falta cuando cambia su cupo de
permisos. Los tres terminan llamando a recalcular_anio, asi que el invariante de
arriba se mantiene: la seleccion cambia, el calculo no.
```

- [ ] **Step 4: Correr para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_cupo_permisos.py -v
```

Esperado: PASS todos.

- [ ] **Step 5: Escribir el test de validación que falla**

Agregar al final de `tests/test_cupo_permisos.py`:

```python
# -- Validacion del cupo -------------------------------------------------------

import pytest
from fastapi import HTTPException

from app.routes.schedules import _validar_cupo


def test_el_cupo_no_puede_ser_negativo():
    with pytest.raises(HTTPException) as e:
        _validar_cupo(-1)
    assert e.value.status_code == 400


@pytest.mark.parametrize("valor", [0, 12, 12.5, 2000])
def test_los_cupos_razonables_pasan(valor):
    assert _validar_cupo(valor) == float(valor)


def test_el_cupo_rechaza_el_error_de_tipeo():
    """
    120 en vez de 12 regala diez veces el cupo sin que nadie se entere. El tope
    no es una regla de negocio: es el atajo contra ese error.
    """
    with pytest.raises(HTTPException) as e:
        _validar_cupo(2001)
    assert e.value.status_code == 400


def test_el_cupo_ausente_vale_cero():
    """
    Un POST viejo sin el campo no puede explotar; se interpreta como sin cupo.
    """
    assert _validar_cupo(None) == 0.0
```

- [ ] **Step 6: Correr para verificar que falla**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_cupo_permisos.py -v -k cupo
```

Esperado: FALLA en el import con `ImportError: cannot import name '_validar_cupo' from 'app.routes.schedules'`.

- [ ] **Step 7: Cablear la ruta de configuración**

En `app/routes/schedules.py`, reemplazar los imports del encabezado (líneas 1-7) por:

```python
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.database.asistencia import ensure_tables as ensure_asistencia
from app.services.asistencia_recalc import recalcular_jornada
from app.auth_middleware import require_auth, require_permission

router = APIRouter(prefix="/schedules", tags=["Schedules"])
```

(Conservar el `get_db` que ya está debajo, sin cambios.)

Agregar el validador justo después de `get_db`:

```python
# El tope no es una regla de negocio sino el atajo contra el error de tipeo,
# que aca cuesta caro: cargar 120 en vez de 12 regala diez veces el cupo y no
# lo nota nadie. 2000 h es mas que un anio laboral completo.
CUPO_PERMISO_MAX_HORAS = 2000.0


def _validar_cupo(valor) -> float:
    """Normaliza horasPermisoAnual a float, o 400 si no tiene sentido."""
    if valor is None:
        return 0.0
    try:
        cupo = float(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="horasPermisoAnual debe ser un numero")
    if cupo < 0:
        raise HTTPException(status_code=400,
                            detail="horasPermisoAnual no puede ser negativo")
    if cupo > CUPO_PERMISO_MAX_HORAS:
        raise HTTPException(
            status_code=400,
            detail=f"horasPermisoAnual no puede superar {int(CUPO_PERMISO_MAX_HORAS)} horas")
    return cupo
```

Reemplazar `get_schedules_regimes` (líneas 16-27) por:

```python
@router.get("/regimes", dependencies=[Depends(require_auth)])
def get_schedules_regimes(db: Session = Depends(get_db)):
    """Get all work regimes (jornadas and horarios)."""
    # La columna del cupo la crea ensure_tables del modulo de asistencia: este
    # router puede ser el primero que la toque en una base recien migrada.
    ensure_asistencia(db)
    try:
        jornadas = db.execute(text(
            "SELECT id, nombre, horasDia, horasPermisoAnual FROM JornadaLaboral"
        )).mappings().all()
        horarios = db.execute(text("SELECT id, horaInicio, horaFin, horasTrabajo FROM Horario")).mappings().all()
        return {
            "jornadas": [
                {**dict(j), "horasPermisoAnual": float(j["horasPermisoAnual"] or 0)}
                for j in jornadas
            ],
            "horarios": [dict(h) for h in horarios]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener regímenes horarios: {str(e)}")
```

Reemplazar `save_jornada` (líneas 29-55) por:

```python
@router.post("/jornadas", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def save_jornada(background_tasks: BackgroundTasks, data: dict = Body(...),
                 db: Session = Depends(get_db)):
    """
    Create or update a JornadaLaboral.

    Cambiar el cupo de permisos obliga a recalcular el anio de todos los
    empleados de esta jornada, porque el banco se consume en orden
    cronologico. Va en segundo plano: el cupo se edita rara vez y la pantalla
    de configuracion no puede quedarse colgada esperando a la nomina entera.
    """
    ensure_asistencia(db)
    nombre = data.get("nombre")
    horas_dia = data.get("horasDia")
    jornada_id = data.get("id")

    if not nombre or horas_dia is None:
        raise HTTPException(status_code=400, detail="Nombre y horas al día son requeridos")

    cupo = _validar_cupo(data.get("horasPermisoAnual"))

    try:
        if jornada_id:
            # Se lee el cupo anterior antes de escribir: si no cambio, no hay
            # nada que recalcular y un renombre no dispara una pasada masiva
            # al vacio.
            previo = db.execute(text(
                "SELECT horasPermisoAnual FROM JornadaLaboral WHERE id = :id"
            ), {"id": jornada_id}).mappings().first()
            cupo_previo = float(previo["horasPermisoAnual"] or 0) if previo else None

            db.execute(text("""
                UPDATE JornadaLaboral
                SET nombre = :nombre, horasDia = :horasDia,
                    horasPermisoAnual = :cupo
                WHERE id = :id
            """), {"nombre": nombre, "horasDia": float(horas_dia),
                   "cupo": cupo, "id": jornada_id})
            db.commit()

            if cupo_previo is not None and cupo_previo != cupo:
                # El background task necesita su propia sesion porque la del
                # request se cierra cuando el handler retorna.
                def _recalcular(jornada_: int, anio_: int):
                    _db = SessionLocal()
                    try:
                        recalcular_jornada(_db, jornada_, anio_)
                    except Exception as e:
                        log.warning("Recalculo por cambio de cupo fallido en jornada %s: %s",
                                    jornada_, e)
                    finally:
                        _db.close()

                from datetime import date as _date
                background_tasks.add_task(_recalcular, int(jornada_id), _date.today().year)
                return {"success": True, "recalculo": "en_proceso"}
        else:
            # Una jornada nueva todavia no tiene empleados asignados: no hay
            # nada que recalcular.
            db.execute(text("""
                INSERT INTO JornadaLaboral (nombre, horasDia, horasPermisoAnual)
                VALUES (:nombre, :horasDia, :cupo)
            """), {"nombre": nombre, "horasDia": float(horas_dia), "cupo": cupo})
            db.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar jornada laboral: {str(e)}")
```

Agregar el logger al encabezado del archivo, después de los imports:

```python
import logging

log = logging.getLogger(__name__)
```

- [ ] **Step 8: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/services/asistencia_recalc.py app/routes/schedules.py tests/test_cupo_permisos.py
git commit -m "$(cat <<'EOF'
feat(schedules): el cupo de permisos se configura por jornada y recalcula de fondo

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: El endpoint de "Mis permisos"

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/asistencia.py` (agregar `mis_permisos` al final del archivo)
- Modify: `app/routes/asistencia.py:18-23` (el import) y después de `get_mi_asistencia` (que termina en la línea 247)
- Test: `tests/test_mis_permisos.py` (nuevo)

**Interfaces:**
- Consumes: la columna `JornadaLaboral.horasPermisoAnual` de la Task 1.
- Produces: `GET /asistencia/mis-permisos?anio=YYYY` con esta forma exacta, que la Task 5 consume:

```json
{
  "anio": 2026,
  "cupoAnual": 12.0,
  "consumido": 8.5,
  "restante": 3.5,
  "deuda": 2.0,
  "permisos": [
    {"id": 4, "fecha": "2026-03-04", "exitTime": 10.5, "returnTime": 12.0,
     "horas": 1.5, "oficial": false}
  ],
  "aniosConDatos": [2026, 2025]
}
```

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_mis_permisos.py`:

```python
"""
La lectura que alimenta la pantalla "Mis permisos".

Lo importante que se testea aca: los totales se LEEN de JornadaDiaria, no se
recalculan. Una segunda implementacion de la regla cronologica se
desincronizaria del motor sin que nadie lo note.
"""

from datetime import date

from app.database.asistencia import mis_permisos
from tests.fakes import FakeSession


def _db(cupo=12.0, consumido=8.5, deuda=2.0, permisos=None, anios=None):
    return FakeSession({
        "FROM Employee e": [{"cupo": cupo}],
        "FROM JornadaDiaria": [{"consumido": consumido, "deuda": deuda}],
        "ORDER BY date DESC": permisos if permisos is not None else [],
        "SELECT DISTINCT YEAR(date)": anios if anios is not None else [],
    })


def test_los_totales_salen_de_jornada_diaria():
    r = mis_permisos(_db(), 8, 2026)
    assert r["cupoAnual"] == 12.0
    assert r["consumido"] == 8.5
    assert r["deuda"] == 2.0
    assert r["restante"] == 3.5


def test_el_restante_no_baja_de_cero():
    """
    Si el consumido supera el cupo -posible si RRHH lo bajo despues de que la
    persona ya habia pedido permisos- el restante es 0, no un negativo que se
    leeria como deuda duplicada.
    """
    r = mis_permisos(_db(cupo=4.0, consumido=10.0), 8, 2026)
    assert r["restante"] == 0.0


def test_sin_jornada_el_cupo_es_cero():
    r = mis_permisos(_db(cupo=None, consumido=0.0, deuda=6.0), 8, 2026)
    assert r["cupoAnual"] == 0.0
    assert r["restante"] == 0.0
    assert r["deuda"] == 6.0


def test_los_permisos_se_serializan_con_la_fecha_en_iso():
    permisos = [{"id": 4, "date": date(2026, 3, 4), "exitTime": 10.5,
                 "returnTime": 12.0, "hours": 1.5, "oficial": False}]
    r = mis_permisos(_db(permisos=permisos), 8, 2026)
    assert r["permisos"] == [{
        "id": 4, "fecha": "2026-03-04", "exitTime": 10.5,
        "returnTime": 12.0, "horas": 1.5, "oficial": False,
    }]


def test_el_anio_en_curso_esta_siempre_en_el_selector():
    """
    Aunque no tenga ningun permiso: es el anio que la pantalla abre por
    defecto y tiene que poder mostrar el cupo completo sin consumir.
    """
    r = mis_permisos(_db(anios=[{"anio": 2024}]), 8, 2026)
    assert date.today().year in r["aniosConDatos"]
    assert 2024 in r["aniosConDatos"]
    # Mas nuevo primero: es el orden en que se quieren leer.
    assert r["aniosConDatos"] == sorted(r["aniosConDatos"], reverse=True)
```

- [ ] **Step 2: Correr para verificar que falla**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_mis_permisos.py -v
```

Esperado: FALLA en el import con `ImportError: cannot import name 'mis_permisos' from 'app.database.asistencia'`.

- [ ] **Step 3: Escribir `mis_permisos`**

Agregar al final de `app/database/asistencia.py`:

```python
def mis_permisos(db: Session, employee_id: int, anio: int) -> dict:
    """
    Los permisos de un empleado en un anio, y como quedo su cupo.

    Los totales se leen de JornadaDiaria: ahi el motor ya dejo resuelto el
    reparto entre lo que cubrio el cupo (permisoBanco) y lo que paso a horas a
    recuperar (permisoDeuda). Aca NO se vuelve a aplicar la regla cronologica
    -eso vive solo en asistencia_calc.calcular_anio-, porque una segunda
    implementacion de la misma regla se desincroniza sin que nadie lo note.
    """
    cupo_fila = db.execute(text("""
        SELECT j.horasPermisoAnual AS cupo
        FROM Employee e
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        WHERE e.id = :emp
    """), {"emp": employee_id}).mappings().first()
    cupo = float(cupo_fila["cupo"] or 0) if cupo_fila else 0.0

    totales = db.execute(text("""
        SELECT COALESCE(SUM(permisoBanco), 0) AS consumido,
               COALESCE(SUM(permisoDeuda), 0) AS deuda
        FROM JornadaDiaria
        WHERE employeeId = :emp AND YEAR(fecha) = :anio
    """), {"emp": employee_id, "anio": anio}).mappings().first()
    consumido = float(totales["consumido"] or 0) if totales else 0.0
    deuda = float(totales["deuda"] or 0) if totales else 0.0

    filas = db.execute(text("""
        SELECT id, date, exitTime, returnTime, hours, oficial
        FROM Permission
        WHERE employeeId = :emp AND YEAR(date) = :anio
        ORDER BY date DESC, exitTime DESC
    """), {"emp": employee_id, "anio": anio}).mappings().all()

    anios_con_permisos = db.execute(text("""
        SELECT DISTINCT YEAR(date) AS anio FROM Permission
        WHERE employeeId = :emp
    """), {"emp": employee_id}).mappings().all()

    return {
        "anio": anio,
        "cupoAnual": round(cupo, 2),
        "consumido": round(consumido, 2),
        # Nunca negativo: si RRHH bajo el cupo despues de que la persona ya
        # habia pedido permisos, el excedente se cuenta como deuda, no como
        # un restante en rojo que se leeria dos veces.
        "restante": round(max(cupo - consumido, 0.0), 2),
        "deuda": round(deuda, 2),
        "permisos": [{
            "id": int(f["id"]),
            "fecha": (f["date"].date() if isinstance(f["date"], datetime)
                      else f["date"]).isoformat(),
            "exitTime": float(f["exitTime"] or 0),
            "returnTime": float(f["returnTime"] or 0),
            "horas": float(f["hours"] or 0),
            "oficial": bool(f["oficial"]),
        } for f in filas],
        # El anio en curso siempre entra, tenga permisos o no: es el que la
        # pantalla abre por defecto.
        "aniosConDatos": sorted(
            {int(a["anio"]) for a in anios_con_permisos} | {date.today().year},
            reverse=True,
        ),
    }
```

- [ ] **Step 4: Correr para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_mis_permisos.py -v
```

Esperado: PASS todos.

- [ ] **Step 5: Exponer el endpoint**

En `app/routes/asistencia.py`, agregar `mis_permisos` al import de la línea 18, que queda:

```python
from app.database.asistencia import (
    biometricos_huerfanos, dias_abuso_de, dias_abuso_todos, ensure_tables,
    get_config, get_jornada, jornadas_abuso_todos, jornadas_de,
    jornadas_incompletas, mis_permisos, reset_inicio_modulo, saldo_acumulado,
    tablero, update_config,
)
```

Y agregar el handler justo después de `get_mi_asistencia` (que termina en la línea 247), antes de `GET /config`:

```python
@router.get("/mis-permisos", dependencies=[Depends(require_auth)])
def get_mis_permisos(anio: int | None = None,
                     usuario: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """
    Los permisos propios de un anio y el estado del cupo anual.

    Mismo contrato que GET /asistencia/mi: el empleado sale del token y no se
    acepta employeeId por parametro, asi que nadie puede leer permisos ajenos.

    Un anio sin permisos responde 200 con la lista vacia y el cupo completo,
    no 404: la pantalla tiene que poder decir "no pediste permisos ese anio".
    """
    ensure_tables(db)
    employee_id = usuario.get("employeeId")
    if employee_id is None:
        raise HTTPException(status_code=403,
                            detail="Tu usuario no esta vinculado a un legajo")
    return mis_permisos(db, int(employee_id), anio or date.today().year)
```

- [ ] **Step 6: Verificar a mano que el endpoint responde**

Levantar el backend y pedirlo con un token de un empleado con legajo:

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m uvicorn app.main:app --reload --port 8000
```

En otra terminal, con `TOKEN` puesto a un JWT válido:

```bash
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/asistencia/mis-permisos?anio=2026"
```

Esperado: JSON con las claves `anio`, `cupoAnual`, `consumido`, `restante`, `deuda`, `permisos` y `aniosConDatos`. Si el usuario no tiene legajo vinculado, 403 con "Tu usuario no esta vinculado a un legajo".

- [ ] **Step 7: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/asistencia.py app/routes/asistencia.py tests/test_mis_permisos.py
git commit -m "$(cat <<'EOF'
feat(asistencia): endpoint de permisos propios con el estado del cupo anual

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: El input del cupo en Configuración

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/screens/ConfiguracionLicencias/Screen.tsx:46-50` (la interfaz), `:141` (el estado inicial), `:626` (el botón de nueva jornada), `:633-644` (la tarjeta), `:891-894` (el modal)
- Modify: `src/app/Componentes/ModalRRHH/LicenseModal.tsx:248-250` (el texto)

**Interfaces:**
- Consumes: `GET /schedules/regimes` y `POST /schedules/jornadas` con el campo `horasPermisoAnual: number` (Task 2).
- Produces: nada que consuman otras tareas.

- [ ] **Step 1: Sumar el campo a la interfaz y al estado**

En `src/app/screens/ConfiguracionLicencias/Screen.tsx`, la interfaz de la línea 46 pasa a:

```tsx
interface JornadaLaboral {
    id?: number;
    nombre: string;
    horasDia: number;
    /** Horas de permiso libres por año antes de que empiecen a acumular
     *  horas a recuperar. */
    horasPermisoAnual: number;
}
```

El estado inicial de la línea 141 pasa a:

```tsx
    const [jornadaForm, setJornadaForm] = useState<JornadaLaboral>({ nombre: "", horasDia: 8, horasPermisoAnual: 12 });
```

Y el reset del botón "Nueva Jornada" (línea 626), que hoy hace `setJornadaForm({ nombre: "", horasDia: 8 })`, pasa a:

```tsx
                                            onClick={() => { setJornadaForm({ nombre: "", horasDia: 8, horasPermisoAnual: 12 }); setIsEditingJornada(false); setShowJornadaModal(true); }}
```

- [ ] **Step 2: Agregar el tercer input al modal**

En el mismo archivo, después del `<div>` de "Horas Diarias" (que cierra en la línea 894) y antes del `<div className="flex gap-3 pt-4">`:

```tsx
                            <div>
                                <label className="block text-sm font-bold text-foreground mb-1">Horas de Permiso al Año</label>
                                <input
                                    type="number"
                                    required
                                    min="0"
                                    max="2000"
                                    step="0.5"
                                    className="w-full px-3 py-2 border rounded-xl"
                                    value={jornadaForm.horasPermisoAnual}
                                    onChange={e => setJornadaForm({ ...jornadaForm, horasPermisoAnual: parseFloat(e.target.value) })}
                                />
                                <p className="text-xs text-muted-foreground mt-1">
                                    Horas libres por año para permisos. Agotadas, los permisos
                                    siguientes pasan a contarse como horas a recuperar. Cambiarlo
                                    recalcula el año en curso de todos los agentes de esta jornada.
                                </p>
                            </div>
```

- [ ] **Step 3: Mostrar el cupo en la tarjeta de la jornada**

Reemplazar el `<p>` de la línea 637, que hoy es:

```tsx
                                                    <p className="text-xs text-muted-foreground mt-1 font-mono">{j.horasDia} hrs/día</p>
```

por:

```tsx
                                                    <p className="text-xs text-muted-foreground mt-1 font-mono">{j.horasDia} hrs/día</p>
                                                    <p className="text-xs text-muted-foreground font-mono">{j.horasPermisoAnual ?? 0} hrs permiso/año</p>
```

- [ ] **Step 4: Sacar la cifra fija del texto del permiso oficial**

En `src/app/Componentes/ModalRRHH/LicenseModal.tsx`, reemplazar el `<p>` de las líneas 248-250 por:

```tsx
            <p className="text-xs text-muted-foreground mt-1">
              Un permiso oficial no consume el cupo anual de permisos del agente
              ni genera horas a recuperar.
            </p>
```

(El cupo ahora depende de la jornada de cada agente, así que la cifra fija de "12 h" quedaba mintiendo.)

- [ ] **Step 5: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "ConfiguracionLicencias|LicenseModal"
```

Esperado: sin salida.

- [ ] **Step 6: Verificar en el navegador**

Con el backend corriendo y `npm run dev` en el frontend, entrando con un usuario con permiso `licencias.configurar`:

1. Configuración → pestaña "Régimen Horario": cada tarjeta de jornada muestra ahora dos líneas, las horas por día y las horas de permiso al año.
2. "Nueva Jornada": el modal tiene tres campos y el de permiso arranca en 12.
3. Editar una jornada existente: el modal trae el cupo guardado, no 12 fijo.
4. Guardar con el cupo cambiado: toast de éxito, y al recargar la pantalla el valor nuevo persiste.
5. Guardar con un valor negativo: el `min="0"` del input lo bloquea en el navegador; forzándolo por la API el backend responde 400.
6. En el perfil de un empleado, abrir el modal de registrar permiso: el texto del permiso oficial ya no menciona "12 h".

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/screens/ConfiguracionLicencias/Screen.tsx src/app/Componentes/ModalRRHH/LicenseModal.tsx
git commit -m "$(cat <<'EOF'
feat(configuracion): el cupo anual de permisos se configura por jornada

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: La pantalla "Mis permisos"

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts:696-715` (el tipo `Page`)
- Modify: `src/app/util/rbac.ts:42` (agregar la entrada después de `mi-asistencia`)
- Create: `src/app/screens/MisPermisos/Screen.tsx`
- Modify: `src/app/page.tsx` (el import y el `case`)
- Modify: `src/app/Componentes/Shell/AppHeader.tsx` (el ítem del menú del avatar)

**Interfaces:**
- Consumes: `GET /asistencia/mis-permisos?anio=YYYY` de la Task 3, con la forma exacta documentada ahí.
- Produces: la página `"mis-permisos"` del tipo `Page`.

- [ ] **Step 1: Sumar la página al tipo y al RBAC**

En `src/app/Interfas/Interfaces.ts`, agregar la variante al tipo `Page` después de `"mi-asistencia"` (línea 699):

```ts
  | "mis-permisos"
```

En `src/app/util/rbac.ts`, agregar la entrada a `PAGE_CONFIG` después de la de `mi-asistencia` (línea 42):

```ts
  // Sin ocultaSiTienePermiso a proposito: si se escondiera del sidebar para
  // los roles de gestion, RRHH y ADMIN se quedarian sin ningun lugar donde
  // ver sus PROPIOS permisos, porque la entrada del menu del avatar esta
  // condicionada a tener navegacion simple.
  { id: "mis-permisos", label: "Mis Permisos", icon: "CalendarClock", section: "Agente", permiso: "asistencia.propia" },
```

- [ ] **Step 2: Crear la pantalla**

Crear `src/app/screens/MisPermisos/Screen.tsx`:

```tsx
"use client";

// Los permisos propios del año y cómo quedó el cupo anual de horas libres.
//
// El cupo sale de la jornada laboral del agente, y las horas que se pasan de
// ese cupo son las que hay que recuperar. Los totales vienen ya resueltos del
// backend: acá no se recalcula nada.

import { useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";

interface PermisoPropio {
  id: number;
  fecha: string;
  exitTime: number;
  returnTime: number;
  horas: number;
  oficial: boolean;
}

interface MisPermisosResp {
  anio: number;
  cupoAnual: number;
  consumido: number;
  restante: number;
  deuda: number;
  permisos: PermisoPropio[];
  aniosConDatos: number[];
}

const fmtHoras = (h: number) => {
  const horas = Math.floor(h);
  const min = Math.round((h - horas) * 60);
  return `${horas}h ${String(min).padStart(2, "0")}m`;
};

/** El backend manda las horas del día como decimal: 10.5 es 10:30. */
const fmtHoraDelDia = (h: number) => {
  const horas = Math.floor(h);
  const min = Math.round((h - horas) * 60);
  return `${String(horas).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
};

const ANIO_ACTUAL = new Date().getFullYear();

export default function MisPermisos() {
  const [anio, setAnio] = useState(ANIO_ACTUAL);
  const [datos, setDatos] = useState<MisPermisosResp | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    apiClient
      .get<MisPermisosResp>(`/asistencia/mis-permisos?anio=${anio}`)
      .then((r) => {
        // Guard contra respuestas de un año que ya no es el elegido.
        if (vigente) setDatos(r);
      })
      .catch((e) => {
        if (vigente) {
          setError(e instanceof Error ? e.message : "No se pudieron cargar tus permisos");
        }
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [anio]);

  const sinJornada = datos !== null && datos.cupoAnual === 0;

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <h1 className="font-heading text-2xl text-foreground mb-6">Mis permisos</h1>

      <div className="bg-card rounded-lg shadow-sm p-4 border border-border mb-6 flex flex-wrap gap-4 items-end">
        <div>
          <label htmlFor="anio-permisos" className="block text-sm font-medium text-foreground mb-1">
            Año
          </label>
          <select
            id="anio-permisos"
            value={anio}
            onChange={(e) => setAnio(Number(e.target.value))}
            className="border border-border rounded-md px-3 py-1.5 text-sm bg-background text-foreground"
          >
            {(datos?.aniosConDatos ?? [ANIO_ACTUAL]).map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
      </div>

      {cargando ? (
        <div className="p-8 text-center text-muted-foreground">
          <i className="pi pi-spin pi-spinner text-3xl mb-3" />
          <p>Cargando tus permisos…</p>
        </div>
      ) : error ? (
        <div className="p-8 text-center text-error">{error}</div>
      ) : datos === null ? null : (
        <>
          {sinJornada ? (
            <div className="mb-8 rounded-lg border border-warning bg-warning-soft p-4">
              <p className="font-semibold text-warning-soft-foreground">
                No tenés una jornada laboral asignada
              </p>
              <p className="mt-1 text-sm text-warning-soft-foreground">
                Por eso no tenés cupo de horas libres para permisos: cada permiso
                común se te cuenta entero como horas a recuperar. Los permisos
                oficiales no. Consultalo con Recursos Humanos.
              </p>
              {datos.deuda > 0 && (
                <p className="mt-2 text-sm text-warning-soft-foreground">
                  Este año acumulás <strong>{fmtHoras(datos.deuda)}</strong> a
                  recuperar por permisos.
                </p>
              )}
            </div>
          ) : (
            <div className="bg-card rounded-lg shadow-sm p-6 border border-border mb-8">
              <h2 className="font-heading text-lg text-foreground mb-4">
                Tu cupo de {datos.anio}
              </h2>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                <div>
                  <p className="text-sm text-muted-foreground mb-1">Cupo del año</p>
                  <p className="text-2xl font-heading text-foreground">
                    {fmtHoras(datos.cupoAnual)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground mb-1">Usado</p>
                  <p className="text-2xl font-heading text-foreground">
                    {fmtHoras(datos.consumido)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground mb-1">Te queda</p>
                  <p className="text-2xl font-heading text-success">
                    {fmtHoras(datos.restante)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground mb-1">A recuperar</p>
                  <p
                    className={`text-2xl font-heading ${
                      datos.deuda > 0 ? "text-error" : "text-muted-foreground"
                    }`}
                  >
                    {fmtHoras(datos.deuda)}
                  </p>
                </div>
              </div>
              <p className="text-sm text-muted-foreground mt-4">
                {datos.restante > 0
                  ? "Mientras te quede cupo, los permisos no te descuentan horas."
                  : "Se te agotó el cupo del año: los permisos comunes que pidas ahora se cuentan como horas a recuperar."}
              </p>
              {datos.deuda > 0 && (
                <p className="text-sm text-muted-foreground mt-2">
                  Las horas a recuperar ya están incluidas en el saldo acumulado
                  que ves en Asistencia: no son una deuda aparte.
                </p>
              )}
            </div>
          )}

          <div className="bg-card rounded-lg shadow-sm p-4 border border-border">
            <h2 className="font-heading text-lg text-foreground mb-4">
              Permisos de {datos.anio}
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground border-b border-border">
                    <th className="py-2 pr-4">Fecha</th>
                    <th className="py-2 pr-4">Salida</th>
                    <th className="py-2 pr-4">Retorno</th>
                    <th className="py-2 pr-4">Tipo</th>
                    <th className="py-2 text-right">Horas</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.permisos.map((p) => (
                    <tr key={p.id} className="border-b border-border last:border-0">
                      <td className="py-2 pr-4 text-foreground">{p.fecha}</td>
                      <td className="py-2 pr-4">{fmtHoraDelDia(p.exitTime)}</td>
                      <td className="py-2 pr-4">{fmtHoraDelDia(p.returnTime)}</td>
                      <td className="py-2 pr-4">
                        {p.oficial ? (
                          <span
                            className="rounded px-1.5 py-0.5 text-xs bg-info-soft text-info-soft-foreground"
                            title="No consume tu cupo ni genera horas a recuperar"
                          >
                            Oficial
                          </span>
                        ) : (
                          <span className="text-muted-foreground">Común</span>
                        )}
                      </td>
                      <td className="py-2 text-right text-foreground">
                        {fmtHoras(p.horas)}
                      </td>
                    </tr>
                  ))}
                  {datos.permisos.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-6 text-center text-muted-foreground">
                        No pediste permisos en {datos.anio}.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Confirmar los tokens de color**

La pantalla usa cuatro pares de tokens del proyecto, todos ya definidos en
`src/app/globals.css` para tema claro y oscuro: `bg-info-soft` /
`text-info-soft-foreground` (etiqueta "Oficial", líneas 82-83 y 232-233),
`bg-warning-soft` / `text-warning-soft-foreground` (el aviso de sin jornada,
que `MiAsistencia.tsx:142` ya usa), `text-success` y `text-error`.

No hace falta agregar ningún token. Confirmarlo de una pasada:

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && grep -cE "color-info-soft|color-warning-soft" src/app/globals.css
```

Esperado: un número mayor a 0 (hoy son 8 coincidencias). Si diera 0, **no
inventar tokens nuevos**: avisar y parar, porque significaría que el tema
cambió desde que se escribió este plan.

- [ ] **Step 4: Cablear la pantalla en el shell**

En `src/app/page.tsx`, agregar el import después del de `MiAsistencia` (línea 29):

```tsx
import MisPermisos from '@/app/screens/MisPermisos/Screen';
```

Y el `case` después del de `'mi-asistencia'` (líneas 166-167):

```tsx
      case 'mis-permisos':
        return <MisPermisos />;
```

- [ ] **Step 5: Agregar la entrada al menú del avatar**

En `src/app/Componentes/Shell/AppHeader.tsx`, sumar `CalendarClock` a la línea de imports de `lucide-react` (línea 5), y agregar el ítem después del bloque de Reubicación (que cierra en la línea 267), antes de `<InstalarAppItem`:

```tsx
            {/* Mis Permisos vive en el sidebar, que en celular no existe para
                quien tiene barra inferior: ahí se la agrega acá. */}
            {navegacionSimple && canAccess(permisos, "mis-permisos") && (
              <div className="md:hidden">
                <DropdownMenuItem onClick={() => setPage("mis-permisos")}>
                  <CalendarClock size={16} className="mr-2" /> Mis Permisos
                </DropdownMenuItem>
              </div>
            )}
```

- [ ] **Step 6: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "MisPermisos|AppHeader|rbac|page.tsx|Interfaces"
```

Esperado: sin salida.

- [ ] **Step 7: Verificar en el navegador**

Con el backend corriendo y `npm run dev`, entrando con un usuario con `asistencia.propia` y **sin** permisos de gestión:

1. En escritorio: "Mis Permisos" aparece en el sidebar, sección "Agente".
2. A 375 px: no está en la barra inferior (que sigue con sus 4), y sí aparece en el menú del avatar junto a Reubicación.
3. La pantalla abre en el año actual, con el cuadro de cupo y la tabla.
4. Cambiar el año en el selector recarga los datos de ese año.
5. Un año sin permisos muestra "No pediste permisos en AAAA" y el cupo completo.
6. Un permiso oficial se ve con la etiqueta "Oficial" y no afecta al cupo usado.
7. Las cuatro cifras cierran: usado + te queda = cupo del año (salvo que el cupo haya bajado después, caso en que "te queda" es 0).

Con un usuario de gestión (RRHH o ADMIN): "Mis Permisos" aparece en su sidebar y la pantalla funciona igual.

Con un empleado **sin jornada asignada**: en vez del cuadro de cupo aparece el aviso de que no tiene jornada, y la tabla de permisos se ve igual.

- [ ] **Step 8: Prueba de punta a punta del recálculo**

1. Entrar con RRHH y anotar el saldo acumulado de un agente que tenga permisos comunes en el año.
2. En Configuración → Régimen Horario, bajarle el cupo a la jornada de ese agente (por ejemplo de 12 a 2).
3. Esperar unos segundos (el recálculo va en segundo plano) y recargar.
4. Entrar con ese agente a "Mis permisos": el cupo nuevo se refleja, "a recuperar" subió, y el saldo acumulado de Asistencia bajó en consecuencia.
5. Volver a subir el cupo a 12 y confirmar que el saldo vuelve a su valor original.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Interfas/Interfaces.ts src/app/util/rbac.ts src/app/screens/MisPermisos/Screen.tsx src/app/page.tsx src/app/Componentes/Shell/AppHeader.tsx
git commit -m "$(cat <<'EOF'
feat(permisos): pantalla Mis Permisos con el cupo anual y el detalle por anio

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Autorrevisión del plan

**Cobertura del spec.** Cada requisito tiene tarea: columna `horasPermisoAnual DECIMAL(6,2) DEFAULT 12` con el patrón `IF COL_LENGTH` (T1); cupo como parámetro de `calcular_anio` y desaparición de `BANCO_PERMISO_ANUAL_HORAS` (T1); cupo 0 sin jornada (T1); `schedules.py` llamando a `ensure_tables` (T2); validación 0–2000 (T2); `recalcular_jornada` con auditoría en `RecalculoLog` y `origen="cupo_permiso"` (T2); recálculo en segundo plano, solo si el cupo cambió, solo el año en curso, y nada al crear una jornada (T2); `GET /asistencia/mis-permisos` resolviendo el empleado desde el token, con totales leídos de `JornadaDiaria` y 403 sin legajo (T3); año sin datos responde 200 con lista vacía (T3); tercer input en el modal de jornada y el cupo en la tarjeta (T4); el texto de los 12 h en `LicenseModal.tsx` (T4); pantalla con selector de año, totales, tabla, oficiales marcados y los dos estados vacíos redactados (T5); navegación con `asistencia.propia`, sin `ocultaSiTienePermiso`, y el ítem del menú del avatar en celular (T5).

**Una desviación del spec, deliberada.** El spec decía espejar `saldo_licencias.anios_de_vacaciones_con_datos` para armar la lista de años. Al escribir el plan se leyó esa función y **no es reusable**: está atada a la ventana de 3 años del ciclo de vacaciones y a las claves `(anio, categoria)`, nada de lo cual aplica acá. La T3 resuelve lo mismo con un `SELECT DISTINCT YEAR(date)` unido al año en curso, que es más directo y no arrastra el concepto de ciclo.

**Dos cosas que el spec no decía y el plan decide.** Primero, qué pasa si el cupo baja por debajo de lo ya consumido: `restante` se trunca en 0 en vez de ir a negativo, porque un negativo ahí se leería como una segunda deuda sumada a la que ya muestra `deuda`. Está testeado en T3. Segundo, el `_validar_cupo(None)` devuelve `0.0` en vez de 400, para que un cliente viejo que no manda el campo no rompa; el frontend siempre lo manda.

**Consistencia de nombres.** `horasPermisoAnual` es el nombre de la columna, de la clave que devuelve `_datos_empleado`, del campo de `GET /schedules/regimes` y `POST /schedules/jornadas`, y de la propiedad de la interfaz `JornadaLaboral` del frontend. `calcular_anio(dias, tolerancias, banco_anual)` se declara en T1 y se llama con ese tercer argumento en `recalcular_anio` (T1) y en los tests (T1). `recalcular_jornada(db, jornada_id, anio)` se declara en T2 y se consume en `save_jornada` (T2). La respuesta de `GET /asistencia/mis-permisos` se declara en el bloque Interfaces de T3 con las claves exactas (`cupoAnual`, `consumido`, `restante`, `deuda`, `permisos`, `aniosConDatos`) y la interfaz `MisPermisosResp` de T5 las repite una a una. El `Page` `"mis-permisos"` se declara en T5 y se usa con ese literal en `PAGE_CONFIG`, en el `case` de `page.tsx` y en el `setPage` de `AppHeader`.
