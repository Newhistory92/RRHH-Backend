# Baja de empleados — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar la baja de un empleado con su motivo, dejándole la cuenta viva pero recortada a ver solo su legajo, y mostrar las bajas de la institución en un tablero con desglose por motivo.

**Architecture:** Una tabla `EmployeeBaja` es la fuente de verdad; "está de baja" se calcula con la fecha en cada uso, nunca se almacena. El recorte de permisos vive en una única función que usan los dos lugares que hoy los resuelven (el middleware por request y la respuesta del login), así que ningún endpoint queda abierto y la UI se recorta sola. La jubilación pasa a ser uno de los siete motivos y su módulo se retira al final, cuando ya nada lo referencia.

**Tech Stack:** Backend: FastAPI, SQLAlchemy Core (`text()`), SQL Server, pytest con el doble `FakeSession`. Frontend: Next.js 15, React, PrimeReact, Tailwind con tokens CSS del proyecto.

## Global Constraints

- Los siete motivos son exactamente, con acentos: `"Jubilación"`, `"Renuncia"`, `"Despido"`, `"Fin de contrato"`, `"Fallecimiento"`, `"Traslado a otro organismo"`, `"Abandono de cargo"`. Un motivo fuera del catálogo se rechaza con 400.
- El recorte devuelve exactamente `{"documentos.propios"}`, ignorando el rol y el comodín `"*"` de ADMIN.
- La baja **nunca** escribe `User.activo`. Ese campo es del panel de ADMIN y queda intacto.
- Cancelar una solicitud pendiente es pasarla a `'Rechazada'`. No se agrega ningún estado nuevo al tipo `LicenseStatus`.
- Todo DDL es idempotente y corre en el startup de `app/main.py`, nunca en el camino de un request.
- Los tests no tocan una base real: van con `FakeSession` de `tests/fakes.py`, que mapea un fragmento de SQL a las filas que devuelve.
- El frontend no tiene runner de tests. Se verifica con `npx tsc --noEmit -p tsconfig.json` y en el navegador.
- Comando de la suite backend (los cuatro `--ignore` son por un paquete `google.genai` ausente en el entorno de desarrollo, no por este trabajo):
  ```bash
  py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
  ```
  Línea base al escribir este plan: **529 passed**.

## Estructura de archivos

**Backend_RRHH** (`C:\Users\Emiliano\Documents\Backend_RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `app/services/bajas.py` | **Nuevo.** Reglas puras: catálogo de motivos, `baja_vigente`, `antiguedad_en_anios`, `a_date`. Sin base. |
| `app/database/bajas.py` | **Nuevo.** Todo el SQL de bajas: DDL, lecturas, escrituras y los efectos colaterales. |
| `app/permisos.py` | Suma el recorte puro `recortar_por_baja`. |
| `app/database/permissions.py` | Suma `permisos_efectivos`, que junta rol y recorte. |
| `app/auth_middleware.py` | Pasa a usar `permisos_efectivos`. |
| `app/routes/auth.py` | Ídem, en la respuesta del login. |
| `app/routes/rrhh.py` | Los cuatro endpoints de baja; al final pierde los de jubilación. |
| `app/routes/licenses.py` | Corte de vacaciones por fecha de baja + guard de `_sync_employee_status`. |
| `app/services/asistencia_recalc.py` | Corte del rango de asistencia por fecha de baja. |
| `app/scheduler.py` | El tick diario aplica efectos de bajas cumplidas. |
| `app/main.py` | `ensure_table` de `EmployeeBaja` en el startup. |
| `app/services/jubilacion.py`, `app/database/jubilacion.py` | **Se eliminan** en la última tarea. |

**RRHH** (`C:\Users\Emiliano\Documents\RRHH`)

| Archivo | Responsabilidad |
|---|---|
| `src/app/Interfas/Interfaces.ts` | `EmpleadoBaja` y `MotivoBaja` reemplazan `EmpleadoJubilado`. |
| `src/app/Componentes/TablaOperador/BajasTable.tsx` | **Nuevo**, reemplaza `JubiladosTable.tsx`: tablero con desglose por motivo. |
| `src/app/Componentes/TablaOperador/BajaModal.tsx` | **Nuevo.** Modal de confirmación de baja, corrección y reincorporación. |
| `src/app/Componentes/TablaOperador/DetailTables.tsx` | Pierde el campo de fecha de jubilación; gana la acción de baja. |
| `src/app/Componentes/TablaOperador/Table.tsx`, `src/app/screens/RRHH/Screen.tsx` | Renombre de la vista y del botón. |
| `src/app/Componentes/Shell/AppHeader.tsx` | Gatea por permiso los ítems del menú de perfil. |

---

## Task 1: Reglas puras de la baja

**Files:**
- Create: `app/services/bajas.py`
- Test: `tests/test_bajas.py`

**Interfaces:**
- Consumes: nada.
- Produces: `MOTIVOS_DE_BAJA: tuple[str, ...]`; `a_date(valor) -> date | None`; `baja_vigente(bajas: list[dict], hoy: date) -> dict | None`; `antiguedad_en_anios(fecha_ingreso, fecha_hasta) -> float | None`. Las bajas son dicts con al menos las claves `fechaBaja` y `fechaReingreso`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_bajas.py`:

```python
"""
Reglas puras de la baja, sin base ni TestClient.

baja_vigente es la definicion unica de "esta de baja": la usan el recorte de
permisos, el job diario y los dos cortes de computo.
"""

from datetime import date, datetime

from app.services.bajas import (
    MOTIVOS_DE_BAJA, a_date, antiguedad_en_anios, baja_vigente,
)

HOY = date(2026, 9, 17)


def _baja(fecha_baja, fecha_reingreso=None, motivo="Renuncia"):
    return {"motivo": motivo, "fechaBaja": fecha_baja,
            "fechaReingreso": fecha_reingreso}


def test_el_catalogo_tiene_los_siete_motivos_acordados():
    assert MOTIVOS_DE_BAJA == (
        "Jubilación", "Renuncia", "Despido", "Fin de contrato",
        "Fallecimiento", "Traslado a otro organismo", "Abandono de cargo",
    )


def test_sin_bajas_no_esta_de_baja():
    assert baja_vigente([], HOY) is None


def test_una_baja_cumplida_esta_vigente():
    b = _baja(date(2026, 9, 1))
    assert baja_vigente([b], HOY) is b


def test_la_baja_de_hoy_ya_esta_vigente():
    b = _baja(HOY)
    assert baja_vigente([b], HOY) is b


def test_una_baja_futura_todavia_no_tiene_efecto():
    """Se carga cuando se sabe; la persona sigue trabajando hasta ese dia."""
    assert baja_vigente([_baja(date(2026, 12, 1))], HOY) is None


def test_una_baja_con_reingreso_ya_no_tiene_efecto():
    """La persona volvio: la fila queda en el historial pero no recorta nada."""
    b = _baja(date(2025, 3, 1), fecha_reingreso=date(2026, 1, 10))
    assert baja_vigente([b], HOY) is None


def test_entre_una_cerrada_y_una_abierta_gana_la_abierta():
    cerrada = _baja(date(2024, 2, 1), fecha_reingreso=date(2024, 8, 1))
    abierta = _baja(date(2026, 5, 1))
    assert baja_vigente([cerrada, abierta], HOY) is abierta


def test_con_varias_abiertas_gana_la_mas_reciente():
    """El endpoint no permite dos abiertas, pero la regla no depende de eso."""
    vieja = _baja(date(2020, 1, 1))
    nueva = _baja(date(2026, 1, 1))
    assert baja_vigente([vieja, nueva], HOY) is nueva


def test_acepta_datetime_de_pyodbc():
    """pyodbc devuelve datetime donde el esquema dice DATE."""
    b = _baja(datetime(2026, 9, 1, 0, 0))
    assert baja_vigente([b], HOY) is b


def test_a_date_normaliza_datetime_a_date():
    assert a_date(datetime(2026, 9, 1, 13, 45)) == date(2026, 9, 1)


def test_a_date_deja_pasar_un_date():
    assert a_date(date(2026, 9, 1)) == date(2026, 9, 1)


def test_a_date_de_none_es_none():
    assert a_date(None) is None


def test_antiguedad_cuenta_los_anios_entre_ingreso_y_baja():
    assert antiguedad_en_anios(date(2016, 9, 1), date(2026, 9, 1)) == 10.0


def test_antiguedad_con_un_decimal():
    assert antiguedad_en_anios(date(2024, 3, 1), date(2026, 9, 1)) == 2.5


def test_antiguedad_sin_ingreso_es_none():
    """No se inventa un cero, que se leeria como 'entro y se fue el mismo dia'."""
    assert antiguedad_en_anios(None, date(2026, 9, 1)) is None


def test_antiguedad_con_baja_anterior_al_ingreso_es_none():
    assert antiguedad_en_anios(date(2026, 9, 1), date(2020, 1, 1)) is None
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `py -m pytest tests/test_bajas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.bajas'`

- [ ] **Step 3: Escribir la implementación**

Crear `app/services/bajas.py`:

```python
"""
Reglas de la baja que no tocan la base.

Vive aparte del SQL para poder testear las condiciones sin base ni
TestClient. baja_vigente es la definicion unica de "esta de baja", y la
comparten el recorte de permisos, el job diario y los dos cortes de computo
(vacaciones y asistencia): una sola regla para todos los caminos.
"""

from datetime import date, datetime
from typing import Optional

# Cerrado a proposito. Las estadisticas del tablero se leen sobre estas
# categorias, asi que tienen que ser estables y comparables entre anios;
# agregar un motivo es una linea aca y un deploy.
MOTIVOS_DE_BAJA: tuple[str, ...] = (
    "Jubilación",
    "Renuncia",
    "Despido",
    "Fin de contrato",
    "Fallecimiento",
    "Traslado a otro organismo",
    "Abandono de cargo",
)


def a_date(valor) -> Optional[date]:
    """
    Normaliza lo que devuelve pyodbc a un date limpio.

    datetime hereda de date, asi que hay que chequear el tipo mas especifico
    primero: el guard invertido ya rompio una vez en este repo.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor).split("T")[0])


def baja_vigente(bajas: list[dict], hoy: date) -> Optional[dict]:
    """
    La baja que hoy tiene efecto, o None.

    Dos casos no tienen efecto. Una baja con fechaReingreso: la persona
    volvio, y la fila queda solo como historial. Y una fechaBaja futura: RRHH
    la carga cuando la sabe y la persona sigue trabajando hasta ese dia.

    Si hubiera mas de una abierta -que el endpoint no permite- gana la mas
    reciente, para que el corte no dependa del orden en que vino la lista.
    """
    vigentes = []
    for b in bajas:
        if b.get("fechaReingreso") is not None:
            continue
        fecha = a_date(b.get("fechaBaja"))
        if fecha is not None and fecha <= hoy:
            vigentes.append((fecha, b))
    if not vigentes:
        return None
    return max(vigentes, key=lambda par: par[0])[1]


def antiguedad_en_anios(fecha_ingreso, fecha_hasta) -> Optional[float]:
    """
    Anios trabajados entre las dos fechas, con un decimal.

    None cuando falta alguna de las dos o cuando la baja es anterior al
    ingreso: no se devuelve cero, que en el tablero se leeria como "entro y se
    fue el mismo dia" en vez de "no sabemos".
    """
    ingreso = a_date(fecha_ingreso)
    hasta = a_date(fecha_hasta)
    if ingreso is None or hasta is None or hasta < ingreso:
        return None
    meses = (hasta.year - ingreso.year) * 12 + hasta.month - ingreso.month
    return round(meses / 12.0, 1)
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `py -m pytest tests/test_bajas.py -q`
Expected: `17 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/bajas.py tests/test_bajas.py
git commit -m "feat(bajas): reglas puras de la baja y catalogo de motivos"
```

---

## Task 2: Persistencia de bajas

**Files:**
- Create: `app/database/bajas.py`
- Modify: `app/main.py` (startup, después de `ensure_columnas_exencion(db)`)
- Test: `tests/test_bajas_db.py`

**Interfaces:**
- Consumes: de `app/services/bajas.py`: `a_date`, `baja_vigente`.
- Produces:
  - `ensure_table(db) -> None`
  - `bajas_de_empleado(db, employee_id: int) -> list[dict]`
  - `registrar_baja(db, employee_id: int, motivo: str, fecha: date, observaciones: str | None, registrada_por: int | None, hoy: date) -> dict`
  - `borrar_baja(db, employee_id: int) -> bool`
  - `reincorporar(db, employee_id: int, fecha_reingreso: date) -> bool`
  - `aplicar_efectos(db, employee_id: int) -> None`
  - `bajas_para_tablero(db, hoy: date) -> list[dict]`
  - `pendientes_de_aplicar(db, hoy: date) -> list[int]`

  Las filas de `bajas_para_tablero` tienen: `id`, `employeeId`, `name`, `dni`, `email`, `photo`, `departamento`, `oficina`, `tipoContrato`, `motivo`, `fechaIngreso`, `fechaBaja`, `fechaReingreso`, `observaciones`, `antiguedadAnios`, `saldoFinal`, `estado` (uno de `"vigente"`, `"reincorporada"`, `"programada"`).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_bajas_db.py`:

```python
"""
Capa de persistencia de bajas, con FakeSession.

Ninguna base real se toca: FakeSession mapea fragmentos de SQL a filas y
guarda lo que se intento ejecutar.
"""

from datetime import date

from app.database.bajas import (
    aplicar_efectos, bajas_de_empleado, bajas_para_tablero, borrar_baja,
    pendientes_de_aplicar, registrar_baja, reincorporar,
)
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_bajas_de_empleado_devuelve_las_filas_como_dicts():
    db = FakeSession({"FROM EmployeeBaja": [
        {"id": 1, "employeeId": 8, "motivo": "Renuncia",
         "fechaBaja": date(2026, 9, 1), "observaciones": None,
         "fechaReingreso": None, "registradaPor": 3,
         "createdAt": date(2026, 9, 1)},
    ]})
    filas = bajas_de_empleado(db, 8)
    assert len(filas) == 1
    assert filas[0]["motivo"] == "Renuncia"


def test_bajas_de_empleado_pasa_el_id_como_bind():
    db = FakeSession({"FROM EmployeeBaja": []})
    bajas_de_empleado(db, 8)
    _sql, params = db.ejecutadas[0]
    assert params == {"id": 8}


def test_registrar_una_baja_cumplida_aplica_los_efectos():
    db = FakeSession({"INSERT INTO EmployeeBaja": [(55,)]})
    resultado = registrar_baja(db, 8, "Renuncia", date(2026, 9, 1),
                               "Resolucion 120/26", 3, HOY)
    assert resultado["vigente"] is True
    sql = db.sql_ejecutado()
    assert "UPDATE Employee SET status" in sql
    assert "UPDATE License" in sql


def test_registrar_una_baja_futura_no_aplica_efectos_todavia():
    """Se guarda, pero la persona sigue operando hasta que llegue el dia."""
    db = FakeSession({"INSERT INTO EmployeeBaja": [(56,)]})
    resultado = registrar_baja(db, 8, "Renuncia", date(2026, 12, 1),
                               None, 3, HOY)
    assert resultado["vigente"] is False
    assert "UPDATE Employee SET status" not in db.sql_ejecutado()


def test_registrar_nunca_toca_user_activo():
    """El bloqueo de cuenta es del panel de ADMIN y no se mezcla con la baja."""
    db = FakeSession({"INSERT INTO EmployeeBaja": [(57,)]})
    registrar_baja(db, 8, "Despido", date(2026, 9, 1), None, 3, HOY)
    assert "[User]" not in db.sql_ejecutado()


def test_aplicar_efectos_cancela_las_pendientes_y_limpia_la_cola():
    """Sin el UPDATE de Aprobaciones la solicitud sigue en la cola del jefe."""
    db = FakeSession()
    aplicar_efectos(db, 8)
    sql = db.sql_ejecutado()
    assert "UPDATE License" in sql
    assert "'Rechazada'" in sql
    assert "UPDATE Aprobaciones" in sql


def test_borrar_baja_devuelve_true_cuando_borro_algo_y_reactiva():
    db = FakeSession({"DELETE FROM EmployeeBaja": [{"id": 1}]})
    assert borrar_baja(db, 8) is True
    assert "UPDATE Employee SET status" in db.sql_ejecutado()


def test_borrar_baja_sin_fila_abierta_devuelve_false():
    db = FakeSession({"DELETE FROM EmployeeBaja": []})
    assert borrar_baja(db, 8) is False


def test_reincorporar_escribe_la_fecha_y_reactiva():
    db = FakeSession({"UPDATE EmployeeBaja": [{"id": 1}]})
    assert reincorporar(db, 8, date(2026, 10, 1)) is True
    sql = db.sql_ejecutado()
    assert "fechaReingreso" in sql
    assert "UPDATE Employee SET status" in sql


def test_reincorporar_sin_baja_abierta_devuelve_false():
    db = FakeSession({"UPDATE EmployeeBaja": []})
    assert reincorporar(db, 8, date(2026, 10, 1)) is False


def test_el_tablero_clasifica_los_tres_estados():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "Vigente", "dni": "1", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Renuncia",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2026, 9, 1), "fechaReingreso": None,
         "saldoFinal": 0},
        {"id": 2, "employeeId": 9, "name": "Volvio", "dni": "2", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Renuncia",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2024, 9, 1), "fechaReingreso": date(2025, 1, 1),
         "saldoFinal": 0},
        {"id": 3, "employeeId": 10, "name": "Futura", "dni": "3", "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": "permanente", "motivo": "Jubilación",
         "observaciones": None, "fechaIngreso": date(2016, 9, 1),
         "fechaBaja": date(2026, 12, 1), "fechaReingreso": None,
         "saldoFinal": 0},
    ]})
    filas = bajas_para_tablero(db, HOY)
    assert [f["estado"] for f in filas] == ["vigente", "reincorporada", "programada"]


def test_el_tablero_calcula_la_antiguedad_al_irse():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "X", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 9, 1), "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None, "saldoFinal": 0},
    ]})
    assert bajas_para_tablero(db, HOY)[0]["antiguedadAnios"] == 10.0


def test_pendientes_de_aplicar_devuelve_los_ids():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"employeeId": 8}, {"employeeId": 9},
    ]})
    assert pendientes_de_aplicar(db, HOY) == [8, 9]
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `py -m pytest tests/test_bajas_db.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.database.bajas'`

- [ ] **Step 3: Escribir la implementación**

Crear `app/database/bajas.py`:

```python
"""
Persistencia de las bajas de empleados.

La tabla EmployeeBaja es la fuente de verdad. Employee.status es cache
cosmetico para los listados que ya muestran esa columna: la condicion real se
calcula con baja_vigente cada vez que se usa, asi que el cache no puede
desincronizar nada importante.

User.activo NO se toca en ningun camino de este modulo. Ese campo es el
bloqueo de cuenta del panel de ADMIN, que es un caso distinto: el dado de baja
conserva el acceso, recortado a su legajo.
"""

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.bajas import a_date, antiguedad_en_anios, baja_vigente

ESTADO_BAJA = "Baja"
ESTADO_ACTIVO = "Activo"

CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT * FROM sysobjects WHERE name = 'EmployeeBaja' AND xtype = 'U'
)
BEGIN
    CREATE TABLE EmployeeBaja (
        id             INT IDENTITY(1,1) PRIMARY KEY,
        employeeId     INT            NOT NULL,
        motivo         NVARCHAR(50)   NOT NULL,
        fechaBaja      DATE           NOT NULL,
        observaciones  NVARCHAR(500)  NULL,
        fechaReingreso DATE           NULL,
        registradaPor  INT            NULL,
        createdAt      DATETIME2      NOT NULL
    );
    CREATE INDEX IX_EmployeeBaja_employeeId ON EmployeeBaja (employeeId);
END
"""


def ensure_table(db: Session) -> None:
    """
    DDL idempotente de EmployeeBaja.

    Se llama en el startup de la app, no en los endpoints: bajas_de_empleado
    corre en CADA request autenticado (el recorte de permisos), y meter DDL en
    ese camino seria pagar una verificacion de esquema por request.
    """
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def bajas_de_empleado(db: Session, employee_id: int) -> list[dict]:
    """
    Todas las bajas de una persona, de la mas nueva a la mas vieja.

    Devuelve el historial completo, no solo la vigente: quien decide cual
    aplica es baja_vigente, que es una regla pura y testeable aparte.
    """
    filas = db.execute(text("""
        SELECT id, employeeId, motivo, fechaBaja, observaciones,
               fechaReingreso, registradaPor, createdAt
        FROM EmployeeBaja
        WHERE employeeId = :id
        ORDER BY fechaBaja DESC
    """), {"id": employee_id}).mappings().all()
    return [dict(f) for f in filas]


def _marcar_estado(db: Session, employee_id: int, estado: str) -> None:
    """Escribe el cache cosmetico de Employee.status."""
    db.execute(text("UPDATE Employee SET status = :e, updatedAt = GETDATE() "
                    "WHERE id = :id"), {"e": estado, "id": employee_id})


def aplicar_efectos(db: Session, employee_id: int) -> None:
    """
    Los efectos colaterales de una baja que ya tiene efecto.

    Cancela las solicitudes de licencia sin resolver y marca el cache de
    estado. No hace commit: el llamador decide la transaccion.

    Las dos sentencias de cancelacion son necesarias. License.status es lo que
    ve la persona, pero la cola del supervisor se arma leyendo Aprobaciones
    con accion pendiente: sin el segundo UPDATE la solicitud le seguiria
    apareciendo para aprobar. Se actualiza la fila que ya existe en vez de
    insertar una nueva, porque supervisorId es NOT NULL y el sistema no es un
    supervisor: la fila pendiente ya trae el suyo.
    """
    db.execute(text("""
        UPDATE License
        SET status = 'Rechazada', updatedAt = GETDATE()
        WHERE employeeId = :id
          AND status IN ('Pendiente', 'Pendiente Siguiente Aprobación')
    """), {"id": employee_id})

    db.execute(text("""
        UPDATE Aprobaciones
        SET accion = 'Rechazada',
            observacion = 'Cancelada automáticamente por la baja del empleado',
            fecha = GETDATE(), updatedAt = GETDATE()
        WHERE accion IN ('Pendiente', 'Pendiente Siguiente Aprobación')
          AND licenseId IN (SELECT id FROM License WHERE employeeId = :id)
    """), {"id": employee_id})

    _marcar_estado(db, employee_id, ESTADO_BAJA)


def registrar_baja(db: Session, employee_id: int, motivo: str, fecha: date,
                   observaciones: Optional[str], registrada_por: Optional[int],
                   hoy: date) -> dict:
    """
    Inserta la baja y, si ya tiene efecto, aplica sus consecuencias.

    Una fecha futura se guarda sin aplicar nada: el tick diario la aplica
    cuando llegue el dia. El recorte de accesos no depende de ese tick, porque
    se calcula con la fecha en cada request.

    Todo va en una transaccion: una baja registrada sin sus efectos dejaria
    solicitudes pendientes de alguien que ya no trabaja.
    """
    fila = db.execute(text("""
        INSERT INTO EmployeeBaja
            (employeeId, motivo, fechaBaja, observaciones, registradaPor, createdAt)
        OUTPUT INSERTED.id
        VALUES (:id, :motivo, :fecha, :obs, :por, GETDATE())
    """), {"id": employee_id, "motivo": motivo, "fecha": fecha,
           "obs": observaciones, "por": registrada_por}).fetchone()

    vigente = fecha <= hoy
    if vigente:
        aplicar_efectos(db, employee_id)

    db.commit()
    return {"id": int(fila[0]) if fila else None, "vigente": vigente}


def borrar_baja(db: Session, employee_id: int) -> bool:
    """
    Corrige un error de carga: borra la baja abierta como si nunca existiera.

    Devuelve False si no habia ninguna abierta. Las solicitudes canceladas no
    se resucitan -ver el spec-: volver a la cola una licencia rechazada
    semanas antes confundiria mas que pedirla de nuevo.
    """
    res = db.execute(text("""
        DELETE FROM EmployeeBaja
        WHERE employeeId = :id AND fechaReingreso IS NULL
    """), {"id": employee_id})

    if res.rowcount == 0:
        return False

    _marcar_estado(db, employee_id, ESTADO_ACTIVO)
    db.commit()
    return True


def reincorporar(db: Session, employee_id: int, fecha_reingreso: date) -> bool:
    """
    Cierra la baja abierta dejandola en el historial.

    Devuelve False si no habia ninguna abierta.
    """
    res = db.execute(text("""
        UPDATE EmployeeBaja
        SET fechaReingreso = :fecha
        WHERE employeeId = :id AND fechaReingreso IS NULL
    """), {"fecha": fecha_reingreso, "id": employee_id})

    if res.rowcount == 0:
        return False

    _marcar_estado(db, employee_id, ESTADO_ACTIVO)
    db.commit()
    return True


def baja_vigente_de(db: Session, employee_id: int, hoy: date) -> Optional[dict]:
    """La baja con efecto hoy para esta persona, o None."""
    return baja_vigente(bajas_de_empleado(db, employee_id), hoy)


def fecha_de_corte(db: Session, employee_id: int, hoy: date) -> Optional[date]:
    """
    Hasta cuando computarle a esta persona, o None si sigue trabajando.

    Es la fecha de la baja vigente, sea cual sea el motivo: quien se fue deja
    de acumular vacaciones y de generar jornadas. Lo consumen
    calcular_dias_vacaciones y rango_de_calculo.
    """
    baja = baja_vigente_de(db, employee_id, hoy)
    return a_date(baja["fechaBaja"]) if baja else None


def bajas_para_tablero(db: Session, hoy: date) -> list[dict]:
    """
    Todas las bajas registradas, con los datos del empleado para el tablero.

    Trae las tres clases -vigente, reincorporada y programada- porque las
    programadas son el unico lugar donde RRHH puede ver y corregir una baja
    cargada con preaviso antes de que llegue el dia.

    El saldo de asistencia no es una columna: es la suma de los dias. Mismo
    calculo que saldo_acumulado() en app/database/asistencia.py.
    """
    filas = db.execute(text("""
        SELECT b.id, b.employeeId, b.motivo, b.fechaBaja, b.fechaReingreso,
               b.observaciones,
               e.name, e.dni, e.email, e.photo,
               d.nombre AS departamento, o.nombre AS oficina,
               c.tipoContrato, c.fechaIngreso,
               (SELECT COALESCE(SUM(j.saldoDia), 0) FROM JornadaDiaria j
                WHERE j.employeeId = e.id) AS saldoFinal
        FROM EmployeeBaja b
        JOIN Employee e ON e.id = b.employeeId
        LEFT JOIN Department d ON e.departmentId = d.id
        LEFT JOIN Office o ON e.officeId = o.id
        LEFT JOIN (
            SELECT employeeId, MIN(fechaIngreso) AS fechaIngreso,
                   MAX(tipoContrato) AS tipoContrato
            FROM CondicionLaboral GROUP BY employeeId
        ) c ON c.employeeId = e.id
        ORDER BY b.fechaBaja DESC, e.name ASC
    """)).mappings().all()

    resultado = []
    for f in filas:
        fecha_baja = a_date(f["fechaBaja"])
        reingreso = a_date(f["fechaReingreso"])
        if reingreso is not None:
            estado = "reincorporada"
        elif fecha_baja is not None and fecha_baja > hoy:
            estado = "programada"
        else:
            estado = "vigente"

        resultado.append({
            "id": int(f["id"]),
            "employeeId": int(f["employeeId"]),
            "name": f["name"],
            "dni": f["dni"],
            "email": f["email"],
            "photo": f["photo"],
            "departamento": f["departamento"],
            "oficina": f["oficina"],
            "tipoContrato": f["tipoContrato"],
            "motivo": f["motivo"],
            "observaciones": f["observaciones"],
            "fechaIngreso": a_date(f["fechaIngreso"]).isoformat()
                            if f["fechaIngreso"] else None,
            "fechaBaja": fecha_baja.isoformat() if fecha_baja else None,
            "fechaReingreso": reingreso.isoformat() if reingreso else None,
            "antiguedadAnios": antiguedad_en_anios(f["fechaIngreso"], fecha_baja),
            "saldoFinal": float(f["saldoFinal"]) if f["saldoFinal"] is not None else 0.0,
            "estado": estado,
        })
    return resultado


def pendientes_de_aplicar(db: Session, hoy: date) -> list[int]:
    """
    Empleados con baja ya cumplida que todavia figuran activos en el cache.

    Es lo que consume el tick diario para aplicar los efectos colaterales de
    las bajas programadas. El corte de accesos no lo necesita: se calcula.
    """
    filas = db.execute(text("""
        SELECT DISTINCT b.employeeId
        FROM EmployeeBaja b
        JOIN Employee e ON e.id = b.employeeId
        WHERE b.fechaReingreso IS NULL
          AND b.fechaBaja <= :hoy
          AND e.status <> :baja
    """), {"hoy": hoy, "baja": ESTADO_BAJA}).mappings().all()
    return [int(f["employeeId"]) for f in filas]
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `py -m pytest tests/test_bajas_db.py -q`
Expected: `13 passed`

- [ ] **Step 5: Crear la tabla en el startup**

En `app/main.py`, agregar el import junto a los otros de `app.database`:

```python
from app.database.bajas import ensure_table as ensure_tabla_bajas
```

Y en `startup()`, inmediatamente después de `ensure_columnas_exencion(db)` y su `print`:

```python
        ensure_tabla_bajas(db)
        print("[OK] tabla EmployeeBaja verificada")
```

- [ ] **Step 6: Correr la suite completa**

Run:
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `559 passed` (529 de base + 17 de Task 1 + 13 de esta)

- [ ] **Step 7: Commit**

```bash
git add app/database/bajas.py app/main.py tests/test_bajas_db.py
git commit -m "feat(bajas): persistencia de EmployeeBaja con sus efectos colaterales"
```

---

## Task 3: El recorte de permisos

**Files:**
- Modify: `app/permisos.py` (al final del archivo, después de `tiene_permiso`)
- Modify: `app/database/permissions.py` (después de `permisos_de_rol`, línea 136)
- Modify: `app/auth_middleware.py:115`
- Modify: `app/routes/auth.py:84`
- Test: `tests/test_recorte_por_baja.py`

**Interfaces:**
- Consumes: de `app/database/bajas.py`: `bajas_de_empleado`; de `app/services/bajas.py`: `baja_vigente`.
- Produces: `PERMISO_DE_BAJA: str`; `recortar_por_baja(permisos: set[str], de_baja: bool) -> set[str]`; `permisos_efectivos(db, role_id: int | None, employee_id: int | None, hoy: date | None = None) -> set[str]`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_recorte_por_baja.py`:

```python
"""
El recorte de permisos del dado de baja.

La parte pura -que devuelve exactamente un permiso- se testea sola. La parte
que junta rol y recorte va con FakeSession.
"""

from datetime import date

from app.database.permissions import permisos_efectivos
from app.permisos import COMODIN, recortar_por_baja
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_sin_baja_los_permisos_pasan_intactos():
    permisos = {"inicio.ver", "licencias.propias"}
    assert recortar_por_baja(permisos, de_baja=False) == permisos


def test_con_baja_queda_solo_el_legajo():
    permisos = {"inicio.ver", "licencias.propias", "documentos.propios",
                "asistencia.propia", "feedback.participar", "perfil.editar"}
    assert recortar_por_baja(permisos, de_baja=True) == {"documentos.propios"}


def test_el_recorte_tambien_alcanza_al_comodin_de_admin():
    """La baja no depende del rol de quien se fue: el comodin no la esquiva."""
    assert recortar_por_baja({COMODIN}, de_baja=True) == {"documentos.propios"}


def test_el_recorte_deja_el_permiso_aunque_el_rol_no_lo_tuviera():
    """Un rol sin documentos.propios igual conserva su legajo al darse de baja."""
    assert recortar_por_baja({"estadisticas.ver"}, de_baja=True) == {"documentos.propios"}


def _db(permisos_del_rol, bajas):
    return FakeSession({
        "FROM AuthRolePermission": [{"code": c} for c in permisos_del_rol],
        "FROM EmployeeBaja": bajas,
    })


def test_permisos_efectivos_sin_baja_devuelve_los_del_rol():
    db = _db(["inicio.ver", "licencias.propias"], [])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver", "licencias.propias"}


def test_permisos_efectivos_con_baja_vigente_recorta():
    db = _db(["inicio.ver", "licencias.propias"],
             [{"fechaBaja": date(2026, 9, 1), "fechaReingreso": None}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"documentos.propios"}


def test_permisos_efectivos_con_baja_futura_no_recorta():
    db = _db(["inicio.ver"],
             [{"fechaBaja": date(2026, 12, 1), "fechaReingreso": None}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver"}


def test_permisos_efectivos_con_baja_reincorporada_no_recorta():
    db = _db(["inicio.ver"],
             [{"fechaBaja": date(2024, 1, 1), "fechaReingreso": date(2025, 1, 1)}])
    assert permisos_efectivos(db, 2, 8, HOY) == {"inicio.ver"}


def test_permisos_efectivos_sin_employee_id_no_consulta_bajas():
    """Una cuenta sin empleado asociado no puede estar de baja."""
    db = _db(["admin.gestionar"], [])
    assert permisos_efectivos(db, 1, None, HOY) == {"admin.gestionar"}
    assert "EmployeeBaja" not in db.sql_ejecutado()
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `py -m pytest tests/test_recorte_por_baja.py -q`
Expected: FAIL con `ImportError: cannot import name 'recortar_por_baja'`

- [ ] **Step 3: Escribir el recorte puro**

Al final de `app/permisos.py`:

```python
# Lo unico que conserva un empleado dado de baja: su legajo a la vista.
PERMISO_DE_BAJA = "documentos.propios"


def recortar_por_baja(permisos: set[str], de_baja: bool) -> set[str]:
    """
    Los permisos que quedan cuando alguien esta dado de baja.

    Devuelve el permiso del legajo y nada mas, sin mirar lo que traia el rol.
    Ignora el comodin de ADMIN a proposito: la baja la decide RRHH sobre una
    persona, y no tendria sentido que el rol que tenia al irse le devolviera
    accesos. Tampoco exige que el rol tuviera el permiso: el legajo es de la
    persona, no del rol.
    """
    if not de_baja:
        return permisos
    return {PERMISO_DE_BAJA}
```

- [ ] **Step 4: Escribir los permisos efectivos**

En `app/database/permissions.py`, agregar a los imports del módulo:

```python
from datetime import date

from app.database.bajas import bajas_de_empleado
from app.permisos import recortar_por_baja
from app.services.bajas import baja_vigente
```

Y después de `permisos_de_rol`:

```python
def permisos_efectivos(db: Session, role_id: int | None,
                       employee_id: int | None,
                       hoy: date | None = None) -> set[str]:
    """
    Los permisos con los que realmente opera alguien: los del rol, recortados
    si esta de baja.

    La tienen que usar TODOS los que resuelven permisos. Hoy son dos: el
    middleware en cada request y la respuesta del login, que el frontend
    guarda en localStorage. Si solo recortara el middleware, el dado de baja
    recibiria el menu completo al loguearse y lo veria hasta la proxima
    recarga.

    Suma una consulta por request, indexada por employeeId sobre una tabla
    chica. Se elige eso antes que cachear el estado en el token: un cache
    dejaria a alguien operando con los permisos de antes hasta que expire, que
    es exactamente el modo de falla que este diseno evita.
    """
    permisos = permisos_de_rol(db, role_id)
    if employee_id is None:
        return permisos
    bajas = bajas_de_empleado(db, employee_id)
    de_baja = baja_vigente(bajas, hoy or date.today()) is not None
    return recortar_por_baja(permisos, de_baja)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `py -m pytest tests/test_recorte_por_baja.py -q`
Expected: `9 passed`

- [ ] **Step 6: Cablear el middleware**

En `app/auth_middleware.py`, cambiar el import de la línea 27:

```python
from app.database.permissions import permisos_efectivos
```

Y en el `return` de `get_current_user` (línea 115), cambiar:

```python
        "permisos":   permisos_de_rol(db, role_id),
```

por:

```python
        "permisos":   permisos_efectivos(db, role_id, employee_id),
```

- [ ] **Step 7: Cablear el login**

En `app/routes/auth.py`, cambiar el import de la línea 18:

```python
from app.database.permissions import permisos_efectivos
```

Y la línea 84:

```python
    permisos = permisos_efectivos(db, resultado.roleId, resultado.employeeId)
```

- [ ] **Step 8: Correr la suite completa**

Run:
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `568 passed`. Si algún test de `test_auth_endpoint_permisos.py` o `test_auth_permisos.py` falla porque su `FakeSession` no responde el fragmento `FROM EmployeeBaja`, agregarle `"FROM EmployeeBaja": []` al diccionario de respuestas: sin baja, los permisos pasan intactos y la aserción original sigue valiendo.

- [ ] **Step 9: Commit**

```bash
git add app/permisos.py app/database/permissions.py app/auth_middleware.py app/routes/auth.py tests/test_recorte_por_baja.py
git commit -m "feat(bajas): el dado de baja opera solo con documentos.propios"
```

---

## Task 4: Endpoints de baja

**Files:**
- Modify: `app/routes/rrhh.py` (nuevos endpoints al final del archivo; los de jubilación quedan intactos hasta Task 9)
- Test: `tests/test_bajas_endpoints.py`

**Interfaces:**
- Consumes: de `app/database/bajas.py`: `bajas_para_tablero`, `baja_vigente_de`, `borrar_baja`, `registrar_baja`, `reincorporar`; de `app/services/bajas.py`: `MOTIVOS_DE_BAJA`, `a_date`.
- Produces: `post_baja`, `delete_baja`, `put_reincorporacion`, `get_bajas` (funciones del router, testeables llamándolas directo); `MOTIVOS_DE_BAJA` se expone en `GET /rrhh/bajas` bajo la clave `motivos`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_bajas_endpoints.py`:

```python
"""
Los endpoints de baja, llamados directo con FakeSession.

No se levanta TestClient: las dependencias de permiso se declaran en el
decorador y no corren cuando se invoca la funcion a mano, que es justo lo que
permite testear la logica del endpoint sin token.
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.routes.rrhh import delete_baja, get_bajas, post_baja, put_reincorporacion
from tests.fakes import FakeSession

USUARIO_RRHH = {"employeeId": 3, "permisos": {"rrhh.gestionar"}}


def _db(extra=None):
    """Empleado existente, no ADMIN, sin bajas previas."""
    respuestas = {
        "SELECT id FROM Employee": [{"id": 8}],
        "FROM EmployeeBaja": [],
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 0}],
        "INSERT INTO EmployeeBaja": [(55,)],
    }
    respuestas.update(extra or {})
    return FakeSession(respuestas)


def test_registra_la_baja_y_devuelve_el_motivo_y_la_fecha():
    resultado = post_baja(
        8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01",
            "observaciones": "Resolución 120/26"},
        db=_db(), user=USUARIO_RRHH,
    )
    assert resultado["motivo"] == "Renuncia"
    assert resultado["fechaBaja"] == "2026-09-01"
    assert resultado["vigente"] is True


def test_rechaza_un_motivo_fuera_del_catalogo():
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Se fue nomás", "fechaBaja": "2026-09-01"},
                  db=_db(), user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "motivo" in str(e.value.detail).lower()


def test_rechaza_una_fecha_mal_formada():
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "01/09/2026"},
                  db=_db(), user=USUARIO_RRHH)
    assert e.value.status_code == 400


def test_rechaza_si_el_empleado_no_existe():
    db = _db({"SELECT id FROM Employee": []})
    with pytest.raises(HTTPException) as e:
        post_baja(99, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 404


def test_rechaza_una_segunda_baja_abierta():
    db = _db({"FROM EmployeeBaja": [
        {"fechaBaja": date(2026, 1, 1), "fechaReingreso": None},
    ]})
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "ya" in str(e.value.detail).lower()


def test_rechaza_la_baja_del_ultimo_admin():
    """Sin esto quedaria un sistema sin nadie que pueda administrarlo ni
    revertir la baja, y habria que arreglarlo a mano en la base."""
    db = _db({
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 1}],
        "u.employeeId <> :id": [{"n": 0}],
    })
    with pytest.raises(HTTPException) as e:
        post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01"},
                  db=db, user=USUARIO_RRHH)
    assert e.value.status_code == 400
    assert "ADMIN" in str(e.value.detail)


def test_permite_la_baja_de_un_admin_si_queda_otro():
    db = _db({
        "r.name = 'ADMIN' AND u.employeeId = :id": [{"n": 1}],
        "u.employeeId <> :id": [{"n": 2}],
    })
    resultado = post_baja(8, {"motivo": "Jubilación", "fechaBaja": "2026-09-01"},
                          db=db, user=USUARIO_RRHH)
    assert resultado["vigente"] is True


def test_la_baja_registra_quien_la_cargo_desde_el_token():
    """La firma tiene que ser de quien la hizo, no de lo que diga el payload."""
    db = _db()
    post_baja(8, {"motivo": "Renuncia", "fechaBaja": "2026-09-01",
                  "registradaPor": 999},
              db=db, user=USUARIO_RRHH)
    insert = next(p for sql, p in db.ejecutadas if "INSERT INTO EmployeeBaja" in sql)
    assert insert["por"] == 3


def test_borrar_sin_baja_abierta_da_404():
    db = FakeSession({"DELETE FROM EmployeeBaja": []})
    with pytest.raises(HTTPException) as e:
        delete_baja(8, db=db)
    assert e.value.status_code == 404


def test_reincorporar_rechaza_una_fecha_anterior_a_la_baja():
    db = FakeSession({"FROM EmployeeBaja": [
        {"fechaBaja": date(2026, 9, 1), "fechaReingreso": None},
    ]})
    with pytest.raises(HTTPException) as e:
        put_reincorporacion(8, {"fechaReingreso": "2026-08-01"}, db=db)
    assert e.value.status_code == 400


def test_reincorporar_sin_baja_abierta_da_404():
    db = FakeSession({"FROM EmployeeBaja": []})
    with pytest.raises(HTTPException) as e:
        put_reincorporacion(8, {"fechaReingreso": "2026-10-01"}, db=db)
    assert e.value.status_code == 404


def test_el_tablero_devuelve_las_bajas_el_conteo_y_el_catalogo():
    db = FakeSession({"FROM EmployeeBaja b": [
        {"id": 1, "employeeId": 8, "name": "A", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 1, 1), "fechaBaja": date(2026, 9, 1),
         "fechaReingreso": None, "saldoFinal": 0},
        {"id": 2, "employeeId": 9, "name": "B", "dni": None, "email": None,
         "photo": None, "departamento": None, "oficina": None,
         "tipoContrato": None, "motivo": "Renuncia", "observaciones": None,
         "fechaIngreso": date(2016, 1, 1), "fechaBaja": date(2026, 12, 1),
         "fechaReingreso": None, "saldoFinal": 0},
    ]})
    resultado = get_bajas(db=db)
    assert len(resultado["bajas"]) == 2
    assert resultado["motivos"][0] == "Jubilación"
    # La programada no se cuenta: todavia puede cancelarse.
    assert resultado["porMotivo"]["Renuncia"] == 1


def test_el_conteo_por_motivo_arranca_en_cero_para_todos_los_motivos():
    db = FakeSession({"FROM EmployeeBaja b": []})
    resultado = get_bajas(db=db)
    assert resultado["porMotivo"] == {
        "Jubilación": 0, "Renuncia": 0, "Despido": 0, "Fin de contrato": 0,
        "Fallecimiento": 0, "Traslado a otro organismo": 0,
        "Abandono de cargo": 0,
    }
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `py -m pytest tests/test_bajas_endpoints.py -q`
Expected: FAIL con `ImportError: cannot import name 'post_baja'`

- [ ] **Step 3: Escribir los endpoints**

En `app/routes/rrhh.py`, agregar a los imports:

```python
from app.auth_middleware import get_current_user, require_permission
from app.database.bajas import (
    baja_vigente_de, bajas_para_tablero, borrar_baja, registrar_baja,
    reincorporar,
)
from app.services.bajas import MOTIVOS_DE_BAJA, a_date
```

> Nota: `require_permission` ya está importado en ese archivo; sumar solo `get_current_user` a esa línea.

Y al final del archivo:

```python
# ---------------------------------------------------------------------------
# Bajas de empleados
# ---------------------------------------------------------------------------
def _es_admin(db: Session, employee_id: int) -> bool:
    fila = db.execute(text("""
        SELECT COUNT(*) AS n
        FROM [User] u JOIN Role r ON r.id = u.roleId
        WHERE r.name = 'ADMIN' AND u.employeeId = :id
    """), {"id": employee_id}).mappings().first()
    return bool(fila and fila["n"])


def _quedan_otros_admin(db: Session, employee_id: int, hoy: date) -> bool:
    """
    Si hay algun otro ADMIN operativo aparte de este empleado.

    Una cuenta ADMIN sin empleado asociado -el admin de sistema- cuenta como
    otro: no se le puede dar de baja, asi que siempre queda disponible.
    """
    fila = db.execute(text("""
        SELECT COUNT(*) AS n
        FROM [User] u JOIN Role r ON r.id = u.roleId
        WHERE r.name = 'ADMIN'
          AND (u.employeeId IS NULL OR u.employeeId <> :id)
          AND (u.employeeId IS NULL OR u.employeeId NOT IN (
                SELECT employeeId FROM EmployeeBaja
                WHERE fechaReingreso IS NULL AND fechaBaja <= :hoy))
    """), {"id": employee_id, "hoy": hoy}).mappings().first()
    return bool(fila and fila["n"])


def _fecha_del_payload(data: dict, clave: str) -> date:
    crudo = data.get(clave)
    if not crudo:
        raise HTTPException(status_code=400, detail=f"Falta {clave}")
    try:
        return date.fromisoformat(str(crudo).split("T")[0])
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"{clave} debe ser YYYY-MM-DD")


@router.post("/employee/{employee_id}/baja",
             dependencies=[Depends(require_permission("rrhh.gestionar"))])
def post_baja(employee_id: int, data: dict = Body(...),
              db: Session = Depends(get_db),
              user: dict = Depends(get_current_user)):
    """
    Da de baja a un empleado.

    Endpoint propio y no un campo mas de condicion-laboral: aquel actualiza
    datos descriptivos, este le recorta a una persona todo el sistema menos su
    legajo y le cancela las solicitudes pendientes.

    La cuenta NO se bloquea: el dado de baja sigue entrando y viendo sus
    documentos. Bloquear el acceso es otra cosa y vive en el panel de ADMIN.
    """
    hoy = date.today()

    if db.execute(text("SELECT id FROM Employee WHERE id = :id"),
                  {"id": employee_id}).first() is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    motivo = data.get("motivo")
    if motivo not in MOTIVOS_DE_BAJA:
        raise HTTPException(
            status_code=400,
            detail=f"El motivo de baja debe ser uno de: {', '.join(MOTIVOS_DE_BAJA)}")

    fecha = _fecha_del_payload(data, "fechaBaja")

    if baja_vigente_de(db, employee_id, hoy) is not None:
        raise HTTPException(
            status_code=400,
            detail="Esta persona ya tiene una baja vigente. Corregila o "
                   "reincorporala antes de registrar otra.")

    if _es_admin(db, employee_id) and not _quedan_otros_admin(db, employee_id, hoy):
        raise HTTPException(
            status_code=400,
            detail="Es el último usuario ADMIN activo: si se da de baja nadie "
                   "podría administrar el sistema ni revertir esta baja. "
                   "Cambiale el rol desde el panel de administración primero.")

    # registradaPor sale del token y no del payload: esto mueve accesos, asi
    # que la firma tiene que ser de quien efectivamente lo hizo.
    resultado = registrar_baja(
        db, employee_id, motivo, fecha, data.get("observaciones"),
        user.get("employeeId"), hoy,
    )
    return {
        "employeeId": employee_id,
        "motivo": motivo,
        "fechaBaja": fecha.isoformat(),
        "vigente": resultado["vigente"],
    }


@router.delete("/employee/{employee_id}/baja",
               dependencies=[Depends(require_permission("rrhh.gestionar"))])
def delete_baja(employee_id: int, db: Session = Depends(get_db)):
    """
    Corrige un error de carga: borra la baja como si nunca hubiera existido.

    Es distinto de reincorporar. Aca no queda rastro, justamente para que un
    error de tipeo no ensucie las estadisticas del tablero.
    """
    if not borrar_baja(db, employee_id):
        raise HTTPException(status_code=404,
                            detail="Esta persona no tiene una baja abierta")
    return {"employeeId": employee_id, "baja": None}


@router.put("/employee/{employee_id}/reincorporacion",
            dependencies=[Depends(require_permission("rrhh.gestionar"))])
def put_reincorporacion(employee_id: int, data: dict = Body(...),
                        db: Session = Depends(get_db)):
    """
    Cierra la baja: la persona volvio a trabajar y recupera sus permisos.

    La baja queda en el historial con su fecha de reingreso, porque paso de
    verdad y el tablero la tiene que poder mostrar.
    """
    fecha = _fecha_del_payload(data, "fechaReingreso")

    baja = baja_vigente_de(db, employee_id, date.today())
    if baja is None:
        raise HTTPException(status_code=404,
                            detail="Esta persona no tiene una baja vigente")

    fecha_baja = a_date(baja["fechaBaja"])
    if fecha_baja is not None and fecha < fecha_baja:
        raise HTTPException(
            status_code=400,
            detail=f"El reingreso no puede ser anterior a la baja "
                   f"({fecha_baja.isoformat()})")

    reincorporar(db, employee_id, fecha)
    return {"employeeId": employee_id, "fechaReingreso": fecha.isoformat()}


@router.get("/bajas", dependencies=[Depends(require_permission("rrhh.gestionar"))])
def get_bajas(db: Session = Depends(get_db)):
    """
    El tablero de bajas: todas las registradas y el desglose por motivo.

    Incluye las programadas -fecha futura, sin efecto todavia- porque es el
    unico lugar donde RRHH puede verlas y corregirlas antes de que lleguen. El
    conteo por motivo las excluye: todavia pueden cancelarse y contarlas
    inflaria la estadistica.

    El conteo arranca en cero para los siete motivos, asi el frontend no tiene
    que saber el catalogo para dibujar el desglose.
    """
    hoy = date.today()
    filas = bajas_para_tablero(db, hoy)

    por_motivo = {motivo: 0 for motivo in MOTIVOS_DE_BAJA}
    for f in filas:
        if f["estado"] != "programada" and f["motivo"] in por_motivo:
            por_motivo[f["motivo"]] += 1

    return {"bajas": filas, "porMotivo": por_motivo,
            "motivos": list(MOTIVOS_DE_BAJA)}
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `py -m pytest tests/test_bajas_endpoints.py -q`
Expected: `13 passed`

- [ ] **Step 5: Correr la suite completa**

Run:
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `581 passed`

- [ ] **Step 6: Commit**

```bash
git add app/routes/rrhh.py tests/test_bajas_endpoints.py
git commit -m "feat(bajas): endpoints de alta, correccion, reincorporacion y tablero"
```

---

## Task 5: La fecha de corte pasa a ser la de la baja

**Files:**
- Modify: `app/routes/licenses.py:107` (query de `tipos_disponibles_de`), `:216`, `:774`, `:888`, `:1009-1029` (`_sync_employee_status`)
- Modify: `app/services/asistencia_recalc.py:44-60` (`_datos_empleado`), `:165-190` (`rango_de_calculo`), `:201` (llamada)
- Test: `tests/test_corte_por_baja.py`

**Interfaces:**
- Consumes: de `app/database/bajas.py`: `fecha_de_corte`, `ESTADO_BAJA`.
- Produces: `rango_de_calculo(anio, inicio_modulo, fecha_ingreso, fecha_baja, hoy)` con el cuarto parámetro renombrado; `_sync_employee_status` no pisa estados terminales.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_corte_por_baja.py`:

```python
"""
La fecha de baja como cota superior de los computos.

Antes esta cota era la fecha de jubilacion y solo aplicaba a ese motivo: a
quien renunciaba le seguian creciendo las vacaciones y el saldo de asistencia
para siempre. Ahora el corte lo pone cualquier baja.
"""

from datetime import date

from app.routes.licenses import _sync_employee_status, calcular_dias_vacaciones
from app.services.asistencia_recalc import rango_de_calculo
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)
INICIO_MODULO = date(2026, 1, 1)


def test_sin_baja_las_vacaciones_cuentan_hasta_hoy():
    sin_corte = calcular_dias_vacaciones("permanente", date(2010, 1, 1), None)
    assert sin_corte > 0


def test_una_renuncia_congela_la_antiguedad_de_vacaciones():
    """El mismo empleado, medido al dia que se fue, no sigue acumulando."""
    al_irse = calcular_dias_vacaciones("permanente", date(2010, 1, 1),
                                       date(2015, 1, 1))
    hasta_hoy = calcular_dias_vacaciones("permanente", date(2010, 1, 1), None)
    assert al_irse < hasta_hoy


def test_la_baja_corta_el_rango_de_asistencia():
    rango = rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1),
                             date(2026, 3, 10), HOY)
    assert rango == (INICIO_MODULO, date(2026, 3, 10))


def test_sin_baja_el_rango_llega_hasta_hoy():
    rango = rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1), None, HOY)
    assert rango == (INICIO_MODULO, HOY)


def test_una_baja_anterior_al_inicio_del_modulo_no_da_rango():
    assert rango_de_calculo(2026, INICIO_MODULO, date(2020, 1, 1),
                            date(2025, 6, 1), HOY) is None


def test_el_sync_de_status_no_pisa_una_baja():
    """Aprobar una licencia no puede devolver a Activo a quien esta de baja.

    Es el bug que ya tenia el jubilado: _sync_employee_status escribia Activo
    o Licencia sin mirar lo que habia."""
    db = FakeSession({"SELECT status FROM Employee": [{"status": "Baja"}]})
    _sync_employee_status(db, 8)
    assert "UPDATE Employee SET status" not in db.sql_ejecutado()


def test_el_sync_de_status_sigue_funcionando_para_un_activo():
    db = FakeSession({
        "SELECT status FROM Employee": [{"status": "Activo"}],
        "SELECT id FROM License": [],
    })
    _sync_employee_status(db, 8)
    assert "UPDATE Employee SET status" in db.sql_ejecutado()
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `py -m pytest tests/test_corte_por_baja.py -q`
Expected: FAIL — `test_el_sync_de_status_no_pisa_una_baja` falla porque hoy el UPDATE se ejecuta siempre

- [ ] **Step 3: Poner el guard en `_sync_employee_status`**

En `app/routes/licenses.py`, reemplazar el cuerpo de `_sync_employee_status` (líneas 1009-1029) por:

```python
def _sync_employee_status(db: Session, employee_id: int):
    """
    Compara la fecha actual con las licencias aprobadas del empleado.
    - Si hoy esta dentro del rango de alguna licencia aprobada → 'Licencia'
    - Si no hay ninguna licencia activa hoy → 'Activo'

    No toca los estados terminales. Sin este guard, aprobar una licencia le
    devolvia el estado 'Activo' a alguien dado de baja, porque el UPDATE se
    escribia sin mirar lo que habia: el mismo bug que ya le pisaba el
    'Jubilado' al jubilado.
    """
    actual = db.execute(text("SELECT status FROM Employee WHERE id = :empId"),
                        {"empId": employee_id}).mappings().first()
    if actual and actual["status"] in ESTADOS_TERMINALES:
        return

    active_lic = db.execute(text("""
        SELECT id FROM License
        WHERE employeeId = :empId
          AND status = 'Aprobada'
          AND CAST(startDate AS DATE) <= CAST(GETDATE() AS DATE)
          AND CAST(endDate AS DATE) >= CAST(GETDATE() AS DATE)
    """), {"empId": employee_id}).first()

    new_status = "Licencia" if active_lic else "Activo"
    db.execute(text("""
        UPDATE Employee SET status = :status, updatedAt = GETDATE() WHERE id = :empId
    """), {"status": new_status, "empId": employee_id})
```

Y agregar arriba, junto a las otras constantes del módulo:

```python
# Estados que no se recalculan a partir de las licencias: los pone la baja y
# solo ella los saca.
ESTADOS_TERMINALES = frozenset({"Baja"})
```

- [ ] **Step 4: Cambiar el corte de vacaciones**

En `app/routes/licenses.py`, agregar al bloque de imports:

```python
from app.database.bajas import fecha_de_corte
```

Quitar `cl.fechaJubilacion, ` de la query de la línea 107 y `fechaJubilacion` de la de la línea 774 (dejando `SELECT tipoContrato, fechaIngreso`).

En la línea 216, reemplazar:

```python
                emp_data.get("fechaJubilacion"),
```

por:

```python
                fecha_de_corte(db, employee_id, today),
```

En la línea 888, reemplazar:

```python
        tipo_contrato, fecha_ingreso, cl.get("fechaJubilacion"),
```

por:

```python
        tipo_contrato, fecha_ingreso, fecha_de_corte(db, employee_id, today),
```

- [ ] **Step 5: Cambiar el corte de asistencia**

En `app/services/asistencia_recalc.py`, reemplazar la query de `_datos_empleado` (líneas 45-59) por:

```python
    fila = db.execute(text("""
        SELECT e.id, e.biometricoId,
               h.horaInicio, h.horaFin, h.horasTrabajo,
               c.fechaIngreso,
               (SELECT MAX(b.fechaBaja) FROM EmployeeBaja b
                WHERE b.employeeId = e.id AND b.fechaReingreso IS NULL
                  AND b.fechaBaja <= CAST(GETDATE() AS DATE)) AS fechaBaja
        FROM Employee e
        LEFT JOIN Horario h ON e.cronogramaId = h.id
        LEFT JOIN (
            SELECT employeeId, MIN(fechaIngreso) AS fechaIngreso
            FROM CondicionLaboral
            GROUP BY employeeId
        ) c ON c.employeeId = e.id
        WHERE e.id = :id
    """), {"id": employee_id}).mappings().first()
```

En `rango_de_calculo` (líneas 165-190), renombrar el parámetro y actualizar el docstring:

```python
def rango_de_calculo(anio: int, inicio_modulo: date,
                     fecha_ingreso: Optional[date],
                     fecha_baja: Optional[date],
                     hoy: date) -> Optional[tuple[date, date]]:
    """
    Los dias a calcular para un empleado en un anio, o None si no hay ninguno.

    Cuatro fechas lo acotan. Por abajo, el inicio del modulo y el ingreso del
    empleado. Por arriba, el fin del anio, hoy y la baja.

    La baja es el espejo exacto del ingreso: por eso el saldo de quien se fue
    se congela sin ningun caso especial, simplemente deja de haber dias que
    calcular despues de su fecha. Aplica a cualquier motivo, no solo a la
    jubilacion.
    """
    desde = max(date(anio, 1, 1), inicio_modulo)
    ingreso = _a_date(fecha_ingreso)
    if ingreso is not None:
        desde = max(desde, ingreso)

    hasta = min(date(anio, 12, 31), hoy)
    baja = _a_date(fecha_baja)
    if baja is not None:
        hasta = min(hasta, baja)

    if desde > hasta:
        return None
```

Y en la llamada de la línea 201:

```python
        emp.get("fechaIngreso"), emp.get("fechaBaja"), date.today(),
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `py -m pytest tests/test_corte_por_baja.py -q`
Expected: `7 passed`

- [ ] **Step 7: Adaptar los tests de jubilación que ejercen el rango**

En `tests/test_jubilacion.py`, los nueve tests de `rango_de_calculo` siguen valiendo: la regla no cambió, solo el nombre del parámetro, que es posicional en todas las llamadas. Correr:

Run: `py -m pytest tests/test_jubilacion.py -q`
Expected: `14 passed` sin cambios en el archivo

- [ ] **Step 8: Correr la suite completa**

Run:
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `588 passed`. Si algún test de licencias falla por el fragmento `FROM EmployeeBaja` sin respuesta en su `FakeSession`, agregarle `"FROM EmployeeBaja": []`: sin baja, `fecha_de_corte` devuelve `None`, que es el comportamiento que esos tests ya esperaban.

- [ ] **Step 9: Commit**

```bash
git add app/routes/licenses.py app/services/asistencia_recalc.py tests/test_corte_por_baja.py
git commit -m "feat(bajas): la fecha de baja congela vacaciones y asistencia, sea el motivo que sea"
```

---

## Task 6: Tablero de bajas

**Files:**
- Create: `src/app/Componentes/TablaOperador/BajasTable.tsx` (repo `RRHH`)
- Delete: `src/app/Componentes/TablaOperador/JubiladosTable.tsx`
- Modify: `src/app/Interfas/Interfaces.ts:1265-1278`, `src/app/Componentes/TablaOperador/Table.tsx:14,18,37,183,186`, `src/app/screens/RRHH/Screen.tsx:8,26,149-151,163`

**Interfaces:**
- Consumes: `GET /rrhh/bajas` → `{ bajas: EmpleadoBaja[], porMotivo: Record<string, number>, motivos: string[] }`.
- Produces: `EmpleadoBaja` y `MotivoBaja` en `Interfaces.ts`; componente `BajasTable` con prop `{ onVolver: () => void }`.

**Nota de diseño del desglose.** Es una comparación de magnitud de una sola serie (cantidad de bajas) sobre categorías ya rotuladas en texto, así que va como barras horizontales de **un solo tono** (`var(--primary)`), no con una paleta categórica: el color no tiene que distinguir nada que el rótulo no distinga ya. Por eso no hace falta validar separación de pares. El número va como etiqueta directa en cada fila —no hay tooltip porque repetiría un dato ya visible— y el texto usa los tokens de texto del proyecto, nunca el color de la barra. La interacción es clic para filtrar la tabla. Los motivos en cero no se dibujan, para que el bloque no sean siete filas vacías.

- [ ] **Step 1: Actualizar las interfaces**

En `src/app/Interfas/Interfaces.ts`, reemplazar el bloque `EmpleadoJubilado` (líneas 1265-1278) por:

```typescript
export type MotivoBaja =
  | 'Jubilación'
  | 'Renuncia'
  | 'Despido'
  | 'Fin de contrato'
  | 'Fallecimiento'
  | 'Traslado a otro organismo'
  | 'Abandono de cargo';

/** Estado de una baja: si tiene efecto hoy, si la persona volvió, o si está
 *  cargada con fecha futura y todavía no aplica. */
export type EstadoBaja = 'vigente' | 'reincorporada' | 'programada';

/** Fila del tablero de bajas. Cada fila es un evento de baja, no una persona:
 *  quien se fue, volvió y se fue de nuevo aparece dos veces. */
export interface EmpleadoBaja {
  id: number;
  employeeId: number;
  name: string;
  dni: string | null;
  email: string | null;
  photo: string | null;
  departamento: string | null;
  oficina: string | null;
  tipoContrato: string | null;
  motivo: MotivoBaja;
  observaciones: string | null;
  fechaIngreso: string | null;
  fechaBaja: string | null;
  fechaReingreso: string | null;
  antiguedadAnios: number | null;
  saldoFinal: number;
  estado: EstadoBaja;
}
```

- [ ] **Step 2: Crear el tablero**

Crear `src/app/Componentes/TablaOperador/BajasTable.tsx`:

```tsx
"use client";

// Tablero de bajas de la institución, en la pantalla Lista de Empleados.
//
// Cada fila es un evento de baja, no una persona. La lista es histórica a
// propósito: incluye las reincorporaciones (pasaron de verdad) y las
// programadas, que son el único lugar donde RRHH puede ver y corregir una baja
// cargada con preaviso antes de que llegue el día.

import { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/app/util/apiClient";
import { EmpleadoBaja } from "@/app/Interfas/Interfaces";

interface Props {
  onVolver: () => void;
}

interface Respuesta {
  bajas: EmpleadoBaja[];
  porMotivo: Record<string, number>;
  motivos: string[];
}

const ETIQUETA_ESTADO: Record<EmpleadoBaja["estado"], string> = {
  vigente: "Vigente",
  reincorporada: "Reincorporado",
  programada: "Programada",
};

export default function BajasTable({ onVolver }: Props) {
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [motivoFiltro, setMotivoFiltro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    (async () => {
      try {
        const r = await apiClient.get<Respuesta>("/rrhh/bajas");
        if (!cancelado) {
          setDatos(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelado) {
          setError(e instanceof Error ? e.message : "No se pudieron cargar las bajas");
        }
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, []);

  const bajas = datos?.bajas ?? [];

  const filtradas = useMemo(
    () =>
      bajas.filter(
        (b) =>
          (motivoFiltro === null || b.motivo === motivoFiltro) &&
          (b.name.toLowerCase().includes(busqueda.toLowerCase()) ||
            (b.dni ?? "").includes(busqueda)),
      ),
    [bajas, busqueda, motivoFiltro],
  );

  // Solo los motivos que ocurrieron: siete filas donde cinco son cero no
  // informa nada y ocupa toda la pantalla.
  const desglose = useMemo(() => {
    const conteos = datos?.porMotivo ?? {};
    const conDatos = Object.entries(conteos).filter(([, n]) => n > 0);
    const mayor = conDatos.reduce((max, [, n]) => Math.max(max, n), 0);
    return { filas: conDatos, mayor };
  }, [datos]);

  const total = desglose.filas.reduce((acc, [, n]) => acc + n, 0);

  if (cargando) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        <i className="pi pi-spin pi-spinner text-2xl mb-2" />
        <p>Cargando bajas…</p>
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
          <h2 className="font-heading text-xl text-foreground">Bajas</h2>
          <p className="text-sm text-muted-foreground">
            {total} baja{total === 1 ? "" : "s"} registrada
            {total === 1 ? "" : "s"}. El saldo de cada persona quedó congelado
            en su último día.
          </p>
        </div>
        <button
          onClick={onVolver}
          className="px-4 py-2 rounded-lg bg-muted text-foreground text-sm hover:opacity-90"
        >
          Volver al tablero
        </button>
      </div>

      {desglose.filas.length > 0 && (
        <div className="bg-card rounded-lg border border-border p-4">
          <h3 className="text-sm font-semibold text-foreground mb-3">
            Bajas por motivo
          </h3>
          <div className="space-y-2">
            {desglose.filas.map(([motivo, n]) => {
              const activo = motivoFiltro === motivo;
              return (
                <button
                  key={motivo}
                  onClick={() => setMotivoFiltro(activo ? null : motivo)}
                  aria-pressed={activo}
                  className={`w-full grid grid-cols-[11rem_1fr_2.5rem] items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted ${
                    activo ? "bg-muted" : ""
                  }`}
                >
                  <span className="text-sm text-foreground truncate">{motivo}</span>
                  <span className="h-2 w-full bg-muted rounded-full overflow-hidden">
                    <span
                      className="block h-full rounded-full"
                      style={{
                        width: `${desglose.mayor > 0 ? (n / desglose.mayor) * 100 : 0}%`,
                        backgroundColor: "var(--primary)",
                      }}
                    />
                  </span>
                  <span className="text-sm text-muted-foreground text-right tabular-nums">
                    {n}
                  </span>
                </button>
              );
            })}
          </div>
          {motivoFiltro && (
            <p className="text-xs text-muted-foreground mt-3">
              Mostrando solo {motivoFiltro}. Volvé a hacer clic para ver todas.
            </p>
          )}
        </div>
      )}

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
              <th className="py-3 px-4">Motivo</th>
              <th className="py-3 px-4">Baja</th>
              <th className="py-3 px-4">Antigüedad</th>
              <th className="py-3 px-4">Estado</th>
              <th className="py-3 px-4 text-right">Saldo final</th>
            </tr>
          </thead>
          <tbody>
            {filtradas.map((b) => (
              <tr key={b.id} className="border-b border-border last:border-0">
                <td className="py-3 px-4 text-foreground">{b.name}</td>
                <td className="py-3 px-4 text-muted-foreground">{b.dni ?? "—"}</td>
                <td className="py-3 px-4 text-muted-foreground">
                  {b.departamento ?? "—"}
                </td>
                <td className="py-3 px-4 text-foreground">{b.motivo}</td>
                <td className="py-3 px-4 text-muted-foreground">
                  {b.fechaBaja ?? "—"}
                </td>
                <td className="py-3 px-4 text-muted-foreground tabular-nums">
                  {b.antiguedadAnios !== null ? `${b.antiguedadAnios} años` : "—"}
                </td>
                <td className="py-3 px-4 text-muted-foreground">
                  {ETIQUETA_ESTADO[b.estado]}
                  {b.estado === "reincorporada" && b.fechaReingreso
                    ? ` el ${b.fechaReingreso}`
                    : ""}
                </td>
                <td
                  className={`py-3 px-4 text-right font-semibold tabular-nums ${
                    b.saldoFinal < 0 ? "text-error" : "text-foreground"
                  }`}
                >
                  {b.saldoFinal.toFixed(2)} hs
                </td>
              </tr>
            ))}
            {filtradas.length === 0 && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-muted-foreground">
                  {bajas.length === 0
                    ? "No hay bajas registradas."
                    : "Ninguna baja coincide con el filtro."}
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

- [ ] **Step 3: Cablear la pantalla de RRHH**

En `src/app/screens/RRHH/Screen.tsx`:
- Línea 8: `import BajasTable from "@/app/Componentes/TablaOperador/BajasTable";`
- Línea 26: `name: "table" | "detail" | "messages" | "bajas";`
- Líneas 149-151: `case "bajas":` con `<BajasTable onVolver={() => setCurrentView({ name: "table" })} />`
- Línea 163: `onShowBajas={() => setCurrentView({ name: "bajas" })}`

En `src/app/Componentes/TablaOperador/Table.tsx`:
- Línea 14: `onShowBajas: () => void;`
- Línea 18: `name: 'table' | 'detail' | 'messages' | 'bajas';`
- Línea 37: `onShowBajas,`
- Línea 183: `onClick={onShowBajas}`
- Línea 186: el texto del botón pasa a `Ver bajas`

- [ ] **Step 4: Borrar el tablero viejo**

```bash
git rm src/app/Componentes/TablaOperador/JubiladosTable.tsx
```

- [ ] **Step 5: Verificar tipos**

Run (en `C:\Users\Emiliano\Documents\RRHH`): `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "BajasTable|Jubilad|RRHH/Screen|TablaOperador/Table"`
Expected: sin salida. Los errores preexistentes en otros archivos (`Productivity.tsx`, `data-grouping.ts`, `SoftSkill`, etc.) no son de este trabajo y quedan como están.

- [ ] **Step 6: Verificar en el navegador**

Levantar el preview, entrar como RRHH a Lista de Empleados y abrir "Ver bajas". Confirmar que la tabla carga, que el desglose por motivo aparece solo con los motivos que tienen bajas, y que hacer clic en un motivo filtra la tabla y volver a hacer clic la desfiltra. Revisar la consola del navegador: sin errores.

- [ ] **Step 7: Commit**

```bash
git add src/app/Componentes/TablaOperador/BajasTable.tsx src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/Table.tsx src/app/screens/RRHH/Screen.tsx
git commit -m "feat(bajas): tablero de bajas con desglose por motivo"
```

---

## Task 7: La acción de baja en el perfil del empleado

**Files:**
- Create: `src/app/Componentes/TablaOperador/BajaModal.tsx` (repo `RRHH`)
- Modify: `src/app/Componentes/TablaOperador/DetailTables.tsx:67-68` (`retirementDate`), `:174-178` (el PUT de jubilación), `:361-378` (el `InfoCard`)

**Interfaces:**
- Consumes: `POST /rrhh/employee/{id}/baja` con `{ motivo, fechaBaja, observaciones }`; `DELETE /rrhh/employee/{id}/baja`; `PUT /rrhh/employee/{id}/reincorporacion` con `{ fechaReingreso }`. `MotivoBaja` de `Interfaces.ts`.
- Produces: componente `BajaModal` con props `{ employeeId: number; employeeName: string; bajaVigente: { motivo: string; fechaBaja: string } | null; onClose: () => void; onHecho: () => void }`.

- [ ] **Step 1: Crear el modal**

Crear `src/app/Componentes/TablaOperador/BajaModal.tsx`:

```tsx
"use client";

// Dar de baja a un empleado, corregir el error de carga o reincorporarlo.
//
// Va como acción propia y no como un campo más del formulario de condición
// laboral: aquel edita datos descriptivos, esto le recorta a una persona todo
// el sistema menos su legajo y le cancela las solicitudes pendientes. Por eso
// el modal enumera las consecuencias antes de confirmar.

import { useRef, useState } from "react";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { Calendar } from "primereact/calendar";
import { InputTextarea } from "primereact/inputtextarea";
import { Button } from "primereact/button";
import { Toast } from "primereact/toast";
import { apiClient } from "@/app/util/apiClient";
import { MotivoBaja } from "@/app/Interfas/Interfaces";

const MOTIVOS: MotivoBaja[] = [
  "Jubilación",
  "Renuncia",
  "Despido",
  "Fin de contrato",
  "Fallecimiento",
  "Traslado a otro organismo",
  "Abandono de cargo",
];

interface Props {
  employeeId: number;
  employeeName: string;
  bajaVigente: { motivo: string; fechaBaja: string } | null;
  onClose: () => void;
  onHecho: () => void;
}

const aISO = (d: Date) => d.toISOString().split("T")[0];

export default function BajaModal({
  employeeId,
  employeeName,
  bajaVigente,
  onClose,
  onHecho,
}: Props) {
  const [motivo, setMotivo] = useState<MotivoBaja | null>(null);
  const [fecha, setFecha] = useState<Date | null>(new Date());
  const [observaciones, setObservaciones] = useState("");
  const [enviando, setEnviando] = useState(false);
  const toast = useRef<Toast>(null);

  const fallar = (e: unknown) =>
    toast.current?.show({
      severity: "error",
      summary: "Error",
      detail: e instanceof Error ? e.message : "No se pudo completar la acción",
      life: 6000,
    });

  const darDeBaja = async () => {
    if (!motivo || !fecha) {
      toast.current?.show({
        severity: "warn",
        summary: "Faltan datos",
        detail: "Elegí el motivo y la fecha.",
        life: 4000,
      });
      return;
    }
    setEnviando(true);
    try {
      await apiClient.post(`/rrhh/employee/${employeeId}/baja`, {
        motivo,
        fechaBaja: aISO(fecha),
        observaciones: observaciones || null,
      });
      onHecho();
      onClose();
    } catch (e) {
      fallar(e);
    } finally {
      setEnviando(false);
    }
  };

  const corregir = async () => {
    setEnviando(true);
    try {
      await apiClient.delete(`/rrhh/employee/${employeeId}/baja`);
      onHecho();
      onClose();
    } catch (e) {
      fallar(e);
    } finally {
      setEnviando(false);
    }
  };

  const reincorporar = async () => {
    if (!fecha) return;
    setEnviando(true);
    try {
      await apiClient.put(`/rrhh/employee/${employeeId}/reincorporacion`, {
        fechaReingreso: aISO(fecha),
      });
      onHecho();
      onClose();
    } catch (e) {
      fallar(e);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <>
      <Toast ref={toast} />
      <Dialog
        header={bajaVigente ? "Baja registrada" : "Dar de baja"}
        visible
        style={{ width: "90vw", maxWidth: "540px" }}
        onHide={onClose}
      >
        {bajaVigente ? (
          <div className="space-y-4">
            <p className="text-sm text-foreground">
              <strong>{employeeName}</strong> está de baja por{" "}
              <strong>{bajaVigente.motivo}</strong> desde el{" "}
              {bajaVigente.fechaBaja}.
            </p>
            <div>
              <label className="block text-sm font-semibold mb-1">
                Fecha de reingreso
              </label>
              <Calendar
                value={fecha}
                onChange={(e) => setFecha(e.value as Date)}
                dateFormat="yy-mm-dd"
                className="w-full"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Reincorporar le devuelve todos sus permisos. La baja queda en el
                historial con esta fecha.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 pt-2">
              <Button
                label="Reincorporar"
                onClick={reincorporar}
                disabled={enviando}
              />
              <Button
                label="Corregir (fue un error)"
                severity="secondary"
                outlined
                onClick={corregir}
                disabled={enviando}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Corregir borra la baja como si nunca se hubiera cargado, así no
              queda contada en las estadísticas. Las solicitudes de licencia que
              se cancelaron no se recuperan: hay que pedirlas de nuevo.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold mb-1">Motivo</label>
              <Dropdown
                value={motivo}
                onChange={(e) => setMotivo(e.value)}
                options={MOTIVOS}
                placeholder="Elegí el motivo…"
                className="w-full"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1">
                Fecha de baja
              </label>
              <Calendar
                value={fecha}
                onChange={(e) => setFecha(e.value as Date)}
                dateFormat="yy-mm-dd"
                className="w-full"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Puede ser pasada, para regularizar el legajo, o futura: en ese
                caso queda programada y aplica sola ese día.
              </p>
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1">
                Observaciones
              </label>
              <InputTextarea
                value={observaciones}
                onChange={(e) => setObservaciones(e.target.value)}
                rows={2}
                maxLength={500}
                placeholder="Número de resolución, por ejemplo"
                className="w-full"
              />
            </div>
            <div className="rounded-lg border border-border bg-muted p-3">
              <p className="text-xs text-foreground font-semibold mb-1">
                Al aplicarse, {employeeName}:
              </p>
              <ul className="text-xs text-muted-foreground space-y-0.5 list-disc pl-4">
                <li>conserva su cuenta y puede seguir entrando</li>
                <li>solo ve su documentación: pierde inicio, CV, asistencia, licencias y encuesta</li>
                <li>deja de acumular vacaciones y saldo de asistencia</li>
                <li>pierde las solicitudes de licencia que tenga sin resolver</li>
              </ul>
            </div>
            <div className="flex gap-3 pt-2">
              <Button label="Dar de baja" onClick={darDeBaja} disabled={enviando} />
              <Button
                label="Cancelar"
                severity="secondary"
                outlined
                onClick={onClose}
                disabled={enviando}
              />
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
```

- [ ] **Step 2: Quitar el campo de jubilación del formulario**

En `src/app/Componentes/TablaOperador/DetailTables.tsx`:

Borrar las líneas 67-68 (`retirementDate` del estado inicial del formulario) y el `InfoCard` completo de "Fecha de Jubilación" (líneas 361-378, hasta su `</InfoCard>`).

Borrar el PUT de jubilación del guardado (líneas 174-178):

```typescript
      await apiClient.put(`/rrhh/employee/${employee.id}/jubilacion`, {
        fechaJubilacion: formData.retirementDate
          ? formData.retirementDate.toISOString().split('T')[0]
          : null,
      });
```

Buscar y borrar cualquier otra referencia a `retirementDate` en el archivo:

```bash
grep -n "retirementDate" src/app/Componentes/TablaOperador/DetailTables.tsx
```

- [ ] **Step 3: Agregar la acción de baja**

En `DetailTables.tsx`, importar el modal y la interfaz:

```typescript
import BajaModal from './BajaModal';
```

Agregar el estado junto a los otros `useState` del componente:

```typescript
  const [mostrarBaja, setMostrarBaja] = useState(false);
```

Y en el encabezado del detalle, junto a los otros botones de acción, el disparador y el render del modal:

```tsx
        <Button
          label={employee.baja ? 'Ver baja' : 'Dar de baja'}
          icon="pi pi-user-minus"
          severity="danger"
          outlined
          className="p-button-sm"
          onClick={() => setMostrarBaja(true)}
        />

        {mostrarBaja && (
          <BajaModal
            employeeId={employee.id}
            employeeName={employee.name}
            bajaVigente={employee.baja ?? null}
            onClose={() => setMostrarBaja(false)}
            onHecho={() => void onSave?.()}
          />
        )}
```

- [ ] **Step 4: Exponer la baja vigente en el detalle del empleado**

Para que el modal sepa si ya hay una baja, el backend tiene que informarla. En `app/routes/rrhh.py` (repo `Backend_RRHH`), en el diccionario de respuesta del detalle del empleado, reemplazar la clave `"fechaJubilacion"` del bloque `condicionLaboral` (línea 409) por una clave `baja` al nivel del empleado:

```python
            "baja": (lambda b: {
                "motivo": b["motivo"],
                "fechaBaja": a_date(b["fechaBaja"]).isoformat(),
            } if b else None)(baja_vigente_de(db, emp["id"], date.today())),
```

Y quitar `c.fechaJubilacion AS condicion_fechaJubilacion,` de la query (línea 139).

En `src/app/Interfas/Interfaces.ts` (repo `RRHH`), agregar al interface `Employee`:

```typescript
  /** La baja vigente de esta persona, o null si sigue trabajando. */
  baja?: { motivo: string; fechaBaja: string } | null;
```

Y quitar `fechaJubilacion` del interface `CondicionLaboral`.

- [ ] **Step 5: Verificar tipos en los dos repos**

Run (en `Backend_RRHH`):
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `588 passed`

Run (en `RRHH`): `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -iE "BajaModal|DetailTables|retirementDate|fechaJubilacion"`
Expected: sin salida

- [ ] **Step 6: Verificar en el navegador**

Como RRHH, abrir el perfil de un empleado de prueba y darlo de baja con motivo "Renuncia" y fecha de hoy. Confirmar que el modal lista las consecuencias, que la baja se guarda, que el empleado aparece en "Ver bajas" y que al volver a abrir su perfil el botón ahora dice "Ver baja" y ofrece corregir y reincorporar. Después, corregir la baja y confirmar que desaparece del tablero.

- [ ] **Step 7: Commit**

En `Backend_RRHH`:
```bash
git add app/routes/rrhh.py
git commit -m "feat(bajas): el detalle del empleado informa su baja vigente"
```

En `RRHH`:
```bash
git add src/app/Componentes/TablaOperador/BajaModal.tsx src/app/Componentes/TablaOperador/DetailTables.tsx src/app/Interfas/Interfaces.ts
git commit -m "feat(bajas): accion de baja, correccion y reincorporacion en el perfil"
```

---

## Task 8: Gatear el menú de perfil por permiso

**Files:**
- Modify: `src/app/Componentes/Shell/AppHeader.tsx:193-207` (repo `RRHH`)

**Interfaces:**
- Consumes: `tienePermiso` de `@/app/util/permisos`; los permisos que el shell ya tiene cargados.
- Produces: nada que consuman otras tareas.

**Por qué.** Los cinco ítems del dropdown están hardcodeados sin chequear permisos. El backstop existe —`handlePageChange` en `page.tsx` no navega sin permiso— pero al dado de baja le quedarían visibles "Editar Perfil", "Mi Asistencia", "Licencias" y "Encuesta" como opciones muertas, y el requisito es que solo vea documentos.

- [ ] **Step 1: Ver cómo llegan los permisos al header**

Run: `grep -n "permisos\|interface AppHeaderProps" -A 10 src/app/Componentes/Shell/AppHeader.tsx | head -30`

Si el componente ya recibe `permisos`, usarlo. Si no, pasarlo desde `AppLayout` —que ya lo recibe en `page.tsx`— agregándolo a sus props.

- [ ] **Step 2: Gatear los ítems**

En `AppHeader.tsx`, importar el helper:

```typescript
import { tienePermiso } from "@/app/util/permisos";
```

Y envolver cada ítem con su permiso, reemplazando el bloque de líneas 193-207:

```tsx
            {tienePermiso(permisos, "perfil.editar") && (
              <DropdownMenuItem onClick={() => setPage("editar-perfil")}>
                <UserCircle size={16} className="mr-2" /> Editar Perfil
              </DropdownMenuItem>
            )}
            {tienePermiso(permisos, "asistencia.propia") && (
              <DropdownMenuItem onClick={() => setPage("mi-asistencia")}>
                <Clock size={16} className="mr-2" /> Mi Asistencia
              </DropdownMenuItem>
            )}
            {tienePermiso(permisos, "licencias.propias") && (
              <DropdownMenuItem onClick={() => setPage("licencias")}>
                <FileText size={16} className="mr-2" /> Licencias
              </DropdownMenuItem>
            )}
            {tienePermiso(permisos, "documentos.propios") && (
              <DropdownMenuItem onClick={() => setPage("documentos")}>
                <Folder size={16} className="mr-2" /> Documentos
              </DropdownMenuItem>
            )}
            {tienePermiso(permisos, "feedback.participar") && (
              <DropdownMenuItem onClick={() => setPage("feedback")}>
                <MessageSquare size={16} className="mr-2" /> Encuesta
              </DropdownMenuItem>
            )}
```

"Cerrar Sesión" no se gatea: siempre tiene que poder salir.

- [ ] **Step 3: Verificar tipos**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -i "AppHeader\|AppLayout"`
Expected: sin salida

- [ ] **Step 4: Verificar el recorte de punta a punta en el navegador**

Este es el paso que valida el requisito central de la feature:

1. Dar de baja a un empleado de prueba que tenga usuario.
2. Cerrar sesión y entrar con ese usuario.
3. Confirmar que aterriza en Documentos, que el sidebar no muestra ninguna otra sección, y que el menú de perfil solo ofrece "Documentos" y "Cerrar Sesión".
4. Confirmar que puede abrir y descargar sus documentos.
5. Reincorporarlo desde RRHH, volver a entrar con ese usuario y confirmar que recuperó todo el menú.

- [ ] **Step 5: Commit**

```bash
git add src/app/Componentes/Shell/AppHeader.tsx
git commit -m "fix(shell): el menu de perfil respeta los permisos"
```

---

## Task 9: Retirar la jubilación

Última tarea a propósito: recién acá nada referencia el módulo viejo.

**Files:**
- Delete: `app/services/jubilacion.py`, `app/database/jubilacion.py`
- Modify: `app/routes/rrhh.py` (borrar `put_jubilacion`, `get_jubilados` y sus imports), `app/scheduler.py:14-18,164-200,206-221`
- Modify: `tests/test_jubilacion.py` → renombrar a `tests/test_corte_rango_asistencia.py`
- Test: `tests/test_scheduler_bajas.py`

**Interfaces:**
- Consumes: de `app/database/bajas.py`: `pendientes_de_aplicar`, `aplicar_efectos`.
- Produces: `_tick_bajas()` en el scheduler, registrado con el id `"bajas"`.

- [ ] **Step 1: Escribir el test del tick que falla**

Crear `tests/test_scheduler_bajas.py`:

```python
"""
El tick diario de bajas.

Solo aplica los EFECTOS colaterales de las bajas que se cumplieron. El corte
de accesos no depende de el: se calcula con la fecha en cada request, asi que
si este job se cae el dado de baja igual queda recortado.
"""

from datetime import date

from app.database.bajas import aplicar_efectos, pendientes_de_aplicar
from tests.fakes import FakeSession

HOY = date(2026, 9, 17)


def test_no_devuelve_a_quien_ya_figura_de_baja():
    """Solo avanza: el tick nunca reactiva ni retoca a quien ya esta aplicado."""
    db = FakeSession({"FROM EmployeeBaja b": []})
    assert pendientes_de_aplicar(db, HOY) == []


def test_devuelve_a_quien_tiene_la_fecha_cumplida_y_sigue_activo():
    db = FakeSession({"FROM EmployeeBaja b": [{"employeeId": 8}]})
    assert pendientes_de_aplicar(db, HOY) == [8]


def test_aplicar_dos_veces_da_el_mismo_resultado():
    """Idempotente: el segundo pase escribe lo mismo que el primero."""
    db = FakeSession()
    aplicar_efectos(db, 8)
    primera = db.sql_ejecutado()
    db2 = FakeSession()
    aplicar_efectos(db2, 8)
    assert db2.sql_ejecutado() == primera
```

- [ ] **Step 2: Correr el test**

Run: `py -m pytest tests/test_scheduler_bajas.py -q`
Expected: `3 passed` (las funciones ya existen de Task 2; el test fija el contrato que el tick usa)

- [ ] **Step 3: Reconvertir el tick del scheduler**

En `app/scheduler.py`, reemplazar el import de las líneas 14-18:

```python
from app.database.bajas import aplicar_efectos, pendientes_de_aplicar
```

Reemplazar `_tick_jubilaciones` (líneas 164-200) por:

```python
def _tick_bajas():
    """
    Aplica los efectos de las bajas cuya fecha ya llego.

    Es la pieza que hace util cargar una baja con fecha futura: RRHH la carga
    cuando la sabe y la persona sigue trabajando hasta ese dia.

    Ojo con lo que este job NO hace: el recorte de accesos no pasa por aca. Se
    calcula con la fecha en cada request, asi que si este tick se cae, el dado
    de baja igual queda recortado. Lo que se aplica aca son los efectos
    colaterales -cancelar solicitudes sin resolver y marcar el estado-, que si
    necesitan un actuador.

    Solo avanza: nunca reactiva a nadie. Reincorporar es siempre un acto
    explicito de RRHH desde la interfaz.

    Corre antes del recalculo de asistencia para que el rango del dia ya tenga
    la cota superior puesta cuando aquel arranque.
    """
    db = SessionLocal()
    try:
        hoy = date.today()
        ids = pendientes_de_aplicar(db, hoy)
        if not ids:
            log.info("Bajas: no hay ninguna para aplicar hoy")
            return
        for eid in ids:
            aplicar_efectos(db, eid)
            log.info("Baja aplicada: empleado %s", eid)
        db.commit()
        log.info("Bajas: %s empleados pasaron a Baja", len(ids))
    except Exception as e:
        db.rollback()
        log.exception("Fallo inesperado en el tick de bajas: %s", e)
    finally:
        db.close()
```

En `iniciar_scheduler`, cambiar el job registrado (líneas 217-221):

```python
        _tick_bajas,
        "cron",
        hour=HORA_JUBILACIONES,
        minute=0,
        id="bajas",
```

Renombrar la constante `HORA_JUBILACIONES` a `HORA_BAJAS` en su definición y en los dos usos (el `add_job` y el log final del arranque), y actualizar el docstring de `iniciar_scheduler` y el mensaje de log que dice "jubilaciones a las %s:00".

- [ ] **Step 4: Borrar los endpoints de jubilación**

En `app/routes/rrhh.py`, borrar `put_jubilacion` y `get_jubilados` completos (desde el comentario `# PUT /rrhh/employee/{id}/jubilacion` hasta el final de `get_jubilados`) y el import:

```python
from app.database.jubilacion import (
    ESTADO_JUBILADO, aplicar_jubilacion, ensure_columna_jubilacion, jubilados,
)
```

Verificar que no queda ninguna referencia:

```bash
grep -rn "jubilacion\|jubilado\|ESTADO_JUBILADO" app/ --include=*.py | grep -v __pycache__
```
Expected: sin salida

- [ ] **Step 5: Borrar los módulos**

```bash
git rm app/services/jubilacion.py app/database/jubilacion.py
```

- [ ] **Step 6: Renombrar el test de jubilación**

```bash
git mv tests/test_jubilacion.py tests/test_corte_rango_asistencia.py
```

En el archivo renombrado, borrar los cinco tests de `jubilacion_cumplida` (esa regla ahora vive en `baja_vigente`, cubierta por `tests/test_bajas.py`) y su import. Quedan los nueve de `rango_de_calculo`. Actualizar el docstring del módulo:

```python
"""
El rango de dias que se le calcula a un empleado en un anio.

Acotado por abajo por el inicio del modulo y el ingreso, y por arriba por el
fin del anio, hoy y la fecha de baja. Es lo que congela el saldo de quien se
fue, sin ningun caso especial.
"""
```

Y renombrar los tests que dicen "jubilacion" para que digan "baja":
`test_sin_jubilacion_el_rango_llega_hasta_hoy` → `test_sin_baja_el_rango_llega_hasta_hoy`, `test_la_jubilacion_corta_el_rango` → `test_la_baja_corta_el_rango`, `test_una_jubilacion_futura_no_recorta_nada` → `test_una_baja_futura_no_recorta_nada`, `test_una_jubilacion_anterior_al_inicio_del_modulo_no_da_rango` → `test_una_baja_anterior_al_inicio_del_modulo_no_da_rango`, `test_ingreso_y_jubilacion_en_el_mismo_anio` → `test_ingreso_y_baja_en_el_mismo_anio`, `test_jubilarse_el_mismo_dia_del_ingreso_da_un_solo_dia` → `test_irse_el_mismo_dia_del_ingreso_da_un_solo_dia`.

- [ ] **Step 7: Borrar la columna del esquema**

`CondicionLaboral.fechaJubilacion` ya no la lee nadie. Como nadie tiene un valor cargado —verificado al escribir el spec: cero filas—, se puede borrar sin migrar datos. Agregar al startup de `app/main.py`, después de `ensure_tabla_bajas(db)`:

```python
        db.execute(_text(
            "IF COL_LENGTH('CondicionLaboral','fechaJubilacion') IS NOT NULL "
            "ALTER TABLE CondicionLaboral DROP COLUMN fechaJubilacion"
        ))
        db.commit()
        print("[OK] columna fechaJubilacion retirada")
```

- [ ] **Step 8: Correr la suite completa**

Run:
```bash
py -m pytest tests/ -q --ignore=tests/test_chat_ausencias.py --ignore=tests/test_chat_buscar_empleado.py --ignore=tests/test_chat_documentos.py --ignore=tests/test_chat_tardanzas.py
```
Expected: `586 passed` (588 menos los 5 tests de `jubilacion_cumplida`, más los 3 del tick)

- [ ] **Step 9: Verificar que la app arranca y el tick está registrado**

Levantar el backend y confirmar en el log del arranque: `[OK] tabla EmployeeBaja verificada`, `[OK] columna fechaJubilacion retirada`, y que el scheduler anuncia el job de bajas sin errores.

- [ ] **Step 10: Commit**

```bash
git add -A app/ tests/
git commit -m "refactor(bajas): retirar el modulo de jubilacion, absorbido por bajas"
```

---

## Autorevisión del plan

**Cobertura del spec.** Cada requisito tiene tarea: catálogo de 7 motivos (T1), tabla `EmployeeBaja` y DDL idempotente (T2), cancelación de pendientes con los dos UPDATE (T2), `Employee.status` como caché y `User.activo` intacto (T2), recorte a `documentos.propios` en los dos puntos de resolución (T3), los cuatro endpoints con las cuatro validaciones incluida la del último ADMIN (T4), corte de vacaciones y asistencia por fecha de baja y guard de `_sync_employee_status` (T5), tablero con desglose por motivo y los tres estados (T6), acción explícita con modal de confirmación y las dos reversiones (T7), menú de perfil gateado (T8), retiro de jubilación y eliminación de `fechaJubilacion` (T9).

**Consistencia de tipos.** `baja_vigente` devuelve el dict crudo de la fila en todos los usos; `fecha_de_corte` devuelve `date | None` y es lo que consumen `calcular_dias_vacaciones` y `rango_de_calculo`; `estado` usa los mismos tres literales en backend (`"vigente"`, `"reincorporada"`, `"programada"`) y en el tipo `EstadoBaja` del frontend; los siete motivos son idénticos, con acentos, en `MOTIVOS_DE_BAJA`, `MotivoBaja` y el array `MOTIVOS` del modal.

**Riesgo de secuencia, deliberado.** Los endpoints de jubilación se borran en T9 y no en T4 justamente porque `DetailTables.tsx` los llama en cada guardado de condición laboral hasta T7: borrarlos antes dejaría un 404 en una pantalla que se usa. El orden T4 (agrega) → T7 (el frontend deja de llamarlos) → T9 (borra) mantiene el sistema funcionando en cada commit.
