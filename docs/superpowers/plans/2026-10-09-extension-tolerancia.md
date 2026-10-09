# Extensión de tolerancia por día — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que RRHH pueda extender, para un día puntual, los 15 minutos de tolerancia de quienes viven fuera del anillo de Circunvalación, sin tocar a los demás.

**Architecture:** Un flag por empleado (`Employee.fueraAnilloCircunvalacion`) decide a quién le aplica; una tabla `ExtensionTolerancia` guarda qué rige cada fecha. El motor de cálculo recibe un diccionario `fecha → Tolerancias` y no se entera de que esta feature existe: quien resuelve qué tolerancia corresponde a cada día es `asistencia_recalc`. En los días de extensión el margen estricto se iguala al otorgado, con lo que el abuso deja de dispararse solo, sin una regla nueva.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15 (App Router), React, Tailwind con los tokens del proyecto, PrimeReact `Toast`.

## Global Constraints

- **Dos repos.** Backend: `C:\Users\Emiliano\Documents\Backend_RRHH`. Frontend: `C:\Users\Emiliano\Documents\RRHH`. Cada tarea dice en cuál trabaja; los commits van en el repo que corresponde, nunca cruzados.
- **El tildado recibe la extensión.** Quien no tiene el check mantiene siempre sus 15 minutos, haya o no extensión cargada.
- **El valor cargado reemplaza, no se suma.** `00:30` significa que ese día la tolerancia es de 30 minutos en total.
- **La salida es opcional y tiene su propio valor.** Si no viene, ese día la salida queda en los 15 de config.
- **Los días de extensión no marcan abuso** a quien la usó: el margen estricto se iguala al otorgado.
- **`app/services/asistencia_calc.py` no aprende qué es una extensión.** Recibe `tolerancias_por_fecha: dict[date, Tolerancias]` y aplica el que corresponda. Nada de `if es_dia_de_extension` adentro del motor.
- **Una extensión por fecha** (clave única). Un segundo alta para la misma fecha responde 409 pidiendo borrar la que está.
- **Fecha de hoy en adelante**, validado en el servidor y no solo con el `min` del input.
- **Cada valor tiene que ser mayor que la tolerancia vigente de su extremo** (entrada contra `toleranciaEntradaMin`, salida contra `toleranciaSalidaMin`), y **con tope de 480 minutos**.
- **El campo del legajo es exclusivo de `rrhh.gestionar`**: si viene en el `PUT` y quien lo manda no lo tiene, responde **403**, no lo ignora en silencio.
- Los tres endpoints de extensión van bajo `require_permission("asistencia.gestionar")`.
- Si el recálculo posterior a un alta, una baja o un cambio del check falla, el dato ya quedó escrito: se registra y el job nocturno lo corrige. Nunca un 500 que haga creer que no se guardó.
- Backend: `"./venv/Scripts/python.exe" -m pytest` desde el repo. Los 4 `tests/test_chat_*.py` pueden fallar al importar por falta de `google-genai`: es preexistente y ajeno. Comentarios del código Python **sin tildes**.
- Frontend: **sin runner de tests.** Verificación `npx tsc --noEmit -p tsconfig.json`, criterio no agregar errores nuevos. El baseline es **27**; contalo con `grep -c "error TS"`, nunca por líneas de salida.
- Commits en español, estilo del repo (`feat(...)`, `fix(...)`), con línea en blanco y la línea `Co-Authored-By` que indique el entorno.
- Archivos con finales de línea LF y UTF-8.

---

## Estructura de archivos

### Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/database/asistencia.py` | **Modificar.** Suma el `ALTER` de `Employee.fueraAnilloCircunvalacion` a `ensure_tables`. |
| `app/routes/employee.py` | **Modificar.** El campo entra en la lista blanca del `PUT` con guard propio de `rrhh.gestionar`, y al cambiar dispara el recálculo. |
| `app/routes/rrhh.py` | **Modificar.** El `SELECT` y el dict del listado devuelven el campo. |
| `app/database/extension_tolerancia.py` | **Nuevo.** DDL, listado, alta y baja de `ExtensionTolerancia`. |
| `app/services/asistencia_calc.py` | **Modificar.** `calcular_anio` suma `tolerancias_por_fecha`. |
| `app/services/asistencia_recalc.py` | **Modificar.** Arma el diccionario por fecha; suma `recalcular_marcados_fuera_del_anillo`. |
| `app/routes/extension_tolerancia.py` | **Nuevo.** Los tres endpoints. |
| `app/main.py` | **Modificar.** Registra el router nuevo. |
| `tests/test_flag_fuera_del_anillo.py` | **Nuevo.** La columna, el guard del `PUT` y el recálculo al cambiarlo. |
| `tests/test_extension_tolerancia_db.py` | **Nuevo.** Persistencia de las extensiones. |
| `tests/test_tolerancia_por_fecha.py` | **Nuevo.** El motor con override, y el abuso que no se dispara. |
| `tests/test_extension_tolerancia_endpoints.py` | **Nuevo.** Los tres endpoints y sus validaciones. |

### Frontend (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Interfas/Interfaces.ts` | **Modificar.** `Employee` suma el campo. |
| `src/app/Componentes/TablaOperador/DetailTables.tsx` | **Modificar.** El check al lado del Domicilio en `ProfileTab`. |
| `src/app/Componentes/Asistencia/ExtensionToleranciaModal.tsx` | **Nuevo.** El modal con el alta y la lista. |
| `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` | **Modificar.** El botón "Extender tolerancia" y el montaje del modal. |

**Orden:** backend completo primero (1 a 4), porque el frontend consume sus endpoints. Dentro del backend: el flag (1), la tabla (2), el motor (3) y los endpoints (4). Después el frontend: el check (5) y el tablero (6).

---

## Task 1: El flag en el legajo

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/database/asistencia.py` (constante de DDL nueva, y `ensure_tables`)
- Modify: `app/routes/employee.py:586` (la lista blanca) y el cuerpo de `update_employee`
- Modify: `app/routes/rrhh.py:113` (el `SELECT`) y `:386` (el dict de salida)
- Test: `tests/test_flag_fuera_del_anillo.py` (nuevo)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: la columna `Employee.fueraAnilloCircunvalacion` (BIT, default 0), y la clave `fueraAnilloCircunvalacion` (bool) en el JSON de `GET /rrhh/employees`, que consume la Task 5.

**Por qué el guard:** `update_employee` autoriza con `if current_user["employeeId"] != employee_id and not tiene_permiso(..., "rrhh.gestionar")`, o sea que **el propio empleado puede editar su legajo**. Correcto para teléfono o domicilio; inaceptable para este campo, que otorga un beneficio: sin guard, cualquiera se auto-tilda y se gana la tolerancia extendida.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_flag_fuera_del_anillo.py`:

```python
"""
El flag que marca a quien vive fuera del anillo de Circunvalacion.

Lo que mas importa aca es el guard: PUT /employee/{id} deja que el propio
empleado edite su legajo, y este campo otorga un beneficio. Sin el guard,
cualquiera se auto-tilda y se gana la tolerancia extendida.
"""

import pytest
from fastapi import HTTPException

from app.routes import employee as m
from tests.fakes import FakeSession


def _db():
    return FakeSession({"SELECT id FROM Employee": [{"id": 8}]})


def _usuario(employee_id, permisos):
    return {"employeeId": employee_id, "permisos": set(permisos)}


def test_rrhh_puede_tildar_el_flag(monkeypatch):
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    m.update_employee(
        8, {"fueraAnilloCircunvalacion": True}, db=db,
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    assert "fueraAnilloCircunvalacion" in db.sql_ejecutado()


def test_el_propio_empleado_no_puede_tildarse_el_flag(monkeypatch):
    """
    Sin esto el campo seria autoservicio: el empleado se marca solo y se
    gana la tolerancia extendida que RRHH otorga.
    """
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    with pytest.raises(HTTPException) as e:
        m.update_employee(
            8, {"fueraAnilloCircunvalacion": True}, db=db,
            current_user=_usuario(8, ["perfil.editar"]),
        )
    assert e.value.status_code == 403
    assert "fueraAnilloCircunvalacion" not in db.sql_ejecutado()


def test_el_empleado_sigue_pudiendo_editar_sus_otros_datos(monkeypatch):
    """El guard es solo para este campo, no cierra la edicion del legajo."""
    monkeypatch.setattr(m, "recalcular_anio", lambda db, eid, anio: 0)
    db = _db()
    m.update_employee(
        8, {"phone": "351-1234567"}, db=db,
        current_user=_usuario(8, ["perfil.editar"]),
    )
    assert "phone" in db.sql_ejecutado()


def test_cambiar_el_flag_recalcula_el_anio_del_empleado(monkeypatch):
    """
    Tildar a alguien despues de un dia con extension deja sus dias ya
    calculados sin el beneficio; destildarlo lo deja aplicado en dias ya
    liquidados. En los dos casos hay que recalcular.
    """
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    m.update_employee(
        8, {"fueraAnilloCircunvalacion": False}, db=_db(),
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    from datetime import date
    assert recalculos == [(8, date.today().year)]


def test_un_put_sin_el_flag_no_recalcula(monkeypatch):
    """Cambiar el telefono no tiene por que recomputar el anio."""
    recalculos = []
    monkeypatch.setattr(m, "recalcular_anio",
                        lambda db, eid, anio: recalculos.append((eid, anio)))
    m.update_employee(
        8, {"phone": "351-1234567"}, db=_db(),
        current_user=_usuario(99, ["rrhh.gestionar"]),
    )
    assert recalculos == []
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_flag_fuera_del_anillo.py -v
```

Esperado: FALLAN. El guard todavía no existe, así que `test_el_propio_empleado_no_puede_tildarse_el_flag` no levanta 403, y los de recálculo fallan porque `employee.py` no importa `recalcular_anio`.

- [ ] **Step 3: Agregar la columna**

En `app/database/asistencia.py`, agregar la constante después de `ALTER_JORNADA_CUPO_PERMISO_SQL`:

```python
# Marca a quien vive fuera del anillo de Circunvalacion. De este flag depende
# a quien le aplican las extensiones de tolerancia que RRHH otorga para un dia
# puntual; quien no lo tiene mantiene siempre los 15 minutos.
ALTER_EMPLOYEE_FUERA_ANILLO_SQL = """
IF COL_LENGTH('Employee','fueraAnilloCircunvalacion') IS NULL
ALTER TABLE Employee ADD fueraAnilloCircunvalacion BIT NOT NULL DEFAULT 0;
"""
```

Y en `ensure_tables`, junto a los demás `ALTER`, antes de `auditoria_ensure_tables(db)`:

```python
    db.execute(text(ALTER_EMPLOYEE_FUERA_ANILLO_SQL))
    db.commit()
```

- [ ] **Step 4: Sumar el guard y el recálculo al `PUT`**

En `app/routes/employee.py`, agregar el import junto a los demás:

```python
from app.services.asistencia_recalc import recalcular_anio
```

Dentro de `update_employee`, inmediatamente después del chequeo de permiso que ya existe (el que levanta "No tenés permiso para editar este empleado"), agregar:

```python
    # Este campo otorga un beneficio -las extensiones de tolerancia que RRHH
    # da para un dia puntual-, asi que no puede viajar por el permiso general
    # del legajo, que deja al propio empleado editarse. Se rechaza explicito
    # y no en silencio: ignorarlo dejaria a RRHH viendo la tilde en pantalla
    # sin que se hubiera guardado nada.
    if ("fueraAnilloCircunvalacion" in data
            and not tiene_permiso(current_user["permisos"], "rrhh.gestionar")):
        raise HTTPException(
            status_code=403,
            detail="Solo RRHH puede cambiar si el agente vive fuera del anillo")
```

Agregar el campo a la lista blanca de la línea 586, que pasa a:

```python
    employee_fields = ["name", "email", "birthDate", "address", "phone", "photo",
                       "horas", "departmentId", "officeId",
                       "fueraAnilloCircunvalacion"]
```

Y al final de la función, justo antes del `return`, agregar:

```python
    # El flag decide que tolerancia rigio en los dias con extension: cambiarlo
    # cambia retroactivamente el calculo de esos dias. Es un solo empleado, asi
    # que va sincrono. Si el recalculo falla, el campo ya quedo guardado: se
    # registra y el job nocturno lo corrige -un 500 aca haria creer que no se
    # guardo cuando si se guardo.
    if "fueraAnilloCircunvalacion" in data:
        try:
            recalcular_anio(db, employee_id, date.today().year)
        except Exception as e:
            log.warning("Recalculo fallido tras cambiar el flag de anillo "
                        "para el empleado %s: %s", employee_id, e)
```

Si `date` o `log` no están importados en ese archivo, agregarlos: `from datetime import date` y `import logging` con `log = logging.getLogger(__name__)` al nivel del módulo.

- [ ] **Step 5: Devolver el campo en el listado**

En `app/routes/rrhh.py`, agregar la columna al `SELECT` del listado de empleados, después de `e.phone` (línea 114):

```sql
            e.fueraAnilloCircunvalacion,
```

Y al dict de salida, después de `"address": emp["address"],` (línea 386):

```python
            "fueraAnilloCircunvalacion": bool(emp["fueraAnilloCircunvalacion"]),
```

- [ ] **Step 6: Correr los tests**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_flag_fuera_del_anillo.py -v
```

Esperado: PASS los 5.

- [ ] **Step 7: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde. Si algún test de `rrhh.py` falla con `KeyError: 'fueraAnilloCircunvalacion'`, es un fixture de `FakeSession` al que le falta la clave nueva en la fila de `Employee`: agregársela con `0`.

- [ ] **Step 8: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/asistencia.py app/routes/employee.py app/routes/rrhh.py tests/test_flag_fuera_del_anillo.py
git commit -m "$(cat <<'EOF'
feat(asistencia): flag de quien vive fuera del anillo, solo editable por RRHH

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: La tabla de extensiones

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Create: `app/database/extension_tolerancia.py`
- Test: `tests/test_extension_tolerancia_db.py` (nuevo)

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces:
  - `ensure_table(db: Session) -> None`
  - `listar(db: Session) -> list[dict]` — todas, la más nueva primero
  - `extensiones_por_fecha(db: Session, desde: date, hasta: date) -> dict[date, dict]` — indexado por fecha, lo que consume la Task 3
  - `existe_para_fecha(db: Session, fecha: date) -> bool`
  - `agregar(db: Session, fecha: date, entrada_min: int, salida_min: int | None, cargado_por: int | None) -> None`
  - `borrar(db: Session, extension_id: int) -> date | None` — la fecha de lo borrado, o `None` si no existía

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_extension_tolerancia_db.py`:

```python
"""
Persistencia de las extensiones de tolerancia.

Una extension por fecha: es una propiedad del dia, no un libro de asientos.
borrar() devuelve la fecha y no un bool porque el caller necesita saber que
anio recalcular.
"""

from datetime import date

from app.database.extension_tolerancia import (
    agregar, borrar, existe_para_fecha, extensiones_por_fecha, listar,
)
from tests.fakes import FakeSession


def test_listar_devuelve_las_extensiones_con_su_id():
    """El id es lo que el modal necesita para poder borrar una puntual."""
    filas = [{"id": 2, "fecha": date(2026, 10, 15), "toleranciaEntradaMin": 30,
              "toleranciaSalidaMin": None, "cargadoPor": 3, "cargadoEn": None}]
    db = FakeSession({"FROM ExtensionTolerancia": filas})
    r = listar(db)
    assert r[0]["id"] == 2
    assert r[0]["toleranciaEntradaMin"] == 30
    assert r[0]["toleranciaSalidaMin"] is None


def test_extensiones_por_fecha_indexa_por_fecha():
    """Asi el recalculo resuelve cada dia con un lookup y no recorriendo."""
    filas = [{"fecha": date(2026, 10, 15), "toleranciaEntradaMin": 30,
              "toleranciaSalidaMin": 20}]
    db = FakeSession({"FROM ExtensionTolerancia": filas})
    r = extensiones_por_fecha(db, date(2026, 1, 1), date(2026, 12, 31))
    assert r[date(2026, 10, 15)]["toleranciaEntradaMin"] == 30
    assert r[date(2026, 10, 15)]["toleranciaSalidaMin"] == 20


def test_extensiones_por_fecha_acota_al_rango():
    """Sin el filtro, un recalculo de un anio traeria las de todos."""
    db = FakeSession({"FROM ExtensionTolerancia": []})
    extensiones_por_fecha(db, date(2026, 1, 1), date(2026, 12, 31))
    sql, params = db.ejecutadas[0]
    assert "fecha >= :desde" in sql
    assert "fecha <= :hasta" in sql
    assert params == {"desde": date(2026, 1, 1), "hasta": date(2026, 12, 31)}


def test_existe_para_fecha_detecta_la_duplicada():
    db = FakeSession({"FROM ExtensionTolerancia": [{"id": 1}]})
    assert existe_para_fecha(db, date(2026, 10, 15)) is True


def test_existe_para_fecha_sin_fila_es_false():
    db = FakeSession({"FROM ExtensionTolerancia": []})
    assert existe_para_fecha(db, date(2026, 10, 15)) is False


def test_agregar_inserta_con_la_salida_opcional_en_null():
    db = FakeSession({})
    agregar(db, date(2026, 10, 15), 30, None, cargado_por=3)
    sql, params = db.ejecutadas[0]
    assert "INSERT INTO ExtensionTolerancia" in sql
    assert params["salidaMin"] is None
    assert db.commits >= 1


def test_borrar_devuelve_la_fecha_de_lo_borrado():
    """
    El caller necesita el anio de ESA fecha para recalcular, no el actual:
    una extension de diciembre borrada en enero pertenece a diciembre.
    """
    db = FakeSession({"DELETE FROM ExtensionTolerancia": [{"fecha": date(2024, 5, 2)}]})
    assert borrar(db, 1) == date(2024, 5, 2)


def test_borrar_lo_que_no_existe_devuelve_none():
    db = FakeSession({"DELETE FROM ExtensionTolerancia": []})
    assert borrar(db, 999) is None
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_extension_tolerancia_db.py -v
```

Esperado: FALLA en el import con `ModuleNotFoundError: No module named 'app.database.extension_tolerancia'`.

- [ ] **Step 3: Crear el módulo**

Crear `app/database/extension_tolerancia.py`:

```python
"""
Extensiones de tolerancia por dia.

Un dia excepcional -un temporal, un paro de transporte- no le pega igual a
todos: quien vive fuera del anillo de Circunvalacion viaja mucho mas. RRHH
carga aca que tolerancia rige ese dia, y aplica solo a los marcados con
Employee.fueraAnilloCircunvalacion.

El valor REEMPLAZA los 15 minutos, no se suma: lo que RRHH ve en pantalla es
el numero final que va a regir.

Una fila por fecha. Es una propiedad del dia, no un libro de asientos que se
acumula, y por eso la clave unica: un segundo alta para la misma fecha se
rechaza en vez de pisar en silencio un valor que le perdona horas a media
planta.

Vive en la base de RRHH. ObraSocial es de solo lectura sin excepcion.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_TABLE_SQL = """
IF OBJECT_ID('ExtensionTolerancia', 'U') IS NULL
CREATE TABLE ExtensionTolerancia (
    id                   INT IDENTITY(1,1) PRIMARY KEY,
    fecha                DATE      NOT NULL,
    toleranciaEntradaMin INT       NOT NULL,
    toleranciaSalidaMin  INT       NULL,
    cargadoPor           INT       NULL,
    cargadoEn            DATETIME2 NOT NULL,
    CONSTRAINT UQ_ExtensionTolerancia_fecha UNIQUE (fecha)
);
"""


def ensure_table(db: Session) -> None:
    """Crea la tabla. Seguro de repetir."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def listar(db: Session) -> list[dict]:
    """Todas las extensiones, la mas nueva primero."""
    filas = db.execute(text("""
        SELECT id, fecha, toleranciaEntradaMin, toleranciaSalidaMin,
               cargadoPor, cargadoEn
        FROM ExtensionTolerancia
        ORDER BY fecha DESC
    """)).mappings().all()
    return [dict(f) for f in filas]


def extensiones_por_fecha(db: Session, desde: date,
                          hasta: date) -> dict[date, dict]:
    """
    Las extensiones del rango, indexadas por fecha.

    Indexado y no una lista porque el recalculo resuelve dia por dia: con el
    diccionario cada dia es un lookup, y recorrer una lista por cada uno de
    los 365 dias seria cuadratico sin necesidad.
    """
    filas = db.execute(text("""
        SELECT fecha, toleranciaEntradaMin, toleranciaSalidaMin
        FROM ExtensionTolerancia
        WHERE fecha >= :desde AND fecha <= :hasta
    """), {"desde": desde, "hasta": hasta}).mappings().all()
    return {
        (f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()): {
            "toleranciaEntradaMin": int(f["toleranciaEntradaMin"]),
            "toleranciaSalidaMin": (None if f["toleranciaSalidaMin"] is None
                                    else int(f["toleranciaSalidaMin"])),
        }
        for f in filas
    }


def existe_para_fecha(db: Session, fecha: date) -> bool:
    """Si ya hay una extension cargada para ese dia."""
    fila = db.execute(text("""
        SELECT id FROM ExtensionTolerancia WHERE fecha = :fecha
    """), {"fecha": fecha}).mappings().first()
    return fila is not None


def agregar(db: Session, fecha: date, entrada_min: int,
            salida_min: int | None, cargado_por: int | None) -> None:
    """Da de alta la extension de un dia."""
    db.execute(text("""
        INSERT INTO ExtensionTolerancia
            (fecha, toleranciaEntradaMin, toleranciaSalidaMin,
             cargadoPor, cargadoEn)
        VALUES (:fecha, :entradaMin, :salidaMin, :cargadoPor, GETDATE())
    """), {"fecha": fecha, "entradaMin": entrada_min,
           "salidaMin": salida_min, "cargadoPor": cargado_por})
    db.commit()


def borrar(db: Session, extension_id: int) -> date | None:
    """
    Borra una extension y devuelve la fecha que tenia, o None si no existia.

    Devuelve la fecha -y no un bool- porque el caller necesita saber que anio
    recalcular: una extension de diciembre borrada ya entrado enero pertenece
    a diciembre, no al anio en curso. OUTPUT lo trae en la misma sentencia,
    sin un SELECT antes que dejaria una ventana entre leer y borrar.
    """
    fila = db.execute(text("""
        DELETE FROM ExtensionTolerancia
        OUTPUT deleted.fecha
        WHERE id = :id
    """), {"id": extension_id}).mappings().first()
    db.commit()
    if fila is None:
        return None
    f = fila["fecha"]
    return f if isinstance(f, date) else f.date()
```

- [ ] **Step 4: Crear la tabla al arrancar**

En `app/database/asistencia.py`, agregar el import junto a los demás del paquete:

```python
from app.database.extension_tolerancia import (
    ensure_table as extension_tolerancia_ensure_table,
)
```

Y en `ensure_tables`, junto a las otras llamadas del final (donde ya está `consumo_inicial_ensure_table(db)`):

```python
    # recalcular_anio lee esta tabla en cada corrida, no solo cuando alguien
    # entra al tablero: tiene que existir antes del primer SELECT.
    extension_tolerancia_ensure_table(db)
```

- [ ] **Step 5: Correr los tests**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_extension_tolerancia_db.py -v
```

Esperado: PASS los 8.

- [ ] **Step 6: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde.

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/database/extension_tolerancia.py app/database/asistencia.py tests/test_extension_tolerancia_db.py
git commit -m "$(cat <<'EOF'
feat(asistencia): tabla de extensiones de tolerancia por dia

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: El motor con tolerancia por fecha

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Modify: `app/services/asistencia_calc.py:248-267` (`calcular_anio`)
- Modify: `app/services/asistencia_recalc.py:50-66` (`_datos_empleado`) y `:313-318` (la llamada al motor)
- Test: `tests/test_tolerancia_por_fecha.py` (nuevo)

**Interfaces:**
- Consumes: `extensiones_por_fecha(db, desde, hasta) -> dict[date, dict]` de la Task 2.
- Produces:
  - `calcular_anio(dias, tolerancias, banco_anual, tolerancias_por_fecha: dict[date, Tolerancias] | None = None)`
  - `_datos_empleado` devuelve ahora también `fueraAnilloCircunvalacion`

**El corazón de la feature, y lo que NO hay que hacer:** el motor recibe `Tolerancias` ya resueltas por fecha. No recibe extensiones, ni el flag, ni sabe qué es el anillo de Circunvalación. Nada de `if es_dia_de_extension` dentro de `asistencia_calc.py`.

**Y el abuso sale gratis:** para un día de extensión el orquestador iguala el margen estricto al otorgado. Como la fórmula que ya existe es `abuso = uso_tolerancia and desvio > estricta`, y dentro de la tolerancia el desvío nunca supera un estricto que vale lo mismo, el abuso no se dispara. No se toca `_ajustar_por_tolerancia`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_tolerancia_por_fecha.py`:

```python
"""
La tolerancia puede variar por dia, y el motor no sabe por que.

calcular_anio recibe un diccionario fecha -> Tolerancias y aplica el que
corresponda. No sabe que existe una "extension" ni que es el anillo de
Circunvalacion: eso lo resuelve asistencia_recalc, que es el que habla con
la base.
"""

from datetime import date, datetime

from app.services import asistencia_calc as c
from app.services import marcaciones_norm as n

JORNADA_8H = n.HorarioDia(horaInicio=8.0, horaFin=16.0, horasTrabajo=8.0)
TOL = c.Tolerancias(entradaMin=15, salidaMin=15,
                    estrictaEntradaMin=7, estrictaSalidaMin=5)
# Un dia de extension: 30 minutos otorgados, y el margen estricto igualado al
# otorgado para que entrar dentro de lo concedido no deje marca de abuso.
TOL_EXTENDIDA = c.Tolerancias(entradaMin=30, salidaMin=15,
                              estrictaEntradaMin=30, estrictaSalidaMin=5)

MIERCOLES = date(2026, 7, 1)
JUEVES = date(2026, 7, 2)


def _dia(fecha, entrada_h, entrada_m):
    return c.EntradaDia(
        fecha=fecha,
        extremos=n.normalizar(
            [datetime(fecha.year, fecha.month, fecha.day, entrada_h, entrada_m),
             datetime(fecha.year, fecha.month, fecha.day, 16, 0)],
            JORNADA_8H, None,
        ),
        horario=JORNADA_8H, es_feriado=False, tiene_licencia=False,
        permisos=[],
    )


def test_sin_overrides_el_anio_calcula_igual_que_siempre():
    """La garantia de que esto no toca a nadie que no tenga el flag."""
    sin = c.calcular_anio([_dia(MIERCOLES, 8, 20)], TOL, 12.0)
    con_dict_vacio = c.calcular_anio([_dia(MIERCOLES, 8, 20)], TOL, 12.0, {})
    assert sin[0].saldoDia == con_dict_vacio[0].saldoDia
    assert sin[0].abusoEntrada == con_dict_vacio[0].abusoEntrada


def test_el_dia_con_override_usa_la_tolerancia_extendida():
    """Entrar 8:25 con 30 min otorgados no descuenta nada."""
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 25)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.horasTrabajadas == 8.0
    assert r.saldoDia == 0.0


def test_el_dia_con_override_no_marca_abuso():
    """
    El motivo de igualar el margen estricto al otorgado: sin eso, todo el
    que llega 8:08 o despues quedaria marcado como abuso justo el dia que
    RRHH le dio el permiso.
    """
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 25)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.abusoEntrada is False


def test_pasarse_de_la_tolerancia_extendida_si_descuenta():
    """La extension corre el limite, no lo elimina."""
    r, = c.calcular_anio([_dia(MIERCOLES, 8, 40)], TOL, 12.0,
                         {MIERCOLES: TOL_EXTENDIDA})
    assert r.saldoDia < 0


def test_un_dia_sin_override_en_un_anio_que_tiene_otros_usa_la_normal():
    """El override es por fecha, no por anio."""
    miercoles, jueves = c.calcular_anio(
        [_dia(MIERCOLES, 8, 25), _dia(JUEVES, 8, 25)], TOL, 12.0,
        {MIERCOLES: TOL_EXTENDIDA},
    )
    assert miercoles.saldoDia == 0.0
    # El jueves no tiene extension: 25 minutos pasan los 15 de siempre.
    assert jueves.saldoDia < 0
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_tolerancia_por_fecha.py -v
```

Esperado: FALLAN con `TypeError: calcular_anio() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Sumar el parámetro al motor**

En `app/services/asistencia_calc.py`, reemplazar `calcular_anio` entera por:

```python
def calcular_anio(dias: list[EntradaDia], tolerancias: Tolerancias,
                  banco_anual: float,
                  tolerancias_por_fecha: Optional[dict] = None) -> list[ResultadoDia]:
    """
    Recorre los dias en orden cronologico arrastrando el consumo del banco de
    permisos. Es el unico lugar donde el banco cambia de valor.

    El cupo entra por parametro y no como constante: cada jornada laboral
    tiene el suyo, y un empleado sin jornada asignada recibe 0.0. Quien lo
    resuelve es asistencia_recalc, que es el que habla con la base; aca se
    recibe ya decidido para que esta funcion siga siendo pura.

    tolerancias_por_fecha permite que un dia rija una tolerancia distinta de
    la del resto del anio. Esta funcion no sabe POR QUE: recibe
    {fecha: Tolerancias} ya resuelto y aplica el que corresponda. Quien decide
    que dia lleva cual -y con que margen estricto- es asistencia_recalc. Sin
    diccionario, o con uno vacio, el calculo es identico al de siempre.
    """
    por_fecha = tolerancias_por_fecha or {}
    consumido = 0.0
    resultados: list[ResultadoDia] = []
    for d in sorted(dias, key=lambda x: x.fecha):
        r = calcular_dia(d, por_fecha.get(d.fecha, tolerancias),
                         banco_anual - consumido)
        if r is None:
            continue
        consumido += r.permisoBanco
        resultados.append(r)
    return resultados
```

`Optional` ya está importado en ese archivo (`from typing import Optional`); si no, agregarlo.

- [ ] **Step 4: Correr los tests del motor**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_tolerancia_por_fecha.py -v
```

Esperado: PASS los 5.

- [ ] **Step 5: Escribir el test que falla, del cableado**

Agregar al final de `tests/test_tolerancia_por_fecha.py`:

```python
# -- El cableado, con FakeSession -----------------------------------------------

from app.services import asistencia_recalc as r
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def _db_recalc(fuera_del_anillo, extensiones):
    return FakeSession({
        "FROM Employee e": [{
            "id": 8, "biometricoId": "123",
            "horaInicio": 8.0, "horaFin": 16.0, "horasTrabajo": 8.0,
            "fechaIngreso": date(2020, 1, 1),
            "horasPermisoAnual": 12.0,
            "fueraAnilloCircunvalacion": fuera_del_anillo,
        }],
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "FROM EmployeeBaja": [],
        "SUM(horasConsumidas)": [{"total": None}],
        "AS excedente": [{"excedente": 0.0}],
        "FROM ExtensionTolerancia": extensiones,
    })


def _overrides_usados(monkeypatch, db):
    """Corre recalcular_anio y devuelve el dict que recibio el motor."""
    capturado = {}

    def fake(dias, tolerancias, banco_anual, tolerancias_por_fecha=None):
        capturado["por_fecha"] = tolerancias_por_fecha
        return []

    monkeypatch.setattr(r, "calcular_anio", fake)
    r.recalcular_anio(db, 8, 2026, hoy=HOY)
    return capturado["por_fecha"]


def test_un_empleado_sin_el_flag_no_recibe_ningun_override(monkeypatch):
    """Con extensiones cargadas en la base, al no marcado no le aplican."""
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=False, extensiones=extensiones)
    assert _overrides_usados(monkeypatch, db) == {}


def test_un_empleado_con_el_flag_recibe_el_override_del_dia(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    overrides = _overrides_usados(monkeypatch, db)
    tol = overrides[date(2026, 7, 1)]
    assert tol.entradaMin == 30
    # El margen estricto igualado al otorgado: asi no marca abuso.
    assert tol.estrictaEntradaMin == 30


def test_la_salida_sin_cargar_queda_en_los_15_de_config(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": None}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    tol = _overrides_usados(monkeypatch, db)[date(2026, 7, 1)]
    assert tol.salidaMin == 15
    # Y su margen estricto sigue siendo el de siempre: la salida no se
    # extendio, asi que ahi el abuso tiene que poder marcarse igual.
    assert tol.estrictaSalidaMin == 5


def test_la_salida_cargada_tambien_iguala_su_margen_estricto(monkeypatch):
    extensiones = [{"fecha": date(2026, 7, 1), "toleranciaEntradaMin": 30,
                    "toleranciaSalidaMin": 20}]
    db = _db_recalc(fuera_del_anillo=True, extensiones=extensiones)
    tol = _overrides_usados(monkeypatch, db)[date(2026, 7, 1)]
    assert tol.salidaMin == 20
    assert tol.estrictaSalidaMin == 20
```

- [ ] **Step 6: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_tolerancia_por_fecha.py -v -k "flag or salida"
```

Esperado: FALLAN — `recalcular_anio` todavía no pasa el cuarto argumento, así que `capturado["por_fecha"]` es `None`.

- [ ] **Step 7: Cablear el orquestador**

En `app/services/asistencia_recalc.py`, agregar el import junto a los demás de `app.database`:

```python
from app.database.extension_tolerancia import extensiones_por_fecha
```

En `_datos_empleado`, agregar la columna al `SELECT` (después de `e.biometricoId`):

```sql
               e.fueraAnilloCircunvalacion,
```

Y reemplazar la llamada al motor (hoy las líneas 313-318) por:

```python
    tolerancias_base = Tolerancias(
        entradaMin=cfg["toleranciaEntradaMin"],
        salidaMin=cfg["toleranciaSalidaMin"],
        estrictaEntradaMin=cfg["toleranciaEstrictaEntradaMin"],
        estrictaSalidaMin=cfg["toleranciaEstrictaSalidaMin"],
    )
    # Las extensiones aplican SOLO a quien vive fuera del anillo. Al resto se
    # le pasa un diccionario vacio y su calculo queda identico al de siempre.
    #
    # El margen estricto se iguala al margen otorgado a proposito: la formula
    # del abuso es "uso la tolerancia Y el desvio supero el estricto", asi que
    # igualandolos el abuso no se dispara dentro de lo concedido. Sin esto, el
    # dia que RRHH otorga 30 minutos quedaria marcado como abuso todo el que
    # llego 8:08 -justo la gente que uso el permiso que le dieron.
    #
    # La salida que no se extendio conserva SU margen estricto: ahi no hubo
    # concesion, asi que el abuso tiene que poder marcarse como siempre.
    por_fecha = {}
    if emp.get("fueraAnilloCircunvalacion"):
        for fecha, ext in extensiones_por_fecha(db, desde, hasta).items():
            salida = ext["toleranciaSalidaMin"]
            por_fecha[fecha] = Tolerancias(
                entradaMin=ext["toleranciaEntradaMin"],
                salidaMin=salida if salida is not None else cfg["toleranciaSalidaMin"],
                estrictaEntradaMin=ext["toleranciaEntradaMin"],
                estrictaSalidaMin=(salida if salida is not None
                                   else cfg["toleranciaEstrictaSalidaMin"]),
            )

    resultados = calcular_anio(entradas, tolerancias_base, banco_anual, por_fecha)
```

- [ ] **Step 8: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde. Si algún test de asistencia falla con `KeyError: 'fueraAnilloCircunvalacion'`, es un fixture de `FakeSession` al que le falta la clave en la fila de `Employee`: agregársela con `False`.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/services/asistencia_calc.py app/services/asistencia_recalc.py tests/test_tolerancia_por_fecha.py
git commit -m "$(cat <<'EOF'
feat(asistencia): la tolerancia puede variar por dia sin que el motor lo sepa

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Los endpoints y el recálculo masivo

**Repo:** Backend (`C:\Users\Emiliano\Documents\Backend_RRHH`)

**Files:**
- Create: `app/routes/extension_tolerancia.py`
- Modify: `app/services/asistencia_recalc.py` (agregar `recalcular_marcados_fuera_del_anillo` después de `recalcular_jornada`)
- Modify: `app/main.py:19` (el import) y la lista de `include_router`
- Test: `tests/test_extension_tolerancia_endpoints.py` (nuevo)

**Interfaces:**
- Consumes: `listar`, `extensiones_por_fecha`, `existe_para_fecha`, `agregar`, `borrar`, `ensure_table` de la Task 2; `get_config` de `app/database/asistencia.py`.
- Produces, y lo consume la Task 6:
  - `GET /asistencia/extensiones-tolerancia` → `{ extensiones: [{ id, fecha: "YYYY-MM-DD", toleranciaEntradaMin, toleranciaSalidaMin: int | null, cargadoPor: int | null, cargadoEn: str | null }] }`
  - `POST /asistencia/extensiones-tolerancia` → body `{ fecha: "YYYY-MM-DD", toleranciaEntradaMin: number, toleranciaSalidaMin?: number | null }`, responde `{ ok: true, fecha }`
  - `DELETE /asistencia/extensiones-tolerancia/{extension_id}` → `{ ok: true, fecha }`, o 404

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_extension_tolerancia_endpoints.py`:

```python
"""
Los tres endpoints de extension de tolerancia.

Se invocan las funciones directo con un FakeSession, que es el patron de la
suite: no hay TestClient porque las dependencias de FastAPI (auth y sesion) se
resuelven por inyeccion y aca se pasan a mano.
"""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.routes import extension_tolerancia as m
from tests.fakes import FakeSession

HOY = date.today()
MANIANA = HOY + timedelta(days=1)
AYER = HOY - timedelta(days=1)


def _db(existe=False, borrado=None, extensiones=None):
    return FakeSession({
        "FROM AsistenciaConfig": [{
            "toleranciaEntradaMin": 15, "toleranciaSalidaMin": 15,
            "fechaInicioModulo": date(2026, 1, 1),
            "toleranciaEstrictaEntradaMin": 7, "toleranciaEstrictaSalidaMin": 5,
            "diasRachaAlerta": 3,
        }],
        "SELECT id FROM ExtensionTolerancia": [{"id": 1}] if existe else [],
        "DELETE FROM ExtensionTolerancia": (
            [{"fecha": borrado}] if borrado is not None else []
        ),
        "ORDER BY fecha DESC": extensiones if extensiones is not None else [],
    })


# -- Validacion ----------------------------------------------------------------

def test_rechaza_una_fecha_pasada():
    """
    Validado en el servidor y no solo con el min del input: el min se saltea
    desde DevTools, y una extension retroactiva reescribiria asistencia ya
    liquidada.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_fecha(AYER.isoformat())
    assert e.value.status_code == 400


def test_acepta_hoy_y_el_futuro():
    assert m._validar_fecha(HOY.isoformat()) == HOY
    assert m._validar_fecha(MANIANA.isoformat()) == MANIANA


def test_rechaza_un_valor_que_no_supera_la_tolerancia_vigente():
    """
    Cargar 5 minutos RECORTARIA el margen de los que viven lejos, al reves
    de lo que el boton promete.
    """
    with pytest.raises(HTTPException) as e:
        m._validar_minutos(5, base=15, extremo="entrada")
    assert e.value.status_code == 400


def test_rechaza_un_valor_igual_a_la_tolerancia_vigente():
    """Igual no es extender: no cambia nada y confunde."""
    with pytest.raises(HTTPException):
        m._validar_minutos(15, base=15, extremo="entrada")


def test_rechaza_el_error_de_tipeo():
    """8 horas ya es una jornada entera y vacia el concepto de tolerancia."""
    with pytest.raises(HTTPException) as e:
        m._validar_minutos(481, base=15, extremo="entrada")
    assert e.value.status_code == 400


def test_acepta_un_valor_razonable():
    assert m._validar_minutos(30, base=15, extremo="entrada") == 30


# -- POST ----------------------------------------------------------------------

def test_el_post_da_de_alta_la_extension(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    db = _db()
    r = m.post_extension(
        {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30},
        user={"employeeId": 3}, db=db,
    )
    assert r["ok"] is True
    assert "INSERT INTO ExtensionTolerancia" in db.sql_ejecutado()


def test_el_post_valida_la_salida_contra_su_propia_base(monkeypatch):
    """
    Que el campo sea opcional no lo exime: una salida de 10 minutos
    recortaria el margen igual que una entrada de 5.
    """
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    with pytest.raises(HTTPException):
        m.post_extension(
            {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30,
             "toleranciaSalidaMin": 10},
            user={"employeeId": 3}, db=_db(),
        )


def test_el_post_rechaza_una_fecha_que_ya_tiene_extension(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    with pytest.raises(HTTPException) as e:
        m.post_extension(
            {"fecha": MANIANA.isoformat(), "toleranciaEntradaMin": 30},
            user={"employeeId": 3}, db=_db(existe=True),
        )
    assert e.value.status_code == 409


def test_el_post_no_escribe_si_la_validacion_falla(monkeypatch):
    monkeypatch.setattr(m, "_recalcular_si_hace_falta", lambda db, fecha: None)
    db = _db()
    with pytest.raises(HTTPException):
        m.post_extension(
            {"fecha": AYER.isoformat(), "toleranciaEntradaMin": 30},
            user={"employeeId": 3}, db=db,
        )
    assert "INSERT" not in db.sql_ejecutado()


# -- Recalculo -----------------------------------------------------------------

def test_una_extension_futura_no_recalcula(monkeypatch):
    """
    El motor solo computa hasta hoy: el dia de maniana todavia no existe en
    JornadaDiaria, asi que no hay nada que rehacer.
    """
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    m._recalcular_si_hace_falta(_db(), MANIANA)
    assert llamados == []


def test_una_extension_de_hoy_si_recalcula(monkeypatch):
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    m._recalcular_si_hace_falta(_db(), HOY)
    assert llamados == [HOY.year]


# -- DELETE --------------------------------------------------------------------

def test_el_delete_borra_y_recalcula_el_anio_de_esa_fecha(monkeypatch):
    """
    Una extension de un anio anterior borrada ahora tiene que recalcular SU
    anio, no el actual.
    """
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    db = _db(borrado=date(2024, 5, 2))
    r = m.delete_extension(1, _user={}, db=db)
    assert r["ok"] is True
    assert llamados == [2024]


def test_el_delete_de_lo_que_no_existe_responde_404(monkeypatch):
    llamados = []
    monkeypatch.setattr(m, "recalcular_marcados_fuera_del_anillo",
                        lambda db, anio: llamados.append(anio))
    with pytest.raises(HTTPException) as e:
        m.delete_extension(999, _user={}, db=_db(borrado=None))
    assert e.value.status_code == 404
    assert llamados == []
```

- [ ] **Step 2: Correr para verificar que fallan**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_extension_tolerancia_endpoints.py -v
```

Esperado: FALLA en el import con `ModuleNotFoundError: No module named 'app.routes.extension_tolerancia'`.

- [ ] **Step 3: Escribir el recálculo masivo**

En `app/services/asistencia_recalc.py`, agregar después de `recalcular_jornada`:

```python
def recalcular_marcados_fuera_del_anillo(db: Session, anio: int) -> dict:
    """
    Recalcula el anio de los empleados que viven fuera del anillo. Es lo que
    se dispara al dar de alta o de baja una extension de tolerancia: cambia
    que tolerancia rigio ese dia, y con ella el saldo.

    Solo los marcados: al resto la extension no le aplica por definicion, asi
    que barrer la nomina entera seria trabajo puro al vacio.

    Hermana de recalcular_todos y recalcular_jornada: misma auditoria y misma
    garantia de que un empleado que falla se registra y no aborta el resto.
    """
    log_id = abrir_recalculo(db, "extension_tolerancia", None, None,
                             date(anio, 1, 1), date(anio, 12, 31))
    ids = [r["id"] for r in db.execute(text("""
        SELECT id FROM Employee
        WHERE fueraAnilloCircunvalacion = 1 AND biometricoId IS NOT NULL
        ORDER BY id
    """)).mappings().all()]

    filas = 0
    ok = 0
    errores = []
    for eid in ids:
        try:
            filas += recalcular_anio(db, eid, anio)
            ok += 1
        except Exception as e:
            db.rollback()
            log.warning("Recalculo por extension fallido para empleado %s: %s",
                        eid, e)
            errores.append({"employeeId": eid, "error": str(e)})

    cerrar_recalculo(db, log_id, ok, filas, errores)
    return {"procesados": ok, "filas": filas, "errores": errores}
```

- [ ] **Step 4: Crear el router**

Crear `app/routes/extension_tolerancia.py`:

```python
"""
Extensiones de tolerancia por dia.

RRHH otorga, para una fecha puntual, una tolerancia distinta de los 15
minutos de siempre. Aplica solo a quien tiene Employee.fueraAnilloCircunvalacion:
el resto mantiene los 15 haya o no extension cargada.
"""

import logging
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_middleware import require_permission
from app.database.asistencia import get_config
from app.database.database import SessionLocal
from app.database.extension_tolerancia import (
    agregar, borrar, ensure_table, existe_para_fecha, listar,
)
from app.services.asistencia_recalc import recalcular_marcados_fuera_del_anillo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/asistencia/extensiones-tolerancia",
                   tags=["Extension de tolerancia"])

# 8 horas ya es una jornada entera y vacia el concepto de tolerancia: mas que
# eso solo puede ser un dedazo.
MINUTOS_MAX = 480

PERMISO = Depends(require_permission("asistencia.gestionar"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validar_fecha(valor) -> date:
    """
    Normaliza la fecha y exige que sea de hoy en adelante.

    Se valida en el servidor y no solo con el min del input: el min se saltea
    desde DevTools, y una extension retroactiva reescribiria asistencia que ya
    se liquido.
    """
    try:
        fecha = date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="fecha debe venir como YYYY-MM-DD")
    if fecha < date.today():
        raise HTTPException(
            status_code=400,
            detail="No se puede extender la tolerancia de un dia que ya paso")
    return fecha


def _validar_minutos(valor, base: int, extremo: str) -> int:
    """
    Normaliza los minutos y exige que superen la tolerancia vigente.

    Un valor menor RECORTARIA el margen de los que viven lejos, exactamente
    al reves de lo que el boton promete. Vale igual para la salida: que el
    campo sea opcional no lo exime.
    """
    try:
        minutos = int(valor)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"La tolerancia de {extremo} debe ser un numero de minutos")
    if minutos <= base:
        raise HTTPException(
            status_code=400,
            detail=(f"La tolerancia de {extremo} tiene que superar los {base} "
                    f"minutos vigentes: {minutos} no es una extension"))
    if minutos > MINUTOS_MAX:
        raise HTTPException(
            status_code=400,
            detail=(f"La tolerancia de {extremo} no puede superar "
                    f"{MINUTOS_MAX} minutos"))
    return minutos


def _recalcular_si_hace_falta(db: Session, fecha: date) -> None:
    """
    Recalcula solo si el dia ya esta calculado.

    El motor computa hasta hoy nada mas, asi que un dia futuro todavia no
    existe en JornadaDiaria: va a nacer con la extension puesta cuando llegue,
    sin que nadie tenga que rehacer nada.

    Si el recalculo falla, la extension ya quedo escrita: se registra y el job
    nocturno la aplica. Un 500 aca haria creer que no se guardo cuando si se
    guardo.
    """
    if fecha > date.today():
        return
    try:
        recalcular_marcados_fuera_del_anillo(db, fecha.year)
    except Exception as e:
        log.warning("Recalculo por extension de tolerancia del %s fallido: %s",
                    fecha, e)


@router.get("")
def get_extensiones(_user: dict = PERMISO, db: Session = Depends(get_db)):
    """Todas las extensiones cargadas, la mas nueva primero."""
    ensure_table(db)
    return {
        "extensiones": [{
            "id": int(e["id"]),
            "fecha": (e["fecha"] if isinstance(e["fecha"], date)
                      else e["fecha"].date()).isoformat(),
            "toleranciaEntradaMin": int(e["toleranciaEntradaMin"]),
            "toleranciaSalidaMin": (None if e["toleranciaSalidaMin"] is None
                                    else int(e["toleranciaSalidaMin"])),
            "cargadoPor": e["cargadoPor"],
            "cargadoEn": e["cargadoEn"].isoformat() if e["cargadoEn"] else None,
        } for e in listar(db)],
    }


@router.post("")
def post_extension(data: dict = Body(...), user: dict = PERMISO,
                   db: Session = Depends(get_db)):
    """
    Da de alta la extension de un dia.

    Una por fecha: un segundo alta para el mismo dia responde 409 pidiendo
    borrar la que esta, en vez de pisar en silencio un valor que le perdona
    horas a toda la planta que vive lejos.
    """
    ensure_table(db)
    cfg = get_config(db)
    fecha = _validar_fecha(data.get("fecha"))
    entrada = _validar_minutos(data.get("toleranciaEntradaMin"),
                               base=cfg["toleranciaEntradaMin"],
                               extremo="entrada")
    salida_cruda = data.get("toleranciaSalidaMin")
    salida = (None if salida_cruda in (None, "")
              else _validar_minutos(salida_cruda,
                                    base=cfg["toleranciaSalidaMin"],
                                    extremo="salida"))

    if existe_para_fecha(db, fecha):
        raise HTTPException(
            status_code=409,
            detail=("Ya hay una extension cargada para esa fecha. "
                    "Borrala primero si queres cambiarla."))

    agregar(db, fecha, entrada, salida, user.get("employeeId"))
    _recalcular_si_hace_falta(db, fecha)
    return {"ok": True, "fecha": fecha.isoformat()}


@router.delete("/{extension_id}")
def delete_extension(extension_id: int, _user: dict = PERMISO,
                     db: Session = Depends(get_db)):
    """
    Borra una extension y recalcula el anio de SU fecha, no el actual: una
    extension de diciembre borrada ya entrado enero pertenece a diciembre.
    """
    ensure_table(db)
    fecha = borrar(db, extension_id)
    if fecha is None:
        raise HTTPException(status_code=404, detail="La extension no existe")
    _recalcular_si_hace_falta(db, fecha)
    return {"ok": True, "fecha": fecha.isoformat()}
```

- [ ] **Step 5: Registrar el router**

En `app/main.py`, agregar `extension_tolerancia` al final de la lista de imports de la línea 19, y la línea de registro junto a los demás `include_router`:

```python
app.include_router(extension_tolerancia.router)
```

- [ ] **Step 6: Correr los tests**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest tests/test_extension_tolerancia_endpoints.py -v
```

Esperado: PASS los 13.

- [ ] **Step 7: Verificar que la app levanta con las rutas nuevas**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -c "from app.main import app; print(sorted({(r.path, tuple(sorted(r.methods))) for r in app.routes if 'extensiones-tolerancia' in r.path}))"
```

Esperado: imprime `/asistencia/extensiones-tolerancia` con `GET` y con `POST`, y `/asistencia/extensiones-tolerancia/{extension_id}` con `DELETE`.

- [ ] **Step 8: Correr la suite completa**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH" && "./venv/Scripts/python.exe" -m pytest --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```

Esperado: todo en verde.

- [ ] **Step 9: Commit**

```bash
cd "C:/Users/Emiliano/Documents/Backend_RRHH"
git add app/routes/extension_tolerancia.py app/services/asistencia_recalc.py app/main.py tests/test_extension_tolerancia_endpoints.py
git commit -m "$(cat <<'EOF'
feat(asistencia): endpoints de extension de tolerancia y recalculo de marcados

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: El check en el legajo

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts:344` (la interfaz `Employee`)
- Modify: `src/app/Componentes/TablaOperador/DetailTables.tsx:261-263` (el `InfoCard` del Domicilio en `ProfileTab`)

**Interfaces:**
- Consumes: la clave `fueraAnilloCircunvalacion` (bool) de `GET /rrhh/employees`, y `PUT /employee/{id}` con `{ fueraAnilloCircunvalacion: boolean }`, de la Task 1.
- Produces: nada que consuman otras tareas.

- [ ] **Step 1: Sumar el campo a la interfaz**

En `src/app/Interfas/Interfaces.ts`, dentro de `export interface Employee`, agregar después de `address: string;`:

```ts
  /** Vive fuera del anillo de Circunvalación: recibe las extensiones de
   *  tolerancia que RRHH otorga para un día puntual. */
  fueraAnilloCircunvalacion: boolean;
```

- [ ] **Step 2: Agregar el check al lado del Domicilio**

En `src/app/Componentes/TablaOperador/DetailTables.tsx`, dentro de `ProfileTab`, reemplazar el `InfoCard` del Domicilio (líneas 261-263) por:

```tsx
              <InfoCard icon={Home} title="Domicilio">
                {employee.address}
                <label
                  className="mt-2 flex items-start gap-2 cursor-pointer"
                  title={
                    "Tildado: este agente vive fuera del anillo y recibe las " +
                    "extensiones de tolerancia que RRHH otorgue para un día " +
                    "puntual. Sin tildar: mantiene siempre los 15 minutos de " +
                    "tolerancia."
                  }
                >
                  <input
                    type="checkbox"
                    checked={fueraAnillo}
                    disabled={!puedeEditarAnillo || guardandoAnillo}
                    onChange={(e) => void guardarAnillo(e.target.checked)}
                    className="mt-0.5 w-4 h-4 accent-primary disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <span className="text-xs text-muted-foreground">
                    Fuera del anillo de Circunvalación
                    {guardandoAnillo && " · guardando…"}
                  </span>
                </label>
              </InfoCard>
```

- [ ] **Step 3: Agregar el estado y el guardado**

En el mismo archivo, dentro del componente `ProfileTab` (que arranca en la línea 72), junto a los demás `useState`, agregar:

```tsx
  // El check se guarda al tocarlo: la tarjeta "Datos Personales" es de solo
  // lectura y no vale la pena montarle un modo de edición entero por un
  // control. Se muestra deshabilitado -no oculto- para quien no es RRHH: que
  // el agente vea cómo está cargado su propio dato es parte de que la
  // decisión sea auditable.
  const [fueraAnillo, setFueraAnillo] = useState(
    employee.fueraAnilloCircunvalacion ?? false
  );
  const [guardandoAnillo, setGuardandoAnillo] = useState(false);
  const puedeEditarAnillo = tienePermiso(leerPermisos(), "rrhh.gestionar");

  const guardarAnillo = async (valor: boolean) => {
    // Optimista: el check responde al toque y vuelve atrás si el PUT falla.
    setFueraAnillo(valor);
    setGuardandoAnillo(true);
    try {
      await apiClient.put(`/employee/${employee.id}`, {
        fueraAnilloCircunvalacion: valor,
      });
      void onSave?.();
    } catch (error) {
      setFueraAnillo(!valor);
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: error instanceof Error
          ? error.message
          : "No se pudo guardar el domicilio fuera del anillo",
        life: 5000,
      });
    } finally {
      setGuardandoAnillo(false);
    }
  };
```

Si `leerPermisos` y `tienePermiso` no están importados en el archivo, agregarlos:

```tsx
import { leerPermisos, tienePermiso } from "@/app/util/permisos";
```

`apiClient`, `useState` y `toast` ya están en el archivo (`apiClient` en la línea 16, `useState` en la 5, y `ProfileTab` ya tiene su `Toast`).

- [ ] **Step 4: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "DetailTables|Interfaces"
```

Esperado: sin salida.

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`. **Contar así y no por líneas de salida**: tsc imprime contexto multilínea por error.

- [ ] **Step 5: Verificar en el navegador**

Con el backend corriendo y `npm run dev`, entrando con un usuario con `rrhh.gestionar`:

1. Legajo de un empleado → pestaña Perfil: debajo del Domicilio aparece el check, sin tildar.
2. Pasar el mouse por encima: el tooltip dice que el tildado recibe las extensiones y el no tildado mantiene los 15 minutos.
3. Tildarlo: muestra "guardando…" un instante. Recargar la página: sigue tildado.
4. Destildarlo y recargar: sigue destildado.
5. Con un usuario **sin** `rrhh.gestionar` mirando su propio legajo: el check se ve, refleja el valor real y está **deshabilitado**.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/DetailTables.tsx
git commit -m "$(cat <<'EOF'
feat(legajo): check de domicilio fuera del anillo de Circunvalacion

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: El botón y el modal en el tablero

**Repo:** Frontend (`C:\Users\Emiliano\Documents\RRHH`)

**Files:**
- Create: `src/app/Componentes/Asistencia/ExtensionToleranciaModal.tsx`
- Modify: `src/app/Componentes/Asistencia/AsistenciaTablero.tsx` (el encabezado de la línea 204 y el montaje del modal)

**Interfaces:**
- Consumes: los tres endpoints de la Task 4, con las formas exactas declaradas ahí.
- Produces: nada.

- [ ] **Step 1: Crear el modal**

Crear `src/app/Componentes/Asistencia/ExtensionToleranciaModal.tsx`:

```tsx
"use client";

// Extensión de tolerancia para un día puntual. Aplica solo a los agentes
// marcados como "fuera del anillo de Circunvalación"; el resto mantiene sus
// 15 minutos haya o no extensión cargada.
//
// El valor reemplaza los 15 minutos, no se suma: lo que se carga acá es el
// número final que va a regir ese día.

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";

interface Extension {
  id: number;
  fecha: string;
  toleranciaEntradaMin: number;
  toleranciaSalidaMin: number | null;
  cargadoPor: number | null;
  cargadoEn: string | null;
}

interface Props {
  onCerrar: () => void;
}

/** "HH:MM" -> minutos. El input de tipo time solo entrega eso o vacío. */
const aMinutos = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

const fmtMinutos = (min: number) => {
  const h = Math.floor(min / 60);
  return h > 0 ? `${h}h ${String(min % 60).padStart(2, "0")}m` : `${min}m`;
};

/** Hoy en local, para el min del calendario. toISOString() daría UTC y en
 *  Argentina adelantaría un día después de las 21:00. */
const hoyLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export default function ExtensionToleranciaModal({ onCerrar }: Props) {
  const [extensiones, setExtensiones] = useState<Extension[]>([]);
  const [fecha, setFecha] = useState("");
  const [entrada, setEntrada] = useState("");
  const [salida, setSalida] = useState("");
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recargar = useCallback(async () => {
    const r = await apiClient.get<{ extensiones: Extension[] }>(
      "/asistencia/extensiones-tolerancia"
    );
    setExtensiones(r.extensiones);
  }, []);

  useEffect(() => {
    recargar()
      .catch((e) =>
        setError(e instanceof Error ? e.message : "No se pudieron cargar")
      )
      .finally(() => setCargando(false));
  }, [recargar]);

  const agregar = async () => {
    setGuardando(true);
    setError(null);
    try {
      await apiClient.post("/asistencia/extensiones-tolerancia", {
        fecha,
        toleranciaEntradaMin: aMinutos(entrada),
        toleranciaSalidaMin: salida === "" ? null : aMinutos(salida),
      });
      // No se cierra: RRHH puede cargar varias y ver la lista actualizarse.
      setFecha("");
      setEntrada("");
      setSalida("");
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la extensión");
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (id: number) => {
    setGuardando(true);
    setError(null);
    try {
      await apiClient.delete(`/asistencia/extensiones-tolerancia/${id}`);
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo borrar la extensión");
    } finally {
      setGuardando(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4"
      onClick={onCerrar}
      role="dialog"
      aria-modal="true"
      aria-labelledby="extension-tolerancia-titulo"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="extension-tolerancia-titulo"
          className="font-heading text-lg font-bold text-foreground mb-1"
        >
          Extender tolerancia
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          Para un día puntual, reemplaza los 15 minutos de tolerancia. Aplica
          solo a los agentes marcados como &quot;fuera del anillo de
          Circunvalación&quot;; el resto mantiene sus 15 minutos.
        </p>

        <div className="grid grid-cols-3 gap-2 mb-1">
          <div>
            <label htmlFor="ext-fecha" className="block text-xs font-medium text-foreground mb-1">
              Fecha
            </label>
            <input
              id="ext-fecha"
              type="date"
              min={hoyLocal()}
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
              className="w-full px-2 py-2 rounded-md border border-border bg-background text-foreground text-sm"
            />
          </div>
          <div>
            <label htmlFor="ext-entrada" className="block text-xs font-medium text-foreground mb-1">
              Entrada
            </label>
            <input
              id="ext-entrada"
              type="time"
              value={entrada}
              onChange={(e) => setEntrada(e.target.value)}
              className="w-full px-2 py-2 rounded-md border border-border bg-background text-foreground text-sm"
            />
          </div>
          <div>
            <label htmlFor="ext-salida" className="block text-xs font-medium text-foreground mb-1">
              Salida (opcional)
            </label>
            <input
              id="ext-salida"
              type="time"
              value={salida}
              onChange={(e) => setSalida(e.target.value)}
              className="w-full px-2 py-2 rounded-md border border-border bg-background text-foreground text-sm"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          La salida vacía deja ese extremo en los 15 minutos de siempre.
        </p>
        <button
          type="button"
          onClick={agregar}
          disabled={guardando || fecha === "" || entrada === ""}
          className="w-full py-2 bg-primary hover:opacity-90 text-primary-foreground rounded-md text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed mb-5"
        >
          {guardando ? "Guardando…" : "Agregar extensión"}
        </button>

        <h3 className="text-sm font-bold text-foreground mb-2">
          Extensiones cargadas
        </h3>
        {cargando ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : extensiones.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Todavía no se cargó ninguna.
          </p>
        ) : (
          <ul className="divide-y divide-border border-y border-border max-h-56 overflow-y-auto">
            {extensiones.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between gap-3 py-2 text-sm"
              >
                <span className="text-foreground font-medium">{e.fecha}</span>
                <span className="text-xs text-muted-foreground flex-1">
                  Entrada {fmtMinutos(e.toleranciaEntradaMin)}
                  {e.toleranciaSalidaMin !== null &&
                    ` · Salida ${fmtMinutos(e.toleranciaSalidaMin)}`}
                </span>
                <button
                  type="button"
                  onClick={() => borrar(e.id)}
                  disabled={guardando}
                  aria-label={`Borrar la extensión del ${e.fecha}`}
                  className="text-error hover:opacity-80 text-xs font-bold disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Borrar
                </button>
              </li>
            ))}
          </ul>
        )}

        {error && <p className="text-sm text-error mt-3">{error}</p>}

        <button
          type="button"
          onClick={onCerrar}
          className="w-full mt-5 py-2 bg-muted hover:bg-border rounded-xl text-sm font-bold"
        >
          Cerrar
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Montar el botón en el tablero**

En `src/app/Componentes/Asistencia/AsistenciaTablero.tsx`, agregar el import junto a los demás del encabezado:

```tsx
import ExtensionToleranciaModal from "./ExtensionToleranciaModal";
```

Agregar el estado junto a los otros `useState` del componente:

```tsx
  const [extensionAbierta, setExtensionAbierta] = useState(false);
```

En el encabezado, dentro del `<div className="flex items-center gap-2">` que ya contiene los dos botones (arranca en la línea 204), agregar como **primer** botón del grupo:

```tsx
          <button
            onClick={() => setExtensionAbierta(true)}
            className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm font-medium hover:opacity-90 transition-opacity flex items-center gap-2"
          >
            <i className="pi pi-clock text-sm" />
            Extender tolerancia
          </button>
```

Y al final del JSX del componente, antes del cierre del `<div>` raíz, montar el modal:

```tsx
      {extensionAbierta && (
        <ExtensionToleranciaModal onCerrar={() => setExtensionAbierta(false)} />
      )}
```

- [ ] **Step 3: Verificar los tipos**

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "AsistenciaTablero|ExtensionTolerancia"
```

Esperado: sin salida.

```bash
cd "C:/Users/Emiliano/Documents/RRHH" && npx tsc --noEmit -p tsconfig.json 2>&1 | grep -c "error TS"
```

Esperado: `27`.

- [ ] **Step 4: Verificar en el navegador**

Con el backend corriendo y `npm run dev`, con un usuario con `asistencia.gestionar`:

1. Asistencia → el botón "Extender tolerancia" aparece junto a "Empezar desde hoy" y "Recalcular todo".
2. El modal abre y dice "Todavía no se cargó ninguna".
3. El calendario **no deja elegir ayer** (el `min` está en hoy).
4. Cargar mañana con entrada `00:30` y salida vacía: aparece en la lista como "Entrada 30m", sin salida. **El modal no se cierra.**
5. Cargar otra fecha con entrada `00:30` y salida `00:20`: la línea muestra los dos valores.
6. Intentar cargar una fecha que ya tiene extensión: muestra el mensaje del 409 pidiendo borrar la que está.
7. Intentar cargar entrada `00:10`: muestra el error de que tiene que superar los 15 minutos vigentes.
8. Borrar una: desaparece de la lista.

- [ ] **Step 5: Prueba de punta a punta**

1. Tildar el check "fuera del anillo" a un agente que tenga marcaciones de hoy con entrada tarde (entre 16 y 30 minutos).
2. Cargar una extensión para **hoy** con entrada `00:30`.
3. Esperar unos segundos (el recálculo corre al guardar) y mirar el saldo de ese agente en el tablero: el descuento de ese día tiene que haber desaparecido.
4. En Mi Asistencia de ese agente, ese día **no** debe figurar la marca de "margen".
5. Un agente **sin** el check, con el mismo atraso el mismo día, tiene que conservar su descuento.
6. Borrar la extensión y confirmar que el descuento del primero vuelve.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Emiliano/Documents/RRHH"
git add src/app/Componentes/Asistencia/ExtensionToleranciaModal.tsx src/app/Componentes/Asistencia/AsistenciaTablero.tsx
git commit -m "$(cat <<'EOF'
feat(asistencia): boton y modal para extender la tolerancia de un dia

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Autorrevisión del plan

**Cobertura del spec.** Cada unidad tiene tarea: la columna `fueraAnilloCircunvalacion` con el patrón `IF COL_LENGTH` y el guard de `rrhh.gestionar` con 403 explícito (T1); el recálculo al tildar o destildar (T1); la tabla `ExtensionTolerancia` con clave única por fecha y el `borrar` que devuelve la fecha (T2); `tolerancias_por_fecha` en `calcular_anio` sin que el motor sepa qué es una extensión (T3); el margen estricto igualado al otorgado para que no marque abuso, y la salida no extendida conservando el suyo (T3); los tres endpoints bajo `asistencia.gestionar`, las tres validaciones y el 409 por fecha duplicada (T4); el recálculo solo cuando el día ya está calculado, y `recalcular_marcados_fuera_del_anillo` filtrando por el flag (T4); el check al lado del Domicilio con el tooltip corregido y deshabilitado para quien no es RRHH (T5); el botón, el calendario desde hoy, los dos selectores y la lista con borrado (T6).

**El tooltip del spec, no el del pedido original.** La T5 lleva textual la redacción que acordamos —tildado recibe las extensiones, sin tildar mantiene los 15—, no la frase original que decía lo contrario. Si alguien la "corrige" de vuelta a la original, invierte el significado de toda la feature.

**Tres cosas que el spec no decía y el plan decide.** Primero, el check se guarda **optimista**: el toque se refleja al instante y revierte si el `PUT` falla; un checkbox que no responde hasta que vuelve el servidor se siente roto. Segundo, el modal **no se cierra** al cargar una extensión, igual que el panel de carga inicial de permisos: el flujo real es cargar y ver la lista. Tercero, el `min` del calendario se calcula con la fecha **local** y no con `toISOString()`, que en Argentina devuelve el día siguiente después de las 21:00 — el mismo error que ya se corrigió una vez en el modal de bajas.

**Un riesgo de fixtures que el plan anticipa.** `_datos_empleado` suma una columna y `ensure_tables` una tabla, así que los `FakeSession` de los tests de asistencia que mapean `"FROM Employee e"` van a devolver filas sin `fueraAnilloCircunvalacion`. El Step 8 de la T1 y el Step 8 de la T3 lo dicen explícitamente y nombran el arreglo. Lo mismo con el fragmento `"FROM ExtensionTolerancia"`, que `extensiones_por_fecha` y `existe_para_fecha` comparten: los tests de endpoints usan `"SELECT id FROM ExtensionTolerancia"` y `"ORDER BY fecha DESC"` para no colisionar.

**Consistencia de nombres.** `fueraAnilloCircunvalacion` es el mismo literal en la columna, en la lista blanca del `PUT`, en el guard, en el `SELECT` de `rrhh.py`, en el JSON, en la interfaz `Employee` de TypeScript y en el `WHERE` de `recalcular_marcados_fuera_del_anillo`. `extensiones_por_fecha`, `existe_para_fecha`, `agregar` y `borrar` se declaran en T2 y se consumen con esos nombres en T3 y T4. `tolerancias_por_fecha` es el nombre del parámetro en T3 y el del argumento que el test captura. Las claves de la respuesta del `GET` (`id`, `fecha`, `toleranciaEntradaMin`, `toleranciaSalidaMin`, `cargadoPor`, `cargadoEn`) se declaran en T4 y la interfaz `Extension` de T6 las repite una a una.
