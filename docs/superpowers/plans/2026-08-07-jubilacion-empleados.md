# Jubilación de empleados — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RRHH carga una fecha de jubilación y el empleado queda sin acceso al sistema, con el cómputo de asistencia y vacaciones congelado, en un tablero aparte.

**Architecture:** La fecha de jubilación es la fuente de verdad; `Employee.status` y `User.activo` son cache derivado que una única función mantiene. Un job diario reconcilia las fechas futuras cuando llega su día. El congelamiento del cómputo no es un caso especial: la fecha entra como cota superior del rango de recálculo, simétrica a `fechaIngreso` que ya es la cota inferior.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server vía pyodbc, APScheduler, Next.js + TypeScript + PrimeReact en el frontend.

## Global Constraints

- **NO levantar servidor.** Nunca correr `uvicorn` ni ningún dev server en ningún paso.
- Credenciales de los relojes solo en `.env` (`RELOJ_USER`, `RELOJ_PASS`, `RELOJ_IPS`), jamás en código ni en documentos versionados.
- `.env` no se commitea.
- Los relojes son de solo lectura: la allowlist de `app/services/isapi_client.py` no se modifica.
- Backend en `C:\Users\Emiliano\Documents\Backend_RRHH`, frontend en `C:\Users\Emiliano\Documents\RRHH`. Son dos repos git distintos, cada uno con sus propios commits.
- SQL Server: los `ALTER`/`CREATE` son idempotentes (`IF COL_LENGTH(...) IS NULL` / `IF NOT EXISTS`).
- El valor exacto del estado nuevo es la cadena `"Jubilado"`.
- `datetime` hereda de `date`: para normalizar un valor de pyodbc hay que chequear `isinstance(x, datetime)` **primero** y recién después devolver el `date`. El guard invertido ya causó un bug en este repo (commit `5f97f85`).
- El jubilado conserva su `biometricoId`. No se desvincula nada del reloj.
- Las licencias ya aprobadas no se cancelan ni se modifican.
- Los tests del proyecto son de funciones puras, sin base ni `TestClient`. Las funciones con SQL se verifican con un import check y un script de verificación manual.

---

### Task 1: Módulo de jubilación — regla pura y persistencia

**Files:**
- Create: `app/services/jubilacion.py`
- Create: `app/database/jubilacion.py`
- Test: `tests/test_jubilacion.py`

**Interfaces:**
- Consumes: nada. Es la base del resto.
- Produces:
  - `jubilacion_cumplida(fecha: Optional[date], hoy: date) -> bool` en `app/services/jubilacion.py`
  - En `app/database/jubilacion.py`:
    - `ensure_columna_jubilacion(db: Session) -> None`
    - `aplicar_jubilacion(db: Session, employee_id: int, fecha: Optional[date], hoy: date) -> bool`
    - `fecha_jubilacion_de(db: Session, employee_id: int) -> Optional[date]`
    - `jubilados(db: Session) -> list[dict]`
    - `pendientes_de_jubilar(db: Session, hoy: date) -> list[int]`

**Contexto:** El proyecto separa la lógica pura (`app/services/`, testeable sin base) del SQL (`app/database/`). `asistencia_justificaciones.py` es el precedente exacto: la regla de la ventana vive en `services/` y el SQL en `database/`.

`aplicar_jubilacion` escribe las tres cosas —la fecha, `Employee.status` y `User.activo`— en una sola transacción. No hay empleado sin fila en `CondicionLaboral` garantizado, así que el UPDATE de la fecha usa el mismo patrón de "actualizar si existe, insertar si no" que ya usa `update_condicion_laboral` en `rrhh.py`.

No todo empleado tiene un `User`: el UPDATE sobre `[User]` afecta cero filas en ese caso y no es un error.

- [ ] **Step 1: Escribir los tests de la regla pura**

Crear `tests/test_jubilacion.py`:

```python
from datetime import date

from app.services.jubilacion import jubilacion_cumplida

HOY = date(2026, 8, 7)


def test_sin_fecha_no_esta_jubilado():
    assert jubilacion_cumplida(None, HOY) is False


def test_una_fecha_futura_todavia_no_jubila():
    # RRHH puede cargar la fecha con anticipacion: la persona sigue trabajando.
    assert jubilacion_cumplida(date(2026, 12, 1), HOY) is False


def test_manana_todavia_no_jubila():
    assert jubilacion_cumplida(date(2026, 8, 8), HOY) is False


def test_la_fecha_de_hoy_ya_jubila():
    assert jubilacion_cumplida(HOY, HOY) is True


def test_una_fecha_pasada_jubila():
    assert jubilacion_cumplida(date(2026, 1, 15), HOY) is True
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_jubilacion.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.jubilacion'`.

- [ ] **Step 3: Escribir el módulo puro**

Crear `app/services/jubilacion.py`:

```python
"""
Regla de la jubilacion que no toca la base.

Vive aparte del SQL para poder testear la condicion sin base ni TestClient,
igual que jubilacion_cumplida se usa tanto al guardar como en el job diario:
una sola definicion de "ya esta jubilado" para los dos caminos.
"""

from datetime import date
from typing import Optional


def jubilacion_cumplida(fecha: Optional[date], hoy: date) -> bool:
    """
    Si la fecha de jubilacion ya corresponde.

    None es "no jubilado". Una fecha futura tampoco jubila: RRHH carga la fecha
    cuando la sabe y la persona sigue trabajando hasta ese dia.
    """
    return fecha is not None and fecha <= hoy
```

- [ ] **Step 4: Correr los tests**

```bash
py -m pytest tests/test_jubilacion.py -v
```

Esperado: PASS en los 5.

- [ ] **Step 5: Escribir el módulo de persistencia**

Crear `app/database/jubilacion.py`:

```python
"""
Persistencia de la jubilacion.

La fecha en CondicionLaboral es la fuente de verdad. Employee.status y
User.activo son cache derivado: aplicar_jubilacion es el unico lugar que los
escribe, y lo hace siempre junto con la fecha y en la misma transaccion.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.jubilacion import jubilacion_cumplida

ESTADO_JUBILADO = "Jubilado"
ESTADO_ACTIVO = "Activo"

ALTER_FECHA_JUBILACION_SQL = """
IF COL_LENGTH('CondicionLaboral','fechaJubilacion') IS NULL
ALTER TABLE CondicionLaboral ADD fechaJubilacion DATE NULL;
"""


def ensure_columna_jubilacion(db: Session) -> None:
    """DDL idempotente de CondicionLaboral.fechaJubilacion."""
    db.execute(text(ALTER_FECHA_JUBILACION_SQL))
    db.commit()


def _a_date(valor) -> Optional[date]:
    """
    Normaliza lo que devuelve pyodbc a un date limpio.

    datetime hereda de date, asi que hay que chequear el tipo mas especifico
    primero: el guard invertido ya rompio una vez en este repo.
    """
    if valor is None:
        return None
    return valor.date() if isinstance(valor, datetime) else valor


def fecha_jubilacion_de(db: Session, employee_id: int) -> Optional[date]:
    """La fecha cargada, sin importar si ya se cumplio."""
    fila = db.execute(text("""
        SELECT MAX(fechaJubilacion) AS fecha
        FROM CondicionLaboral WHERE employeeId = :id
    """), {"id": employee_id}).mappings().first()
    return _a_date(fila["fecha"]) if fila else None


def aplicar_jubilacion(db: Session, employee_id: int, fecha: Optional[date],
                       hoy: date) -> bool:
    """
    Guarda la fecha y sincroniza el estado derivado. Devuelve True si el
    empleado quedo jubilado.

    fecha=None revierte: el empleado vuelve a Activo y recupera el acceso. Es
    el caso del error de carga, que es el mas comun.

    Una fecha futura se guarda pero no desactiva nada todavia; el job diario la
    aplica cuando llega el dia.

    Las tres escrituras van en una sola transaccion: si la fecha se guardara y
    el estado no, quedaria un jubilado con acceso al sistema.
    """
    existe = db.execute(text(
        "SELECT id FROM CondicionLaboral WHERE employeeId = :id"
    ), {"id": employee_id}).first()

    if existe:
        db.execute(text("""
            UPDATE CondicionLaboral SET fechaJubilacion = :fecha
            WHERE employeeId = :id
        """), {"fecha": fecha, "id": employee_id})
    else:
        db.execute(text("""
            INSERT INTO CondicionLaboral (employeeId, fechaJubilacion)
            VALUES (:id, :fecha)
        """), {"id": employee_id, "fecha": fecha})

    jubilado = jubilacion_cumplida(fecha, hoy)
    estado = ESTADO_JUBILADO if jubilado else ESTADO_ACTIVO
    activo = 0 if jubilado else 1

    db.execute(text("UPDATE Employee SET status = :e WHERE id = :id"),
               {"e": estado, "id": employee_id})
    # Un empleado puede no tener usuario: el UPDATE afecta cero filas y esta bien.
    db.execute(text("UPDATE [User] SET activo = :a WHERE employeeId = :id"),
               {"a": activo, "id": employee_id})

    db.commit()
    return jubilado


def pendientes_de_jubilar(db: Session, hoy: date) -> list[int]:
    """
    Empleados con fecha cumplida que todavia figuran activos.

    Es lo que consume el job diario. La consulta ya filtra por fecha para no
    traer el padron entero, pero la decision final la toma jubilacion_cumplida
    sobre cada fila: una sola definicion de "ya esta jubilado".
    """
    filas = db.execute(text("""
        SELECT e.id, c.fechaJubilacion
        FROM Employee e
        JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE c.fechaJubilacion IS NOT NULL
          AND c.fechaJubilacion <= :hoy
          AND e.status <> :jubilado
    """), {"hoy": hoy, "jubilado": ESTADO_JUBILADO}).mappings().all()
    return [int(f["id"]) for f in filas
            if jubilacion_cumplida(_a_date(f["fechaJubilacion"]), hoy)]


def jubilados(db: Session) -> list[dict]:
    """
    Los empleados con la jubilacion ya efectiva, para el tablero propio.

    Trae el saldo congelado: como el recalculo no genera dias posteriores a la
    fecha, la ultima jornada calculada es la del dia de la jubilacion.
    """
    filas = db.execute(text("""
        SELECT e.id, e.name, e.dni, e.email, e.photo, e.status,
               d.nombre AS departamento, o.nombre AS oficina,
               c.tipoContrato, c.fechaIngreso, c.fechaJubilacion,
               -- El saldo acumulado no es una columna: es la suma de los dias.
               -- Mismo calculo que saldo_acumulado() en app/database/asistencia.py.
               (SELECT COALESCE(SUM(j.saldoDia), 0) FROM JornadaDiaria j
                WHERE j.employeeId = e.id) AS saldoFinal
        FROM Employee e
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN CondicionLaboral c ON c.employeeId = e.id
        WHERE e.status = :jubilado
        ORDER BY c.fechaJubilacion DESC, e.name ASC
    """), {"jubilado": ESTADO_JUBILADO}).mappings().all()

    return [{
        "id": int(f["id"]),
        "name": f["name"],
        "dni": f["dni"],
        "email": f["email"],
        "photo": f["photo"],
        "status": f["status"],
        "departamento": f["departamento"],
        "oficina": f["oficina"],
        "tipoContrato": f["tipoContrato"],
        "fechaIngreso": _a_date(f["fechaIngreso"]).isoformat()
                        if f["fechaIngreso"] else None,
        "fechaJubilacion": _a_date(f["fechaJubilacion"]).isoformat()
                           if f["fechaJubilacion"] else None,
        "saldoFinal": float(f["saldoFinal"]) if f["saldoFinal"] is not None else 0.0,
    } for f in filas]
```

- [ ] **Step 6: Verificar que el módulo importa y crear la columna**

```bash
py -c "
from app.database.database import SessionLocal
from app.database.jubilacion import ensure_columna_jubilacion, jubilados, pendientes_de_jubilar
from datetime import date
db = SessionLocal()
ensure_columna_jubilacion(db)
print('Columna fechaJubilacion lista')
print('Jubilados hoy:', len(jubilados(db)))
print('Pendientes de jubilar:', pendientes_de_jubilar(db, date.today()))
db.close()
"
```

Esperado (precedido por los mensajes de conexión, que son normales):

```
Columna fechaJubilacion lista
Jubilados hoy: 0
Pendientes de jubilar: []
```

- [ ] **Step 7: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services/jubilacion.py app/database/jubilacion.py tests/test_jubilacion.py
git commit -m "feat: capa de jubilacion, regla pura y persistencia

La fecha en CondicionLaboral es la fuente de verdad; Employee.status y
User.activo son cache derivado. aplicar_jubilacion es el unico lugar que
los escribe y lo hace en una sola transaccion: si la fecha se guardara y
el estado no, quedaria un jubilado con acceso al sistema.

jubilacion_cumplida vive en services/ porque la usan los dos caminos, el
guardado manual y el job diario, y una sola definicion evita que se
separen.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Asistencia — la jubilación como cota superior

**Files:**
- Modify: `app/services/asistencia_recalc.py`

**Interfaces:**
- Consumes: la columna `CondicionLaboral.fechaJubilacion` de Task 1.
- Produces: `rango_de_calculo(anio: int, inicio_modulo: date, fecha_ingreso: Optional[date], fecha_jubilacion: Optional[date], hoy: date) -> Optional[tuple[date, date]]` en `app/services/asistencia_recalc.py`. Devuelve `None` cuando no hay ningún día que calcular.

**Contexto:** `recalcular_anio` ya calcula un rango `desde`/`hasta` donde `fechaIngreso` actúa como cota inferior por empleado. La jubilación es el espejo exacto: cota superior. No hay que excluir al jubilado de `recalcular_todos` ni escribir un caso especial — sigue procesándose y el saldo se congela como consecuencia del rango.

`_datos_empleado` ya joinea `CondicionLaboral` con un subquery agregado; solo hay que sumarle la columna.

**Por qué se extrae una función:** con la jubilación son cuatro fechas interactuando (inicio del módulo, ingreso, jubilación y hoy) y el resultado tiene que ser correcto en todas las combinaciones. Ese cálculo hoy está embebido en `recalcular_anio`, que toca la base y no se puede testear en este proyecto. Extraerlo lo vuelve testeable sin base, que es la única forma de cubrir los casos que pide el spec.

**Corrección adyacente deliberada:** la normalización de `inicio_modulo` que ya está en `recalcular_anio` usa el guard invertido:

```python
    if not isinstance(inicio_modulo, date):
        inicio_modulo = inicio_modulo.date()
```

Como `datetime` hereda de `date`, un `datetime` entra por `isinstance(..., date) == True` y nunca se normaliza. Hoy no rompe porque `get_config` devuelve un `date` real, pero es el mismo defecto que ya se arregló en el commit `5f97f85`. Se corrige acá porque son las líneas que esta task está reescribiendo, no como refactor suelto.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_jubilacion.py`, ampliar el encabezado del archivo para que quede:

```python
from datetime import date, datetime

from app.services.asistencia_recalc import rango_de_calculo
from app.services.jubilacion import jubilacion_cumplida

HOY = date(2026, 8, 7)
```

Y agregar al final del archivo:

```python
# -- Rango de calculo con la jubilacion como cota superior ---------------------

INICIO_MODULO = date(2026, 1, 1)


def test_sin_jubilacion_el_rango_llega_hasta_hoy():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1), None, HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_la_jubilacion_corta_el_rango():
    # Jubilado el 30/06: no se calculan dias posteriores.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 6, 30), HOY)
    assert r == (date(2026, 1, 1), date(2026, 6, 30))


def test_una_jubilacion_futura_no_recorta_nada():
    # La fecha esta cargada pero todavia no llego: se calcula hasta hoy igual.
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2026, 12, 1), HOY)
    assert r == (date(2026, 1, 1), HOY)


def test_una_jubilacion_anterior_al_inicio_del_modulo_no_da_rango():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2020, 3, 1),
                         date(2025, 5, 1), HOY)
    assert r is None


def test_el_ingreso_sigue_siendo_la_cota_inferior():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 4, 10), None, HOY)
    assert r == (date(2026, 4, 10), HOY)


def test_ingreso_y_jubilacion_en_el_mismo_anio():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 3, 1),
                         date(2026, 9, 15), HOY)
    assert r == (date(2026, 3, 1), date(2026, 9, 15))


def test_jubilarse_el_mismo_dia_del_ingreso_da_un_solo_dia():
    r = rango_de_calculo(2026, INICIO_MODULO, date(2026, 5, 20),
                         date(2026, 5, 20), HOY)
    assert r == (date(2026, 5, 20), date(2026, 5, 20))


def test_un_anio_pasado_se_calcula_entero_sin_recortar_por_hoy():
    r = rango_de_calculo(2026, date(2025, 1, 1), date(2020, 3, 1), None,
                         date(2027, 4, 1))
    assert r == (date(2026, 1, 1), date(2026, 12, 31))


def test_acepta_datetime_de_pyodbc_y_devuelve_date():
    # pyodbc puede devolver datetime en una columna DATE; datetime hereda de
    # date, asi que un guard mal escrito lo deja pasar sin normalizar.
    r = rango_de_calculo(2026, INICIO_MODULO, datetime(2020, 3, 1, 9, 30),
                         datetime(2026, 6, 30, 17, 0), HOY)
    assert r == (date(2026, 1, 1), date(2026, 6, 30))
    assert type(r[0]) is date and type(r[1]) is date
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_jubilacion.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'rango_de_calculo' from 'app.services.asistencia_recalc'`.

- [ ] **Step 3: Agregar `fechaJubilacion` a `_datos_empleado`**

En `app/services/asistencia_recalc.py`, la función `_datos_empleado` queda:

```python
def _datos_empleado(db: Session, employee_id: int) -> Optional[dict]:
    fila = db.execute(text("""
        SELECT e.id, e.biometricoId,
               h.horaInicio, h.horaFin, h.horasTrabajo,
               c.fechaIngreso, c.fechaJubilacion
        FROM Employee e
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN (
            SELECT employeeId,
                   MIN(fechaIngreso)    AS fechaIngreso,
                   MAX(fechaJubilacion) AS fechaJubilacion
            FROM CondicionLaboral
            GROUP BY employeeId
        ) c ON c.employeeId = e.id
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()
    return dict(fila) if fila else None
```

`MIN` para el ingreso y `MAX` para la jubilación: el rango más ancho, que es la elección conservadora si alguna vez hay más de una fila por empleado.

- [ ] **Step 4: Extraer la función pura**

En `app/services/asistencia_recalc.py`, agregar antes de `recalcular_anio`:

```python
def _a_date(valor) -> Optional[date]:
    """
    Normaliza a date lo que pyodbc puede devolver como datetime.

    datetime hereda de date, asi que el chequeo va sobre el tipo mas
    especifico primero. El guard invertido ya rompio una vez en este repo.
    """
    if valor is None:
        return None
    return valor.date() if isinstance(valor, datetime) else valor


def rango_de_calculo(anio: int, inicio_modulo: date,
                     fecha_ingreso: Optional[date],
                     fecha_jubilacion: Optional[date],
                     hoy: date) -> Optional[tuple[date, date]]:
    """
    Los dias a calcular para un empleado en un anio, o None si no hay ninguno.

    Cuatro fechas lo acotan. Por abajo, el inicio del modulo y el ingreso del
    empleado. Por arriba, el fin del anio, hoy y la jubilacion.

    La jubilacion es el espejo exacto del ingreso: por eso el saldo de un
    jubilado se congela sin ningun caso especial, simplemente deja de haber
    dias que calcular despues de su fecha.
    """
    desde = max(date(anio, 1, 1), inicio_modulo)
    ingreso = _a_date(fecha_ingreso)
    if ingreso is not None:
        desde = max(desde, ingreso)

    hasta = min(date(anio, 12, 31), hoy)
    jubilacion = _a_date(fecha_jubilacion)
    if jubilacion is not None:
        hasta = min(hasta, jubilacion)

    if desde > hasta:
        return None
    return desde, hasta
```

Verificar que `Optional` esté importado desde `typing` y `datetime` desde `datetime`. Los dos ya se usan en el archivo.

- [ ] **Step 5: Usar la función en `recalcular_anio`**

En `recalcular_anio`, reemplazar todo este bloque:

```python
    cfg = get_config(db)
    inicio_modulo = cfg["fechaInicioModulo"]
    if not isinstance(inicio_modulo, date):
        inicio_modulo = inicio_modulo.date()

    desde = max(date(anio, 1, 1), inicio_modulo)
    ingreso = emp.get("fechaIngreso")
    if ingreso is not None:
        # isinstance(datetime_obj, date) es True porque datetime hereda de date;
        # hay que verificar el tipo mas especifico primero.
        ingreso = ingreso.date() if isinstance(ingreso, datetime) else ingreso
        desde = max(desde, ingreso)
    hasta = min(date(anio, 12, 31), date.today())
    if desde > hasta:
        return 0
```

por:

```python
    cfg = get_config(db)
    rango = rango_de_calculo(
        anio, _a_date(cfg["fechaInicioModulo"]),
        emp.get("fechaIngreso"), emp.get("fechaJubilacion"), date.today(),
    )
    if rango is None:
        return 0
    desde, hasta = rango
```

La normalización de `inicio_modulo` pasa por `_a_date`, que corrige el guard invertido descrito en el contexto de esta task.

- [ ] **Step 6: Correr los tests**

```bash
py -m pytest tests/test_jubilacion.py -v
```

Esperado: PASS en los 14 (los 5 de la regla pura más los 9 del rango).

- [ ] **Step 7: Verificar que el módulo compila**

```bash
py -c "from app.services.asistencia_recalc import recalcular_anio; print('OK')"
```

Esperado: imprime `OK`.

- [ ] **Step 8: Verificar que un empleado sin jubilación no cambia**

```bash
py -c "
from dotenv import load_dotenv; load_dotenv()
from app.database.database import SessionLocal
from sqlalchemy import text
from app.services.asistencia_recalc import recalcular_anio
db = SessionLocal()
antes = db.execute(text('SELECT COUNT(*) FROM JornadaDiaria WHERE employeeId = 8')).scalar()
recalcular_anio(db, 8, 2026)
despues = db.execute(text('SELECT COUNT(*) FROM JornadaDiaria WHERE employeeId = 8')).scalar()
print(f'Jornadas antes={antes} despues={despues} (deben coincidir)')
db.close()
"
```

Esperado: los dos números coinciden. El empleado 8 no tiene fecha de jubilación, así que el rango no cambió.

- [ ] **Step 9: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 10: Commit**

```bash
git add app/services/asistencia_recalc.py tests/test_jubilacion.py
git commit -m "feat: la jubilacion es la cota superior del rango de recalculo

Espejo exacto de fechaIngreso, que ya es la cota inferior por empleado.
El saldo se congela como consecuencia del rango y no como caso especial:
el jubilado se sigue procesando, simplemente no genera dias posteriores a
su fecha. Un recalculo posterior da el mismo resultado, que es la
propiedad que el modulo ya tenia.

El calculo del rango sale a una funcion pura: con la jubilacion son
cuatro fechas interactuando y embebido en recalcular_anio no habia forma
de testearlo sin base.

De paso se corrige el guard invertido de inicio_modulo, que chequeaba
'not isinstance(x, date)' y por lo tanto nunca normalizaba un datetime.
Son las mismas lineas que esta task reescribe.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Vacaciones — cortar la antigüedad en la jubilación

**Files:**
- Modify: `app/routes/licenses.py`
- Test: `tests/test_vacaciones_corte.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `calcular_dias_vacaciones(tipo_contrato: str, fecha_ingreso, fecha_corte: Optional[date] = None) -> int` — tercer parámetro nuevo, opcional, con default `None`.

**Contexto:** `calcular_dias_vacaciones` está en `app/routes/licenses.py:231`. Es casi pura: lo único que la ata al reloj es el `date.today()` de adentro. Agregarle una fecha de corte opcional la vuelve determinista y testeable sin congelar el reloj, además de resolver el requisito.

Se queda donde está. Moverla a `services/` sería un refactor que no sirve a este objetivo y tocaría llamadores que no tienen nada que ver con la jubilación.

Los dos llamadores están en `licenses.py:163` y `licenses.py:660`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_vacaciones_corte.py`:

```python
from datetime import date

from app.routes.licenses import calcular_dias_vacaciones

INGRESO = date(2010, 1, 1)


def test_sin_fecha_de_corte_usa_hoy():
    # Se compara contra hoy explicito en vez de contra un numero fijo: la
    # antiguedad crece con el calendario y un valor hardcodeado haria que el
    # test empezara a fallar solo, sin que nadie toque el codigo.
    assert (calcular_dias_vacaciones("permanente", INGRESO)
            == calcular_dias_vacaciones("permanente", INGRESO, date.today()))


def test_la_fecha_de_corte_congela_la_antiguedad():
    # Jubilado en 2018: 8 anios de antiguedad, no los que corresponderian hoy.
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2018, 1, 1)) == 15


def test_la_antiguedad_no_sigue_creciendo_despues_del_corte():
    # El mismo corte da el mismo resultado sin importar cuando se pregunte.
    primero = calcular_dias_vacaciones("permanente", INGRESO, date(2018, 1, 1))
    segundo = calcular_dias_vacaciones("permanente", INGRESO, date(2018, 1, 1))
    assert primero == segundo == 15


def test_un_corte_en_el_primer_anio_da_proporcional():
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2010, 10, 1)) == 7


def test_un_corte_antes_de_los_seis_meses_no_da_derecho():
    assert calcular_dias_vacaciones(
        "permanente", INGRESO, date(2010, 4, 1)) == 0


def test_contratado_con_corte_sigue_topeado_en_diez():
    assert calcular_dias_vacaciones(
        "contratado", INGRESO, date(2018, 1, 1)) == 10
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_vacaciones_corte.py -v
```

Esperado: FAIL con `TypeError: calcular_dias_vacaciones() takes 2 positional arguments but 3 were given` en los tests que pasan la fecha de corte.

- [ ] **Step 3: Agregar el parámetro**

En `app/routes/licenses.py`, la firma y las dos primeras líneas del cuerpo de `calcular_dias_vacaciones` quedan:

```python
def calcular_dias_vacaciones(tipo_contrato: str, fecha_ingreso,
                             fecha_corte: Optional[date] = None) -> int:
    """
    Dias de vacaciones por antiguedad y tipo de contrato.

    fecha_corte congela la antiguedad en un dia concreto: es la fecha de
    jubilacion, para que a alguien que ya se jubilo no le siga creciendo el
    derecho con el paso del tiempo. En None cuenta hasta hoy.
    """
    if not fecha_ingreso:
        return 0
```

Y reemplazar la línea que fija `today`:

```python
    today  = date.today()
```

por:

```python
    today  = fecha_corte or date.today()
```

El resto de la función no cambia.

Verificar que `Optional` esté importado en el archivo. Si no lo está, agregarlo al import de `typing` que ya exista, o sumar `from typing import Optional`.

- [ ] **Step 4: Correr los tests**

```bash
py -m pytest tests/test_vacaciones_corte.py -v
```

Esperado: PASS en los 6.

- [ ] **Step 5: Pasar la fecha de jubilación en los dos llamadores**

**Primer llamador.** La consulta que lo alimenta está en `licenses.py:80` y empieza así:

```python
        SELECT cl.tipoContrato, cl.fechaIngreso, e.gender,
```

pasa a:

```python
        SELECT cl.tipoContrato, cl.fechaIngreso, cl.fechaJubilacion, e.gender,
```

Y el llamador de `licenses.py:163`:

```python
                dias_vac = calcular_dias_vacaciones(tipo_contrato, fecha_ingreso)
```

pasa a:

```python
                dias_vac = calcular_dias_vacaciones(
                    tipo_contrato, fecha_ingreso,
                    emp_data.get("fechaJubilacion"),
                )
```

**Segundo llamador.** La consulta de `licenses.py:524`:

```python
            SELECT tipoContrato, fechaIngreso
```

pasa a:

```python
            SELECT tipoContrato, fechaIngreso, fechaJubilacion
```

Y el llamador de `licenses.py:660`:

```python
    dias_vac = calcular_dias_vacaciones(tipo_contrato, fecha_ingreso)
```

pasa a:

```python
    dias_vac = calcular_dias_vacaciones(
        tipo_contrato, fecha_ingreso, cl.get("fechaJubilacion"),
    )
```

Los números de línea se corren a medida que se edita: ubicar cada bloque por su contenido, no por la línea.

- [ ] **Step 6: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/licenses.py tests/test_vacaciones_corte.py
git commit -m "feat: la antiguedad para vacaciones se corta en la jubilacion

calcular_dias_vacaciones gana una fecha de corte opcional. Ademas de
resolver el requisito, vuelve determinista una funcion que dependia de
date.today() por dentro y no se podia testear sin congelar el reloj.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: API — endpoints de jubilación y filtro del listado

**Files:**
- Modify: `app/routes/rrhh.py`

**Interfaces:**
- Consumes: `aplicar_jubilacion`, `fecha_jubilacion_de`, `jubilados`, `ensure_columna_jubilacion` de Task 1.
- Produces:
  - `PUT /rrhh/employee/{employee_id}/jubilacion` — body `{"fechaJubilacion": "YYYY-MM-DD"}` o `{"fechaJubilacion": null}`
  - `GET /rrhh/jubilados`

**Contexto:** Va como endpoint propio y no como un campo más de `PUT /rrhh/employee/{id}/condicion-laboral`. Aquel hace un UPDATE plano de datos descriptivos; este corta el acceso de una persona al sistema. Compartirlos haría que un guardado de rutina pudiera dejar a alguien afuera sin que se vea en el código del llamador.

`rrhh.py` ya tiene `get_db`, `require_roles`, `ROLE_ADMIN` y `ROLE_RRHH` importados y en uso. El listado de empleados (`GET /rrhh/employees`) hoy no tiene `WHERE`: la consulta termina en `LEFT JOIN SatisfaccionMetrica sm ON e.id = sm.employeeId` y sigue `ORDER BY e.name ASC`.

- [ ] **Step 1: Agregar los imports**

En `app/routes/rrhh.py`, junto a los imports existentes de `app.database`:

```python
from app.database.jubilacion import (
    ESTADO_JUBILADO, aplicar_jubilacion, ensure_columna_jubilacion, jubilados,
)
```

Verificar que `date` esté importado desde `datetime`. Si no, agregarlo.

- [ ] **Step 2: Excluir a los jubilados del listado de RRHH**

En la consulta de `GET /rrhh/employees`, agregar el `WHERE` entre el último `LEFT JOIN` y el `ORDER BY`:

```sql
        LEFT JOIN SatisfaccionMetrica sm ON e.id = sm.employeeId
        WHERE e.status <> 'Jubilado'
        ORDER BY e.name ASC
```

- [ ] **Step 3: Escribir los dos endpoints**

Agregar al final de `app/routes/rrhh.py`:

```python
# ---------------------------------------------------------------------------
# PUT /rrhh/employee/{id}/jubilacion
# ---------------------------------------------------------------------------
@router.put("/employee/{employee_id}/jubilacion",
            dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def put_jubilacion(employee_id: int, data: dict = Body(...),
                   db: Session = Depends(get_db)):
    """
    Carga o borra la fecha de jubilacion.

    Endpoint propio y no un campo mas de condicion-laboral: aquel actualiza
    datos descriptivos, este le corta el acceso al sistema a una persona.

    Enviar fechaJubilacion en null revierte: el empleado vuelve a Activo y
    recupera el acceso. Es el caso del error de carga.
    """
    ensure_columna_jubilacion(db)

    if db.execute(text("SELECT id FROM Employee WHERE id = :id"),
                  {"id": employee_id}).first() is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    crudo = data.get("fechaJubilacion")
    fecha = None
    if crudo:
        try:
            fecha = date.fromisoformat(str(crudo).split("T")[0])
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="La fecha de jubilacion debe ser YYYY-MM-DD")

    jubilado = aplicar_jubilacion(db, employee_id, fecha, date.today())
    return {
        "employeeId": employee_id,
        "fechaJubilacion": fecha.isoformat() if fecha else None,
        "jubilado": jubilado,
        "status": ESTADO_JUBILADO if jubilado else "Activo",
    }


# ---------------------------------------------------------------------------
# GET /rrhh/jubilados
# ---------------------------------------------------------------------------
@router.get("/jubilados",
            dependencies=[Depends(require_roles(ROLE_ADMIN, ROLE_RRHH))])
def get_jubilados(db: Session = Depends(get_db)):
    """
    El tablero de jubilados: los que ya tienen la jubilacion efectiva.

    Los que tienen fecha futura cargada no aparecen aca todavia, siguen en el
    tablero normal porque siguen trabajando.
    """
    ensure_columna_jubilacion(db)
    return {"jubilados": jubilados(db)}
```

- [ ] **Step 4: Exponer la fecha en el detalle del empleado**

En la consulta de `GET /rrhh/employees`, el `SELECT` ya trae columnas de `CondicionLaboral` con alias `condicion_*`. Sumar la fecha con el mismo patrón:

```sql
            c.fechaJubilacion AS condicion_fechaJubilacion,
```

Y en el diccionario `condicionLaboral` que arma la respuesta, agregar la clave:

```python
            "condicionLaboral": {
                "tipoContrato":    emp["condicion_tipoContrato"],
                "fechaIngreso":    emp["condicion_fechaIngreso"],
                "fechaPlanta":     emp["condicion_fechaPlanta"],
                "categoria":       emp["condicion_categoria"],
                "position":        emp["condicion_position"],
                "fechaCategoria":  emp["condicion_fechaCategoria"],
                "fechaJubilacion": emp["condicion_fechaJubilacion"],
            },
```

Leer la consulta completa antes de editar para ubicar el alias en el lugar correcto del `SELECT`.

- [ ] **Step 5: Verificar que la app carga y las rutas existen**

```bash
py -c "from app.main import app; rutas = sorted({r.path for r in app.routes if 'jubila' in r.path.lower()}); print('\n'.join(rutas))"
```

Esperado:

```
/rrhh/employee/{employee_id}/jubilacion
/rrhh/jubilados
```

- [ ] **Step 6: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/rrhh.py
git commit -m "feat: endpoints de jubilacion y filtro del listado de RRHH

La jubilacion va en endpoint propio y no como campo de condicion-laboral:
aquel actualiza datos descriptivos, este corta el acceso al sistema. Si
compartieran endpoint, un guardado de rutina podria dejar a alguien
afuera sin que se vea en el codigo del llamador.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Reconciliador diario

**Files:**
- Modify: `app/scheduler.py`

**Interfaces:**
- Consumes: `pendientes_de_jubilar`, `aplicar_jubilacion`, `fecha_jubilacion_de`, `ensure_columna_jubilacion` de Task 1.
- Produces: nada que consuman otros tasks.

**Contexto:** El scheduler ya tiene tres jobs con el mismo molde: una función `_tick_*` que abre sesión, trabaja, nunca propaga excepción y cierra en `finally`. El nuevo sigue ese molde.

Corre a las 2 AM, una hora antes del recálculo de asistencia de las 3 AM, para que cuando el recálculo corra las jubilaciones del día ya estén aplicadas y el rango se corte donde corresponde.

**Solo avanza.** El reconciliador nunca reactiva a nadie: `pendientes_de_jubilar` solo devuelve gente con fecha cumplida que figura activa. Revertir es siempre un acto explícito de RRHH.

- [ ] **Step 1: Agregar el import y la constante de hora**

En `app/scheduler.py`, junto a los imports de `app.database`:

```python
from app.database.jubilacion import (
    aplicar_jubilacion, ensure_columna_jubilacion, fecha_jubilacion_de,
    pendientes_de_jubilar,
)
```

Y junto a las constantes de arriba del archivo:

```python
HORA_JUBILACIONES = 2  # 2 AM, antes del recalculo de asistencia de las 3
```

- [ ] **Step 2: Escribir el tick**

Agregar después de `_tick_autoreparacion`:

```python
def _tick_jubilaciones():
    """
    Aplica las jubilaciones cuya fecha ya llego.

    Es la pieza que hace util cargar una fecha futura: RRHH la carga cuando la
    sabe y la persona sigue trabajando hasta ese dia.

    Solo avanza. Nunca reactiva a nadie, ni siquiera si alguien edito la fecha
    hacia adelante: volver a activar es siempre un acto explicito de RRHH desde
    la interfaz.

    Corre antes del recalculo de asistencia para que el rango del dia ya tenga
    la cota superior puesta cuando aquel arranque.
    """
    db = SessionLocal()
    try:
        ensure_columna_jubilacion(db)
        hoy = date.today()
        ids = pendientes_de_jubilar(db, hoy)
        if not ids:
            log.info("Jubilaciones: no hay ninguna para aplicar hoy")
            return
        for eid in ids:
            fecha = fecha_jubilacion_de(db, eid)
            aplicar_jubilacion(db, eid, fecha, hoy)
            log.info("Jubilacion aplicada: empleado %s, fecha %s", eid, fecha)
        log.info("Jubilaciones: %s empleados pasaron a Jubilado", len(ids))
    except Exception as e:
        log.exception("Fallo inesperado en el tick de jubilaciones: %s", e)
    finally:
        db.close()
```

- [ ] **Step 3: Registrar el job**

En `iniciar_scheduler`, después del bloque que agrega `recalculo_asistencia`:

```python
    _scheduler.add_job(
        _tick_jubilaciones,
        "cron",
        hour=HORA_JUBILACIONES,
        minute=0,
        id="jubilaciones",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
```

Y sumar la hora al log final del arranque:

```python
    _scheduler.start()
    log.info("Scheduler iniciado: sync cada %s min, jubilaciones a las %s:00, "
             "recalculo a las %s:00, autoreparacion en %s s",
             INTERVALO_MINUTOS, HORA_JUBILACIONES,
             HORA_RECALCULO_ASISTENCIA, SEGUNDOS_AUTOREPARACION)
```

- [ ] **Step 4: Verificar que el módulo compila**

```bash
py -c "from app.scheduler import _tick_jubilaciones, iniciar_scheduler; print('OK')"
```

Esperado: imprime `OK`.

- [ ] **Step 5: Correr el tick a mano, sin levantar servidor**

```bash
py -c "
from dotenv import load_dotenv; load_dotenv()
from app.scheduler import _tick_jubilaciones
_tick_jubilaciones()
print('Tick ejecutado sin excepciones')
"
```

Esperado: termina sin excepción. Con la base actual no hay nadie con fecha cargada, así que loguea que no hay ninguna para aplicar.

- [ ] **Step 6: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add app/scheduler.py
git commit -m "feat: job diario que aplica las jubilaciones cumplidas

Es lo que hace util cargar una fecha futura. Corre a las 2 AM, antes del
recalculo de asistencia, para que el rango ya tenga la cota superior
puesta cuando aquel arranque.

Solo avanza: nunca reactiva a nadie. Volver a activar es siempre un acto
explicito de RRHH.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — fecha de jubilación en el legajo

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Interfas\Interfaces.ts`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\DetailTables.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\util\UiRRHH.tsx`

**Interfaces:**
- Consumes: `PUT /rrhh/employee/{id}/jubilacion` de Task 4, y la clave `fechaJubilacion` dentro de `condicionLaboral`.
- Produces: nada que consuman otros tasks del backend.

**Contexto:** Este es el repo del frontend, con sus propios commits. La tarjeta de Condición Laboral en `DetailTables.tsx` ya tiene campos de fecha con `Calendar` de PrimeReact; el nuevo sigue ese molde. `buildFormData` arma el estado inicial y `handleSave` manda los datos.

`handleSave` ya hace varias llamadas: primero `biometricoId` y después el resto en paralelo. La jubilación va como llamada propia, coherente con que el endpoint es propio.

`StatusBadge` en `UiRRHH.tsx:830` tiene un map de estados con fallback gris. Sin una entrada para `'Jubilado'` el badge igual funciona, pero sale gris como si fuera un estado desconocido.

- [ ] **Step 1: Agregar el campo al tipo**

En `src/app/Interfas/Interfaces.ts`, la interfaz `CondicionLaboral` queda:

```typescript
export interface CondicionLaboral {
  tipoContrato: EmploymentStatus;
  fechaIngreso: Date | null;
  fechaPlanta: Date | null;
  categoria: string;
  fechaCategoria: Date | null;
  position: string;
  /** Fecha de jubilación. Con fecha cumplida el empleado queda desactivado. */
  fechaJubilacion: Date | null;
}
```

Y agregar al final del archivo el tipo del tablero de jubilados:

```typescript
/** Fila del tablero de jubilados. */
export interface EmpleadoJubilado {
  id: number;
  name: string;
  dni: string | null;
  email: string | null;
  photo: string | null;
  status: string;
  departamento: string | null;
  oficina: string | null;
  tipoContrato: string | null;
  fechaIngreso: string | null;
  fechaJubilacion: string | null;
  saldoFinal: number;
}
```

- [ ] **Step 2: Agregar el color del badge**

En `src/app/util/UiRRHH.tsx`, el map de `StatusBadge` queda:

```tsx
export const StatusBadge = ({ status }: { status: string }) => {
  const map: Record<string, string> = {
    'Activo': 'bg-success-soft text-success-soft-foreground',
    'De licencia': 'bg-warning-soft text-warning-soft-foreground',
    'Parte médico': 'bg-error-soft text-error-soft-foreground',
    'Jubilado': 'bg-muted text-muted-foreground',
  };
```

El resto de la función no cambia. El gris es deliberado: un jubilado no es un estado de alerta ni de actividad, es alguien que ya no está operativo.

- [ ] **Step 3: Sumar la fecha al form**

En `src/app/Componentes/TablaOperador/DetailTables.tsx`, `buildFormData` gana el campo al final:

```typescript
  lastCategoryUpdate: employee.condicionLaboral.fechaCategoria
    ? new Date(employee.condicionLaboral.fechaCategoria)
    : null,
  retirementDate: employee.condicionLaboral.fechaJubilacion
    ? new Date(employee.condicionLaboral.fechaJubilacion)
    : null,
  biometricoId: employee.biometricoId ?? ''
});
```

- [ ] **Step 4: Agregar el campo a la tarjeta**

En la tarjeta de Condición Laboral, después del `InfoCard` de "Ultima Recategorización", agregar:

```tsx
              <InfoCard icon={CalendarIcon} title="Fecha de Jubilación">
                {editingSection === 'condicionLaboral' ? (
                  <>
                    <Calendar
                      value={formData.retirementDate}
                      onChange={(e) => setFormData({ ...formData, retirementDate: e.value as Date })}
                      dateFormat="yy-mm-dd"
                      showButtonBar
                      className="w-full"
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      Con la fecha cumplida el empleado queda desactivado: pierde el
                      acceso al sistema y deja de sumar horas y vacaciones. Vaciar el
                      campo lo reactiva.
                    </p>
                  </>
                ) : (
                  formData.retirementDate ? formatDate(formData.retirementDate) : '—'
                )}
              </InfoCard>
```

`showButtonBar` agrega el botón "Limpiar" del `Calendar`, que es como RRHH revierte una jubilación cargada por error.

- [ ] **Step 5: Guardar la fecha**

En `handleSave`, después de la llamada que guarda `biometricoId` y antes del `Promise.all` que guarda condición laboral y horario, agregar:

```typescript
      await apiClient.put(`/rrhh/employee/${employee.id}/jubilacion`, {
        fechaJubilacion: formData.retirementDate
          ? formData.retirementDate.toISOString().split('T')[0]
          : null,
      });
```

Se manda solo la parte de fecha (`YYYY-MM-DD`) y no el ISO completo: el backend guarda un `DATE` y la hora no aporta nada. Va antes del `Promise.all` por la misma razón que `biometricoId`: si falla, no queda un guardado a medias.

- [ ] **Step 6: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "DetailTables\.tsx|UiRRHH\.tsx|Interfas/Interfaces\.ts"
```

Esperado: sin salida. El proyecto tiene errores de tipos previos en otros archivos que no son parte de este trabajo; el filtro aísla los tres que sí lo son.

- [ ] **Step 7: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/DetailTables.tsx src/app/util/UiRRHH.tsx
git commit -m "feat: fecha de jubilacion en la condicion laboral del legajo

La fecha se guarda con su propia llamada, coherente con que el endpoint
es propio: no es un dato descriptivo mas, corta el acceso al sistema.

El boton de limpiar del Calendar es como RRHH revierte una jubilacion
cargada por error.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Frontend — tablero de jubilados

**Files:**
- Create: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\JubiladosTable.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\screens\RRHH\Screen.tsx`

**Interfaces:**
- Consumes: `GET /rrhh/jubilados` de Task 4, y el tipo `EmpleadoJubilado` de Task 6.
- Produces: nada. Es la última pieza de la feature.

**Contexto:** `Screen.tsx` maneja la vista con un estado `currentView` de tipo `ViewState` (`{ name: 'table' | 'detail' | 'messages'; id?: number }`) y renderiza `EmployeeTableView` cuando está en `table`.

El tablero de jubilados es una tabla propia y no un modo de `EmployeeTableView`: aquella recibe `Employee[]` completos con subordinados, licencias y permisos, mientras que el endpoint de jubilados devuelve un resumen plano. Forzar el mismo componente obligaría a inventar campos vacíos.

- [ ] **Step 1: Escribir la tabla**

Crear `src/app/Componentes/TablaOperador/JubiladosTable.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/app/util/apiClient";
import { EmpleadoJubilado } from "@/app/Interfas/Interfaces";

interface Props {
  onVolver: () => void;
}

export default function JubiladosTable({ onVolver }: Props) {
  const [jubilados, setJubilados] = useState<EmpleadoJubilado[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");

  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const r = await apiClient.get<{ jubilados: EmpleadoJubilado[] }>(
          "/rrhh/jubilados",
        );
        if (!cancelado) {
          setJubilados(r.jubilados);
          setError(null);
        }
      } catch (e) {
        if (!cancelado) {
          setError(e instanceof Error ? e.message : "No se pudieron cargar los jubilados");
        }
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, []);

  const filtrados = jubilados.filter((j) =>
    j.name.toLowerCase().includes(busqueda.toLowerCase()) ||
    (j.dni ?? "").includes(busqueda),
  );

  if (cargando) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-2xl mb-2" />
        <p>Cargando jubilados…</p>
      </div>
    );
  }

  if (error) {
    return <div className="p-6 text-center text-error">{error}</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="font-heading text-xl text-foreground">Jubilados</h2>
          <p className="text-sm text-muted-foreground">
            {jubilados.length} persona{jubilados.length === 1 ? "" : "s"} con la
            jubilación efectiva. El saldo quedó congelado en su último día.
          </p>
        </div>
        <button
          onClick={onVolver}
          className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm hover:opacity-90"
        >
          Volver al tablero
        </button>
      </div>

      <input
        type="text"
        value={busqueda}
        onChange={(e) => setBusqueda(e.target.value)}
        placeholder="Buscar por nombre o DNI…"
        className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm w-full max-w-sm"
      />

      <div className="bg-card rounded-lg border border-border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th className="py-3 px-4">Nombre</th>
              <th className="py-3 px-4">DNI</th>
              <th className="py-3 px-4">Departamento</th>
              <th className="py-3 px-4">Ingreso</th>
              <th className="py-3 px-4">Jubilación</th>
              <th className="py-3 px-4 text-right">Saldo final</th>
            </tr>
          </thead>
          <tbody>
            {filtrados.map((j) => (
              <tr key={j.id} className="border-b border-border last:border-0">
                <td className="py-3 px-4 text-foreground">{j.name}</td>
                <td className="py-3 px-4 text-muted-foreground">{j.dni ?? "—"}</td>
                <td className="py-3 px-4 text-muted-foreground">
                  {j.departamento ?? "—"}
                </td>
                <td className="py-3 px-4 text-muted-foreground">
                  {j.fechaIngreso ?? "—"}
                </td>
                <td className="py-3 px-4 text-foreground">
                  {j.fechaJubilacion ?? "—"}
                </td>
                <td
                  className={`py-3 px-4 text-right font-semibold ${
                    j.saldoFinal < 0 ? "text-error" : "text-foreground"
                  }`}
                >
                  {j.saldoFinal.toFixed(2)} hs
                </td>
              </tr>
            ))}
            {filtrados.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-muted-foreground">
                  {jubilados.length === 0
                    ? "No hay jubilados registrados."
                    : "Ningún jubilado coincide con la búsqueda."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Sumar la vista a la pantalla de RRHH**

En `src/app/screens/RRHH/Screen.tsx`, agregar el import:

```tsx
import JubiladosTable from "@/app/Componentes/TablaOperador/JubiladosTable";
```

Leer el archivo completo para ubicar la definición de `ViewState` que usa (viene importada de `Table.tsx`) y el bloque que renderiza `EmployeeTableView`.

En `Table.tsx`, ampliar el tipo para admitir la vista nueva:

```tsx
export interface ViewState {
  name: 'table' | 'detail' | 'messages' | 'jubilados';
  id?: number;
}
```

En `Screen.tsx`, junto al render de `EmployeeTableView`, agregar el render de la vista nueva:

```tsx
        {currentView.name === "jubilados" && (
          <JubiladosTable onVolver={() => setCurrentView({ name: "table" })} />
        )}
```

- [ ] **Step 3: Agregar el acceso al tablero**

En `Screen.tsx`, sobre el bloque que renderiza `EmployeeTableView`, agregar el botón que lleva al tablero nuevo:

```tsx
        {currentView.name === "table" && (
          <div className="flex justify-end mb-4">
            <button
              onClick={() => setCurrentView({ name: "jubilados" })}
              className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm hover:opacity-90"
            >
              Ver jubilados
            </button>
          </div>
        )}
```

Ubicarlo dentro del mismo contenedor donde ya vive `EmployeeTableView`, para que herede el ancho del layout.

- [ ] **Step 4: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "JubiladosTable\.tsx|RRHH/Screen\.tsx|TablaOperador/Table\.tsx"
```

Esperado: sin salida.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/TablaOperador/JubiladosTable.tsx src/app/Componentes/TablaOperador/Table.tsx src/app/screens/RRHH/Screen.tsx
git commit -m "feat: tablero de jubilados

Tabla propia y no un modo de EmployeeTableView: aquella recibe Employee
completos con subordinados, licencias y permisos, mientras que el
endpoint de jubilados devuelve un resumen plano. Forzar el mismo
componente obligaria a inventar campos vacios.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Fix del desborde de las pestañas del legajo

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\Perfildetail.tsx`

**Interfaces:**
- Consumes: nada.
- Produces: nada.

**Contexto:** Bug independiente de la jubilación. `Perfildetail.tsx` tiene ocho pestañas (Perfil, Licencias, Permisos, Documentos, Feedback 360, Asistencia, Alertas de tolerancia, Ausencias) en un `nav` con `flex space-x-8` y sin manejo de desborde, así que en pantallas angostas se salen del layout.

Va como task propia y no dentro de la feature: es un fix que se verifica mirando la pantalla, no con los tests de jubilación, y un reviewer puede aprobarlo o rechazarlo por separado.

- [ ] **Step 1: Aplicar el fix**

En `src/app/Componentes/TablaOperador/Perfildetail.tsx`, la línea del contenedor y la del `nav`:

```tsx
      <div className="border-b border-border no-print">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
```

pasan a:

```tsx
      <div className="border-b border-border no-print overflow-x-auto">
        <nav className="-mb-px flex space-x-6 min-w-max" aria-label="Tabs">
```

Tres cambios y cada uno hace falta: `overflow-x-auto` deja que el exceso scrollee dentro del contenedor en vez de desbordar la página, `min-w-max` impide que flex comprima los botones para hacerlos entrar (que es lo que rompe el `whitespace-nowrap` de cada botón), y `space-x-6` recupera algo de ancho para que en pantallas medianas no haga falta scrollear.

- [ ] **Step 2: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep "Perfildetail\.tsx"
```

Esperado: sin salida.

- [ ] **Step 3: Verificar en el navegador**

Abrir el legajo de un empleado y comprobar, achicando la ventana:

- Las ocho pestañas quedan dentro del ancho de la tarjeta, sin pisar el borde.
- En pantalla angosta aparece scroll horizontal **dentro** de la barra de pestañas, y el resto de la página no scrollea de lado.
- Ninguna pestaña queda con el texto cortado o en dos líneas.

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "fix: las pestanas del legajo se salian del layout

Ocho pestanas en un flex sin manejo de desborde. min-w-max evita que
flex las comprima, que es lo que peleaba contra el whitespace-nowrap de
cada boton, y overflow-x-auto deja el scroll dentro de la barra en vez de
empujar la pagina entera.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verificación final

Con todas las tareas completas:

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -m pytest tests/ -v
```

Esperado: PASS en toda la suite.

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "Jubilados|Perfildetail|DetailTables|UiRRHH|Interfas/Interfaces"
```

Esperado: sin salida.

Prueba del ciclo completo contra la base, sin levantar servidor. Usa el empleado 8 y **lo deja como estaba** al terminar:

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -c "
from dotenv import load_dotenv; load_dotenv()
from datetime import date, timedelta
from sqlalchemy import text
from app.database.database import SessionLocal
from app.database.jubilacion import (
    aplicar_jubilacion, ensure_columna_jubilacion, jubilados,
    pendientes_de_jubilar,
)

db = SessionLocal()
ensure_columna_jubilacion(db)
hoy = date.today()
EMP = 8

def estado():
    e = db.execute(text('SELECT status FROM Employee WHERE id=:i'), {'i': EMP}).scalar()
    u = db.execute(text('SELECT activo FROM [User] WHERE employeeId=:i'), {'i': EMP}).scalar()
    return f'status={e} userActivo={u}'

print('0. inicial          ', estado())

aplicar_jubilacion(db, EMP, hoy + timedelta(days=30), hoy)
print('1. fecha futura     ', estado(), '<- sigue activo, correcto')
print('   pendientes hoy:  ', pendientes_de_jubilar(db, hoy), '<- vacio, todavia no le toca')
print('   pendientes en 30d:', pendientes_de_jubilar(db, hoy + timedelta(days=30)))

aplicar_jubilacion(db, EMP, hoy, hoy)
print('2. fecha de hoy     ', estado(), '<- jubilado y sin acceso')
print('   en el tablero:   ', [j['name'] for j in jubilados(db)])

aplicar_jubilacion(db, EMP, None, hoy)
print('3. revertido        ', estado(), '<- vuelve a Activo con acceso')
print('   en el tablero:   ', [j['name'] for j in jubilados(db)])
db.close()
"
```

Esperado:

```
0. inicial           status=Activo userActivo=True
1. fecha futura      status=Activo userActivo=True <- sigue activo, correcto
   pendientes hoy:   [] <- vacio, todavia no le toca
   pendientes en 30d: [8]
2. fecha de hoy      status=Jubilado userActivo=False <- jubilado y sin acceso
   en el tablero:    ['Juan Gonzalez']
3. revertido         status=Activo userActivo=True <- vuelve a Activo con acceso
   en el tablero:    []
```

Si el paso 3 no deja `status=Activo userActivo=True`, hay que revisarlo antes de dar por terminado: significa que revertir no restituye el acceso.
