# Carga inicial de horas de permiso ya consumidas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que RRHH pueda cargar las horas de permiso que un agente ya usó antes de que el sistema las registrara, y que esas horas achiquen su cupo anual en vez de regalárselas.

**Architecture:** Un valor guardado por empleado y año, en tabla propia, que `recalcular_anio` resta del cupo de la jornada antes de llamar al motor. El motor (`asistencia_calc.calcular_anio`) no cambia ni se entera: sigue recibiendo un número. Por eso descuenta siempre, haya marcaciones del reloj o no — que es lo que un permiso backdateado no lograría, porque `calcular_dia` ignora a propósito los permisos de días sin fichadas.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15 (App Router), React, Tailwind con los tokens CSS del proyecto.

## Global Constraints

- **Dos repos.** Backend: `C:\Users\Emiliano\Documents\Backend_RRHH`. Frontend: `C:\Users\Emiliano\Documents\RRHH`. Cada tarea dice en cuál trabaja. Los commits van en el repo que corresponde, nunca cruzados.
- Se guarda lo **consumido**, no lo que queda. El cupo es configuración que RRHH edita; las horas ya usadas son un hecho histórico que no se mueve.
- **Solo el año calendario en curso** es cargable. El año igual va estampado en la fila: sin esa columna, el 1 de enero la carga vieja seguiría descontando contra el cupo nuevo.
- La lectura de la tabla devuelve **`float | None`**, con `None` para "no hay fila". No coalesce a 0 adentro: el recálculo coalesce con `or 0.0`, y el `GET` conserva la distinción porque el panel muestra vacío o cero según corresponda.
- **`app/services/asistencia_calc.py` no se toca en ninguna tarea.** El motor no se entera de esta feature.
- Validación de `horasConsumidas`: no negativo, tope de 2000. **Sin tope contra el cupo del empleado**: alguien puede haber usado más horas de las que su cupo cubre.
- El permiso nuevo es `asistencia.cargaInicialPermisos`. **No se agrega a `PERMISOS_POR_ROL`**: es transitorio y se otorga a mano desde la UI de administración de roles, igual que `licencias.cargaInicial`, que tampoco está en ninguna tupla de rol.
- Backend: `python -m pytest` desde el repo. Los 4 archivos `tests/test_chat_*.py` pueden fallar al importar por falta de `google-genai` en algunos entornos: es preexistente y ajeno, no cuenta como falla. Comentarios del código Python **sin tildes** (convención del repo).
- Frontend: **no tiene runner de tests.** La verificación es `npx tsc --noEmit -p tsconfig.json`, y el criterio es **no agregar errores nuevos**. El repo arrastra 27 previos no relacionados; contalos con `grep -c "error TS"`, nunca por líneas de salida (tsc imprime contexto multilínea por error).
- Commits en español, estilo del repo (`feat(...)`, `fix(...)`, `test(...)`), terminando con una línea en blanco y `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Archivos con finales de línea LF y UTF-8.

---

## Estructura de archivos

### Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/database/consumo_inicial_permisos.py` | **Nuevo.** DDL, lectura y upsert de la tabla. |
| `app/permisos.py` | **Modificar.** Suma el código de permiso y su descripción. |
| `app/services/asistencia_recalc.py` | **Modificar.** El banco efectivo = cupo − consumo inicial. |
| `app/routes/carga_inicial_permisos.py` | **Nuevo.** Los dos endpoints. |
| `app/main.py` | **Modificar.** Registra el router nuevo. |
| `app/database/asistencia.py` | **Modificar.** `mis_permisos` suma `consumoInicial` y ajusta `restante`. |
| `tests/test_consumo_inicial_permisos.py` | **Nuevo.** Persistencia y permiso. |
| `tests/test_banco_con_carga_inicial.py` | **Nuevo.** El banco efectivo, incluido el caso sin marcaciones. |
| `tests/test_carga_inicial_permisos_endpoints.py` | **Nuevo.** Los dos endpoints. |
| `tests/test_mis_permisos.py` | **Modificar.** `consumoInicial` y el `restante` nuevo. |

### Frontend (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx` | **Nuevo.** El panel de carga. |
| `src/app/Componentes/TablaOperador/DetailTables.tsx` | **Modificar.** `PermissionHistoryTab` suma el botón y monta el panel. |
| `src/app/Componentes/TablaOperador/Perfildetail.tsx` | **Modificar.** Le pasa el empleado a `PermissionHistoryTab`. |
| `src/app/screens/MisPermisos/Screen.tsx` | **Modificar.** La línea "Ya usadas antes del registro". |

**Orden:** el backend completo primero (1 a 4), porque el frontend consume sus endpoints. Dentro del backend: la persistencia y el permiso (1), el efecto en el cálculo (2), los endpoints (3), y lo que ve el empleado (4). Después el frontend: el panel de RRHH (5) y la pantalla del empleado (6).

---

## Task 1: La tabla y el permiso

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Create: `app/database/consumo_inicial_permisos.py`
- Modify: `app/permisos.py` (el frozenset `PERMISOS` y el dict `DESCRIPCIONES`)
- Test: `tests/test_consumo_inicial_permisos.py` (nuevo)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `ensure_table(db: Session) -> None`
  - `carga_de_empleado(db: Session, employee_id: int, anio: int) -> dict | None` — la fila completa con `horasConsumidas`, `cargadoPor`, `cargadoEn`
  - `consumo_de_empleado(db: Session, employee_id: int, anio: int) -> float | None`
  - `upsert_consumo(db: Session, employee_id: int, anio: int, horas: float, cargado_por: int | None) -> None`
  - El código de permiso `"asistencia.cargaInicialPermisos"`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_consumo_inicial_permisos.py`:

```python
"""
Persistencia de las horas de permiso ya consumidas antes del alta.

Lo que mas importa acá: que la lectura distinga "no hay fila" de "hay una fila
en cero". Son estados distintos -no haber mirado a un empleado, y haber
determinado que no uso ninguna hora- y confundirlos regala el cupo entero.
"""

from app.database.consumo_inicial_permisos import (
    carga_de_empleado, consumo_de_empleado, upsert_consumo,
)
from app.permisos import DESCRIPCIONES, PERMISOS, PERMISOS_POR_ROL
from tests.fakes import FakeSession


def _db(filas):
    return FakeSession({"FROM ConsumoInicialPermiso": filas})


def test_sin_fila_el_consumo_es_none_y_no_cero():
    """None deja que rija el cupo completo; 0 afirma que no uso ninguna."""
    assert consumo_de_empleado(_db([]), 8, 2026) is None


def test_una_fila_en_cero_devuelve_cero_y_no_none():
    db = _db([{"horasConsumidas": 0, "cargadoPor": 3, "cargadoEn": None}])
    assert consumo_de_empleado(db, 8, 2026) == 0.0


def test_devuelve_las_horas_cargadas():
    db = _db([{"horasConsumidas": 5.5, "cargadoPor": 3, "cargadoEn": None}])
    assert consumo_de_empleado(db, 8, 2026) == 5.5


def test_la_lectura_filtra_por_empleado_y_anio():
    """Sin el filtro por anio, la carga de un anio descontaria en el otro."""
    db = _db([{"horasConsumidas": 5.0, "cargadoPor": None, "cargadoEn": None}])
    consumo_de_empleado(db, 8, 2026)
    sql, params = db.ejecutadas[0]
    assert "employeeId = :empId" in sql
    assert "anio = :anio" in sql
    assert params == {"empId": 8, "anio": 2026}


def test_carga_de_empleado_trae_la_trazabilidad():
    """El panel de RRHH muestra quien cargo y cuando."""
    db = _db([{"horasConsumidas": 5.0, "cargadoPor": 3, "cargadoEn": None}])
    fila = carga_de_empleado(db, 8, 2026)
    assert fila["horasConsumidas"] == 5.0
    assert fila["cargadoPor"] == 3


def test_el_upsert_corrige_en_vez_de_duplicar():
    """
    Corregir una carga equivocada es el caso normal, y la clave
    (employeeId, anio) es unica: un INSERT fallaria en el segundo intento.
    """
    db = FakeSession({})
    upsert_consumo(db, 8, 2026, 5.0, cargado_por=3)
    sql = db.sql_ejecutado()
    assert "MERGE ConsumoInicialPermiso" in sql
    # HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    # simultaneas de la misma clave entrando las dos por NOT MATCHED.
    assert "HOLDLOCK" in sql
    assert db.commits >= 1


# -- El permiso ----------------------------------------------------------------

def test_el_permiso_esta_en_el_catalogo_y_tiene_descripcion():
    assert "asistencia.cargaInicialPermisos" in PERMISOS
    assert DESCRIPCIONES["asistencia.cargaInicialPermisos"]


def test_el_permiso_no_se_siembra_en_ningun_rol():
    """
    Es transitorio: se otorga a mano desde la UI de roles y se revoca cuando
    termina la migracion. Sembrarlo lo volveria permanente de hecho.
    """
    for codigos in PERMISOS_POR_ROL.values():
        assert "asistencia.cargaInicialPermisos" not in codigos
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_consumo_inicial_permisos.py -v
```

Esperado: FALLA en el import con `ModuleNotFoundError: No module named 'app.database.consumo_inicial_permisos'`.

- [ ] **Step 3: Crear el módulo de persistencia**

Crear `app/database/consumo_inicial_permisos.py`:

```python
"""
Horas de permiso ya consumidas antes de que el sistema las registrara.

El cupo anual sale de la jornada laboral y se consume cronologicamente. Un
empleado recien dado de alta -o al que recien se le asigna una jornada- no
tiene ninguna fila de Permission del anio, asi que arranca con el cupo entero
aunque en la realidad ya se haya tomado horas que se llevaban en papel.

Esta tabla guarda lo que RRHH sabe: cuantas horas ya uso ese anio. Guarda lo
CONSUMIDO y no lo que le queda, al reves que SaldoInicialLicencia. Es
deliberado: el cupo de permisos no se deriva de nada, sale de
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
    cargadoEn       DATETIME2    NOT NULL,
    CONSTRAINT UQ_ConsumoInicialPermiso_emp_anio UNIQUE (employeeId, anio)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def carga_de_empleado(db: Session, employee_id: int, anio: int) -> dict | None:
    """
    La fila completa de ese empleado y anio, o None si no se cargo nada.

    El anio es parte de la clave y no un detalle: sin el, la carga de un anio
    seguiria descontando contra el cupo del siguiente.
    """
    fila = db.execute(
        text("""
            SELECT horasConsumidas, cargadoPor, cargadoEn
            FROM ConsumoInicialPermiso
            WHERE employeeId = :empId AND anio = :anio
        """),
        {"empId": employee_id, "anio": anio},
    ).mappings().first()
    return dict(fila) if fila else None


def consumo_de_empleado(db: Session, employee_id: int,
                        anio: int) -> float | None:
    """
    Las horas ya consumidas, o None cuando no hay fila.

    NO coalesce a 0 a proposito: sus dos consumidores necesitan cosas
    distintas. El recalculo hace la aritmetica y coalesce con `or 0.0`, porque
    sin carga el banco es el cupo entero. El endpoint conserva la distincion,
    porque el panel de RRHH muestra vacio o cero segun corresponda: no haber
    mirado a un empleado y haber determinado que no uso ninguna hora son cosas
    distintas. Si coalesciera aca, esa distincion se perderia en la capa de
    datos y no habria forma de recuperarla.
    """
    fila = carga_de_empleado(db, employee_id, anio)
    return float(fila["horasConsumidas"]) if fila else None


def upsert_consumo(db: Session, employee_id: int, anio: int,
                   horas: float, cargado_por: int | None) -> None:
    """
    Guarda las horas del anio, corrigiendo si ya habia una carga.

    Es MERGE y no INSERT porque corregir una carga equivocada es el caso
    normal y la clave (employeeId, anio) es unica: un INSERT fallaria en el
    segundo intento.

    HOLDLOCK evita la carrera clasica del MERGE en T-SQL: dos cargas
    simultaneas de la misma clave entrando las dos por NOT MATCHED.
    """
    db.execute(
        text("""
            MERGE ConsumoInicialPermiso WITH (HOLDLOCK) AS destino
            USING (SELECT :empId AS employeeId, :anio AS anio) AS origen
                ON destino.employeeId = origen.employeeId
               AND destino.anio = origen.anio
            WHEN MATCHED THEN
                UPDATE SET horasConsumidas = :horas,
                           cargadoPor = :cargadoPor,
                           cargadoEn = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (employeeId, anio, horasConsumidas, cargadoPor, cargadoEn)
                VALUES (:empId, :anio, :horas, :cargadoPor, GETDATE());
        """),
        {"empId": employee_id, "anio": anio, "horas": horas,
         "cargadoPor": cargado_por},
    )
    db.commit()
```

- [ ] **Step 4: Agregar el permiso al catálogo**

En `app/permisos.py`, dentro del frozenset `PERMISOS`, agregar el código justo después de `"asistencia.gestionar",` (línea 24):

```python
    "asistencia.cargaInicialPermisos",
```

Y en el dict `DESCRIPCIONES`, justo después de la línea de `"asistencia.gestionar"`:

```python
    "asistencia.cargaInicialPermisos": "Cargar horas de permiso ya consumidas previas al alta (transitorio)",
```

**No tocar `PERMISOS_POR_ROL`.** El permiso es transitorio y se otorga a mano desde la UI de administración de roles, igual que `licencias.cargaInicial`, que tampoco figura en ninguna tupla de rol. Hay un test que lo verifica.

- [ ] **Step 5: Correr los tests para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_consumo_inicial_permisos.py -v
```

Esperado: PASS los 8.

- [ ] **Step 6: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde salvo los 4 `tests/test_chat_*.py` si este entorno no tiene `google-genai`.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/consumo_inicial_permisos.py app/permisos.py tests/test_consumo_inicial_permisos.py
git commit -m "$(cat <<'EOF'
feat(permisos): tabla y permiso para la carga inicial de horas consumidas

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: El banco efectivo en el recálculo

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/services/asistencia_recalc.py` (el import, y la línea 299 donde se arma `banco_anual`)
- Test: `tests/test_banco_con_carga_inicial.py` (nuevo)

**Interfaces:**
- Consumes: `consumo_de_empleado(db, employee_id, anio) -> float | None` de la Task 1.
- Produces: nada que consuman otras tareas. Cambia el comportamiento de `recalcular_anio`.

**Lo que NO se toca:** `app/services/asistencia_calc.py`. El motor sigue recibiendo un número por parámetro y no se entera de que existe una carga inicial. Esa es justamente la propiedad que hace que descuente aunque el día no tenga marcaciones.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_banco_con_carga_inicial.py`:

```python
"""
El consumo inicial achica el banco con el que arranca el anio.

El test que mas importa es el ultimo: descuenta aunque el dia no tenga
marcaciones. Es lo que distingue este camino del de backdatear un permiso, que
no serviria -calcular_dia ignora a proposito los permisos de dias sin fichadas.
"""

from datetime import date

from app.services import asistencia_recalc as r
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db(cupo, carga_inicial):
    """
    FakeSession con un empleado, su cupo de jornada y su carga inicial.

    carga_inicial None simula que no hay fila en ConsumoInicialPermiso.
    """
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
        "FROM ConsumoInicialPermiso": (
            [] if carga_inicial is None
            else [{"horasConsumidas": carga_inicial,
                   "cargadoPor": None, "cargadoEn": None}]
        ),
    })


def _banco_usado(monkeypatch, db):
    """Corre recalcular_anio y devuelve el banco que recibio el motor."""
    capturado = {}

    def fake_calcular_anio(dias, tolerancias, banco_anual):
        capturado["banco"] = banco_anual
        return []

    monkeypatch.setattr(r, "calcular_anio", fake_calcular_anio)
    r.recalcular_anio(db, 8, 2026, hoy=HOY)
    return capturado["banco"]


def test_sin_carga_inicial_el_banco_es_el_cupo_entero(monkeypatch):
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=None)) == 12.0


def test_la_carga_inicial_achica_el_banco(monkeypatch):
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=5.0)) == 7.0


def test_una_carga_mayor_al_cupo_deja_el_banco_en_cero(monkeypatch):
    """
    Esa persona ya se paso: el banco arranca vacio y todo permiso del anio va
    derecho a horas a recuperar. Nunca negativo.
    """
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=20.0)) == 0.0


def test_una_carga_en_cero_deja_el_cupo_entero(monkeypatch):
    """Cero es una afirmacion ("no uso ninguna"), no una ausencia de dato."""
    assert _banco_usado(monkeypatch, _db(cupo=12.0, carga_inicial=0.0)) == 12.0


def test_descuenta_aunque_el_empleado_no_tenga_jornada(monkeypatch):
    """Sin jornada el cupo es 0, y el banco no puede irse a negativo."""
    assert _banco_usado(monkeypatch, _db(cupo=None, carga_inicial=5.0)) == 0.0


def test_el_descuento_no_depende_de_las_marcaciones(monkeypatch):
    """
    El motivo de ser de toda la feature.

    El FakeSession no devuelve ninguna marcacion, asi que todos los dias del
    anio quedan sin fichadas. Aun asi el banco llega achicado al motor: el
    descuento ocurre ANTES de calcular ningun dia. Un permiso backdateado a un
    dia sin marcaciones no lograria esto, porque calcular_dia los ignora.
    """
    db = _db(cupo=12.0, carga_inicial=5.0)
    assert _banco_usado(monkeypatch, db) == 7.0
    # Se confirma que efectivamente no habia marcaciones que ayudaran.
    assert "FROM Marcacion" in db.sql_ejecutado()
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_banco_con_carga_inicial.py -v
```

Esperado: `test_sin_carga_inicial_el_banco_es_el_cupo_entero`, `test_una_carga_en_cero_deja_el_cupo_entero` y `test_descuenta_aunque_el_empleado_no_tenga_jornada` pueden PASAR ya (el comportamiento sin carga no cambia); los otros tres FALLAN con el banco todavía en el cupo entero (por ejemplo `assert 12.0 == 7.0`).

- [ ] **Step 3: Restar el consumo inicial del banco**

En `app/services/asistencia_recalc.py`, agregar el import junto a los demás de `app.database` (cerca de la línea 24, donde ya importa de `app.database.asistencia`):

```python
from app.database.consumo_inicial_permisos import consumo_de_empleado
```

Y reemplazar la línea 299 (hoy `banco_anual = float(emp.get("horasPermisoAnual") or 0)`), conservando el comentario que ya está encima, por:

```python
    banco_anual = float(emp.get("horasPermisoAnual") or 0)
    # Las horas que la persona ya uso antes de que el sistema las registrara
    # achican el banco con el que arranca el anio. Se resta aca y no dentro
    # del motor a proposito: calcular_anio sigue recibiendo un numero y no se
    # entera de que esto existe, y por eso el descuento vale aunque el dia no
    # tenga marcaciones. Un permiso backdateado no lograria lo mismo, porque
    # calcular_dia ignora los permisos de un dia sin fichadas.
    #
    # El `or 0.0` coalesce el None de "no hay fila": aca la distincion entre
    # "sin carga" y "carga en cero" no cambia nada, las dos dejan el cupo
    # entero.
    consumo_inicial = consumo_de_empleado(db, employee_id, anio) or 0.0
    banco_anual = max(banco_anual - consumo_inicial, 0.0)
```

- [ ] **Step 4: Correr para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_banco_con_carga_inicial.py -v
```

Esperado: PASS los 6.

- [ ] **Step 5: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde. Si algún test de asistencia falla con `KeyError`, es un fixture de `FakeSession` al que le falta la clave `"FROM ConsumoInicialPermiso"`; agregársela devolviendo `[]` (sin carga inicial), que es el comportamiento previo.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/services/asistencia_recalc.py tests/test_banco_con_carga_inicial.py
git commit -m "$(cat <<'EOF'
feat(asistencia): la carga inicial achica el banco de permisos del anio

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Los endpoints de carga

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Create: `app/routes/carga_inicial_permisos.py`
- Modify: `app/main.py` (la línea 19 de imports y la lista de `include_router`)
- Test: `tests/test_carga_inicial_permisos_endpoints.py` (nuevo)

**Interfaces:**
- Consumes: `ensure_table`, `carga_de_empleado`, `upsert_consumo` de la Task 1; `recalcular_anio(db, employee_id, anio)` que ya existe.
- Produces:
  - `GET /asistencia/carga-inicial-permisos/{employee_id}` → `{ anio: int, cupoAnual: float, horasConsumidas: float | null, cargadoPor: int | null, cargadoEn: str | null }`
  - `PUT /asistencia/carga-inicial-permisos/{employee_id}` → body `{ horasConsumidas: number }`, responde `{ ok: true, anio, horasConsumidas }`

**Nota sobre el spec:** el spec dice que los endpoints van "en `app/routes/asistencia.py`". Este plan los pone en un router propio, `app/routes/carga_inicial_permisos.py`, por dos razones: `asistencia.py` ya es grande, y el precedente directo de esta feature —`app/routes/carga_inicial_licencias.py`— es exactamente un router propio con su prefijo. El spec pide "mismo patrón" en todo lo demás; esto lo hace consistente también acá.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_carga_inicial_permisos_endpoints.py`:

```python
"""
Los dos endpoints de carga inicial de horas de permiso.

Se invocan las funciones directo con un FakeSession, que es el patron de la
suite: no hay TestClient porque las dependencias de FastAPI (auth y sesion) se
resuelven por inyeccion y aca se pasan a mano.
"""

import pytest
from fastapi import HTTPException

from app.routes import carga_inicial_permisos as m
from tests.fakes import FakeSession


def _db(carga=None, cupo=12.0):
    return FakeSession({
        "FROM ConsumoInicialPermiso": (
            [] if carga is None
            else [{"horasConsumidas": carga, "cargadoPor": 3,
                   "cargadoEn": None}]
        ),
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


def test_rechaza_el_error_de_tipeo():
    """Mismo atajo que el cupo: 2000 h es mas que un anio laboral completo."""
    with pytest.raises(HTTPException) as e:
        m._validar_horas(2001)
    assert e.value.status_code == 400


def test_rechaza_lo_que_no_es_numero():
    with pytest.raises(HTTPException) as e:
        m._validar_horas("mucho")
    assert e.value.status_code == 400


def test_no_hay_tope_contra_el_cupo_del_empleado():
    """
    Alguien pudo haber usado mas horas de las que su cupo cubre, y eso tiene
    que poder cargarse: el banco queda en 0 y el resto del anio es deuda.
    """
    assert m._validar_horas(50) == 50.0


# -- GET -----------------------------------------------------------------------

def test_el_get_devuelve_null_cuando_no_hay_carga():
    """null y 0 son estados distintos y el panel los muestra distinto."""
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=None))
    assert r["horasConsumidas"] is None
    assert r["cupoAnual"] == 12.0


def test_el_get_devuelve_cero_cuando_la_carga_es_cero():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=0))
    assert r["horasConsumidas"] == 0.0


def test_el_get_trae_la_trazabilidad():
    r = m.get_carga_inicial_permisos(8, _user={}, db=_db(carga=5.0))
    assert r["horasConsumidas"] == 5.0
    assert r["cargadoPor"] == 3


# -- PUT -----------------------------------------------------------------------

def test_el_put_guarda_y_recalcula(monkeypatch):
    """
    El recalculo va sincrono: es un solo empleado, a diferencia del cambio de
    cupo de una jornada, que toca a toda su nomina.
    """
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))

    db = _db(carga=None)
    r = m.put_carga_inicial_permisos(
        8, {"horasConsumidas": 5}, user={"employeeId": 3}, db=db,
    )

    assert r["ok"] is True
    assert r["horasConsumidas"] == 5.0
    assert recalculos == [(8, r["anio"])]
    assert "MERGE ConsumoInicialPermiso" in db.sql_ejecutado()


def test_el_put_rechaza_un_valor_invalido_antes_de_escribir(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: None)
    db = _db(carga=None)
    with pytest.raises(HTTPException):
        m.put_carga_inicial_permisos(
            8, {"horasConsumidas": -1}, user={"employeeId": 3}, db=db,
        )
    assert "MERGE" not in db.sql_ejecutado()
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_carga_inicial_permisos_endpoints.py -v
```

Esperado: FALLA en el import con `ModuleNotFoundError: No module named 'app.routes.carga_inicial_permisos'`.

- [ ] **Step 3: Crear el router**

Crear `app/routes/carga_inicial_permisos.py`:

```python
"""
Carga inicial de horas de permiso ya consumidas.

Transitorio: existe para la migracion. Cuando termine, se le quita el permiso
al rol y los dos endpoints quedan inalcanzables sin tocar codigo.
"""

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.consumo_inicial_permisos import (
    carga_de_empleado, ensure_table, upsert_consumo,
)
from app.database.database import SessionLocal
from app.services.asistencia_recalc import recalcular_anio

router = APIRouter(prefix="/asistencia/carga-inicial-permisos",
                   tags=["Carga inicial permisos"])

# Mismo atajo contra el error de tipeo que usa el cupo de la jornada: 2000 h es
# mas que un anio laboral completo. No hay tope contra el cupo del empleado a
# proposito: alguien pudo haber usado mas horas de las que su cupo cubre, y eso
# tiene que poder cargarse.
HORAS_MAX = 2000.0

PERMISO = Depends(require_permission("asistencia.cargaInicialPermisos"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_horas(valor) -> float:
    """Normaliza horasConsumidas a float, o 400 si no tiene sentido."""
    try:
        horas = float(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="horasConsumidas debe ser un numero")
    if horas < 0:
        raise HTTPException(status_code=400,
                            detail="horasConsumidas no puede ser negativo")
    if horas > HORAS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"horasConsumidas no puede superar {int(HORAS_MAX)} horas")
    return horas


def _cupo_de_empleado(db: Session, employee_id: int) -> float:
    """El cupo de la jornada del empleado, 0 si no tiene jornada asignada."""
    fila = db.execute(text("""
        SELECT j.horasPermisoAnual AS cupo
        FROM Employee e
        LEFT JOIN JornadaLaboral j ON e.jornadaId = j.id
        WHERE e.id = :emp
    """), {"emp": employee_id}).mappings().first()
    return float(fila["cupo"] or 0) if fila else 0.0


@router.get("/{employee_id}")
def get_carga_inicial_permisos(employee_id: int, _user: dict = PERMISO,
                               db: Session = Depends(get_db)):
    """
    Lo cargado para el anio en curso, con el cupo como contexto.

    horasConsumidas null significa "no se cargo nada" y 0 significa "se
    determino que no uso ninguna". Son estados distintos y el panel los
    muestra distinto.
    """
    ensure_table(db)
    anio = date.today().year
    fila = carga_de_empleado(db, employee_id, anio)
    cargado_en = fila["cargadoEn"] if fila else None
    return {
        "anio": anio,
        "cupoAnual": _cupo_de_empleado(db, employee_id),
        "horasConsumidas": float(fila["horasConsumidas"]) if fila else None,
        "cargadoPor": fila["cargadoPor"] if fila else None,
        "cargadoEn": cargado_en.isoformat() if cargado_en else None,
    }


@router.put("/{employee_id}")
def put_carga_inicial_permisos(employee_id: int, data: dict = Body(...),
                               user: dict = PERMISO,
                               db: Session = Depends(get_db)):
    """
    Guarda las horas del anio en curso y recalcula ese anio del empleado.

    El anio no se recibe por parametro: siempre es el calendario en curso, que
    es el unico cargable. Aceptarlo del cliente abriria la puerta a escribir
    anios que despues nadie recalcula.

    El recalculo va sincrono porque es un solo empleado, a diferencia del
    cambio de cupo de una jornada, que toca a toda su nomina y por eso va en
    segundo plano.
    """
    ensure_table(db)
    horas = _validar_horas(data.get("horasConsumidas"))
    anio = date.today().year
    upsert_consumo(db, employee_id, anio, horas, user.get("employeeId"))
    recalcular_anio(db, employee_id, anio)
    return {"ok": True, "anio": anio, "horasConsumidas": horas}
```

- [ ] **Step 4: Registrar el router**

En `app/main.py`, agregar `carga_inicial_permisos` al final de la lista de imports de la línea 19 (que hoy termina en `carga_inicial_licencias`):

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes, asistencia, asistencia_ausencias, chat, logs_productividad, carga_inicial_licencias, carga_inicial_permisos
```

Y agregar la línea de registro junto a los demás `include_router`, inmediatamente después del de `carga_inicial_licencias`:

```python
app.include_router(carga_inicial_permisos.router)
```

- [ ] **Step 5: Correr para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_carga_inicial_permisos_endpoints.py -v
```

Esperado: PASS los 11.

- [ ] **Step 6: Verificar que la app levanta con el router nuevo**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -c "from app.main import app; print([r.path for r in app.routes if 'carga-inicial-permisos' in r.path])"
```

Esperado: imprime las dos rutas, `/asistencia/carga-inicial-permisos/{employee_id}` dos veces (GET y PUT).

- [ ] **Step 7: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/routes/carga_inicial_permisos.py app/main.py tests/test_carga_inicial_permisos_endpoints.py
git commit -m "$(cat <<'EOF'
feat(permisos): endpoints para cargar las horas ya consumidas

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: El consumo inicial en "Mis permisos"

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/asistencia.py` (la función `mis_permisos`, alrededor de las líneas 495-560)
- Test: `tests/test_mis_permisos.py` (agregar casos)

**Interfaces:**
- Consumes: `consumo_de_empleado(db, employee_id, anio) -> float | None` de la Task 1.
- Produces: `GET /asistencia/mis-permisos` suma la clave `consumoInicial` (`float | None`), y `restante` pasa a descontarla. La Task 6 consume esa clave.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `tests/test_mis_permisos.py`, agregar:

```python
def test_el_consumo_inicial_se_devuelve_y_descuenta_del_restante():
    """
    Las horas cargadas a mano no dejan filas en Permission ni en
    JornadaDiaria: si no se devolvieran, el restante quedaria inflado.
    """
    db = _db(cupo=12.0, consumido=2.0, deuda=0.0)
    db.respuestas["FROM ConsumoInicialPermiso"] = [
        {"horasConsumidas": 5.0, "cargadoPor": None, "cargadoEn": None}
    ]
    r = mis_permisos(db, 8, date.today().year)
    assert r["consumoInicial"] == 5.0
    # 12 de cupo, 5 cargadas a mano y 2 del sistema: quedan 5.
    assert r["restante"] == 5.0
    # consumido sigue siendo solo lo que registro el sistema: la pantalla las
    # muestra en lineas separadas para que el total cierre contra la lista.
    assert r["consumido"] == 2.0


def test_sin_carga_inicial_el_consumo_inicial_es_cero():
    r = mis_permisos(_db(cupo=12.0, consumido=2.0), 8, date.today().year)
    assert r["consumoInicial"] == 0.0
    assert r["restante"] == 10.0


def test_el_restante_no_baja_de_cero_con_la_carga_inicial():
    db = _db(cupo=12.0, consumido=2.0)
    db.respuestas["FROM ConsumoInicialPermiso"] = [
        {"horasConsumidas": 20.0, "cargadoPor": None, "cargadoEn": None}
    ]
    r = mis_permisos(db, 8, date.today().year)
    assert r["restante"] == 0.0


def test_el_consumo_inicial_es_null_para_un_anio_que_no_es_el_actual():
    """Misma regla que cupoAnual y restante: solo se muestra el anio en curso."""
    r = mis_permisos(_db(cupo=12.0), 8, date.today().year - 1)
    assert r["consumoInicial"] is None
```

Revisá el helper `_db(...)` que ya existe en ese archivo: construye un `FakeSession` con un diccionario de respuestas. Los tests nuevos le agregan la clave `"FROM ConsumoInicialPermiso"` después de construirlo; si la forma del helper no lo permite, extendelo para aceptar la carga inicial como parámetro con default `None`, manteniendo los tests existentes andando sin cambios.

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_mis_permisos.py -v -k "consumo_inicial or restante_no_baja"
```

Esperado: FALLAN con `KeyError: 'consumoInicial'`.

- [ ] **Step 3: Sumar el consumo inicial a la respuesta**

En `app/database/asistencia.py`, agregar el import junto a los demás del paquete `app.database`:

```python
from app.database.consumo_inicial_permisos import consumo_de_empleado
```

Dentro de `mis_permisos`, después de la línea que calcula `es_anio_actual` (hoy la 540), agregar:

```python
    # Horas que la persona ya uso antes de que el sistema las registrara. No
    # dejan filas en Permission ni en JornadaDiaria, asi que si no se
    # devolvieran el restante quedaria inflado.
    consumo_inicial = consumo_de_empleado(db, employee_id, anio) or 0.0
```

Y en el diccionario de retorno, agregar la clave nueva justo después de `"cupoAnual"`, y reemplazar la línea de `"restante"`:

```python
        "consumoInicial": round(consumo_inicial, 2) if es_anio_actual else None,
```

```python
        # Descuenta las dos cosas: lo cargado a mano y lo que registro el
        # sistema. Nunca negativo, por el mismo motivo de siempre -un
        # negativo aca se leeria como una deuda duplicada.
        "restante": (round(max(cupo - consumo_inicial - consumido, 0.0), 2)
                     if es_anio_actual else None),
```

- [ ] **Step 4: Correr para verificar que pasan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest tests/test_mis_permisos.py -v
```

Esperado: PASS todos, los previos incluidos.

- [ ] **Step 5: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && python -m pytest
```

Esperado: todo en verde.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/asistencia.py tests/test_mis_permisos.py
git commit -m "$(cat <<'EOF'
feat(permisos): mis-permisos devuelve el consumo inicial y lo descuenta

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: El panel de carga en el legajo

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Create: `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx`
- Modify: `src/app/Componentes/TablaOperador/DetailTables.tsx` (el componente `PermissionHistoryTab`, línea 909)
- Modify: `src/app/Componentes/TablaOperador/Perfildetail.tsx` (línea 203)

**Interfaces:**
- Consumes: `GET` y `PUT /asistencia/carga-inicial-permisos/{employee_id}` de la Task 3, con las formas exactas declaradas ahí.
- Produces: nada que consuman otras tareas.

**El detalle que no es obvio:** `PermissionHistoryTab` está escrito hoy como una arrow function de expresión única, con un `console.log(permisos)` colgando de un operador coma antes del JSX. Esa forma no admite hooks, y el panel necesita estado. Hay que convertirla a un cuerpo de función con `return`. El `console.log` se va en el camino: es una consecuencia necesaria del cambio, no limpieza al pasar.

- [ ] **Step 1: Crear el panel**

Crear `src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx`:

```tsx
"use client";

// Carga de las horas de permiso que el agente ya usó antes de que el sistema
// las registrara. Transitorio: existe para la migración, y se apaga quitándole
// el permiso al rol, sin tocar código.

import { useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";

interface CargaInicialPermisos {
  anio: number;
  cupoAnual: number;
  horasConsumidas: number | null;
  cargadoPor: number | null;
  cargadoEn: string | null;
}

interface Props {
  employeeId: number;
  onCerrar: () => void;
}

export function CargaInicialPermisosPanel({ employeeId, onCerrar }: Props) {
  const [datos, setDatos] = useState<CargaInicialPermisos | null>(null);
  // Texto y no número: el campo tiene que distinguir vacío ("no se cargó
  // nada") de "0" ("se determinó que no usó ninguna"), y un input numérico
  // colapsa los dos casos.
  const [valor, setValor] = useState("");
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<CargaInicialPermisos>(`/asistencia/carga-inicial-permisos/${employeeId}`)
      .then((r) => {
        setDatos(r);
        setValor(r.horasConsumidas === null ? "" : String(r.horasConsumidas));
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "No se pudo cargar el dato")
      )
      .finally(() => setCargando(false));
  }, [employeeId]);

  const guardar = async () => {
    setGuardando(true);
    setError(null);
    try {
      await apiClient.put(`/asistencia/carga-inicial-permisos/${employeeId}`, {
        horasConsumidas: Number(valor),
      });
      onCerrar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
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
        className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
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
          registrara. Se descuentan de su cupo anual.
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
                  {datos.cupoAnual} h
                </span>
              </p>
              {sinJornada && (
                <p className="text-warning-soft-foreground mt-1">
                  Este agente no tiene jornada laboral asignada, así que su cupo
                  es 0: todo permiso común ya le genera horas a recuperar.
                </p>
              )}
            </div>

            <label
              htmlFor="horas-consumidas"
              className="block text-sm font-medium text-foreground mb-1"
            >
              Horas ya consumidas
            </label>
            <input
              id="horas-consumidas"
              type="number"
              min="0"
              max="2000"
              step="0.5"
              value={valor}
              onChange={(e) => setValor(e.target.value)}
              placeholder="Sin cargar"
              className="w-full px-3 py-2 rounded-md border border-border bg-background text-foreground"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Dejarlo vacío significa que todavía no se revisó. Cargar 0 afirma
              que no usó ninguna.
            </p>

            {datos.cargadoEn && (
              <p className="text-xs text-muted-foreground mt-3">
                Última carga: {datos.cargadoEn.slice(0, 10)}
                {datos.cargadoPor !== null && ` · legajo ${datos.cargadoPor}`}
              </p>
            )}

            {error && <p className="text-sm text-error mt-3">{error}</p>}

            <div className="flex gap-3 pt-5">
              <button
                type="button"
                onClick={onCerrar}
                className="flex-1 py-2 bg-muted hover:bg-border rounded-xl text-sm font-bold"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={guardar}
                disabled={guardando || valor === ""}
                className="flex-1 py-2 bg-primary hover:opacity-90 text-primary-foreground rounded-xl text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {guardando ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Convertir `PermissionHistoryTab` y montarle el botón**

En `src/app/Componentes/TablaOperador/DetailTables.tsx`, agregar los imports que faltan junto a los que ya existen arriba del archivo:

```tsx
import { CargaInicialPermisosPanel } from "./CargaInicialPermisosPanel";
import { leerPermisos, tienePermiso } from "@/app/util/permisos";
```

Reemplazar la cabecera del componente (línea 909, hoy `export const PermissionHistoryTab = ({ permisos }: { permisos: Permit[] }) => (` seguida de `console.log(permisos),` y una línea en blanco) por:

```tsx
export const PermissionHistoryTab = ({
  permisos,
  employeeId,
}: {
  permisos: Permit[];
  employeeId: number;
}) => {
  const [panelAbierto, setPanelAbierto] = useState(false);
  // Transitorio: el permiso se revoca cuando termina la migracion y el boton
  // desaparece para todos, sin tocar codigo.
  const puedeCargar = tienePermiso(leerPermisos(), "asistencia.cargaInicialPermisos");

  return (
```

Dentro del JSX, inmediatamente después de la apertura de `<div className="bg-card p-6 rounded-lg shadow-sm">` (línea 913 hoy), agregar el botón:

```tsx
      {puedeCargar && (
        <div className="flex justify-end mb-4">
          <button
            type="button"
            onClick={() => setPanelAbierto(true)}
            className="text-primary hover:bg-primary/10 border border-primary/30 px-3 py-1.5 rounded-lg text-xs font-bold transition-all"
          >
            Cargar horas ya consumidas
          </button>
        </div>
      )}
```

Y al final del componente, reemplazar el cierre (hoy `  </div>\n);`) por:

```tsx
      </div>
      {panelAbierto && (
        <CargaInicialPermisosPanel
          employeeId={employeeId}
          onCerrar={() => setPanelAbierto(false)}
        />
      )}
    </div>
  );
};
```

Prestá atención al balanceo de etiquetas: el componente abre `<div className="mt-4 flow-root">` y adentro `<div className="bg-card ...">`. El panel va **fuera** del `div` de la tarjeta pero dentro del `div` raíz, y el `return (` nuevo exige que el `)` final pase a `);` con el `};` del cierre de la función. Si el conteo de `</div>` no cierra, `tsc` lo va a marcar en el paso siguiente.

- [ ] **Step 3: Pasarle el empleado desde el legajo**

En `src/app/Componentes/TablaOperador/Perfildetail.tsx`, la línea 203 pasa de:

```tsx
          <PermissionHistoryTab permisos={employee.permisos} />
```

a:

```tsx
          <PermissionHistoryTab permisos={employee.permisos} employeeId={employee.id} />
```

- [ ] **Step 4: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "DetailTables|Perfildetail|CargaInicialPermisos"
```

Esperado: sin salida.

Y confirmar que no subió el total:

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`, el baseline preexistente. **Contar así y no por líneas de salida**: tsc imprime contexto multilínea por error.

- [ ] **Step 5: Verificar en el navegador**

Con el backend corriendo y `npm run dev`, entrando con un usuario con `rrhh.gestionar`:

1. Abrir el legajo de un empleado → pestaña "Historial de Permisos". **Sin** el permiso `asistencia.cargaInicialPermisos`, el botón **no** aparece.
2. Otorgar el permiso al rol desde Administración, recargar, y confirmar que ahora sí aparece.
3. Tocar el botón: el panel abre mostrando el año, el cupo de la jornada del agente, y el campo vacío si nunca se cargó.
4. Guardar 5 horas: el panel cierra. Reabrirlo muestra 5 y la fecha de la última carga.
5. Corregir a 3 y guardar: reabrir muestra 3, no dos valores ni un error de clave duplicada.
6. Guardar 0: reabrir muestra `0`, distinto del vacío del paso 3.
7. Con un agente **sin jornada asignada**, el panel muestra el cupo 0 y el aviso correspondiente.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Componentes/TablaOperador/CargaInicialPermisosPanel.tsx src/app/Componentes/TablaOperador/DetailTables.tsx src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "$(cat <<'EOF'
feat(permisos): panel para cargar las horas ya consumidas desde el legajo

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: La línea en "Mis permisos"

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/screens/MisPermisos/Screen.tsx` (la interfaz `MisPermisosResp` en la línea 21, y el bloque de cifras del año actual que arranca en la línea 138)

**Interfaces:**
- Consumes: la clave `consumoInicial` (`number | null`) de `GET /asistencia/mis-permisos`, de la Task 4.
- Produces: nada.

- [ ] **Step 1: Sumar el campo a la interfaz**

En `src/app/screens/MisPermisos/Screen.tsx`, en `MisPermisosResp`, agregar la clave justo después de `cupoAnual`:

```tsx
  consumoInicial: number | null;
```

- [ ] **Step 2: Mostrar la línea**

El bloque de cuatro cifras del año actual arranca en la línea 138 con `{datos.cupoAnual !== null && datos.restante !== null ? (` y su `<div className="grid grid-cols-2 lg:grid-cols-4 gap-6">`. Dentro de ese grid, insertar una columna nueva **entre** la de "Cupo del año" y la de "Usado":

```tsx
                  {datos.consumoInicial !== null && datos.consumoInicial > 0 && (
                    <div>
                      <p className="text-sm text-muted-foreground mb-1">
                        Ya usadas antes del registro
                      </p>
                      <p className="text-2xl font-heading text-foreground">
                        {fmtHoras(datos.consumoInicial)}
                      </p>
                    </div>
                  )}
```

Se muestra solo cuando hay carga: una línea en cero sería ruido para la enorme mayoría, que no tiene ninguna.

No se suman dentro de "Usado" a propósito: el agente vería "Usado 7h" con una lista de permisos que suma 2h, y no cerraría a la vista. Es el mismo problema que ya se resolvió marcando los permisos oficiales, que tampoco consumen cupo.

El grid pasa de cuatro cifras a cinco **solo cuando hay carga inicial**, así que
la cantidad de columnas tiene que acompañar. Si quedara fija en 5, el caso
normal —que es la enorme mayoría, sin carga— mostraría cuatro cifras y un hueco.
Reemplazar la línea de apertura del grid por:

```tsx
                <div
                  className={`grid grid-cols-2 gap-6 ${
                    datos.consumoInicial !== null && datos.consumoInicial > 0
                      ? "lg:grid-cols-5"
                      : "lg:grid-cols-4"
                  }`}
                >
```

- [ ] **Step 3: Explicar de dónde salen esas horas**

Debajo del grid, junto al párrafo que ya existe condicionado a `datos.restante !== null`, agregar:

```tsx
              {datos.consumoInicial !== null && datos.consumoInicial > 0 && (
                <p className="text-sm text-muted-foreground mt-2">
                  Las horas &quot;ya usadas antes del registro&quot; las cargó
                  Recursos Humanos: son permisos que te tomaste antes de que el
                  sistema los registrara, y por eso no figuran en la lista de
                  abajo.
                </p>
              )}
```

Sin esa aclaración la cifra no tiene explicación posible desde la pantalla: no hay ninguna fila en la tabla que la respalde.

- [ ] **Step 4: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -i "MisPermisos"
```

Esperado: sin salida.

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`.

- [ ] **Step 5: Verificar en el navegador**

Con el backend corriendo y `npm run dev`:

1. Con un agente **sin** carga inicial, "Mis permisos" se ve igual que antes: cuatro cifras, sin la línea nueva.
2. Cargarle 5 horas desde el legajo (el panel de la Task 5) y volver a "Mis permisos" con ese agente: aparece "Ya usadas antes del registro: 5h 00m", y "Te queda" bajó en 5.
3. Las cifras cierran: cupo = ya usadas + usado + te queda, salvo que haya deuda.
4. El párrafo explicativo aparece solo cuando hay carga inicial.
5. En un año anterior, la línea **no** aparece (como cupo y restante, es del año en curso).

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/screens/MisPermisos/Screen.tsx
git commit -m "$(cat <<'EOF'
feat(permisos): Mis Permisos muestra las horas usadas antes del registro

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Autorrevisión del plan

**Cobertura del spec.** Cada unidad tiene tarea: la tabla `ConsumoInicialPermiso` con `UNIQUE (employeeId, anio)`, el módulo con `MERGE ... HOLDLOCK` y la lectura `float | None` (T1); el permiso `asistencia.cargaInicialPermisos` con su descripción y sin sembrar en roles (T1); el banco efectivo `max(cupo − inicial, 0)` con el motor intacto (T2); los dos endpoints con validación 0–2000 sin tope contra el cupo, el año siempre el calendario en curso, y el recálculo sincrónico (T3); `consumoInicial` en `mis-permisos` con el `restante` ajustado y la regla de solo-año-actual (T4); el botón gateado por el permiso y el panel con los tres estados vacío/cero/positivo más el cupo como contexto (T5); la línea propia "Ya usadas antes del registro" separada de "Usado" (T6).

**Una desviación del spec, deliberada.** El spec ubica los endpoints "en `app/routes/asistencia.py`". El plan crea `app/routes/carga_inicial_permisos.py`, un router propio. Razón: `asistencia.py` ya es grande, y el precedente directo de esta feature —`carga_inicial_licencias.py`— es exactamente un router propio con su prefijo. El spec pide "mismo patrón" en todo lo demás, y esto lo hace consistente también acá. Queda anotado en el bloque de la Task 3.

**Un detalle de layout que el plan resuelve.** El grid de cifras de "Mis
permisos" pasa de cuatro a cinco columnas solo cuando hay carga inicial. Si la
clase quedara fija en cinco, el caso normal —la enorme mayoría, sin carga—
mostraría cuatro cifras y un hueco.

**Dos cosas que el spec no decía y el plan decide.** Primero, el campo del panel es `type="number"` pero su estado es un **string**: es lo único que distingue vacío de cero, que es el punto de los tres estados; con un `number` los dos colapsan. El botón de guardar se deshabilita con el campo vacío, para que no se pueda mandar un `Number("")` que vale 0 y afirmaría algo que nadie dijo. Segundo, "Mis permisos" suma un párrafo explicando de dónde salen esas horas: sin él la cifra no tiene respaldo en la tabla de abajo y se lee como un error.

**Un arrastre necesario, no limpieza al pasar.** `PermissionHistoryTab` es hoy una arrow function de expresión única con un `console.log` colgado de un operador coma. Esa forma no admite hooks y el panel necesita estado, así que la T5 la convierte a cuerpo de función y el `console.log` se va con ella. Está dicho en el bloque de la tarea para que un revisor no lo lea como scope creep.

**Consistencia de nombres.** `consumo_de_empleado` / `carga_de_empleado` / `upsert_consumo` / `ensure_table` se declaran en T1 y se consumen con esos nombres exactos en T2 (`asistencia_recalc`), T3 (el router) y T4 (`mis_permisos`). `asistencia.cargaInicialPermisos` es el mismo literal en el catálogo (T1), en el `require_permission` del router (T3) y en el `tienePermiso` del frontend (T5). La clave `horasConsumidas` es la misma en la columna, en el body del `PUT`, en la respuesta del `GET` y en la interfaz `CargaInicialPermisos` del panel. `consumoInicial` se declara en T4 y se consume con ese nombre en la interfaz `MisPermisosResp` de T6. `employeeId` es el nombre de la prop nueva de `PermissionHistoryTab` en T5, y así se la pasa `Perfildetail.tsx`.
