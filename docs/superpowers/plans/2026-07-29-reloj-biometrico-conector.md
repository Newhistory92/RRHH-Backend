# Conector ISAPI de relojes biométricos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-29-reloj-biometrico-conector-design.md`
**Branch:** `reloj-biometrico-conector`
**Repos:** Backend_RRHH (tareas 1-6, 8) + RRHH (tarea 7)

**Goal:** Leer automáticamente las marcaciones de dos relojes Hikvision por ISAPI hacia SQL Server, y permitir que RRHH vincule cada empleado con su ID del reloj.

**Architecture:** Un job de APScheduler dentro del proceso FastAPI consulta cada 5 minutos ambos equipos usando una ventana temporal con 10 minutos de solape; la unicidad `(relojIp, serialNo)` hace idempotente el reprocesamiento. Todo acceso a los equipos pasa por un único cliente con allowlist de solo lectura.

**Tech Stack:** FastAPI, SQLAlchemy `text()` sobre SQL Server, `requests` con `HTTPDigestAuth`, APScheduler, pytest.

## Global Constraints

- **Solo lectura sobre los relojes.** Requisito explícito del usuario: *"no quiero modificar nada del reloj, solo absorber la información"*. El cliente ISAPI implementa únicamente `GET` y `POST`, nunca `PUT` ni `DELETE`, y valida el path contra una allowlist cerrada de exactamente estos tres endpoints:
  - `GET /ISAPI/System/deviceInfo`
  - `POST /ISAPI/AccessControl/AcsEvent`
  - `POST /ISAPI/AccessControl/UserInfo/Search`
- **SQL 100% parametrizado** con `text()` y diccionario de parámetros — nunca interpolación de datos de entrada.
- **DDL idempotente:** `IF OBJECT_ID(...) IS NULL` / `IF COL_LENGTH(...) IS NULL`, cada sentencia en su **propio batch seguido de `db.commit()`** (SQL Server compila el batch completo antes de ejecutarlo).
- **RBAC:** solo existen dos roles, `ROLE_ADMIN = 1` y `ROLE_USER = 2` (no hay rol RRHH separado). Escrituras y toda operación contra los equipos: `require_admin`. Lecturas de marcaciones: `require_any_auth` con chequeo de pertenencia (un `ROLE_USER` accede solo a las propias).
- **Credenciales en `.env`** (`RELOJ_USER`, `RELOJ_PASS`, `RELOJ_IPS`) — nunca en código ni en documentos versionados.
- **Marcación válida:** `major = 5` y `minor = 38`. `minor` 21 y 22 son aperturas de puerta sin persona: se descartan.
- **`fechaHora` se almacena en hora local de Argentina** tal como la reporta el equipo (`-03:00`), sin convertir a UTC: el subsistema 3 la compara contra `Horario.horaInicio = 7.0`, que también es hora local.
- **Solape de la ventana:** 10 minutos. **Frecuencia del job:** 5 minutos. **Carga inicial:** último mes (30 días), nunca historial anterior.
- **Timeout** explícito en toda llamada HTTP a los relojes.
- **NO tocar** `prisma/schema.prisma` ni `src/app/util/UiRRHH.tsx`.
- **CSS semántico** en el frontend: `text-muted-foreground`, `text-error`, `border-border`, etc. Nunca colores crudos de Tailwind.

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `app/services/isapi_client.py` (nuevo) | Único punto de acceso a los relojes. Allowlist de solo lectura, digest auth, timeout |
| `app/database/marcaciones.py` (nuevo) | DDL idempotente, inserción y consultas de `Marcacion` / `RelojSync` |
| `app/services/reloj_sync.py` (nuevo) | Lógica de sincronización: ventana con solape, paginación, filtrado, orquestación |
| `app/scheduler.py` (nuevo) | Configuración de APScheduler |
| `app/routes/relojes.py` (nuevo) | Endpoints de estado, sync manual, carga inicial, consulta de usuario |
| `app/main.py` (modificar) | Registrar router y arrancar el scheduler |
| `app/routes/employee.py` (modificar) | `biometricoId` en el GET del empleado y en el PUT |
| `tests/test_isapi_client.py` (nuevo) | Allowlist y rechazo de verbos de escritura |
| `tests/test_reloj_sync.py` (nuevo) | Ventana con solape y filtrado de eventos, con JSON mockeado |
| `requirements.txt` (modificar) | `apscheduler`, `pytest` |
| `src/app/Interfas/Interfaces.ts` (modificar, repo RRHH) | `biometricoId` en `Employee` |
| `src/app/Componentes/TablaOperador/DetailTables.tsx` (modificar, repo RRHH) | Campo editable en `ProfileTab` |

`DetailTables.tsx` tiene 1250 líneas. No se divide en este plan — sería alcance no pedido — pero el campo nuevo se agrega a la sección `detallesAdicionales` que ya existe, sin crear estructura nueva.

---

## Task 1: Cliente ISAPI de solo lectura

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/isapi_client.py`
- Create: `tests/__init__.py`
- Create: `tests/test_isapi_client.py`
- Modify: `requirements.txt`
- Modify: `.env`

**Interfaces:**
- Consumes: nada (primera tarea)
- Produces:
  - `ALLOWLIST: set[tuple[str, str]]` — exactamente 3 pares `(metodo, path)`
  - `ENDPOINT_DEVICE_INFO`, `ENDPOINT_ACS_EVENT`, `ENDPOINT_USER_SEARCH: str`
  - `ISAPIError(Exception)`, `ISAPINotAllowed(ISAPIError)`
  - `relojes_configurados() -> list[str]`
  - `pedir(metodo: str, ip: str, path: str, json_body: dict | None = None) -> dict | str`
  - `buscar_eventos(ip: str, desde: datetime, hasta: datetime, posicion: int, max_results: int = 100) -> dict`
  - `buscar_usuario(ip: str, biometrico_id: str) -> dict | None`
  - `info_dispositivo(ip: str) -> str`

- [ ] **Step 1: Agregar dependencias**

En `requirements.txt`, agregar al final:

```
apscheduler==3.10.4
pytest==8.3.4
```

Instalar:

```bash
py -m pip install apscheduler==3.10.4 pytest==8.3.4
```

- [ ] **Step 2: Agregar variables al `.env`**

Agregar al final de `.env` (usar la contraseña real del equipo, no la del ejemplo):

```
# Relojes biometricos Hikvision (ISAPI, solo lectura)
RELOJ_IPS="10.25.2.24,10.25.2.25"
RELOJ_USER="admin"
RELOJ_PASS="<contrasena_real_del_reloj>"
```

- [ ] **Step 3: Escribir el test que falla**

Crear `tests/__init__.py` vacío y `tests/test_isapi_client.py`:

```python
import pytest
from app.services import isapi_client as c


def test_allowlist_tiene_exactamente_tres_endpoints():
    assert len(c.ALLOWLIST) == 3
    assert ("GET", c.ENDPOINT_DEVICE_INFO) in c.ALLOWLIST
    assert ("POST", c.ENDPOINT_ACS_EVENT) in c.ALLOWLIST
    assert ("POST", c.ENDPOINT_USER_SEARCH) in c.ALLOWLIST


@pytest.mark.parametrize("metodo", ["PUT", "DELETE", "PATCH"])
def test_rechaza_verbos_de_escritura(metodo):
    with pytest.raises(c.ISAPINotAllowed):
        c.pedir(metodo, "10.25.2.24", c.ENDPOINT_DEVICE_INFO)


@pytest.mark.parametrize("path", [
    "/ISAPI/AccessControl/UserInfo/Delete",
    "/ISAPI/AccessControl/UserInfo/Record",
    "/ISAPI/AccessControl/UserInfo/Modify",
    "/ISAPI/AccessControl/RemoteControl/door/1",
    "/ISAPI/System/time",
])
def test_rechaza_endpoints_que_escriben(path):
    with pytest.raises(c.ISAPINotAllowed):
        c.pedir("POST", "10.25.2.24", path, {"algo": 1})


def test_relojes_configurados_parsea_lista(monkeypatch):
    monkeypatch.setenv("RELOJ_IPS", " 10.25.2.24 , 10.25.2.25 ,")
    assert c.relojes_configurados() == ["10.25.2.24", "10.25.2.25"]
```

- [ ] **Step 4: Correr el test para verificar que falla**

Run: `py -m pytest tests/test_isapi_client.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 5: Implementar el cliente**

Crear `app/services/__init__.py` vacío y `app/services/isapi_client.py`:

```python
"""
Cliente ISAPI de SOLO LECTURA para relojes Hikvision DS-K1T320MFWX.

Garantia dura del subsistema: este modulo es el unico punto de acceso a los
equipos. Requisito explicito del usuario -- "no quiero modificar nada del reloj,
solo absorber la informacion".

En ISAPI el verbo HTTP no indica si la operacion escribe: las busquedas usan
POST porque el filtro viaja en el cuerpo. Por eso la garantia no puede apoyarse
en el verbo y se implementa como allowlist cerrada de (metodo, path).
"""

import os
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth

ENDPOINT_DEVICE_INFO = "/ISAPI/System/deviceInfo"
ENDPOINT_ACS_EVENT = "/ISAPI/AccessControl/AcsEvent"
ENDPOINT_USER_SEARCH = "/ISAPI/AccessControl/UserInfo/Search"

# Unicos endpoints invocables. Deliberadamente excluidos por escribir en el
# equipo: UserInfo/Record, UserInfo/Modify, UserInfo/Delete,
# RemoteControl/door/*, System/time, ClearEvent y todo PUT de configuracion.
ALLOWLIST = {
    ("GET", ENDPOINT_DEVICE_INFO),
    ("POST", ENDPOINT_ACS_EVENT),
    ("POST", ENDPOINT_USER_SEARCH),
}

TIMEOUT_SEGUNDOS = 15


class ISAPIError(Exception):
    """Fallo al comunicarse con un reloj."""


class ISAPINotAllowed(ISAPIError):
    """Se intento una operacion fuera de la allowlist de solo lectura."""


def _credenciales() -> HTTPDigestAuth:
    usuario = os.getenv("RELOJ_USER")
    clave = os.getenv("RELOJ_PASS")
    if not usuario or not clave:
        raise ISAPIError("RELOJ_USER / RELOJ_PASS no estan configurados en el .env")
    return HTTPDigestAuth(usuario, clave)


def relojes_configurados() -> list[str]:
    """IPs de los relojes, desde RELOJ_IPS separadas por coma."""
    crudo = os.getenv("RELOJ_IPS", "")
    return [ip.strip() for ip in crudo.split(",") if ip.strip()]


def pedir(metodo: str, ip: str, path: str, json_body: Optional[dict] = None):
    """
    Unica salida a la red hacia un reloj. Rechaza cualquier par (metodo, path)
    que no este en la allowlist ANTES de abrir la conexion.
    """
    if (metodo, path) not in ALLOWLIST:
        raise ISAPINotAllowed(
            f"{metodo} {path} no esta en la allowlist de solo lectura del cliente ISAPI"
        )

    url = f"http://{ip}{path}"
    if json_body is not None:
        url += "?format=json"

    try:
        resp = requests.request(
            metodo, url, auth=_credenciales(), json=json_body, timeout=TIMEOUT_SEGUNDOS
        )
    except requests.RequestException as e:
        raise ISAPIError(f"Reloj {ip} inaccesible: {e}") from e

    if resp.status_code == 401:
        raise ISAPIError(f"Reloj {ip}: credenciales rechazadas (401)")
    if resp.status_code >= 400:
        raise ISAPIError(f"Reloj {ip}: HTTP {resp.status_code}")

    if json_body is None:
        return resp.text
    try:
        return resp.json()
    except ValueError as e:
        raise ISAPIError(f"Reloj {ip}: respuesta JSON malformada") from e


def buscar_eventos(ip: str, desde: datetime, hasta: datetime,
                   posicion: int, max_results: int = 100) -> dict:
    """
    Busca marcaciones validas en una ventana. El filtro major/minor va DENTRO
    de AcsEventCond para que filtre el equipo y no viajen los eventos de puerta.
    """
    cond = {
        "AcsEventCond": {
            "searchID": "rrhh-sync",
            "searchResultPosition": posicion,
            "maxResults": max_results,
            "major": 5,
            "minor": 38,
            "startTime": desde.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
            "endTime": hasta.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
        }
    }
    return pedir("POST", ip, ENDPOINT_ACS_EVENT, cond)


def buscar_usuario(ip: str, biometrico_id: str) -> Optional[dict]:
    """Datos de una persona del padron del reloj, o None si no existe."""
    cond = {
        "UserInfoSearchCond": {
            "searchID": "rrhh-lookup",
            "searchResultPosition": 0,
            "maxResults": 30,
            "EmployeeNoList": [{"employeeNo": str(biometrico_id)}],
        }
    }
    data = pedir("POST", ip, ENDPOINT_USER_SEARCH, cond)
    usuarios = (data.get("UserInfoSearch") or {}).get("UserInfo") or []
    for u in usuarios:
        if str(u.get("employeeNo")) == str(biometrico_id):
            return u
    return None


def info_dispositivo(ip: str) -> str:
    """XML crudo de deviceInfo. Se usa como health check."""
    return pedir("GET", ip, ENDPOINT_DEVICE_INFO)
```

- [ ] **Step 6: Correr el test para verificar que pasa**

Run: `py -m pytest tests/test_isapi_client.py -v`
Expected: PASS — 10 tests (1 allowlist + 3 verbos + 5 paths + 1 parseo)

- [ ] **Step 7: Verificar contra el equipo real**

Run: `py -c "from dotenv import load_dotenv; load_dotenv(); from app.services.isapi_client import info_dispositivo, relojes_configurados; [print(ip, 'OK' if 'DS-K1T320MFWX' in info_dispositivo(ip) else 'REVISAR') for ip in relojes_configurados()]"`
Expected: `10.25.2.24 OK` y `10.25.2.25 OK`

- [ ] **Step 8: Commit**

```bash
git add requirements.txt app/services tests
git commit -m "feat: cliente ISAPI de solo lectura con allowlist para relojes biometricos"
```

Nota: `.env` no se commitea (está en `.gitignore`).

---

## Task 2: Tablas Marcacion y RelojSync

**Files:**
- Create: `app/database/marcaciones.py`

**Interfaces:**
- Consumes: nada del código nuevo
- Produces:
  - `ensure_tables(db: Session) -> None`
  - `estado_relojes(db: Session) -> list[dict]` — filas de `RelojSync`
  - `registrar_reloj(db: Session, reloj_ip: str) -> None` — alta idempotente en `RelojSync`
  - `ultima_sync(db: Session, reloj_ip: str) -> datetime | None`
  - `marcar_sync_ok(db: Session, reloj_ip: str, momento: datetime) -> None`
  - `marcar_sync_error(db: Session, reloj_ip: str, error: str) -> None`
  - `max_serial_no(db: Session, reloj_ip: str) -> int | None`
  - `insertar_marcaciones(db: Session, filas: list[dict]) -> int` — devuelve cuántas insertó
  - `marcaciones_de(db: Session, biometrico_id: str, desde: datetime, hasta: datetime) -> list[dict]`

- [ ] **Step 1: Crear el módulo con el DDL idempotente**

Crear `app/database/marcaciones.py`:

```python
"""
Marcaciones crudas de los relojes biometricos y estado de sincronizacion.

Las marcaciones se guardan SIEMPRE, incluso si el biometricoId todavia no
corresponde a ningun empleado: quedan huerfanas y aparecen retroactivamente
cuando RRHH carga el vinculo, sin necesidad de resincronizar.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

CREATE_MARCACION_SQL = """
IF OBJECT_ID('Marcacion', 'U') IS NULL
CREATE TABLE Marcacion (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    relojIp       NVARCHAR(20)  NOT NULL,
    serialNo      BIGINT        NOT NULL,
    biometricoId  NVARCHAR(50)  NOT NULL,
    nombreReloj   NVARCHAR(100) NULL,
    fechaHora     DATETIME2     NOT NULL,
    verifyMode    NVARCHAR(30)  NULL,
    createdAt     DATETIME2     NOT NULL DEFAULT GETDATE(),
    CONSTRAINT UQ_Marcacion UNIQUE (relojIp, serialNo)
);
"""

CREATE_INDEX_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Marcacion_bio_fecha')
CREATE INDEX IX_Marcacion_bio_fecha ON Marcacion (biometricoId, fechaHora);
"""

CREATE_RELOJSYNC_SQL = """
IF OBJECT_ID('RelojSync', 'U') IS NULL
CREATE TABLE RelojSync (
    relojIp     NVARCHAR(20)  PRIMARY KEY,
    ultimaSync  DATETIME2     NULL,
    ultimoError NVARCHAR(500) NULL,
    activo      BIT           NOT NULL DEFAULT 1
);
"""


def ensure_tables(db: Session) -> None:
    """DDL idempotente. Cada sentencia en su propio batch + commit."""
    db.execute(text(CREATE_MARCACION_SQL))
    db.commit()
    db.execute(text(CREATE_INDEX_SQL))
    db.commit()
    db.execute(text(CREATE_RELOJSYNC_SQL))
    db.commit()


def registrar_reloj(db: Session, reloj_ip: str) -> None:
    """Alta idempotente en RelojSync."""
    db.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM RelojSync WHERE relojIp = :ip)
        INSERT INTO RelojSync (relojIp, ultimaSync, ultimoError, activo)
        VALUES (:ip, NULL, NULL, 1)
    """), {"ip": reloj_ip})
    db.commit()


def estado_relojes(db: Session) -> list[dict]:
    filas = db.execute(text(
        "SELECT relojIp, ultimaSync, ultimoError, activo FROM RelojSync ORDER BY relojIp"
    )).mappings().all()
    return [dict(f) for f in filas]


def ultima_sync(db: Session, reloj_ip: str) -> Optional[datetime]:
    fila = db.execute(text(
        "SELECT ultimaSync FROM RelojSync WHERE relojIp = :ip"
    ), {"ip": reloj_ip}).mappings().first()
    return fila["ultimaSync"] if fila else None


def marcar_sync_ok(db: Session, reloj_ip: str, momento: datetime) -> None:
    db.execute(text("""
        UPDATE RelojSync SET ultimaSync = :m, ultimoError = NULL WHERE relojIp = :ip
    """), {"m": momento, "ip": reloj_ip})


def marcar_sync_error(db: Session, reloj_ip: str, error: str) -> None:
    db.execute(text("""
        UPDATE RelojSync SET ultimoError = :e WHERE relojIp = :ip
    """), {"e": error[:500], "ip": reloj_ip})


def max_serial_no(db: Session, reloj_ip: str) -> Optional[int]:
    """
    Mayor serialNo ya almacenado del equipo. Se usa para detectar un reinicio
    del correlativo, que romperia silenciosamente la idempotencia.
    """
    fila = db.execute(text(
        "SELECT MAX(serialNo) AS m FROM Marcacion WHERE relojIp = :ip"
    ), {"ip": reloj_ip}).mappings().first()
    return fila["m"] if fila and fila["m"] is not None else None


def insertar_marcaciones(db: Session, filas: list[dict]) -> int:
    """
    Inserta descartando las que ya existen por (relojIp, serialNo).

    Resuelve los existentes con UNA consulta previa por lote en lugar de
    apoyarse en el rowcount de un 'IF NOT EXISTS ... INSERT': sobre SQL Server
    ese rowcount no distingue de forma confiable el insert que ocurrio del que
    se salteo, y el conteo devuelto se usa para verificar la idempotencia.
    """
    if not filas:
        return 0

    reloj_ip = filas[0]["relojIp"]
    seriales = [f["serialNo"] for f in filas]

    # Parametrizado: se genera un bind por serial, nunca interpolacion.
    binds = {f"s{i}": s for i, s in enumerate(seriales)}
    marcadores = ", ".join(f":{k}" for k in binds)
    existentes = {
        r["serialNo"]
        for r in db.execute(text(
            f"SELECT serialNo FROM Marcacion WHERE relojIp = :ip AND serialNo IN ({marcadores})"
        ), {"ip": reloj_ip, **binds}).mappings().all()
    }

    nuevas = [f for f in filas if f["serialNo"] not in existentes]
    ahora = datetime.now()
    for f in nuevas:
        db.execute(text("""
            INSERT INTO Marcacion
                (relojIp, serialNo, biometricoId, nombreReloj, fechaHora, verifyMode, createdAt)
            VALUES
                (:relojIp, :serialNo, :biometricoId, :nombreReloj, :fechaHora, :verifyMode, :createdAt)
        """), {**f, "createdAt": ahora})

    db.commit()
    return len(nuevas)


def marcaciones_de(db: Session, biometrico_id: str,
                   desde: datetime, hasta: datetime) -> list[dict]:
    filas = db.execute(text("""
        SELECT id, relojIp, serialNo, biometricoId, nombreReloj, fechaHora, verifyMode
        FROM Marcacion
        WHERE biometricoId = :bio AND fechaHora >= :desde AND fechaHora <= :hasta
        ORDER BY fechaHora
    """), {"bio": str(biometrico_id), "desde": desde, "hasta": hasta}).mappings().all()
    return [dict(f) for f in filas]
```

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/database/marcaciones.py`
Expected: exit 0, sin salida

- [ ] **Step 3: Verificar el DDL contra la base real**

Crear y correr un script temporal:

```python
import sys, os
sys.path.insert(0, r"C:\Users\Emiliano\Documents\Backend_RRHH")
os.chdir(r"C:\Users\Emiliano\Documents\Backend_RRHH")
from app.database.database import SessionLocal
from app.database.marcaciones import ensure_tables, registrar_reloj, estado_relojes
from sqlalchemy import text

db = SessionLocal()
ensure_tables(db)
ensure_tables(db)  # segunda vez: debe ser inofensiva
registrar_reloj(db, "10.25.2.24")
registrar_reloj(db, "10.25.2.24")  # idempotente
registrar_reloj(db, "10.25.2.25")
print("RelojSync:", estado_relojes(db))
cols = db.execute(text(
    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='Marcacion'"
)).mappings().all()
print("Columnas Marcacion:", [c["COLUMN_NAME"] for c in cols])
```

Expected: `RelojSync` con exactamente 2 filas (no 4), y las 8 columnas de `Marcacion`.

- [ ] **Step 4: Commit**

```bash
git add app/database/marcaciones.py
git commit -m "feat: tablas Marcacion y RelojSync con DDL idempotente"
```

---

## Task 3: Lógica de sincronización

**Files:**
- Create: `app/services/reloj_sync.py`
- Create: `tests/test_reloj_sync.py`

**Interfaces:**
- Consumes: de Task 1 `buscar_eventos`, `relojes_configurados`, `ISAPIError`; de Task 2 `ensure_tables`, `registrar_reloj`, `ultima_sync`, `marcar_sync_ok`, `marcar_sync_error`, `max_serial_no`, `insertar_marcaciones`
- Produces:
  - `SOLAPE_MINUTOS = 10`, `DIAS_CARGA_INICIAL = 30`
  - `calcular_ventana(ultima: datetime | None, ahora: datetime, dias_iniciales: int = 30) -> tuple[datetime, datetime]`
  - `extraer_marcaciones(payload: dict, reloj_ip: str) -> list[dict]`
  - `hay_mas_paginas(payload: dict) -> bool`
  - `sincronizar_reloj(db, reloj_ip: str, desde=None, hasta=None) -> dict`
  - `sincronizar_todos(db, desde=None, hasta=None) -> list[dict]`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_reloj_sync.py`:

```python
from datetime import datetime, timedelta

from app.services import reloj_sync as s

PAYLOAD_MIXTO = {
    "AcsEvent": {
        "searchID": "1",
        "totalMatches": 4,
        "responseStatusStrg": "MORE",
        "numOfMatches": 4,
        "InfoList": [
            {"major": 5, "minor": 21, "time": "2026-07-28T05:52:25-03:00",
             "serialNo": 168410, "currentVerifyMode": "invalid"},
            {"major": 5, "minor": 38, "time": "2026-07-28T06:08:29-03:00",
             "name": "Zalazar Beatriz", "employeeNoString": "50",
             "serialNo": 168409, "currentVerifyMode": "fpOrface"},
            {"major": 5, "minor": 22, "time": "2026-07-28T05:52:30-03:00",
             "serialNo": 168411, "currentVerifyMode": "invalid"},
            {"major": 5, "minor": 38, "time": "2026-07-28T13:02:22-03:00",
             "employeeNoString": "", "serialNo": 168500},
        ],
    }
}


def test_ventana_con_solape_de_diez_minutos():
    ultima = datetime(2026, 7, 28, 10, 0, 0)
    ahora = datetime(2026, 7, 28, 10, 5, 0)
    desde, hasta = s.calcular_ventana(ultima, ahora)
    assert desde == datetime(2026, 7, 28, 9, 50, 0)
    assert hasta == ahora


def test_primera_sync_trae_el_ultimo_mes():
    ahora = datetime(2026, 7, 29, 12, 0, 0)
    desde, hasta = s.calcular_ventana(None, ahora)
    assert desde == ahora - timedelta(days=30)
    assert hasta == ahora


def test_descarta_ruido_de_puerta_y_eventos_sin_persona():
    filas = s.extraer_marcaciones(PAYLOAD_MIXTO, "10.25.2.24")
    assert len(filas) == 1
    fila = filas[0]
    assert fila["biometricoId"] == "50"
    assert fila["serialNo"] == 168409
    assert fila["relojIp"] == "10.25.2.24"
    assert fila["nombreReloj"] == "Zalazar Beatriz"
    assert fila["verifyMode"] == "fpOrface"


def test_fecha_se_guarda_como_hora_local_sin_tzinfo():
    fila = s.extraer_marcaciones(PAYLOAD_MIXTO, "10.25.2.24")[0]
    assert fila["fechaHora"] == datetime(2026, 7, 28, 6, 8, 29)
    assert fila["fechaHora"].tzinfo is None


def test_payload_vacio_no_explota():
    assert s.extraer_marcaciones({}, "10.25.2.24") == []
    assert s.extraer_marcaciones({"AcsEvent": {}}, "10.25.2.24") == []


def test_deteccion_de_mas_paginas():
    assert s.hay_mas_paginas(PAYLOAD_MIXTO) is True
    assert s.hay_mas_paginas({"AcsEvent": {"responseStatusStrg": "OK"}}) is False
    assert s.hay_mas_paginas({}) is False
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `py -m pytest tests/test_reloj_sync.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.reloj_sync'`

- [ ] **Step 3: Implementar la lógica**

Crear `app/services/reloj_sync.py`:

```python
"""
Sincronizacion de marcaciones desde los relojes hacia SQL Server.

AcsEvent filtra por startTime/endTime y no admite "serialNo mayor a", asi que
el sync no usa un cursor de correlativo sino una ventana temporal con solape.
El solape cubre desfasajes de hora y eventos registrados con retraso; los
duplicados que genera los descarta la unicidad (relojIp, serialNo), lo que hace
que reprocesar una ventana sea inofensivo.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database.marcaciones import (
    ensure_tables, registrar_reloj, ultima_sync, marcar_sync_ok,
    marcar_sync_error, max_serial_no, insertar_marcaciones,
)
from app.services.isapi_client import (
    ISAPIError, buscar_eventos, relojes_configurados,
)

log = logging.getLogger(__name__)

SOLAPE_MINUTOS = 10
DIAS_CARGA_INICIAL = 30
MAX_RESULTS = 100
MAX_PAGINAS = 500  # tope de seguridad: 50.000 marcaciones por corrida

MAJOR_ACCESO = 5
MINOR_MARCACION_VALIDA = 38


def calcular_ventana(ultima: Optional[datetime], ahora: datetime,
                     dias_iniciales: int = DIAS_CARGA_INICIAL) -> tuple[datetime, datetime]:
    """Sin sync previa trae el ultimo mes; con sync previa, desde ahi menos el solape."""
    if ultima is None:
        return ahora - timedelta(days=dias_iniciales), ahora
    return ultima - timedelta(minutes=SOLAPE_MINUTOS), ahora


def _parsear_fecha(crudo: str) -> Optional[datetime]:
    """
    '2026-07-28T06:08:29-03:00' -> datetime(2026,7,28,6,8,29) naive.
    Se conserva la hora de pared local: el motor de asistencia la compara
    contra Horario.horaInicio, que tambien es hora local.
    """
    try:
        return datetime.fromisoformat(crudo).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def extraer_marcaciones(payload: dict, reloj_ip: str) -> list[dict]:
    """Filtra el payload a marcaciones validas y lo normaliza a filas de Marcacion."""
    eventos = ((payload or {}).get("AcsEvent") or {}).get("InfoList") or []
    filas = []
    for ev in eventos:
        if ev.get("major") != MAJOR_ACCESO:
            continue
        if ev.get("minor") != MINOR_MARCACION_VALIDA:
            continue
        bio = str(ev.get("employeeNoString") or "").strip()
        if not bio:
            continue
        fecha = _parsear_fecha(ev.get("time"))
        if fecha is None:
            continue
        serial = ev.get("serialNo")
        if serial is None:
            continue
        filas.append({
            "relojIp": reloj_ip,
            "serialNo": int(serial),
            "biometricoId": bio,
            "nombreReloj": (ev.get("name") or None),
            "fechaHora": fecha,
            "verifyMode": (ev.get("currentVerifyMode") or None),
        })
    return filas


def hay_mas_paginas(payload: dict) -> bool:
    estado = ((payload or {}).get("AcsEvent") or {}).get("responseStatusStrg")
    return estado == "MORE"


def sincronizar_reloj(db: Session, reloj_ip: str,
                     desde: Optional[datetime] = None,
                     hasta: Optional[datetime] = None) -> dict:
    """
    Sincroniza un equipo. Nunca propaga excepcion: un reloj caido se registra
    en RelojSync.ultimoError y no debe tumbar el job ni el otro equipo.
    """
    registrar_reloj(db, reloj_ip)
    ahora = hasta or datetime.now()
    if desde is None:
        desde, ahora = calcular_ventana(ultima_sync(db, reloj_ip), ahora)

    resultado = {"relojIp": reloj_ip, "leidos": 0, "insertados": 0, "error": None}
    previo_max = max_serial_no(db, reloj_ip)

    try:
        posicion = 0
        max_visto = 0
        for _ in range(MAX_PAGINAS):
            payload = buscar_eventos(reloj_ip, desde, ahora, posicion, MAX_RESULTS)
            filas = extraer_marcaciones(payload, reloj_ip)
            resultado["leidos"] += len(filas)
            if filas:
                resultado["insertados"] += insertar_marcaciones(db, filas)
                max_visto = max(max_visto, max(f["serialNo"] for f in filas))
            if not hay_mas_paginas(payload):
                break
            posicion += MAX_RESULTS

        # Riesgo conocido: si el equipo reinicia su correlativo, los eventos
        # nuevos colisionarian con los viejos y se descartarian en silencio.
        if previo_max is not None and max_visto and max_visto < previo_max:
            log.warning(
                "Reloj %s: serialNo maximo recibido (%s) es menor al almacenado (%s). "
                "Posible reinicio del correlativo: las marcaciones nuevas podrian "
                "estar descartandose por la unicidad.",
                reloj_ip, max_visto, previo_max,
            )

        marcar_sync_ok(db, reloj_ip, ahora)
        db.commit()
    except ISAPIError as e:
        resultado["error"] = str(e)
        marcar_sync_error(db, reloj_ip, str(e))
        db.commit()
        log.warning("Reloj %s: sync fallida: %s", reloj_ip, e)

    return resultado


def sincronizar_todos(db: Session, desde: Optional[datetime] = None,
                      hasta: Optional[datetime] = None) -> list[dict]:
    """Sincroniza todos los relojes configurados, cada uno de forma independiente."""
    ensure_tables(db)
    return [sincronizar_reloj(db, ip, desde, hasta) for ip in relojes_configurados()]
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `py -m pytest tests/test_reloj_sync.py -v`
Expected: PASS — 6 tests

- [ ] **Step 5: Correr toda la suite**

Run: `py -m pytest tests/ -v`
Expected: PASS — 16 tests, 0 fallos

- [ ] **Step 6: Commit**

```bash
git add app/services/reloj_sync.py tests/test_reloj_sync.py
git commit -m "feat: logica de sincronizacion con ventana de solape y filtrado de eventos"
```

---

## Task 4: Scheduler APScheduler

**Files:**
- Create: `app/scheduler.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: de Task 3 `sincronizar_todos`
- Produces:
  - `INTERVALO_MINUTOS = 5`
  - `iniciar_scheduler() -> BackgroundScheduler | None`
  - `detener_scheduler() -> None`

- [ ] **Step 1: Crear el scheduler**

Crear `app/scheduler.py`:

```python
"""
Job periodico que sincroniza las marcaciones de los relojes.

El estado vive en la tabla RelojSync, no en memoria: un reinicio del backend no
pierde nada, el ciclo siguiente retoma desde ultimaSync.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.database.database import SessionLocal
from app.services.isapi_client import relojes_configurados
from app.services.reloj_sync import sincronizar_todos

log = logging.getLogger(__name__)

INTERVALO_MINUTOS = 5

_scheduler: BackgroundScheduler | None = None


def _tick():
    """Una corrida del sync. Nunca debe propagar excepcion al scheduler."""
    db = SessionLocal()
    try:
        resultados = sincronizar_todos(db)
        for r in resultados:
            if r["error"]:
                log.warning("Sync %s: %s", r["relojIp"], r["error"])
            elif r["insertados"]:
                log.info("Sync %s: %s marcaciones nuevas", r["relojIp"], r["insertados"])
    except Exception as e:
        log.exception("Fallo inesperado en el tick de sincronizacion: %s", e)
    finally:
        db.close()


def iniciar_scheduler():
    """Arranca el job. Si no hay relojes configurados, no arranca nada."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    if not relojes_configurados():
        log.warning("RELOJ_IPS vacio: el sync de relojes no se inicia")
        return None

    _scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
    _scheduler.add_job(
        _tick,
        "interval",
        minutes=INTERVALO_MINUTOS,
        id="sync_relojes",
        max_instances=1,       # nunca dos corridas simultaneas
        coalesce=True,         # si se acumularon ticks, corre uno solo
        replace_existing=True,
    )
    _scheduler.start()
    log.info("Scheduler de relojes iniciado (cada %s min)", INTERVALO_MINUTOS)
    return _scheduler


def detener_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

- [ ] **Step 2: Enganchar en `main.py`**

En `app/main.py`, extender el import de routers de la línea 5 agregando `relojes` al final de la lista:

```python
from app.routes import employee, user, auth, role, active, rrhh, departments, tests, feedback, licenses, obrasocial, stats, configtest, contracts, professions, schedules, reubicacion, publications, activos_config, activos, activos_modelos, relojes
```

Agregar después de ese import:

```python
from app.scheduler import iniciar_scheduler, detener_scheduler
```

Reemplazar el bloque de startup (líneas 18-22) por:

```python
# Inicializar tabla TokenBlacklist en DB al arrancar
@app.on_event("startup")
def startup():
    print("[*] Iniciando app...")
    init_blacklist()
    print("[OK] init_blacklist ejecutado")
    iniciar_scheduler()
    print("[OK] scheduler de relojes iniciado")


@app.on_event("shutdown")
def shutdown():
    detener_scheduler()
```

Y registrar el router junto a los demás, después de `app.include_router(activos.router)`:

```python
app.include_router(relojes.router)
```

- [ ] **Step 3: Verificar que compila**

Run: `py -m py_compile app/scheduler.py app/main.py`
Expected: exit 0

Nota: `main.py` no arranca hasta que exista `app/routes/relojes.py` (Task 5). Es esperado: el import falla hasta entonces. La verificación de arranque real se hace al final de Task 5.

- [ ] **Step 4: Commit**

```bash
git add app/scheduler.py app/main.py
git commit -m "feat: job de APScheduler cada 5 minutos para sincronizar relojes"
```

---

## Task 5: Endpoints de relojes y marcaciones

**Files:**
- Create: `app/routes/relojes.py`

**Interfaces:**
- Consumes: de Task 1 `relojes_configurados`, `buscar_usuario`, `ISAPIError`; de Task 2 `ensure_tables`, `estado_relojes`, `marcaciones_de`; de Task 3 `sincronizar_todos`, `DIAS_CARGA_INICIAL`
- Produces: router con prefix `/relojes` y el endpoint `GET /marcaciones/{employee_id}`

- [ ] **Step 1: Crear el router**

Crear `app/routes/relojes.py`:

```python
"""
Router de relojes biometricos: estado de sincronizacion, sync manual, carga
inicial y consulta de marcaciones.

Todas las operaciones contra los equipos son de solo lectura (ver la allowlist
en app/services/isapi_client.py).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_middleware import (
    ROLE_ADMIN, get_current_user, require_admin, require_any_auth,
)
from app.database.database import SessionLocal
from app.database.marcaciones import (
    ensure_tables, estado_relojes, marcaciones_de,
)
from app.services.isapi_client import (
    ISAPIError, buscar_usuario, relojes_configurados,
)
from app.services.reloj_sync import DIAS_CARGA_INICIAL, sincronizar_todos

router = APIRouter(tags=["Relojes biometricos"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/relojes/estado", dependencies=[Depends(require_admin)])
def get_estado(db: Session = Depends(get_db)):
    ensure_tables(db)
    return {"configurados": relojes_configurados(), "relojes": estado_relojes(db)}


@router.post("/relojes/sync", dependencies=[Depends(require_admin)])
def post_sync(db: Session = Depends(get_db)):
    """Sincronizacion manual de la ventana normal."""
    return {"resultados": sincronizar_todos(db)}


@router.post("/relojes/carga-inicial", dependencies=[Depends(require_admin)])
def post_carga_inicial(db: Session = Depends(get_db)):
    """
    Trae el ultimo mes. Idempotente por la unicidad (relojIp, serialNo):
    repetirla no duplica marcaciones.
    """
    hasta = datetime.now()
    desde = hasta - timedelta(days=DIAS_CARGA_INICIAL)
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resultados": sincronizar_todos(db, desde=desde, hasta=hasta),
    }


@router.get("/relojes/usuario/{biometrico_id}", dependencies=[Depends(require_admin)])
def get_usuario_reloj(biometrico_id: str):
    """
    Nombre que tienen los relojes cargado para ese employeeNo. Lo usa el perfil
    para que RRHH confirme el ID antes de guardarlo.
    """
    encontrados = []
    errores = []
    for ip in relojes_configurados():
        try:
            u = buscar_usuario(ip, biometrico_id)
            if u:
                encontrados.append({"relojIp": ip, "nombre": u.get("name")})
        except ISAPIError as e:
            errores.append({"relojIp": ip, "error": str(e)})

    return {
        "biometricoId": biometrico_id,
        "encontrado": len(encontrados) > 0,
        "nombre": encontrados[0]["nombre"] if encontrados else None,
        "relojes": encontrados,
        "errores": errores,
    }


@router.get("/marcaciones/{employee_id}", dependencies=[Depends(require_any_auth)])
def get_marcaciones(employee_id: int, desde: str | None = None, hasta: str | None = None,
                    db: Session = Depends(get_db),
                    current_user: dict = Depends(get_current_user)):
    """
    Marcaciones de un empleado. Un ROLE_USER accede solo a las propias.
    """
    if current_user["roleId"] != ROLE_ADMIN and current_user.get("employeeId") != employee_id:
        raise HTTPException(status_code=403, detail="No tenes permiso para ver estas marcaciones")

    ensure_tables(db)
    fila = db.execute(text(
        "SELECT biometricoId FROM Employee WHERE id = :id"
    ), {"id": employee_id}).mappings().first()
    if not fila:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    if not fila["biometricoId"]:
        return {"biometricoId": None, "marcaciones": []}

    hasta_dt = datetime.fromisoformat(hasta) if hasta else datetime.now()
    desde_dt = datetime.fromisoformat(desde) if desde else hasta_dt - timedelta(days=30)

    return {
        "biometricoId": fila["biometricoId"],
        "desde": desde_dt.isoformat(),
        "hasta": hasta_dt.isoformat(),
        "marcaciones": marcaciones_de(db, fila["biometricoId"], desde_dt, hasta_dt),
    }
```

Nota: `GET /marcaciones/{employee_id}` consulta `Employee.biometricoId`, columna que crea Task 6. El endpoint no se puede probar hasta que esa tarea esté hecha.

- [ ] **Step 2: Verificar que compila**

Run: `py -m py_compile app/routes/relojes.py app/main.py`
Expected: exit 0

- [ ] **Step 3: Verificar que la app arranca y expone las rutas**

Run: `py -c "from dotenv import load_dotenv; load_dotenv(); from app.main import app; print([r.path for r in app.routes if 'reloj' in r.path or 'marcacion' in r.path])"`
Expected: las 5 rutas — `/relojes/estado`, `/relojes/sync`, `/relojes/carga-inicial`, `/relojes/usuario/{biometrico_id}`, `/marcaciones/{employee_id}`

- [ ] **Step 4: Commit**

```bash
git add app/routes/relojes.py
git commit -m "feat: endpoints de estado, sync, carga inicial y marcaciones"
```

---

## Task 6: Columna Employee.biometricoId

**Files:**
- Modify: `app/database/marcaciones.py`
- Modify: `app/routes/employee.py:31` (SELECT), `app/routes/employee.py:386` (dict de respuesta), `app/routes/employee.py:605` (update)

**Interfaces:**
- Consumes: de Task 2 el módulo `marcaciones`
- Produces:
  - `ensure_columna_biometrico(db: Session) -> None` en `app/database/marcaciones.py`
  - `GET /employee/{id}` devuelve `biometricoId: str | None`
  - `PUT /employee/{id}` acepta `biometricoId` en el body

- [ ] **Step 1: Agregar el DDL de la columna**

En `app/database/marcaciones.py`, agregar después de `CREATE_RELOJSYNC_SQL`:

```python
ALTER_EMPLOYEE_BIOMETRICO_SQL = """
IF COL_LENGTH('Employee','biometricoId') IS NULL
ALTER TABLE Employee ADD biometricoId NVARCHAR(50) NULL;
"""

# Indice filtrado: impide que dos empleados compartan el mismo ID del reloj
# (seria un error silencioso: dos personas viendo las mismas marcaciones),
# pero admite varios NULL para los que todavia no estan vinculados.
CREATE_UX_BIOMETRICO_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Employee_biometricoId')
CREATE UNIQUE INDEX UX_Employee_biometricoId ON Employee (biometricoId)
WHERE biometricoId IS NOT NULL;
"""
```

Y agregar la función, después de `ensure_tables`:

```python
def ensure_columna_biometrico(db: Session) -> None:
    """DDL idempotente de Employee.biometricoId. Cada batch con su commit."""
    db.execute(text(ALTER_EMPLOYEE_BIOMETRICO_SQL))
    db.commit()
    db.execute(text(CREATE_UX_BIOMETRICO_SQL))
    db.commit()
```

Extender `ensure_tables` para que la llame, agregando al final de su cuerpo:

```python
    ensure_columna_biometrico(db)
```

- [ ] **Step 2: Exponer la columna en el GET del empleado**

En `app/routes/employee.py`, en el SELECT (después de `e.dni,` en la línea 31) agregar:

```python
            e.biometricoId,
```

En el dict de respuesta (después de `"dni": result["dni"],` en la línea 386) agregar:

```python
        "biometricoId": result["biometricoId"],
```

- [ ] **Step 3: Aceptar la columna en el PUT**

En `app/routes/employee.py`, dentro de `update_employee` (línea 605), agregar antes del commit final:

```python
    # ID del reloj biometrico: cadena vacia se guarda como NULL (desvincula).
    if "biometricoId" in data:
        crudo = data.get("biometricoId")
        nuevo = str(crudo).strip() if crudo not in (None, "") else None

        if nuevo is not None:
            duplicado = db.execute(text("""
                SELECT id, name FROM Employee
                WHERE biometricoId = :bio AND id <> :id
            """), {"bio": nuevo, "id": employee_id}).mappings().first()
            if duplicado:
                raise HTTPException(
                    status_code=400,
                    detail=f"El ID de reloj {nuevo} ya esta asignado a {duplicado['name']}",
                )

        db.execute(text("UPDATE Employee SET biometricoId = :bio WHERE id = :id"),
                   {"bio": nuevo, "id": employee_id})
```

Verificar que `HTTPException` y `text` ya estén importados en el archivo; si no, agregarlos.

- [ ] **Step 4: Verificar que compila**

Run: `py -m py_compile app/database/marcaciones.py app/routes/employee.py`
Expected: exit 0

- [ ] **Step 5: Verificar el DDL y el vínculo contra la base real**

Correr un script temporal:

```python
import sys, os
sys.path.insert(0, r"C:\Users\Emiliano\Documents\Backend_RRHH")
os.chdir(r"C:\Users\Emiliano\Documents\Backend_RRHH")
from dotenv import load_dotenv; load_dotenv()
from app.database.database import SessionLocal
from app.database.marcaciones import ensure_tables
from sqlalchemy import text

db = SessionLocal()
ensure_tables(db)
ensure_tables(db)  # idempotente

# Vincular los 5 empleados de prueba a los employeeNo 50-55 del reloj
ids = [r["id"] for r in db.execute(text("SELECT id FROM Employee ORDER BY id")).mappings().all()]
for i, emp_id in enumerate(ids):
    db.execute(text("UPDATE Employee SET biometricoId = :b WHERE id = :i"),
               {"b": str(50 + i), "i": emp_id})
db.commit()
print([dict(r) for r in db.execute(text(
    "SELECT id, name, biometricoId FROM Employee ORDER BY id")).mappings().all()])

# El indice unico debe rechazar un duplicado
try:
    db.execute(text("UPDATE Employee SET biometricoId = '50' WHERE id = :i"), {"i": ids[1]})
    db.commit()
    print("FALLO: el indice unico no impidio el duplicado")
except Exception:
    db.rollback()
    print("OK: el indice unico rechazo el duplicado")
```

Expected: los 5 empleados con `biometricoId` 50-54, y `OK: el indice unico rechazo el duplicado`.

- [ ] **Step 6: Commit**

```bash
git add app/database/marcaciones.py app/routes/employee.py
git commit -m "feat: columna Employee.biometricoId con indice unico filtrado y edicion via PUT"
```

---

## Task 7: Frontend — campo de ID del reloj en el perfil

**Files:**
- Modify: `src/app/Interfas/Interfaces.ts` (repo RRHH)
- Modify: `src/app/Componentes/TablaOperador/DetailTables.tsx` (repo RRHH)

**Interfaces:**
- Consumes: de Task 5 `GET /relojes/usuario/{biometricoId}`; de Task 6 `biometricoId` en el GET y el PUT de empleado
- Produces: campo editable en la sección `detallesAdicionales` de `ProfileTab`

Contexto del archivo: `ProfileTab` (línea 69) ya es editable. Tiene `editingSection` de tipo `ProfileSection = 'condicionLaboral' | 'detallesAdicionales'` (línea 46), `buildFormData(employee)`, `handleEdit`, `handleSave`, y un `Toast` en `toast.current`. El campo nuevo se agrega a `detallesAdicionales`.

- [ ] **Step 1: Agregar el campo a la interface**

En `src/app/Interfas/Interfaces.ts`, en la interface `Employee`, agregar después de `dni`:

```typescript
  biometricoId: string | null;
```

- [ ] **Step 2: Agregar el campo al formulario**

En `DetailTables.tsx`, en `buildFormData` agregar al final del objeto:

```typescript
  biometricoId: employee.biometricoId ?? ''
```

- [ ] **Step 3: Agregar el estado de confirmación**

En `ProfileTab`, después de `const [originalFormData, setOriginalFormData] = useState<typeof formData | null>(null);`:

```typescript
  const [nombreEnReloj, setNombreEnReloj] = useState<string | null>(null);
  const [verificandoReloj, setVerificandoReloj] = useState(false);

  // Confirmacion por nombre: al escribir el ID, consulta que nombre tienen los
  // relojes cargado para ese numero, para que un typo (51 en vez de 50) quede a
  // la vista antes de guardar. Es una lectura, no modifica el equipo.
  const verificarIdReloj = async (valor: string) => {
    const limpio = valor.trim();
    if (!limpio) {
      setNombreEnReloj(null);
      return;
    }
    setVerificandoReloj(true);
    try {
      const r = await apiClient.get<{ encontrado: boolean; nombre: string | null }>(
        `/relojes/usuario/${encodeURIComponent(limpio)}`
      );
      setNombreEnReloj(r.encontrado ? r.nombre : null);
    } catch {
      setNombreEnReloj(null);
    } finally {
      setVerificandoReloj(false);
    }
  };
```

`apiClient` ya está importado en la línea 16 del archivo (`import { apiClient } from '../../util/apiClient';`), no hace falta agregarlo.

- [ ] **Step 4: Enviar el campo al guardar**

En `handleSave`, agregar a las llamadas en paralelo del `Promise.all`:

```typescript
      await Promise.all([
        updateCondicionLaboral(employee.id, condicionLaboralData),
        updateHorario(employee.id, horarioData),
        apiClient.put(`/employee/${employee.id}`, { biometricoId: formData.biometricoId || null })
      ]);
```

- [ ] **Step 5: Renderizar el campo**

Dentro del bloque de la sección `detallesAdicionales`, agregar:

```tsx
<div>
  <label className="block text-sm font-medium text-muted-foreground mb-1">
    ID de reloj biométrico
  </label>
  {editingSection === 'detallesAdicionales' ? (
    <>
      <input
        type="text"
        inputMode="numeric"
        value={formData.biometricoId}
        onChange={(e) => setFormData({ ...formData, biometricoId: e.target.value })}
        onBlur={(e) => verificarIdReloj(e.target.value)}
        placeholder="Ej: 50"
        className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm w-full"
      />
      {verificandoReloj && (
        <p className="text-xs text-muted-foreground mt-1">Verificando en el reloj…</p>
      )}
      {!verificandoReloj && nombreEnReloj && (
        <p className="text-xs text-muted-foreground mt-1">
          En el reloj: <span className="font-medium text-foreground">{nombreEnReloj}</span>
        </p>
      )}
      {!verificandoReloj && nombreEnReloj === null && formData.biometricoId.trim() !== '' && (
        <p className="text-xs text-error mt-1">
          Ese ID no existe en ningún reloj
        </p>
      )}
    </>
  ) : (
    <p className="text-foreground">{employee.biometricoId ?? '—'}</p>
  )}
</div>
```

- [ ] **Step 6: Verificar que compila**

Run (en `C:\Users\Emiliano\Documents\RRHH`): `npx tsc --noEmit`
Expected: sin errores nuevos. Son preexistentes y aceptables los de `Estadisticas`, `TestConfig`, `UiRRHH`, `useSkillManagement`, `Constants.ts`.

- [ ] **Step 7: Commit**

```bash
git add src/app/Interfas/Interfaces.ts src/app/Componentes/TablaOperador/DetailTables.tsx
git commit -m "feat: campo de ID de reloj biometrico en el perfil con confirmacion por nombre"
```

---

## Task 8: Verificación end-to-end

**Files:** ninguno (solo verificación)

**Interfaces:**
- Consumes: todo lo anterior

- [ ] **Step 1: Correr la suite completa**

Run: `py -m pytest tests/ -v`
Expected: PASS — 16 tests, 0 fallos

- [ ] **Step 2: Verificar la carga inicial del último mes**

Correr un script temporal que ejercite el camino real:

```python
import sys, os
sys.path.insert(0, r"C:\Users\Emiliano\Documents\Backend_RRHH")
os.chdir(r"C:\Users\Emiliano\Documents\Backend_RRHH")
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timedelta
from app.database.database import SessionLocal
from app.services.reloj_sync import sincronizar_todos
from sqlalchemy import text

db = SessionLocal()
hasta = datetime.now()
desde = hasta - timedelta(days=30)
print("Primera corrida:", sincronizar_todos(db, desde=desde, hasta=hasta))

total = db.execute(text("SELECT COUNT(*) c FROM Marcacion")).mappings().first()["c"]
print("Marcaciones almacenadas:", total)

# Idempotencia: repetir la misma ventana no debe insertar nada nuevo
print("Segunda corrida:", sincronizar_todos(db, desde=desde, hasta=hasta))
total2 = db.execute(text("SELECT COUNT(*) c FROM Marcacion")).mappings().first()["c"]
print("Marcaciones despues de repetir:", total2)
assert total == total2, "FALLO: la segunda corrida duplico marcaciones"
print("OK: la carga inicial es idempotente")
```

Expected: ~5.627 marcaciones en total (4.055 del `.24` + 1.572 del `.25`), y la segunda corrida con `insertados: 0` en ambos equipos y el mismo total.

- [ ] **Step 3: Verificar el caso de referencia de la spec**

```python
import sys, os
sys.path.insert(0, r"C:\Users\Emiliano\Documents\Backend_RRHH")
os.chdir(r"C:\Users\Emiliano\Documents\Backend_RRHH")
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime
from app.database.database import SessionLocal
from app.database.marcaciones import marcaciones_de

db = SessionLocal()
filas = marcaciones_de(db, "50", datetime(2026, 7, 28), datetime(2026, 7, 28, 23, 59, 59))
for f in filas:
    print(f["fechaHora"], f["relojIp"], f["nombreReloj"])
```

Expected: exactamente 2 filas del `10.25.2.24` — `06:08:29` y `13:02:22`, nombre `Zalazar Beatriz`. Es el caso verificado en la spec.

- [ ] **Step 4: Verificar que solo se leyó, nunca se escribió**

```python
import sys, os
sys.path.insert(0, r"C:\Users\Emiliano\Documents\Backend_RRHH")
os.chdir(r"C:\Users\Emiliano\Documents\Backend_RRHH")
from app.services.isapi_client import pedir, ISAPINotAllowed, ALLOWLIST

print("Allowlist:", sorted(ALLOWLIST))
assert len(ALLOWLIST) == 3

for metodo, path in [
    ("PUT", "/ISAPI/AccessControl/UserInfo/Modify"),
    ("POST", "/ISAPI/AccessControl/UserInfo/Delete"),
    ("PUT", "/ISAPI/AccessControl/RemoteControl/door/1"),
    ("PUT", "/ISAPI/System/time"),
]:
    try:
        pedir(metodo, "10.25.2.24", path, {})
        print(f"FALLO: {metodo} {path} no fue rechazado")
    except ISAPINotAllowed:
        print(f"OK: rechazado {metodo} {path}")
```

Expected: los 4 rechazados, ninguna llamada saliendo a la red.

- [ ] **Step 5: Verificar el scheduler en el arranque real**

Arrancar el backend y confirmar en el log:

```bash
py -m uvicorn app.main:app
```

Expected: `[OK] scheduler de relojes iniciado`, y a los 5 minutos una línea `Sync 10.25.2.x: N marcaciones nuevas` o ninguna si no hubo marcaciones en la ventana. No debe aparecer traceback.

- [ ] **Step 6: Verificar el flujo del perfil en el navegador**

Con backend y frontend levantados: abrir el detalle de un empleado → pestaña Perfil → editar "Detalles adicionales" → escribir `50` → salir del campo.

Expected: aparece `En el reloj: Zalazar Beatriz`. Escribir `999999` debe mostrar `Ese ID no existe en ningún reloj`. Guardar con `50` persiste; reabrir el perfil lo muestra. Intentar asignar el mismo `50` a otro empleado devuelve 400 con el nombre del que ya lo tiene.

- [ ] **Step 7: Commit final si hubo ajustes**

```bash
git add -A
git commit -m "test: verificacion end-to-end del conector de relojes biometricos"
```

---

## Notas para el subsistema 3

Datos ya confirmados que el motor de asistencia va a necesitar, para no volver a investigarlos:

- La **primera marcación del día es la entrada y la última es la salida**; el reloj no lo etiqueta.
- Cada persona usa **un equipo u otro**, no los dos: hay que unificar por `biometricoId` sin asumir el `relojIp`.
- `Horario.horaInicio` / `horaFin` son **FLOAT** (`7.0` = 07:00, `13.0` = 13:00) y **no tienen día de la semana**: qué días cuentan como laborables es una decisión pendiente de definir.
- `Employee.horas` es el campo destino del balance y hoy está en `NULL` para todos.
- Queda sin definir la semántica exacta de la tolerancia de 15 minutos: si el tiempo dentro de la tolerancia afecta el balance o solo cuenta para el contador de abuso, y si al excederla se descuenta el exceso o el total.
