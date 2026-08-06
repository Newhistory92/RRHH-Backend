# Justificación de ausencias — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RRHH puede justificar una ausencia adjuntando un parte médico, y el día deja de restar horas del saldo.

**Architecture:** La justificación es un insumo más del recálculo, igual que feriados, licencias y correcciones manuales. Una tabla `JornadaJustificacion` guarda una fila por día justificado; el motor puro gana el estado `justificada`, que se calcula como la licencia (0 requeridas, 0 saldo). El recálculo sigue siendo reconstruible desde sus insumos.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text()` con binds nombrados), SQL Server vía pyodbc, Next.js + TypeScript en el frontend.

## Global Constraints

- **NO levantar servidor.** Nunca correr `uvicorn` ni ningún dev server en ningún paso.
- Credenciales de los relojes solo en `.env` (`RELOJ_USER`, `RELOJ_PASS`, `RELOJ_IPS`), jamás en código ni en documentos versionados.
- `.env` no se commitea.
- Los relojes son de solo lectura: la allowlist de `app/services/isapi_client.py` no se modifica.
- Backend en `C:\Users\Emiliano\Documents\Backend_RRHH`, frontend en `C:\Users\Emiliano\Documents\RRHH`. Son dos repos git distintos, cada uno con sus propios commits.
- SQL Server: los `ALTER`/`CREATE` son idempotentes (`IF ... IS NULL` / `IF NOT EXISTS`).
- Ventana de justificación: **30 días** hacia atrás. Se valida al crear, nunca al aplicar.
- Estado nuevo: la cadena exacta es `"justificada"`.
- Tipo de documento para los partes: la cadena exacta es `"Parte médico"`.

---

### Task 1: Motor de cálculo — estado justificada

**Files:**
- Modify: `app/services/asistencia_calc.py`
- Test: `tests/test_asistencia_calc.py`

**Interfaces:**
- Consumes: nada nuevo. `EntradaDia`, `ResultadoDia` y `calcular_dia` ya existen.
- Produces:
  - `ESTADO_JUSTIFICADA = "justificada"` — constante exportada en `__all__`.
  - `EntradaDia` gana el campo `justificada: bool = False`, último de la dataclass.

**Contexto:** `EntradaDia` es una dataclass congelada. El campo nuevo va **último y con default**, así ninguna construcción existente se rompe. `ResultadoDia` no cambia: el estado ya viaja en `ResultadoDia.estado` y se persiste en `JornadaDiaria.estado`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_asistencia_calc.py`:

```python
# -- Justificacion de ausencias -----------------------------------------------

def test_ausencia_justificada_no_resta_horas():
    r = c.calcular_dia(_dia(justificada=True), TOL, 12.0)
    assert r.estado == c.ESTADO_JUSTIFICADA
    assert r.horasRequeridas == 0.0
    assert r.horasTrabajadas == 0.0
    assert r.saldoDia == 0.0


def test_ausencia_sin_justificar_sigue_restando_la_jornada():
    r = c.calcular_dia(_dia(), TOL, 12.0)
    assert r.estado == c.ESTADO_AUSENTE
    assert r.horasRequeridas == 8.0
    assert r.saldoDia == -8.0


def test_la_justificacion_no_borra_las_horas_realmente_trabajadas():
    # Si aparece una marcacion despues de justificar, la persona trabajo:
    # se le cuentan las horas y el dia no queda como justificado.
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0), (16, 0)), justificada=True), TOL, 12.0,
    )
    assert r.estado == c.ESTADO_OK
    assert r.horasTrabajadas == 8.0


def test_con_licencia_y_justificacion_gana_la_licencia():
    r = c.calcular_dia(_dia(tiene_licencia=True, justificada=True), TOL, 12.0)
    assert r.estado == c.ESTADO_LICENCIA


def test_un_dia_no_laborable_justificado_sigue_sin_generar_fila():
    # Sabado 2026-07-04.
    r = c.calcular_dia(_dia(fecha=date(2026, 7, 4), justificada=True), TOL, 12.0)
    assert r is None


def test_una_jornada_incompleta_justificada_sigue_incompleta():
    # Falta un extremo: no es una ausencia, asi que la justificacion no aplica.
    r = c.calcular_dia(
        _dia(marcaciones=_marcas((8, 0)), justificada=True), TOL, 12.0,
    )
    assert r.estado == c.ESTADO_INCOMPLETA
```

Y agregar el parámetro al helper `_dia`, que está al principio del archivo. La firma pasa a:

```python
def _dia(fecha=date(2026, 7, 1), marcaciones=None, horario=JORNADA_8H,
         es_feriado=False, tiene_licencia=False, permisos=None,
         entrada_manual=None, salida_manual=None, justificada=False):
```

y el `return` suma el campo:

```python
    return c.EntradaDia(
        fecha=fecha,
        extremos=n.normalizar(
            marcaciones if marcaciones is not None else [], horario, correccion,
        ),
        horario=horario,
        es_feriado=es_feriado,
        tiene_licencia=tiene_licencia,
        permisos=permisos if permisos is not None else [],
        justificada=justificada,
    )
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_asistencia_calc.py -k justificad -v
```

Esperado: FAIL con `TypeError: EntradaDia.__init__() got an unexpected keyword argument 'justificada'`.

- [ ] **Step 3: Agregar la constante**

En `app/services/asistencia_calc.py`, después de `ESTADO_LICENCIA = "licencia"`:

```python
ESTADO_JUSTIFICADA = "justificada"
```

Y sumarla a `__all__`, que queda:

```python
__all__ = [
    "BANCO_PERMISO_ANUAL_HORAS", "DIAS_HABILES", "ESTADO_OK",
    "ESTADO_INCOMPLETA", "ESTADO_AUSENTE", "ESTADO_FERIADO", "ESTADO_LICENCIA",
    "ESTADO_JUSTIFICADA", "ESTADO_SIN_HORARIO", "HorarioDia", "Permiso",
    "EntradaDia", "ResultadoDia", "Tolerancias", "AjusteTolerancia",
    "calcular_dia", "calcular_anio",
]
```

- [ ] **Step 4: Agregar el campo a `EntradaDia`**

La dataclass queda:

```python
@dataclass(frozen=True)
class EntradaDia:
    fecha: date
    extremos: ExtremosDia
    horario: Optional[HorarioDia]
    es_feriado: bool
    tiene_licencia: bool
    permisos: list[Permiso]
    # Ultimo y con default: las construcciones que no lo pasan siguen andando.
    justificada: bool = False
```

- [ ] **Step 5: Aplicar la justificación en la rama de ausencia**

En `calcular_dia`, reemplazar el bloque de ausencia:

```python
    if entrada is None and salida is None:
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return _resultado(
            e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
            -e.horario.horasTrabajo,
        )
```

por:

```python
    if entrada is None and salida is None:
        # La justificacion se evalua aca y no antes: si mas tarde aparece una
        # marcacion por correccion manual, la persona trabajo y se le cuentan
        # las horas. Un parte medico no puede borrar presencia real.
        if e.justificada:
            return _resultado(e, ESTADO_JUSTIFICADA, 0.0, 0.0, 0.0)
        # Ausencia: se le exige la jornada completa. Los permisos de un dia sin
        # marcaciones no descuentan nada, no hay presencia que ajustar.
        return _resultado(
            e, ESTADO_AUSENTE, e.horario.horasTrabajo, 0.0,
            -e.horario.horasTrabajo,
        )
```

La licencia se sigue evaluando antes, sin cambios: cubre el día aunque la persona haya pasado por la oficina.

- [ ] **Step 6: Correr los tests**

```bash
py -m pytest tests/test_asistencia_calc.py -v
```

Esperado: PASS en todos, los nuevos y los que ya existían.

- [ ] **Step 7: Commit**

```bash
git add app/services/asistencia_calc.py tests/test_asistencia_calc.py
git commit -m "feat: estado justificada para las ausencias con parte medico

El dia justificado se calcula como una licencia: cero requeridas, cero
saldo. La condicion se evalua dentro de la rama de ausencia y no antes,
para que una marcacion posterior por correccion manual gane: un parte
medico no puede borrar presencia real.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Capa de justificaciones — validación pura y persistencia

**Files:**
- Create: `app/services/asistencia_justificaciones.py`
- Create: `app/database/asistencia_justificaciones.py`
- Test: `tests/test_asistencia_justificaciones.py`

**Interfaces:**
- Consumes: `ESTADO_JUSTIFICADA` de `app.services.asistencia_calc` (Task 1) — solo en el router, no acá.
- Produces:
  - `VENTANA_JUSTIFICACION_DIAS = 30` y `validar_fecha_justificable(fecha: date, hoy: date) -> None` en `app/services/asistencia_justificaciones.py`.
  - En `app/database/asistencia_justificaciones.py`:
    - `ensure_tables(db: Session) -> None`
    - `justificar(db, employee_id: int, fecha: date, file_name: str, mime_type: str, file_data: str, observacion: str | None, justificado_por: int) -> int` — devuelve el `documentoId` nuevo.
    - `borrar_justificacion(db, employee_id: int, fecha: date) -> bool`
    - `dias_justificados(db, employee_id: int, desde: date, hasta: date) -> set[date]`
    - `justificaciones_de(db, employee_id: int, desde: date, hasta: date) -> dict[date, dict]`

**Contexto:** El proyecto separa la lógica pura (`app/services/`, testeable sin base) del SQL (`app/database/`). `asistencia_alertas.py` es el precedente: `validar_umbrales` vive ahí y no en las rutas, para poder testearla sin `TestClient`. La validación de la ventana sigue ese patrón.

**Nota sobre la transacción:** `app/database/employee_documents.py` ya tiene `save_document`, pero hace `db.commit()` internamente. Si lo usáramos, un fallo posterior en el upsert dejaría un documento huérfano. Por eso `justificar` hace su propio `INSERT` sin commit y cierra las dos operaciones con un solo `db.commit()` al final.

**Desviación deliberada del spec:** el spec listaba `upsert_justificacion(db, employee_id, fecha, documento_id, ...)` como función separada, con el documento ya creado por afuera. Ese reparto no puede cumplir el requisito transaccional que el propio spec exige ("las dos operaciones van en la misma transacción"), porque quien crea el documento tendría que commitear antes de llamarla. `justificar` unifica ambas en una sola función y una sola transacción. Es el mismo contrato de negocio con una frontera distinta.

- [ ] **Step 1: Escribir los tests de la validación pura**

Crear `tests/test_asistencia_justificaciones.py`:

```python
from datetime import date

import pytest

from app.services.asistencia_justificaciones import (
    VENTANA_JUSTIFICACION_DIAS, validar_fecha_justificable,
)

HOY = date(2026, 8, 6)


def test_la_ventana_es_de_treinta_dias():
    assert VENTANA_JUSTIFICACION_DIAS == 30


def test_hoy_se_puede_justificar():
    validar_fecha_justificable(HOY, HOY)


def test_ayer_se_puede_justificar():
    validar_fecha_justificable(date(2026, 8, 5), HOY)


def test_el_borde_exacto_de_treinta_dias_se_puede_justificar():
    # 2026-07-07 esta exactamente 30 dias antes de 2026-08-06.
    validar_fecha_justificable(date(2026, 7, 7), HOY)


def test_treinta_y_un_dias_atras_ya_no_se_puede():
    with pytest.raises(ValueError, match="30 dias"):
        validar_fecha_justificable(date(2026, 7, 6), HOY)


def test_una_fecha_futura_no_se_puede_justificar():
    with pytest.raises(ValueError, match="futura"):
        validar_fecha_justificable(date(2026, 8, 7), HOY)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

```bash
py -m pytest tests/test_asistencia_justificaciones.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'app.services.asistencia_justificaciones'`.

- [ ] **Step 3: Escribir el módulo puro**

Crear `app/services/asistencia_justificaciones.py`:

```python
"""
Reglas de la justificacion de ausencias que no tocan la base.

Vive aparte del SQL para poder testear la ventana sin TestClient ni base,
igual que validar_umbrales en asistencia_alertas.py.
"""

from datetime import date, timedelta

VENTANA_JUSTIFICACION_DIAS = 30


def validar_fecha_justificable(fecha: date, hoy: date) -> None:
    """
    Verifica que la fecha caiga dentro de la ventana para justificar. Lanza
    ValueError con un mensaje listo para mostrar; el traductor a HTTP vive en
    la capa de rutas.

    La ventana limita cuando se PUEDE crear una justificacion, nunca cuando
    aplica. Una vez cargada vale para siempre: si el motor mirara la ventana,
    el saldo historico de una persona cambiaria solo con el paso del tiempo.
    """
    if fecha > hoy:
        raise ValueError("No se puede justificar una fecha futura")
    if fecha < hoy - timedelta(days=VENTANA_JUSTIFICACION_DIAS):
        raise ValueError(
            f"Solo se pueden justificar ausencias de los ultimos "
            f"{VENTANA_JUSTIFICACION_DIAS} dias")
```

- [ ] **Step 4: Correr los tests**

```bash
py -m pytest tests/test_asistencia_justificaciones.py -v
```

Esperado: PASS en los 6.

- [ ] **Step 5: Escribir el módulo de persistencia**

Crear `app/database/asistencia_justificaciones.py`:

```python
"""
Persistencia de las justificaciones de ausencia.

Una fila por dia justificado. La tabla es un insumo del recalculo, igual que
JornadaCorreccion: el motor la lee y reconstruye el estado del dia. Por eso no
guarda nada calculado.
"""

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

TIPO_DOCUMENTO = "Parte médico"

CREATE_TABLE_SQL = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='JornadaJustificacion' AND xtype='U')
BEGIN
    CREATE TABLE JornadaJustificacion (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        employeeId     INT           NOT NULL,
        fecha          DATE          NOT NULL,
        documentoId    INT           NOT NULL,
        observacion    NVARCHAR(500) NULL,
        justificadoPor INT           NOT NULL,
        createdAt      DATETIME2     NOT NULL,
        CONSTRAINT UQ_JornadaJustificacion UNIQUE (employeeId, fecha)
    );
    CREATE INDEX IX_JornadaJustificacion_empleado
        ON JornadaJustificacion (employeeId, fecha);
END
"""


def ensure_tables(db: Session) -> None:
    """Crea la tabla si no existe. Idempotente."""
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def justificar(db: Session, employee_id: int, fecha: date, file_name: str,
               mime_type: str, file_data: str, observacion: str | None,
               justificado_por: int) -> int:
    """
    Guarda el parte medico y la justificacion del dia en una sola transaccion.
    Devuelve el id del documento nuevo.

    Si el dia ya estaba justificado, reemplaza el parte y da de baja el
    anterior: es la carga de un documento corregido, no un duplicado.

    El INSERT del documento se hace aca y no con employee_documents.save_document
    porque aquella funcion commitea por su cuenta, y un fallo posterior en el
    upsert dejaria un documento huerfano.
    """
    ahora = datetime.utcnow()

    documento_id = db.execute(text("""
        INSERT INTO EmployeeDocument
            (employeeId, tipo, descripcion, fileName, mimeType, fileData,
             activo, createdAt)
        OUTPUT INSERTED.id
        VALUES (:emp, :tipo, :desc, :nombre, :mime, :datos, 1, :ahora)
    """), {
        "emp": employee_id, "tipo": TIPO_DOCUMENTO,
        "desc": f"Justificacion de la ausencia del {fecha.isoformat()}",
        "nombre": file_name, "mime": mime_type, "datos": file_data,
        "ahora": ahora,
    }).scalar()

    previa = db.execute(text("""
        SELECT documentoId FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()

    if previa is None:
        db.execute(text("""
            INSERT INTO JornadaJustificacion
                (employeeId, fecha, documentoId, observacion, justificadoPor,
                 createdAt)
            VALUES (:emp, :fecha, :doc, :obs, :por, :ahora)
        """), {"emp": employee_id, "fecha": fecha, "doc": documento_id,
               "obs": observacion, "por": justificado_por, "ahora": ahora})
    else:
        db.execute(text("""
            UPDATE JornadaJustificacion
            SET documentoId = :doc, observacion = :obs, justificadoPor = :por,
                createdAt = :ahora
            WHERE employeeId = :emp AND fecha = :fecha
        """), {"emp": employee_id, "fecha": fecha, "doc": documento_id,
               "obs": observacion, "por": justificado_por, "ahora": ahora})
        db.execute(text("""
            UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
        """), {"id": previa["documentoId"]})

    db.commit()
    return int(documento_id)


def borrar_justificacion(db: Session, employee_id: int, fecha: date) -> bool:
    """
    Anula la justificacion y da de baja su documento. Devuelve False si no
    habia ninguna.
    """
    fila = db.execute(text("""
        SELECT documentoId FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha}).mappings().first()
    if fila is None:
        return False

    db.execute(text("""
        DELETE FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": fecha})
    db.execute(text("""
        UPDATE EmployeeDocument SET activo = 0 WHERE id = :id
    """), {"id": fila["documentoId"]})
    db.commit()
    return True


def dias_justificados(db: Session, employee_id: int,
                      desde: date, hasta: date) -> set[date]:
    """Las fechas justificadas del rango. Es el insumo del recalculo."""
    filas = db.execute(text("""
        SELECT fecha FROM JornadaJustificacion
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return {f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
            for f in filas}


def justificaciones_de(db: Session, employee_id: int, desde: date,
                       hasta: date) -> dict[date, dict]:
    """
    El detalle de cada justificacion del rango, indexado por fecha. Trae los
    datos del documento y el nombre de quien justifico, que es lo que muestra
    la pestana de Ausencias.
    """
    filas = db.execute(text("""
        SELECT j.fecha, j.documentoId, j.observacion, j.createdAt,
               d.fileName, d.mimeType, e.name AS justificadoPor
        FROM JornadaJustificacion j
        LEFT JOIN EmployeeDocument d ON d.id = j.documentoId
        LEFT JOIN Employee e ON e.id = j.justificadoPor
        WHERE j.employeeId = :emp AND j.fecha >= :desde AND j.fecha <= :hasta
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()

    detalle: dict[date, dict] = {}
    for f in filas:
        d = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        detalle[d] = {
            "documentoId": int(f["documentoId"]),
            "fileName": f["fileName"],
            "mimeType": f["mimeType"],
            "observacion": f["observacion"],
            "justificadoPor": f["justificadoPor"] or "",
            "createdAt": f["createdAt"].isoformat() if f["createdAt"] else None,
        }
    return detalle
```

- [ ] **Step 6: Verificar que el módulo importa**

```bash
py -c "from app.database.asistencia_justificaciones import justificar, dias_justificados; print('OK')"
```

Esperado: imprime `OK` (precedido por los mensajes de conexión a la base, que son normales).

- [ ] **Step 7: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services/asistencia_justificaciones.py app/database/asistencia_justificaciones.py tests/test_asistencia_justificaciones.py
git commit -m "feat: capa de justificaciones de ausencia

La ventana de 30 dias vive en services/ como funcion pura, testeable sin
base ni TestClient, igual que validar_umbrales.

justificar() hace su propio INSERT del documento en vez de reusar
save_document porque aquella commitea por su cuenta: un fallo posterior
en el upsert dejaria un parte medico huerfano.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Recálculo — conectar el insumo

**Files:**
- Modify: `app/services/asistencia_recalc.py`

**Interfaces:**
- Consumes: `dias_justificados(db, employee_id, desde, hasta) -> set[date]` de Task 2; el campo `EntradaDia.justificada` de Task 1.
- Produces: nada nuevo. A partir de acá, `recalcular_anio` respeta las justificaciones.

**Contexto:** `recalcular_anio` carga todos los insumos en bloque (correcciones, marcaciones, feriados, licencias, permisos) y después arma un `EntradaDia` por día. La justificación se suma como un insumo más, con la misma forma que `feriados` y `licencias`, que ya son `set[date]`.

- [ ] **Step 1: Agregar el import**

En `app/services/asistencia_recalc.py`, después del import de `asistencia_auditoria`:

```python
from app.database.asistencia_justificaciones import dias_justificados
```

- [ ] **Step 2: Cargar el insumo**

En `recalcular_anio`, después de la línea que carga los permisos:

```python
    permisos = _permisos_por_dia(db, employee_id, desde, hasta)
```

agregar:

```python
    justificados = dias_justificados(db, employee_id, desde, hasta)
```

- [ ] **Step 3: Pasarlo a cada `EntradaDia`**

En el bucle que arma las entradas, el `append` queda:

```python
        entradas.append(EntradaDia(
            fecha=d,
            extremos=normalizar(
                marcaciones.get(d, []), horario, correcciones.get(d),
            ),
            horario=horario,
            es_feriado=d in feriados,
            tiene_licencia=d in licencias,
            permisos=permisos.get(d, []),
            justificada=d in justificados,
        ))
```

- [ ] **Step 4: Verificar que el módulo compila**

```bash
py -c "from app.services.asistencia_recalc import recalcular_anio; print('OK')"
```

Esperado: imprime `OK`.

- [ ] **Step 5: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/asistencia_recalc.py
git commit -m "feat: el recalculo respeta las ausencias justificadas

dias_justificados entra como un insumo mas, con la misma forma que
feriados y licencias. El recalculo sigue siendo reconstruible desde sus
insumos: justificar y despues recalcular da el mismo resultado que
recalcular y despues justificar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: API — router de ausencias

**Files:**
- Create: `app/routes/asistencia_ausencias.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: todo lo de Tasks 1-3 (`ESTADO_JUSTIFICADA`, `ESTADO_AUSENTE`, `validar_fecha_justificable`, `justificar`, `borrar_justificacion`, `justificaciones_de`, `recalcular_anio`).
- Produces: tres endpoints bajo `/asistencia`, todos restringidos a RRHH:
  - `GET /asistencia/empleado/{employee_id}/ausencias?desde&hasta`
  - `POST /asistencia/empleado/{employee_id}/ausencias/{fecha}/justificar`
  - `DELETE /asistencia/empleado/{employee_id}/ausencias/{fecha}/justificar`

**Contexto:** `app/routes/asistencia.py` ya carga tablero, config, recálculo, correcciones y alertas. Este router va aparte para que aquel no siga creciendo. Copia el patrón de `get_db`, `_rango` y `SOLO_RRHH` de `asistencia.py`; son pocas líneas y evitan un import circular entre routers.

- [ ] **Step 1: Escribir el router**

Crear `app/routes/asistencia_ausencias.py`:

```python
"""
Ausencias de un empleado y su justificacion.

Dos vias llegan al mismo lugar. Por licencia: RRHH carga y aprueba una licencia
que cubre la fecha, y el dia deja de ser una ausencia en el proximo recalculo
sin que nadie toque nada de este router. Por parte medico: RRHH adjunta el
documento aca y el dia pasa a estado justificada.
"""

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, ROLE_RRHH, get_current_user, require_roles,
)
from app.database.asistencia import ensure_tables as ensure_tablas_asistencia
from app.database.asistencia_justificaciones import (
    borrar_justificacion, ensure_tables, justificaciones_de, justificar,
)
from app.database.database import SessionLocal
from app.services.asistencia_calc import ESTADO_AUSENTE, ESTADO_JUSTIFICADA
from app.services.asistencia_justificaciones import (
    VENTANA_JUSTIFICACION_DIAS, validar_fecha_justificable,
)
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
    try:
        d = date.fromisoformat(desde) if desde else date(hoy.year, 1, 1)
        h = date.fromisoformat(hasta) if hasta else hoy
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="Formato de fecha invalido, use YYYY-MM-DD")
    if d > h:
        raise HTTPException(status_code=400,
                            detail="'desde' no puede ser posterior a 'hasta'")
    return d, h


def _fecha(crudo: str) -> date:
    try:
        return date.fromisoformat(crudo)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="La fecha debe ser YYYY-MM-DD")


def _licencias_sin_aprobar(db: Session, employee_id: int,
                           desde: date, hasta: date) -> list[dict]:
    """
    Licencias que cubren dias del rango pero todavia no estan aprobadas.

    Es lo que hace accionable la via licencia: RRHH ve la ausencia, ve que hay
    una licencia sin aprobar que la cubriria, la aprueba, y la ausencia se
    resuelve sola en el recalculo.
    """
    filas = db.execute(text("""
        SELECT id, type, status, startDate, endDate
        FROM License
        WHERE employeeId = :emp AND status <> 'Aprobada'
          AND startDate <= :hasta AND endDate >= :desde
    """), {"emp": employee_id, "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]


def _licencia_que_cubre(licencias: list[dict], dia: date) -> dict | None:
    for lic in licencias:
        ini = lic["startDate"]
        fin = lic["endDate"]
        ini = ini if isinstance(ini, date) else ini.date()
        fin = fin if isinstance(fin, date) else fin.date()
        if ini <= dia <= fin:
            return {"id": int(lic["id"]), "type": lic["type"],
                    "status": lic["status"]}
    return None


@router.get("/empleado/{employee_id}/ausencias", dependencies=[SOLO_RRHH])
def get_ausencias(employee_id: int, desde: str | None = None,
                  hasta: str | None = None, db: Session = Depends(get_db)):
    """
    Los dias ausentes y justificados del rango.

    Los dias de licencia no aparecen: nunca fueron un problema a resolver. Que
    una ausencia desaparezca de esta lista es justamente la confirmacion de que
    la licencia retroactiva quedo aprobada.
    """
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    d, h = _rango(desde, hasta)
    hoy = date.today()

    filas = db.execute(text("""
        SELECT fecha, estado, horasRequeridas
        FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha >= :desde AND fecha <= :hasta
          AND estado IN (:ausente, :justificada)
        ORDER BY fecha DESC
    """), {"emp": employee_id, "desde": d, "hasta": h,
           "ausente": ESTADO_AUSENTE, "justificada": ESTADO_JUSTIFICADA}
    ).mappings().all()

    detalle = justificaciones_de(db, employee_id, d, h)
    pendientes = _licencias_sin_aprobar(db, employee_id, d, h)

    ausencias = []
    for f in filas:
        dia = f["fecha"] if isinstance(f["fecha"], date) else f["fecha"].date()
        justificada = f["estado"] == ESTADO_JUSTIFICADA
        puede = True
        try:
            validar_fecha_justificable(dia, hoy)
        except ValueError:
            puede = False
        ausencias.append({
            "fecha": dia.isoformat(),
            "estado": f["estado"],
            "horasPerdidas": float(f["horasRequeridas"] or 0),
            "puedeJustificar": puede,
            "justificacion": detalle.get(dia),
            "licenciaPendiente": (
                None if justificada else _licencia_que_cubre(pendientes, dia)
            ),
        })

    return {"desde": d.isoformat(), "hasta": h.isoformat(),
            "ausencias": ausencias,
            "ventanaDias": VENTANA_JUSTIFICACION_DIAS}


@router.post("/empleado/{employee_id}/ausencias/{fecha}/justificar",
             dependencies=[SOLO_RRHH])
def post_justificar(employee_id: int, fecha: str, data: dict = Body(...),
                    usuario: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Adjunta el parte medico, justifica el dia y recalcula el anio."""
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    dia = _fecha(fecha)

    try:
        validar_fecha_justificable(dia, date.today())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_name = data.get("fileName")
    mime_type = data.get("mimeType")
    file_data = data.get("fileData")
    if not file_name or not mime_type or not file_data:
        raise HTTPException(
            status_code=400,
            detail="El parte medico es obligatorio: faltan fileName, mimeType o fileData")

    if usuario.get("employeeId") is None:
        raise HTTPException(
            status_code=403,
            detail="Tu usuario no tiene legajo vinculado para registrar la justificacion")

    jornada = db.execute(text("""
        SELECT estado FROM JornadaDiaria
        WHERE employeeId = :emp AND fecha = :fecha
    """), {"emp": employee_id, "fecha": dia}).mappings().first()
    if jornada is None:
        raise HTTPException(status_code=404,
                            detail="No hay una jornada calculada para ese dia")
    # Se acepta justificada para permitir reemplazar el parte por uno
    # corregido. Cualquier otro estado seria borrarle horas reales a la persona.
    if jornada["estado"] not in (ESTADO_AUSENTE, ESTADO_JUSTIFICADA):
        raise HTTPException(
            status_code=400,
            detail=f"El dia esta en estado '{jornada['estado']}' y no es una ausencia")

    documento_id = justificar(
        db, employee_id, dia, file_name, mime_type, file_data,
        data.get("observacion"), int(usuario["employeeId"]),
    )
    recalcular_anio(db, employee_id, dia.year)
    return {"ok": True, "fecha": dia.isoformat(), "documentoId": documento_id}


@router.delete("/empleado/{employee_id}/ausencias/{fecha}/justificar",
               dependencies=[SOLO_RRHH])
def delete_justificar(employee_id: int, fecha: str,
                      db: Session = Depends(get_db)):
    """Anula la justificacion. El dia vuelve a contar como ausencia."""
    ensure_tablas_asistencia(db)
    ensure_tables(db)
    dia = _fecha(fecha)
    if not borrar_justificacion(db, employee_id, dia):
        raise HTTPException(status_code=404,
                            detail="No hay justificacion para ese dia")
    recalcular_anio(db, employee_id, dia.year)
    return {"eliminado": True, "fecha": dia.isoformat()}
```

- [ ] **Step 2: Registrar el router**

En `app/main.py`, la línea 5 del import pasa a terminar en `asistencia, asistencia_ausencias`:

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes, asistencia, asistencia_ausencias
```

Y después de `app.include_router(asistencia.router)`:

```python
app.include_router(asistencia_ausencias.router)
```

- [ ] **Step 3: Verificar que la app carga**

```bash
py -c "from app.main import app; rutas = [r.path for r in app.routes if 'ausencias' in r.path]; print('\n'.join(sorted(set(rutas))))"
```

Esperado: las tres rutas listadas.

```
/asistencia/empleado/{employee_id}/ausencias
/asistencia/empleado/{employee_id}/ausencias/{fecha}/justificar
```

(la segunda aparece una vez aunque tenga POST y DELETE)

- [ ] **Step 4: Correr la suite completa**

```bash
py -m pytest tests/ -q
```

Esperado: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/asistencia_ausencias.py app/main.py
git commit -m "feat: endpoints de ausencias y justificacion por parte medico

Router propio: asistencia.py ya carga tablero, config, recalculo,
correcciones y alertas.

El GET lista solo ausentes y justificadas. Los dias de licencia no
aparecen porque nunca fueron un problema a resolver, y que una ausencia
desaparezca de la lista es la confirmacion de que la licencia
retroactiva quedo aprobada. Para que esa via sea accionable, cada
ausencia informa si hay una licencia sin aprobar que la cubriria.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — pestaña de Ausencias

**Files:**
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Interfas\Interfaces.ts`
- Create: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\AusenciasEmpleadoTab.tsx`
- Modify: `C:\Users\Emiliano\Documents\RRHH\src\app\Componentes\TablaOperador\Perfildetail.tsx`

**Interfaces:**
- Consumes: los tres endpoints de Task 4.
- Produces: nada que consuman otros tasks. Es la última pieza.

**Contexto:** Este es el repo del frontend, con sus propios commits. El patrón de subida de archivos a base64 ya existe en `DetailTables.tsx`: `FileReader.readAsDataURL` produce `"data:<mime>;base64,<data>"` y se manda solo la parte después de la coma. La pestaña se suma a `Perfildetail.tsx`, que ya maneja las pestañas con `useState` y clases `border-b-2`.

- [ ] **Step 1: Agregar los tipos**

En `src/app/Interfas/Interfaces.ts`, después de la interfaz `AlertaTolerancia`:

```typescript
/** Parte médico que justifica una ausencia. */
export interface JustificacionAusencia {
  documentoId: number;
  fileName: string;
  mimeType: string;
  observacion: string | null;
  justificadoPor: string;
  createdAt: string | null;
}

/** Licencia que cubriría la fecha pero todavía no está aprobada. */
export interface LicenciaPendiente {
  id: number;
  type: string;
  status: string;
}

/** Día ausente o justificado en la pestaña de Ausencias. */
export interface AusenciaEmpleado {
  fecha: string;
  estado: "ausente" | "justificada";
  horasPerdidas: number;
  puedeJustificar: boolean;
  justificacion: JustificacionAusencia | null;
  licenciaPendiente: LicenciaPendiente | null;
}
```

- [ ] **Step 2: Escribir el componente**

Crear `src/app/Componentes/TablaOperador/AusenciasEmpleadoTab.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Toast } from "primereact/toast";
import { apiClient } from "@/app/util/apiClient";
import { AusenciaEmpleado, Employee } from "@/app/Interfas/Interfaces";

const DIAS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

const diaDeSemana = (iso: string) => {
  const [a, m, d] = iso.split("-").map(Number);
  return DIAS[new Date(a, m - 1, d).getDay()];
};

const aBase64 = (archivo: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      if (typeof reader.result === "string") {
        // readAsDataURL produce "data:<mime>;base64,<data>" — solo el base64
        resolve(reader.result.split(",")[1] || "");
      } else {
        reject(new Error("No se pudo leer el archivo"));
      }
    };
    reader.onerror = () => reject(new Error("No se pudo leer el archivo"));
    reader.readAsDataURL(archivo);
  });

interface Props {
  employee: Employee;
}

export function AusenciasEmpleadoTab({ employee }: Props) {
  const [ausencias, setAusencias] = useState<AusenciaEmpleado[]>([]);
  const [ventanaDias, setVentanaDias] = useState(30);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [justificando, setJustificando] = useState<string | null>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [observacion, setObservacion] = useState("");
  const [guardando, setGuardando] = useState(false);
  const toast = useRef<Toast>(null);

  const cargar = useCallback(async () => {
    if (!employee.id) return;
    setCargando(true);
    try {
      const r = await apiClient.get<{
        ausencias: AusenciaEmpleado[];
        ventanaDias: number;
      }>(`/asistencia/empleado/${employee.id}/ausencias`);
      setAusencias(r.ausencias);
      setVentanaDias(r.ventanaDias);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar las ausencias");
    } finally {
      setCargando(false);
    }
  }, [employee.id]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const guardar = async () => {
    if (!justificando || !archivo) return;
    setGuardando(true);
    try {
      const fileData = await aBase64(archivo);
      await apiClient.post(
        `/asistencia/empleado/${employee.id}/ausencias/${justificando}/justificar`,
        {
          fileName: archivo.name,
          mimeType: archivo.type || "application/octet-stream",
          fileData,
          observacion: observacion || null,
        },
      );
      toast.current?.show({
        severity: "success",
        summary: "Ausencia justificada",
        detail: "El saldo del empleado fue recalculado.",
        life: 4000,
      });
      setJustificando(null);
      setArchivo(null);
      setObservacion("");
      await cargar();
    } catch (e) {
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: e instanceof Error ? e.message : "No se pudo justificar",
        life: 5000,
      });
    } finally {
      setGuardando(false);
    }
  };

  const anular = async (fecha: string) => {
    if (!confirm(`¿Anular la justificación del ${fecha}? El día vuelve a contar como ausencia.`)) {
      return;
    }
    try {
      await apiClient.delete(
        `/asistencia/empleado/${employee.id}/ausencias/${fecha}/justificar`,
      );
      toast.current?.show({
        severity: "info",
        summary: "Justificación anulada",
        detail: "El saldo del empleado fue recalculado.",
        life: 4000,
      });
      await cargar();
    } catch (e) {
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: e instanceof Error ? e.message : "No se pudo anular",
        life: 5000,
      });
    }
  };

  const descargar = async (documentoId: number, fileName: string) => {
    try {
      const doc = await apiClient.get<{ fileData: string; mimeType: string }>(
        `/rrhh/employee/${employee.id}/documents/${documentoId}/download`,
      );
      const binario = atob(doc.fileData);
      const bytes = new Uint8Array(binario.length);
      for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes], { type: doc.mimeType }));
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.current?.show({
        severity: "error",
        summary: "Error",
        detail: e instanceof Error ? e.message : "No se pudo descargar el parte",
        life: 5000,
      });
    }
  };

  if (!employee.biometricoId) {
    return (
      <div className="mt-6 p-6 bg-card rounded-lg border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400">
        <p className="font-semibold mb-1">Sin ID de reloj asignado</p>
        <p className="text-sm">
          Este empleado no tiene un ID biométrico vinculado, así que no hay ausencias
          calculadas.
        </p>
      </div>
    );
  }

  if (cargando) {
    return (
      <div className="mt-6 p-8 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-2xl mb-2" />
        <p>Cargando ausencias…</p>
      </div>
    );
  }

  if (error) {
    return <div className="mt-6 p-6 text-center text-error">{error}</div>;
  }

  const pendientes = ausencias.filter((a) => a.estado === "ausente");
  const justificadas = ausencias.filter((a) => a.estado === "justificada");
  const horasPerdidas = pendientes.reduce((s, a) => s + a.horasPerdidas, 0);

  return (
    <div className="mt-6 space-y-6">
      <Toast ref={toast} />

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-card rounded-lg border border-border p-5">
          <p className="text-xs text-muted-foreground mb-1">Sin justificar</p>
          <p className={`text-3xl font-heading ${pendientes.length > 0 ? "text-error" : "text-foreground"}`}>
            {pendientes.length}
          </p>
          <p className="text-xs text-muted-foreground mt-1">días</p>
        </div>
        <div className="bg-card rounded-lg border border-border p-5">
          <p className="text-xs text-muted-foreground mb-1">Justificadas</p>
          <p className="text-3xl font-heading text-success">{justificadas.length}</p>
          <p className="text-xs text-muted-foreground mt-1">con parte médico</p>
        </div>
        <div className="bg-card rounded-lg border border-border p-5">
          <p className="text-xs text-muted-foreground mb-1">Horas perdidas</p>
          <p className={`text-3xl font-heading ${horasPerdidas > 0 ? "text-error" : "text-foreground"}`}>
            {horasPerdidas.toFixed(1)}
          </p>
          <p className="text-xs text-muted-foreground mt-1">sin justificar</p>
        </div>
      </div>

      <div className="bg-card rounded-lg border border-border p-4">
        <h3 className="font-heading text-base text-foreground mb-1">Ausencias</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Se pueden justificar las de los últimos {ventanaDias} días. Una licencia
          aprobada que cubra la fecha resuelve la ausencia sin cargar nada acá.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="py-2 pr-4">Fecha</th>
                <th className="py-2 pr-4">Día</th>
                <th className="py-2 pr-4">Estado</th>
                <th className="py-2 pr-4">Parte médico</th>
                <th className="py-2 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {ausencias.map((a) => (
                <tr key={a.fecha} className="border-b border-border last:border-0">
                  <td className="py-2 pr-4 text-foreground">{a.fecha}</td>
                  <td className="py-2 pr-4 text-muted-foreground">{diaDeSemana(a.fecha)}</td>
                  <td className="py-2 pr-4">
                    {a.estado === "justificada" ? (
                      <span className="text-success">Justificada</span>
                    ) : (
                      <>
                        <span className="text-error">Sin justificar</span>
                        {a.licenciaPendiente && (
                          <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                            Licencia de {a.licenciaPendiente.type} sin aprobar cubriría este día
                          </p>
                        )}
                      </>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {a.justificacion ? (
                      <button
                        onClick={() =>
                          descargar(a.justificacion!.documentoId, a.justificacion!.fileName)
                        }
                        className="text-primary hover:underline"
                      >
                        {a.justificacion.fileName}
                      </button>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {a.estado === "justificada" ? (
                      <button
                        onClick={() => anular(a.fecha)}
                        className="px-3 py-1 rounded-lg bg-muted text-foreground text-xs hover:opacity-90"
                      >
                        Anular
                      </button>
                    ) : a.puedeJustificar ? (
                      <button
                        onClick={() => setJustificando(a.fecha)}
                        className="px-3 py-1 rounded-lg bg-primary text-white text-xs hover:opacity-90"
                      >
                        Justificar
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">Fuera de plazo</span>
                    )}
                  </td>
                </tr>
              ))}
              {ausencias.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-muted-foreground">
                    Sin ausencias en el período.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {justificando && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-lg shadow-lg p-6 w-full max-w-md">
            <h3 className="font-heading text-lg text-foreground mb-1">Justificar ausencia</h3>
            <p className="text-sm text-muted-foreground mb-4">
              {employee.name} — {justificando}
            </p>

            <label className="block text-sm font-medium text-muted-foreground mb-1">
              Parte médico (obligatorio)
            </label>
            <input
              type="file"
              onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
              className="w-full text-sm mb-4"
            />

            <label className="block text-sm font-medium text-muted-foreground mb-1">
              Observación
            </label>
            <input
              type="text"
              value={observacion}
              onChange={(e) => setObservacion(e.target.value)}
              placeholder="Ej: reposo indicado por 24hs"
              className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm w-full mb-6"
            />

            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setJustificando(null);
                  setArchivo(null);
                  setObservacion("");
                }}
                disabled={guardando}
                className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={guardar}
                disabled={!archivo || guardando}
                className="px-4 py-2 rounded-lg bg-primary text-white text-sm disabled:opacity-50"
              >
                {guardando ? "Guardando…" : "Justificar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Agregar la pestaña**

En `src/app/Componentes/TablaOperador/Perfildetail.tsx`, sumar el import después del de `AlertasToleranciaTab`:

```tsx
import { AusenciasEmpleadoTab } from "./AusenciasEmpleadoTab"
```

Agregar el botón después del de "Alertas de tolerancia", dentro del `<nav>`:

```tsx
          <button
            onClick={() => setActiveTab("ausencias")}
            className={`${
              activeTab === "ausencias"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Ausencias
          </button>
```

Y el render, después de la línea de `alertas`:

```tsx
        {activeTab === "ausencias" && <AusenciasEmpleadoTab employee={employee} />}
```

- [ ] **Step 4: Verificar que compila**

```bash
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -E "AusenciasEmpleadoTab|Perfildetail|Interfaces"
```

Esperado: sin salida. El proyecto tiene un error de tipos previo en `src/app/util/Constants.ts` que no es parte de este trabajo; el filtro aísla los tres archivos que sí lo son.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\Emiliano\Documents\RRHH"
git add src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/AusenciasEmpleadoTab.tsx src/app/Componentes/TablaOperador/Perfildetail.tsx
git commit -m "feat: pestana de ausencias con justificacion por parte medico

RRHH adjunta el parte y el dia deja de restar horas. La fila de una
ausencia sin justificar avisa si hay una licencia sin aprobar que la
cubriria: aprobarla la resuelve sin cargar ningun documento.

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
cd "C:\Users\Emiliano\Documents\RRHH" && npx tsc --noEmit 2>&1 | grep -vE "Constants.ts"
```

Esperado: sin salida más allá del error preexistente de `Constants.ts`.

Y la verificación de que la tabla se crea, sin levantar servidor:

```bash
cd "C:\Users\Emiliano\Documents\Backend_RRHH" && py -c "
from app.database.database import SessionLocal
from app.database.asistencia_justificaciones import ensure_tables
db = SessionLocal()
ensure_tables(db)
print('Tabla JornadaJustificacion lista')
db.close()
"
```

Esperado: imprime `Tabla JornadaJustificacion lista`.
