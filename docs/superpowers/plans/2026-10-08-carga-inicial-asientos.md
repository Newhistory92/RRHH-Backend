# Carga inicial de permisos por asientos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que cada carga manual de horas de permiso ya consumidas sea un asiento que se suma al total, con el historial a la vista y la posibilidad de borrar un asiento equivocado.

**Architecture:** La tabla `ConsumoInicialPermiso` pasa de una fila por empleado y año a varias: se le quita la clave única, el `MERGE` se reemplaza por un `INSERT` por asiento, y la lectura del total pasa a ser un `SUM`. Los endpoints `PUT` (reemplazar) se vuelven `POST` (agregar) y `DELETE` (borrar un asiento). El panel muestra la lista de asientos con el total acumulado.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15 (App Router), React, Tailwind con los tokens del proyecto.

## Contexto: esto corrige una feature ya implementada

La carga inicial ya existe y funciona, con una diferencia: **reemplaza en vez de sumar**. Cargar 5 y después 10 deja 10, no 15. El spec original lo eligió a propósito (*"corregir una carga equivocada es el caso normal"*), y el usuario, probándolo, pidió lo contrario.

El spec ya está actualizado con el diseño nuevo:
`docs/superpowers/specs/2026-10-08-carga-inicial-permisos-design.md` (ver el bloque **"Revisión 2026-10-08"** en la Unidad 1).

## Global Constraints

- **Dos repos.** Backend: `C:\Users\Emiliano\Documents\Backend_RRHH`. Frontend: `C:\Users\Emiliano\Documents\RRHH`. Cada tarea dice en cuál trabaja; los commits van en el repo que corresponde, nunca cruzados.
- **Cada carga es un asiento.** Varios asientos del mismo `(employeeId, anio)` es el caso normal: se le quita la clave única a la tabla.
- **El total es la suma de los asientos.** La lectura del total devuelve `float | None`, con `None` cuando **no hay ningún asiento** — y no coalesce a 0 adentro del módulo, porque el recálculo coalesce con `or 0.0` y el `GET` necesita conservar la distinción.
- **Un asiento equivocado se corrige borrándolo.** No se puede editar en el lugar.
- **El `DELETE` valida que el asiento pertenezca al empleado de la URL.** Sin ese chequeo, el `id` alcanzaría para borrarle un asiento a cualquier otra persona.
- Validación: `horasConsumidas` no negativo, tope de 2000, **por asiento** (no al total: un total alto puede ser la suma legítima de varias cargas).
- El año nunca viene del cliente: siempre `date.today().year`.
- Las tres rutas exigen `require_permission("asistencia.cargaInicialPermisos")` y recalculan sincrónico (un solo empleado).
- **`app/services/asistencia_calc.py` no se toca.** El motor no se entera de esta feature.
- La migración tiene que ser **idempotente** y correr contra una base que **ya tiene** la tabla con la clave única (el usuario estuvo probando): hay que soltar el constraint con el patrón `IF EXISTS(...)`, no asumir que no está.
- Backend: `python -m pytest` desde el repo, con el intérprete del venv: `"./venv/Scripts/python.exe" -m pytest`. Los 4 archivos `tests/test_chat_*.py` pueden fallar al importar por falta de `google-genai`: es preexistente y ajeno. Comentarios del código Python **sin tildes**.
- Frontend: **sin runner de tests.** Verificación `npx tsc --noEmit -p tsconfig.json`, criterio no agregar errores nuevos. El baseline es **27**; contalo con `grep -c "error TS"`, nunca por líneas de salida.
- Commits en español, estilo del repo, con línea en blanco y la línea `Co-Authored-By` que indique el entorno.
- Archivos con finales de línea LF y UTF-8.

---

## Estructura de archivos

### Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/database/consumo_inicial_permisos.py` | **Modificar.** Suelta la clave única, `INSERT` por asiento, `DELETE` por asiento, total por `SUM`, listado de asientos. |
| `app/database/asistencia.py` | **Modificar.** `excedente_carga_inicial` pasa a comparar el **total** contra el cupo, no cada fila. |
| `app/routes/carga_inicial_permisos.py` | **Modificar.** `PUT` → `POST`; suma `DELETE`; el `GET` devuelve los asientos. |
| `tests/test_consumo_inicial_permisos.py` | **Modificar.** Los tests del upsert pasan a ser de asientos. |
| `tests/test_carga_inicial_permisos_endpoints.py` | **Modificar.** `PUT` → `POST`, y suma los del `DELETE`. |
| `tests/test_saldo_con_carga_inicial.py` | **Modificar.** El excedente se mide sobre el total. |

### Frontend (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx` | **Modificar.** Lista de asientos con total, agregar y borrar. |

**Orden:** el backend completo primero (1 y 2), porque el panel consume sus endpoints. Después el frontend (3).

---

## Task 1: La tabla pasa a guardar asientos

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/consumo_inicial_permisos.py` (el DDL, y reemplazar `carga_de_empleado`/`consumo_de_empleado`/`upsert_consumo`)
- Modify: `app/database/asistencia.py` (la función `excedente_carga_inicial`)
- Test: `tests/test_consumo_inicial_permisos.py` (modificar), `tests/test_saldo_con_carga_inicial.py` (modificar)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `ensure_table(db: Session) -> None` — crea la tabla y **suelta** la clave única si está
  - `total_de_empleado(db: Session, employee_id: int, anio: int) -> float | None` — suma de los asientos, `None` si no hay ninguno (reemplaza a `consumo_de_empleado`)
  - `asientos_de_empleado(db: Session, employee_id: int, anio: int) -> list[dict]` — cada asiento con `id`, `horasConsumidas`, `cargadoPor`, `cargadoEn` (reemplaza a `carga_de_empleado`)
  - `agregar_asiento(db: Session, employee_id: int, anio: int, horas: float, cargado_por: int | None) -> None` (reemplaza a `upsert_consumo`)
  - `borrar_asiento(db: Session, employee_id: int, asiento_id: int) -> bool` — `False` si el asiento no existe o no es de ese empleado

**El bug que esta tarea también corrige:** `excedente_carga_inicial` en `asistencia.py` compara **cada fila** contra el cupo (`CASE WHEN ci.horasConsumidas > cupo ...`). Con una sola fila daba bien, pero con asientos es incorrecto: dos asientos de 10 contra un cupo de 12 dan un total de 20 y un excedente real de 8, mientras que la comparación por fila da 0 (ninguna fila sola supera 12). Hay que sumar primero y comparar después.

- [ ] **Step 1: Escribir los tests que fallan, de la persistencia**

Reemplazar en `tests/test_consumo_inicial_permisos.py` el bloque de tests de lectura y upsert (desde `def _db(filas):` hasta el final del test `test_el_upsert_corrige_en_vez_de_duplicar`) por:

```python
def _db(filas):
    return FakeSession({"FROM ConsumoInicialPermiso": filas})


def test_sin_asientos_el_total_es_none_y_no_cero():
    """None deja que rija el cupo completo; 0 afirma que no uso ninguna."""
    assert total_de_empleado(_db([{"total": None}]), 8, 2026) is None


def test_asientos_que_suman_cero_devuelven_cero_y_no_none():
    assert total_de_empleado(_db([{"total": 0}]), 8, 2026) == 0.0


def test_el_total_es_la_suma_de_los_asientos():
    """Es el cambio que motiva esta tarea: 5 y despues 10 dan 15, no 10."""
    assert total_de_empleado(_db([{"total": 15.0}]), 8, 2026) == 15.0


def test_el_total_suma_en_sql_y_no_en_python():
    """
    Si sumara en Python, traeria todas las filas para descartarlas: el SUM
    tiene que estar en la consulta.
    """
    db = _db([{"total": 15.0}])
    total_de_empleado(db, 8, 2026)
    sql = db.sql_ejecutado()
    assert "SUM(horasConsumidas)" in sql
    assert "employeeId = :empId" in sql
    assert "anio = :anio" in sql


def test_los_asientos_se_listan_con_su_id_y_trazabilidad():
    """El id es lo que el panel necesita para poder borrar uno puntual."""
    filas = [
        {"id": 2, "horasConsumidas": 10.0, "cargadoPor": 3, "cargadoEn": None},
        {"id": 1, "horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None},
    ]
    asientos = asientos_de_empleado(_db(filas), 8, 2026)
    assert [a["id"] for a in asientos] == [2, 1]
    assert asientos[0]["horasConsumidas"] == 10.0
    assert asientos[0]["cargadoPor"] == 3


def test_agregar_un_asiento_inserta_y_no_pisa():
    """
    INSERT y no MERGE: la segunda carga del mismo (empleado, anio) es un
    asiento mas, legitimo, no una correccion de la primera.
    """
    db = FakeSession({})
    agregar_asiento(db, 8, 2026, 5.0, cargado_por=3)
    sql = db.sql_ejecutado()
    assert "INSERT INTO ConsumoInicialPermiso" in sql
    assert "MERGE" not in sql
    assert db.commits >= 1


def test_borrar_un_asiento_exige_que_sea_del_empleado():
    """
    Sin el filtro por employeeId, el id de la URL alcanzaria para borrarle
    un asiento a cualquier otra persona.
    """
    db = FakeSession({"DELETE FROM ConsumoInicialPermiso": [{"id": 1}]})
    assert borrar_asiento(db, 8, 1) is True
    sql, params = db.ejecutadas[0]
    assert "employeeId = :empId" in sql
    assert params == {"empId": 8, "asientoId": 1}


def test_borrar_un_asiento_que_no_es_del_empleado_devuelve_false():
    """rowcount 0: el DELETE no encontro nada que borrar."""
    db = FakeSession({"DELETE FROM ConsumoInicialPermiso": []})
    assert borrar_asiento(db, 8, 1) is False
```

Y actualizar el import del encabezado de ese archivo:

```python
from app.database.consumo_inicial_permisos import (
    agregar_asiento, asientos_de_empleado, borrar_asiento, total_de_empleado,
)
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_consumo_inicial_permisos.py -v
```

Esperado: FALLA en el import con `ImportError: cannot import name 'total_de_empleado'`.

- [ ] **Step 3: Reescribir el módulo de persistencia**

Reemplazar el contenido de `app/database/consumo_inicial_permisos.py` por:

```python
"""
Horas de permiso ya consumidas antes de que el sistema las registrara.

El cupo anual sale de la jornada laboral y se consume cronologicamente. Un
empleado recien dado de alta -o al que recien se le asigna una jornada- no
tiene ninguna fila de Permission del anio, asi que arranca con el cupo entero
aunque en la realidad ya se haya tomado horas que se llevaban en papel.

Cada carga de RRHH es un ASIENTO: varias del mismo empleado y anio se suman.
Cargar 5 y despues 10 da 15, no 10 -son dos cargas reales, no una correccion
de la otra. Un asiento equivocado se corrige borrandolo, que es la
contrapartida necesaria: sumando, un 50 mal tipeado quedaria para siempre.

Se guarda lo CONSUMIDO y no lo que le queda, al reves que SaldoInicialLicencia.
Es deliberado: el cupo de permisos no se deriva de nada, sale de
JornadaLaboral.horasPermisoAnual, que RRHH edita a mano. Guardando "le quedan
7", subir el cupo de 12 a 20 dejaria esas 7 clavadas cuando la persona uso 5 y
deberia tener 15. Lo consumido no se mueve; el cupo si.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('ConsumoInicialPermiso', 'U') IS NULL
CREATE TABLE ConsumoInicialPermiso (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    employeeId      INT          NOT NULL,
    anio            INT          NOT NULL,
    horasConsumidas DECIMAL(6,2) NOT NULL,
    cargadoPor      INT          NULL,
    cargadoEn       DATETIME2    NOT NULL
);
"""

# La primera version de la tabla tenia UNIQUE (employeeId, anio), porque cada
# carga reemplazaba a la anterior. Ahora cada carga es un asiento y varios del
# mismo par son el caso normal, asi que el constraint tiene que irse. Las bases
# que ya lo tienen lo sueltan aca; las nuevas no lo crean nunca.
DROP_UQ_SQL = """
IF EXISTS (SELECT 1 FROM sys.objects
           WHERE name = 'UQ_ConsumoInicialPermiso_emp_anio'
             AND parent_object_id = OBJECT_ID('ConsumoInicialPermiso'))
ALTER TABLE ConsumoInicialPermiso
    DROP CONSTRAINT UQ_ConsumoInicialPermiso_emp_anio;
"""


def ensure_table(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch con su commit."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()
    db.execute(text(DROP_UQ_SQL))
    db.commit()


def total_de_empleado(db: Session, employee_id: int,
                      anio: int) -> float | None:
    """
    La suma de los asientos de ese empleado y anio, o None si no hay ninguno.

    NO coalesce a 0 a proposito: sus dos consumidores necesitan cosas
    distintas. El recalculo hace la aritmetica y coalesce con `or 0.0`, porque
    sin carga el banco es el cupo completo. El endpoint conserva la
    distincion, porque el panel de RRHH muestra el estado real: no haber
    mirado a un empleado y haber determinado que no uso ninguna hora son cosas
    distintas. Si coalesciera aca, esa distincion se perderia en la capa de
    datos y no habria forma de recuperarla.

    El SUM va en la consulta y no en Python: traer todas las filas para
    sumarlas aca seria leer de mas para tirar.
    """
    fila = db.execute(
        text("""
            SELECT SUM(horasConsumidas) AS total
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().first()
    if fila is None or fila["total"] is None:
        return None
    return float(fila["total"])


def asientos_de_empleado(db: Session, employee_id: int,
                         anio: int) -> list[dict]:
    """
    Los asientos de ese empleado y anio, el mas nuevo primero.

    Incluye el id porque es lo que el panel necesita para poder borrar uno
    puntual, que es la unica forma de corregir una carga equivocada.
    """
    filas = db.execute(
        text("""
            SELECT id, horasConsumidas, cargadoPor, cargadoEn
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
            ORDER BY cargadoEn DESC, id DESC
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().all()
    return [dict(f) for f in filas]


def agregar_asiento(db: Session, employee_id: int, anio: int,
                    horas: float, cargado_por: int | None) -> None:
    """
    Agrega un asiento. Es INSERT y no MERGE: la segunda carga del mismo
    (empleado, anio) es un asiento mas, no una correccion de la primera.
    """
    db.execute(
        text("""
            INSERT INTO ConsumoInicialPermiso
                (employeeId, anio, horasConsumidas, cargadoPor, cargadoEn)
            VALUES (:empId, :anio, :horas, :cargadoPor, GETDATE())
        """),
        {"empId": employee_id, "anio": anio, "horas": horas,
         "cargadoPor": cargado_por},
    )
    db.commit()


def borrar_asiento(db: Session, employee_id: int, asiento_id: int) -> bool:
    """
    Borra un asiento. Devuelve False si no existe o no es de ese empleado.

    El filtro por employeeId no es redundante con el id: sin el, el id que
    viene en la URL alcanzaria para borrarle un asiento a cualquier otra
    persona.
    """
    resultado = db.execute(
        text("""
            DELETE FROM ConsumoInicialPermiso
            WHERE id = :asientoId AND employeeId = :empId
        """),
        {"empId": employee_id, "asientoId": asiento_id},
    )
    db.commit()
    return resultado.rowcount > 0
```

- [ ] **Step 4: Correr los tests de persistencia**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_consumo_inicial_permisos.py -v
```

Esperado: PASS los de asientos. El test `test_asistencia_ensure_tables_crea_tambien_consumo_inicial_permiso` que ya está en el archivo tiene que seguir pasando sin cambios.

- [ ] **Step 5: Escribir el test que falla, del excedente sobre el total**

En `tests/test_saldo_con_carga_inicial.py`, reemplazar el helper `_db` y agregar el caso de varios asientos. El helper pasa a:

```python
def _db(saldo_dias=0.0, excedente=0.0):
    return FakeSession({
        "SUM(saldoDia)": [{"s": saldo_dias}],
        "AS excedente": [{"excedente": excedente}],
    })
```

Y agregar al final del archivo:

```python
def test_el_excedente_se_mide_sobre_el_total_y_no_por_asiento():
    """
    Con asientos, comparar cada fila contra el cupo da mal: dos asientos de
    10 contra un cupo de 12 son 20 en total y 8 de excedente, pero ninguna
    fila sola supera 12. El SUM tiene que estar adentro de la resta.
    """
    db = _db(excedente=0.0)
    excedente_carga_inicial(db, 8)
    sql = db.sql_ejecutado()
    # La resta opera sobre la suma de los asientos, no sobre cada fila.
    assert "SUM(ci.horasConsumidas)" in sql
    # Y ya no hay un CASE por fila comparando cada asiento contra el cupo.
    assert "CASE WHEN ci.horasConsumidas >" not in sql
```

Los tests `test_el_excedente_se_mide_contra_el_cupo_de_la_jornada` y `test_un_empleado_sin_jornada_cuenta_todo_como_excedente` siguen en el archivo; el segundo afirma `"COALESCE(j.horasPermisoAnual, 0)" in db.sql_ejecutado()`, que la consulta nueva conserva.

- [ ] **Step 6: Correr para verificar que falla**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_saldo_con_carga_inicial.py -v -k excedente_se_mide_sobre_el_total
```

Esperado: FALLA en `assert "SUM(ci.horasConsumidas)" in sql`.

- [ ] **Step 7: Corregir el excedente para que opere sobre el total**

En `app/database/asistencia.py`, reemplazar el cuerpo de la consulta de `excedente_carga_inicial` (hoy con un `CASE` por fila) por:

```python
    fila = db.execute(text("""
        SELECT COALESCE(
                   CASE WHEN SUM(ci.horasConsumidas) > COALESCE(j.horasPermisoAnual, 0)
                        THEN SUM(ci.horasConsumidas) - COALESCE(j.horasPermisoAnual, 0)
                        ELSE 0 END, 0) AS excedente
        FROM ConsumoInicialPermiso ci
        JOIN Employee e ON e.id = ci.employeeId
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        WHERE ci.employeeId = :emp
        GROUP BY ci.anio, j.horasPermisoAnual
    """), {"emp": employee_id}).mappings().all()
    return float(sum(f["excedente"] or 0 for f in fila))
```

Y actualizar su docstring, agregando al final:

```
    El excedente se mide sobre el TOTAL de los asientos de cada anio, no
    asiento por asiento: dos cargas de 10 contra un cupo de 12 son 20 en
    total y 8 de excedente, aunque ninguna de las dos sola lo supere. Por eso
    el GROUP BY por anio y la suma de los excedentes de cada anio en Python:
    cada anio tiene su propio cupo que agotar.
```

- [ ] **Step 8: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde. Si algún test de asistencia o del banco falla con `KeyError`, es un fixture de `FakeSession` cuyo fragmento ya no coincide con el SQL nuevo: ajustarlo al fragmento real. Los fixtures que mapeaban `"SELECT horasConsumidas"` ahora tienen que mapear `"SUM(horasConsumidas)"` para el total, y `"AS excedente"` sigue sirviendo para el excedente.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/consumo_inicial_permisos.py app/database/asistencia.py tests/test_consumo_inicial_permisos.py tests/test_saldo_con_carga_inicial.py
git commit -m "$(cat <<'EOF'
feat(permisos): la carga inicial pasa a guardar asientos que se suman

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Los endpoints de asientos

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/routes/carga_inicial_permisos.py` (el `GET`, y el `PUT` que pasa a `POST`; suma el `DELETE`)
- Test: `tests/test_carga_inicial_permisos_endpoints.py` (modificar)

**Interfaces:**
- Consumes: `asientos_de_empleado`, `total_de_empleado`, `agregar_asiento`, `borrar_asiento`, `ensure_table` de la Task 1; `recalcular_anio(db, employee_id, anio)` que ya existe.
- Produces, y lo consume la Task 3:
  - `GET /asistencia/carga-inicial-permisos/{employee_id}` → `{ anio: int, cupoAnual: float, total: float | null, asientos: [{ id: int, horasConsumidas: float, cargadoPor: int | null, cargadoEn: str | null }] }`
  - `POST /asistencia/carga-inicial-permisos/{employee_id}` → body `{ horasConsumidas: number }`, responde `{ ok: true, anio, horasConsumidas }`
  - `DELETE /asistencia/carga-inicial-permisos/{employee_id}/{asiento_id}` → `{ ok: true, anio }`, o 404 si el asiento no existe o no es de ese empleado

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_carga_inicial_permisos_endpoints.py`, reemplazar el helper `_db` y todos los tests de `GET` y `PUT` (desde `def _db(` hasta el final del archivo) por:

```python
def _db(asientos=None, total=None, cupo=12.0, borrado=True):
    return FakeSession({
        "SUM(horasConsumidas)": [{"total": total}],
        "ORDER BY cargadoEn DESC": asientos if asientos is not None else [],
        "DELETE FROM ConsumoInicialPermiso": [{"id": 1}] if borrado else [],
        "FROM Employee e": [{"cupo": cupo}],
    })


# -- Validacion ----------------------------------------------------------------

@pytest.mark.parametrize("valor", [0, 5, 12.5, 2000])
def test_las_horas_razonables_pasan(valor):
    assert m._validar_horas(valor) == float(valor)


def test_rechaza_horas_negativas():
    with pytest.raises(HTTPException) as e:
        m._validar_horas(-1)
    assert e.value.status_code == 400


def test_el_tope_es_por_asiento_y_no_del_total():
    """
    Un total alto puede ser la suma legitima de varias cargas reales; un solo
    asiento de mas de 2000 horas solo puede ser un error de tipeo.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_horas(2001)
    assert e.value.status_code == 400


def test_rechaza_lo_que_no_es_numero():
    with pytest.raises(HTTPException) as e:
        m._validar_horas("mucho")
    assert e.value.status_code == 400


# -- GET -----------------------------------------------------------------------

def test_el_get_devuelve_null_cuando_no_hay_asientos():
    """null y 0 son estados distintos y el panel los muestra distinto."""
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(total=None))
    assert r["total"] is None
    assert r["asientos"] == []
    assert r["cupoAnual"] == 12.0


def test_el_get_devuelve_cero_cuando_los_asientos_suman_cero():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(total=0))
    assert r["total"] == 0.0


def test_el_get_lista_los_asientos_con_su_id():
    asientos = [
        {"id": 2, "horasConsumidas": 10.0, "cargadoPor": 3, "cargadoEn": None},
        {"id": 1, "horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None},
    ]
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(asientos=asientos, total=15.0))
    assert r["total"] == 15.0
    assert [a["id"] for a in r["asientos"]] == [2, 1]
    assert r["asientos"][0]["horasConsumidas"] == 10.0


# -- POST ----------------------------------------------------------------------

def test_el_post_agrega_un_asiento_y_recalcula(monkeypatch):
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db()
    r = m.post_carga_inicial_permisos(
        8, {"horasConsumidas": 5}, user={"employeeId": 3}, db=db,
    )

    assert r["ok"] is True
    assert r["horasConsumidas"] == 5.0
    assert recalculos == [(8, r["anio"])]
    assert "INSERT INTO ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_post_rechaza_un_valor_invalido_antes_de_escribir(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db()
    with pytest.raises(HTTPException):
        m.post_carga_inicial_permisos(
            8, {"horasConsumidas": -1}, user={"employeeId": 3}, db=db,
        )
    assert "INSERT" not in db.sql_ejecutado()


# -- DELETE --------------------------------------------------------------------

def test_el_delete_borra_el_asiento_y_recalcula(monkeypatch):
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db(borrado=True)
    r = m.delete_carga_inicial_permisos(8, 1, _user={}, db=db)

    assert r["ok"] is True
    assert recalculos == [(8, r["anio"])]
    assert "DELETE FROM ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_delete_de_un_asiento_ajeno_responde_404(monkeypatch):
    """
    borrar_asiento devuelve False cuando el filtro por employeeId no
    encontro nada: el id de la URL no alcanza para borrar el de otro.
    """
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db(borrado=False)
    with pytest.raises(HTTPException) as e:
        m.delete_carga_inicial_permisos(8, 999, _user={}, db=db)
    assert e.value.status_code == 404


def test_el_delete_que_no_borro_nada_no_recalcula(monkeypatch):
    """Sin cambio no hay nada que recalcular."""
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    with pytest.raises(HTTPException):
        m.delete_carga_inicial_permisos(8, 999, _user={}, db=_db(borrado=False))
    assert recalculos == []
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_carga_inicial_permisos_endpoints.py -v
```

Esperado: FALLAN los de `GET`/`POST`/`DELETE` con `AttributeError: module 'app.routes.carga_inicial_permisos' has no attribute 'post_carga_inicial_permisos'` (y el `GET` por `KeyError: 'total'`).

- [ ] **Step 3: Reescribir los endpoints**

En `app/routes/carga_inicial_permisos.py`, actualizar el import del módulo de persistencia:

```python
from app.database.consumo_inicial_permisos import (
    agregar_asiento, asientos_de_empleado, borrar_asiento, ensure_table,
    total_de_empleado,
)
```

Reemplazar el handler del `GET` entero por:

```python
@router.get("/{employee_id}")
def get_carga_inicial_permisos(employee_id: int, _user: dict = PERMISO,
                               db: Session = Depends(get_db)):
    """
    Los asientos del anio en curso y su total, con el cupo como contexto.

    total null significa "no hay ningun asiento" y 0 significa "los asientos
    suman cero". Son estados distintos y el panel los muestra distinto.
    """
    ensure_table(db)
    anio = date.today().year
    asientos = asientos_de_empleado(db, employee_id, anio)
    return {
        "anio": anio,
        "cupoAnual": _cupo_de_empleado(db, employee_id),
        "total": total_de_empleado(db, employee_id, anio),
        "asientos": [{
            "id": int(a["id"]),
            "horasConsumidas": float(a["horasConsumidas"]),
            "cargadoPor": a["cargadoPor"],
            "cargadoEn": a["cargadoEn"].isoformat() if a["cargadoEn"] else None,
        } for a in asientos],
    }
```

Reemplazar el handler del `PUT` entero por estos dos:

```python
@router.post("/{employee_id}")
def post_carga_inicial_permisos(employee_id: int, data: dict = Body(...),
                                user: dict = PERMISO,
                                db: Session = Depends(get_db)):
    """
    Agrega un asiento al anio en curso y recalcula ese anio del empleado.

    Es POST y no PUT porque no se guarda "el valor": se agrega una carga. Dos
    cargas del mismo anio se suman, que es el comportamiento buscado.

    El anio no se recibe por parametro: siempre es el calendario en curso, que
    es el unico cargable. Aceptarlo del cliente abriria la puerta a escribir
    anios que despues nadie recalcula.

    El recalculo va sincrono porque es un solo empleado, a diferencia del
    cambio de cupo de una jornada, que toca a toda su nomina y va en segundo
    plano.
    """
    ensure_table(db)
    horas = _validar_horas(data.get("horasConsumidas"))
    anio = date.today().year
    agregar_asiento(db, employee_id, anio, horas, user.get("employeeId"))
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio, "horasConsumidas": horas}


@router.delete("/{employee_id}/{asiento_id}")
def delete_carga_inicial_permisos(employee_id: int, asiento_id: int,
                                  _user: dict = PERMISO,
                                  db: Session = Depends(get_db)):
    """
    Borra un asiento y recalcula. Es la unica forma de corregir una carga
    equivocada: los asientos no se editan en el lugar.

    404 cuando el asiento no existe o no es de ese empleado -borrar_asiento
    filtra por employeeId, asi que el id de la URL no alcanza para borrarle
    uno a otra persona. Sin cambio no se recalcula nada.
    """
    ensure_table(db)
    if not borrar_asiento(db, employee_id, asiento_id):
        raise HTTPException(status_code=404,
                            detail="El asiento no existe o no es de este agente")
    anio = date.today().year
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio}
```

- [ ] **Step 4: Correr los tests de los endpoints**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_carga_inicial_permisos_endpoints.py -v
```

Esperado: PASS todos.

- [ ] **Step 5: Verificar que la app levanta con las tres rutas**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -c "from app.main import app; print(sorted({(r.path, tuple(sorted(r.methods))) for r in app.routes if 'carga-inicial-permisos' in r.path}))"
```

Esperado: imprime la ruta `/asistencia/carga-inicial-permisos/{employee_id}` con `GET` y con `POST`, y `/asistencia/carga-inicial-permisos/{employee_id}/{asiento_id}` con `DELETE`. **No** tiene que aparecer `PUT`.

- [ ] **Step 6: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/routes/carga_inicial_permisos.py tests/test_carga_inicial_permisos_endpoints.py
git commit -m "$(cat <<'EOF'
feat(permisos): endpoints de asientos -agregar, listar y borrar

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: El panel con el historial de asientos

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx`

**Interfaces:**
- Consumes: los tres endpoints de la Task 2, con las formas exactas declaradas ahí.
- Produces: nada.

**Qué cambia respecto del panel actual:** hoy tiene un campo con el valor guardado y un botón "Guardar" que lo reemplaza, más una línea "Última carga". Pasa a tener el total acumulado, la lista de asientos con un botón de borrar en cada uno, y un campo para agregar uno nuevo que no cierra el panel al guardar. La prop `employeeId` y el gating por permiso del botón que lo abre **no cambian**: siguen igual en `DetailTables.tsx`, que esta tarea no toca.

- [ ] **Step 1: Reescribir el panel**

Reemplazar el contenido de `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx` por:

```tsx
"use client";

// Carga de las horas de permiso que el agente ya usó antes de que el sistema
// las registrara. Cada carga es un asiento y el total es la suma: cargar 5 y
// después 10 da 15. Un asiento equivocado se corrige borrándolo, que es la
// única forma -no se editan en el lugar.
//
// Transitorio: existe para la migración, y se apaga quitándole el permiso al
// rol, sin tocar código.

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";

interface Asiento {
  id: number;
  horasConsumidas: number;
  cargadoPor: number | null;
  cargadoEn: string | null;
}

interface CargaInicialPermisos {
  anio: number;
  cupoAnual: number;
  total: number | null;
  asientos: Asiento[];
}

interface Props {
  employeeId: number;
  onCerrar: () => void;
}

const fmtHoras = (h: number) => `${h} h`;

export function CargaInicialPermisosPanel({ employeeId, onCerrar }: Props) {
  const [datos, setDatos] = useState<CargaInicialPermisos | null>(null);
  // Texto y no número: el campo tiene que distinguir vacío ("no se cargó
  // nada") de "0" ("se determinó que no usó ninguna"), y un input numérico
  // colapsa los dos casos.
  const [valor, setValor] = useState("");
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recargar = useCallback(async () => {
    const r = await apiClient.get<CargaInicialPermisos>(
      `/asistencia/carga-inicial-permisos/${employeeId}`
    );
    setDatos(r);
  }, [employeeId]);

  useEffect(() => {
    recargar()
      .catch((e) =>
        setError(e instanceof Error ? e.message : "No se pudo cargar el dato")
      )
      .finally(() => setCargando(false));
  }, [recargar]);

  // El input type="number" normalmente bloquea texto no numérico, pero un
  // valor pegado o un estado transitorio ("-", "e") puede colar un NaN.
  // Number(NaN) serializa a null en el body, lo que mandaría
  // horasConsumidas: null al backend.
  const valorInvalido = valor !== "" && Number.isNaN(Number(valor));

  const agregar = async () => {
    setGuardando(true);
    setError(null);
    try {
      await apiClient.post(`/asistencia/carga-inicial-permisos/${employeeId}`, {
        horasConsumidas: Number(valor),
      });
      // No se cierra el panel: RRHH suele cargar varios asientos de una
      // pasada y necesita ver el total actualizándose.
      setValor("");
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo agregar la carga");
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (asientoId: number) => {
    setGuardando(true);
    setError(null);
    try {
      await apiClient.delete(
        `/asistencia/carga-inicial-permisos/${employeeId}/${asientoId}`
      );
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar la carga");
    } finally {
      setGuardando(false);
    }
  };

  const sinJornada = datos !== null && datos.cupoAnual === 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4"
      onClick={onCerrar}
      role="dialog"
      aria-modal="true"
      aria-labelledby="carga-inicial-permisos-titulo"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="carga-inicial-permisos-titulo"
          className="font-heading text-lg font-bold text-foreground mb-1"
        >
          Horas de permiso ya consumidas
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          Horas que el agente ya usó este año antes de que el sistema las
          registrara. Cada carga se suma al total, y el total se descuenta de su
          cupo anual.
        </p>

        {cargando ? (
          <p className="text-sm text-muted-foreground py-4">Cargando…</p>
        ) : datos === null ? (
          <p className="text-sm text-error py-4">{error}</p>
        ) : (
          <>
            <div className="mb-4 rounded-lg bg-muted p-3 text-sm">
              <p className="text-muted-foreground">
                Año <span className="text-foreground font-medium">{datos.anio}</span>
                {" · "}
                Cupo de su jornada{" "}
                <span className="text-foreground font-medium">
                  {fmtHoras(datos.cupoAnual)}
                </span>
                {" · "}
                Total cargado{" "}
                <span className="text-foreground font-medium">
                  {datos.total === null ? "sin cargar" : fmtHoras(datos.total)}
                </span>
              </p>
              {sinJornada && (
                <p className="text-warning-soft-foreground mt-1">
                  Este agente no tiene jornada laboral asignada, así que su cupo
                  es 0: todo permiso común ya le genera horas a recuperar.
                </p>
              )}
            </div>

            <h3 className="text-sm font-bold text-foreground mb-2">Cargas</h3>
            {datos.asientos.length === 0 ? (
              <p className="text-sm text-muted-foreground mb-4">
                Todavía no se cargó ninguna.
              </p>
            ) : (
              <ul className="mb-4 divide-y divide-border border-y border-border">
                {datos.asientos.map((a) => (
                  <li
                    key={a.id}
                    className="flex items-center justify-between gap-3 py-2 text-sm"
                  >
                    <span className="text-foreground font-medium">
                      {fmtHoras(a.horasConsumidas)}
                    </span>
                    <span className="text-xs text-muted-foreground flex-1">
                      {a.cargadoEn ? a.cargadoEn.slice(0, 10) : "—"}
                      {a.cargadoPor !== null && ` · legajo ${a.cargadoPor}`}
                    </span>
                    <button
                      type="button"
                      onClick={() => borrar(a.id)}
                      disabled={guardando}
                      aria-label={`Borrar la carga de ${fmtHoras(a.horasConsumidas)}`}
                      className="text-error hover:opacity-80 text-xs font-bold disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Borrar
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <label
              htmlFor="horas-consumidas"
              className="block text-sm font-medium text-foreground mb-1"
            >
              Agregar una carga
            </label>
            <div className="flex gap-2">
              <input
                id="horas-consumidas"
                type="number"
                min="0"
                max="2000"
                step="0.5"
                value={valor}
                onChange={(e) => setValor(e.target.value)}
                placeholder="Horas"
                className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground"
              />
              <button
                type="button"
                onClick={agregar}
                disabled={guardando || valor === "" || valorInvalido}
                className="px-4 py-2 bg-primary hover:opacity-90 text-primary-foreground rounded-md text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {guardando ? "Guardando…" : "Agregar"}
              </button>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Cada carga se suma. Para corregir una equivocada, borrala de la
              lista y cargá la correcta.
            </p>

            {error && <p className="text-sm text-error mt-3">{error}</p>}

            <div className="flex pt-5">
              <button
                type="button"
                onClick={onCerrar}
                className="flex-1 py-2 bg-muted hover:bg-border rounded-xl text-sm font-bold"
              >
                Cerrar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -i "CargaInicialPermisos"
```

Esperado: sin salida.

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`. **Contar así y no por líneas de salida**: tsc imprime contexto multilínea por error.

- [ ] **Step 3: Verificar en el navegador**

Con el backend corriendo y `npm run dev`, con un usuario que tenga `rrhh.gestionar` y `asistencia.cargaInicialPermisos`:

1. Abrir el legajo de un agente → pestaña "Historial de Permisos" → "Cargar horas ya consumidas". El panel abre y dice "Total cargado: sin cargar" y "Todavía no se cargó ninguna".
2. Cargar 5 y agregar: aparece una línea de 5 h con la fecha de hoy, y el total pasa a 5 h. **El panel no se cierra.**
3. Cargar 10 y agregar: aparecen dos líneas (10 h y 5 h), y el total pasa a **15 h** — es el comportamiento que motiva todo este trabajo.
4. Borrar la línea de 10: queda una línea de 5 h y el total vuelve a 5 h.
5. Cerrar y reabrir el panel: el total y la lista persisten.
6. Ir a "Mis permisos" con ese agente: "Ya usadas antes del registro" muestra el total acumulado, y "Te queda" lo descuenta.
7. Con un cupo de 12 y cargas que sumen 25: "Mis permisos" muestra "A recuperar 13 h", y el saldo de "Mi asistencia" baja esas 13 h.

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx
git commit -m "$(cat <<'EOF'
feat(permisos): el panel de carga inicial muestra los asientos y su total

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Autorevisión del plan

**Cobertura del spec revisado.** Cada punto de la revisión tiene tarea: la tabla sin clave única y el `DROP CONSTRAINT` idempotente contra una base que ya la tiene (T1); `INSERT` por asiento en lugar del `MERGE`, con la justificación de por qué el `HOLDLOCK` ya no hace falta (T1); el total por `SUM` devolviendo `float | None` sin coalescer (T1); el listado con `id` para poder borrar (T1); el borrado con chequeo de pertenencia (T1, y su 404 en T2); los tres endpoints con el año server-side y el recálculo sincrónico (T2); el tope por asiento y no del total (T2); el panel con total, lista, agregar y borrar sin cerrarse (T3).

**Un bug propio que este plan corrige.** `excedente_carga_inicial` (agregada ayer, cuando había una sola fila por empleado y año) compara **cada fila** contra el cupo. Con asientos eso da mal: dos cargas de 10 contra un cupo de 12 son 20 en total y 8 de excedente, pero ninguna fila sola supera 12, así que daría 0. La T1 lo cambia a sumar primero y comparar después, con `GROUP BY` por año porque cada año tiene su propio cupo que agotar. Está cubierto por un test que afirma sobre el SQL real.

**Dos cosas que el spec no decía y el plan decide.** Primero, el `DELETE` que no borró nada **no recalcula**: sin cambio no hay nada que recalcular, y hay un test que lo fija. Segundo, el panel **no se cierra** al agregar un asiento, porque el flujo real es cargar varios de una pasada y ver el total moverse; cerrarlo obligaría a reabrirlo para cada carga.

**Un riesgo de fixtures que el plan anticipa.** `ConsumoInicialPermiso` ahora la leen tres consultas distintas (el total, el listado, y la del excedente en `asistencia.py`), y `FakeSession` matchea por el primer fragmento que encuentra. Los fixtures que hoy mapean `"SELECT horasConsumidas"` o `"FROM ConsumoInicialPermiso"` a secas van a entregarle la fila equivocada a alguna de las tres. El Step 8 de la T1 lo dice explícitamente y nombra los fragmentos inequívocos a usar: `"SUM(horasConsumidas)"`, `"ORDER BY cargadoEn DESC"` y `"AS excedente"`.

**Consistencia de nombres.** `total_de_empleado`, `asientos_de_empleado`, `agregar_asiento` y `borrar_asiento` se declaran en T1 y se consumen con esos nombres exactos en T2. Las claves de la respuesta del `GET` (`anio`, `cupoAnual`, `total`, `asientos[]` con `id`/`horasConsumidas`/`cargadoPor`/`cargadoEn`) se declaran en el bloque Interfaces de T2 y la interfaz `CargaInicialPermisos` de T3 las repite una a una. `horasConsumidas` es el mismo nombre en la columna, en el body del `POST` y en cada asiento del `GET`. La ruta del `DELETE` lleva `{employee_id}/{asiento_id}` en T2 y el panel la arma con ese orden en T3.
